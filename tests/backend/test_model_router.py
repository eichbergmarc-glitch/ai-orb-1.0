"""Tests des ModelRouter und der OpenAI-kompatiblen Provider.

Geprueft wird die Leitregel aus Abschnitt 65: lokal wenn moeglich, Cloud
wenn noetig, Datenschutz ueber allem. Und die Sicherheitsgebote der
Abschnitte 11/12: kein Schluessel im Code, keiner in der Konfiguration.
"""

from __future__ import annotations

from backend.orchestrator.model_router import (
    Mode,
    ModelRouter,
    TaskProfile,
    profile_task,
)
from backend.orchestrator.providers.openai_compatible_provider import (
    PRESETS,
    OpenAICompatibleProvider,
)


def _router() -> ModelRouter:
    return ModelRouter()


# ---------------------------------------------------------------------------
#  Die Leitregel
# ---------------------------------------------------------------------------


def test_einfache_aufgabe_bleibt_lokal():
    router = _router()
    aufgabe = TaskProfile(complexity=0.3)
    entscheidung = router.route(aufgabe, ["claude_code", "ollama"], mode=Mode.AUTO)
    assert entscheidung.provider == "ollama", entscheidung.reason


def test_komplexe_aufgabe_geht_in_die_cloud():
    router = _router()
    aufgabe = TaskProfile(complexity=0.95)
    entscheidung = router.route(aufgabe, ["claude_code", "ollama"], mode=Mode.AUTO)
    assert entscheidung.provider == "claude_code", entscheidung.reason


def test_sensible_daten_bleiben_lokal_trotz_komplexitaet():
    """Datenschutz ueberstimmt alles - was einmal weg ist, ist gewesen."""

    router = _router()
    aufgabe = TaskProfile(complexity=0.95, sensitive=True)
    entscheidung = router.route(aufgabe, ["claude_code", "ollama"], mode=Mode.AUTO)
    assert entscheidung.provider == "ollama"
    assert "lokal" in entscheidung.reason.lower()


def test_offline_nimmt_nur_lokale_modelle():
    router = _router()
    aufgabe = TaskProfile(complexity=0.9)
    entscheidung = router.route(
        aufgabe, ["claude_code", "openai", "ollama"], mode=Mode.AUTO, online=False
    )
    assert entscheidung.provider == "ollama"


def test_offline_ohne_lokales_modell_meldet_das():
    """Ein ehrliches Scheitern ist besser als ein stiller Cloud-Aufruf."""

    router = _router()
    aufgabe = TaskProfile(complexity=0.5)
    entscheidung = router.route(aufgabe, ["claude_code", "openai"], online=False)
    assert entscheidung.provider == ""
    assert "offline" in entscheidung.reason.lower()


def test_qualitaetsmodus_nimmt_das_staerkste():
    router = _router()
    aufgabe = TaskProfile(complexity=0.3)  # eigentlich einfach
    entscheidung = router.route(
        aufgabe, ["claude_code", "ollama"], mode=Mode.QUALITY
    )
    assert entscheidung.provider == "claude_code"


def test_sparmodus_bevorzugt_das_guenstigste():
    router = _router()
    aufgabe = TaskProfile(complexity=0.7)
    entscheidung = router.route(
        aufgabe, ["claude_code", "ollama"], mode=Mode.CHEAPEST
    )
    assert entscheidung.provider == "ollama"


# ---------------------------------------------------------------------------
#  Eskalation (Abschnitt 15)
# ---------------------------------------------------------------------------


def test_schwache_lokale_antwort_eskaliert():
    router = _router()
    aufgabe = TaskProfile(complexity=0.5)
    entscheidung = router.route(aufgabe, ["claude_code", "ollama"], mode=Mode.AUTO)
    assert entscheidung.provider == "ollama"
    assert router.needs_escalation(entscheidung, quality=0.3) == "claude_code"


def test_gute_antwort_eskaliert_nicht():
    router = _router()
    aufgabe = TaskProfile(complexity=0.5)
    entscheidung = router.route(aufgabe, ["claude_code", "ollama"], mode=Mode.AUTO)
    assert router.needs_escalation(entscheidung, quality=0.9) is None


def test_sensible_daten_eskalieren_nicht_in_die_cloud():
    """Auch eine schwache Antwort rechtfertigt keine Preisgabe."""

    router = _router()
    aufgabe = TaskProfile(complexity=0.7, sensitive=True)
    entscheidung = router.route(aufgabe, ["claude_code", "ollama"], mode=Mode.AUTO)
    assert router.needs_escalation(entscheidung, quality=0.2) is None


# ---------------------------------------------------------------------------
#  Aufgabenerkennung
# ---------------------------------------------------------------------------


def test_zusammenfassung_gilt_als_einfach():
    profil = profile_task("Fasse diesen Text in drei Saetzen zusammen")
    assert profil.complexity < 0.5


def test_historiographie_gilt_als_komplex():
    profil = profile_task(
        "Analysiere die historiographische Kontroverse und begruende deine These"
    )
    assert profil.complexity >= 0.6


def test_lokale_datei_gilt_als_sensibel():
    profil = profile_task("Analysiere meine lokale Datei mit den privaten Notizen")
    assert profil.sensitive


# ---------------------------------------------------------------------------
#  Provider-Sicherheit (Abschnitte 11, 12)
# ---------------------------------------------------------------------------


def test_schluessel_kommt_nur_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "geheim-123")
    provider = OpenAICompatibleProvider({"preset": "openai", "model": "gpt-4o"})
    assert provider.api_key == "geheim-123"


def test_schluessel_steht_nicht_in_der_konfiguration():
    """Ein Schluessel in der Konfiguration wird ignoriert, nicht benutzt."""

    provider = OpenAICompatibleProvider(
        {"preset": "openai", "model": "gpt-4o", "api_key": "sollte-ignoriert-werden"}
    )
    # Der Wert aus der Konfiguration darf nicht als Schluessel dienen.
    assert provider.api_key != "sollte-ignoriert-werden"


def test_lokale_dienste_brauchen_keinen_schluessel():
    for preset in ("lmstudio", "llamacpp"):
        provider = OpenAICompatibleProvider({"preset": preset, "model": "x"})
        assert provider.is_local
        assert not provider._requires_key


def test_presets_haben_sinnvolle_vorgaben():
    assert PRESETS["openai"]["base_url"].startswith("https://")
    assert PRESETS["lmstudio"]["base_url"].startswith("http://127.0.0.1")
    assert not PRESETS["lmstudio"]["requires_key"]
