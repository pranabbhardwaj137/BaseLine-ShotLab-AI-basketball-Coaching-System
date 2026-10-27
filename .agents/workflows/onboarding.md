---
name: onboarding
description: Developer onboarding, setup, and verification workflow for Baseline Shot Lab
---

# Workflow: Developer Onboarding

Follow these steps to set up the repository, verify dependencies, run tests, and test entry points.

## Step 1: Environment Setup

Install the package in editable mode with core dependencies:
```powershell
# In PowerShell (Windows)
python -m pip install -e .
```
Or install directly from `requirements.txt`:
```powershell
python -m pip install -r requirements.txt
```

## Step 2: Verify Pre-bundled Assets

The repository includes the required model files and baseline clips:
- `models/best.pt`: Primary ball/rim YOLO detection weights
- `models/ballRim.pt`: Alternative rim detection weights
- `models/yolov8m-pose.pt`: YOLOv8 Pose model
- `pose_landmarker.task`: MediaPipe BlazePose landmark task asset
- `hand_landmarker.task`: MediaPipe hand landmark task asset
- `raw_clips/`: Sample basketball shooting footage

No lengthy asset downloads are needed to get started.

## Step 3: Run the Test Suite

Run the full automated test suite (123+ tests across unit, integration, and e2e suites):
```powershell
$env:PYTHONPATH="src;."
python -m unittest discover tests
```
Expected output: `OK (skipped=...)` with zero failures and zero errors.

## Step 4: Run Entry Points

### A. Live / Video Desktop HUD
```powershell
# Analyze a sample video clip with default ball & rim tracking
python main.py --video raw_clips\klay_vid.mp4 --player klay_thompson --camera-view side_90 --windowed
```
Or using the package module syntax:
```powershell
python -m basketball.app.main --video raw_clips\klay_vid.mp4 --player klay_thompson --camera-view side_90 --windowed
```

### B. Local Web Application
```powershell
python web_app.py --port 8000
```
Or using the package module syntax:
```powershell
python -m basketball.app.web_app --port 8000
```
Open `http://127.0.0.1:8000/` in any browser to upload clips, view biomechanics metrics, and generate reports.

### C. Developer Annotation Lab
```powershell
python tools/annotation_lab.py
```
Or run the batch ingestion script:
```powershell
python scripts/batch_ingest_clips.py --dry-run
```
