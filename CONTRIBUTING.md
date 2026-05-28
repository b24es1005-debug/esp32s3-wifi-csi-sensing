# Contributing Guide

Thanks for your interest in improving this ESP32-S3 WiFi CSI sensing project.

## Development Setup

1. Clone the repository.
2. Create and activate a Python virtual environment.
3. Install dependencies from `requirements.txt`.
4. Follow firmware and runtime setup docs in `docs/setup/`.

```bash
git clone https://github.com/b24es1005-debug/esp32s3-wifi-csi-sensing.git
cd esp32s3-wifi-csi-sensing
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Branch Naming

Use descriptive branch names:

- `docs/<topic>` for documentation changes
- `feature/<short-description>` for new features
- `fix/<short-description>` for bug fixes
- `chore/<short-description>` for maintenance tasks

## Commit Style

Use clear, focused commits. Preferred style follows Conventional Commits:

- `feat: add ...`
- `fix: resolve ...`
- `docs: update ...`
- `chore: clean ...`
- `refactor: improve ...`

## Pull Request Guidelines

Before opening a PR:

- Keep PR scope focused and reviewable.
- Ensure source code behavior is unchanged unless explicitly intended.
- Update related docs when changing workflows or interfaces.
- Include screenshots/GIFs for dashboard UI changes.
- Link relevant issues in the PR description.

PR description checklist:

- What changed
- Why it changed
- How it was tested
- Any limitations or follow-up work

## Coding Standards

- Preserve existing coding style per directory.
- Avoid unrelated refactors.
- Keep functions and modules single-purpose.
- Add docstrings/comments only where they improve clarity.

## Documentation Standards

- Keep docs concise, reproducible, and technically accurate.
- Prefer tables, diagrams, and examples.
- Keep paths and commands copy-paste ready.

## Reporting Issues

Use the GitHub issue templates and include:

- environment details (OS, Python version, ESP-IDF version)
- clear reproduction steps
- expected vs actual behavior
- logs/screenshots where possible
