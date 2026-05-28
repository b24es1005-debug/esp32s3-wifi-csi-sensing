import csv
import re
import numpy as np
from pathlib import Path

WINDOW_SIZE = 30


def clean_numeric(val):
    """
    Extract only numeric part from corrupted strings.
    Example:
        '1100\\x1b80036m8' -> 1100
    """

    match = re.search(r"-?\d+\.?\d*", val)

    if match:
        return float(match.group())

    return None


def load_activity(folder, label):

    X = []
    y = []

    files = list(Path(folder).glob("*.csv"))

    print(f"[INFO] Found {len(files)} files in {folder}")

    for file in files:

        print(f"[INFO] Loading {file.name}")

        samples = []

        with open(file) as f:

            reader = csv.DictReader(f)

            for row in reader:

                raw_vals = row["amplitudes"].split()

                amps = []

                for v in raw_vals:

                    num = clean_numeric(v)

                    if num is not None:
                        amps.append(num)

                # Skip corrupted packets
                if len(amps) < 10:
                    continue

                samples.append(amps)

        # Skip empty files
        if len(samples) == 0:
            continue

        # Force equal length
        min_len = min(len(s) for s in samples)

        samples = np.array([
            s[:min_len]
            for s in samples
        ])

        if len(samples) < WINDOW_SIZE:
            continue

        for i in range(
            0,
            len(samples) - WINDOW_SIZE,
            WINDOW_SIZE
        ):

            window = samples[i:i + WINDOW_SIZE]

            X.append(window)
            y.append(label)

    return X, y
