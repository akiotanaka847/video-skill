#!/usr/bin/env python3
"""Transcript cache for /watch.

Only the transcript and its metadata are cached — never frames. Frames depend
on --detail/--fps/--resolution/--start/--end, so a frame cache key would be
huge and rarely hit, and re-extracting them is a local ffmpeg pass. The
transcript is the part that costs money (Whisper) and network (yt-dlp), so it
is the part worth persisting.

Layout: ~/.cache/video-skill/transcripts/<key>.json
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config import CACHE_DIR  # noqa: E402

CACHE_VERSION = 1
DEFAULT_MAX_AGE_DAYS = 30


def _source_identity(source: str) -> str:
    """A stable identity for the source.

    URLs are identified by the URL itself. Local files add mtime and size so an
    edited or re-rendered file misses the cache instead of returning a stale
    transcript for different content.
    """
    p = Path(source).expanduser()
    try:
        if p.exists() and p.is_file():
            st = p.stat()
            return f"file:{p.resolve()}:{int(st.st_mtime)}:{st.st_size}"
    except OSError:
        pass
    return f"url:{source.strip()}"


def cache_key(
    source: str,
    sub_langs: list[str] | None,
    whisper_lang: str = "",
    glossary: str = "",
) -> str:
    """Hash every input that can change the resulting transcript.

    Changing the glossary or the forced language must invalidate the entry —
    otherwise you tune your vocabulary, re-run, and silently get the old text.
    """
    parts = [
        f"v{CACHE_VERSION}",
        _source_identity(source),
        "langs=" + ",".join(sub_langs or []),
        f"wlang={whisper_lang}",
        "glossary=" + hashlib.sha256(glossary.encode("utf-8")).hexdigest()[:16],
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def _entry_path(key: str) -> Path:
    return CACHE_DIR / "transcripts" / f"{key}.json"


def load(key: str, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> dict | None:
    """Return the cached payload, or None on miss/expiry/corruption.

    Every failure mode returns None rather than raising: a broken cache must
    degrade into a normal (slower) run, never into a failed one.
    """
    path = _entry_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("cache_version") != CACHE_VERSION:
        return None
    created = payload.get("created_at", 0)
    if max_age_days > 0 and (time.time() - created) > max_age_days * 86400:
        return None
    if not payload.get("segments"):
        return None
    return payload


def save(key: str, payload: dict) -> Path | None:
    """Write an entry. Returns the path, or None if the cache is unwritable."""
    path = _entry_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = dict(payload)
        record["cache_version"] = CACHE_VERSION
        record["created_at"] = time.time()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a killed run never leaves half a file
        return path
    except OSError as exc:
        print(f"[watch] cache write skipped: {exc}", file=sys.stderr)
        return None


def purge(max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> int:
    """Delete expired entries. Returns how many were removed."""
    root = CACHE_DIR / "transcripts"
    if not root.exists():
        return 0
    removed = 0
    cutoff = time.time() - max_age_days * 86400
    for entry in root.glob("*.json"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def stats() -> dict:
    root = CACHE_DIR / "transcripts"
    files = list(root.glob("*.json")) if root.exists() else []
    return {
        "dir": str(root),
        "entries": len(files),
        "bytes": sum(f.stat().st_size for f in files if f.exists()),
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "purge":
        print(f"removed {purge()} expired entries")
    else:
        print(json.dumps(stats(), indent=2))
