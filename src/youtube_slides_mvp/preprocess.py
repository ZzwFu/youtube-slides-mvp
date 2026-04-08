from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps


def default_mask_profile() -> dict[str, Any]:
    return {
        "bottom_subtitle_ratio": 0.12,
        "progress_ratio": 0.03,
        "watermark_box_ratio": 0.18,
        "watermark_enabled": True,
        "speaker_box_ratio": 0.22,
        "speaker_enabled": True,
    }


def load_mask_profile(mask_config_path: Path | None) -> dict[str, Any]:
    profile = default_mask_profile()
    if mask_config_path is None:
        return profile
    if not mask_config_path.exists():
        return profile
    data = json.loads(mask_config_path.read_text(encoding="utf-8"))
    profile.update(data)
    return profile


def _apply_mask(arr: np.ndarray, profile: dict[str, Any]) -> np.ndarray:
    h, w = arr.shape
    out = arr.copy()

    subtitle_h = int(h * float(profile.get("bottom_subtitle_ratio", 0.12)))
    if subtitle_h > 0:
        out[h - subtitle_h :, :] = 0

    progress_h = int(h * float(profile.get("progress_ratio", 0.03)))
    if progress_h > 0:
        out[h - progress_h :, :] = 0

    if bool(profile.get("watermark_enabled", True)):
        box = int(min(w, h) * float(profile.get("watermark_box_ratio", 0.18)))
        if box > 0:
            out[h - box : h, w - box : w] = 0

    if bool(profile.get("speaker_enabled", True)):
        sw = int(w * float(profile.get("speaker_box_ratio", 0.22)))
        sh = int(h * float(profile.get("speaker_box_ratio", 0.22)))
        if sw > 0 and sh > 0:
            out[h - sh : h, w - sw : w] = 0

    return out


def preprocess_frames(
    input_frames: list[Path],
    out_dir: Path,
    profile: dict[str, Any],
    target_size: tuple[int, int] = (1280, 720),
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    for frame in sorted(input_frames):
        img = Image.open(frame).convert("L")
        img = ImageOps.autocontrast(img)
        img = img.resize(target_size, Image.Resampling.BILINEAR)
        arr = np.asarray(img, dtype=np.uint8)
        masked = _apply_mask(arr, profile)
        out_img = Image.fromarray(masked)
        out_path = out_dir / frame.name
        out_img.save(out_path, format="JPEG", quality=95)
        outputs.append(out_path)

    return outputs


def write_mask_profile(path: Path, profile: dict[str, Any]) -> None:
    path.write_text(json.dumps(profile, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
