from pathlib import Path

import numpy as np
from PIL import Image

from src.youtube_slides_mvp.scene import detect_scene_driven_windows


def test_detect_scene_driven_windows_progressive_run(tmp_path: Path) -> None:
    paths = []
    rows = []
    base = np.zeros((144, 256), dtype=np.uint8)

    for i in range(8):
        arr = base.copy()
        # Progressive reveal: each frame adds a brighter stripe.
        arr[:, : (i + 1) * 24] = 120
        p = tmp_path / f"frame_{i:06d}.jpg"
        Image.fromarray(arr).save(p, format="JPEG")
        paths.append(p)
        rows.append({"frame_name": p.name, "timestamp_sec": float(i * 2)})

    windows = detect_scene_driven_windows(
        paths,
        rows,
        min_pair_run=3,
        progressive_diff_th=0.12,
        progressive_hash_th=64,
        progressive_cover_th=0.70,
        progressive_add_th=0.50,
    )
    assert windows
    assert windows[0]["reason"] == "scene-progressive-run"
