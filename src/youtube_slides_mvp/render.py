from __future__ import annotations

import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def _timestamp_url(url: str, sec: float) -> str:
    base = url.split("&t=")[0]
    return f"{base}&t={int(sec)}s"


def render_pdf_a(selected_frames: list[Path], out_pdf: Path) -> None:
    """Render selected frames to PDF one page at a time (no bulk RAM load)."""
    if not selected_frames:
        raise ValueError("no selected frames for pdf")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for frame_path in selected_frames:
        with Image.open(frame_path) as img:
            w, h = img.size
        page = doc.new_page(width=w, height=h)
        page.insert_image(fitz.Rect(0, 0, w, h), filename=str(frame_path))
    doc.save(str(out_pdf))
    doc.close()


def _build_index_pages(
    items: list[dict[str, int | float | str]],
    width: int = 1240,
    height: int = 1754,
    items_per_page: int = 40,
) -> list[Image.Image]:
    """Build one index image per page (no [:40] cap)."""
    total_pages = max(1, (len(items) + items_per_page - 1) // items_per_page)
    pages = []
    for pg in range(total_pages):
        batch = items[pg * items_per_page : (pg + 1) * items_per_page]
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        y = 60
        title = "Slide Index" if total_pages == 1 else f"Slide Index ({pg + 1}/{total_pages})"
        draw.text((60, y), title, fill=(0, 0, 0))
        y += 50
        for i, item in enumerate(batch, start=pg * items_per_page + 1):
            line = f"{i:02d}. page={item['page']} ts={item['timestamp_sec']}s {item['frame_name']}"
            draw.text((60, y), line, fill=(0, 0, 0))
            y += 34
        pages.append(img)
    return pages


def render_pdf_b_with_index(
    selected_frames: list[Path],
    index_rows: list[dict[str, int | float | str]],
    source_url: str,
    out_pdf: Path,
) -> None:
    temp_pdf = out_pdf.with_suffix(".tmp.pdf")
    render_pdf_a(selected_frames, temp_pdf)

    items_per_page = 40
    index_images = _build_index_pages(index_rows, items_per_page=items_per_page)
    index_img_paths = [out_pdf.with_name(f"{out_pdf.stem}.index{i}.jpg") for i in range(len(index_images))]
    for img, path in zip(index_images, index_img_paths):
        img.save(path, format="JPEG", quality=95)

    doc = fitz.open(str(temp_pdf))
    idx_doc = fitz.open()
    for pg_num, index_img_path in enumerate(index_img_paths):
        idx_page = idx_doc.new_page(width=595, height=842)
        idx_page.insert_image(fitz.Rect(0, 0, 595, 842), filename=str(index_img_path))

        batch_start = pg_num * items_per_page
        batch = index_rows[batch_start : batch_start + items_per_page]
        y = 95
        for i, row in enumerate(batch, start=batch_start + 1):
            target_url = _timestamp_url(source_url, float(row["timestamp_sec"]))
            rect = fitz.Rect(50, y, 550, y + 24)
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
    for p in index_img_paths:
        p.unlink(missing_ok=True)


def write_slides_json(path: Path, rows: list[dict[str, int | float | str]]) -> None:
    payload = {"slides": rows, "count": len(rows)}
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def render_pdf_raw(frame_paths: list[Path], out_pdf: Path) -> None:
    """Output all extracted frames as a single PDF, one page at a time (no bulk RAM load)."""
    if not frame_paths:
        raise ValueError("no frames for raw pdf")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for frame_path in frame_paths:
        with Image.open(frame_path) as img:
            w, h = img.size
        page = doc.new_page(width=w, height=h)
        page.insert_image(fitz.Rect(0, 0, w, h), filename=str(frame_path))
    doc.save(str(out_pdf))
    doc.close()
