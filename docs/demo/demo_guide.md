# Demo Guide

Use this guide to run a polished live demonstration for recruiters, interviewers, and research reviewers.

## Demo Objective

Showcase the project as a complete **ESP32-S3 WiFi CSI embedded AI platform** for human activity recognition.

## Recommended Room Setup

- small-to-medium indoor room with stable WiFi
- fixed positions for AP and ESP32-S3
- clear sensing zone for subject movement
- minimal extra motion in background

## Pre-Demo Checklist

- firmware flashed and serial streaming verified
- virtual environment activated
- dependencies installed (`requirements.txt`)
- trained model available at `ml/models/activity_model.pkl`
- backup USB cable and known working serial port

## Demo Flow (10–15 minutes)

1. **Architecture (2 min):** explain CSI-based RF sensing concept.
2. **Data Path (2 min):** describe firmware → serial → features → ML → dashboard.
3. **Live Activity Demo (5 min):** perform `empty`, `walk`, `stand`, `sit`, `wave`.
4. **Model Discussion (2 min):** explain feature-based classifier and confidence bars.
5. **Research Roadmap (2 min):** discuss advanced HAR extensions.

## Run Commands

```bash
source .venv/bin/activate
cd ml
python dashboard.py
```

Optional CLI-only demo:

```bash
cd ml
python realtime_predictor.py
```

## How to Explain to Recruiters / Interviewers

- "This is a real-time RF sensing system that uses WiFi CSI from ESP32-S3."
- "I implemented an end-to-end embedded AI pipeline from packet acquisition to live inference."
- "The dashboard provides interpretable confidence scores and signal behavior in real time."
- "The project is structured for reproducibility, extensibility, and research experimentation."
