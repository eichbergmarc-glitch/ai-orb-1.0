"""Tests der beiden Bremsen, die den Orb langsam machten.

Gefunden wurden sie nicht durch Nachdenken, sondern im Protokoll des
Benutzers - und das ist der Punkt: Vorher stand dort NICHTS ueber
Antwortzeiten. `latency_seconds` wurde im Code erfasst und nirgends
aufgeschrieben. Was man nicht misst, verbessert man nicht, sondern glaubt
es nur.

Zwei Befunde:

**Der Warmstart war aus.** Ich hatte ihn abgeschaltet, als er den Orb
lahmlegte. Das Sicherheitsnetz dagegen faengt jede EINZELNE Frage ab -
aber nicht den Fall, dass der Warmstart dauerhaft kaputt ist. Dann zahlt
jede Frage erst die vergebliche Frist und danach den vollen Neustart, und
der Warmstart macht den Orb langsamer statt schneller. Dafuer ist der
Wachhund da.

**Jede Minute eine Pruefung.** 271 Mal im Protokoll startete der Orb einen
eigenen Prozess, um zu fragen, ob Claude Code erreichbar ist - auch dann,
wenn Claude Code Sekunden zuvor eine ganze Antwort geliefert hatte.
"""

from __future__ import annotations

import asyncio
import time

from backend.orchestrator.provider_health import ProviderHealth


class _Anbieter:
    """Ein Anbieter, der mitzaehlt, wie oft er gefragt wird."""

    def __init__(self, name: str = "test", erreichbar: bool = True):
        self.name = name
        self.erreichbar = erreichbar
        self.gefragt = 0

    async def is_available(self) -> bool:
        self.gefragt += 1
        return self.erreichbar


# --- Die Minutenpruefung ----------------------------------------------------------


def test_wer_gerade_geantwortet_hat_wird_nicht_gefragt():
    """Der Kern der Sache: Eine gelungene Antwort IST der Beweis.

    Die Pruefung startet bei Claude Code einen eigenen Prozess, und der
    kostet auf Windows Sekunden.
    """

    monitor = ProviderHealth(interval_seconds=60)
    anbieter = _Anbieter()
    monitor.register(anbieter)

    monitor.note_success("test", latency=1.2)
    asyncio.run(monitor.check_now())

    assert anbieter.gefragt == 0, "es wurde trotz frischer Antwort nachgefragt"


def test_ohne_frische_antwort_wird_sehr_wohl_gefragt():
    """Sonst haette man die Ueberwachung abgeschafft statt entschaerft."""

    monitor = ProviderHealth(interval_seconds=60)
    anbieter = _Anbieter()
    monitor.register(anbieter)

    asyncio.run(monitor.check_now())
    assert anbieter.gefragt == 1


def test_bestaetigt_abwesender_provider_wird_nicht_jede_minute_gestartet():
    monitor = ProviderHealth(interval_seconds=60)
    anbieter = _Anbieter(erreichbar=False)
    monitor.register(anbieter)

    asyncio.run(monitor.check_now(force=True))
    asyncio.run(monitor.check_now())

    assert anbieter.gefragt == 1


def test_eine_alte_antwort_zaehlt_nicht_mehr():
    """Meldet sich der Anbieter zwischendurch ab, soll das auffallen."""

    monitor = ProviderHealth(interval_seconds=60)
    anbieter = _Anbieter()
    monitor.register(anbieter)

    monitor.note_success("test", latency=1.0)
    eintrag = monitor.record("test")
    eintrag.last_success = time.time() - (ProviderHealth.VERTRAUENSDAUER + 10)

    asyncio.run(monitor.check_now())
    assert anbieter.gefragt == 1


def test_die_startpruefung_fragt_wirklich_nach():
    """Beim Start gibt es keine Antwort, an der man sich orientieren koennte."""

    monitor = ProviderHealth(interval_seconds=60)
    anbieter = _Anbieter()
    monitor.register(anbieter)

    monitor.note_success("test", latency=1.0)
    asyncio.run(monitor.check_now(force=True))

    assert anbieter.gefragt == 1


def test_hintergrundpruefung_konkurriert_nicht_mit_einer_antwort():
    """Ein Health-Check darf keinen Prozess waehrend des Dialogzugs starten."""

    monitor = ProviderHealth(interval_seconds=60)
    anbieter = _Anbieter()
    monitor.register(anbieter)
    monitor.set_busy_check(lambda: True)

    ergebnis = asyncio.run(monitor.check_now())

    assert anbieter.gefragt == 0
    assert ergebnis == {"test": False}


def test_erzwungene_pruefung_bleibt_auch_waehrend_dialog_moeglich():
    monitor = ProviderHealth(interval_seconds=60)
    anbieter = _Anbieter()
    monitor.register(anbieter)
    monitor.set_busy_check(lambda: True)

    asyncio.run(monitor.check_now(force=True))

    assert anbieter.gefragt == 1


def test_die_grenzen_sind_vernuenftig_gewaehlt():
    """Zu lang, und ein Ausfall faellt erst nach einer Viertelstunde auf."""

    assert 120.0 <= ProviderHealth.VERTRAUENSDAUER <= 600.0
    assert ProviderHealth.MAX_INTERVAL <= 1800.0
    assert 120.0 <= ProviderHealth.UNAVAILABLE_RETRY_INTERVAL <= 600.0


def test_der_abstand_geht_bei_einem_fehlschlag_sofort_zurueck():
    """Wenn etwas nicht stimmt, will man es schnell wissen.

    Nachgerechnet wird die Regel aus der Schleife - eine Schleife mit
    echten Wartezeiten liesse sich nicht in einem Test pruefen, ohne ihn
    minutenlang laufen zu lassen.
    """

    interval, hoechstens = 60.0, 900.0

    def naechster(abstand: float, alles_gut: bool) -> float:
        return min(hoechstens, abstand * 1.6) if alles_gut else interval

    abstand = interval
    for _ in range(20):
        abstand = naechster(abstand, True)
    assert abstand == hoechstens, "der Abstand waechst nicht"

    assert naechster(abstand, False) == interval, "er geht nicht sofort zurueck"


# --- Der Wachhund ueber dem Warmstart ----------------------------------------------


class _Halber:
    """Nur die Wachhund-Methoden, ohne Prozesse und Netz."""

    def __init__(self):
        from backend.orchestrator.providers.claude_code_provider import ClaudeCodeProvider

        self.p = ClaudeCodeProvider.__new__(ClaudeCodeProvider)
        self.p._warm_fehler = 0
        self.p._warm_broken = False
        self.K = ClaudeCodeProvider

    def scheitern(self, grund="Zeitlimit"):
        self.K._warm_gescheitert(self.p, grund)

    def gelingen(self):
        self.K._warm_gelungen(self.p)


def test_ein_einzelner_ausrutscher_schaltet_nichts_ab():
    """Ein einzelner Fehlschlag kann eine ueberlange Frage sein."""

    halb = _Halber()
    halb.scheitern()
    assert not halb.p._warm_broken


def test_zwei_fehlschlaege_legen_den_warmstart_still():
    """Sonst zahlt jede Frage erst die Frist und dann den Neustart."""

    halb = _Halber()
    halb.scheitern()
    halb.scheitern()
    assert halb.p._warm_broken


def test_eine_gelungene_antwort_setzt_den_zaehler_zurueck():
    """Zwei voellig unabhaengige Ausrutscher duerfen nicht zusammenzaehlen."""

    halb = _Halber()
    halb.scheitern()
    halb.gelingen()
    halb.scheitern()

    assert not halb.p._warm_broken, "der Zaehler wurde nicht zurueckgesetzt"


def test_der_warmstart_ist_wieder_eingeschaltet():
    """Ohne ihn zahlt jede Frage die Anlaufzeit der Befehlszeile."""

    from backend.config import get_config

    assert bool(get_config().get("ai.primary.warm_process", False)), (
        "der Warmstart ist aus - jede Frage zahlt die Anlaufzeit"
    )


def test_die_dauer_steht_jetzt_im_protokoll():
    """Was man nicht misst, verbessert man nicht, sondern glaubt es nur."""

    from backend.utils.paths import get_project_root

    quelle = (
        get_project_root()
        / "backend"
        / "orchestrator"
        / "providers"
        / "claude_code_provider.py"
    ).read_text(encoding="utf-8")

    assert "Antwort in %.1f s" in quelle, "die Antwortzeit wird nirgends notiert"
