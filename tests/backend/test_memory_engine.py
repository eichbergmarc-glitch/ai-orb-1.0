"""Tests für die Memory Engine."""

from __future__ import annotations

import pytest

from backend.memory.memory_index import MemoryIndex
from backend.memory.memory_search import MemorySearch
from backend.memory.memory_store import MemoryRecord, MemoryStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Ein MemoryStore, der ausschließlich in einem temporären Ordner arbeitet."""

    monkeypatch.setattr("backend.utils.store.get_data_dir", lambda: tmp_path)
    return MemoryStore(filename="test_memory.json")


@pytest.fixture()
def search(store):
    index = MemoryIndex()
    index.rebuild(store.all())
    return MemorySearch(store, index), index


def test_store_add_and_get(store):
    record = store.add(MemoryRecord(content="Kali Linux ist mein Hauptsystem."))
    loaded = store.get(record.id)
    assert loaded is not None
    assert loaded.content == "Kali Linux ist mein Hauptsystem."


def test_store_persists_across_instances(store, tmp_path, monkeypatch):
    store.add(MemoryRecord(content="Ein dauerhaft gespeicherter Eintrag."))

    monkeypatch.setattr("backend.utils.store.get_data_dir", lambda: tmp_path)
    reloaded = MemoryStore(filename="test_memory.json")
    assert reloaded.count() == 1


def test_store_filter_by_project(store):
    store.add(MemoryRecord(content="Projekt A Notiz", project_id="a"))
    store.add(MemoryRecord(content="Projekt B Notiz", project_id="b"))

    assert len(store.filter(project_id="a")) == 1
    assert len(store.filter(project_id="b")) == 1


def test_delete_where_removes_project_knowledge(store):
    store.add(MemoryRecord(content="Erste Notiz", project_id="a"))
    store.add(MemoryRecord(content="Zweite Notiz", project_id="a"))
    store.add(MemoryRecord(content="Fremde Notiz", project_id="b"))

    removed = store.delete_where(project_id="a")

    assert removed == 2
    assert store.count() == 1


def test_semantic_search_finds_related_wording(store, search):
    searcher, index = search
    record = store.add(
        MemoryRecord(content="Projekt Smart Home läuft auf einem Raspberry Pi.")
    )
    index.add(record)

    results = searcher.search("Mein Raspberry Projekt")

    assert results
    assert results[0].record.id == record.id


def test_search_respects_project_separation(store, search):
    searcher, index = search
    for record in [
        store.add(MemoryRecord(content="Investiturstreit Quellenlage", project_id="a")),
        store.add(MemoryRecord(content="Investiturstreit Forschung", project_id="b")),
    ]:
        index.add(record)

    results = searcher.search("Investiturstreit", project_id="a")

    assert all(result.record.project_id in (None, "a") for result in results)


def test_find_similar_detects_repetition(store, search):
    searcher, index = search
    record = store.add(MemoryRecord(content="Ich arbeite an einer Hausarbeit über das Mittelalter."))
    index.add(record)

    match = searcher.find_similar("Ich arbeite an einer Hausarbeit über das Mittelalter.")

    assert match is not None
    assert match.id == record.id


def test_index_removal_excludes_record(store, search):
    searcher, index = search
    record = store.add(MemoryRecord(content="Ein Eintrag über Quellenkritik."))
    index.add(record)
    index.remove(record.id)
    store.delete(record.id)

    assert searcher.search("Quellenkritik") == []
