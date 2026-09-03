#!/usr/bin/env python3
"""Persist a watched video as a markdown note in a knowledge repo.

Upstream /watch writes everything to a temp dir and tells the agent to `rm -rf`
it, so nothing survives the session. This module is the other half: it lands a
structured note in `reports/` and keeps the README index table in sync, using
the repo conventions in ~/.claude/rules/markdown-docs.md (back-navigation link
at the top, relative links between docs, tables for structured comparisons).
"""
from __future__ import annotations

import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

README_TABLE_MARKER = "<!-- reports:start -->"
README_TABLE_END = "<!-- reports:end -->"


def slugify(text: str, max_len: int = 60) -> str:
    """'¿Qué hay de nuevo en Workfront?' -> 'que-hay-de-nuevo-en-workfront'.

    NFKD + ASCII fold keeps accented Spanish titles from producing filenames
    that differ only by invisible combining marks.
    """
    if not text:
        return "video"
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = slug[:max_len].rstrip("-")
    return slug or "video"


def format_duration(seconds: float | int | None) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# NOTE TEMPLATE
#
# This is the one function shaped entirely by *your* documentation conventions
# rather than by how video processing works. The default below follows the
# markdown-docs rule (back-nav link, metadata table, timestamped sections) and
# is fully working — but the exact frontmatter, badges from `!/tags/`, and
# section order are your call. Edit here; nothing else depends on the layout.
# ---------------------------------------------------------------------------
def render_note(
    *,
    title: str,
    source_url: str,
    uploader: str | None,
    duration: float | int | None,
    transcript_source: str,
    language: str | None,
    detail: str,
    frame_count: int,
    summary: str,
    transcript: str,
    back_link: str = "../README.md",
) -> str:
    """Render the markdown body of a video note."""
    today = date.today().isoformat()
    lines = [
        f"[← Volver al índice]({back_link})",
        "",
        f"# {title}",
        "",
        "| Campo | Valor |",
        "|---|---|",
        f"| Fuente | {source_url} |",
        f"| Autor / canal | {uploader or '—'} |",
        f"| Duración | {format_duration(duration)} |",
        f"| Transcripción | {transcript_source} |",
        f"| Idioma | {language or 'auto'} |",
        f"| Detalle | `{detail}` |",
        f"| Frames analizados | {frame_count} |",
        f"| Visto el | {today} |",
        "",
        "## Resumen",
        "",
        summary.strip() or "_Sin resumen._",
        "",
        "## Transcripción",
        "",
    ]
    if transcript.strip():
        lines += [
            "<details>",
            "<summary>Desplegar transcripción completa</summary>",
            "",
            "```",
            transcript.strip(),
            "```",
            "",
            "</details>",
            "",
        ]
    else:
        lines += ["_No hubo transcripción disponible para este vídeo._", ""]
    return "\n".join(lines)


def write_note(
    notes_dir: Path,
    filename_stem: str,
    body: str,
    overwrite: bool = False,
) -> Path:
    """Write the note, suffixing -2, -3… rather than clobbering an existing one."""
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / f"{filename_stem}.md"
    if path.exists() and not overwrite:
        n = 2
        while (notes_dir / f"{filename_stem}-{n}.md").exists():
            n += 1
        path = notes_dir / f"{filename_stem}-{n}.md"
    path.write_text(body, encoding="utf-8")
    return path


def update_readme_index(
    readme: Path,
    note_path: Path,
    title: str,
    source_url: str,
) -> bool:
    """Insert a row into the README table between the reports markers.

    Returns False (without raising) when the README or its markers are absent —
    indexing is a convenience, so a missing marker must never fail a run that
    already produced a good note.
    """
    if not readme.exists():
        return False
    try:
        content = readme.read_text(encoding="utf-8")
    except OSError:
        return False
    if README_TABLE_MARKER not in content or README_TABLE_END not in content:
        return False

    try:
        rel = note_path.resolve().relative_to(readme.parent.resolve())
    except ValueError:
        rel = note_path
    row = f"| [{title}]({rel.as_posix()}) | {date.today().isoformat()} | {source_url} |"

    if row in content:
        return True
    head, rest = content.split(README_TABLE_MARKER, 1)
    table, tail = rest.split(README_TABLE_END, 1)
    table = table.rstrip("\n") + "\n" + row + "\n"
    readme.write_text(
        head + README_TABLE_MARKER + table + README_TABLE_END + tail, encoding="utf-8"
    )
    return True


def save_note(
    notes_dir: str | Path,
    *,
    title: str,
    source_url: str,
    uploader: str | None = None,
    duration: float | int | None = None,
    transcript_source: str = "—",
    language: str | None = None,
    detail: str = "balanced",
    frame_count: int = 0,
    summary: str = "",
    transcript: str = "",
    update_index: bool = True,
) -> dict:
    """Full save flow. Returns {note_path, indexed}."""
    notes_dir = Path(notes_dir).expanduser().resolve()
    body = render_note(
        title=title,
        source_url=source_url,
        uploader=uploader,
        duration=duration,
        transcript_source=transcript_source,
        language=language,
        detail=detail,
        frame_count=frame_count,
        summary=summary,
        transcript=transcript,
    )
    path = write_note(notes_dir, slugify(title), body)
    indexed = False
    if update_index:
        indexed = update_readme_index(notes_dir.parent / "README.md", path, title, source_url)
    return {"note_path": str(path), "indexed": indexed}
