# Dataset Collection Guide

This guide standardizes data recording for WiFi CSI HAR experiments.

## Objectives

- create balanced, high-quality CSI datasets
- improve model robustness and reproducibility
- keep labels and folder structure consistent

## Supported Labels

- `empty`
- `walk`
- `stand`
- `sit`
- `wave`

## Recommended Recording Duration

- Per recording: **30–60 seconds**
- Per class target: **10+ recordings** minimum
- Total samples: collect across multiple sessions/times of day

## Environment Consistency

- keep AP and ESP32-S3 positions fixed
- maintain similar room layout during one dataset session
- reduce moving objects not part of the target activity
- avoid frequent orientation changes unless intentionally augmenting

## Labeling Structure

Store recordings as:

```text
data/datasets/
├── empty/
│   ├── empty_<timestamp>.csv
├── walk/
│   ├── walk_<timestamp>.csv
├── stand/
├── sit/
└── wave/
```

## Collection Procedure

1. Set `LABEL` in `python/logger.py` for current activity.
2. Run recording script for fixed duration.
3. Repeat multiple trials for each class.
4. Verify CSV file integrity and naming.

Example:

```bash
source .venv/bin/activate
cd python
python logger.py
```

Alternative recorder with arguments:

```bash
cd python
python serial_reader.py --port /dev/ttyACM0 --baud 115200 --duration 45
```

## Quality Checklist

- packet stream contains valid `CSI,` lines
- no large recording gaps from serial disconnects
- class counts are approximately balanced
- at least one independent session reserved for validation/demo
