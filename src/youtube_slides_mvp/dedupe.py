from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class DedupeConfig:
    adjacent_diff_th: float = 0.035
    adjacent_hash_th: int = 8
    reveal_cover_th: float = 0.92
    reveal_add_th: float = 0.18
    transition_mid_th: float = 0.09
    # Stage C: a "midpoint" cannot be classified as a transition if it was
    # held for this many or more original frames in Stage A (i.e. it represents
    # real content, not a brief flash between two dark frames).
    transition_min_hold: int = 3
    progressive_lookback: int = 20
    progressive_diff_th: float = 0.06
    progressive_hash_th: int = 10
    progressive_cover_th: float = 0.95
    progressive_add_th: float = 0.24
    # Stage E secondary: "additive progressive reveal" on light-background slides.
    # Fires when the primary bright-pixel coverage check misses pairs where new
    # content was added as bright pixels (neg ≈ 0, pos >> 0, dark text preserved).
    additive_reveal_diff_th: float = 0.12
    additive_neg_max: float = 0.025
    additive_dark_cover_th: float = 0.70
    additive_dark_add_th: float = 0.25
    # Stage F: chain-based progressive-reveal collapse.
    # Frames are merged into a chain as long as each step diff is small AND
    # the total drift from the chain anchor stays below chain_anchor_max.
    # Only the final (most-complete) state of each chain is kept.
    chain_step_th: float = 0.060
    chain_anchor_max: float = 0.15
    chain_direction_ratio: float = 0.72
    # Stage G: motion-ratio stable-segment collapse.
    # Walk Stage-F output and track runs of consecutive frame-pairs whose
    # "motion ratio" (fraction of pixels with |diff| > motion_th) stays
    # below motion_ratio_th. Only the tail (most-settled) frame of each run
    # that is long enough (>= min_stable_frames) is kept.
    motion_th: float = 15.0        # pixel-diff to count a pixel as "moving"
    motion_ratio_th: float = 0.025 # fraction below which a pair is "stable"
    min_stable_frames: int = 3     # minimum run length to trigger collapse


def _load_gray(path: Path, size: tuple[int, int] = (256, 144)) -> np.ndarray:
    img = Image.open(path).convert("L").resize(size, Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.uint8)


def _hash_bits(gray: np.ndarray) -> np.ndarray:
    small = gray.reshape(12, gray.shape[0] // 12, 16, gray.shape[1] // 16).mean(axis=(1, 3))
    return (small > small.mean()).reshape(-1)


def _hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def _diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)


def _reveal(prev: np.ndarray, curr: np.ndarray) -> tuple[float, float]:
    pm = prev >= np.percentile(prev, 70)
    cm = curr >= np.percentile(curr, 70)
    prev_n = int(pm.sum())
    curr_n = int(cm.sum())
    if prev_n == 0 or curr_n == 0:
        return 0.0, 1.0
    inter = int(np.logical_and(pm, cm).sum())
    add = int(np.logical_and(~pm, cm).sum())
    return inter / float(prev_n), add / float(curr_n)


def _directional_change(prev: np.ndarray, curr: np.ndarray) -> tuple[float, float]:
    """Return one-way normalized change magnitudes.

    Values are normalized to [0, 1] by dividing by 255.
    """
    delta = curr.astype(np.float32) - prev.astype(np.float32)
    neg = float(np.mean(np.clip(-delta, 0, None)) / 255.0)
    pos = float(np.mean(np.clip(delta, 0, None)) / 255.0)
    return neg, pos


def _motion_ratio(a: np.ndarray, b: np.ndarray, motion_th: float = 15.0) -> float:
    """Fraction of pixels where |a - b| exceeds motion_th."""
    return float((np.abs(a.astype(np.float32) - b.astype(np.float32)) > motion_th).mean())


def _dark_cover(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Dark-pixel coverage: fraction of a's text/dark content preserved in b, and fraction new.

    For light-background slides, dark pixels represent text.  A high cover with
    low add means b is a progressive-reveal superset of a.
    """
    pm = a <= np.percentile(a, 30)
    cm = b <= np.percentile(b, 30)
    pn = int(pm.sum())
    cn = int(cm.sum())
    if pn == 0 or cn == 0:
        return 0.0, 1.0
    inter = int(np.logical_and(pm, cm).sum())
    new   = int(np.logical_and(~pm, cm).sum())
    return inter / float(pn), new / float(cn)


def _sorted_unique(idx: list[int]) -> list[int]:
    if not idx:
        return []
    return sorted(set(idx))


def dedupe_frames(paths: list[Path], cfg: DedupeConfig) -> tuple[list[Path], dict[str, int]]:
    if not paths:
        return [], {"input": 0, "after_a": 0, "after_c": 0, "after_d": 0}

    arrays = [_load_gray(p) for p in paths]
    hashes = [_hash_bits(a) for a in arrays]

    # Stage A/B: adjacent compression + reveal merge
    keep_idx = [0]
    for i in range(1, len(paths)):
        j = keep_idx[-1]
        d = _diff(arrays[j], arrays[i])
        hd = _hamming(hashes[j], hashes[i])
        cover, add = _reveal(arrays[j], arrays[i])

        merge = False
        if d <= cfg.adjacent_diff_th and hd <= cfg.adjacent_hash_th:
            merge = True
        elif cover >= cfg.reveal_cover_th and add <= cfg.reveal_add_th and d <= 0.12:
            merge = True

        if merge:
            keep_idx[-1] = i
        else:
            keep_idx.append(i)

    # Stage C: drop transition midpoint if previous and next are close but current differs strongly.
    # Guard: if this Stage-A slot represents >= transition_min_hold original frames the content
    # was held long enough to be real — don't classify it as a brief transition midpoint.
    c_idx = [keep_idx[0]]
    for k in range(1, len(keep_idx) - 1):
        p = keep_idx[k - 1]
        c = keep_idx[k]
        n = keep_idx[k + 1]
        hold = c - p  # number of original frames collapsed into this Stage-A slot
        d_pc = _diff(arrays[p], arrays[c])
        d_cn = _diff(arrays[c], arrays[n])
        d_pn = _diff(arrays[p], arrays[n])
        is_mid = (
            hold < cfg.transition_min_hold
            and d_pc > cfg.transition_mid_th
            and d_cn > cfg.transition_mid_th
            and d_pn < cfg.adjacent_diff_th
        )
        if not is_mid:
            c_idx.append(c)
    if len(keep_idx) > 1:
        c_idx.append(keep_idx[-1])

    # Stage D: final rendered-sequence dedupe
    out_idx = [c_idx[0]] if c_idx else []
    for i in c_idx[1:]:
        j = out_idx[-1]
        d = _diff(arrays[j], arrays[i])
        hd = _hamming(hashes[j], hashes[i])
        if d <= cfg.adjacent_diff_th and hd <= cfg.adjacent_hash_th:
            out_idx[-1] = i
        else:
            out_idx.append(i)

    # Stage E: lookback progressive merge for repeated reveal-like pages.
    # Primary check: bright-pixel coverage (works for dark-bg + light-text slides).
    # Secondary check: additive-reveal detection for light-bg + dark-text slides where
    # new content appears as bright pixels (neg ≈ 0, pos >> 0, dark text preserved).
    e_idx: list[int] = []
    for i in out_idx:
        merged = False
        for back in range(len(e_idx) - 1, max(-1, len(e_idx) - 1 - cfg.progressive_lookback), -1):
            j = e_idx[back]
            d = _diff(arrays[j], arrays[i])
            hd = _hamming(hashes[j], hashes[i])
            cover, add = _reveal(arrays[j], arrays[i])
            primary = (
                d <= cfg.progressive_diff_th
                and hd <= cfg.progressive_hash_th
                and cover >= cfg.progressive_cover_th
                and add <= cfg.progressive_add_th
            )
            if not primary:
                neg, pos = _directional_change(arrays[j], arrays[i])
                dc, da = _dark_cover(arrays[j], arrays[i])
                secondary = (
                    d <= cfg.additive_reveal_diff_th
                    and neg <= cfg.additive_neg_max
                    and dc >= cfg.additive_dark_cover_th
                    and da <= cfg.additive_dark_add_th
                )
            else:
                secondary = False
            if primary or secondary:
                e_idx[back] = i
                merged = True
                break
        if not merged:
            e_idx.append(i)

    # Lookback replacement can mutate an earlier slot with a later frame index.
    # Normalize indices to keep output chronological.
    e_idx = _sorted_unique(e_idx)

    selected = [paths[i] for i in e_idx]
    stats = {
        "input": len(paths),
        "after_a": len(keep_idx),
        "after_c": len(c_idx),
        "after_d": len(out_idx),
        "after_e": len(e_idx),
    }

    # Stage F: chain-based progressive-reveal collapse.
    # Walk the Stage-E output in order. Maintain a running "chain anchor" —
    # the first frame of the current progressive-reveal run. Extend the chain
    # (replace the last kept index) while both:
    #   • adjacent step diff ≤ chain_step_th  (small incremental change)
    #   • anchor diff ≤ chain_anchor_max       (total drift stays bounded)
    # When either condition breaks, commit the current chain tail and start a
    # new chain. This keeps only the final (most-complete) state per run.
    f_idx: list[int] = []
    chain_anchor_idx: int = -1

    for i in e_idx:
        if not f_idx:
            f_idx.append(i)
            chain_anchor_idx = i
            continue
        j = f_idx[-1]
        d_step = _diff(arrays[j], arrays[i])
        d_anchor = _diff(arrays[chain_anchor_idx], arrays[i])
        neg, pos = _directional_change(arrays[j], arrays[i])
        total = neg + pos
        if total <= 1e-9:
            dominant_ratio = 1.0
        else:
            dominant_ratio = max(neg, pos) / total

        # Guardrail against missing pages:
        # balanced two-way changes are more likely a true content replacement
        # than a progressive reveal chain.
        if (
            d_step <= cfg.chain_step_th
            and d_anchor <= cfg.chain_anchor_max
            and dominant_ratio >= cfg.chain_direction_ratio
        ):
            f_idx[-1] = i  # advance chain tail to the more-complete frame
        else:
            f_idx.append(i)  # new chain starts here
            chain_anchor_idx = i

    f_idx = _sorted_unique(f_idx)

    stats["after_f"] = len(f_idx)

    # Stage G: motion-ratio stable-segment collapse.
    # Walk Stage-F output and identify runs of consecutive frame-pairs that
    # have very little pixel motion (slide is still settling / progressive
    # reveal finishing). Keep only the tail (most-complete) frame of each
    # run long enough to be a genuine reveal sequence.
    if len(f_idx) < 2:
        g_idx: list[int] = list(f_idx)
    else:
        g_run: list[int] = [f_idx[0]]
        g_idx = []
        for i in f_idx[1:]:
            j = g_run[-1]
            mr = _motion_ratio(arrays[j], arrays[i], cfg.motion_th)
            if mr < cfg.motion_ratio_th:
                g_run.append(i)       # extend stable run
            else:
                # motion spike: commit the current stable run
                if len(g_run) >= cfg.min_stable_frames:
                    g_idx.append(g_run[-1])  # keep tail (most settled)
                else:
                    g_idx.extend(g_run)       # short run: keep all
                g_run = [i]           # new run starts with trigger frame
        # commit the final run
        if len(g_run) >= cfg.min_stable_frames:
            g_idx.append(g_run[-1])
        else:
            g_idx.extend(g_run)
        g_idx = _sorted_unique(g_idx)

    stats["after_g"] = len(g_idx)
    selected = [paths[i] for i in g_idx]
    return selected, stats