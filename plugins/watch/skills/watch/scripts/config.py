#!/usr/bin/env python3
"""Shared /watch configuration helpers.

Reads ~/.config/video-skill/.env, falling back to a legacy ~/.config/watch/.env
so API keys already stored there carry over unchanged. Environment variables
always win over both files.
"""
from __future__ import annotations

import os
from pathlib import Path


CONFIG_DIR = Path.home() / ".config" / "video-skill"
CONFIG_FILE = CONFIG_DIR / ".env"

# Legacy location. Read-only fallback: we never write here, so anything already
# configured there keeps working and its keys are inherited.
LEGACY_CONFIG_FILE = Path.home() / ".config" / "watch" / ".env"

CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
) / "video-skill"

DEFAULT_DETAIL = "balanced"
DETAILS = {"transcript", "efficient", "balanced", "token-burner"}

# Caption languages to request, in preference order. Hardcoding English here
# would mean a Spanish video with perfect Spanish subtitles returns zero
# captions and falls through to paid Whisper.
DEFAULT_SUB_LANGS = "es,en"


def read_env_file(path: Path | None = None) -> dict[str, str]:
    if path is None:
        path = CONFIG_FILE
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        else:
            # Strip an inline comment (a '#' preceded by whitespace) from an
            # unquoted value. Without this, `WATCH_DETAIL=balanced  # note`
            # parses as "balanced  # note", fails validation, and silently
            # falls back to the default. Keeps '#' inside quotes / API keys.
            for i, ch in enumerate(value):
                if ch == "#" and i > 0 and value[i - 1] in " \t":
                    value = value[:i].rstrip()
                    break
        values[key.strip()] = value
    return values


def read_all_env() -> dict[str, str]:
    """Merge the legacy config under the current one (current wins)."""
    merged = read_env_file(LEGACY_CONFIG_FILE)
    merged.update(read_env_file(CONFIG_FILE))
    return merged


def _setting(file_values: dict[str, str], key: str, default: str = "") -> str:
    return (os.environ.get(key) or file_values.get(key) or default).strip()


def _as_bool(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def normalize_langs(raw: str) -> list[str]:
    """'es, en-US , ' -> ['es', 'en-US']. Order is preference order."""
    seen: list[str] = []
    for part in raw.replace(";", ",").split(","):
        code = part.strip()
        if code and code not in seen:
            seen.append(code)
    return seen


def sub_lang_patterns(langs: list[str]) -> tuple[str, list[str]]:
    """Return (yt-dlp --sub-langs value, ordered filename markers).

    yt-dlp wants glob-ish patterns ('es.*' also matches 'es-419'); the marker
    list is what _pick_subtitle uses to choose between several downloaded VTTs.
    """
    if not langs:
        langs = normalize_langs(DEFAULT_SUB_LANGS)
    patterns = ",".join(f"{code}.*" for code in langs)
    markers = [f".{code}." for code in langs]
    # yt-dlp names YouTube's original-language auto track '<lang>-orig'.
    markers += [f".{code}-orig." for code in langs]
    return patterns, markers


def get_config() -> dict[str, object]:
    file_values = read_all_env()

    detail = _setting(file_values, "WATCH_DETAIL") or DEFAULT_DETAIL
    if detail not in DETAILS:
        detail = DEFAULT_DETAIL

    langs = normalize_langs(
        _setting(file_values, "WATCH_SUB_LANGS", DEFAULT_SUB_LANGS)
    )

    return {
        "detail": detail,
        "sub_langs": langs,
        # Forced Whisper language (ISO-639-1, e.g. 'es'). Empty = auto-detect.
        "whisper_lang": _setting(file_values, "WATCH_WHISPER_LANG"),
        # Domain vocabulary passed to Whisper as a decoding prompt. Whisper
        # biases toward terms it has seen in the prompt, which is how you stop
        # it writing "Work front" or "Kayo" for Workfront / Qaio.
        "glossary": _setting(file_values, "WATCH_GLOSSARY"),
        "cache_enabled": _as_bool(_setting(file_values, "WATCH_CACHE"), True),
        "notes_dir": _setting(file_values, "WATCH_NOTES_DIR"),
        "config_file": str(CONFIG_FILE),
        "cache_dir": str(CACHE_DIR),
    }


def frame_cap(detail: str) -> int | None:
    if detail == "efficient":
        return 50
    if detail == "balanced":
        return 100
    if detail == "token-burner":
        return None
    if detail == "transcript":
        return None
    return 100
