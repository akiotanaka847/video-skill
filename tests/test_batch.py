"""Playlist / URL-list expansion."""
from __future__ import annotations

import json

import batch
import pytest


def _fake_yt_dlp(monkeypatch, payload, returncode=0, stderr=""):
    class _Result:
        pass
    r = _Result()
    r.returncode = returncode
    r.stdout = json.dumps(payload) if payload is not None else ""
    r.stderr = stderr
    monkeypatch.setattr(batch.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(batch.subprocess, "run", lambda *a, **k: r)


def test_expands_url_list_file(tmp_path):
    listing = tmp_path / "urls.txt"
    listing.write_text(
        "# comentario\nhttps://youtu.be/a\n\n  https://youtu.be/b  \n", encoding="utf-8"
    )
    result = batch.expand(str(listing))
    assert result["kind"] == "file"
    assert [e["url"] for e in result["entries"]] == ["https://youtu.be/a", "https://youtu.be/b"]


def test_limit_reports_skipped(tmp_path):
    listing = tmp_path / "urls.txt"
    listing.write_text("https://youtu.be/a\nhttps://youtu.be/b\nhttps://youtu.be/c\n")
    result = batch.expand(str(listing), limit=2)
    assert result["count"] == 2 and result["skipped"] == 1


def test_expands_playlist(monkeypatch):
    _fake_yt_dlp(monkeypatch, {"entries": [
        {"url": "abc123", "title": "Uno", "duration": 65},
        {"url": "https://youtu.be/def", "title": "Dos", "duration": 30},
    ]})
    result = batch.expand("https://youtube.com/playlist?list=X")
    assert result["kind"] == "playlist"
    # A bare video id from --flat-playlist is expanded to a full URL.
    assert result["entries"][0]["url"] == "https://www.youtube.com/watch?v=abc123"
    assert result["entries"][1]["url"] == "https://youtu.be/def"


def test_playlist_skips_deleted_entries(monkeypatch):
    """yt-dlp yields None for private/deleted items."""
    _fake_yt_dlp(monkeypatch, {"entries": [None, {"url": "abc", "title": "Uno"}, {}]})
    assert batch.expand("https://youtube.com/playlist?list=X")["count"] == 1


def test_single_video_dumps_without_entries(monkeypatch):
    _fake_yt_dlp(monkeypatch, {"webpage_url": "https://youtu.be/solo", "title": "Solo",
                               "duration": 10})
    result = batch.expand("https://youtu.be/solo")
    assert result["count"] == 1 and result["entries"][0]["title"] == "Solo"


def test_hard_failure_raises(monkeypatch):
    _fake_yt_dlp(monkeypatch, None, returncode=1, stderr="boom")
    with pytest.raises(SystemExit):
        batch.expand("https://youtube.com/playlist?list=X")


def test_non_url_non_file_rejected():
    with pytest.raises(SystemExit):
        batch.expand("no soy ni url ni fichero")


def test_report_is_a_markdown_table(tmp_path):
    listing = tmp_path / "urls.txt"
    listing.write_text("https://youtu.be/a\n")
    report = batch.format_report(batch.expand(str(listing)))
    assert "| # | Title | Duration | URL |" in report
    assert "https://youtu.be/a" in report
    # The report must warn against watching everything in one turn.
    assert "One video, one answer" in report
