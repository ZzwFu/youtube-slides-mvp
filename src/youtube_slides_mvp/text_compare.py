from __future__ import annotations


def _normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return " ".join(text.lower().split())


def compare_text_prefix(
    text_a: str,
    text_b: str,
    min_prefix_len: int = 20,
    different_jaccard_th: float = 0.20,
    different_min_words: int = 5,
) -> str:
    """Compare two OCR text strings to determine progressive-reveal relationship.

    Returns:
        "progressive" — one text is a prefix of the other, indicating a
                        progressive-reveal (same slide, more content added).
        "different"   — texts share too few words to be from the same slide.
        "unknown"     — insufficient signal (empty, too short, or ambiguous).

    This is used as a first-priority guard in _is_additive and the Phase 2
    FSM collapse: if OCR says "different", block the merge regardless of pixel
    metrics; if OCR says "progressive", allow it without running pixel checks.
    p13/14 and p38/39 are expected to return "different" here (non-prefix
    relationship), preventing incorrect merge even when pixel metrics are close.
    """
    a = _normalize_text(text_a)
    b = _normalize_text(text_b)

    if not a or not b:
        return "unknown"

    # Prefix check: shorter string must be a text prefix of the longer one.
    # Handles both reveal directions (a→b or b→a).
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if longer.startswith(shorter) and len(shorter) >= min_prefix_len:
        return "progressive"

    # Word-level Jaccard: if overlap is below threshold and both sides have
    # enough words, the slides are clearly different.
    words_a = set(a.split())
    words_b = set(b.split())
    if len(words_a) >= different_min_words and len(words_b) >= different_min_words:
        union = words_a | words_b
        jaccard = len(words_a & words_b) / len(union)
        if jaccard < different_jaccard_th:
            return "different"

    return "unknown"


def signals_to_text_map(signals: list) -> dict[str, str]:
    """Convert a list of OcrSignal objects to {frame_name: fingerprint} for fast lookup."""
    return {s.frame_name: s.fingerprint for s in signals}
