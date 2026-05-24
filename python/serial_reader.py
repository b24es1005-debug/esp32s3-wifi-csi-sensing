"""
serial_reader.py
Save to: python/serial_reader.py

Reads raw CSI packets from the ESP32-S3 over UART serial, validates each line,
parses it, and saves to a timestamped CSV file in ../data/.

Usage:
    python3 serial_reader.py
    python3 serial_reader.py --port /dev/ttyACM0 --baud 115200 --duration 120
    python3 serial_reader.py --port /dev/ttyUSB0 --no-save --verbose

Architecture:
    This is a standalone script — it does NOT launch the visualizer.
    Run it first to collect a CSV dataset, then run visualizer.py for analysis.
    Or run visualizer.py directly — it has its own built-in reader thread.
"""

import serial
import csv
import sys
import time
import argparse
import logging
from pathlib import Path

# Local utilities (same python/ directory)
from utils import (
    validate_csi_line,
    parse_csi_line,
    make_csv_path,
    csv_fieldnames,
    CSI_LINE_PREFIX,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("serial_reader")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ESP32-S3 CSI serial reader and CSV logger",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--port",     default="/dev/ttyACM0",
                   help="Serial port (use 'ls /dev/ttyACM* /dev/ttyUSB*' to find)")
    p.add_argument("--baud",     default=115200, type=int,
                   help="Baud rate — must match CSI_UART_BAUD in wifi_csi.h")
    p.add_argument("--duration", default=0, type=float,
                   help="Recording duration in seconds (0 = run until Ctrl+C)")
    p.add_argument("--outdir",   default="../data",
                   help="Output directory for CSV files")
    p.add_argument("--no-save",  action="store_true",
                   help="Parse and print only — do not write CSV")
    p.add_argument("--verbose",  action="store_true",
                   help="Print every valid packet to console")
    return p


# ---------------------------------------------------------------------------
# Main reader loop
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> None:
    """
    Open the serial port, read CSI lines, validate, parse, and save.

    Statistics are printed every 10 seconds:
        rx_total    — all lines read from serial (including ESP_LOGI debug)
        valid       — lines that passed validation and were saved
        malformed   — lines that failed validation (dropped)
        rate_hz     — valid packet rate since last stats print
    """
    log.info("Opening %s at %d baud …", args.port, args.baud)
    log.info("Baud rate must match CSI_UART_BAUD in wifi_csi.h (%d)", 115200)

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=2.0,    # readline() returns "" after 2 s with no data
        )
    except serial.SerialException as exc:
        log.error("Cannot open serial port: %s", exc)
        log.error("")
        log.error("Troubleshooting steps:")
        log.error("  1. Check port:   ls /dev/ttyACM* /dev/ttyUSB*")
        log.error("  2. Check group:  groups $USER   (must include 'dialout' or 'uucp')")
        log.error("  3. Add yourself: sudo usermod -aG uucp $USER  (Arch Linux)")
        log.error("     Then log out and back in, or: newgrp uucp")
        log.error("  4. Check cable:  must be USB data cable, not charge-only")
        sys.exit(1)

    log.info("Port open. Waiting for CSI packets …")
    log.info("Press Ctrl+C to stop.\n")

    # CSV state — created lazily after we know the subcarrier count
    csv_fh     = None
    csv_writer = None
    csv_path   = None

    # Statistics
    rx_total     = 0
    valid_count  = 0
    bad_count    = 0
    t_start      = time.monotonic()
    t_last_stat  = time.monotonic()
    valid_since_stat = 0
    STAT_EVERY   = 10.0  # seconds

    try:
        while True:
            # Duration check
            if args.duration > 0:
                if time.monotonic() - t_start >= args.duration:
                    log.info("Duration %.1f s reached. Stopping.", args.duration)
                    break

            # Read one line from serial
            try:
                raw_bytes = ser.readline()
            except serial.SerialException as exc:
                log.warning("Serial read error: %s — retrying …", exc)
                time.sleep(0.1)
                continue

            # Timeout: readline returned empty bytes
            if not raw_bytes:
                continue

            # Decode bytes → string, replacing any invalid UTF-8 bytes
            try:
                raw_line = raw_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                continue

            rx_total += 1

            # Skip non-CSI lines silently (ESP_LOGI output, boot messages)
            if not raw_line.startswith(CSI_LINE_PREFIX):
                continue

            # Validate
            valid, reason = validate_csi_line(raw_line)
            if not valid:
                bad_count += 1
                if args.verbose:
                    log.warning("DROPPED [%s]: %s", reason, raw_line[:80])
                continue

            # Parse
            pkt = parse_csi_line(raw_line)
            if pkt is None:
                bad_count += 1
                continue

            valid_count     += 1
            valid_since_stat += 1

            # Lazy CSV initialisation (need first valid packet for column count)
            if not args.no_save and csv_writer is None:
                csv_path = make_csv_path(args.outdir)
                fieldnames = csv_fieldnames(pkt["num_subcarriers"])
                csv_fh     = open(csv_path, "w", newline="", buffering=1)
                csv_writer = csv.DictWriter(csv_fh, fieldnames=fieldnames)
                csv_writer.writeheader()
                log.info("Saving to: %s", csv_path)

            # Build CSV row
            if csv_writer is not None:
                row = {
                    "timestamp_us":    pkt["timestamp_us"],
                    "rssi":            pkt["rssi"],
                    "num_subcarriers": pkt["num_subcarriers"],
                }
                for i, amp in enumerate(pkt["amplitudes"]):
                    row[f"amp_{i}"] = round(amp, 4)
                csv_writer.writerow(row)

            # Verbose console output
            if args.verbose:
                amps = pkt["amplitudes"]
                log.info(
                    "ts=%d rssi=%d sc=%d amps[0:4]=%s",
                    pkt["timestamp_us"], pkt["rssi"],
                    pkt["num_subcarriers"],
                    [round(a, 2) for a in amps[:4]],
                )

            # Periodic statistics
            now = time.monotonic()
            if now - t_last_stat >= STAT_EVERY:
                dt   = now - t_last_stat
                rate = valid_since_stat / dt
                log.info(
                    "── Stats ── valid=%d  bad=%d  rate=%.1f Hz  total_rx=%d",
                    valid_count, bad_count, rate, rx_total,
                )
                valid_since_stat = 0
                t_last_stat = now

    except KeyboardInterrupt:
        log.info("\nStopped by user (Ctrl+C)")

    finally:
        ser.close()
        if csv_fh:
            csv_fh.close()
        elapsed = time.monotonic() - t_start
        log.info(
            "Session ended — elapsed=%.1f s  valid=%d  bad=%d  total_rx=%d",
            elapsed, valid_count, bad_count, rx_total,
        )
        if csv_path:
            log.info("CSV saved: %s", csv_path)


if __name__ == "__main__":
    args = build_parser().parse_args()
    run(args)
