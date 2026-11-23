"""Sunrise TV im Browser (22.11.2026).

Sunrise bietet keine oeffentliche Schnittstelle. Die Web-App
(www.sunrisetv.ch, eine Flutter-Anwendung ohne einzeln aufrufbare
Seitenadressen) laeuft aber im normalen Browser, angemeldet mit Marcs
Sunrise-Konto. Das Werkzeug oeffnet sie dort; Sender und Sendung waehlt
Marc in der App. Was er schauen will, merkt sich Synapse als Filmgeschmack
in der Wissensbibliothek - daraus macht sie spaeter Vorschlaege.
"""

from __future__ import annotations

import asyncio
import webbrowser
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

SUNRISE_TV = "https://www.sunrisetv.ch/de/home"


class SunriseTvTool(Tool):
    name = "sunrise_tv"
    description = (
        "Oeffnet Sunrise TV (Marcs Fernsehen) im Browser am PC: Live-TV, "
        "Replay der letzten 7 Tage, Aufnahmen. Benutze das bei 'oeffne "
        "Sunrise TV', 'ich will fernsehen', 'mach SRF 1 an', 'zeig mir den "
        "Film ...'. Nenne in 'sendung' den gewuenschten Sender, Film oder die "
        "Serie - Synapse merkt sich das als Filmgeschmack fuer spaetere "
        "Vorschlaege. Den Sender waehlt Marc in der App selbst; sag ihm das "
        "kurz. Fuer 'was laeuft heute' nutze die Internetsuche."
    )
    permission = "launch_application"
    parameters = (
        ToolParameter("sendung", "string", "Sender, Film oder Serie (optional).", required=False, default=""),
    )

    def __init__(self, desktop: Any | None = None) -> None:
        super().__init__()
        self._desktop = desktop

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sendung = " ".join(str(arguments.get("sendung") or "").split())[:120]
        geoeffnet = False
        if self._desktop is not None and hasattr(self._desktop, "open_url"):
            try:
                ergebnis = self._desktop.open_url(SUNRISE_TV)
                if asyncio.iscoroutine(ergebnis):
                    ergebnis = await ergebnis
                geoeffnet = bool(getattr(ergebnis, "success", ergebnis))
            except Exception:  # noqa: BLE001
                geoeffnet = False
        if not geoeffnet:
            geoeffnet = bool(webbrowser.open(SUNRISE_TV, new=2))
        if not geoeffnet:
            return ToolResult.failure("Der Browser liess sich nicht oeffnen.")
        if sendung:
            try:
                from backend.knowledge.wissensbibliothek import bibliothek

                bibliothek().merke(f"Marc wollte schauen: {sendung}",
                                   f"Marc wollte auf Sunrise TV schauen: {sendung}.",
                                   quelle=f"sunrise-tv:{sendung.lower()}", art="filmgeschmack")
            except Exception:  # noqa: BLE001 - Merken ist Zugabe
                logger.debug("Filmgeschmack nicht gemerkt.", exc_info=True)
        text = "Sunrise TV ist im Browser geoeffnet."
        if sendung:
            text += f" Waehle dort '{sendung}' aus - ich habe mir gemerkt, dass du das sehen wolltest."
        text += " Beim ersten Mal musst du dich dort mit deinem Sunrise-Konto anmelden."
        return ToolResult.success(text, url=SUNRISE_TV)


class FilmVorschlagTool(Tool):
    name = "film_vorschlaege"
    description = (
        "Nennt, was Marc zuletzt auf Sunrise TV schauen wollte (sein "
        "Filmgeschmack), damit du passende Filme oder Serien vorschlagen "
        "kannst. Benutze das bei 'was soll ich schauen', 'schlag mir einen "
        "Film vor'."
    )
    permission = "read_files"
    parameters = ()

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.knowledge.wissensbibliothek import bibliothek

        def lesen() -> list[str]:
            bib = bibliothek()
            with bib._lock:  # noqa: SLF001
                con = bib._eigenes()  # noqa: SLF001
                if con is None:
                    return []
                return [str(r[0]) for r in con.execute(
                    "SELECT titel FROM wissen WHERE art = 'filmgeschmack' ORDER BY rowid DESC LIMIT 25")]

        eintraege = await asyncio.to_thread(lesen)
        if not eintraege:
            return ToolResult.success(
                "Noch nichts gemerkt. Frag Marc, was er gern schaut, und schlage dann vor.")
        return ToolResult.success(
            "Zuletzt wollte Marc schauen:\n" + "\n".join(f"- {e.split(': ',1)[-1]}" for e in eintraege)
            + "\nSchlage dazu Passendes vor (aehnliche Filme, Serien, Genres).")


# --- TV-Programm, Vorschlaege, Aufnahmen (22.11.2026) ------------------------

class TvProgrammTool(Tool):
    name = "tv_programm"
    description = (
        "Zeigt das Fernsehprogramm (rund 240 Sender, Schweizer Programm, eine "
        "Woche im Voraus): was jetzt/heute Abend/morgen/um 20:15 laeuft, auf "
        "einem Sender, oder wann eine Sendung kommt. 'wann': jetzt, heute, "
        "heute abend, morgen abend, 20:15, 24.11. 20:00. 'sender': z. B. "
        "'SRF 1' oder 'SRF zwei, 3+' (leer = die grossen Sender). 'suche': "
        "Titel einer Sendung. 'art': film, serie, doku, krimi, sport, "
        "nachrichten, show, kinder. Nenne die Zeiten so, wie sie geliefert "
        "werden; erfinde nichts dazu."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("wann", "string", "Zeitpunkt oder Zeitraum.", required=False, default="jetzt"),
        ToolParameter("sender", "string", "Sender (optional).", required=False, default=""),
        ToolParameter("suche", "string", "Titel einer Sendung (optional).", required=False, default=""),
        ToolParameter("art", "string", "Art der Sendung (optional).", required=False, default=""),
        ToolParameter("anzahl", "integer", "Hoechstens so viele Eintraege.", required=False, default=15),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.integrations import tvprogramm as tv

        try:
            anzahl = int(arguments.get("anzahl") or 15)
        except (TypeError, ValueError):
            anzahl = 15
        try:
            treffer, wann_text = await asyncio.to_thread(
                tv.suchen, sender=str(arguments.get("sender") or ""),
                wann=str(arguments.get("wann") or "jetzt"), suche=str(arguments.get("suche") or ""),
                art=str(arguments.get("art") or ""), anzahl=anzahl,
            )
        except Exception as fehler:  # noqa: BLE001
            logger.exception("TV-Programm nicht lesbar.")
            return ToolResult.failure(f"Das Fernsehprogramm ist gerade nicht abrufbar: {fehler}")
        if not treffer:
            return ToolResult.success(f"Dazu habe ich im Programm ({wann_text}) nichts gefunden.")
        kopf = f"Fernsehprogramm {wann_text}:" if not arguments.get("suche") else "Sendetermine:"
        return ToolResult.success(kopf + "\n" + "\n".join(f"- {tv.zeile(s)}" for s in treffer))


class TvVorschlaegeTool(Tool):
    name = "tv_vorschlaege"
    description = (
        "Fuer 'was soll ich heute schauen', 'schlag mir einen Film vor': holt "
        "die Filme, Serien und Dokus im Programm (Standard: heute Abend) und "
        "was Marc bisher gern sehen wollte. Waehle daraus 2 bis 3 passende "
        "Sendungen aus und begruende kurz - mit Sender und Uhrzeit."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("wann", "string", "Zeitraum.", required=False, default="heute abend"),
        ToolParameter("art", "string", "film, serie, doku ... (optional).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.integrations import tvprogramm as tv

        wann = str(arguments.get("wann") or "heute abend")
        arten = [str(arguments.get("art"))] if arguments.get("art") else ["film", "serie", "doku"]
        zeilen: list[str] = []
        try:
            for art in arten:
                treffer, wann_text = await asyncio.to_thread(tv.suchen, wann=wann, art=art, anzahl=14)
                if treffer:
                    zeilen.append(f"{art.capitalize()}e {wann_text}:")
                    zeilen += [f"- {tv.zeile(s, mit_text=True)}" for s in treffer]
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Das Fernsehprogramm ist gerade nicht abrufbar: {fehler}")
        geschmack = (await FilmVorschlagTool().execute({})).output
        if not zeilen:
            return ToolResult.success("Im Programm habe ich dazu nichts gefunden.\n" + geschmack)
        return ToolResult.success("\n".join(zeilen) + "\n\nMarcs Geschmack: " + geschmack)


class TvAufnahmeTool(Tool):
    name = "tv_aufnahme"
    description = (
        "Fuer 'nimm ... auf', 'programmier eine Aufnahme': sucht die Sendung im "
        "Programm und merkt sie als Aufnahmewunsch vor. Sunrise laesst "
        "Aufnahmen nur in der eigenen App programmieren - danach oeffnest du "
        "mit sunrise_tv die App und setzt mit erinnerung_setzen eine "
        "Erinnerung 10 Minuten vor Beginn, falls Marc das will."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("sendung", "string", "Titel der Sendung."),
        ToolParameter("sender", "string", "Sender (optional).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.integrations import tvprogramm as tv

        titel = str(arguments.get("sendung") or "").strip()
        if not titel:
            return ToolResult.failure("Welche Sendung soll aufgenommen werden?")
        try:
            treffer, _ = await asyncio.to_thread(
                tv.suchen, suche=titel, sender=str(arguments.get("sender") or ""), anzahl=6)
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Das Fernsehprogramm ist gerade nicht abrufbar: {fehler}")
        if not treffer:
            return ToolResult.failure(f"'{titel}' kommt in der naechsten Woche nicht im Programm.")
        erste = treffer[0]
        try:
            from backend.knowledge.wissensbibliothek import bibliothek

            bibliothek().merke(f"Marc wollte aufnehmen: {erste['titel']}",
                               f"Aufnahmewunsch: {tv.zeile(erste)}",
                               quelle=f"aufnahme:{erste['sender_id']}:{erste['start']:%Y%m%d%H%M}",
                               art="filmgeschmack")
        except Exception:  # noqa: BLE001
            pass
        termine = "\n".join(f"- {tv.zeile(s)}" for s in treffer)
        return ToolResult.success(
            f"Gefunden:\n{termine}\n\nNaechster Termin: {erste['start']:%d.%m. %H:%M} auf {erste['sender']}. "
            "Aufnahmen programmiert Sunrise nur in seiner App (Sendung antippen -> Aufnehmen). "
            "Biete Marc an: App jetzt oeffnen (sunrise_tv) und/oder Erinnerung "
            f"am {erste['start']:%d.%m.} um {(erste['start'] - __import__('datetime').timedelta(minutes=10)):%H:%M} "
            "(erinnerung_setzen)."
        )


def build_sunrise_tools(desktop: Any | None = None) -> list[Tool]:
    # Das Programm einmal im Hintergrund holen, damit die erste Frage schnell ist.
    import threading

    def _vorwaermen() -> None:
        try:
            from backend.integrations import tvprogramm

            tvprogramm.aktualisieren()
        except Exception:  # noqa: BLE001
            logger.info("TV-Programm beim Start nicht geholt.", exc_info=True)

    threading.Thread(target=_vorwaermen, name="tv-programm", daemon=True).start()
    return [SunriseTvTool(desktop), FilmVorschlagTool(), TvProgrammTool(), TvVorschlaegeTool(), TvAufnahmeTool()]
