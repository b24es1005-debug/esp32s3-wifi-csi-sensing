import sys
import re
import serial
import joblib
import numpy as np

from collections import deque, Counter

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QProgressBar,
)

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont

import pyqtgraph as pg

from features import extract_features

# ---------------- CONFIG ----------------

PORT = "/dev/ttyACM0"
BAUD = 115200

WINDOW_SIZE = 30
VOTE_WINDOW = 10

LABELS = {
    0: "EMPTY",
    1: "WALK",
    2: "STAND",
    3: "SIT",
    4: "WAVE",
}

COLORS = {
    "EMPTY": "#2ecc71",
    "WALK": "#e74c3c",
    "STAND": "#3498db",
    "SIT": "#f1c40f",
    "WAVE": "#9b59b6",
}

# ---------------- MODEL ----------------

model = joblib.load("models/activity_model.pkl")

ser = serial.Serial(PORT, BAUD, timeout=1)

buffer = deque(maxlen=WINDOW_SIZE)

pred_history = deque(maxlen=VOTE_WINDOW)

# ---------------- APP ----------------

app = QApplication(sys.argv)

pg.setConfigOption("background", "#050816")
pg.setConfigOption("foreground", "w")

window = QWidget()
window.setWindowTitle("ESP32-S3 WiFi CSI AI Dashboard")
window.resize(1400, 900)

main_layout = QVBoxLayout()

# ---------- TITLE ----------

title = QLabel("ESP32-S3 • WiFi CSI • AI HAR Dashboard")
title.setFont(QFont("Arial", 20))
title.setStyleSheet("color: #4ea3ff; padding: 10px;")
main_layout.addWidget(title)

# ---------- ACTIVITY CARD ----------

activity_label = QLabel("WAITING...")
activity_label.setFont(QFont("Arial", 32))

activity_label.setStyleSheet("""
background-color: #222;
color: white;
padding: 30px;
border-radius: 20px;
""")

main_layout.addWidget(activity_label)

# ---------- CONFIDENCE BARS ----------

bars_layout = QVBoxLayout()

bars = {}

for label in LABELS.values():

    lbl = QLabel(label)
    lbl.setStyleSheet("color: white;")

    bar = QProgressBar()
    bar.setMaximum(100)

    bars[label] = bar

    bars_layout.addWidget(lbl)
    bars_layout.addWidget(bar)

main_layout.addLayout(bars_layout)

# ---------- CSI GRAPH ----------

plot = pg.PlotWidget(title="CSI Subcarrier Amplitudes")
plot.showGrid(x=True, y=True)

curve = plot.plot(pen=pg.mkPen("#4ea3ff", width=2))

main_layout.addWidget(plot)

window.setLayout(main_layout)

# ---------------- HELPERS ----------------

def clean_numeric(val):

    match = re.search(r"-?\d+\.?\d*", val)

    if match:
        return float(match.group())

    return None


# ---------------- UPDATE LOOP ----------------

def update():

    try:

        line = ser.readline().decode(errors="ignore").strip()

        if not line.startswith("CSI,"):
            return

        parts = line.split(",")

        raw_vals = parts[4:]

        amps = []

        for v in raw_vals:

            num = clean_numeric(v)

            if num is not None:
                amps.append(num)

        if len(amps) < 10:
            return

        buffer.append(amps)

        if len(buffer) < WINDOW_SIZE:
            return

        # ---------- FEATURES ----------

        feats = extract_features(list(buffer))

        feats = feats.reshape(1, -1)

        probs = model.predict_proba(feats)[0]

        pred = np.argmax(probs)

        pred_history.append(pred)

        stable_pred = Counter(pred_history).most_common(1)[0][0]

        label = LABELS[stable_pred]

        # ---------- UPDATE CARD ----------

        activity_label.setText(label)

        activity_label.setStyleSheet(f"""
        background-color: {COLORS[label]};
        color: white;
        padding: 30px;
        border-radius: 20px;
        """)

        # ---------- UPDATE BARS ----------

        for i, lbl in LABELS.items():

            confidence = int(probs[i] * 100)

            bars[lbl].setValue(confidence)

        # ---------- UPDATE GRAPH ----------

        amps_np = np.array(amps)

        x = np.arange(len(amps_np))

        curve.setData(x, amps_np)

    except Exception as e:
        print("ERR:", e)


timer = QTimer()
timer.timeout.connect(update)
timer.start(30)

window.show()

sys.exit(app.exec())
