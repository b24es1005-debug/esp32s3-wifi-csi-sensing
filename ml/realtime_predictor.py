import serial
import numpy as np
import joblib
import re
from collections import deque

from features import extract_features

PORT = "/dev/ttyACM0"
BAUD = 115200

WINDOW_SIZE = 30

LABELS = {
    0: "EMPTY",
    1: "WALK",
    2: "STAND",
    3: "SIT",
    4: "WAVE",
}

model = joblib.load("models/activity_model.pkl")

ser = serial.Serial(PORT, BAUD, timeout=1)

buffer = deque(maxlen=WINDOW_SIZE)

print("[INFO] Real-time activity predictor started")


def clean_numeric(val):

    match = re.search(r"-?\d+\.?\d*", val)

    if match:
        return float(match.group())

    return None


while True:

    try:

        line = ser.readline().decode(errors="ignore").strip()

        if not line.startswith("CSI,"):
            continue

        parts = line.split(",")

        raw_vals = parts[4:]

        amps = []

        for v in raw_vals:

            num = clean_numeric(v)

            if num is not None:
                amps.append(num)

        if len(amps) < 10:
            continue

        buffer.append(amps)

        if len(buffer) < WINDOW_SIZE:
            continue

        feats = extract_features(list(buffer))

        feats = feats.reshape(1, -1)

        pred = model.predict(feats)[0]

        print(
            f"\r[PREDICTION] {LABELS[pred]}",
            end=""
        )

    except KeyboardInterrupt:
        break

    except Exception as e:
        print("\nERR:", e)

ser.close()