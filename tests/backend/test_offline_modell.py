"""Tests des Offline-Betriebs.

Der Benutzer will, dass der Orb ohne Internet weiterarbeitet: ein lokales
Modell springt ein, mit denselben Funktionen und demselben Wissen, und die
Stimme spricht auch offline.

Das meiste davon ist Architektur, die schon steht - das lokale Modell geht
denselben Weg wie das Online-Gehirn und bekommt deshalb dieselben
Werkzeuge und dasselbe Gedaechtnis. Diese Tests sichern die wenigen
Stellen, die dafuer WIRKLICH stimmen muessen und die still kippen koennten.
"""

from __future__ import annotations

import asyncio

import yaml

from backend.utils.paths import get_project_root


def _config() -> dict:
    return yaml.safe_load((get_project_root() / "config.yaml").read_text(encoding="utf-8"))


def test_das_fallback_modell_ist_ein_lokales_ollama_modell():
    """Das Fallback-Modell muss lokal LAUFEN - nicht nur gut gewaehlt sein.

    Hier stand vorher die Forderung, es muesse qwen2.5 sein. Das Protokoll
    des Benutzers zeigte, warum das zu wenig ist: Der Orb WAR auf
    qwen2.5:7b-instruct eingestellt - und es war nicht installiert
    ("Ollama laeuft, aber Modell 'qwen2.5:7b-instruct' ist nicht
    installiert. Verfuegbar: llama3.1:8b, llama3.2:3b"). Offline sprang
    damit gar nichts ein. Ein Modell, das nicht auf dem Rechner liegt, ist
    offline wertlos, so gut es sonst auch waere.

    Darum sichert dieser Test das, worauf es ankommt: eine lokale
    Ollama-Engine und ein gesetztes Modell. Welches genau, entscheidet,
    was auf dem Rechner liegt - hier ist es das schon installierte
    llama3.1:8b.
    """

    fb = _config()["ai"]["fallback"]
    assert fb["engine"] == "ollama"
    assert fb.get("model"), "Ohne Modellnamen springt offline nichts ein."
    assert fb["base_url"].startswith("http://127.0.0.1"), (
        "Das Fallback muss lokal laufen, sonst ist es offline nutzlos."
    )


def test_das_modell_wird_warm_gehalten():
    """Sonst laedt Ollama es nach jeder Pause neu und die erste Antwort dauert."""

    fb = _config()["ai"]["fallback"]
    assert fb.get("keep_alive"), "Ohne keep_alive wird das Modell staendig neu geladen."


def test_die_offline_stimme_ist_konfiguriert():
    d = _config()
    tts = d["voice"]["output"] if "voice" in d and "output" in d["voice"] else d.get("tts", {})
    engines = tts.get("engines", [])
    assert "piper" in engines, "Ohne Piper gibt es offline keine Stimme."


def test_ollama_schickt_keep_alive_mit(monkeypatch):
    """Die Einstellung muss auch wirklich in der Anfrage landen."""

    from backend.orchestrator.providers.ollama_provider import OllamaProvider
    from backend.orchestrator.providers.base_provider import ChatMessage

    provider = OllamaProvider({"model": "qwen2.5:7b-instruct", "keep_alive": "30m"})

    gesehen: dict = {}

    async def _fake(url, payload=None, method="POST", timeout=None):
        gesehen.update(payload or {})
        return {"message": {"content": "ok"}}

    monkeypatch.setattr(provider, "_request_json", _fake)
    asyncio.run(provider.chat([ChatMessage(role="user", content="Hallo")]))

    assert gesehen.get("keep_alive") == "30m", (
        "Das Modell wird nicht warm gehalten - keep_alive fehlt in der Anfrage."
    )
    assert "options" in gesehen and "temperature" in gesehen["options"]


def test_das_lokale_modell_bekommt_dieselben_nachrichten():
    """Werkzeuge und Gedaechtnis kommen ueber die messages - fuer JEDEN Provider gleich.

    Der Beleg ist, dass der Ollama-Provider die messages unveraendert
    weiterreicht (kein eigener, abgespeckter Weg). Faende sich hier ein
    Sonderpfad, der die Werkzeuge weglaesst, waere das Offline-Modell
    stumm gestellt.
    """

    import inspect
    from backend.orchestrator.providers.ollama_provider import OllamaProvider

    quelle = inspect.getsource(OllamaProvider.chat)
    assert "message.to_dict() for message in messages" in quelle, (
        "Der Ollama-Provider baut die Nachrichten anders zusammen - dann "
        "koennte er Werkzeuge oder Gedaechtnis verlieren."
    )


def test_der_umschalter_faellt_bei_einem_fehler_weiter():
    """Offline heisst: der aktive (Online-)Provider wirft - dann muss der
    naechste dran, nicht ein Fehler an den Benutzer."""

    import inspect
    from backend.orchestrator.provider_manager import ProviderManager

    quelle = inspect.getsource(ProviderManager.chat)
    # Der Rueckfall selbst: Bei einem Fehler wird der naechste Provider
    # versucht (die Schleife) und die erste erfolgreiche Antwort geliefert.
    assert "for name in order" in quelle
    assert "return response" in quelle, (
        "Die Anfrage faellt bei einem Fehler nicht auf den naechsten "
        "Provider zurueck - offline bekaeme der Benutzer dann einen Fehler."
    )
    # Und das Gegenstueck: Ein EINZELNER Ausweichtreffer darf den schwachen
    # Provider NICHT dauerhaft aktiv machen. Sonst strandet die Sitzung nach
    # einem kurzen Claude-Wackler beim lokalen Modell, und Bildschirm-Ansehen
    # wie Werkzeuge fallen ploetzlich aus.
    assert "aktiv bleibt" in quelle, (
        "Ein Ausweichtreffer macht den Ausweichprovider zum Dauerzustand - "
        "das strandet die Sitzung beim schwachen Modell."
    )
