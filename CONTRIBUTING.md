# Contributing

## Development setup

1. Create and activate virtualenv.
2. Install dependencies:

```bash
pip install -r python/requirements.txt
pip install pre-commit black flake8 mypy
pre-commit install
```

## Code quality

Run before commit:

```bash
black python
flake8 python
mypy python
```

## Experiment reproducibility checklist

- Record session with a valid label (`empty_room`, `walking`, `sitting`, `standing`, `micro_motion`).
- Save CSV and metadata JSON together.
- Record firmware commit hash and Python commit hash in notes.
- Log room setup details (distance, orientation, obstacles, AP channel).
