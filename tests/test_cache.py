"""Transcript cache: key invalidation, expiry, and failure tolerance."""
from __future__ import annotations

import json
import time

import cache
import pytest


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")


SEGMENTS = [{"start": 0.0, "end": 1.5, "text": "hola mundo"}]


def _key(**over):
    args = {"source": "https://youtu.be/abc", "sub_langs": ["es", "en"],
            "whisper_lang": "es", "glossary": "Workfront"}
    args.update(over)
    return cache.cache_key(**args)


def test_key_is_stable_for_identical_inputs():
    assert _key() == _key()


@pytest.mark.parametrize("field,value", [
    ("source", "https://youtu.be/other"),
    ("sub_langs", ["en"]),
    ("whisper_lang", "en"),
    ("glossary", "Workfront, Qaio"),
])
def test_every_transcript_affecting_input_invalidates(field, value):
    """Changing the glossary must miss — otherwise you tune vocabulary,
    re-run, and silently get the previous transcript back."""
    assert _key() != _key(**{field: value})


def test_roundtrip():
    key = _key()
    cache.save(key, {"segments": SEGMENTS, "transcript_source": "captions", "language": "es"})
    got = cache.load(key)
    assert got is not None
    assert got["segments"] == SEGMENTS
    assert got["language"] == "es"


def test_miss_on_unknown_key():
    assert cache.load(_key()) is None


def test_expired_entry_is_a_miss():
    key = _key()
    cache.save(key, {"segments": SEGMENTS})
    stale = time.time() - 40 * 86400
    path = cache._entry_path(key)
    payload = json.loads(path.read_text())
    payload["created_at"] = stale
    path.write_text(json.dumps(payload))
    assert cache.load(key, max_age_days=30) is None
    # max_age_days=0 disables expiry entirely.
    assert cache.load(key, max_age_days=0) is not None


def test_corrupt_entry_degrades_to_miss():
    """A broken cache must produce a slower run, never a failed one."""
    key = _key()
    path = cache._entry_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert cache.load(key) is None


def test_version_bump_invalidates(monkeypatch):
    key = _key()
    cache.save(key, {"segments": SEGMENTS})
    monkeypatch.setattr(cache, "CACHE_VERSION", cache.CACHE_VERSION + 1)
    assert cache.load(key) is None


def test_empty_segments_are_not_served():
    key = _key()
    cache.save(key, {"segments": []})
    assert cache.load(key) is None


def test_local_file_identity_tracks_mtime_and_size(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"aaaa")
    first = cache.cache_key(str(video), ["es"])
    video.write_bytes(b"bbbbbbbb")  # different size -> different content
    assert cache.cache_key(str(video), ["es"]) != first


def test_purge_removes_only_expired():
    fresh, old = _key(), _key(source="https://youtu.be/old")
    cache.save(fresh, {"segments": SEGMENTS})
    cache.save(old, {"segments": SEGMENTS})
    import os
    stale = time.time() - 90 * 86400
    os.utime(cache._entry_path(old), (stale, stale))
    assert cache.purge(max_age_days=30) == 1
    assert cache.load(fresh) is not None


def test_stats_counts_entries():
    cache.save(_key(), {"segments": SEGMENTS})
    assert cache.stats()["entries"] == 1
