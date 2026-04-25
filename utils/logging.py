# utils/logging.py
import logging
import sys

def get_logger(name=__name__, level=logging.INFO):
    """
    Sets up a consistent, standardized logger for all modules.
    
    Args:
        name (str): The name of the logger (usually module name).
        level (int): The minimum logging level to output.
    """
    logger = logging.getLogger(name)
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    handler = logging.StreamHandler(sys.stdout)
    # Standard format for easy readability and parsing
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    handler.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger

# Example of setting the root logger level (optional, but useful)
logging.basicConfig(level=logging.INFO)