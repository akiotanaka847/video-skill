"""Note rendering, safe file naming, and README index updating."""
from __future__ import annotations

import notes


def test_slugify_folds_spanish_accents():
    assert notes.slugify("¿Qué hay de NUEVO en Workfront?") == "que-hay-de-nuevo-en-workfront"


def test_slugify_never_returns_empty():
    assert notes.slugify("¿¡---!?") == "video"
    assert notes.slugify("") == "video"


def test_slugify_truncates_without_trailing_dash():
    slug = notes.slugify("palabra " * 40, max_len=20)
    assert len(slug) <= 20 and not slug.endswith("-")


def test_format_duration():
    assert notes.format_duration(3725) == "1:02:05"
    assert notes.format_duration(95) == "1:35"
    assert notes.format_duration(None) == "—"
    assert notes.format_duration(0) == "—"


def _render(**over):
    args = dict(
        title="Demo", source_url="https://youtu.be/x", uploader="Canal",
        duration=90, transcript_source="captions", language="es",
        detail="balanced", frame_count=12, summary="Un resumen.",
        transcript="00:00 hola",
    )
    args.update(over)
    return notes.render_note(**args)


def test_note_starts_with_back_navigation_link():
    """The markdown-docs convention: report docs open with a link back."""
    assert _render().splitlines()[0] == "[← Volver al índice](../README.md)"


def test_note_contains_metadata_and_sections():
    body = _render()
    for expected in ("# Demo", "| Idioma | es |", "| Frames analizados | 12 |",
                     "## Resumen", "Un resumen.", "## Transcripción", "00:00 hola"):
        assert expected in body


def test_note_without_transcript_omits_empty_code_block():
    body = _render(transcript="")
    assert "```" not in body
    assert "No hubo transcripción disponible" in body


def test_write_note_does_not_clobber(tmp_path):
    first = notes.write_note(tmp_path, "demo", "uno")
    second = notes.write_note(tmp_path, "demo", "dos")
    assert first != second
    assert first.read_text() == "uno" and second.read_text() == "dos"


def test_write_note_overwrites_when_asked(tmp_path):
    notes.write_note(tmp_path, "demo", "uno")
    again = notes.write_note(tmp_path, "demo", "dos", overwrite=True)
    assert again.name == "demo.md" and again.read_text() == "dos"


def _readme(tmp_path, with_markers=True):
    body = "# Índice\n\n| Nota | Fecha | Fuente |\n|---|---|---|\n"
    if with_markers:
        body += f"{notes.README_TABLE_MARKER}\n{notes.README_TABLE_END}\n"
    path = tmp_path / "README.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_index_row_inserted_between_markers(tmp_path):
    readme = _readme(tmp_path)
    note = tmp_path / "reports" / "demo.md"
    note.parent.mkdir()
    note.write_text("x")
    assert notes.update_readme_index(readme, note, "Demo", "https://youtu.be/x") is True
    content = readme.read_text()
    assert "[Demo](reports/demo.md)" in content
    assert content.index(notes.README_TABLE_MARKER) < content.index("[Demo]")
    assert content.index("[Demo]") < content.index(notes.README_TABLE_END)


def test_index_is_idempotent(tmp_path):
    readme = _readme(tmp_path)
    note = tmp_path / "reports" / "demo.md"
    note.parent.mkdir()
    note.write_text("x")
    notes.update_readme_index(readme, note, "Demo", "u")
    notes.update_readme_index(readme, note, "Demo", "u")
    assert readme.read_text().count("[Demo](reports/demo.md)") == 1


def test_missing_markers_is_reported_not_raised(tmp_path):
    """Indexing is a convenience — it must never fail a run that produced a note."""
    readme = _readme(tmp_path, with_markers=False)
    note = tmp_path / "demo.md"
    note.write_text("x")
    assert notes.update_readme_index(readme, note, "Demo", "u") is False


def test_missing_readme_is_reported_not_raised(tmp_path):
    note = tmp_path / "demo.md"
    note.write_text("x")
    assert notes.update_readme_index(tmp_path / "nope.md", note, "Demo", "u") is False


def test_save_note_end_to_end(tmp_path):
    readme = _readme(tmp_path)
    result = notes.save_note(
        tmp_path / "reports",
        title="Qué hay de nuevo",
        source_url="https://youtu.be/x",
        uploader="Canal",
        duration=120,
        transcript_source="captions",
        language="es",
        detail="balanced",
        frame_count=8,
        summary="Resumen.",
        transcript="00:00 hola",
    )
    assert result["indexed"] is True
    body = (tmp_path / "reports" / "que-hay-de-nuevo.md").read_text()
    assert "Resumen." in body
    assert "[Qué hay de nuevo](reports/que-hay-de-nuevo.md)" in readme.read_text()
