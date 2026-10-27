---
trigger: always_on
description: Modular repository layout and package conventions for basketball_proj.
---

# Codebase Structure & Conventions

This repository follows a clean, modular Python layout designed for developer onboarding and feature extensibility.

## Directory Layout

```
basketball_proj/
├── src/basketball/           # Core library and application packages
│   ├── core/                 # Pose inference, joint angle computation, kinematic features
│   ├── tracking/             # YOLO ball/rim tracker, trajectory math, shot detector FSM/ML
│   ├── analysis/             # Biomechanical shooting analysis, baselines, pro comparison
│   ├── coaching/             # Evidence-based coaching rules, drills, LLM coach integration
│   ├── persistence/          # SQLite database storage (ShotLabDB)
│   ├── services/             # Video analysis pipeline, report service, player history
│   ├── hand/                 # MediaPipe hand tracking & wrist snap
│   └── app/                  # Application entry points (main.py HUD & web_app.py server)
├── tests/                    # Comprehensive test suites
│   ├── unit/                 # Fast, isolated unit tests
│   ├── integration/          # Subsystem & database integration tests
│   ├── e2e/                  # End-to-end web & browser tests
│   └── support/              # Synthetic test fixtures & pose generators
├── scripts/                  # Batch ingestion, export, and administrative scripts
├── tools/                    # Interactive developer tools (e.g. annotation_lab.py)
├── evaluation/               # Benchmark evaluation harnesses
├── configs/                  # Dataset splits and system configurations
├── data/                     # Ground truth annotations, manifests, benchmark reports
├── docs/                     # Specifications, guides, metric dictionary, verification index
├── main.py                   # Backward-compatible CLI entry point (delegates to src/basketball/app/main.py)
├── web_app.py                # Backward-compatible Web entry point (delegates to src/basketball/app/web_app.py)
├── pyproject.toml            # Modern Python package configuration
└── setup.py                  # Standard setuptools configuration
```

## Rules for Code Changes

1. **Package Imports**: Always import modules within `src/` using `basketball.<subpackage>.<module>` (e.g., `from basketball.core.pose_engine import PoseEngine`).
2. **Backward Compatibility**: Do not break existing CLI arguments, database schemas, or public APIs. Root entry points (`main.py`, `web_app.py`) must continue to work.
3. **Tests**: All tests in `tests/` must pass when adding or modifying features. Run:
   ```powershell
   $env:PYTHONPATH="src;."
   python -m unittest discover tests
   ```
4. **Data Integrity**: Follow `AGENTS.md`. Never hardcode synthetic results as real data, and keep `docs/reference/MANUAL_VERIFICATION_COMMANDS.md` updated.
