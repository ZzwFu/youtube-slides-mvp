from pathlib import Path

from youtube_slides_mvp.manifest import build_task_paths, ensure_task_dirs


def test_task_paths_bootstrap(tmp_path: Path) -> None:
    paths = build_task_paths(tmp_path, "slide-test")
    ensure_task_dirs(paths)
    assert paths.task_dir.exists()
    assert paths.video_dir.exists()
    assert paths.frames_raw_dir.exists()
    assert paths.frames_norm_dir.exists()
    assert paths.artifacts_dir.exists()
    assert paths.pdf_dir.exists()
