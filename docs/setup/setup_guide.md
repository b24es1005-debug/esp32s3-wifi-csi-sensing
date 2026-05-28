# Setup Guide

This guide prepares your environment for the ESP32-S3 WiFi CSI sensing workflow without changing project logic.

## 1) Prerequisites

- Python 3.10+
- `git`
- ESP-IDF toolchain (for firmware build/flash)
- USB serial access to ESP32-S3 board

## 2) Clone and Python Environment

```bash
git clone https://github.com/b24es1005-debug/esp32s3-wifi-csi-sensing.git
cd esp32s3-wifi-csi-sensing
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3) Verify Python Tools

```bash
python -c "import serial, numpy, pandas, scipy, sklearn, joblib; print('Python stack OK')"
```

## 4) Firmware Preparation

Follow `docs/setup/firmware_guide.md`.

## 5) Data and Training Workflow

1. Record datasets into `data/datasets/<activity>/`
2. Train model with `ml/train.py`
3. Run realtime predictor or dashboard

## 6) First Run (Quick Path)

```bash
source .venv/bin/activate
cd ml
python train.py
python realtime_predictor.py
```

## 7) Troubleshooting Quick Checks

- Validate serial device path (`/dev/ttyACM0` or `/dev/ttyUSB0`)
- Confirm baud rate consistency (`115200`)
- Ensure model file exists at `ml/models/activity_model.pkl`
