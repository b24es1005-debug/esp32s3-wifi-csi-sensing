# System Architecture

This project is structured as an embedded RF sensing stack for WiFi CSI-based human activity recognition.

## High-Level Architecture (ASCII)

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         Physical Environment                        │
│             Human motion modifies WiFi multipath channel            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ESP32-S3 CSI Receiver (firmware/csi_receiver)                       │
│ - WiFi CSI capture                                                   │
│ - Packet formatting                                                   │
│ - UART serial streaming                                              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ UART (CSI lines)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Host Data Ingestion (python/)                                        │
│ - serial_reader.py / logger.py                                       │
│ - CSV persistence in data/                                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ windowed CSI amplitudes
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Signal Processing + Features (ml/features.py)                        │
│ - amplitude processing                                                │
│ - time/frequency-domain features                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ feature vectors
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ML Layer (ml/train.py, ml/realtime_predictor.py)                     │
│ - supervised training                                                 │
│ - model persistence (joblib)                                          │
│ - live activity prediction                                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ class probabilities / labels
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Visualization Layer (ml/dashboard.py)                                │
│ - activity state card                                                 │
│ - confidence bars                                                     │
│ - live CSI waveform                                                    │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow Summary

1. ESP32-S3 captures CSI and sends serial packets.
2. Python scripts parse and save recordings.
3. Dataset windows are transformed into ML features.
4. Classifier predicts activity labels in real-time.
5. Dashboard displays RF analytics and model outputs.

## Design Intent

- Embedded-first sensing pipeline
- Research-friendly data collection structure
- Reproducible training and demonstration workflow
