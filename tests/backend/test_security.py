"""Tests der Sicherheitsschicht (Phase 8).

Geprüft wird vor allem das, was schiefgehen darf und nicht schiefgehen soll:
dass Unbekanntes verweigert wird, dass Schweigen als Nein gilt, und dass
sich der Pfadschutz nicht über ``..`` aushebeln lässt.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.events.event_bus import EventBus
from backend.security.audit_log import AuditEntry, AuditLog
from backend.security.consent import ConsentManager
from backend.security.path_guard import PathGuard
from backend.security.permissions import (
    KNOWN_PERMISSIONS,
    RiskLevel,
    describe,
    get_permission,
    highest_risk,
)


# --- Berechtigungen ---------------------------------------------------------


def test_known_permissions_are_complete() -> None:
    """Jede Berechtigung hat Beschreibung und Einstufung."""

    assert len(KNOWN_PERMISSIONS) >= 15
    for name, permission in KNOWN_PERMISSIONS.items():
        assert permission.name == name
        assert len(permission.description) > 10, f"{name} hat keine Beschreibung"
        assert isinstance(permission.risk, RiskLevel)


def test_critical_permissions_are_never_remembered() -> None:
    """Kritisches wird jedes Mal neu bestätigt."""

    for permission in KNOWN_PERMISSIONS.values():
        if permission.risk is RiskLevel.CRITICAL:
            assert not permission.remembering_allowed, permission.name


def test_safe_permissions_need_no_consent() -> None:
    """Unbedenkliches wird nicht erfragt."""

    assert not get_permission("read_time").requires_consent
    assert not get_permission("compute").requires_consent
    assert get_permission("delete_files").requires_consent


def test_unknown_permission_is_treated_as_critical() -> None:
    """Was nicht bekannt ist, gilt als schlimmstmöglich."""

    assert get_permission("zauberei") is None
    assert highest_risk(["read_time", "zauberei"]) is RiskLevel.CRITICAL

    described = describe(["zauberei"])
    assert described[0]["unknown"] is True
    assert described[0]["requires_consent"] is True


# --- Pfadschutz ---------------------------------------------------------------


def test_path_guard_allows_inside_root(tmp_path) -> None:
    guard = PathGuard([str(tmp_path)])
    target = tmp_path / "notiz.txt"
    target.write_text("Inhalt", encoding="utf-8")

    decision = guard.check_read(target)
    assert decision.allowed


def test_path_guard_blocks_traversal(tmp_path) -> None:
    """Ein Ausbruch über ``..`` wird abgewiesen."""

    inner = tmp_path / "freigegeben"
    inner.mkdir()
    guard = PathGuard([str(inner)])

    decision = guard.check_read(str(inner / ".." / "geheim.txt"))
    assert not decision.allowed
    assert "ausserhalb" in decision.reason.lower() or "außerhalb" in decision.reason.lower()


def test_path_guard_blocks_credentials(tmp_path) -> None:
    """Zugangsdaten sind auch im freigegebenen Ordner gesperrt."""

    guard = PathGuard([str(tmp_path)])
    decision = guard.check_read(tmp_path / ".env")
    assert not decision.allowed
    assert "Zugangsdaten" in decision.reason


def test_path_guard_blocks_executable_writes(tmp_path) -> None:
    """Ausführbares wird nicht geschrieben."""

    guard = PathGuard([str(tmp_path)])
    assert guard.check_write(tmp_path / "harmlos.txt").allowed
    assert not guard.check_write(tmp_path / "boese.exe").allowed
    assert not guard.check_write(tmp_path / "skript.ps1").allowed


def test_path_guard_without_roots_denies_everything(tmp_path) -> None:
    guard = PathGuard([])
    decision = guard.check_read(tmp_path / "irgendwas.txt")
    assert not decision.allowed
    assert "kein Ordner" in decision.reason


# --- Zustimmung ------------------------------------------------------------------


def test_silence_counts_as_refusal() -> None:
    """Kommt keine Antwort, wird nicht gehandelt."""

    async def scenario() -> None:
        manager = ConsentManager(EventBus(), timeout_seconds=10.0)
        # Die Untergrenze der Klasse liegt bei 10 Sekunden; für den Test
        # wird sie direkt gesetzt, damit er nicht so lange läuft.
        manager._timeout = 0.2  # noqa: SLF001

        decision = await manager.request(
            "test", get_permission("read_files"), "Etwas lesen"
        )
        assert not decision.granted
        assert "keine Antwort" in decision.reason

    asyncio.run(scenario())


def test_consent_can_be_granted_and_remembered() -> None:
    """Eine erteilte Zustimmung gilt und lässt sich merken."""

    async def scenario() -> None:
        manager = ConsentManager(EventBus(), timeout_seconds=10.0)
        manager.revoke_all()

        permission = get_permission("read_files")

        async def answer() -> None:
            """Beantwortet die Frage, sobald sie gestellt ist."""

            for _ in range(50):
                open_requests = manager.pending()
                if open_requests:
                    manager.resolve(open_requests[0]["request_id"], True, remember=True)
                    return
                await asyncio.sleep(0.02)

        task = asyncio.create_task(answer())
        decision = await manager.request("test", permission, "Etwas lesen")
        await task

        assert decision.granted
        assert decision.remembered
        assert manager.is_remembered("test", "read_files")

        # Beim zweiten Mal wird nicht mehr gefragt.
        second = await manager.request("test", permission, "Nochmal lesen")
        assert second.granted
        assert second.remembered

        assert manager.revoke("test", "read_files")
        assert not manager.is_remembered("test", "read_files")

    asyncio.run(scenario())


# --- Prüfprotokoll -----------------------------------------------------------------


def test_audit_log_records_and_reads_back() -> None:
    log = AuditLog(filename=f"security/test-audit-{int(time.time() * 1000)}.jsonl")

    log.record(
        AuditEntry(
            event="consent.granted",
            actor="test",
            permission="read_files",
            detail="Eine Datei lesen",
            allowed=True,
        )
    )
    log.record(
        AuditEntry(
            event="consent.denied",
            actor="test",
            permission="delete_files",
            detail="Etwas löschen",
            allowed=False,
        )
    )

    entries = log.recent(limit=10)
    assert len(entries) == 2
    # Neueste zuerst.
    assert entries[0]["permission"] == "delete_files"
    assert entries[0]["allowed"] is False

    gefiltert = log.recent(limit=10, permission="read_files")
    assert len(gefiltert) == 1

    summary = log.summary()
    assert summary["granted"] == 1
    assert summary["denied"] == 1

    log.path.unlink(missing_ok=True)


def test_audit_log_survives_broken_line() -> None:
    """Eine beschädigte Zeile macht das Protokoll nicht unlesbar."""

    log = AuditLog(filename=f"security/test-broken-{int(time.time() * 1000)}.jsonl")
    log.record(AuditEntry(event="a", actor="test", allowed=True))

    with log.path.open("a", encoding="utf-8") as handle:
        handle.write("{kaputt\n")

    log.record(AuditEntry(event="b", actor="test", allowed=True))

    entries = log.recent(limit=10)
    assert len(entries) == 2

    log.path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
#  Offener Modus
# ---------------------------------------------------------------------------
#
#  Der offene Modus ist die ausdrueckliche Entscheidung des Benutzers, auf
#  Rueckfragen und Pfadsperren zu verzichten. Getestet wird beides: dass er
#  wirklich alles erlaubt - und dass der geschuetzte Modus davon unberuehrt
#  bleibt. Ein Schalter, der versehentlich in die falsche Richtung wirkt,
#  waere hier besonders unangenehm.


def test_offener_modus_erlaubt_jeden_pfad():
    from backend.security.path_guard import PathGuard

    guard = PathGuard([], unrestricted=True)

    for pfad in ("C:/Windows/System32/kernel32.dll", "/etc/shadow", "~/.ssh/id_rsa"):
        assert guard.check_read(pfad).allowed, f"Lesen verweigert: {pfad}"
        assert guard.check_write(pfad).allowed, f"Schreiben verweigert: {pfad}"


def test_geschuetzter_modus_bleibt_streng():
    """Der Schalter darf nur in eine Richtung wirken."""

    from backend.security.path_guard import PathGuard

    guard = PathGuard(["~/Desktop"])

    entscheidung = guard.check_read("C:/Windows/System32/kernel32.dll")
    assert not entscheidung.allowed
    assert entscheidung.reason, "Eine Ablehnung ohne Begruendung ist keine."


def test_offener_modus_wird_trotzdem_protokolliert(tmp_path):
    """Erlauben heisst nicht vergessen.

    Das Pruefprotokoll ist das Einzige, was hinterher noch sagen kann, was
    geschehen ist. Es kostet nichts und faellt deshalb auch im offenen
    Modus nicht weg.
    """

    import asyncio

    from backend.config import get_config
    from backend.events.event_bus import EventBus
    from backend.security.security_engine import SecurityEngine

    config = get_config()
    vorher = config.get("security.mode", "geschuetzt")
    config._data.setdefault("security", {})["mode"] = "offen"

    try:
        engine = SecurityEngine(EventBus())
    finally:
        config._data["security"]["mode"] = vorher
    assert engine.is_open, "Der offene Modus wurde nicht erkannt."

    entscheidung = asyncio.run(
        engine.require("test", "system_commands", "Etwas Weitreichendes tun")
    )

    assert entscheidung.allowed, "Im offenen Modus wurde etwas verweigert."

    eintraege = engine.audit.recent(limit=10)
    assert any(
        eintrag.get("permission") == "system_commands" for eintrag in eintraege
    ), "Die erlaubte Aktion steht nicht im Pruefprotokoll."
