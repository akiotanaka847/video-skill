"""yt-dlp argv construction and caption-track choice for download.py.

Regression guard: ``--sub-langs all`` makes yt-dlp fetch YouTube's hundreds of
auto-translated caption tracks, which can take minutes and stalls before the
video download even starts. A caption fetch must name exactly one track.
"""
from __future__ import annotations

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


def _arg(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


# --- caption track choice: the original beats a translation --------------------

YT_ENGLISH_WEBINAR = {
    # Real shape of a YouTube info.json: no manual subs (live_chat is the chat
    # replay, not captions), 150+ machine-translated auto tracks, one '-orig'.
    "language": "en",
    "subtitles": {"live_chat": [{}]},
    "automatic_captions": {"en-orig": [{}], "en": [{}], "es": [{}], "fr": [{}]},
}


def test_english_video_uses_original_asr_not_spanish_translation():
    """The bug this guards: 'es,en' used to pick YouTube's Spanish MT."""
    track = download.choose_caption_track(YT_ENGLISH_WEBINAR, ["es", "en"])
    assert track == {"lang": "en-orig", "auto": True, "kind": "auto, original language"}


def test_manual_track_in_preferred_language_wins():
    raw = dict(YT_ENGLISH_WEBINAR, subtitles={"es": [{}], "en": [{}]})
    assert download.choose_caption_track(raw, ["es", "en"])["lang"] == "es"


def test_manual_regional_variant_matches_base_code():
    raw = dict(YT_ENGLISH_WEBINAR, subtitles={"es-419": [{}]})
    track = download.choose_caption_track(raw, ["es"])
    assert track["lang"] == "es-419" and track["auto"] is False


def test_manual_in_original_language_beats_original_asr():
    raw = dict(YT_ENGLISH_WEBINAR, subtitles={"en": [{}]})
    assert download.choose_caption_track(raw, ["es"]) == {"lang": "en", "auto": False, "kind": "manual"}


def test_spanish_video_uses_spanish_original():
    raw = {"language": "es", "subtitles": {}, "automatic_captions": {"es-orig": [{}], "en": [{}]}}
    assert download.choose_caption_track(raw, ["en"])["lang"] == "es-orig"


def test_declared_language_used_when_orig_is_not_marked():
    raw = {"language": "de", "subtitles": {}, "automatic_captions": {"de": [{}], "es": [{}]}}
    assert download.choose_caption_track(raw, ["es"])["lang"] == "de"


def test_translation_only_as_last_resort():
    raw = {"subtitles": {}, "automatic_captions": {"es": [{}]}}
    assert download.choose_caption_track(raw, ["es"])["kind"] == "auto-translated"


def test_no_captions_at_all():
    assert download.choose_caption_track({"subtitles": {"live_chat": [{}]}}, ["es"]) is None
    assert download.choose_caption_track({}, ["es"]) is None


# --- one extraction, replayed ------------------------------------------------------

def test_probe_downloads_nothing_and_writes_info(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    download.probe(URL, tmp_path)
    argv = calls[0]
    assert "--skip-download" in argv and "--write-info-json" in argv
    assert "--write-subs" not in argv and "--write-auto-subs" not in argv


def test_fetch_subtitle_requests_exactly_one_track(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    info = tmp_path / "video.info.json"
    info.write_text("{}")
    download.fetch_subtitle(URL, tmp_path, {"lang": "es-419", "auto": True, "kind": "x"}, str(info))
    argv = calls[0]
    langs = _arg(argv, "--sub-langs")
    assert "all" not in langs.split(",") and "," not in langs
    assert langs == "es\\-419"  # escaped: yt-dlp treats entries as regexes
    assert "--write-auto-subs" in argv and "--write-subs" not in argv
    assert _arg(argv, "--load-info-json") == str(info)
    assert URL not in argv  # replayed, not re-extracted


def test_manual_track_uses_write_subs(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    download.fetch_subtitle(URL, tmp_path, {"lang": "es", "auto": False, "kind": "manual"})
    assert "--write-subs" in calls[0] and "--write-auto-subs" not in calls[0]


def test_missing_info_json_falls_back_to_url(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    download.fetch_subtitle(URL, tmp_path, {"lang": "es", "auto": False, "kind": "manual"},
                            str(tmp_path / "gone.json"))
    assert "--load-info-json" not in calls[0] and calls[0][-1] == URL


# --- media sized for the job -------------------------------------------------------

def test_download_res_tracks_frame_width():
    assert download.download_res(512) == 480
    assert download.download_res(640) == 480
    assert download.download_res(1024) == 720
    assert download.download_res(1920) == 1080


def test_video_download_is_video_only_small_and_h264(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    (tmp_path / "video.mp4").write_bytes(b"x")
    download.download_video(URL, tmp_path, resolution=512)
    argv = calls[0]
    assert _arg(argv, "-f") == "bv/b"
    # res = smallest side, so vertical video is sized by its width.
    assert _arg(argv, "-S") == "res:480,vcodec:h264"
    assert "--write-subs" not in argv and "--merge-output-format" not in argv
    assert _arg(argv, "--http-chunk-size") == download.HTTP_CHUNK


def test_video_download_resolution_follows_frames(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    (tmp_path / "video.mp4").write_bytes(b"x")
    download.download_video(URL, tmp_path, resolution=1024)
    assert _arg(calls[0], "-S") == "res:720,vcodec:h264"


def test_video_download_without_file_fails_loudly(monkeypatch, tmp_path):
    _capture_argv(monkeypatch)
    with pytest.raises(SystemExit):
        download.download_video(URL, tmp_path)


def test_audio_download_picks_small_stream(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    (tmp_path / "audio.m4a").write_bytes(b"x")
    got = download.download_audio(URL, tmp_path)
    assert _arg(calls[0], "-f") == "wa[abr>=40]/ba"
    assert got is not None and got.name == "audio.m4a"


def test_audio_download_reports_none_when_nothing_arrives(monkeypatch, tmp_path):
    _capture_argv(monkeypatch)
    assert download.download_audio(URL, tmp_path) is None


def test_pick_video_ignores_audio_files(tmp_path):
    (tmp_path / "video.m4a").write_bytes(b"x")  # an audio-only file named video.*
    assert download._pick_video(tmp_path) is None


def test_pick_subtitle_prefers_first_configured_language(tmp_path):
    for name in ("video.en.vtt", "video.es.vtt"):
        (tmp_path / name).write_text("WEBVTT")
    _, markers = config.sub_lang_patterns(["es", "en"])
    picked = download._pick_subtitle(tmp_path, markers)
    assert picked is not None and ".es." in picked.name


def test_subtitle_lang_extracts_tag():
    assert download.subtitle_lang("/tmp/video.es-419.vtt") == "es-419"
    assert download.subtitle_lang(None) is None


def test_failed_replay_retries_with_fresh_extraction(monkeypatch, tmp_path):
    """A replayed format URL can 403; the retry must re-extract from the URL."""
    calls = _capture_argv(monkeypatch)
    info = tmp_path / "video.info.json"
    info.write_text("{}")
    real_run = download.subprocess.run

    def run_then_succeed(cmd, *a, **k):
        result = real_run(cmd, *a, **k)
        if "--load-info-json" not in cmd:  # the fresh attempt produces the file
            (tmp_path / "video.mp4").write_bytes(b"x")
        return result

    monkeypatch.setattr(download.subprocess, "run", run_then_succeed)
    (tmp_path / "video.mp4.part").write_bytes(b"stale")
    got = download.download_video(URL, tmp_path, info_json=str(info))
    assert got.name == "video.mp4"
    assert len(calls) == 2
    assert "--load-info-json" in calls[0] and calls[1][-1] == URL
    assert not (tmp_path / "video.mp4.part").exists()  # no resuming a dead URL


def test_no_retry_without_replay(monkeypatch, tmp_path):
    calls = _capture_argv(monkeypatch)
    with pytest.raises(SystemExit):
        download.download_video(URL, tmp_path)
    assert len(calls) == 1
