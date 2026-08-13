"""Tests für backend.config.config_loader."""

from __future__ import annotations

import pytest

from backend.config.config_loader import ConfigError, ConfigLoader


SAMPLE_CONFIG = """
app:
  name: "AI-Orb Test"
  version: "9.9.9"

window:
  width: 220
  height: 220
  frameless: true

nested:
  a:
    b:
      c: 42
"""


@pytest.fixture()
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    return path


def test_get_returns_top_level_value(config_file):
    loader = ConfigLoader(config_path=config_file)
    assert loader.get("app.name") == "AI-Orb Test"


def test_get_returns_deeply_nested_value(config_file):
    loader = ConfigLoader(config_path=config_file)
    assert loader.get("nested.a.b.c") == 42


def test_get_returns_default_for_missing_key(config_file):
    loader = ConfigLoader(config_path=config_file)
    assert loader.get("does.not.exist", "fallback") == "fallback"


def test_get_returns_none_by_default_for_missing_key(config_file):
    loader = ConfigLoader(config_path=config_file)
    assert loader.get("does.not.exist") is None


def test_section_returns_dict(config_file):
    loader = ConfigLoader(config_path=config_file)
    assert loader.section("window") == {
        "width": 220,
        "height": 220,
        "frameless": True,
    }


def test_section_returns_empty_dict_for_missing_section(config_file):
    loader = ConfigLoader(config_path=config_file)
    assert loader.section("does_not_exist") == {}


def test_missing_file_raises_config_error(tmp_path):
    missing_path = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ConfigError):
        ConfigLoader(config_path=missing_path)


def test_invalid_top_level_type_raises_config_error(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigLoader(config_path=path)


def test_reload_picks_up_changes(config_file):
    loader = ConfigLoader(config_path=config_file)
    assert loader.get("app.version") == "9.9.9"

    config_file.write_text(
        SAMPLE_CONFIG.replace('"9.9.9"', '"10.0.0"'), encoding="utf-8"
    )
    loader.reload()
    assert loader.get("app.version") == "10.0.0"


def test_real_project_config_loads_successfully():
    """Stellt sicher, dass die tatsächliche config.yaml des Projekts von
    ConfigLoader ohne Fehler eingelesen werden kann."""

    loader = ConfigLoader()
    assert loader.get("app.name") == "AI-Orb"
    assert isinstance(loader.section("window"), dict)
    assert isinstance(loader.section("orb"), dict)


@pytest.mark.parametrize(
    ("text", "path"),
    [
        ("backend:\n  port: 99999\n", "backend.port"),
        ("orb:\n  scale: riesig\n", "orb.scale"),
        ("window:\n  start_position: irgendwo\n", "window.start_position"),
        ("states:\n  idle:\n    scale: 4\n", "states.idle.scale"),
    ],
)
def test_schema_meldet_den_genauen_pfad(tmp_path, text, path):
    config = tmp_path / "config.yaml"
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=path.replace(".", r"\.")):
        ConfigLoader(config_path=config)


def test_yaml_fehler_meldet_zeile(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("orb:\n  scale: [1,\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Zeile"):
        ConfigLoader(config_path=config)
