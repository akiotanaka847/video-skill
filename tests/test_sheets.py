"""Contact sheets: grid planning, composition, and timestamp labels."""
from __future__ import annotations

import subprocess
from pathlib import Path

import frames
import pytest
import sheets


def _size(path: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


@pytest.mark.parametrize("width,height", [
    (512, 288), (512, 278), (512, 384), (512, 910), (1024, 576), (512, 512), (320, 240),
])
def test_every_grid_fits_claudes_no_resample_envelope(width, height):
    cols, rows, tile_w, tile_h = sheets.plan_grid(width, height)
    sheet_w, sheet_h = sheets._sheet_size(cols, rows, tile_w, tile_h)
    assert max(sheet_w, sheet_h) <= sheets.SHEET_MAX_EDGE
    assert sheet_w * sheet_h <= sheets.SHEET_MAX_PIXELS
    assert tile_w >= width * sheets.MIN_TILE_SCALE  # never shrunk past the floor


def test_widescreen_frames_get_nine_per_sheet():
    assert sheets.plan_grid(512, 288)[:2] == (3, 3)


def test_vertical_frames_sit_side_by_side():
    cols, rows, *_ = sheets.plan_grid(512, 910)
    assert (cols, rows) == (3, 1)


def test_label_format():
    assert sheets.format_label(0) == "00:00"
    assert sheets.format_label(754.9) == "12:34"
    assert sheets.format_label(3725) == "1:02:05"


def test_label_raster_has_ink():
    w, h, pixels = sheets._render_label("12:34", 2)
    assert len(pixels) == w * h * 3
    assert bytes(sheets.LABEL_FG) in pixels  # white digits drawn
    assert pixels[:3] == bytes(sheets.LABEL_BG)  # padding stays background


def test_build_sheets_from_real_frames(cut_clip: Path, tmp_path: Path):
    out, _ = frames.extract_scene_or_uniform(
        str(cut_clip), tmp_path / "f", fps=2.0, target_frames=50, max_frames=100,
    )
    built = sheets.build_sheets(out, tmp_path / "sheets")
    per = len(built[0]["frames"])
    assert len(built) == -(-len(out) // per)  # ceil
    # Every frame lands on exactly one sheet, in order.
    flat = [f for sheet in built for f in sheet["frames"]]
    assert flat == out
    for sheet in built:
        w, h = _size(sheet["path"])
        assert max(w, h) <= sheets.SHEET_MAX_EDGE and w * h <= sheets.SHEET_MAX_PIXELS


def test_last_sheet_drops_empty_rows(cut_clip: Path, tmp_path: Path):
    out, _ = frames.extract_scene_or_uniform(
        str(cut_clip), tmp_path / "f", fps=2.0, target_frames=50, max_frames=100,
    )
    four = out[:4]
    cols, rows, *_ = sheets.plan_grid(*_size(four[0]["path"]))
    built = sheets.build_sheets(four, tmp_path / "sheets")
    assert cols * rows > 4 or len(built) == 1
    last = built[-1]
    assert last["grid"] == f"{cols}x{-(-len(last['frames']) // cols)}"


def test_too_few_frames_skip_sheets(cut_clip: Path, tmp_path: Path):
    out, _ = frames.extract_scene_or_uniform(
        str(cut_clip), tmp_path / "f", fps=2.0, target_frames=50, max_frames=100,
    )
    assert sheets.build_sheets(out[:2], tmp_path / "sheets") == []
    assert sheets.build_sheets([], tmp_path / "sheets") == []
