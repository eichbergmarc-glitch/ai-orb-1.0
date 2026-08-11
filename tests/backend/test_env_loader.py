"""Tests für das Einlesen der Datei ``.env``."""

from __future__ import annotations

import os

import pytest

from backend.config.env_loader import load_env_file, parse_env_text


def test_parses_simple_pairs():
    values = parse_env_text("ANTHROPIC_API_KEY=abc123\nHERMES_API_KEY=xyz")

    assert values["ANTHROPIC_API_KEY"] == "abc123"
    assert values["HERMES_API_KEY"] == "xyz"


def test_ignores_comments_and_blank_lines():
    values = parse_env_text("# Kommentar\n\n  \nKEY=wert\n")

    assert values == {"KEY": "wert"}


def test_strips_quotes():
    values = parse_env_text('A="in doppelten"\nB=\'in einfachen\'')

    assert values["A"] == "in doppelten"
    assert values["B"] == "in einfachen"


def test_supports_export_prefix():
    values = parse_env_text("export KEY=wert")

    assert values["KEY"] == "wert"


def test_strips_trailing_comment():
    values = parse_env_text("KEY=wert # ein Hinweis")

    assert values["KEY"] == "wert"


def test_keeps_hash_inside_quotes():
    values = parse_env_text('KEY="wert # kein Kommentar"')

    assert values["KEY"] == "wert # kein Kommentar"


def test_value_may_contain_equals_sign():
    values = parse_env_text("KEY=abc=def=ghi")

    assert values["KEY"] == "abc=def=ghi"


def test_lines_without_equals_are_skipped():
    values = parse_env_text("nur text\nKEY=wert")

    assert values == {"KEY": "wert"}


def test_missing_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "gibt-es-nicht") == []


def test_loads_into_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_ORB_TESTSCHLUESSEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("AI_ORB_TESTSCHLUESSEL=geheim\n", encoding="utf-8")

    applied = load_env_file(env_file)

    assert "AI_ORB_TESTSCHLUESSEL" in applied
    assert os.environ["AI_ORB_TESTSCHLUESSEL"] == "geheim"
    os.environ.pop("AI_ORB_TESTSCHLUESSEL", None)


def test_existing_environment_wins(tmp_path, monkeypatch):
    """Ein bereits gesetzter Wert darf nicht überschrieben werden."""

    monkeypatch.setenv("AI_ORB_TESTSCHLUESSEL", "aus_der_umgebung")
    env_file = tmp_path / ".env"
    env_file.write_text("AI_ORB_TESTSCHLUESSEL=aus_der_datei\n", encoding="utf-8")

    load_env_file(env_file)

    assert os.environ["AI_ORB_TESTSCHLUESSEL"] == "aus_der_umgebung"


def test_empty_placeholder_is_ignored(tmp_path, monkeypatch):
    """Ein leerer Platzhalter aus der Vorlage darf nichts überschreiben."""

    monkeypatch.setenv("AI_ORB_TESTSCHLUESSEL", "echter_wert")
    env_file = tmp_path / ".env"
    env_file.write_text("AI_ORB_TESTSCHLUESSEL=\n", encoding="utf-8")

    load_env_file(env_file)

    assert os.environ["AI_ORB_TESTSCHLUESSEL"] == "echter_wert"


def test_override_replaces_existing_value(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ORB_TESTSCHLUESSEL", "alt")
    env_file = tmp_path / ".env"
    env_file.write_text("AI_ORB_TESTSCHLUESSEL=neu\n", encoding="utf-8")

    load_env_file(env_file, override=True)

    assert os.environ["AI_ORB_TESTSCHLUESSEL"] == "neu"
