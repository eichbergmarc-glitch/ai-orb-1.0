"""Sprache von einem Gerät ohne eigenen Orb.

Am Rechner hört der Orb mit seinem eigenen Mikrofon zu. Ein iPad hat
sein eigenes, und der Mensch sitzt davor - nicht vor dem Rechner. Der
Ton muss also hin und die Antwort zurück.

Geprüft wird der Weg, nicht die Erkennung: dass Rohdaten unverändert
ankommen, dass eine zu große Aufnahme abgewiesen wird, bevor sie den
Arbeitsspeicher füllt, dass eine Tondatei als Ton herausgeht - und vor
allem, dass über den Ton-Endpunkt nichts anderes das Haus verlässt.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest

from backend.api.http_server import ApiRouter, LocalApiServer, SseBroker


@pytest.fixture()
def empfangen():
    """Sammelt, was beim Rohdaten-Endpunkt ankommt."""

    return []


@pytest.fixture()
def adresse(empfangen, tmp_path):
    ton = tmp_path / "ton.wav"
    ton.write_bytes(b"RIFF....WAVEfmt ")

    router = ApiRouter()

    def aufnahme(daten: bytes, kopfzeilen: dict[str, str]):
        empfangen.append((daten, kopfzeilen.get("Content-Type", "")))
        return {"frage": "Wie spät ist es?", "antwort": "Kurz nach zehn.", "ton": "ton.wav"}

    def herausgeben(params: dict):
        name = str(params.get("datei", ""))
        if not name or "/" in name or "\\" in name or ".." in name:
            return {"_status": 400, "_bytes": b"", "_type": "", "error": "ungueltig"}
        ziel = (tmp_path / name).resolve()
        if tmp_path not in ziel.parents or not ziel.is_file():
            return {"_status": 404, "_bytes": b"", "_type": "", "error": "unbekannt"}
        return {"_bytes": ziel.read_bytes(), "_type": "audio/wav", "_status": 200}

    router.post_raw("/stimme/aufnahme", aufnahme)
    router.get("/stimme/ton", herausgeben)

    server = LocalApiServer("127.0.0.1", 0, router, SseBroker())
    server.start()
    yield f"http://127.0.0.1:{server.port}"
    server.stop()


def _schicken(url: str, daten: bytes, typ: str = "audio/wav"):
    anfrage = urllib.request.Request(url, data=daten, headers={"Content-Type": typ})
    try:
        with urllib.request.urlopen(anfrage, timeout=5) as antwort:
            return antwort.status, antwort.read()
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read()


def _holen(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as antwort:
            return antwort.status, antwort.headers.get("Content-Type", ""), antwort.read()
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.headers.get("Content-Type", ""), fehler.read()


def test_aufnahme_kommt_unveraendert_an(adresse, empfangen):
    """Ton ist kein Text. Jedes Byte, das sich ändert, ist ein Knacken."""

    # Alle 256 Bytewerte - auch die, die in Text zu Unfug würden.
    ton = bytes(range(256)) * 8
    status, antwort = _schicken(f"{adresse}/stimme/aufnahme", ton)

    assert status == 200
    assert empfangen[0][0] == ton
    assert empfangen[0][1] == "audio/wav"
    assert json.loads(antwort)["frage"] == "Wie spät ist es?"


def test_leere_aufnahme_wird_abgewiesen(adresse):
    status, _ = _schicken(f"{adresse}/stimme/aufnahme", b"")
    assert status == 400


def test_zu_grosse_aufnahme_wird_abgewiesen_bevor_sie_gelesen_wird(adresse):
    """Ohne Grenze füllte eine einzige Anfrage den Arbeitsspeicher."""

    from backend.api.http_server import _RequestHandler

    zu_viel = b"x" * (_RequestHandler.ROHDATEN_GRENZE + 1)
    status, antwort = _schicken(f"{adresse}/stimme/aufnahme", zu_viel)
    assert status == 413
    assert json.loads(antwort)["error"] == "zu_gross"


def test_ton_geht_als_ton_hinaus(adresse):
    status, typ, inhalt = _holen(f"{adresse}/stimme/ton?datei=ton.wav")
    assert status == 200
    assert typ == "audio/wav"
    assert inhalt.startswith(b"RIFF")


@pytest.mark.parametrize(
    "datei",
    [
        "../../.env",
        "..\\..\\.env",
        "/etc/passwd",
        "unterordner/ton.wav",
        "",
    ],
)
def test_der_ton_endpunkt_ist_keine_leseluke(adresse, datei):
    """Er gibt Töne heraus - nicht, was immer der Fragende nennt."""

    status, _, inhalt = _holen(
        f"{adresse}/stimme/ton?datei={urllib.parse.quote(datei, safe='')}"
    )
    assert status in (400, 404)
    assert b"RIFF" not in inhalt


def test_unbekannte_tondatei_ist_kein_fehler_sondern_ein_nein(adresse):
    status, _, _ = _holen(f"{adresse}/stimme/ton?datei=gibtesnicht.wav")
    assert status == 404


# --- Teilstücke, wie Safari sie verlangt --------------------------------
#
# Safari auf iPhone und iPad spielt Ton nur ab, wenn der Server
# Teilstücke beherrscht. Es fragt zuerst mit `Range: bytes=0-1` nach und
# spielt gar nicht erst, wenn darauf die ganze Datei kommt - lautlos,
# ohne Fehler. Diese Tests halten fest, dass der Orb richtig antwortet.


@pytest.fixture()
def tonserver():
    """Ein Endpunkt, der eine kleine Tondatei herausgibt."""

    daten = bytes(range(256)) * 4  # 1024 Bytes, jedes anders

    router = ApiRouter()
    router.get("/ton", lambda _: {"_bytes": daten, "_type": "audio/wav", "_status": 200})

    server = LocalApiServer("127.0.0.1", 0, router, SseBroker())
    server.start()
    yield f"http://127.0.0.1:{server.port}", daten
    server.stop()


def _mit_bereich(url: str, bereich: str | None):
    kopf = {"Range": bereich} if bereich else {}
    anfrage = urllib.request.Request(url, headers=kopf)
    try:
        with urllib.request.urlopen(anfrage, timeout=5) as antwort:
            return antwort.status, dict(antwort.headers), antwort.read()
    except urllib.error.HTTPError as fehler:
        return fehler.code, dict(fehler.headers), fehler.read()


def test_ohne_bereich_kommt_alles_und_die_einladung(tonserver):
    """`Accept-Ranges` ist die Einladung - ohne sie fragt Safari nicht."""

    adresse, daten = tonserver
    status, kopf, inhalt = _mit_bereich(f"{adresse}/ton", None)
    assert status == 200
    assert kopf.get("Accept-Ranges") == "bytes"
    assert inhalt == daten


def test_die_erste_frage_von_safari(tonserver):
    """Genau diese zwei Bytes fragt Safari zuerst ab."""

    adresse, daten = tonserver
    status, kopf, inhalt = _mit_bereich(f"{adresse}/ton", "bytes=0-1")
    assert status == 206
    assert kopf.get("Content-Range") == f"bytes 0-1/{len(daten)}"
    assert inhalt == daten[0:2]


def test_ein_stueck_aus_der_mitte(tonserver):
    adresse, daten = tonserver
    status, kopf, inhalt = _mit_bereich(f"{adresse}/ton", "bytes=100-199")
    assert status == 206
    assert inhalt == daten[100:200]
    assert kopf.get("Content-Length") == "100"


def test_offenes_ende_geht_bis_zum_schluss(tonserver):
    adresse, daten = tonserver
    status, kopf, inhalt = _mit_bereich(f"{adresse}/ton", "bytes=1000-")
    assert status == 206
    assert inhalt == daten[1000:]
    assert kopf.get("Content-Range") == f"bytes 1000-{len(daten) - 1}/{len(daten)}"


def test_die_letzten_bytes(tonserver):
    adresse, daten = tonserver
    status, _, inhalt = _mit_bereich(f"{adresse}/ton", "bytes=-50")
    assert status == 206
    assert inhalt == daten[-50:]


@pytest.mark.parametrize(
    "bereich",
    ["bytes=abc-def", "bytes=99999-", "bytes=200-100", "haeppchen=0-10", "bytes=-0"],
)
def test_unsinnige_angaben_liefern_die_ganze_datei(tonserver, bereich):
    """Nicht verstanden heißt: alles schicken. Das ist erlaubt und
    besser, als mit einem Fehler zu antworten, den niemand erwartet."""

    adresse, daten = tonserver
    status, _, inhalt = _mit_bereich(f"{adresse}/ton", bereich)
    assert status == 200
    assert inhalt == daten


# --- Sprechstücke -------------------------------------------------------
#
# Die Stimme braucht ungefähr so lange wie das Gesagte dauert. Wer erst
# die vollständige Antwort erzeugt und dann abspielt, wartet die gesamte
# Sprechdauer, *bevor* das erste Wort kommt. Deshalb kommt die Antwort in
# Stücken - und deshalb muss der Server drei Lagen unterscheiden können:
# „da", „kommt gleich" und „gibt es nicht". Wer „kommt gleich" mit „gibt
# es nicht" verwechselt, bricht das Vorlesen mitten im Satz ab.


@pytest.fixture()
def kern():
    """Ein Runtime-Gerippe - nur mit dem, was `sprechstueck` anfasst."""

    from collections import OrderedDict

    from backend.runtime import Runtime

    leer = Runtime.__new__(Runtime)
    leer._sprechauftraege = OrderedDict()  # noqa: SLF001 - bewusst gesetzt
    # `sprechstueck` stößt das nächste Stück an; hier wird nur vermerkt,
    # welches - erzeugt wird im Test nichts.
    leer.angestossen = []
    leer._stueck_anstossen = lambda auftrag, nummer: leer.angestossen.append(nummer)
    return leer


def test_fertiges_stueck_wird_genannt(kern):
    kern._sprechauftraege["a"] = {
        "teile": ["eins", "zwei"],
        "dateien": {0: "erstes.wav"},
        "fehler": {},
        "laeuft": set(),
        "abgebrochen": False,
    }
    assert kern.sprechstueck("a", 0) == ("da", "erstes.wav")


def test_noch_nicht_fertiges_stueck_heisst_kommt(kern):
    """Nicht „weg" - sonst hörte die Antwort nach dem ersten Satz auf."""

    kern._sprechauftraege["a"] = {
        "teile": ["eins", "zwei"],
        "dateien": {0: "erstes.wav"},
        "fehler": {},
        "laeuft": set(),
        "abgebrochen": False,
    }
    assert kern.sprechstueck("a", 1) == ("kommt", "")


def test_gescheitertes_stueck_wird_nicht_ewig_erwartet(kern):
    """Sonst wartete das iPad zweieinhalb Minuten auf nichts."""

    kern._sprechauftraege["a"] = {
        "teile": ["eins"],
        "dateien": {},
        "fehler": {0: "Stimme nicht verfügbar"},
        "laeuft": set(),
        "abgebrochen": False,
    }
    zustand, grund = kern.sprechstueck("a", 0)
    assert zustand == "nichts"
    assert "verfügbar" in grund


@pytest.mark.parametrize("nummer", [-1, 2, 99])
def test_stueck_ausserhalb_der_antwort(kern, nummer):
    kern._sprechauftraege["a"] = {
        "teile": ["eins", "zwei"],
        "dateien": {},
        "fehler": {},
        "laeuft": set(),
        "abgebrochen": False,
    }
    assert kern.sprechstueck("a", nummer) == ("weg", "")


def test_unbekannter_auftrag(kern):
    assert kern.sprechstueck("gibtesnicht", 0) == ("weg", "")


def test_abholen_stoesst_das_naechste_stueck_an(kern):
    """Ein Stück Vorsprung genügt - alles darüber ist Arbeit, die
    niemandem nützt und der nächsten Frage im Weg steht."""

    kern._sprechauftraege["a"] = {
        "teile": ["eins", "zwei", "drei"],
        "dateien": {0: "erstes.wav"},
        "fehler": {},
        "laeuft": set(),
        "abgebrochen": False,
    }

    assert kern.sprechstueck("a", 0) == ("da", "erstes.wav")
    assert kern.angestossen == [1]
    # Nicht auch noch 2 - das entsteht erst, wenn 1 abgeholt wird.
    assert 2 not in kern.angestossen


def test_fehlendes_stueck_wird_beim_fragen_angestossen(kern):
    kern._sprechauftraege["a"] = {
        "teile": ["eins", "zwei"],
        "dateien": {},
        "fehler": {},
        "laeuft": set(),
        "abgebrochen": False,
    }

    assert kern.sprechstueck("a", 0) == ("kommt", "")
    assert kern.angestossen == [0]


def test_abgebrochener_auftrag_gibt_nichts_mehr_heraus(kern):
    """Wer eine neue Frage stellt, hat die alte Antwort abgehakt."""

    kern._sprechauftraege["a"] = {
        "teile": ["eins", "zwei"],
        "dateien": {0: "erstes.wav"},
        "fehler": {},
        "laeuft": set(),
        "abgebrochen": True,
    }

    assert kern.sprechstueck("a", 0) == ("weg", "")
    assert kern.angestossen == []


def test_neue_frage_bricht_die_alte_antwort_ab(kern):
    from collections import OrderedDict

    kern._sprechauftraege = OrderedDict({
        "alt": {"teile": ["x"], "dateien": {}, "fehler": {}, "laeuft": set(),
                "abgebrochen": False},
    })
    kern._alte_auftraege_abbrechen()
    assert kern._sprechauftraege["alt"]["abgebrochen"] is True


# --- Der Faden, in dem gefragt wird ------------------------------------
#
# Der HTTP-Server bearbeitet jede Anfrage in einem eigenen Faden. Dort
# gibt es keine laufende Ereignisschleife. Wer von dort aus Arbeit für
# den Kern anstößt, muss sie ausdrücklich auf dessen Schleife legen -
# sonst scheitert es mit "There is no current event loop in thread", und
# zwar erst im Betrieb, nicht beim Import.
#
# Genau das ist am 27.08. passiert: Der Orb verstummte vollständig, weil
# jede Anfrage nach einem Sprechstück eine Ausnahme warf. Dieser Test
# hält den Weg offen.


@pytest.fixture()
def kern_mit_schleife():
    """Ein Runtime-Gerippe mit echter Ereignisschleife in eigenem Faden."""

    import asyncio
    import threading
    from collections import OrderedDict
    from pathlib import Path as _Path
    from types import SimpleNamespace

    from backend.runtime import Runtime

    schleife = asyncio.new_event_loop()
    faden = threading.Thread(target=schleife.run_forever, daemon=True)
    faden.start()

    gesprochen: list[str] = []

    async def falsches_speak(text, emotion=""):
        gesprochen.append(text)
        return SimpleNamespace(
            succeeded=True,
            audio_path=_Path(f"stueck-{len(gesprochen)}.wav"),
            error="",
        )

    leer = Runtime.__new__(Runtime)
    leer._sprechauftraege = OrderedDict()  # noqa: SLF001
    leer._loop = schleife  # noqa: SLF001
    leer.voice = SimpleNamespace(tts=SimpleNamespace(speak=falsches_speak))

    yield leer, gesprochen

    schleife.call_soon_threadsafe(schleife.stop)
    faden.join(timeout=2)


def test_stueck_anfordern_aus_fremdem_faden(kern_mit_schleife):
    """So fragt der HTTP-Server - und so darf es nicht scheitern."""

    import threading
    import time

    kern, gesprochen = kern_mit_schleife
    kern._sprechauftraege["a"] = {
        "teile": ["Erster Satz.", "Zweiter Satz."],
        "dateien": {},
        "fehler": {},
        "laeuft": set(),
        "abgebrochen": False,
    }

    ergebnis: list = []

    def fragen():
        # Ein anderer Faden als der der Schleife - genau wie im Server.
        ergebnis.append(kern.sprechstueck("a", 0))

    faden = threading.Thread(target=fragen)
    faden.start()
    faden.join(timeout=5)

    assert ergebnis == [("kommt", "")], "Die Anfrage selbst darf nicht scheitern."

    # Und das Stück muss tatsächlich entstehen.
    for _ in range(50):
        if kern._sprechauftraege["a"]["dateien"]:
            break
        time.sleep(0.05)

    assert gesprochen == ["Erster Satz."]
    assert kern._sprechauftraege["a"]["dateien"][0] == "stueck-1.wav"
    assert kern._sprechauftraege["a"]["laeuft"] == set()


def test_ohne_schleife_wird_nichts_angestossen():
    """Beim Herunterfahren darf das keine Ausnahme werfen."""

    from collections import OrderedDict

    from backend.runtime import Runtime

    leer = Runtime.__new__(Runtime)
    leer._sprechauftraege = OrderedDict({
        "a": {"teile": ["x"], "dateien": {}, "fehler": {}, "laeuft": set(),
              "abgebrochen": False},
    })
    leer._loop = None

    assert leer.sprechstueck("a", 0) == ("kommt", "")


# --- Bedienbefehle ------------------------------------------------------
#
# „Chat aktivieren" ist keine Frage. Sie erst an das Modell zu geben wäre
# eine Denkpause für etwas, das sofort wirken soll - und das Modell
# könnte sie auch missverstehen.


@pytest.mark.parametrize(
    "gesagt",
    [
        "Chat aktivieren",
        "chat aktivieren",
        "Chat aktivieren.",
        "  Chat   aktivieren  ",
        "Chatfenster aktivieren",
        "Chat öffnen",
        "Chat oeffnen",
        "zeig mir den chat",
    ],
)
def test_chat_wird_geoeffnet(gesagt):
    from backend.runtime import Runtime

    assert Runtime._befehl_erkennen(gesagt) == "chat_auf"


@pytest.mark.parametrize(
    "gesagt",
    ["Chat schließen", "chat schliessen", "Chat zu.", "Chat ausblenden"],
)
def test_chat_wird_geschlossen(gesagt):
    from backend.runtime import Runtime

    assert Runtime._befehl_erkennen(gesagt) == "chat_zu"


@pytest.mark.parametrize(
    "gesagt",
    [
        "Was steht im Chat?",
        "Erklär mir, wie ich den Chat aktivieren kann",
        "Chat",
        "",
        "Halte mir eine Vorlesung über Chatbots",
    ],
)
def test_keine_befehle(gesagt):
    """Nur der genaue Wortlaut zählt. Sonst würde jede Frage, in der das
    Wort vorkommt, ungefragt Fenster verschieben."""

    from backend.runtime import Runtime

    assert Runtime._befehl_erkennen(gesagt) == ""


def test_lange_antworten_werden_nicht_mehr_gekuerzt():
    """Wer eine Vorlesung hören will, soll eine Vorlesung hören.

    Die Kürzung war eine Notbremse gegen Wartezeit, als die gesamte
    Antwort entstand, bevor das erste Wort kam. Seit die Stücke einzeln
    und auf Abruf entstehen, gibt es diesen Grund nicht mehr.
    """

    from backend.runtime import Runtime

    lang = ("Ein Satz über den neuen Realismus. " * 120).strip()
    assert len(lang) > 3000

    text, gekuerzt = Runtime._fuers_sprechen(lang, Runtime.SPRECH_GRENZE)
    assert gekuerzt is False
    assert text == lang
