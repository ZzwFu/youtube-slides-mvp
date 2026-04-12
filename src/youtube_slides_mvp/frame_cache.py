from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


class FrameCache:
    """Shared LRU-like in-memory cache for grayscale frame arrays.

    Eliminates the duplicated ``_load`` + ``cache: dict`` pattern that
    previously appeared 6 times across cli.py.  All post-processing
    functions (_refill_gaps, _complete_pages, _cleanup_close_pairs) share
    the same resize target (256x144) and dtype (uint8).

    Usage:
        fc = FrameCache()
        arr = fc.get(path)        # loads & caches on first call
        arr = fc.get_name(name, frames_raw_dir)  # load by filename from dir
    """

    _SIZE: tuple[int, int] = (256, 144)

    def __init__(self) -> None:
        self._cache: dict[str, np.ndarray] = {}

    def get(self, path: Path) -> np.ndarray:
        key = path.name
        if key not in self._cache:
            img = Image.open(path).convert("L").resize(self._SIZE, Image.Resampling.BILINEAR)
            self._cache[key] = np.asarray(img, dtype=np.uint8)
        return self._cache[key]

    def get_name(self, name: str, directory: Path) -> np.ndarray | None:
        """Load by filename from a directory; returns None if file absent."""
        if name in self._cache:
            return self._cache[name]
        path = directory / name
        if not path.exists():
            return None
        return self.get(path)

    def contains(self, name: str) -> bool:
        return name in self._cache

    def clear(self) -> None:
        self._cache.clear()
