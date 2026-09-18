"""Keyframe engine + preserved scene/uniform fallbacks."""
from __future__ import annotations

from pathlib import Path

import frames


def test_keyframe_engine_on_cut_clip(cut_clip: Path, tmp_path: Path):
    out, meta = frames.extract_keyframes(str(cut_clip), tmp_path / "f", max_frames=50)
    assert meta["engine"] == "keyframe"
    assert meta["fallback"] is False
    assert len(out) >= frames.KEYFRAME_MIN
    assert all(fr["reason"] == "keyframe" for fr in out)
    assert len(out) == len(list((tmp_path / "f").glob("frame_*.jpg")))


def test_keyframe_even_sampling_caps_and_spans(cut_clip: Path, tmp_path: Path):
    out, meta = frames.extract_keyframes(str(cut_clip), tmp_path / "f", max_frames=5)
    assert meta["engine"] == "keyframe"
    assert len(out) == 5
    assert meta["selected_count"] == 5
    assert meta["candidate_count"] > 5
    ts = [fr["timestamp_seconds"] for fr in out]
    assert ts == sorted(ts)
    assert ts[0] < ts[-1]  # spans first → last keyframe
    assert [fr["index"] for fr in out] == [0, 1, 2, 3, 4]


def test_keyframe_fallback_on_static_clip(static_clip: Path, tmp_path: Path):
    out, meta = frames.extract_keyframes(str(static_clip), tmp_path / "f", max_frames=50)
    assert meta["engine"] == "uniform"
    assert meta["fallback"] is True
    assert len(out) > 0
    assert all(fr["reason"] == "uniform" for fr in out)


def test_scene_engine_on_cut_clip(cut_clip: Path, tmp_path: Path):
    out, meta = frames.extract_scene_or_uniform(
        str(cut_clip), tmp_path / "f", fps=2.0, target_frames=50, max_frames=100, fast=False,
    )
    assert meta["engine"] == "scene"
    assert meta["fallback"] is False
    assert len(out) >= frames.SCENE_MIN_FRAMES


def test_scene_even_sampling_caps_and_spans(cut_clip: Path, tmp_path: Path):
    """Over-cap scene detection must even-sample across the whole clip, not keep
    the first N cuts and drop the tail (the long-video coverage bug)."""
    out, meta = frames.extract_scene_or_uniform(
        str(cut_clip), tmp_path / "f", fps=2.0, target_frames=50, max_frames=5, fast=False,
    )
    assert meta["engine"] == "scene"
    assert meta["fallback"] is False
    assert len(out) == 5
    assert meta["selected_count"] == 5
    assert meta["candidate_count"] > 5  # all cuts detected, then sampled down
    ts = [fr["timestamp_seconds"] for fr in out]
    assert ts == sorted(ts)
    assert ts[-1] > 4.0  # spans the full ~5.6s clip, not just the first ~1.6s
    assert len(out) == len(list((tmp_path / "f").glob("frame_*.jpg")))
    assert [fr["index"] for fr in out] == [0, 1, 2, 3, 4]


def test_scene_fallback_on_static_clip(static_clip: Path, tmp_path: Path):
    out, meta = frames.extract_scene_or_uniform(
        str(static_clip), tmp_path / "f", fps=2.0, target_frames=12, max_frames=100, fast=False,
    )
    assert meta["engine"] == "uniform"
    assert meta["fallback"] is True


# --- keyframe scene engine (the fast default) --------------------------------

def test_keyframe_scene_is_the_default_engine(cut_clip: Path, tmp_path: Path):
    out, meta = frames.extract_scene_or_uniform(
        str(cut_clip), tmp_path / "f", fps=2.0, target_frames=50, max_frames=100,
    )
    assert meta["engine"] == "keyframe-scene"
    assert meta["fallback"] is False
    assert len(out) >= frames.SCENE_MIN_FRAMES
    ts = [fr["timestamp_seconds"] for fr in out]
    assert ts == sorted(ts) and ts[0] == 0.0


def test_keyframe_scene_even_samples_across_whole_clip(cut_clip: Path, tmp_path: Path):
    out, meta = frames.extract_scene_or_uniform(
        str(cut_clip), tmp_path / "f", fps=2.0, target_frames=50, max_frames=5,
    )
    assert meta["engine"] == "keyframe-scene"
    assert len(out) == 5 and meta["candidate_count"] > 5
    assert out[-1]["timestamp_seconds"] > 4.0  # tail kept, not just the first cuts
    assert len(out) == len(list((tmp_path / "f").glob("frame_*.jpg")))


def test_keyframe_scene_reports_density(cut_clip: Path, tmp_path: Path):
    _, stats = frames.extract_keyframe_scenes(str(cut_clip), tmp_path / "f", duration_seconds=5.6)
    assert stats["keyframe_count"] >= 10  # conftest forces one per cut
    assert frames.keyframes_trustworthy(stats)


def test_sparse_keyframes_are_not_trusted(sparse_key_clip: Path, tmp_path: Path):
    frames_out, stats = frames.extract_keyframe_scenes(
        str(sparse_key_clip), tmp_path / "f", duration_seconds=36.0,
    )
    assert stats["keyframe_count"] == 1
    assert not frames.keyframes_trustworthy(stats)
    assert len(frames_out) == 1  # keyframes alone saw none of the 11 cuts


def test_sparse_keyframes_fall_back_to_full_decode(sparse_key_clip: Path, tmp_path: Path, capsys):
    out, meta = frames.extract_scene_or_uniform(
        str(sparse_key_clip), tmp_path / "f", fps=1.0, target_frames=30, max_frames=100,
        duration_seconds=36.0,
    )
    assert meta["engine"] == "scene"  # the full decode found the cuts
    assert len(out) >= frames.SCENE_MIN_FRAMES
    assert "too sparse" in capsys.readouterr().err


def test_packed_keyframes_are_not_trusted():
    """A good mean can hide a long hole; the max-gap check catches it."""
    stats = {"keyframe_count": 60, "mean_gap": 10.0, "max_gap": 540.0}
    assert not frames.keyframes_trustworthy(stats)
    assert frames.keyframes_trustworthy({"keyframe_count": 60, "mean_gap": 6.0, "max_gap": 10.0})
