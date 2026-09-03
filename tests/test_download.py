"""yt-dlp argv construction for download.py.

Regression guard: ``--sub-langs all`` makes yt-dlp fetch YouTube's hundreds of
auto-translated caption tracks, which can take minutes and stalls before the
video download even starts. We only support English, so the request must stay
bounded to the English-only pattern.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "plugins" / "watch" / "skills" / "watch" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import config
import download  # noqa: E402

URL = "https://www.youtube.com/watch?v=rlOpbu3Enkw"


def _capture_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Stub subprocess.run inside download.py and record every argv."""
    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return _Result()

    monkeypatch.setattr(download.subprocess, "run", fake_run)
    # These tests assert how the yt-dlp argv is built, not whether yt-dlp is
    # installed. Without this the suite only passes on a machine that happens
    # to have the binary, which makes it useless in CI.
    monkeypatch.setattr(download.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    return calls


def _sub_langs(argv: list[str]) -> str:
    idx = argv.index("--sub-langs")
    return argv[idx + 1]


def _assert_not_all_languages(langs: str) -> None:
    """Requesting every language would download dozens of subtitle files."""
    assert "all" not in langs.split(","), f"sub-langs must stay explicit, got {langs!r}"


def test_fetch_captions_defaults_to_spanish_first(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    download.fetch_captions(URL, tmp_path / "download")
    langs = _sub_langs(calls[0])
    _assert_not_all_languages(langs)
    assert langs == "es.*,en.*", f"default should be Spanish-first, got {langs!r}"


def test_fetch_captions_honours_explicit_langs(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    download.fetch_captions(URL, tmp_path / "download", sub_langs=["fr", "de"])
    assert _sub_langs(calls[0]) == "fr.*,de.*"


def test_download_url_requests_configured_langs(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    # _pick_video returns None with no real file, which raises SystemExit after
    # the yt-dlp argv is already built — that's all we need to inspect.
    with pytest.raises(SystemExit):
        download.download_url(URL, tmp_path / "download", sub_langs=["es"])
    assert _sub_langs(calls[0]) == "es.*"


def test_pick_subtitle_prefers_first_configured_language(tmp_path):
    for name in ("video.en.vtt", "video.es.vtt", "video.fr.vtt"):
        (tmp_path / name).write_text("WEBVTT\n", encoding="utf-8")
    _, markers = config.sub_lang_patterns(["es", "en"])
    picked = download._pick_subtitle(tmp_path, markers)
    assert picked is not None and ".es." in picked.name


def test_pick_subtitle_falls_back_to_second_language(tmp_path):
    (tmp_path / "video.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
    _, markers = config.sub_lang_patterns(["es", "en"])
    picked = download._pick_subtitle(tmp_path, markers)
    assert picked is not None and ".en." in picked.name


def test_subtitle_lang_extracts_tag():
    assert download.subtitle_lang("/tmp/video.es-419.vtt") == "es-419"
    assert download.subtitle_lang(None) is None
