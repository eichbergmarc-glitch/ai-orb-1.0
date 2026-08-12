"""Der Selbsttest beim Start prüft, was im Betrieb aussetzte.

Der Benutzer wollte einen Selbsttest, der grün/rot zeigt, ob die
Fähigkeiten wirklich da sind - Werkzeuge, Suche, Bildschirmfoto. Diese
Tests sichern: die Prüfungen stürzen nie ab, melden bei Fehlern eine
Warnung (statt den Start zu blockieren) und erklären den Grund im Klartext.
"""

from __future__ import annotations

from backend.launcher.health_check import CheckState, HealthCheck


def test_werkzeugpruefung_findet_die_kernwerkzeuge():
    state, detail, _ = HealthCheck().check_werkzeuge()
    # In dieser Umgebung sind Such- und Lesewerkzeug immer dabei.
    assert state in (CheckState.OK, CheckState.WARNING)
    assert "Werkzeug" in detail or "Kern" in detail


def test_suchpruefung_stuerzt_nie_ab_und_erklaert_sich():
    # Ob Netz da ist oder nicht - die Prüfung liefert immer ein Ergebnis mit
    # Erklärung, nie eine Ausnahme.
    state, detail, remedy = HealthCheck().check_suche()
    assert state in (CheckState.OK, CheckState.WARNING)
    if state is CheckState.WARNING:
        assert remedy  # ein Grund im Klartext


def test_bildschirmpruefung_ist_nie_blockierend():
    state, _, _ = HealthCheck().check_bildschirm_fotografieren()
    assert state in (CheckState.OK, CheckState.WARNING)


def test_selbsttest_taucht_im_bericht_auf_und_blockiert_start_nicht():
    bericht = HealthCheck().run(include_optional=True)
    namen = {r.name for r in bericht.results}
    assert {"Werkzeuge", "Suche", "Bildschirmfoto"} <= namen
    # Die drei sind entbehrlich: Selbst wenn Suche/Bildschirm hier (ohne Netz,
    # ohne mss) warnen, darf der Start nicht als "nicht bereit" gelten,
    # solange die notwendigen Prüfungen stehen.
    for r in bericht.results:
        if r.name in {"Suche", "Bildschirmfoto", "Werkzeuge"}:
            assert r.required is False


def test_fehlgeschlagene_pruefung_liefert_immer_ein_ergebnis(monkeypatch):
    # Eine Prüfung, die eine Ausnahme wirft, wird vom Rahmen abgefangen und
    # als FAILED mit Erklärung gemeldet - nicht als Absturz.
    hc = HealthCheck()

    def _explodiert():
        raise RuntimeError("kaputt")

    ergebnis = hc._run("Testprüfung", _explodiert, required=False)
    assert ergebnis.state is CheckState.FAILED
    assert "kaputt" in ergebnis.remedy
