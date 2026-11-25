"""Scale only the elapsed-time assertions in the test suite."""
import math
import os


def timing_limit(seconds):
    setting = os.environ.get("BACKTICK_TIMING_SCALE", "1")
    try:
        multiplier = float(setting)
    except ValueError:
        multiplier = 0
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("BACKTICK_TIMING_SCALE must be a finite positive number")
    return seconds * multiplier
