"""
preprocessor.py
Save to: python/preprocessor.py

CSI signal processing pipeline.

Provides both:
  - Batch mode:     load a CSV file, process all packets, return results
  - Streaming mode: push one packet at a time; get filtered output + motion state

Pipeline (in order):
  1. Subcarrier selection     — remove DC bin and noisy edge subcarriers
  2. Hampel filter            — spike / impulse outlier removal
  3. Butterworth low-pass     — smooth ADC noise, preserve motion band (0.1-3 Hz)
  4. Normalisation            — zero-mean, unit variance per subcarrier
  5. Variance computation     — sliding window mean variance → motion indicator
  6. Motion classification    — STATIC / MOTION based on variance threshold

Run as a script for a self-test without hardware:
    python3 preprocessor.py
"""

import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass, field
from collections import deque
from pathlib import Path
from typing import Optional
from scipy.signal import butter, filtfilt

log = logging.getLogger("csi.preprocessor")


# ===========================================================================
"""Compatibility shim: re-export backend preprocessing.

This module preserves the original top-level import path and re-exports
the contents of `backend.preprocessing`. Existing scripts import from
`preprocessor` and will continue to work unchanged.
"""

from .backend.preprocessing import *
    Calibration workflow:
