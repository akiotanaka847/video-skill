"""End-to-end routing of --detail through watch.py on a local clip."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WATCH = Path(__file__).resolve().parent.parent / "plugins" / "watch" / "skills" / "watch" / "scripts" / "watch.py"


def _run(clip: Path, *args: str, env_extra: dict | None = None) -> str:
    env = dict(os.environ)
    env.pop("WATCH_DETAIL", None)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(WATCH), str(clip), "--no-whisper", *args],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_efficient_uses_keyframe_engine(cut_clip: Path):
    out = _run(cut_clip, "--detail", "efficient")
    assert "(keyframe" in out
    assert "**Detail:** efficient" in out


def test_balanced_uses_keyframe_scene_engine(cut_clip: Path):
    out = _run(cut_clip, "--detail", "balanced")
    assert "(keyframe-scene" in out
    assert "**Detail:** balanced" in out


def test_token_burner_uses_scene_engine(cut_clip: Path):
    out = _run(cut_clip, "--detail", "token-burner")
    assert "(scene" in out


def test_transcript_skips_frames(cut_clip: Path):
    out = _run(cut_clip, "--detail", "transcript")
    assert "skipped" in out
    assert "frame_0000.jpg" not in out


def test_flag_overrides_env(cut_clip: Path):
    out = _run(cut_clip, "--detail", "efficient", env_extra={"WATCH_DETAIL": "balanced"})
    assert "(keyframe" in out


def test_default_is_balanced(cut_clip: Path):
    out = _run(cut_clip)  # no flag, WATCH_DETAIL cleared
    assert "**Detail:** balanced" in out
    assert "(keyframe-scene" in out


def test_timestamps_add_cue_frames_to_detail(cut_clip: Path):
    out = _run(cut_clip, "--detail", "balanced", "--timestamps", "1,3", "--no-sheets")
    assert "reason=transcript-cue" in out
    assert "reason=scene-change" in out  # detail frames still present (additive)


def test_timestamps_with_transcript_detail_is_cue_only(cut_clip: Path):
    out = _run(cut_clip, "--detail", "transcript", "--timestamps", "1,3")
    assert "reason=transcript-cue" in out
    assert "reason=scene-change" not in out
    assert "reason=keyframe" not in out


def _frame_lines(out: str) -> int:
    return sum(1 for line in out.splitlines() if "/frames/frame_" in line and "(t=" in line)


def test_dedup_collapses_static_by_default(static_clip: Path):
    out = _run(static_clip)  # solid blue → identical frames collapse to one
    assert "near-duplicate" in out
    assert _frame_lines(out) == 1


def test_no_dedup_preserves_static_frames(static_clip: Path):
    out = _run(static_clip, "--no-dedup", "--no-sheets")
    assert "near-duplicate" not in out
    assert _frame_lines(out) > 1


def test_balanced_report_lists_sheets_not_frames(cut_clip: Path):
    out = _run(cut_clip, "--detail", "balanced")
    assert "/sheets/sheet_01.jpg" in out
    assert "Read every sheet" in out
    assert _frame_lines(out) == 0  # per-frame lines replaced by one line per sheet


def test_no_sheets_flag_lists_frames(cut_clip: Path):
    out = _run(cut_clip, "--detail", "balanced", "--no-sheets")
    assert "/sheets/" not in out
    assert _frame_lines(out) > 1


def test_report_points_at_reusable_video(cut_clip: Path):
    out = _run(cut_clip, "--detail", "balanced")
    assert "Video file (reuse it" in out and str(cut_clip) in out


def test_sweep_removes_only_our_stale_dirs(tmp_path, monkeypatch):
    import importlib.util
    import os
    import time

    spec = importlib.util.spec_from_file_location("watch_main", WATCH)
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    monkeypatch.setattr(watch.tempfile, "gettempdir", lambda: str(tmp_path))

    old = time.time() - 48 * 3600
    ours_old = tmp_path / "watch-aaaa1111"
    ours_new = tmp_path / "watch-bbbb2222"
    foreign_old = tmp_path / "watch-somebody-else"
    for d in (ours_old, ours_new, foreign_old):
        d.mkdir()
    (ours_old / watch.WORKDIR_MARKER).touch()
    (ours_new / watch.WORKDIR_MARKER).touch()
    os.utime(ours_old, (old, old))
    os.utime(foreign_old, (old, old))

    assert watch.sweep_stale_workdirs() == 1
    assert not ours_old.exists()
    assert ours_new.exists()      # fresh: may still be serving follow-ups
    assert foreign_old.exists()   # no marker: not ours to delete


def _audio_only(path: Path) -> Path:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(path),
    ], check=True)
    return path


def test_failed_frames_still_report_the_transcript(tmp_path: Path, monkeypatch):
    """Frames failing (here: a file with no video stream) must not throw away a
    transcript we already have."""
    import cache

    audio = _audio_only(tmp_path / "talk.mp3")
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "xdg" / "video-skill")
    key = cache.cache_key(str(audio), ["es"], "", "")
    cache.save(key, {"transcript_source": "captions", "language": "es",
                     "segments": [{"start": 0.0, "end": 2.0, "text": "hola desde la caché"}]})

    out = _run(audio, "--lang", "es", "--whisper-lang", "", "--glossary", "",
               env_extra={"XDG_CACHE_HOME": str(tmp_path / "xdg")})
    assert "**Frames:** unavailable" in out
    assert "hola desde la caché" in out


def test_failed_frames_without_transcript_is_an_error(tmp_path: Path):
    audio = _audio_only(tmp_path / "talk.mp3")
    env = dict(os.environ, XDG_CACHE_HOME=str(tmp_path / "xdg"))
    proc = subprocess.run(
        [sys.executable, str(WATCH), str(audio), "--no-whisper", "--no-cache"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode != 0  # nothing to show: say so instead of an empty report


def test_missing_binaries_stop_the_run_with_setup_pointer(cut_clip: Path, tmp_path: Path):
    """Not a degraded report: the agent must see a failure and run setup."""
    env = dict(os.environ, PATH=str(tmp_path))  # nothing on PATH
    proc = subprocess.run(
        [sys.executable, str(WATCH), str(cut_clip), "--no-whisper"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 2
    assert "ffmpeg, ffprobe is not installed" in proc.stderr
    assert "setup.py" in proc.stderr
