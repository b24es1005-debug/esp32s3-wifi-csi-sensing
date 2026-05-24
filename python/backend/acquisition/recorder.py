"""
backend/acquisition/recorder.py

Serial recorder for CSI that captures CSI lines and writes CSV + metadata JSON.
This is a non-destructive wrapper around the existing serial reader logic but
adds reproducible metadata for research datasets.
"""

import time
import json
import argparse
import logging
from pathlib import Path
from typing import Optional

from ..utils import (
    CSI_LINE_PREFIX,
    validate_csi_line,
    parse_csi_line,
    make_csv_path,
    csv_fieldnames,
)

import serial

log = logging.getLogger("csi.recorder")

ALLOWED_LABELS = {
    "empty_room",
    "walking",
    "sitting",
    "standing",
    "micro_motion",
}


def write_metadata(path_csv: Path, metadata: dict) -> None:
    meta_path = path_csv.with_suffix(".json")
    with open(meta_path, "w") as fh:
        json.dump(metadata, fh, indent=2)
    log.info("Wrote metadata: %s", meta_path)


def run(port: str = "/dev/ttyACM0", baud: int = 115200,
        outdir: str = "../data", duration: float = 0.0,
        label: Optional[str] = None):
    log.info("Recorder starting — port=%s baud=%d", port, baud)

    if label is not None and label not in ALLOWED_LABELS:
        raise ValueError(f"Invalid label '{label}'. Allowed: {sorted(ALLOWED_LABELS)}")

    try:
        ser = serial.Serial(port, baud, timeout=2.0)
    except serial.SerialException as exc:
        log.error("Cannot open serial port: %s", exc)
        return

    csv_fh = None
    csv_writer = None
    csv_path = None

    t_start = time.monotonic()
    rx_total = 0
    valid = 0
    bad = 0
    last_ts_us: Optional[int] = None
    ts_delta_us = []

    try:
        while True:
            if duration > 0 and (time.monotonic() - t_start) >= duration:
                log.info("Duration reached — stopping")
                break

            raw_bytes = ser.readline()
            if not raw_bytes:
                continue
            try:
                raw_line = raw_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            rx_total += 1
            if not raw_line.startswith(CSI_LINE_PREFIX):
                continue
            valid_line, reason = validate_csi_line(raw_line)
            if not valid_line:
                bad += 1
                continue
            pkt = parse_csi_line(raw_line)
            if pkt is None:
                bad += 1
                continue
            valid += 1

            if last_ts_us is not None:
                delta = pkt["timestamp_us"] - last_ts_us
                if delta > 0:
                    ts_delta_us.append(delta)
            last_ts_us = pkt["timestamp_us"]

            if csv_writer is None:
                csv_path = make_csv_path(outdir)
                fieldnames = csv_fieldnames(pkt["num_subcarriers"])
                csv_fh = open(csv_path, "w", newline="", buffering=1)
                import csv as _csv
                csv_writer = _csv.DictWriter(csv_fh, fieldnames=fieldnames)
                csv_writer.writeheader()
                log.info("Recording to %s", csv_path)

            row = {
                "timestamp_us": pkt["timestamp_us"],
                "rssi": pkt["rssi"],
                "num_subcarriers": pkt["num_subcarriers"],
            }
            for i, amp in enumerate(pkt["amplitudes"]):
                row[f"amp_{i}"] = round(amp, 4)
            csv_writer.writerow(row)

    except KeyboardInterrupt:
        log.info("Stopped by user")
    finally:
        ser.close()
        if csv_fh:
            csv_fh.close()
        elapsed = time.monotonic() - t_start
        log.info("Session ended — elapsed=%.1f s  valid=%d  bad=%d  total_rx=%d",
                 elapsed, valid, bad, rx_total)
        if csv_path:
            git_sha = None
            try:
                # Attempt to capture firmware repo commit if present
                import subprocess
                git_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
            except Exception:
                git_sha = None
            metadata = {
                "label": label,
                "duration_s": round(elapsed, 2),
                "valid_packets": valid,
                "malformed": bad,
                "total_rx": rx_total,
                "loss_proxy_ratio": round((bad / (valid + bad)) if (valid + bad) else 0.0, 6),
                "recorder_time_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                "firmware_git": git_sha,
            }

            if ts_delta_us:
                import numpy as np
                d = np.array(ts_delta_us, dtype=np.float64)
                metadata["timing"] = {
                    "mean_delta_us": float(d.mean()),
                    "std_delta_us": float(d.std()),
                    "min_delta_us": float(d.min()),
                    "max_delta_us": float(d.max()),
                    "estimated_rate_hz": float(1e6 / d.mean()) if d.mean() > 0 else 0.0,
                }

            write_metadata(Path(csv_path), metadata)


def build_parser():
    p = argparse.ArgumentParser(description="CSI recorder — CSV + metadata")
    p.add_argument("--port", default="/dev/ttyACM0")
    p.add_argument("--baud", default=115200, type=int)
    p.add_argument("--outdir", default="../data")
    p.add_argument("--duration", default=0.0, type=float)
    p.add_argument("--label", default=None, choices=sorted(ALLOWED_LABELS))
    return p


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
    args = build_parser().parse_args()
    run(args.port, args.baud, args.outdir, args.duration, args.label)


if __name__ == "__main__":
    main()
