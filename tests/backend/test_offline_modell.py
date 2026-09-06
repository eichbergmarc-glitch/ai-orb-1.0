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


def test_lfm_hat_konservative_temperatur_und_10k_kontext():
    """Die lokalen Leistungsparameter muessen nicht nur empfohlen, sondern aktiv sein."""

    fb = _config()["ai"]["fallback"]
    assert fb["model"] == "lfm2.5:8b"
    assert 0.2 <= float(fb["temperature"]) <= 0.3
    assert 8192 <= int(fb["context_window"]) <= 12288
    assert int(fb["minimum_predict_tokens"]) >= 512


def test_lokales_nebenmodell_ist_getrennt_und_speicherschonend_konfiguriert():
    """Llama darf LFM ergaenzen, aber weder ersetzen noch parallel belasten."""

    ai = _config()["ai"]
    routing = ai["local_routing"]
    fast = ai["additional"][routing["fast_provider"]]

    assert routing["enabled"] is True
    assert routing["main_provider"] == "ollama"
    assert routing["sequential_only"] is True
    assert fast["engine"] == "ollama"
    assert fast["instance_name"] == routing["fast_provider"]
    assert fast["model"] == "llama3.2:3b"
    assert int(fast["context_window"]) <= 4096
    assert int(fast["minimum_predict_tokens"]) < int(
        ai["fallback"]["minimum_predict_tokens"]
    )


def test_die_offline_stimme_ist_konfiguriert():
    """Offline spricht nur, was auf diesem Rechner laeuft.

    Geprueft wird die Eigenschaft, nicht der Name: Im Offlinebetrieb darf
    keine Cloudstimme in der Liste stehen, und die letzte Instanz der
    normalen Reihe muss lokal sein - sonst heisst ein Netzausfall Stille.

    Warum Pocket-TTS und nicht Supertonic: Das Protokoll auf diesem Rechner
    verzeichnet fuer Supertonic vier Faelle "konnte den Text nicht
    sprechen" (zuletzt 31.08.2026, 08:54) und fuer Pocket-TTS keinen
    einzigen, bei einem Echtzeitfaktor von 0,3 bis 0,6 statt 0,7 bis 2,4.
    """

    d = _config()
    tts = d["voice"]["output"] if "voice" in d and "output" in d["voice"] else d.get("tts", {})
    engines = list(tts.get("engines", []))
    offline = list(tts.get("offline_engines", []))
    lokal = {"pocket_tts", "supertonic", "piper", "openvoice_clone", "kokoro", "sapi"}

    assert offline == ["pocket_tts"]
    assert set(offline) <= lokal, "im Offlinebetrieb darf keine Cloudstimme stehen"
    assert engines, "ohne Stimme bleibt der Orb stumm"
    assert engines[-1] in lokal, (
        "die letzte Instanz muss lokal sein, sonst ist ein Netzausfall Stille"
    )
    # Faellt die erste Stimme aus, muss die zweite ran duerfen.
    assert tts.get("allow_voice_fallback") is True


def test_ollama_schickt_keep_alive_mit(monkeypatch):
    """Die Einstellung muss auch wirklich in der Anfrage landen."""

    from backend.orchestrator.providers.ollama_provider import OllamaProvider
    from backend.orchestrator.providers.base_provider import ChatMessage

    provider = OllamaProvider({
        "model": "lfm2.5:8b",
        "keep_alive": "30m",
        "temperature": 0.25,
        "context_window": 10240,
    })

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
    assert gesehen["options"]["temperature"] == 0.25
    assert gesehen["options"]["num_ctx"] == 10240


def test_ollama_waermt_mit_einem_echten_kurzen_dialog_vor(monkeypatch):
    from backend.orchestrator.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider({
        "model": "lfm2.5:8b", "warmup_tokens": 8, "context_window": 10240
    })
    gesehen: dict = {}

    async def _fake(url, payload, *, versuche=3):
        gesehen.update(payload)
        return {"message": {"content": "Bereit"}}

    monkeypatch.setattr(provider, "_mit_ladegeduld", _fake)

    assert asyncio.run(provider.waermen()) is True
    assert len(gesehen["messages"]) == 2
    assert gesehen["options"]["num_predict"] == 8
    assert gesehen["options"]["num_ctx"] == 10240


def test_ollama_stream_is_async_and_forwards_the_speech_limit(monkeypatch):
    import json
    import httpx
    from backend.orchestrator.providers import ollama_provider as module
    from backend.orchestrator.providers.base_provider import ChatMessage

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode("utf-8")))
        body = (
            b'{"message":{"content":"Hallo "},"done":false}\n'
            b'{"message":{"content":"Welt."},"done":true}\n'
        )
        return httpx.Response(200, content=body)

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs.get("timeout"),
        )

    monkeypatch.setattr(module.httpx, "AsyncClient", client_factory)
    provider = module.OllamaProvider(
        {
            "model": "lfm2.5:8b",
            "timeout": 5,
            "first_token_timeout": 2,
            "context_window": 10240,
            "minimum_predict_tokens": 512,
        }
    )

    async def collect() -> list[str]:
        return [
            piece
            async for piece in provider.chat_stream(
                [ChatMessage(role="user", content="Hallo")], max_tokens=72
            )
        ]

    assert asyncio.run(collect()) == ["Hallo ", "Welt."]
    assert seen["options"]["num_predict"] == 512
    assert seen["options"]["num_ctx"] == 10240
    assert seen["keep_alive"]


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
