#!/usr/bin/env python3
"""Expand a playlist / channel / URL list into individual video entries.

This is deliberately only a *resolver*. It does not watch anything: seeing a
video means loading frames into the model's context via Read, which cannot be
delegated to a subprocess. So this prints the work list as JSON and the agent
drives the per-video loop itself.

    python3 batch.py <playlist-url|urls.txt> [--limit N] [--json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from download import is_url  # noqa: E402


def _from_file(path: Path) -> list[dict]:
    """Read a newline-delimited URL list. '#' starts a comment."""
    entries: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append({"url": line, "title": None, "duration": None})
    return entries


def _from_playlist(url: str) -> list[dict]:
    """Expand a playlist/channel with --flat-playlist.

    Flat mode reads the playlist index only — one request instead of one per
    video, which is the difference between seconds and minutes on a long channel.
    """
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--ignore-errors",
        "--",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and not result.stdout.strip():
        raise SystemExit(f"yt-dlp could not expand {url}: {result.stderr.strip()[:400]}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"yt-dlp returned non-JSON for {url}: {exc}")

    # A single video URL dumps as one object with no 'entries'.
    raw_entries = data.get("entries")
    if raw_entries is None:
        return [{
            "url": data.get("webpage_url") or url,
            "title": data.get("title"),
            "duration": data.get("duration"),
        }]

    entries: list[dict] = []
    for item in raw_entries:
        if not item:  # yt-dlp yields None for deleted/private items
            continue
        entry_url = item.get("url") or item.get("webpage_url")
        if not entry_url:
            continue
        if not is_url(entry_url):  # flat mode can emit a bare video id
            entry_url = f"https://www.youtube.com/watch?v={entry_url}"
        entries.append({
            "url": entry_url,
            "title": item.get("title"),
            "duration": item.get("duration"),
        })
    return entries


def expand(source: str, limit: int | None = None) -> dict:
    path = Path(source).expanduser()
    if path.exists() and path.is_file() and path.suffix.lower() in (".txt", ".list", ".md"):
        entries = _from_file(path)
        kind = "file"
        title = path.name
    elif is_url(source):
        entries = _from_playlist(source)
        kind = "playlist"
        title = source
    else:
        raise SystemExit(f"Not a URL or a readable .txt list: {source}")

    skipped = 0
    if limit is not None and limit > 0 and len(entries) > limit:
        skipped = len(entries) - limit
        entries = entries[:limit]

    return {
        "source": source,
        "kind": kind,
        "title": title,
        "count": len(entries),
        "skipped": skipped,
        "entries": entries,
    }


def format_report(result: dict) -> str:
    lines = [
        f"# Batch: {result['title']}",
        "",
        f"{result['count']} video(s) to watch"
        + (f" ({result['skipped']} skipped by --limit)" if result["skipped"] else ""),
        "",
        "| # | Title | Duration | URL |",
        "|---|---|---|---|",
    ]
    for i, e in enumerate(result["entries"], 1):
        dur = e.get("duration")
        dur_s = f"{int(dur) // 60}:{int(dur) % 60:02d}" if dur else "—"
        lines.append(f"| {i} | {e.get('title') or '—'} | {dur_s} | {e['url']} |")
    lines += [
        "",
        "Watch each entry in order, saving a note per video. Do not run them all "
        "in one turn — frames from several videos at once will blow the context "
        "budget. One video, one answer, one note, then the next.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(prog="batch", description=__doc__)
    ap.add_argument("source", help="Playlist/channel URL, or a .txt file of URLs")
    ap.add_argument("--limit", type=int, default=None, help="Cap the number of entries")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a report")
    args = ap.parse_args()

    result = expand(args.source, args.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
