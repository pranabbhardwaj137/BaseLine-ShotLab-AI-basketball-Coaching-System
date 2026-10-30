# Model Weights & Assets Manifest

This document records the provenance, licensing, architecture, class taxonomy, and cryptographic checksums for all external neural network weights utilized in the Basketball Shot Lab project.

---

## 1. Active Phase 7 Production Checkpoint

### `models/best.pt`
- **Role:** Primary Ball & Rim Detector for shot-synchronized trajectory fitting and rim proximity estimation.
- **Architecture:** Ultralytics YOLOv8n (Nano object detection).
- **File Size:** 6,257,066 bytes (~6.25 MB).
- **SHA-256 Checksum:** `d3a52414eb0970661d98473663a858ce7c05db6d8a6e107a413d2c714231d43f`
- **Training Provenance:** Pre-trained on the Roboflow `Basketball.v1i.yolov8` (project `eagle-eye / basketball-1zhpe`, version 1, `Basketball-1/data.yaml`).
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0).
- **Class Taxonomy (3 classes):**
  - Class `0`: `basketball`
  - Class `1`: `rim`
  - Class `2`: `sports ball`
- **Runtime Resolution:** Dynamically mapped via `model.names` in `ball_tracker.py`.

---

## 2. Experimental Pose Comparison Model

### `models/yolov8m-pose.pt`
- **Role:** Comparative benchmark backend evaluated offline against MediaPipe Tasks Pose on 12 shared human joints.
- **Architecture:** Ultralytics YOLOv8m-pose (Medium human pose estimation).
- **File Size:** 53,266,977 bytes (~53.27 MB).
- **SHA-256 Checksum:** `dbe539ea268db2534390942cfdf206e521f376f19e5415967a57f6a2ddfa3c90`
- **Training Provenance:** Pre-trained on COCO Keypoints topology (17 keypoints).
- **License:** AGPL-3.0.
- **Topology (Shared Joints Mapped to MediaPipe):**
  - Shoulders (`left_shoulder`: 5, `right_shoulder`: 6)
  - Elbows (`left_elbow`: 7, `right_elbow`: 8)
  - Wrists (`left_wrist`: 9, `right_wrist`: 10)
  - Hips (`left_hip`: 11, `right_hip`: 12)
  - Knees (`left_knee`: 13, `right_knee`: 14)
  - Ankles (`left_ankle`: 15, `right_ankle`: 16)

---

## 3. Alternative & Reference Checkpoints

### `models/ballRim.pt`
- **Role:** Heavyweight alternative 2-class detector for extreme resolution / distant court evaluation.
- **Architecture:** Ultralytics YOLOv8s/m.
- **File Size:** 22,524,451 bytes (~22.52 MB).
- **SHA-256 Checksum:** `56b7b23d63aedfa01cd0b4ffe9ffe97444ca80ffa934dc736b1c5ed91d0f940a`
- **Training Provenance:** Google Colab training run on `Basket2-7/data.yaml`.
- **Class Taxonomy (2 classes):**
  - Class `0`: `Basketball`
  - Class `1`: `Rim`

### `models/bestYT.pt`
- **Role:** Multi-class action and context detection checkpoint (exploratory).
- **Architecture:** Ultralytics YOLOv8n.
- **File Size:** 6,229,219 bytes (~6.23 MB).
- **SHA-256 Checksum:** `010376003d9c899ce49b71f8825253c5e2a32501bd11cfddc2e3e0018dab21f2`
- **Training Provenance:** Regis University Data Science MSDS_692 capstone project (YouTube basketball clips).
- **Class Taxonomy (8 classes):** `['ball', 'rim', 'net', 'shooting', 'dribbling', 'after shooting', 'standing', 'score']`.

---

## 4. Local Neural Speech Synthesis Checkpoints (Kokoro ONNX)

### `models/kokoro/kokoro-v0_19.int8.onnx`
- **Role:** High-fidelity offline neural speech synthesizer for live Practice audio coaching cues and Guided Workout voice guidance.
- **Architecture:** Kokoro v0.19 (StyleTTS 2 + ISTFTNet acoustic and vocoder pipeline, INT8 quantized ONNX graph).
- **File Size:** 92,360,686 bytes (~92.36 MB).
- **SHA-256 Checksum:** `03e2815f4be9c8289b3b0919f40f5857acd24cfd121ca258cf042d309ee3a0cf`
- **Model Provenance:** Hugging Face repository `hexgrad/Kokoro-82M`.
- **License:** Apache-2.0.

### `models/kokoro/voices.bin`
- **Role:** Precomputed speaker voice embeddings (54 distinct multi-accent voices, including `af_sarah`, `af_bella`, `am_adam`, `am_michael`, `bf_emma`).
- **File Size:** 5,758,648 bytes (~5.76 MB).
- **SHA-256 Checksum:** `157eab2fa1dd1c91b46599ea6f514bf86f66944c0c760250ed324e6cd99af075`
- **Provenance:** Hexgrad Kokoro-82M repository.
- **License:** Apache-2.0.

---

## 5. Compliance and Licensing Summary

All weights are tracked outside source control versioning (`.gitignore` excludes `*.pt`, `*.onnx`, `*.bin`). Runtime modules access weights via explicit local paths or configuration with automatic, graceful fallback to native browser Web Speech API (`speechSynthesis`) if Kokoro neural models are uninstalled or offline.
