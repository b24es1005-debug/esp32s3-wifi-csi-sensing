# ML Pipeline Explanation

This project uses a feature-based supervised HAR pipeline.

## Pipeline Steps

1. **Load labeled datasets** from `data/datasets/<activity>/`.
2. **Create windows** of CSI amplitudes per sample segment.
3. **Extract features** using `ml/features.py`.
4. **Train classifier** using `ml/train.py`.
5. **Persist model** to `ml/models/activity_model.pkl`.
6. **Run realtime inference** in `ml/realtime_predictor.py` or `ml/dashboard.py`.

## Training Command

```bash
source .venv/bin/activate
cd ml
python train.py
```

## Inference Commands

```bash
cd ml
python realtime_predictor.py
```

```bash
cd ml
python dashboard.py
```

## Reproducibility Recommendations

- Use consistent class folder names.
- Keep train data balanced across activities.
- Document recording sessions (time, room, AP placement).
- Re-train after any major environment or hardware layout changes.
