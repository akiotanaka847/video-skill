"""Config resolution: detail, caption languages, Whisper hints, frame caps."""
from __future__ import annotations

import config
import pytest


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Point both config files at nonexistent paths.

    Without neutralising LEGACY_CONFIG_FILE too, these tests would read the
    developer's real ~/.config/watch/.env and pass or fail based on their
    machine rather than on the code.
    """
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(config, "LEGACY_CONFIG_FILE", tmp_path / "missing-legacy.env")
    for var in (
        "WATCH_DETAIL", "WATCH_SUB_LANGS", "WATCH_WHISPER_LANG",
        "WATCH_GLOSSARY", "WATCH_CACHE", "WATCH_NOTES_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


def test_default_detail_is_balanced():
    assert config.get_config()["detail"] == "balanced"


def test_env_overrides_detail(monkeypatch):
    monkeypatch.setenv("WATCH_DETAIL", "efficient")
    assert config.get_config()["detail"] == "efficient"


def test_invalid_detail_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("WATCH_DETAIL", "bogus")
    assert config.get_config()["detail"] == "balanced"


def test_get_config_keys():
    assert set(config.get_config()) == {
        "detail", "sub_langs", "whisper_lang", "glossary",
        "cache_enabled", "notes_dir", "config_file", "cache_dir",
    }


def test_default_sub_langs_is_spanish_first():
    assert config.get_config()["sub_langs"] == ["es", "en"]


def test_sub_langs_from_env(monkeypatch):
    monkeypatch.setenv("WATCH_SUB_LANGS", " fr , de ,fr ")
    # Whitespace trimmed, duplicates dropped, order preserved.
    assert config.get_config()["sub_langs"] == ["fr", "de"]


def test_sub_lang_patterns_shape():
    patterns, markers = config.sub_lang_patterns(["es", "en"])
    assert patterns == "es.*,en.*"
    # Manual tracks are preferred over YouTube's '-orig' auto track.
    assert markers.index(".es.") < markers.index(".es-orig.")


def test_sub_lang_patterns_falls_back_when_empty():
    patterns, _ = config.sub_lang_patterns([])
    assert patterns == "es.*,en.*"


def test_cache_enabled_by_default():
    assert config.get_config()["cache_enabled"] is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE"])
def test_cache_can_be_disabled(monkeypatch, value):
    monkeypatch.setenv("WATCH_CACHE", value)
    assert config.get_config()["cache_enabled"] is False


def test_whisper_lang_and_glossary_default_empty():
    cfg = config.get_config()
    assert cfg["whisper_lang"] == "" and cfg["glossary"] == ""


def test_whisper_hints_from_env(monkeypatch):
    monkeypatch.setenv("WATCH_WHISPER_LANG", "es")
    monkeypatch.setenv("WATCH_GLOSSARY", "Workfront, Qaio")
    cfg = config.get_config()
    assert cfg["whisper_lang"] == "es" and cfg["glossary"] == "Workfront, Qaio"


def test_env_file_inline_comment_is_stripped(monkeypatch, tmp_path):
    env = tmp_path / "with-comment.env"
    env.write_text("WATCH_DETAIL=efficient  # note\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", env)
    assert config.get_config()["detail"] == "efficient"


def test_current_config_wins_over_legacy(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.env"
    legacy.write_text("WATCH_DETAIL=efficient\nGROQ_API_KEY=inherited\n", encoding="utf-8")
    current = tmp_path / "current.env"
    current.write_text("WATCH_DETAIL=token-burner\n", encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_CONFIG_FILE", legacy)
    monkeypatch.setattr(config, "CONFIG_FILE", current)
    assert config.get_config()["detail"] == "token-burner"
    # Keys only present in the legacy file are still inherited.
    assert config.read_all_env()["GROQ_API_KEY"] == "inherited"


def test_frame_cap_mapping():
    assert config.frame_cap("efficient") == 50
    assert config.frame_cap("balanced") == 100
    assert config.frame_cap("token-burner") is None
    assert config.frame_cap("transcript") is None
    assert config.frame_cap("anything-else") == 100
