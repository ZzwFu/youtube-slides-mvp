from __future__ import annotations

import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def _timestamp_url(url: str, sec: float) -> str:
    base = url.split("&t=")[0]
    return f"{base}&t={int(sec)}s"


def render_pdf_a(selected_frames: list[Path], out_pdf: Path) -> None:
    if not selected_frames:
        raise ValueError("no selected frames for pdf")
    images = [Image.open(p).convert("RGB") for p in selected_frames]
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out_pdf, format="PDF", save_all=True, append_images=images[1:])


def _build_index_page(items: list[dict[str, int | float | str]], width: int = 1240, height: int = 1754) -> Image.Image:
    page = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    y = 60
    draw.text((60, y), "Slide Index", fill=(0, 0, 0))
    y += 50

    for i, item in enumerate(items[:40], start=1):
        line = f"{i:02d}. page={item['page']} ts={item['timestamp_sec']}s {item['frame_name']}"
        draw.text((60, y), line, fill=(0, 0, 0))
        y += 34
        if y > height - 60:
            break
    return page


def render_pdf_b_with_index(
    selected_frames: list[Path],
    index_rows: list[dict[str, int | float | str]],
    source_url: str,
    out_pdf: Path,
) -> None:
    temp_pdf = out_pdf.with_suffix(".tmp.pdf")
    render_pdf_a(selected_frames, temp_pdf)

    index_img = _build_index_page(index_rows)
    index_img_path = out_pdf.with_suffix(".index.jpg")
    index_img.save(index_img_path, format="JPEG", quality=95)

    doc = fitz.open(str(temp_pdf))
    idx_doc = fitz.open()
    idx_page = idx_doc.new_page(width=595, height=842)
    idx_page.insert_image(fitz.Rect(0, 0, 595, 842), filename=str(index_img_path))

    y = 95
    for i, row in enumerate(index_rows[:24], start=1):
        target_page = int(row["page"])
        target_url = _timestamp_url(source_url, float(row["timestamp_sec"]))
        rect = fitz.Rect(50, y, 550, y + 24)
        idx_page.insert_text((54, y + 16), f"{i:02d}. t={int(float(row['timestamp_sec']))}s -> page {target_page}", fontsize=10)
        idx_page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": target_url})
        y += 28

    out = fitz.open()
    out.insert_pdf(idx_doc)
    out.insert_pdf(doc)
    out.save(str(out_pdf))

    idx_doc.close()
    doc.close()
    out.close()
    temp_pdf.unlink(missing_ok=True)
    index_img_path.unlink(missing_ok=True)


def write_slides_json(path: Path, rows: list[dict[str, int | float | str]]) -> None:
    payload = {"slides": rows, "count": len(rows)}
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def render_pdf_raw(frame_paths: list[Path], out_pdf: Path) -> None:
    """Output all extracted frames (no deduplication) as a single PDF for reference."""
    if not frame_paths:
        raise ValueError("no frames for raw pdf")
    images = [Image.open(p).convert("RGB") for p in frame_paths]
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out_pdf, format="PDF", save_all=True, append_images=images[1:])
