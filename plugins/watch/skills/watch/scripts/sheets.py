#!/usr/bin/env python3
"""Tile extracted frames into timestamped contact sheets.

The agent sees a frame by calling Read on its path, and every call costs
~50 output tokens (tool name, a long temp path, ids) that the model has to
*generate* before it sees anything. Generation is the slowest step in the loop,
so 60 frames meant ~3k generated tokens of pure overhead — close to a minute.
A sheet carries up to nine frames per Read.

Image tokens do not change: Claude bills an image by its pixels (~w*h/750), so
nine frames on one sheet cost what nine separate frames cost. Sheets are sized
to stay inside what Claude accepts without resampling, so what is composed here
is exactly what the model sees.

Each tile carries its timestamp, drawn with a tiny built-in bitmap font into a
raw RGB buffer. ffmpeg's drawtext needs a freetype build that Homebrew's ffmpeg
does not ship, and Pillow would be a new dependency; this needs neither.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

# Claude resamples an image whose long edge exceeds 1568 px or whose area
# exceeds ~1.19 MP (~1,600 tokens). Staying inside both avoids a hidden
# downscale that would quietly blur every tile.
SHEET_MAX_EDGE = 1568
SHEET_MAX_PIXELS = 1_190_000
# Shrink tiles by at most this much to fit a bigger grid. Past it, fewer tiles
# per sheet at full size reads better than more tiles that are hard to see.
MIN_TILE_SCALE = 0.85
# Layouts to try, grouped by tile count, most tiles first.
GRIDS = (
    (3, 3), (4, 2), (2, 4), (3, 2), (2, 3),
    (4, 1), (1, 4), (2, 2), (3, 1), (1, 3), (2, 1), (1, 2),
)
# Below this many frames a sheet saves at most one Read — not worth the step.
MIN_FRAMES = 3
GAP = 4
BACKGROUND = (24, 24, 24)
LABEL_BG = (0, 0, 0)
LABEL_FG = (255, 255, 255)

# 5x7 bitmap glyphs: only what a timestamp needs.
FONT = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ":": ("000", "010", "010", "000", "010", "010", "000"),
}


def format_label(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    if hours:
        return f"{hours}:{rem // 60:02d}:{rem % 60:02d}"
    return f"{rem // 60:02d}:{rem % 60:02d}"


def _sheet_size(cols: int, rows: int, tile_w: int, tile_h: int) -> tuple[int, int]:
    return cols * tile_w + (cols - 1) * GAP, rows * tile_h + (rows - 1) * GAP


def _fits(cols: int, rows: int, tile_w: int, tile_h: int) -> bool:
    w, h = _sheet_size(cols, rows, tile_w, tile_h)
    return max(w, h) <= SHEET_MAX_EDGE and w * h <= SHEET_MAX_PIXELS


def _fit_tile(cols: int, rows: int, width: int, height: int) -> tuple[int, int]:
    """Largest even tile size, same aspect ratio, that keeps the sheet in bounds."""
    tile_w = width - (width % 2)
    while tile_w > 2:
        tile_h = max(2, int(round(tile_w * height / width / 2)) * 2)
        if tile_h <= height and _fits(cols, rows, tile_w, tile_h):
            return tile_w, tile_h
        tile_w -= 2
    return 0, 0


def plan_grid(width: int, height: int) -> tuple[int, int, int, int]:
    """Choose (cols, rows, tile_w, tile_h) for frames of ``width`` x ``height``.

    Takes the largest tile count whose best layout keeps tiles at no less than
    MIN_TILE_SCALE of their size. (1, 1, ...) means sheets would not help.
    """
    by_count: dict[int, list[tuple[int, int]]] = {}
    for cols, rows in GRIDS:
        by_count.setdefault(cols * rows, []).append((cols, rows))
    for count in sorted(by_count, reverse=True):
        best = max(
            (( *_fit_tile(c, r, width, height), c, r) for c, r in by_count[count]),
            key=lambda option: option[0],
        )
        tile_w, tile_h, cols, rows = best
        if tile_w and tile_w >= width * MIN_TILE_SCALE:
            return cols, rows, tile_w, tile_h
    return 1, 1, width, height


def _render_label(text: str, scale: int) -> tuple[int, int, bytes]:
    """Rasterize ``text`` as white-on-black RGB. Returns (width, height, pixels)."""
    pad = scale * 2
    glyphs = [FONT[ch] for ch in text if ch in FONT]
    spacing = scale
    text_w = sum(len(g[0]) * scale for g in glyphs) + spacing * max(0, len(glyphs) - 1)
    width, height = text_w + 2 * pad, 7 * scale + 2 * pad
    pixels = bytearray(bytes(LABEL_BG) * (width * height))
    fg = bytes(LABEL_FG)
    x = pad
    for glyph in glyphs:
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    y = pad + gy * scale + dy
                    start = (y * width + x + gx * scale) * 3
                    pixels[start:start + 3 * scale] = fg * scale
        x += len(glyph[0]) * scale + spacing
    return width, height, bytes(pixels)


def _blit(canvas: bytearray, canvas_w: int, x0: int, y0: int, w: int, h: int, pixels: bytes) -> None:
    row = w * 3
    for y in range(h):
        dst = ((y0 + y) * canvas_w + x0) * 3
        canvas[dst:dst + row] = pixels[y * row:(y + 1) * row]


def _probe_size(path: str) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        width, height = (int(v) for v in result.stdout.strip().split(",")[:2])
    except ValueError:
        raise SystemExit(f"could not read frame size of {path}") from None
    return width, height


def _decode_tiles(paths: list[str], tile_w: int, tile_h: int, list_file: Path) -> list[bytes]:
    """Decode every frame to raw RGB at tile size in a single ffmpeg call."""
    list_file.write_text(
        "".join("file '" + p.replace("'", "'\\''") + "'\n" for p in paths),
        encoding="utf-8",
    )
    vf = (
        f"scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease,"
        f"pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2,format=rgb24"
    )
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-vf", vf, "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True,
    )
    size = tile_w * tile_h * 3
    if result.returncode != 0 or len(result.stdout) < size * len(paths):
        raise SystemExit(f"ffmpeg tile decode failed: {result.stderr.decode(errors='ignore').strip()}")
    return [result.stdout[i * size:(i + 1) * size] for i in range(len(paths))]


def _encode(sheets: list[bytes], width: int, height: int, out_dir: Path, first_number: int) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", "1",
         "-i", "pipe:0", "-q:v", "2", "-start_number", str(first_number),
         str(out_dir / "sheet_%02d.jpg")],
        input=b"".join(sheets), capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg sheet encode failed: {result.stderr.decode(errors='ignore').strip()}")


def build_sheets(frames: list[dict], out_dir: Path) -> list[dict]:
    """Compose ``frames`` (chronological) into sheets. Returns [] when not worth it.

    Each entry: {"path", "grid", "frames"} where "frames" are the source frame
    dicts in reading order (left to right, top to bottom).
    """
    if len(frames) < MIN_FRAMES or shutil.which("ffmpeg") is None:
        return []
    width, height = _probe_size(frames[0]["path"])
    cols, rows, tile_w, tile_h = plan_grid(width, height)
    per_sheet = cols * rows
    if per_sheet == 1:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("sheet_*.jpg"):
        stale.unlink()
    tiles = _decode_tiles([f["path"] for f in frames], tile_w, tile_h, out_dir / "tiles.txt")
    label_scale = 2 if tile_w < 600 else 3
    background = bytes(BACKGROUND)

    # Full sheets share one size; the last sheet drops its empty rows, so it is
    # encoded on its own. Two ffmpeg calls at most.
    groups: list[tuple[int, int, int, list[bytes]]] = []
    entries: list[dict] = []
    for number, first in enumerate(range(0, len(frames), per_sheet), start=1):
        batch = list(range(first, min(first + per_sheet, len(frames))))
        sheet_rows = math.ceil(len(batch) / cols)
        sheet_w, sheet_h = _sheet_size(cols, sheet_rows, tile_w, tile_h)
        canvas = bytearray(background * (sheet_w * sheet_h))
        for slot, index in enumerate(batch):
            x0 = (slot % cols) * (tile_w + GAP)
            y0 = (slot // cols) * (tile_h + GAP)
            _blit(canvas, sheet_w, x0, y0, tile_w, tile_h, tiles[index])
            label_w, label_h, label = _render_label(
                format_label(frames[index]["timestamp_seconds"]), label_scale
            )
            _blit(canvas, sheet_w, x0 + GAP, y0 + GAP, label_w, label_h, label)
        if groups and groups[-1][0] == sheet_w and groups[-1][1] == sheet_h:
            groups[-1][3].append(bytes(canvas))
        else:
            groups.append((sheet_w, sheet_h, number, [bytes(canvas)]))
        entries.append({
            "path": str(out_dir / f"sheet_{number:02d}.jpg"),
            "grid": f"{cols}x{sheet_rows}",
            "frames": [frames[i] for i in batch],
        })

    for sheet_w, sheet_h, first_number, sheets in groups:
        _encode(sheets, sheet_w, sheet_h, out_dir, first_number)
    return entries


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: sheets.py <out-dir> <frame.jpg> [frame.jpg ...]", file=sys.stderr)
        raise SystemExit(2)
    demo = [{"path": p, "timestamp_seconds": float(i * 10)} for i, p in enumerate(sys.argv[2:])]
    for entry in build_sheets(demo, Path(sys.argv[1])):
        print(entry["path"], entry["grid"])
