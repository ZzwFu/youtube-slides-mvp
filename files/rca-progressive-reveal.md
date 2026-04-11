# RCA Report: Progressive-Reveal Dedup & Gap-Fill

## Problem Statement

The 68-page baseline (`iterative none`, run `slide-20260409-121905`) had missing pages in
wide gaps between selected slides. The confidence mode (`iterative confidence`) was designed
to fill those gaps, but initial implementations either introduced duplicate intermediate
frames or failed to detect genuinely missing pages.

**Target**: fill all genuinely missing pages without introducing progressive-reveal
intermediate duplicates, using purely content-based (not time-based) decisions.

## Timeline of Iterations

### Phase 1: Original Greedy Scoring (pre-debug)
- **Approach**: Pick frame with max min-diff from accumulated anchors.
- **Problem**: No progressive-reveal awareness. Intermediate frames score high on novelty.
- **Outcome**: 73-page version with duplicates.

### Phase 2: Mini-FSM Architecture (tag `debug-mini-fsm-87`, 87 pages)
- **Key insight**: Replace greedy scoring with sequential walk that groups consecutive
  additive frames, keeps last (most complete) per group.
- **Changes**:
  - Mini-FSM walk: groups frames where `is_additive(group_base, candidate)` OR
    `is_additive(current_rep, candidate)`
  - Endpoint pruning: drop groups whose rep is additive toward right endpoint B
  - Left-endpoint pruning: drop first group if additive from A
  - `bridge_min_gap_sec=40`, `score=far`, `novelty_th=0.04`, `max_rounds=2`
- **Outcome**: 87 pages, 19 fills, all correct. User confirmed direction.

### Phase 3: Bridge Gate Reduction (tag `debug-mini-fsm-88`, 88 pages)
- **Change**: `bridge_min_gap_sec: 40 → 15`
- **Outcome**: Added 102s fill in p6→p7 gap.
- **Problem**: 102s is intermediate frame (complete frame at 104-111s). False fill.

### Phase 4: Root Cause Analysis of Two Failures
- **102s issue**: In 95→110 gap, mini-FSM forms G0(96-102) and G1(103-109).
  G1 rep(109s) additive to B(110s) → pruned. G0 rep(102s) survives but is intermediate.
  Root cause: 102→B has da=0.355 (barely fails additive threshold 0.35).
- **1808s issue**: In 1790→1829 gap, `is_add_to_base` check keeps group_base=1791s
  throughout, merging all 38 frames into one group. Even 1809s (genuinely new content)
  is additive to 1791s. Group rep=1828s additive to B → entire group pruned.
  Root cause: group_base spans too wide; endpoint pruning is too coarse.

### Phase 5: Fix 1+2+3 Combined (91 pages, REJECTED)
- **Fix 1**: Remove group_base, only check `is_additive(current_rep, candidate)`
- **Fix 2**: Reverse-scan within group for last frame NOT additive to B
- **Fix 3**: Group-bridge pruning (drop prev group if rep additive to next group's rep)
- **Outcome**: 91 pages, 4 extra false fills (268, 335, 1123, 1776). Overfilled.
- **Root cause**: Fix 2 changes rep selection, allowing borderline intermediates to survive.

### Phase 6: Fix 1 Only (tag `debug-mini-fsm-88-fix1`, 88 pages)
- **Approach**: Apply only Fix 1 (rep-only grouping), keep original endpoint pruning.
- **Outcome**: 88 pages, +1 fill (1123s, correct). 87-page baseline fully preserved.
- **Key learning**: Fix 2 (reverse-scan) was the source of false fills.

### Phase 7: Bridge Gate = 39 (89 pages, confirmed)
- User changed `bridge_min_gap_sec: 40 → 39` to allow 1790→1829 gap (dt=39s).
- **Outcome**: 89 pages, +2 fills (1123s, 1808s), both correct.
- **User concern**: Why does a content decision depend on a time threshold?

### Phase 8: Content-Based Endpoint Proximity Pruning (tag `debug-mini-fsm-89-content-gate`, 89 pages)
- **Key insight**: Replace time-based bridge gate entirely with content-based pruning.
- **Approach**: Strengthen endpoint pruning with proximity check:
  - Canonical `_is_additive` check (unchanged)
  - New: if `diff(rep, endpoint) ≤ 0.07 AND neg ≤ 0.008`, also prune.
- **Data-driven thresholds**:
  - False fills (102s, 697s, 701s): neg ≤ 0.007, close to one endpoint.
  - Legit fills (1293s, 1523s, etc.): neg ≥ 0.010, genuine content replacement.
  - Gap: 0.007 vs 0.010 → clear separation at threshold 0.008.
- **Removed**: `bridge_min_gap_sec`, `min_endpoint_dc` parameters.
- **Outcome**: 89 pages, identical to bridge=39 version but fully content-based.

## Root Causes (Summary)

| Issue | Root Cause | Fix Applied |
|-------|-----------|-------------|
| Intermediate frames selected | Greedy scoring, no reveal awareness | Mini-FSM walk |
| 1808s not extracted | group_base spans too wide, merges unlike frames | Fix 1: rep-only grouping |
| 102s false fill | da=0.355 barely fails 0.35 threshold | Proximity pruning (diff+neg) |
| 697/701s false fills | Low-dc gap opened by removing bridge gate | Proximity pruning |
| Time-based bridge gate | Arbitrary time threshold, not content-based | Replaced with proximity pruning |

## Key Technical Insights

1. **Additive test is the core primitive**: `diff ≤ 0.10, neg ≤ 0.002, dc ≥ 0.60, da ≤ 0.35`.
   Works for both progressive reveal and gap fill.

2. **Group membership should only check previous frame** (not group base). When group_base
   stays fixed across many frames, even unrelated content can appear "additive" if viewed from
   the base's perspective.

3. **Endpoint pruning needs two layers**:
   - Strict: canonical additive test
   - Soft: proximity (diff ≤ 0.07, neg ≤ 0.008) for borderline cases where thresholds
     are barely exceeded.

4. **Content beats time**: The bridge_min_gap_sec was an unreliable proxy for "is there
   a hidden page in this gap?" Content-based checks (additive + proximity) are both more
   accurate and more generalizable.

5. **neg (negative directional change)** is the single best discriminator between "same slide,
   slightly evolved" (neg ≤ 0.007) and "different slide, content replaced" (neg ≥ 0.010).

## Final State

- **Code**: `cli.py` at commit `5fc8e2d`, tag `debug-mini-fsm-89-content-gate`
- **Product**: 89 pages from `slide-20260409-022438` test video
- **Fills**: 21 correct fills, 0 false fills, 0 regressions vs 68-page baseline
- **Parameters removed**: `bridge_min_gap_sec`, `min_endpoint_dc`
- **Parameters added**: `ep_prune_diff=0.07`, `ep_prune_neg=0.008`

## Git Tags Reference

| Tag | Pages | Description |
|-----|-------|-------------|
| `debug-mini-fsm-87` | 87 | First mini-FSM, all fills correct |
| `debug-mini-fsm-88` | 88 | bridge=15, introduced 102s false fill |
| `debug-mini-fsm-91-fix12` | 91 | Fix 1+2, 4 false fills (rejected) |
| `debug-mini-fsm-88-fix1` | 88 | Fix 1 only, +1 correct fill |
| `debug-mini-fsm-89-content-gate` | 89 | Final: content-based, no time gate |

---

# RCA Report: Fade-In/Fade-Out Slide Support

## Problem Statement

A new test video (`slide-20260410-135526`) uses fade transitions between slides instead of
hard cuts. The progressive-reveal pipeline (tag `debug-mini-fsm-89-content-gate`) produced
61 pages with three categories of failure:
1. First slide (0–9s) was missing entirely
2. Fade-blend frames survived as slide representatives (p7/p8)
3. An intermediate slide (86–88s) was destroyed by a false Stage E merge

**Target**: extract all clean slides with zero fade artifacts while keeping V1 (89 pages) unchanged.

## Anatomy of a Fade Transition

```
stable_A → fade_start → fade_mid → fade_end → stable_B
  (clean)   (bidir≈0.02)  (bidir≈0.06)          (clean)
```

Key geometric property: a fade-midpoint `f` satisfies `d(A,f)+d(f,B) ≈ d(A,B)` —
**betweenness ≈ 1.0**. Progressive-reveal intermediates have betweenness > 2.0 (extra
content pushed them off the line). This is the core discriminator.

## Failures and Root Causes

### Failure 1: First Slide Missing (p1 = 0–9s)
- **Root cause**: Stage E (secondary merge) merged slot 9 into slot 25 because frame
  9 is additive-like to frame 25 (same template, dc=0.82, neg≈0, da=0.18).
  The merge crossed a page boundary because both frames come from the same visual template.
- **Fix**: Cross-template guard in Stage E — block secondary merges where the pair shows
  balanced bidirectional change (bal ≥ 0.45) + low dark_cover (dc < 0.80) + significant
  dark_additive (da > 0.10). True additive reveals are unidirectional (balance ≈ 0, dc ≈ 1.0).

### Failure 2: Fade-Blend Frames as Representatives (p7 at 80s, p8 at 84s)
- **Root cause**: Stage A picks the LAST frame of each merge run. In a stable-then-fade
  sequence, Stage A slurps the fade-start into the preceding slot (d < 0.035), making a
  fade-start frame the representative.
- **Fix (Stage A′, Pass 1)**: If `d(rep-1, rep) ∈ (0.01, 0.035)` and prev→rep shows
  balanced bidir change (neg,pos ≥ 0.005, bal ≥ 0.40), roll back to rep-1. Genuine
  progressive-reveal last-steps are unidirectional (bal < 0.01).
- **Additional case (Stage A′, Pass 2)**: Some reps drift only subtly (d ≈ 0.003–0.008)
  into a fade zone. Confirm fade-out after rep (d_next > 0.02, balanced), then walk back
  while each step shows tiny bidirectional drift (0.002 < d < 0.01). Zero V1 false positives.

### Failure 3: Intermediate Slide Destroyed (86–88s)
- **Root cause**: After Stage D′ removes the fade-midpoint at 84s, Stage E secondary merge
  consumed frame 87 (86–88s intermediate slide) into frame 100 (a completely different later
  slide). They shared a visual template (similar layout) causing additive-like metrics.
- **Fix**: Cross-template guard (same as Failure 1 fix) — see above.

### Failure 4 (addressed): Fade-Midpoint Frames in Output
- **Root cause**: Stage C/D transitions only remove clean hard-cut midpoints. Fade frames
  have low-but-nonzero betweenness and balanced bidir change that the original C check missed.
- **Fix (Stage D′)**: Iterative fade-midpoint removal. For each triplet (A, B, C): if
  betweenness(B) ≤ 1.15 AND d(A,B) ≤ 0.12 AND both neg,pos ≥ 0.008 AND balance ≥ 0.40,
  remove B. Loop until convergence.

## Implementation Summary

| Stage | Change | Discriminator |
|-------|--------|---------------|
| D′ (new) | Fade-midpoint removal | betweenness ≤ 1.15 + balanced bidir |
| A′ Pass 1 | Clear fade-start rollback | d(prev,rep) > 0.01, bal ≥ 0.40 |
| A′ Pass 2 | Subtle fade-drift rollback | fade-out after rep + tiny bidir drift walk-back |
| E guard (new) | Cross-template secondary block | bal ≥ 0.45, dc < 0.80, da > 0.10 |

## Key Separators (V1 vs V2)

| Feature | V1 progressive reveal | V2 fade transition |
|---------|----------------------|-------------------|
| Bidir balance (secondary merge) | bal < 0.35 (mostly < 0.01) | bal ≥ 0.45 |
| Dark cover (secondary merge) | dc ≥ 0.83 | dc ≤ 0.80 |
| Betweenness (triplet midpoint) | > 2.0 | ≤ 1.15 |
| Stage A drift balance | mostly unidirectional | bal ≥ 0.35 in fade zone |

All thresholds have clear gaps between V1 and V2 — no regime overlap found.

## Final State

- **Code**: `dedupe.py` at commit `6ace1f7`, tag `debug-fade-rollback-p2-62pg`
- **V1 product**: 89 pages (zero regression)
- **V2 product**: 62 pages, zero fade artifacts, zero missing pages
- **Parameters added**: `fade_betweenness_max`, `fade_bidir_min`, `fade_diff_max`,
  `fade_balance_min`, `fade_blend_min`, `fade_blend_bidir`, `fade_drift_min`,
  `fade_drift_max`, `fade_drift_bidir`, `fade_out_min`, `fade_out_bal_min`,
  `fade_out_bidir`, `fade_drift_max_walk`, `cross_template_balance_min`,
  `cross_template_dc_max`, `cross_template_da_min`

## Git Tags Reference (Fade Work)

| Tag | V1 | V2 | Description |
|-----|----|----|-------------|
| `debug-fade-detect-62pg` | 89 | 62 | Stage D′ only (committed) |
| `debug-cross-template-62pg` | 89 | 62 | + A′ Pass 1 + cross-template guard |
| `debug-fade-rollback-p2-62pg` | 89 | 62 | + A′ Pass 2 (subtle drift) — final |
