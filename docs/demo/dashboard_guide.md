# Dashboard Guide

The dashboard provides live visualization for CSI-driven activity recognition.

## What It Shows

- current predicted activity label
- per-class confidence bars
- real-time CSI amplitude waveform

## Run

```bash
source .venv/bin/activate
cd ml
python dashboard.py
```

## Typical Demo Interpretation

- stable activity should produce consistent top confidence class
- transitions (e.g., stand → walk) show changing confidence distribution
- waveform shape and variance reflect motion dynamics

## Tips

- keep serial link stable
- avoid overloading CPU during live plotting
- ensure `ml/models/activity_model.pkl` exists before launching
