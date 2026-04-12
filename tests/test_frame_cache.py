from pathlib import Path

import numpy as np
from PIL import Image

from src.youtube_slides_mvp.frame_cache import FrameCache


def _write_frame(path: Path, value: int) -> None:
    arr = np.full((144, 256), value, dtype=np.uint8)
    Image.fromarray(arr).save(path, format="JPEG")


def test_frame_cache_get_returns_array(tmp_path: Path) -> None:
    f = tmp_path / "frame_000001.jpg"
    _write_frame(f, 100)
    fc = FrameCache()
    arr = fc.get(f)
    assert isinstance(arr, np.ndarray)
    assert arr.dtype == np.uint8
    assert arr.shape == (144, 256)


def test_frame_cache_get_caches(tmp_path: Path) -> None:
    f = tmp_path / "frame_000001.jpg"
    _write_frame(f, 100)
    fc = FrameCache()
    arr1 = fc.get(f)
    arr2 = fc.get(f)
    assert arr1 is arr2  # same object from cache


def test_frame_cache_get_name_missing_returns_none(tmp_path: Path) -> None:
    fc = FrameCache()
    result = fc.get_name("nonexistent.jpg", tmp_path)
    assert result is None


def test_frame_cache_get_name_loads_from_dir(tmp_path: Path) -> None:
    f = tmp_path / "frame_000002.jpg"
    _write_frame(f, 200)
    fc = FrameCache()
    arr = fc.get_name("frame_000002.jpg", tmp_path)
    assert arr is not None
    assert arr.shape == (144, 256)


def test_frame_cache_contains(tmp_path: Path) -> None:
    f = tmp_path / "frame_000001.jpg"
    _write_frame(f, 100)
    fc = FrameCache()
    assert not fc.contains("frame_000001.jpg")
    fc.get(f)
    assert fc.contains("frame_000001.jpg")


def test_frame_cache_clear(tmp_path: Path) -> None:
    f = tmp_path / "frame_000001.jpg"
    _write_frame(f, 100)
    fc = FrameCache()
    fc.get(f)
    assert fc.contains("frame_000001.jpg")
    fc.clear()
    assert not fc.contains("frame_000001.jpg")
