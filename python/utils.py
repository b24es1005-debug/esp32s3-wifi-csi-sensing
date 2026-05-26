"""
utils.py
Save to: python/utils.py

Shared utilities used by serial_reader.py, preprocessor.py, and visualizer.py.
Centralising these avoids duplicating validation logic across files.
"""

import re
import logging
import numpy as np
from pathlib import Path
from datetime import datetime

log = logging.getLogger("csi.utils")

# ---------------------------------------------------------------------------
# Constants — must match firmware/csi_receiver/main/wifi_csi.h
# ---------------------------------------------------------------------------

CSI_LINE_PREFIX     = "CSI"
MIN_SUBCARRIERS     = 20    # below this → corrupted or non-data frame
MAX_SUBCARRIERS     = 128   # above this → impossible on 802.11n

# RSSI physical limits
RSSI_MIN_DBM        = -100
RSSI_MAX_DBM        = 0

# Compiled regex for fast prefix check — avoids repeated string ops
_CSI_PREFIX_RE      = re.compile(r"^CSI,")


# ---------------------------------------------------------------------------
# Packet validation
# ---------------------------------------------------------------------------

def validate_csi_line(raw_line: str) -> tuple[bool, str]:
    """
    Validate a raw serial line before parsing.

    Expected format:
        CSI,<timestamp_us>,<rssi_dbm>,<num_subcarriers>,<amp0>,<amp1>,...

    Returns:
        (True, "ok")              if the line is valid
        (False, "<reason>")       if the line should be dropped

    Design note:
        We validate in order of cheapest check first (prefix, field count)
        to short-circuit early on the most common malformed inputs —
        ESP_LOGI debug lines, partial UART frames, boot messages.
    """
    line = raw_line.strip()

    # Check 1: not empty
    if not line:
        return False, "empty"

    # Check 2: correct prefix — cheapest filter
    if not _CSI_PREFIX_RE.match(line):
        return False, f"wrong prefix: {line[:20]!r}"

    # Check 3: split into fields
    parts = line.split(",")
    # Minimum: "CSI" + timestamp + rssi + num_sc + at least 1 amplitude
    if len(parts) < 5:
        return False, f"too few fields: {len(parts)}"

    # Check 4: timestamp must be a non-negative integer
    try:
        ts = int(parts[1])
        if ts < 0:
            return False, f"negative timestamp: {ts}"
    except ValueError:
        return False, f"non-integer timestamp: {parts[1]!r}"

    # Check 5: RSSI must be an integer in physical range
    try:
        rssi = int(parts[2])
        if not (RSSI_MIN_DBM <= rssi <= RSSI_MAX_DBM):
            return False, f"RSSI out of range: {rssi}"
    except ValueError:
        return False, f"non-integer RSSI: {parts[2]!r}"

    # Check 6: num_subcarriers must be integer in plausible range
    try:
        n = int(parts[3])
        if not (MIN_SUBCARRIERS <= n <= MAX_SUBCARRIERS):
            return False, f"subcarrier count out of range: {n}"
    except ValueError:
        return False, f"non-integer subcarrier count: {parts[3]!r}"

    # Check 7: amplitude count must match declared num_subcarriers
    amp_fields = parts[4:]
    if len(amp_fields) != n:
        return False, f"amplitude count mismatch: declared {n}, got {len(amp_fields)}"

    # Check 8: all amplitudes must be non-negative floats
    for idx, a in enumerate(amp_fields):
        try:
            v = float(a)
            if v < 0.0:
                return False, f"negative amplitude[{idx}] = {v}"
        except ValueError:
            return False, f"non-float amplitude[{idx}] = {a!r}"

    return True, "ok"


def parse_csi_line(raw_line: str) -> dict | None:
    """
    Parse a validated CSI line into a structured dict.

    Call validate_csi_line() first. This function trusts the input is valid
    and only wraps in try/except as a belt-and-suspenders safety net.

    Returns dict with keys:
        timestamp_us    int     microseconds since ESP32 boot
        rssi            int     dBm
        num_subcarriers int
        amplitudes      list[float]

    Returns None on unexpected parse error (should never happen after validation).
    """
    try:
        parts = raw_line.strip().split(",")
        n     = int(parts[3])
        return {
            "timestamp_us":    int(parts[1]),
            "rssi":            int(parts[2]),
            "num_subcarriers": n,
            "amplitudes": [float(a) / 100.0 for a in parts[4 : 4 + n]],
        }
    except Exception as exc:
        log.error("Unexpected parse error: %s | line: %r", exc, raw_line[:60])
        return None


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def make_csv_path(outdir: str, prefix: str = "csi") -> Path:
    """Generate a timestamped CSV path inside outdir."""
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.csv"
    return outdir_path / filename


def csv_fieldnames(num_subcarriers: int) -> list[str]:
    """Build the CSV column header list for a given subcarrier count."""
    return (
        ["timestamp_us", "rssi", "num_subcarriers"]
        + [f"amp_{i}" for i in range(num_subcarriers)]
    )


# ---------------------------------------------------------------------------
# Array utilities
# ---------------------------------------------------------------------------

def amplitudes_to_array(pkt: dict) -> np.ndarray:
    """Convert the amplitudes list in a parsed packet to a float32 NumPy array."""
    return np.array(pkt["amplitudes"], dtype=np.float32)


def safe_mean(arr: np.ndarray) -> float:
    """Mean that returns 0.0 on empty arrays instead of raising."""
    return float(np.mean(arr)) if arr.size > 0 else 0.0


def safe_var(arr: np.ndarray) -> float:
    """Variance that returns 0.0 on arrays with fewer than 2 elements."""
    return float(np.var(arr)) if arr.size >= 2 else 0.0
