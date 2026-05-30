# Solar Collector — 3 Line Dynamic Simulator

Minimal starting README for the Python reimplementation of Russ Rhinehart's
parabolic solar collector plant (3 collector lines), using CasADi for modeling.

Prerequisites
- Python 3.9 or newer

Quick setup (assuming you created a venv in VS Code and activated it)

```bash
pip install -U pip
# install runtime dependencies only
pip install .
# or install runtime + developer extras (tests, ruff)
pip install -e ".[dev]"
```

Run tests

```bash
pytest
```

Development
- Put source under `src/` and create modules for the simulator and Gymnasium environment.

License: MIT
Author: Russ Rhinehart / Research Team
