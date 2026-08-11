"""Tests des vorgewaermten Claude-Code-Prozesses.

Die Antwortzeit war zu lang, und der groesste einzelne Posten war reine
Anlaufzeit: Fuer jede Frage wurde die Claude-Code-Befehlszeile neu
gestartet, was unter Windows mehrere Sekunden kostet - bevor auch nur ein
Wort gedacht war.

Geprueft wird hier gegen eine nachgebaute Befehlszeile, also ohne Netz und
ohne Anmeldung: dass ein Prozess wirklich im Voraus bereitsteht, dass die
Antwort stueckweise ankommt (sonst kann der Orb nicht frueh zu sprechen
anfangen), dass nach jeder Antwort ein frischer Prozess nachrueckt - und
dass der alte Weg uebrig bleibt, wenn das Vorwaermen scheitert.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path

from backend.orchestrator.providers.base_provider import ChatMessage, ProviderError
from backend.orchestrator.providers.claude_code_provider import ClaudeCodeProvider

# Eine nachgebaute Befehlszeile: Sie spricht dasselbe Protokoll wie Claude
# Code, antwortet aber nur mit dem, was sie gefragt wurde - rueckwaerts
# gelesen waere zu albern, also einfach mit einer festen Bestaetigung plus
# der Frage. So laesst sich pruefen, dass die Frage wirklich ankommt.
_FAKE = '''#!{python}
import json, sys

def raus(daten):
    sys.stdout.write(json.dumps(daten) + "\\n")
    sys.stdout.flush()

if "--help" in sys.argv:
    # Der Provider fragt zuerst nach, welche Schalter es ueberhaupt gibt -
    # sonst wuerde ein unbekannter Schalter den Start verweigern.
    print("""Usage: claude [options]
  -p, --print
  --input-format <format>
  --output-format <format>
  --verbose
  --include-partial-messages
  --model <model>
  --tools <tools...>
  --allowedTools <tools...>
  --effort <level>
  --strict-mcp-config
  --mcp-config <configs...>
  --setting-sources <sources>
  --disable-slash-commands
  --no-session-persistence
""")
    sys.exit(0)

if "--input-format" not in sys.argv:
    # Der alte Weg: eine Frage als Argument, eine JSON-Antwort.
    frage = sys.argv[sys.argv.index("-p") + 1]
    raus({{"type": "result", "result": "einzeln: " + frage.splitlines()[-1]}})
    sys.exit(0)

for zeile in sys.stdin:
    zeile = zeile.strip()
    if not zeile:
        continue
    daten = json.loads(zeile)
    frage = daten["message"]["content"][0]["text"].splitlines()[-1]
    for stueck in ["warm: ", frage]:
        raus({{"type": "stream_event",
               "event": {{"type": "content_block_delta",
                         "delta": {{"type": "text_delta", "text": stueck}}}}}})
    raus({{"type": "result", "result": "warm: " + frage}})
'''


def _falsche_befehlszeile(ordner: Path) -> str:
    pfad = ordner / "claude-nachbau.py"
    pfad.write_text(_FAKE.format(python=sys.executable), encoding="utf-8")
    pfad.chmod(pfad.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(pfad)


def _provider(tmp_path: Path, **extra) -> ClaudeCodeProvider:
    einstellungen = {
        "executable": _falsche_befehlszeile(tmp_path),
        "model": "",
        "timeout": 30,
        **extra,
    }
    anbieter = ClaudeCodeProvider(einstellungen)
    anbieter._workdir = tmp_path
    return anbieter


def _frage(text: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text)]


def test_vorgewaermter_prozess_steht_vor_der_frage_bereit(tmp_path: Path):
    """Genau das ist der Punkt: Der Prozess laeuft, bevor gefragt wird."""

    anbieter = _provider(tmp_path)

    async def ablauf():
        assert await anbieter.prewarm() is True
        assert anbieter._warm is not None, "es steht kein Prozess bereit"
        assert anbieter._warm.returncode is None, "der bereitstehende Prozess ist tot"
        await anbieter.shutdown()

    asyncio.run(ablauf())


def test_antwort_kommt_ueber_den_warmen_weg(tmp_path: Path):
    anbieter = _provider(tmp_path)

    async def ablauf():
        await anbieter.prewarm()
        antwort = await anbieter.chat(_frage("Wie spaet ist es?"))
        await anbieter.shutdown()
        return antwort

    antwort = asyncio.run(ablauf())
    assert antwort.text == "warm: Wie spaet ist es?"
    assert antwort.raw.get("warm") is True


def test_derselbe_prozess_traegt_das_ganze_gespraech(tmp_path: Path):
    """Der Prozess bleibt - das spart nicht nur den Start.

    Er kennt den bisherigen Verlauf dann schon und muss ihn nicht erneut
    durchdenken. Gemessen war genau das der Unterschied zwischen "erstes
    Wort nach vier Sekunden" und "nach anderthalb".
    """

    anbieter = _provider(tmp_path)

    async def ablauf():
        await anbieter.prewarm()
        erster = anbieter._warm
        eins = await anbieter.chat([ChatMessage(role="user", content="Eins")])
        zwei = await anbieter.chat(
            [
                ChatMessage(role="user", content="Eins"),
                ChatMessage(role="assistant", content="warm: Eins"),
                ChatMessage(role="user", content="Zwei"),
            ]
        )
        danach = anbieter._warm
        await anbieter.shutdown()
        return erster, danach, eins, zwei

    erster, danach, eins, zwei = asyncio.run(ablauf())
    assert danach is erster, "der Prozess wurde ohne Not ausgetauscht"
    assert eins.text == "warm: Eins"
    # Nur das Neue wurde geschickt - nicht der ganze Verlauf noch einmal.
    assert zwei.text == "warm: Zwei"


def test_geaenderter_verlauf_beginnt_von_vorn(tmp_path: Path):
    """Wurde der Verlauf verdichtet oder geleert, muss ein frischer her.

    Sonst spraeche der Orb aus einer Vergangenheit, die es nicht mehr gibt.
    """

    anbieter = _provider(tmp_path)

    async def ablauf():
        await anbieter.prewarm()
        await anbieter.chat([ChatMessage(role="user", content="Eins")])
        erster = anbieter._warm
        # Ein Verlauf, der NICHT mit dem bisherigen beginnt.
        await anbieter.chat([ChatMessage(role="user", content="Ganz was anderes")])
        danach = anbieter._warm
        await anbieter.shutdown()
        return erster, danach

    erster, danach = asyncio.run(ablauf())
    assert danach is not erster, "der Prozess redete aus einem alten Verlauf weiter"


def test_nach_vielen_runden_wird_abgeloest(tmp_path: Path):
    """Irgendwann ist der mitgefuehrte Verlauf laenger als noetig."""

    anbieter = _provider(tmp_path, max_turns=2)

    async def ablauf():
        await anbieter.prewarm()
        erster = anbieter._warm
        verlauf: list[ChatMessage] = []
        for nummer in ("Eins", "Zwei"):
            verlauf.append(ChatMessage(role="user", content=nummer))
            await anbieter.chat(list(verlauf))
            verlauf.append(ChatMessage(role="assistant", content=f"warm: {nummer}"))
        # Die Abloesung laeuft im Hintergrund - ihr kurz Zeit geben.
        for _ in range(150):
            if anbieter._warm is not None and anbieter._warm is not erster:
                break
            await asyncio.sleep(0.02)
        danach = anbieter._warm
        await anbieter.shutdown()
        return erster, danach

    erster, danach = asyncio.run(ablauf())
    assert danach is not None, "es steht kein Prozess mehr bereit"
    assert danach is not erster, "der erschoepfte Prozess wurde nicht abgeloest"


def test_die_antwort_kommt_stueckweise(tmp_path: Path):
    """Ohne Stuecke kann der Orb nicht anfangen zu sprechen, bevor er fertig
    gedacht hat - und genau das war die gefuehlte Wartezeit."""

    anbieter = _provider(tmp_path)

    async def ablauf():
        await anbieter.prewarm()
        stuecke = [s async for s in anbieter.chat_stream(_frage("Hallo Welt"))]
        await anbieter.shutdown()
        return stuecke

    stuecke = asyncio.run(ablauf())
    assert len(stuecke) > 1, f"die Antwort kam in einem Stueck: {stuecke}"
    assert "".join(stuecke) == "warm: Hallo Welt"


def test_ohne_warmen_weg_bleibt_der_alte(tmp_path: Path):
    """Vorwaermen ist eine Beschleunigung, keine Voraussetzung."""

    anbieter = _provider(tmp_path, warm_process=False)

    async def ablauf():
        return await anbieter.chat(_frage("Ohne Vorwaermen"))

    antwort = asyncio.run(ablauf())
    assert antwort.text == "einzeln: Ohne Vorwaermen"


def test_gescheitertes_vorwaermen_faellt_zurueck(tmp_path: Path):
    """Laesst sich kein Prozess halten, wird eben wieder einzeln gestartet."""

    anbieter = _provider(tmp_path)

    async def ablauf():
        anbieter._warm_broken = True  # so, als waere der Start gescheitert
        return await anbieter.chat(_frage("Trotzdem"))

    antwort = asyncio.run(ablauf())
    assert antwort.text == "einzeln: Trotzdem"


def test_ohne_befehlszeile_gibt_es_keinen_warmen_prozess(tmp_path: Path):
    """Ist nichts zu finden, wird auch nichts gestartet - und nichts haengt."""

    anbieter = _provider(tmp_path)
    # So, als waere auf diesem Rechner keine Befehlszeile auffindbar.
    anbieter._find_executable = lambda: None  # type: ignore[method-assign]

    async def ablauf():
        bereit = await anbieter.prewarm()
        try:
            await anbieter.chat(_frage("Hallo"))
        except ProviderError as fehler:
            return bereit, str(fehler)
        return bereit, ""

    bereit, meldung = asyncio.run(ablauf())
    assert bereit is False
    assert "nicht gefunden" in meldung


def test_die_schlanken_schalter_sind_gesetzt(tmp_path: Path):
    """Fremde MCP-Server und Einstellungsdateien kosten Sekunden beim Start."""

    anbieter = _provider(tmp_path)

    async def ablauf():
        await anbieter._supported_flags(anbieter._find_executable() or "")
        return anbieter._stream_arguments("claude")

    argumente = asyncio.run(ablauf())

    for schalter in (
        "--strict-mcp-config",
        "--setting-sources",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--include-partial-messages",
    ):
        assert schalter in argumente, f"{schalter} fehlt"

    assert argumente[argumente.index("--tools") + 1] == "Read"
    assert argumente[argumente.index("--effort") + 1] == "low"


def test_umgebung_ohne_api_schluessel(tmp_path: Path):
    """Ein gesetzter Schluessel wuerde ueber die API abrechnen statt ueber das Abo."""

    anbieter = _provider(tmp_path)
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    try:
        umgebung = anbieter._build_environment()
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)

    assert "ANTHROPIC_API_KEY" not in umgebung


# Eine aeltere Befehlszeile: Sie kennt die Beschleunigungsschalter nicht und
# verweigert den Start, wenn einer davon auftaucht - genau wie das Original.
_ALT = '''#!{python}
import json, sys

BEKANNT = {{"-p", "--output-format", "--model", "--help"}}

if "--help" in sys.argv:
    print("Usage: claude [options]\\\\n  -p, --print\\\\n  --output-format <format>\\\\n  --model <model>")
    sys.exit(0)

for eintrag in sys.argv[1:]:
    if eintrag.startswith("--") and eintrag not in BEKANNT:
        sys.stderr.write("error: unknown option '" + eintrag + "'\\\\n")
        sys.exit(1)

frage = sys.argv[sys.argv.index("-p") + 1]
print(json.dumps({{"type": "result", "result": "alt: " + frage.splitlines()[-1]}}))
'''


def test_aeltere_befehlszeile_wird_langsamer_statt_kaputt(tmp_path: Path):
    """Der wichtigste Test dieser Datei.

    Die Beschleunigungsschalter gibt es erst ab neueren Fassungen von Claude
    Code. Auf einer aelteren wuerde ein unbekannter Schalter nicht etwa
    uebergangen, sondern den Start verweigern - und dann bekaeme der Benutzer
    auf JEDE Frage einen Fehler statt einer Antwort. Ein langsamer Orb ist
    aergerlich, ein stummer unbrauchbar.
    """

    pfad = tmp_path / "claude-alt.py"
    pfad.write_text(_ALT.format(python=sys.executable), encoding="utf-8")
    pfad.chmod(pfad.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    anbieter = ClaudeCodeProvider({"executable": str(pfad), "model": "", "timeout": 30})
    anbieter._workdir = tmp_path

    async def ablauf():
        bereit = await anbieter.prewarm()
        antwort = await anbieter.chat(_frage("Geht es trotzdem?"))
        await anbieter.shutdown()
        return bereit, antwort

    bereit, antwort = asyncio.run(ablauf())
    assert bereit is False, "auf einer alten Fassung darf nichts vorgewaermt werden"
    assert antwort.text == "alt: Geht es trotzdem?"


# --- Wenn der wartende Prozess versagt -----------------------------------------


def test_ein_haengender_prozess_verhindert_keine_antwort(tmp_path: Path):
    """Der wichtigste Test dieser Datei.

    Blieb der wartende Prozess haengen oder starb er still, scheiterte damit
    JEDE Anfrage - und zwar erst nach dem Zeitlimit. Der Orb schwieg
    minutenlang und antwortete dann gar nicht. Ein Beschleuniger, der beim
    Versagen alles mitreisst, ist keiner.
    """

    anbieter = _provider(tmp_path)

    async def ablauf():
        await anbieter.prewarm()

        # Der wartende Prozess bricht bei der Frage weg.
        async def _kaputt(prompt):
            raise ProviderError("claude_code: der Prozess hat sich beendet.")
            yield ("ende", "")  # pragma: no cover

        anbieter._stream_from_warm = _kaputt  # type: ignore[method-assign]
        antwort = await anbieter.chat(_frage("Trotzdem eine Antwort?"))
        await anbieter.shutdown()
        return antwort

    antwort = asyncio.run(ablauf())
    assert antwort.text == "einzeln: Trotzdem eine Antwort?", (
        "der Ausfall des warmen Wegs hat die Antwort verhindert"
    )


def test_nach_dem_ausfall_wird_der_prozess_verabschiedet(tmp_path: Path):
    """Ein kaputter Prozess darf nicht fuer die naechste Frage stehenbleiben."""

    anbieter = _provider(tmp_path)

    async def ablauf():
        await anbieter.prewarm()

        async def _kaputt(prompt):
            raise ProviderError("kaputt")
            yield ("ende", "")  # pragma: no cover

        anbieter._stream_from_warm = _kaputt  # type: ignore[method-assign]
        await anbieter.chat(_frage("Eins"))
        danach = anbieter._warm
        await anbieter.shutdown()
        return danach

    assert asyncio.run(ablauf()) is None


def test_das_warme_zeitlimit_ist_kuerzer_als_das_grosse(tmp_path: Path):
    """Drei Minuten zu warten hiesse, den Benutzer fuer einen Fehler buessen
    zu lassen, der nach einer Minute feststand."""

    anbieter = _provider(tmp_path, timeout=180)
    assert anbieter._warm_timeout < anbieter._timeout
