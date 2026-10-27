"""
launch_annotation_lab.py - Interactive CLI launcher for Annotation Lab.
"""

import os
import sys
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
LAB_SCRIPT = str(_REPO_ROOT / "tools" / "annotation_lab.py") if (_REPO_ROOT / "tools" / "annotation_lab.py").exists() else "annotation_lab.py"

CLIPS = [
    # Train set (Lavish & Klay)
    {"id": "lavish_1", "video": "raw_clips/lavish_1_90deg.mp4", "player": "lavish", "split": "train"},
    {"id": "lavish_2", "video": "raw_clips/lavish_2_90deg.mp4", "player": "lavish", "split": "train"},
    {"id": "lavish_3", "video": "raw_clips/lavish_3_mix.mp4",   "player": "lavish", "split": "train"},
    {"id": "lavish_4", "video": "raw_clips/lavish_4_0deg.mp4",  "player": "lavish", "split": "train"},
    {"id": "lavish_5", "video": "raw_clips/lavish_5_0deg.mp4",  "player": "lavish", "split": "train"},
    {"id": "klay_vid", "video": "raw_clips/klay_vid.mp4",       "player": "klay_thompson", "split": "train"},
    # Validation set (Mike Dunn)
    {"id": "mikedunn",       "video": "raw_clips/Mikedunn.mp4",       "player": "mike_dunn", "split": "val"},
    {"id": "mikedunn_stud1", "video": "raw_clips/mikeddunnstud1.mp4", "player": "mike_dunn", "split": "val"},
    {"id": "mikedunn_stud2", "video": "raw_clips/mikeddunnstud2.mp4", "player": "mike_dunn", "split": "val"},
    # Test set (Sid)
    {"id": "sid_1", "video": "raw_clips/sid_1.mp4",          "player": "sid", "split": "test"},
    {"id": "sid_2", "video": "raw_clips/sid_2.mp4",          "player": "sid", "split": "test"},
    {"id": "sid_3", "video": "raw_clips/sid_3_mult.mp4",     "player": "sid", "split": "test"},
    {"id": "sid_4", "video": "raw_clips/sid_4_97deg_wrim.mp4", "player": "sid", "split": "test"},
    {"id": "sid_5", "video": "raw_clips/sid_5_0deg.mp4",     "player": "sid", "split": "test"},
    {"id": "sid_6", "video": "raw_clips/sid_6_0deg.mp4",     "player": "sid", "split": "test"},
]

def main():
    if len(sys.argv) > 1:
        query = sys.argv[1].lower()
        for c in CLIPS:
            if query in c["id"].lower() or query in c["video"].lower():
                cmd = [
                    sys.executable, LAB_SCRIPT,
                    "--video", c["video"],
                    "--clip-id", c["id"],
                    "--player-id", c["player"],
                    "--split", c["split"]
                ]
                print(f"Launching: {' '.join(cmd)}")
                subprocess.run(cmd)
                return
        print(f"No clip matching '{query}' found.")
        return

    print("=" * 80)
    print("Basketball Shot Lab - Clip Annotation Launcher")
    print("=" * 80)
    for idx, c in enumerate(CLIPS, 1):
        print(f" [{idx:02d}] {c['video']:<30} | Player: {c['player']:<14} | Split: {c['split']}")
    print("=" * 80)

    try:
        choice = input("Enter clip number (1-15) or clip ID (e.g. sid_1): ").strip()
        if not choice:
            return
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(CLIPS):
                target = CLIPS[idx]
            else:
                print("Invalid number.")
                return
        else:
            target = next((c for c in CLIPS if choice.lower() in c["id"].lower() or choice.lower() in c["video"].lower()), None)
            if not target:
                print("No matching clip found.")
                return

        cmd = [
            sys.executable, LAB_SCRIPT,
            "--video", target["video"],
            "--clip-id", target["id"],
            "--player-id", target["player"],
            "--split", target["split"]
        ]
        print(f"\nRunning: {' '.join(cmd)}\n")
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nExited.")

if __name__ == "__main__":
    main()
