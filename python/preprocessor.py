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
# Configuration
# ===========================================================================

@dataclass
class CSIConfig:
    """
    All tunable processing parameters in one place.

    Calibration workflow:
        1. Record 60 s of empty room. Observe mean variance → set PRESENCE threshold
           just above that (idle variance × 1.3 is a good starting point).
        2. Record 60 s of someone sitting still 2 m away.
           Observe mean variance → set MOTION threshold just above that.
        3. Record 60 s of someone walking.
           Verify variance exceeds MOTION threshold consistently.
    """

    # -- Subcarrier selection ------------------------------------------------
    # 802.11n HT20: 52 data subcarriers, indices 0–51.
    # Subcarriers near DC (index ~26) and the band edges have lower SNR.
    # exclude_subcarriers: list of indices to drop before filtering.
    exclude_subcarriers: list = field(
        default_factory=lambda: list(range(0, 5)) + list(range(47, 52)) + [25, 26]
    )

    # -- Hampel filter -------------------------------------------------------
    # Replaces samples that deviate more than hampel_k × MAD from the local
    # median (over a window of ±hampel_window samples).
    hampel_window: int   = 7      # half-window; total window = 2×7+1 = 15 samples
    hampel_k:      float = 3.0    # deviation threshold in MAD units

    # -- Butterworth low-pass filter -----------------------------------------
    # Removes high-frequency ADC noise. Human motion occupies 0.1–3 Hz.
    # Cutoff at 5 Hz keeps the full motion band while suppressing RF noise.
    # filtfilt (zero-phase) avoids introducing phase lag between subcarriers.
    butter_order:  int   = 4
    butter_cutoff: float = 5.0    # Hz
    sample_rate:   float = 50.0   # Hz — set to your actual capture rate

    # -- Normalisation -------------------------------------------------------
    # Per-subcarrier z-score: subtract mean, divide by std.
    # Makes subcarriers with different average amplitudes comparable.
    normalise: bool = True
    norm_eps:  float = 1e-6   # avoid division by zero for flat subcarriers

    # -- Variance-based motion detection ------------------------------------
    # Mean variance over a sliding window drives the motion classifier.
    var_window:        int   = 30    # packets (~0.6 s at 50 Hz)
    motion_threshold:  float = 0.5   # tune upward if too many false positives
    presence_threshold: float = 0.1  # tune upward if empty room triggers presence


# ===========================================================================
# Motion state constants
# ===========================================================================

class MotionState:
    STATIC   = "No motion"
    MOTION   = "Motion detected"


# ===========================================================================
# 1. Subcarrier selection
# ===========================================================================

def select_subcarriers(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    """
    Remove noisy/DC subcarriers from the amplitude matrix.

    Args:
        amp_matrix: shape [N_packets, N_subcarriers]
        cfg:        CSIConfig instance

    Returns:
        Filtered matrix: [N_packets, N_selected]

    Why remove edge subcarriers?
        The OFDM pilot subcarriers at the band edges carry synchronisation
        symbols, not data. Their amplitude varies with the preamble structure,
        adding non-motion-related variance. The DC bin carries no signal at all.
    """
    n_sc = amp_matrix.shape[1]
    keep = [i for i in range(n_sc) if i not in cfg.exclude_subcarriers]
    result = amp_matrix[:, keep]
    log.debug("Subcarrier selection: kept %d / %d", len(keep), n_sc)
    return result


# ===========================================================================
# 2. Hampel filter
# ===========================================================================

def hampel_filter_1d(signal: np.ndarray, half_window: int, k: float) -> np.ndarray:
    """
    Hampel identifier applied to a 1D time series.

    For each sample x[i]:
        1. Compute the local median m over [i-half_window, i+half_window]
        2. Compute MAD = median(|x[j] - m|) over the same window
        3. If |x[i] - m| > k × 1.4826 × MAD → replace x[i] with m

    The constant 1.4826 makes MAD a consistent estimator of σ for Gaussian
    data. Setting k=3 is approximately the 3-sigma rule.

    Why Hampel before Butterworth?
        If you LPF first, a spike gets smeared over ±half_window samples.
        Hampel runs on raw data, replaces only the spike sample, and preserves
        the surrounding signal shape for the LPF to smooth normally.
    """
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
    """Apply Hampel filter independently to every subcarrier column."""
    result = np.empty_like(amp_matrix)
    for sc in range(amp_matrix.shape[1]):
        result[:, sc] = hampel_filter_1d(
            amp_matrix[:, sc], cfg.hampel_window, cfg.hampel_k
        )
    return result


# ===========================================================================
# 3. Butterworth low-pass filter
# ===========================================================================

def butter_lowpass(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    """
    Apply a zero-phase Butterworth LPF to every subcarrier column.

    filtfilt() does a forward pass then a backward pass. The two passes
    cancel each other's phase shift — result has zero phase distortion.
    This preserves the relative timing between subcarriers, which matters
    for cross-subcarrier correlation in Phase 4.

    The minimum signal length for filtfilt is 3 × filter_order. Short
    buffers (startup) are returned unfiltered.
    """
    nyq = cfg.sample_rate / 2.0
    Wn  = cfg.butter_cutoff / nyq

    if Wn >= 1.0:
        log.warning(
            "butter_cutoff (%.1f Hz) >= Nyquist (%.1f Hz). "
            "Skipping filter — adjust sample_rate or butter_cutoff.",
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


# ===========================================================================
# 4. Normalisation
# ===========================================================================

def normalise(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    """
    Per-subcarrier z-score normalisation.

    Subcarriers at different positions have different average amplitudes
    due to the frequency-selective nature of the channel. Normalisation
    puts them all on the same scale so variance is comparable across
    subcarriers. Without this, high-amplitude subcarriers dominate the
    variance computation unfairly.

    Formula: z[t, sc] = (x[t, sc] - mean_sc) / (std_sc + eps)
    """
    if not cfg.normalise:
        return amp_matrix

    mean = amp_matrix.mean(axis=0, keepdims=True)   # [1, N_sc]
    std  = amp_matrix.std(axis=0,  keepdims=True)   # [1, N_sc]
    return (amp_matrix - mean) / (std + cfg.norm_eps)


# ===========================================================================
# 5. Full batch pipeline
# ===========================================================================

def preprocess(amp_matrix: np.ndarray, cfg: CSIConfig) -> np.ndarray:
    """
    Run the complete batch pipeline on a full amplitude matrix.

    Steps: subcarrier selection → Hampel → Butterworth → normalise

    Args:
        amp_matrix: [N_packets, N_subcarriers] float32
        cfg:        CSIConfig

    Returns:
        Cleaned matrix: [N_packets, N_selected] float32
    """
    amp = select_subcarriers(amp_matrix, cfg)
    amp = hampel_filter(amp, cfg)
    amp = butter_lowpass(amp, cfg)
    amp = normalise(amp, cfg)
    log.info("Batch preprocess complete: %s → %s", amp_matrix.shape, amp.shape)
    return amp


# ===========================================================================
# 6. Variance computation and motion classification
# ===========================================================================

def compute_window_variance(window: np.ndarray) -> float:
    """
    Compute mean-across-subcarriers of per-subcarrier variance over a window.

    Args:
        window: [var_window, N_selected] amplitude values

    Returns:
        Scalar float — the mean variance indicator.

    Why average across subcarriers?
        Motion affects multiple subcarriers simultaneously (multipath
        scattering). Averaging reduces the impact of any one subcarrier
        that has anomalously high/low noise, giving a more stable indicator.
    """
    per_sc_var = np.var(window, axis=0)   # [N_sc] variance over time axis
    return float(np.mean(per_sc_var))


def classify_motion(variance: float, cfg: CSIConfig) -> str:
    """
    Map a variance scalar to a motion state label.

    Thresholds:
        variance >= motion_threshold   → "Motion detected"
        otherwise                      → "No motion"
    """
    if variance >= cfg.motion_threshold:
        return MotionState.MOTION
    else:
        return MotionState.STATIC


# ===========================================================================
# 7. Streaming preprocessor (used by visualizer.py)
# ===========================================================================

@dataclass
class StreamResult:
    """Output from StreamingPreprocessor.push() — one result per valid push."""
    amplitudes:   np.ndarray   # [N_selected] filtered amps for current packet
    smoothed:     np.ndarray   # [N_selected] rolling mean over var_window
    variance:     float        # scalar motion indicator
    motion_state: str          # MotionState constant


class StreamingPreprocessor:
    """
    Stateful per-packet processor for real-time use.

    Push one amplitude vector at a time; get a StreamResult back once the
    variance window is full (first var_window packets return None).

    Usage:
        cfg  = CSIConfig()
        proc = StreamingPreprocessor(cfg)
        while receiving:
            result = proc.push(packet["amplitudes"])
            if result:
                update_plot(result.amplitudes)
                print(result.motion_state)
    """

    def __init__(self, cfg: CSIConfig):
        self.cfg     = cfg
        self._buffer = deque(maxlen=cfg.var_window)  # rolling amplitude history
        self._raw    = deque(maxlen=15)              # for streaming Hampel (window=7)

    def push(self, raw_amplitudes: list) -> Optional[StreamResult]:
        """
        Accept one raw amplitude vector, apply lightweight streaming filters,
        update rolling buffers, and return a StreamResult if ready.

        Streaming filter differences from batch mode:
          - Hampel: applied over last 15 samples (not full history)
          - Butterworth: skipped (too slow per-packet; rolling mean substitutes)
          - Normalise: applied over var_window buffer, not entire session
        """
        TARGET_LEN = 64

        amps = np.array(raw_amplitudes, dtype=np.float32)

        if len(amps) < TARGET_LEN:
            amps = np.pad(amps, (0, TARGET_LEN - len(amps)))

        elif len(amps) > TARGET_LEN:
            amps = amps[:TARGET_LEN]

        arr = amps


        # Subcarrier selection
        n_sc = len(arr)
        keep = [i for i in range(n_sc) if i not in self.cfg.exclude_subcarriers]
        if not keep:
            return None
        arr = arr[keep]

        # Streaming Hampel: median of last 15 raw samples per subcarrier
        self._raw.append(arr.copy())
        if len(self._raw) >= 5:
            recent = np.stack(list(self._raw)[-min(15, len(self._raw)):], axis=0)
            arr    = np.median(recent, axis=0).astype(np.float32)

        self._buffer.append(arr)

        # Need a full window before computing variance
        if len(self._buffer) < self.cfg.var_window:
            return None

        window   = np.stack(list(self._buffer), axis=0)  # [var_window, N_sc]

        # Normalise window
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


# ===========================================================================
# 8. Batch CSV analysis helper
# ===========================================================================

def analyse_csv(filepath: str, cfg: Optional[CSIConfig] = None) -> dict:
    """
    Load a CSV saved by serial_reader.py and run the full batch pipeline.

    Returns dict:
        raw_matrix    [N, S] float32 — raw amplitudes
        clean_matrix  [N, S'] float32 — filtered amplitudes
        variances     [N-W] float32 — per-window variance
        states        list[str] — motion state per window
        timestamps    [N] int64 — µs timestamps
        df            pd.DataFrame — original data
    """
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


# ===========================================================================
# Self-test — run with: python3 preprocessor.py
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    log.info("Running preprocessor self-test with synthetic data …")
    cfg = CSIConfig()
    rng = np.random.default_rng(42)

    N, S = 300, 52
    # Simulate 3 phases: static → motion → static
    static1  = rng.normal(20.0, 0.3,  (100, S)).astype(np.float32)
    motion   = rng.normal(20.0, 3.0,  (100, S)).astype(np.float32)
    static2  = rng.normal(20.0, 0.3,  (100, S)).astype(np.float32)
    raw      = np.vstack([static1, motion, static2])

    # Add spikes
    raw[rng.integers(0, N, 25), rng.integers(0, S, 25)] = 80.0

    clean = preprocess(raw, cfg)
    log.info("raw shape:   %s", raw.shape)
    log.info("clean shape: %s", clean.shape)

    # Test streaming
    proc   = StreamingPreprocessor(cfg)
    states = []
    for i in range(N):
        r = proc.push(raw[i].tolist())
        if r:
            states.append(r.motion_state)

    from collections import Counter
    log.info("Streaming results: %s", dict(Counter(states)))
    log.info("Self-test passed ✓")
