"""Unified CLI entrypoint for CSI tooling.

Keeps existing standalone scripts intact while adding a consistent interface
for research workflows and reproducible runs.
"""

import argparse
import logging
from pathlib import Path

from backend.acquisition.recorder import run as run_recorder
from backend.preprocessing import analyse_csv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ESP32 CSI research CLI")
    sub = p.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="Record CSI stream to CSV + metadata")
    rec.add_argument("--port", default="/dev/ttyACM0")
    rec.add_argument("--baud", type=int, default=115200)
    rec.add_argument("--outdir", default="../data")
    rec.add_argument("--duration", type=float, default=0.0)
    rec.add_argument("--label", default=None,
                     choices=["empty_room", "walking", "sitting", "standing", "micro_motion"])

    ana = sub.add_parser("analyse", help="Batch-analyse a recorded CSV")
    ana.add_argument("--csv", required=True, help="Path to CSV file")

    return p


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    args = build_parser().parse_args()

    if args.command == "record":
        run_recorder(
            port=args.port,
            baud=args.baud,
            outdir=args.outdir,
            duration=args.duration,
            label=args.label,
        )
        return

    if args.command == "analyse":
        result = analyse_csv(args.csv)
        motion = result["states"].count("Motion detected")
        static = result["states"].count("No motion")
        logging.info(
            "Analysis complete: packets=%d, windows=%d, motion=%d, static=%d",
            len(result["df"]),
            len(result["states"]),
            motion,
            static,
        )
        return


if __name__ == "__main__":
    main()
