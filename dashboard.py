import json
import datetime
import time
import dash
from dash import html, dcc, Input, Output, State, ALL
from influxdb_client import InfluxDBClient
from utils.common import load_influx_config, create_influx_client, create_influx_apis, safe_close_client, load_json_file
from utils.logging import get_logger

logger = get_logger("dashboard")

# ---------------- Load config ----------------
cfg = load_influx_config()
INFLUX_URL = cfg.get("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = cfg.get("INFLUX_TOKEN", "")
INFLUX_ORG = cfg.get("INFLUX_ORG", "TechMahindra")
INFLUX_BUCKET = cfg.get("INFLUX_BUCKET", "TechroomB2")

# ---------------- Influx client ----------------
client = create_influx_client(INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG)
query_api, _ = create_influx_apis(client, need_write=False)

# ---------------- Dash app ----------------
EXTERNAL_STYLESHEETS = [
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css'
]
app = dash.Dash(__name__, title="Solenis Vibration Analysis", suppress_callback_exceptions=True, external_stylesheets=EXTERNAL_STYLESHEETS)
server = app.server

# ---------------- HTML helpers ----------------
def load_src_file(name):
    try:
        with open(name, 'r',encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"File not found: {name}")
        return f"<h1>Error: File '{name}' not found.</h1>"

# ---------------- Define all charts ----------------pp.clientside_callback(
CHART_MAPPING = {
    '/chart-24h-history-rms': {'id': 'temp_vibration_24h', 'title': '24H History (Temp/Vib RMS)', 'src_file': 'temp_vibration_24h.html', 'group': 'Overview Charts', 'icon': 'fas fa-chart-line'},
    '/chart-24h-history-rpm': {'id': 'temp_rpm_24h', 'title': 'Time Domain 24H History (Temp/RPM)', 'src_file': 'timeseries_chart.html', 'group': 'Overview Charts', 'icon': 'fas fa-gauge-high'},
    '/chart-time-wave': {'id': 'time_wave_chart', 'title': 'Time Waveform (CH1)', 'src_file': 'time_chart.html', 'group': 'Overview Charts', 'icon': 'fas fa-wave-square'},
    '/chart-main-spectrum': {'id': 'main_spectrum', 'title': 'Current Spectrum (CH1)', 'src_file': 'single_spectrum.html', 'group': 'Overview Charts', 'icon': 'fas fa-chart-area'},
    '/chart-multi-spectrum': {'id': 'multi_spectrum_channels', 'title': 'Frequency Domain(All Channels)', 'src_file': 'spectrum_chart.html', 'group': 'Channel Spectrum Detail', 'icon': 'fas fa-chart-line'},
    '/chart-spec-ch1': {'id': 'spec_ch1', 'title': 'Frequency Domain 1', 'src_file': 'single_spectrum.html', 'group': 'Channel Spectrum Detail', 'icon': 'fas fa-chart-bar'},
    '/chart-spec-ch2': {'id': 'spec_ch2', 'title': 'Frequency Domain 2', 'src_file': 'single_spectrum.html', 'group': 'Channel Spectrum Detail', 'icon': 'fas fa-chart-bar'},
    '/chart-spec-ch3': {'id': 'spec_ch3', 'title': 'Frequency Domain 3', 'src_file': 'single_spectrum.html', 'group': 'Channel Spectrum Detail', 'icon': 'fas fa-chart-bar'},
    '/chart-spec-ch4': {'id': 'spec_ch4', 'title': 'Frequency Domainl 4', 'src_file': 'single_spectrum.html', 'group': 'Channel Spectrum Detail', 'icon': 'fas fa-chart-bar'}
}
DEFAULT_PATH = '/chart-24h-history-rms'
ALL_PATHS = list(CHART_MAPPING.keys())

CHART_GROUPS = {}
for path, info in CHART_MAPPING.items():
    group = info['group']
    if group not in CHART_GROUPS: CHART_GROUPS[group] = []
    CHART_GROUPS[group].append((path, info['title'], info['icon']))

SRC_FILES = {k: load_src_file(k) for k in ['time_chart.html', 'temp_vibration_24h.html', 'single_spectrum.html', 'timeseries_chart.html', 'spectrum_chart.html']}

# ---------------- Data fetching ----------------

def fetch_data_from_influx(query_api, bucket, initial_load: bool, offset: int = 0):
    data = {}
    
    # 1. Logic for Time Waveform (CH1) with Offset Navigation
    if offset == 0:
        # LIVE MODE: Pull last 10 seconds of waveform data
        q_wave = f'from(bucket: "{bucket}") |> range(start: -10s) |> filter(fn: (r) => r["_measurement"] == "waveform" and r["channel"] == "CH1") |> last()'
    else:
        # HISTORY MODE: Pull specific 60s window based on offset (e.g., -2m to -1m)
        start_time, stop_time = f"-{offset + 1}m", f"-{offset}m"
        q_wave = f'from(bucket: "{bucket}") |> range(start: {start_time}, stop: {stop_time}) |> filter(fn: (r) => r["_measurement"] == "waveform" and r["channel"] == "CH1")'

    end_time = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
    limits_config = load_json_file('limits_config.json')
    
    # Use -24h for initial data or if we need to hydrate a chart from scratch
    time_range = '-24h' if initial_load else '-1m'
    aggregate_window = '1m' if initial_load else '1s'

    try:
        # Fetch Waveform Data
        res = query_api.query(query=q_wave)
        points = []
        for table in res:
            for record in table.records:
                val = record.get_value()
                if isinstance(val, (list, str)): # Handle JSON blobs or lists
                    points = json.loads(val) if isinstance(val, str) else val
                else: # Handle individual points
                    points.append([record.get_time().timestamp() * 1000, val])
        data['time_wave_chart'] = json.dumps(points)

        # Fetch Timeseries Data (Temp, Vibration RMS, RPM)
        temp_vib_rpm_query = f"""
            from(bucket: "{bucket}")
            |> range(start: {time_range}, stop: {end_time})
            |> filter(fn: (r) => r["_measurement"] == "timeseries" and (r["_field"] == "temperature" or r["_field"] == "vibration_rms" or r["_field"] == "rpm"))
            |> group(columns: ["_field"])
            |> aggregateWindow(every: {aggregate_window}, fn: mean, createEmpty: false)
            |> yield(name: "mean")
        """
        
        if not initial_load:
            temp_vib_rpm_query = temp_vib_rpm_query.replace('|> yield(name: "mean")', '|> last()')

        result = query_api.query(query=temp_vib_rpm_query)
        temp_hist, vib_hist, rpm_hist, latest = [], [], [], {}

        for table in result:
            for record in table.records:
                ts, val, field = record.get_time().timestamp() * 1000, record.get_value(), record["_field"]
                if initial_load:
                    if field == "temperature": temp_hist.append([ts, val])
                    elif field == "vibration_rms": vib_hist.append([ts, val])
                    elif field == "rpm": rpm_hist.append([ts, val])
                else:
                    if field == "temperature": latest['temp'] = [ts, val]
                    elif field == "vibration_rms": latest['vibration'] = [ts, val]
                    elif field == "rpm": latest['rpm'] = [ts, val]

        if initial_load:
            data['temp_vibration_24h'] = json.dumps({"temp_history": temp_hist, "vibration_history": vib_hist, "limits": limits_config})
            data['temp_rpm_24h'] = json.dumps({"temp_history": temp_hist, "rpm_history": rpm_hist, "limits": limits_config})
            # Also store a "latest" format for future incremental updates
            data['latest_raw'] = latest
        else:
            data['temp_vibration_24h'] = json.dumps(latest)
            data['temp_rpm_24h'] = json.dumps(latest)
          

        # Fetch Latest Spectrum
        q_spec = f'from(bucket: "{bucket}") |> range(start: -10s) |> filter(fn: (r) => r["_measurement"] == "spectrum" and r["channel"] == "CH1") |> last()'
        res_spec = query_api.query(query=q_spec)
        queries = {
            'main_spectrum': f'from(bucket: "{bucket}") |> range(start: -10s) |> filter(fn: (r) => r["_measurement"] == "spectrum" and r["channel"] == "CH1") |> last()'
        }
        for key, q in queries.items():
            try:
                res = query_api.query(query=q)
                if res and len(res) > 0 and len(res[0].records) > 0:
                    val = res[0].records[0].get_value()
                    data[key] = val if isinstance(val, str) else json.dumps(val)
                else:
                    data[key] = json.dumps([]) # Ensure key exists so the UI doesn't break
            except Exception as e:
                logger.error(f"Error fetching {key}: {e}")
                data[key] = json.dumps([])

        if res_spec and len(res_spec) > 0 and len(res_spec[0].records) > 0:
            val = res_spec[0].records[0].get_value()
            data['main_spectrum'] = val if isinstance(val, str) else json.dumps(val) 

        # for i in range(1, 5):
    #         try:
    #            q = f'from(bucket: "{bucket}") |> range(start: -10s) |> filter(fn: (r) => r["_measurement"] == "spectrum" and r["channel"] == "CH{i}") |> last()'
    #            res = query_api.query(query=q)
    #            data[f'spec_ch{i}'] = res[0].records[0].get_value() if res and res[0].records else json.dumps([])
    #         except Exception as e:
    #             logger.error(f"Error fetching CH{i}: {e}")
    #             data[f'spec_ch{i}'] = json.dumps([])

    #     data['multi_spectrum_channels'] = json.dumps({f"ch{i}": data.get(f'spec_ch{i}', "[]") for i in range(1, 5)})

    # except Exception as e:
    #     logger.error(f"InfluxDB error: {e}")
    # return data

        for i in range(1, 5):
            q = f'from(bucket: "{bucket}") |> range(start: -10s) |> filter(fn: (r) => r["_measurement"] == "spectrum" and r["channel"] == "CH{i}") |> last()'
            res = query_api.query(query=q)
            data[f'spec_ch{i}'] = res[0].records[0].get_value() if res and res[0].records else json.dumps([])

        data['multi_spectrum_channels'] = json.dumps({f"ch{i}": data.get(f'spec_ch{i}', "[]") for i in range(1, 5)})

    except Exception as e:
        logger.error(f"InfluxDB error: {e}")
    return data

# ---------------- Layout ----------------

app.layout = html.Div(style={'backgroundColor': '#f0f2f5'}, children=[
    dcc.Store(id='data-store'),
    dcc.Store(id='current-path-store', data=DEFAULT_PATH),
    dcc.Store(id='history-offset-store', data=0),
    dcc.Store(id='initial-load-done', data=False), 

    html.Div(style={'position': 'fixed', 'top': 0, 'left': 0, 'bottom': 0, 'width': '18rem', 'padding': '1.5rem 1rem', 'backgroundColor': '#29323c', 'color': 'white', 'zIndex': 10, 'overflowY': 'auto'}, children=[
        html.H2('Solenis Monitor', style={'color': '#4CAF50', 'marginBottom': '2rem'}),
        html.Div(id='sidebar-menu-links')
    ]),
    html.Div(style={'marginLeft': '19rem', 'padding': '1rem'}, children=[
        dcc.Location(id='url', refresh=False),
        html.Div(id='page-content'),
        html.Div(id='dummy-output', style={'display': 'none'})
    ]),
    dcc.Interval(id='interval-component', interval=5000, n_intervals=0)
])

# ---------------- Callbacks ----------------

@app.callback(Output('current-path-store', 'data'), [Input('url', 'pathname')])
def update_path(path): 
    return path if path in ALL_PATHS else DEFAULT_PATH

@app.callback(Output('sidebar-menu-links', 'children'), [Input('current-path-store', 'data')])
def render_menu(path):
    menu = []
    for g, links in CHART_GROUPS.items():
        menu.append(html.H4(g, style={'color': '#b0bec5', 'fontSize': '0.75rem', 'marginTop': '1.5rem'}))
        for p, t, i in links:
            active = (p == path)
            style = {'display': 'flex', 'alignItems': 'center', 'padding': '0.75rem', 'color': '#4CAF50' if active else 'white', 'textDecoration': 'none', 'borderRadius': '8px', 'backgroundColor': 'rgba(255,255,255,0.1)' if active else 'transparent'}
            menu.append(dcc.Link([html.I(className=i, style={'marginRight': '10px'}), t], href=p, style=style))
    return menu

@app.callback(Output('page-content', 'children'), [Input('current-path-store', 'data')])
def render_content(path):
    info = CHART_MAPPING.get(path)
    if not info or not info['src_file']: return html.Div("Placeholder")
    
    timestamp = int(time.time() * 1000) # Higher precision for rapid switching
    # unique_id = f"{info['id']}_{timestamp}"
    
    return html.Div(className='p-4 bg-white rounded-xl shadow-lg', children=[
        html.H3(info['title'], className='text-2xl font-bold mb-4'),
        html.Iframe(
            id={'type': 'chart-iframe', 'index': info['id']}, 
            # key=unique_id,
            srcDoc=SRC_FILES.get(info['src_file']), 
            style={'width': '100%', 'height': '600px', 'border': 'none', 'borderRadius': '12px'}
        ),
        # This hidden signal triggers the clientside callback immediately upon page render
        html.Div(id={'type': 'refresh-signal', 'index' : f"{info['id']}_{timestamp}"}, children=str(timestamp), style={'display': 'none'})
    ])

@app.callback(
    [Output('data-store', 'data'), Output('initial-load-done', 'data')], 
    [Input('interval-component', 'n_intervals'), 
     Input('current-path-store', 'data'),
     Input('history-offset-store', 'data')],  #triggers when offset changes
    [State('initial-load-done', 'data')]
)
def update_data(n, path, offset, done): 
    # If path changes or n is 0, we do a full fetch to hydrate the new chart
    # This ensures that navigating back to Graph 1 gets the 24h history immediately
    ctx = dash.callback_context
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    is_init = (n == 0 or triggered_id == 'current-path-store' or triggered_id == 'history-offset-store')
    data = fetch_data_from_influx(query_api, INFLUX_BUCKET, is_init,offset=offset)
    return data, True

# Single Listener for messages from the Iframe
app.clientside_callback(
    """
    function(id) {
        if (!window.hasMessageListener) {
            window.addEventListener("message", (event) => {
                if (event.data.type === 'SET_OFFSET') {
                    dash_clientside.set_props('history-offset-store', {data: event.data.offset});
                }
            }, false);
            window.hasMessageListener = true;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("dummy-output", "id"),
    [Input("dummy-output", "id")]
)
app.clientside_callback(
    """
    function(data, signals) {
        if (!data) return window.dash_clientside.no_update;
        
        const sendData = () => {
            const iframes = document.querySelectorAll('iframe[id*="chart-iframe"]');
            iframes.forEach(iframe => {
                try {
                    const idStr = iframe.id;
                    const match = idStr.match(/"index":"([^"]+)"/);
                    if (match && match[1]) {
                        const chartKey = match[1];
                        if (data[chartKey] && iframe.contentWindow) {
                            // Only parse if it's a string
                            const rawData = data[chartKey];
                            const parsed = (typeof rawData === 'string') ? JSON.parse(rawData) : rawData;
                            iframe.contentWindow.postMessage(parsed, '*');
                        }
                    }
                } catch(e) { console.error("PostMessage Error:", e); }
            });
        };

        // Retry logic: Iframes might take a moment to be 'ready' for postMessage
        sendData();
        setTimeout(sendData, 100);
        setTimeout(sendData, 500); 
        
        return window.dash_clientside.no_update;
    }
    """,
    Output("dummy-output", "children"),
    [
        Input("data-store", "data"),
        Input({'type': 'refresh-signal', 'index': ALL}, 'children')
    ]
)

if __name__ == '__main__':
    app.run(debug=True)
    # app.run(debug=True, host="0.0.0.0", port=8050)