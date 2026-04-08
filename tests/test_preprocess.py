from pathlib import Path

import numpy as np
from PIL import Image

from src.youtube_slides_mvp.preprocess import default_mask_profile, preprocess_frames


def test_preprocess_masks_bottom_region(tmp_path: Path) -> None:
    src = tmp_path / "frame_000001.jpg"
    arr = np.full((120, 200), 200, dtype=np.uint8)
    Image.fromarray(arr).save(src, format="JPEG")

    out_dir = tmp_path / "out"
    paths = preprocess_frames([src], out_dir, default_mask_profile(), target_size=(200, 120))
    out = np.asarray(Image.open(paths[0]).convert("L"))
    assert out.shape == (120, 200)
    assert int(out[-1, 100]) == 0
