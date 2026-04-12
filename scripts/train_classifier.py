"""
Train a lightweight pair classifier from Stage-E sidecar data.

Usage:
    python scripts/train_classifier.py [--sidecar GLOB] [--out models/pair_classifier.pkl]

Inputs:
    runs/*/artifacts/sidecar.json  — block_features + label pairs produced by
                                     dedupe_frames(sidecar_path=...) (Card 4.2)

Output:
    models/pair_classifier.pkl  — scikit-learn GradientBoostingClassifier

The classifier predicts "progressive" (1) vs "different" (0) from the 48-dim
block-feature vector.  When the model file exists, dedupe_frames can load it
and use it to gate Stage-E merge decisions instead of the fixed threshold stack.
"""
from __future__ import annotations

import argparse
import glob
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"


def _load_sidecar_pairs(pattern: str) -> tuple[list[list[float]], list[int]]:
    X: list[list[float]] = []
    y: list[int] = []
    files = sorted(glob.glob(pattern, recursive=True))
    if not files:
        print(f"WARNING: no sidecar files matched pattern: {pattern}", file=sys.stderr)
        return X, y
    for fpath in files:
        try:
            data = json.loads(Path(fpath).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"WARNING: skipping unreadable sidecar {fpath}: {e}", file=sys.stderr)
            continue
        for pair in data.get("pairs", []):
            feats = pair.get("block_features")
            label = pair.get("label")
            if feats is None or label is None or len(feats) != 48:
                continue
            X.append([float(v) for v in feats])
            y.append(1 if label == "progressive" else 0)
    return X, y


def train(sidecar_pattern: str, out_path: Path) -> int:
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score
        import numpy as np
    except ImportError:
        print("ERROR: scikit-learn is required. Install with: pip install scikit-learn", file=sys.stderr)
        return 1

    X_raw, y = _load_sidecar_pairs(sidecar_pattern)
    if len(X_raw) < 10:
        print(f"ERROR: not enough training pairs ({len(X_raw)} found, need >= 10)", file=sys.stderr)
        return 1

    X = np.array(X_raw, dtype=np.float32)
    y_arr = np.array(y, dtype=np.int32)

    n_pos = int(y_arr.sum())
    n_neg = int(len(y_arr) - n_pos)
    print(f"Training pairs: {len(X_raw)} total  progressive={n_pos}  different={n_neg}")

    clf = GradientBoostingClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.1,
        random_state=42,
    )

    if len(X_raw) >= 20:
        cv = min(5, n_pos, n_neg) if min(n_pos, n_neg) >= 2 else 2
        scores = cross_val_score(clf, X, y_arr, cv=cv, scoring="f1")
        print(f"Cross-val F1 ({cv}-fold): {scores.mean():.4f} ± {scores.std():.4f}")

    clf.fit(X, y_arr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        pickle.dump(clf, f, protocol=4)

    print(f"Model saved: {out_path}")
    print(f"Feature importances (top 10):")
    importances = clf.feature_importances_
    top10 = sorted(enumerate(importances), key=lambda x: -x[1])[:10]
    for rank, (idx, imp) in enumerate(top10, 1):
        block = idx // 3
        metric = ["diff", "neg", "pos"][idx % 3]
        row, col = block // 4, block % 4
        print(f"  {rank:2d}. block[{row},{col}].{metric}  importance={imp:.4f}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Train pair classifier from Stage-E sidecar data")
    parser.add_argument(
        "--sidecar",
        default="runs/*/artifacts/sidecar.json",
        help="glob pattern for sidecar JSON files (default: runs/*/artifacts/sidecar.json)",
    )
    parser.add_argument(
        "--out",
        default=str(MODELS_DIR / "pair_classifier.pkl"),
        help="output path for trained classifier (default: models/pair_classifier.pkl)",
    )
    args = parser.parse_args()
    return train(sidecar_pattern=args.sidecar, out_path=Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
