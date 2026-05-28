import serial
import csv
import time
from pathlib import Path

PORT = "/dev/ttyACM0"
BAUD = 115200

LABEL = "empty"   # change before each recording
DURATION = 30    # seconds

SAVE_DIR = Path("../data/datasets") / LABEL
SAVE_DIR.mkdir(parents=True, exist_ok=True)

timestamp = int(time.time())
csv_path = SAVE_DIR / f"{LABEL}_{timestamp}.csv"

ser = serial.Serial(PORT, BAUD, timeout=1)

print(f"[INFO] Recording {LABEL} for {DURATION}s")
print(f"[INFO] Saving to {csv_path}")

start = time.time()

with open(csv_path, "w", newline="") as f:
    writer = csv.writer(f)

    writer.writerow([
        "timestamp_us",
        "rssi",
        "num_subcarriers",
        "amplitudes"
    ])

    while time.time() - start < DURATION:
        try:
            line = ser.readline().decode(errors="ignore").strip()

            if not line.startswith("CSI,"):
                continue

            parts = line.split(",")

            ts = parts[1]
            rssi = parts[2]
            n_sc = parts[3]

            amps = parts[4:]

            writer.writerow([
                ts,
                rssi,
                n_sc,
                " ".join(amps)
            ])

        except Exception as e:
            print("ERR:", e)

print("[INFO] Recording complete")

ser.close()
