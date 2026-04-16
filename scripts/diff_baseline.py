"""Diff a run against a benchmark baseline and report OCR deltas."""
import argparse
import difflib
import json
import shutil
import subprocess
from pathlib import Path


def unique_paths(paths):
    seen = set()
    result = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def baseline_run_dirs(b_data):
    candidates = []
    for key in ("approved_run_id", "benchmark_id", "source_run_id"):
        run_id = b_data.get(key)
        if isinstance(run_id, str) and run_id:
            candidates.append(Path("runs") / run_id)
    return unique_paths(candidates)


def resolve_frame_path(frame_name, run_dirs):
    for run_dir in run_dirs:
        for subdir in ("frames_raw", "frames_norm"):
            img_path = run_dir / subdir / frame_name
            if img_path.exists():
                return img_path
    return None


def ocr_with_tesseract(img_path, lang):
    binary = shutil.which("tesseract")
    if binary is None:
        return None, "tesseract is not installed. Install it with brew install tesseract"

    language_candidates = []
    if isinstance(lang, str) and lang.strip():
        language_candidates.append(lang.strip())
        primary_lang = lang.split("+", 1)[0].strip()
        if primary_lang and primary_lang not in language_candidates:
            language_candidates.append(primary_lang)
    if "eng" not in language_candidates:
        language_candidates.append("eng")

    errors = []
    for candidate_lang in language_candidates:
        proc = subprocess.run(
            [binary, str(img_path), "stdout", "-l", candidate_lang, "--psm", "6"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            text = "\n".join(line for line in proc.stdout.splitlines() if line.strip())
            return text, None
        stderr = proc.stderr.strip()
        if stderr:
            errors.append(f"{candidate_lang}: {stderr}")

    if errors:
        return None, "; ".join(errors)
    return None, "tesseract failed without a readable error"


def get_ocr(frame_name, run_dirs, lang):
    """Run OCR on a given frame and return the cleaned text."""
    img_path = resolve_frame_path(frame_name, run_dirs)
    if img_path is None:
        checked = ", ".join(str(run_dir / "frames_raw" / frame_name) for run_dir in run_dirs)
        return f"[Image missing: {frame_name}; checked: {checked}]"

    try:
        text, error = ocr_with_tesseract(img_path, lang)
    except Exception as exc:
        return f"[OCR error: {exc}]"

    if error is not None:
        return f"[OCR error: {error}]"

    return text

def text_diff(text1, text2):
    """Return unified diff of two text blocks."""
    lines1 = text1.splitlines()
    lines2 = text2.splitlines()
    diff = difflib.unified_diff(lines1, lines2, fromfile="baseline", tofile="run", lineterm='')
    return '\n'.join(diff)

def main():
    parser = argparse.ArgumentParser(description="Diff output against baseline with OCR support.")
    parser.add_argument('--baseline', default='benchmarks/slide-20260410-122639/expected_pages.json', help='The expected baseline JSON.')
    parser.add_argument('--run', default='runs/slide-v3-full-progressive', help='The run directory outcome to evaluate.')
    parser.add_argument('--ocr-lang', default='eng+chi_sim', help='Tesseract language string for OCR checks.')
    args = parser.parse_args()

    # Load baseline
    baseline_path = Path(args.baseline)
    run_path = Path(args.run)

    with baseline_path.open(encoding='utf-8') as f:
        b_data = json.load(f)
    baseline = b_data['pages']
    
    # "tolerance时间从基准文件重载" (load tolerance time from baseline file)
    tolerance = b_data.get('tolerance_ms', 2000.0) / 1000.0
    baseline_dirs = baseline_run_dirs(b_data)
    if not baseline_dirs:
        baseline_dirs = [baseline_path.parent]

    with (run_path / 'artifacts' / 'slides.json').open(encoding='utf-8') as f:
        v3_full = json.load(f)['slides']

    b_ts = [(p['timestamp_sec'], p.get('frame_name', '')) for p in baseline]
    v_ts = [(s['timestamp_sec'], s.get('frame_name', '')) for s in v3_full]

    print(f"Baseline: {len(b_ts)} pages (from {args.baseline})")
    print(f"Run:      {len(v_ts)} pages (from {args.run})")
    print(f"Tolerance: {tolerance}s")
    print(f"Baseline OCR sources: {', '.join(str(path) for path in baseline_dirs)}")
    print(f"Run OCR source: {run_path}")

    matched_v = set()
    matches = []
    missing = []
    for i, (bt, bn) in enumerate(b_ts):
        found_j = -1
        for j, (vt, vn) in enumerate(v_ts):
            if j not in matched_v and abs(bt - vt) <= tolerance:
                matched_v.add(j)
                found_j = j
                break
        if found_j != -1:
            matches.append((i, bt, bn, found_j, v_ts[found_j][0], v_ts[found_j][1]))
        else:
            missing.append((i, bt, bn))

    extra = []
    for j, (vt, vn) in enumerate(v_ts):
        if j not in matched_v:
            extra.append((j, vt, vn))

    # "引入ocr检查出现变化页面的区别" (and introduce OCR checking for the difference between changed pages)
    if matches:
        changed = [(bp, bt, bn, vp, vt, vn) for (bp, bt, bn, vp, vt, vn) in matches if bn != vn]
        if changed:
            print(f"\nCHANGED FRAMES on MATCHED pages ({len(changed)}):")
            for bp, bt, bn, vp, vt, vn in changed:
                print(f"  baseline p{bp+1} (t={bt:.1f}s, {bn}) != run p{vp+1} (t={vt:.1f}s, {vn})")
                ocr_b = get_ocr(bn, baseline_dirs, args.ocr_lang)
                ocr_v = get_ocr(vn, [run_path], args.ocr_lang)
                diff = text_diff(ocr_b, ocr_v)
                if diff.strip():
                    print("    OCR Diff vs Run:")
                    for line in diff.splitlines():
                        print(f"      {line}")
                else:
                    print("    OCR identical.")

    print(f"\nMISSING from run ({len(missing)}):")
    for bp, bt, bn in missing:
        print(f"  baseline p{bp+1}: t={bt:.1f}s {bn}")
        ocr = get_ocr(bn, baseline_dirs, args.ocr_lang)
        print("    OCR Preview:")
        for line in ocr.splitlines()[:5]:
            print(f"      {line}")
        if len(ocr.splitlines()) > 5:
            print("      ...")

    print(f"\nEXTRA in run ({len(extra)}):")
    for vp, vt, vn in extra:
        print(f"  run p{vp+1}: t={vt:.1f}s {vn}")
        ocr = get_ocr(vn, [run_path], args.ocr_lang)
        print("    OCR Preview:")
        for line in ocr.splitlines()[:5]:
            print(f"      {line}")
        if len(ocr.splitlines()) > 5:
            print("      ...")

if __name__ == '__main__':
    main()
