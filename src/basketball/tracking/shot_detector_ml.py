"""
shot_detector_ml.py - Lightweight Machine Learning Sequence Classifier for Shot Events.

Trains a sliding-window classifier on biomechanical kinematics to generate shot proposals,
refine keyframe boundaries (dip, set, release), and suppress hard negative actions.
"""

from __future__ import annotations
import os
import math
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import joblib
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

from basketball.core.shot_feature_extractor import ShotFeatureExtractor


class MLSequenceDetector:
    """
    Lightweight ML sequence detector for basketball shot proposals.
    Uses sliding-window kinematic features to produce continuous shot probabilities,
    detect activation segments, and localize keyframe boundaries.
    """

    def __init__(
        self,
        prob_threshold: float = 0.50,
        min_activation_frames: int = 5,
        window_size: int = 15,
        default_fps: float = 30.0
    ):
        self.prob_threshold = prob_threshold
        self.min_activation_frames = min_activation_frames
        self.window_size = window_size
        self.default_fps = default_fps

        self.feature_extractor = ShotFeatureExtractor(window_size=window_size, default_fps=default_fps)

        # Model weights
        self.model: Optional[Any] = None
        self.scaler: Optional[Any] = None
        self.is_trained: bool = False

        # Fallback pure NumPy linear weights if sklearn not available
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0

        # State during online streaming
        self.reset_stream()

    def reset_stream(self):
        """Reset internal streaming buffers."""
        self.kinematics_buffer: List[Dict[str, Any]] = []
        self.active_segment_frames: List[int] = []
        self.active_segment_probs: List[float] = []
        self.completed_proposals: List[Dict[str, Any]] = []

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weights: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        Train classifier on feature matrices X (N x 24) and binary labels y (N).
        """
        if len(X) == 0 or len(y) == 0:
            raise ValueError("Training dataset cannot be empty.")

        if HAS_SKLEARN:
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)

            # L2-regularized logistic regression with balanced class weights
            self.model = LogisticRegression(
                C=1.0,
                max_iter=500,
                class_weight="balanced",
                random_state=42
            )
            self.model.fit(X_scaled, y, sample_weight=sample_weights)
            self.is_trained = True

            train_acc = float(self.model.score(X_scaled, y))
            return {
                "status": "TRAINED",
                "backend": "sklearn_logistic_regression",
                "samples": int(len(X)),
                "features": int(X.shape[1]),
                "train_accuracy": round(train_acc, 4)
            }
        else:
            # Pure NumPy Ridge Classification fallback
            mean = np.mean(X, axis=0)
            std = np.std(X, axis=0)
            std[std < 1e-6] = 1.0
            X_scaled = (X - mean) / std

            # Normal equations with L2 ridge: (X^T X + lambda I)^-1 X^T y
            reg = 1.0 * np.eye(X_scaled.shape[1])
            self.weights = np.linalg.solve(X_scaled.T @ X_scaled + reg, X_scaled.T @ y)
            self.bias = float(np.mean(y) - np.mean(X_scaled @ self.weights))
            self.is_trained = True

            preds = (X_scaled @ self.weights + self.bias) >= 0.5
            acc = float(np.mean(preds == y))
            return {
                "status": "TRAINED",
                "backend": "numpy_ridge_classifier",
                "samples": int(len(X)),
                "features": int(X.shape[1]),
                "train_accuracy": round(acc, 4)
            }

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict shot probability for a matrix of window feature vectors."""
        if not self.is_trained:
            # Prior rule-based fallback if untrained
            # Higher upward wrist velocity and elevation -> higher probability
            wv_y = X[:, 0]
            rel_sh = X[:, 2]
            scores = -1.5 * wv_y - 2.0 * rel_sh
            return 1.0 / (1.0 + np.exp(-scores))

        if HAS_SKLEARN and self.model is not None and self.scaler is not None:
            X_scaled = self.scaler.transform(X)
            return self.model.predict_proba(X_scaled)[:, 1]
        else:
            # NumPy fallback
            scores = X @ self.weights + self.bias
            return 1.0 / (1.0 + np.exp(-np.clip(scores, -10.0, 10.0)))

    def update(
        self,
        frame_idx: int,
        kinematics: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Stream processing for online or batch inference:
        Appends kinematics to sliding window, computes probability, and returns proposal if completed.
        """
        self.kinematics_buffer.append(kinematics)
        if len(self.kinematics_buffer) > self.window_size * 2:
            self.kinematics_buffer.pop(0)

        # Extract window vector
        recent_window = self.kinematics_buffer[-self.window_size:]
        vec = self.feature_extractor.extract_window_vector(recent_window)
        prob = float(self.predict_proba(vec[np.newaxis, :])[0])

        proposal = None

        if prob >= self.prob_threshold:
            self.active_segment_frames.append(frame_idx)
            self.active_segment_probs.append(prob)
        else:
            # Segment terminated: check if valid shot proposal
            if len(self.active_segment_frames) >= self.min_activation_frames:
                proposal = self._extract_proposal_from_segment(
                    self.active_segment_frames,
                    self.active_segment_probs
                )
                if proposal:
                    self.completed_proposals.append(proposal)

            self.active_segment_frames = []
            self.active_segment_probs = []

        return proposal

    def _extract_proposal_from_segment(
        self,
        frames: List[int],
        probs: List[float]
    ) -> Optional[Dict[str, Any]]:
        """
        Localize keyframes (start, dip, set, release, end) from an activation segment.
        """
        if not frames:
            return None

        p_start = max(0, frames[0] - 10)
        p_end = frames[-1] + 10

        # Peak probability frame
        best_idx = int(np.argmax(probs))
        p_release = frames[best_idx]
        mean_conf = float(np.mean(probs))

        # Approximate dip and set relative to release
        p_dip = max(p_start, p_release - 10)
        p_set = max(p_dip, p_release - 5)

        # Strict monotonic bounds
        p_dip = max(p_start, min(p_dip, p_release))
        p_set = max(p_dip, min(p_set, p_release))
        p_release = max(p_set, min(p_release, p_end))

        return {
            "detector_name": "ml_sequence_detector",
            "detector_version": "1.0.0",
            "start_frame": int(p_start),
            "dip_frame": int(p_dip),
            "set_frame": int(p_set),
            "release_frame": int(p_release),
            "end_frame": int(p_end),
            "confidence": round(mean_conf, 3),
            "status": "proposed"
        }

    def save_model(self, path: str):
        """Serialize model weights and metadata to file."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if HAS_SKLEARN and self.model is not None:
            joblib.dump({
                "model": self.model,
                "scaler": self.scaler,
                "prob_threshold": self.prob_threshold,
                "window_size": self.window_size
            }, path)
        else:
            np.savez(
                path,
                weights=self.weights if self.weights is not None else np.zeros(24),
                bias=self.bias,
                prob_threshold=self.prob_threshold,
                window_size=self.window_size
            )

    def load_model(self, path: str):
        """Deserialize model weights from file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")

        if HAS_SKLEARN and path.endswith(".joblib"):
            data = joblib.load(path)
            self.model = data["model"]
            self.scaler = data["scaler"]
            self.prob_threshold = data.get("prob_threshold", 0.50)
            self.window_size = data.get("window_size", 15)
            self.is_trained = True
        else:
            data = np.load(path)
            self.weights = data["weights"]
            self.bias = float(data["bias"])
            self.prob_threshold = float(data["prob_threshold"])
            self.is_trained = True
