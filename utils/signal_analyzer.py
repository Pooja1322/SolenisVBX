import numpy as np
import json
from scipy.fft import rfft, rfftfreq
from scipy.signal.windows import hann
import math
from typing import List, Tuple

# Constants used for signal processing parameters
DEFAULT_SAMPLE_RATE = 60000
DEFAULT_FFT_SIZE = 4096
DEFAULT_MAX_FREQ = 27000
DEFAULT_OUT_POINTS = 512

class SignalAnalyzer:
    """
    A class to perform signal processing analysis, including FFT and RMS computation.
    It encapsulates the configuration parameters for these calculations.
    """
    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        fft_size: int = DEFAULT_FFT_SIZE,
        max_freq: int = DEFAULT_MAX_FREQ,
        out_points: int = DEFAULT_OUT_POINTS
    ):
        """
        Initializes the SignalAnalyzer with key parameters.

        :param sample_rate: The rate at which the signal was sampled (Hz).
        :param fft_size: The number of points used for the FFT calculation.
        :param max_freq: The maximum frequency to include in the spectrum (Hz).
        :param out_points: The number of points to downsample the final spectrum to.
        """
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.max_freq = max_freq
        self.out_points = out_points

    def compute_rms(self, signal: np.ndarray) -> float:
        """
        Computes the Root Mean Square (RMS) value of a given signal.

        :param signal: A 1D NumPy array representing the signal.
        :return: The RMS value as a float.
        """
        signal = np.asarray(signal)
        if signal.size == 0:
            return 0.0
        # RMS = sqrt(mean(signal^2))
        return float(np.sqrt(np.mean(np.square(signal))))

    def compute_fft_json(
        self,
        signal: np.ndarray,
        sample_rate: int = None,
        fft_size: int = None,
        max_freq: int = None,
        out_points: int = None
    ) -> str:
        """
        Compute one-sided FFT, filter up to max_freq, downsample to out_points,
        and return JSON string list [[freq, amplitude], ...].

        Parameters can be overridden via arguments or use instance defaults.
        """
        # Use instance defaults if parameters are not provided
        sample_rate = sample_rate if sample_rate is not None else self.sample_rate
        fft_size = fft_size if fft_size is not None else self.fft_size
        max_freq = max_freq if max_freq is not None else self.max_freq
        out_points = out_points if out_points is not None else self.out_points

        signal = np.asarray(signal)
        if signal.size == 0:
            return "[]"

        # 1. Prepare signal: Ensure signal length == fft_size
        if signal.size != fft_size:
            if signal.size > fft_size:
                s = signal[:fft_size]
            else:
                s = np.zeros(fft_size)
                s[: signal.size] = signal
        else:
            s = signal

        # 2. Apply Hann Window and perform FFT
        windowed = s * hann(len(s))
        yf = rfft(windowed)
        xf = rfftfreq(len(s), 1 / sample_rate) # Frequency bins
        mag = (2.0 / len(s)) * np.abs(yf)    # Calculate magnitude

        # 3. Filter Frequencies
        # Find the index corresponding to max_freq
        max_index = np.searchsorted(xf, max_freq)
        xf_filtered = xf[:max_index]
        mag_filtered = mag[:max_index]

        # 4. Downsample (if necessary)
        if xf_filtered.size > out_points:
            # Create indices for downsampling
            indices = np.round(np.linspace(
                0, xf_filtered.size - 1, out_points
            )).astype(int)

            # Downsample by selecting points at the calculated indices
            xf_downsampled = xf_filtered[indices]
            mag_downsampled = mag_filtered[indices]
        else:
            xf_downsampled = xf_filtered
            mag_downsampled = mag_filtered

        # 5. Format to JSON
        data = np.column_stack((xf_downsampled, mag_downsampled)).tolist()
        return json.dumps(data)