"""
backend/utils.py

Copy of original top-level utilities moved into backend package. Keep
functionality identical; top-level `python/utils.py` will re-export these
symbols to preserve backward compatibility.
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
    line = raw_line.strip()
    if not line:
        return False, "empty"
    if not _CSI_PREFIX_RE.match(line):
        return False, f"wrong prefix: {line[:20]!r}"
    parts = line.split(",")
    if len(parts) < 5:
        return False, f"too few fields: {len(parts)}"
    try:
        ts = int(parts[1])
        if ts < 0:
            return False, f"negative timestamp: {ts}"
    except ValueError:
        return False, f"non-integer timestamp: {parts[1]!r}"
    try:
        rssi = int(parts[2])
        if not (RSSI_MIN_DBM <= rssi <= RSSI_MAX_DBM):
            return False, f"RSSI out of range: {rssi}"
    except ValueError:
        return False, f"non-integer RSSI: {parts[2]!r}"
    try:
        n = int(parts[3])
        if not (MIN_SUBCARRIERS <= n <= MAX_SUBCARRIERS):
            return False, f"subcarrier count out of range: {n}"
    except ValueError:
        return False, f"non-integer subcarrier count: {parts[3]!r}"
    amp_fields = parts[4:]
    if len(amp_fields) != n:
        return False, f"amplitude count mismatch: declared {n}, got {len(amp_fields)}"
    for idx, a in enumerate(amp_fields):
        try:
            v = float(a)
            if v < 0.0:
                return False, f"negative amplitude[{idx}] = {v}"
        except ValueError:
            return False, f"non-float amplitude[{idx}] = {a!r}"
    return True, "ok"


def parse_csi_line(raw_line: str) -> dict | None:
    try:
        parts = raw_line.strip().split(",")
        n     = int(parts[3])
        return {
            "timestamp_us":    int(parts[1]),
            "rssi":            int(parts[2]),
            "num_subcarriers": n,
            "amplitudes":      [float(a) / 100.0 for a in parts[4 : 4 + n]],
        }
    except Exception as exc:
        log.error("Unexpected parse error: %s | line: %r", exc, raw_line[:60])
        return None


def make_csv_path(outdir: str, prefix: str = "csi") -> Path:
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.csv"
    return outdir_path / filename


def csv_fieldnames(num_subcarriers: int) -> list[str]:
    return (
        ["timestamp_us", "rssi", "num_subcarriers"]
        + [f"amp_{i}" for i in range(num_subcarriers)]
    )


def amplitudes_to_array(pkt: dict) -> np.ndarray:
    return np.array(pkt["amplitudes"], dtype=np.float32)


def safe_mean(arr: np.ndarray) -> float:
    return float(np.mean(arr)) if arr.size > 0 else 0.0


def safe_var(arr: np.ndarray) -> float:
    return float(np.var(arr)) if arr.size >= 2 else 0.0
