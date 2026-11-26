"""Scale only the elapsed-time assertions in the test suite."""
import os


def timing_limit(seconds):
    setting = os.environ.get("BACKTICK_TIMING_SCALE", "1")
    try:
        multiplier = float(setting)
    except ValueError:
        multiplier = 0
    if not 0 < multiplier <= 10:
        raise ValueError("BACKTICK_TIMING_SCALE must be a finite positive number no greater than 10")
    return seconds * multiplier
