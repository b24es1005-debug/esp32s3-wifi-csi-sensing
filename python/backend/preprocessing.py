"""
backend/preprocessing.py

Copy of original preprocessor moved into backend package. Kept unchanged
so existing behavior is preserved. Top-level `python/preprocessor.py` will
re-export these symbols to maintain compatibility with existing scripts.
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


# ==========================================================================
# Configuration
# ==========================================================================

@dataclass
class CSIConfig:
    exclude_subcarriers: list = field(
        default_factory=lambda: list(range(0, 5)) + list(range(47, 52)) + [25, 26]
    )
    hampel_window: int   = 7
    hampel_k:      float = 3.0
    butter_order:  int   = 4
    butter_cutoff: float = 5.0
    sample_rate:   float = 50.0
    normalise: bool = True
    norm_eps:  float = 1e-6
    var_window:        int   = 30
    motion_threshold:  float = 0.5
    presence_threshold: float = 0.1


class MotionState:
    STATIC   = "No motion"
    MOTION   = "Motion detected"


def select_subcarriers(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    n_sc = amp_matrix.shape[1]
    keep = [i for i in range(n_sc) if i not in cfg.exclude_subcarriers]
    result = amp_matrix[:, keep]
    log.debug("Subcarrier selection: kept %d / %d", len(keep), n_sc)
    return result


def hampel_filter_1d(signal: np.ndarray, half_window: int, k: float) -> np.ndarray:
    n      = len(signal)
    result = signal.copy()
    for i in range(n):
        lo = max(0, i - half_window)
        hi = min(n, i + half_window + 1)
        nb = signal[lo:hi]
        m   = np.median(nb)
        mad = np.median(np.abs(nb - m))
        if mad > 0 and np.abs(signal[i] - m) > k * 1.4826 * mad:
            result[i] = m
    return result


def hampel_filter(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    result = np.empty_like(amp_matrix)
    for sc in range(amp_matrix.shape[1]):
        result[:, sc] = hampel_filter_1d(
            amp_matrix[:, sc], cfg.hampel_window, cfg.hampel_k
        )
    return result


def butter_lowpass(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    nyq = cfg.sample_rate / 2.0
    Wn  = cfg.butter_cutoff / nyq
    if Wn >= 1.0:
        log.warning(
            "butter_cutoff (%.1f Hz) >= Nyquist (%.1f Hz). Skipping filter.",
            cfg.butter_cutoff, nyq,
        )
        return amp_matrix
    b, a   = butter(cfg.butter_order, Wn, btype="low", analog=False)
    result = np.empty_like(amp_matrix)
    min_len = 3 * cfg.butter_order + 1
    for sc in range(amp_matrix.shape[1]):
        col = amp_matrix[:, sc]
        result[:, sc] = filtfilt(b, a, col) if len(col) > min_len else col
    return result


def normalise(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    if not cfg.normalise:
        return amp_matrix
    mean = amp_matrix.mean(axis=0, keepdims=True)
    std  = amp_matrix.std(axis=0,  keepdims=True)
    return (amp_matrix - mean) / (std + cfg.norm_eps)


def preprocess(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    amp = select_subcarriers(amp_matrix, cfg)
    amp = hampel_filter(amp, cfg)
    amp = butter_lowpass(amp, cfg)
    amp = normalise(amp, cfg)
    log.info("Batch preprocess complete: %s → %s", amp_matrix.shape, amp.shape)
    return amp


def compute_window_variance(window: np.ndarray) -> float:
    per_sc_var = np.var(window, axis=0)
    return float(np.mean(per_sc_var))


def classify_motion(variance: float, cfg: CSIConfig) -> str:
    if variance >= cfg.motion_threshold:
        return MotionState.MOTION
    else:
        return MotionState.STATIC


@dataclass
class StreamResult:
    amplitudes:   np.ndarray
    smoothed:     np.ndarray
    variance:     float
    motion_state: str


class StreamingPreprocessor:
    def __init__(self, cfg: CSIConfig):
        self.cfg     = cfg
        self._buffer = deque(maxlen=cfg.var_window)
        self._raw    = deque(maxlen=15)

    def push(self, raw_amplitudes: list) -> Optional[StreamResult]:
        TARGET_LEN = 64
        amps = np.array(raw_amplitudes, dtype=np.float32)
        if len(amps) < TARGET_LEN:
            amps = np.pad(amps, (0, TARGET_LEN - len(amps)))
        elif len(amps) > TARGET_LEN:
            amps = amps[:TARGET_LEN]
        arr = amps
        n_sc = len(arr)
        keep = [i for i in range(n_sc) if i not in self.cfg.exclude_subcarriers]
        if not keep:
            return None
        arr = arr[keep]
        self._raw.append(arr.copy())
        if len(self._raw) >= 5:
            recent = np.stack(list(self._raw)[-min(15, len(self._raw)):], axis=0)
            arr    = np.median(recent, axis=0).astype(np.float32)
        self._buffer.append(arr)
        if len(self._buffer) < self.cfg.var_window:
            return None
        window   = np.stack(list(self._buffer), axis=0)
        mean     = window.mean(axis=0, keepdims=True)
        std      = window.std(axis=0,  keepdims=True)
        norm_win = (window - mean) / (std + self.cfg.norm_eps)
        variance = compute_window_variance(norm_win)
        state    = classify_motion(variance, self.cfg)
        smoothed = np.mean(window, axis=0)
        return StreamResult(
            amplitudes   = arr,
            smoothed     = smoothed,
            variance     = variance,
            motion_state = state,
        )


def analyse_csv(filepath: str, cfg: Optional[CSIConfig] = None) -> dict:
    if cfg is None:
        cfg = CSIConfig()
    df  = pd.read_csv(filepath)
    amp_cols = sorted(
        [c for c in df.columns if c.startswith("amp_")],
        key=lambda c: int(c.split("_")[1]),
    )
    if not amp_cols:
        raise ValueError(f"No amplitude columns in {filepath}")
    raw_matrix = df[amp_cols].to_numpy(dtype=np.float32)
    timestamps = df["timestamp_us"].to_numpy(dtype=np.int64)
    clean      = preprocess(raw_matrix, cfg)
    w          = cfg.var_window
    variances  = []
    states     = []
    for i in range(w, len(clean)):
        var   = compute_window_variance(clean[i-w:i])
        state = classify_motion(var, cfg)
        variances.append(var)
        states.append(state)
    log.info(
        "CSV analysis: %d packets, MOTION=%d, STATIC=%d",
        len(df),
        states.count(MotionState.MOTION),
        states.count(MotionState.STATIC),
    )
    return {
        "raw_matrix":   raw_matrix,
        "clean_matrix": clean,
        "variances":    np.array(variances, dtype=np.float32),
        "states":       states,
        "timestamps":   timestamps,
        "df":           df,
    }
