"""Alltag: Erinnerungen, Abfahrtswecker, Wetter und Morgen-Briefing (12.11.2026).

Marc wollte, dass Synapse im Alltag mehr abnimmt:

* "Erinnere mich um 16 Uhr an den Hund"          -> erinnerung_setzen
* "Sag mir, wann ich los muss, damit ich um 17 Uhr
   in Bern bin"                                   -> abfahrt_erinnern
* "Wie wird das Wetter morgen?"                   -> wetter
* "Was steht heute an?" / jeden Morgen um 7       -> tagesueberblick,
                                                     briefing_einplanen

Erinnerungen liegen in ``data/erinnerungen.json`` und ueberstehen einen
Neustart. Faellig gewordene sagt der Orb am PC an UND legt sie fuer das
Handy bereit - die Handy-Seite holt sie alle paar Sekunden ab und liest
sie vor (ein iPhone laesst eine Webseite nichts von sich aus zustellen,
solange sie nicht offen ist).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

BRIEFING = "__briefing__"

# --- Zeitangaben ----------------------------------------------------------------

_ZAHLWORTE = {
    "eine": 1, "einer": 1, "einem": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "zehn": 10, "fünfzehn": 15, "fuenfzehn": 15,
    "zwanzig": 20, "dreissig": 30, "dreißig": 30, "halbe": 30,
}


def zeitpunkt_aus(zeit: str, datum: str = "", *, jetzt: _dt.datetime | None = None) -> _dt.datetime:
    """Macht aus "16:00", "16 Uhr 30", "in 20 Minuten" (+ "morgen") einen Zeitpunkt."""

    jetzt = jetzt or _dt.datetime.now()
    text = " ".join(str(zeit or "").lower().split())

    relativ = re.search(
        r"in\s+(\d+|[a-zäöüß]+)\s*(minute|minuten|min|stunde|stunden|std)\b", text
    )
    if relativ:
        roh = relativ.group(1)
        menge = int(roh) if roh.isdigit() else _ZAHLWORTE.get(roh, 0)
        if not menge:
            raise ValueError(f"Die Dauer '{zeit}' verstehe ich nicht.")
        minuten = menge * 60 if relativ.group(2).startswith(("stu", "std")) else menge
        if roh == "halbe":
            minuten = 30
        return jetzt + _dt.timedelta(minutes=minuten)

    uhr = re.search(r"(\d{1,2})[:.h](\d{2})", text) or re.search(
        r"(\d{1,2})\s*uhr(?:\s*(\d{1,2}))?", text
    ) or re.fullmatch(r"(\d{1,2})", text)
    if not uhr:
        raise ValueError(f"Die Uhrzeit '{zeit}' verstehe ich nicht (z. B. 16:30 oder 'in 20 Minuten').")
    stunde = int(uhr.group(1))
    minute = int(uhr.group(2) or 0) if uhr.lastindex and uhr.lastindex >= 2 else 0
    if stunde > 23 or minute > 59:
        raise ValueError(f"Die Uhrzeit '{zeit}' gibt es nicht.")

    tag = jetzt.date()
    d = str(datum or "").strip().lower()
    if d in ("morgen",):
        tag += _dt.timedelta(days=1)
    elif d in ("übermorgen", "uebermorgen"):
        tag += _dt.timedelta(days=2)
    elif d and d != "heute":
        treffer = re.match(r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?$", d)
        if treffer:
            jahr = int(treffer.group(3)) if treffer.group(3) else jetzt.year
            if jahr < 100:
                jahr += 2000
            tag = _dt.date(jahr, int(treffer.group(2)), int(treffer.group(1)))
        else:
            tag = _dt.date.fromisoformat(d)
    zeitpunkt = _dt.datetime.combine(tag, _dt.time(stunde, minute))
    if not d and zeitpunkt <= jetzt:
        zeitpunkt += _dt.timedelta(days=1)  # "um 7" heisst: das naechste 7 Uhr
    return zeitpunkt


def _wann(zeitpunkt: _dt.datetime, jetzt: _dt.datetime | None = None) -> str:
    jetzt = jetzt or _dt.datetime.now()
    uhr = zeitpunkt.strftime("%H:%M")
    if zeitpunkt.date() == jetzt.date():
        return f"heute um {uhr}"
    if zeitpunkt.date() == jetzt.date() + _dt.timedelta(days=1):
        return f"morgen um {uhr}"
    return f"am {zeitpunkt.strftime('%d.%m.')} um {uhr}"


# --- Erinnerungen -----------------------------------------------------------------


class Erinnerungsdienst:
    """Speichert Erinnerungen und sagt sie an, wenn sie faellig sind."""

    def __init__(
        self,
        pfad: Path,
        ansagen: Callable[[str], Awaitable[Any]] | None = None,
        *,
        takt_sekunden: float = 15.0,
    ) -> None:
        self._pfad = Path(pfad)
        self._ansagen = ansagen
        self._takt = takt_sekunden
        self._aufgabe: asyncio.Task[Any] | None = None
        self.briefing: Callable[[], Awaitable[str]] | None = None

    # Speicher
    def alle(self) -> list[dict[str, Any]]:
        try:
            daten = json.loads(self._pfad.read_text(encoding="utf-8"))
            return list(daten) if isinstance(daten, list) else []
        except (OSError, ValueError):
            return []

    def _schreiben(self, liste: list[dict[str, Any]]) -> None:
        self._pfad.parent.mkdir(parents=True, exist_ok=True)
        zwischen = self._pfad.with_suffix(".tmp")
        zwischen.write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
        zwischen.replace(self._pfad)

    def anlegen(self, text: str, zeitpunkt: _dt.datetime, *, wiederholen: str = "") -> dict[str, Any]:
        eintrag = {
            "id": uuid.uuid4().hex[:8],
            "text": str(text).strip(),
            "zeit": zeitpunkt.replace(second=0, microsecond=0).isoformat(),
            "wiederholen": wiederholen,
        }
        liste = self.alle()
        if text == BRIEFING:
            liste = [e for e in liste if e.get("text") != BRIEFING]
        liste.append(eintrag)
        liste.sort(key=lambda e: e.get("zeit", ""))
        self._schreiben(liste)
        return eintrag

    def loeschen(self, suche: str) -> list[dict[str, Any]]:
        suche = str(suche or "").strip().lower()
        liste = self.alle()
        if suche in ("alle", "alles"):
            weg, bleibt = liste, []
        else:
            weg = [e for e in liste if suche and (suche == e.get("id") or suche in str(e.get("text", "")).lower()
                   or (suche in ("briefing", "morgenbriefing") and e.get("text") == BRIEFING))]
            bleibt = [e for e in liste if e not in weg]
        self._schreiben(bleibt)
        return weg

    # Ablauf
    def faellige(self, jetzt: _dt.datetime | None = None) -> list[dict[str, Any]]:
        """Nimmt alle faelligen heraus (wiederkehrende werden weitergeschoben)."""

        jetzt = jetzt or _dt.datetime.now()
        liste = self.alle()
        faellig: list[dict[str, Any]] = []
        neu: list[dict[str, Any]] = []
        for eintrag in liste:
            try:
                zeit = _dt.datetime.fromisoformat(str(eintrag.get("zeit")))
            except ValueError:
                continue
            if zeit > jetzt:
                neu.append(eintrag)
                continue
            # Laenger als 6 Stunden verpasst (PC war aus): nicht mehr ansagen.
            if jetzt - zeit <= _dt.timedelta(hours=6):
                faellig.append(eintrag)
            if eintrag.get("wiederholen") == "taeglich":
                while zeit <= jetzt:
                    zeit += _dt.timedelta(days=1)
                eintrag = dict(eintrag, zeit=zeit.isoformat())
                neu.append(eintrag)
        if faellig or len(neu) != len(liste):
            neu.sort(key=lambda e: e.get("zeit", ""))
            self._schreiben(neu)
        return faellig

    async def einmal_pruefen(self) -> int:
        anzahl = 0
        for eintrag in self.faellige():
            text = str(eintrag.get("text", ""))
            if text == BRIEFING:
                if self.briefing is None:
                    continue
                try:
                    text = await self.briefing()
                except Exception:  # noqa: BLE001
                    logger.exception("Das Morgen-Briefing liess sich nicht erstellen.")
                    continue
            else:
                text = f"Erinnerung: {text}"
            if self._ansagen is not None:
                try:
                    await self._ansagen(text)
                except Exception:  # noqa: BLE001
                    logger.exception("Erinnerung liess sich nicht ansagen.")
            logger.info("Erinnerung faellig: %s", text[:120])
            anzahl += 1
        return anzahl

    def starten(self) -> None:
        if self._aufgabe is None or self._aufgabe.done():
            self._aufgabe = asyncio.get_running_loop().create_task(self._schleife())

    async def anhalten(self) -> None:
        if self._aufgabe is not None:
            self._aufgabe.cancel()

    async def _schleife(self) -> None:
        while True:
            try:
                await self.einmal_pruefen()
            except Exception:  # noqa: BLE001
                logger.exception("Erinnerungsschleife gestolpert.")
            await asyncio.sleep(self._takt)


class ErinnerungSetzenTool(Tool):
    name = "erinnerung_setzen"
    description = (
        "Merkt eine Erinnerung vor und sagt sie zur Zeit an (am PC und auf dem Handy). "
        "Fuer 'erinnere mich um 16 Uhr an ...', 'in 20 Minuten ...', 'jeden Tag um 8 ...'."
    )
    permission = "compute"
    parameters = (
        ToolParameter("text", "string", "Woran erinnert werden soll."),
        ToolParameter("zeit", "string", "Uhrzeit (16:30, 7 Uhr) oder Dauer ('in 20 Minuten')."),
        ToolParameter("datum", "string", "heute, morgen, TT.MM. - leer = naechstes Mal.",
                      required=False, default=""),
        ToolParameter("taeglich", "boolean", "Jeden Tag wiederholen.", required=False, default=False),
    )

    def __init__(self, dienst: Erinnerungsdienst) -> None:
        super().__init__()
        self._dienst = dienst

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = str(arguments.get("text", "") or "").strip()
        if not text:
            return ToolResult.failure("Woran soll ich erinnern?")
        try:
            zeitpunkt = zeitpunkt_aus(str(arguments.get("zeit", "")), str(arguments.get("datum", "") or ""))
        except ValueError as fehler:
            return ToolResult.failure(str(fehler))
        taeglich = str(arguments.get("taeglich", "")).lower() in ("true", "1", "ja")
        self._dienst.anlegen(text, zeitpunkt, wiederholen="taeglich" if taeglich else "")
        return ToolResult.success(
            f"Erinnerung gesetzt: {_wann(zeitpunkt)}" + (" (jeden Tag)" if taeglich else "")
            + f" - {text}."
        )


class ErinnerungenZeigenTool(Tool):
    name = "erinnerungen_zeigen"
    description = "Nennt alle anstehenden Erinnerungen und das Morgen-Briefing."
    permission = "compute"
    parameters = ()

    def __init__(self, dienst: Erinnerungsdienst) -> None:
        super().__init__()
        self._dienst = dienst

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        liste = self._dienst.alle()
        if not liste:
            return ToolResult.success("Es stehen keine Erinnerungen an.")
        zeilen = []
        for e in liste:
            zeit = _dt.datetime.fromisoformat(e["zeit"])
            text = "Morgen-Briefing" if e.get("text") == BRIEFING else e.get("text")
            zeilen.append(f"- {_wann(zeit)}: {text}" + (" (taeglich)" if e.get("wiederholen") else ""))
        return ToolResult.success("Anstehende Erinnerungen:\n" + "\n".join(zeilen))


class ErinnerungLoeschenTool(Tool):
    name = "erinnerung_loeschen"
    description = "Loescht Erinnerungen: ein Stichwort aus dem Text, 'briefing' oder 'alle'."
    permission = "compute"
    parameters = (ToolParameter("suche", "string", "Stichwort, 'briefing' oder 'alle'."),)

    def __init__(self, dienst: Erinnerungsdienst) -> None:
        super().__init__()
        self._dienst = dienst

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        weg = self._dienst.loeschen(str(arguments.get("suche", "")))
        if not weg:
            return ToolResult.failure("Dazu habe ich keine Erinnerung gefunden.")
        return ToolResult.success(f"{len(weg)} Erinnerung(en) geloescht.")


class BriefingEinplanenTool(Tool):
    name = "briefing_einplanen"
    description = (
        "Plant das taegliche Morgen-Briefing (Wetter, Termine, Mails, Pendelverbindung) "
        "zu einer Uhrzeit ein, z. B. 'jeden Morgen um 7'. Abschalten: erinnerung_loeschen('briefing')."
    )
    permission = "compute"
    parameters = (ToolParameter("uhrzeit", "string", "z. B. 07:00"),)

    def __init__(self, dienst: Erinnerungsdienst) -> None:
        super().__init__()
        self._dienst = dienst

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            zeitpunkt = zeitpunkt_aus(str(arguments.get("uhrzeit", "")))
        except ValueError as fehler:
            return ToolResult.failure(str(fehler))
        self._dienst.anlegen(BRIEFING, zeitpunkt, wiederholen="taeglich")
        return ToolResult.success(f"Morgen-Briefing eingeplant: jeden Tag um {zeitpunkt:%H:%M}.")


# --- Abfahrtswecker ---------------------------------------------------------------


class AbfahrtErinnernTool(Tool):
    name = "abfahrt_erinnern"
    description = (
        "Sucht die passende OeV-Verbindung, um rechtzeitig anzukommen, und erinnert "
        "Marc, wann er los muss. Fuer 'sag mir, wann ich los muss, damit ich um 17 Uhr "
        "in Bern bin'. Ohne 'von' gilt der Heimatort."
    )
    permission = "network"
    parameters = (
        ToolParameter("nach", "string", "Ziel."),
        ToolParameter("ankunft", "string", "Gewuenschte Ankunftszeit, z. B. 17:00."),
        ToolParameter("von", "string", "Start - leer = Heimatort.", required=False, default=""),
        ToolParameter("datum", "string", "heute/morgen/TT.MM.", required=False, default=""),
        ToolParameter("vorlauf_minuten", "integer", "Wie viele Minuten vor Abfahrt erinnern.",
                      required=False, default=10),
    )

    def __init__(self, dienst: Erinnerungsdienst, *, heimatort: str = "",
                 abfragen: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None) -> None:
        super().__init__()
        self._dienst = dienst
        self._heimatort = heimatort
        self._abfragen = abfragen or _fahrplan_abfragen

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        von = str(arguments.get("von", "") or "").strip() or self._heimatort
        nach = str(arguments.get("nach", "") or "").strip()
        if not von or not nach:
            return ToolResult.failure("Von wo nach wo? (Ein Heimatort ist nicht eingestellt.)")
        try:
            ankunft = zeitpunkt_aus(str(arguments.get("ankunft", "")), str(arguments.get("datum", "") or ""))
        except ValueError as fehler:
            return ToolResult.failure(str(fehler))
        try:
            daten = await self._abfragen({
                "from": von, "to": nach, "date": ankunft.date().isoformat(),
                "time": ankunft.strftime("%H:%M"), "isArrivalTime": 1, "limit": 4,
            })
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Der Fahrplan ist gerade nicht erreichbar: {fehler}")

        passend = None
        for verbindung in daten.get("connections") or []:
            an = _iso(((verbindung.get("to") or {}).get("arrival")))
            ab = _iso(((verbindung.get("from") or {}).get("departure")))
            if an and ab and an <= ankunft and (passend is None or ab > passend[0]):
                passend = (ab, an, verbindung)
        if passend is None:
            return ToolResult.failure(f"Ich finde keine Verbindung von {von} nach {nach}, die bis {ankunft:%H:%M} ankommt.")

        ab, an, verbindung = passend
        linie = ""
        for abschnitt in verbindung.get("sections") or []:
            fahrt = abschnitt.get("journey")
            if fahrt:
                linie = f"{fahrt.get('category') or ''} {fahrt.get('number') or ''}".strip()
                break
        vorlauf = int(arguments.get("vorlauf_minuten") or 10)
        wecker = ab - _dt.timedelta(minutes=vorlauf)
        jetzt = _dt.datetime.now()
        text = (f"In {vorlauf} Minuten musst du los: {linie} um {ab:%H:%M} ab "
                f"{(verbindung.get('from') or {}).get('station', {}).get('name') or von}, "
                f"an {nach} um {an:%H:%M}.")
        if wecker <= jetzt:
            return ToolResult.success(
                f"Du musst sofort los: {linie} faehrt um {ab:%H:%M}, an {nach} um {an:%H:%M}."
            )
        self._dienst.anlegen(text.replace("Erinnerung: ", ""), wecker)
        return ToolResult.success(
            f"Erledigt: {linie} ab {ab:%H:%M}, an {nach} {an:%H:%M}. Ich erinnere dich "
            f"{_wann(wecker)}."
        )


def _iso(stempel: Any) -> _dt.datetime | None:
    """'2026-11-12T16:47:00+0100' -> naive Ortszeit."""

    treffer = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})", str(stempel or ""))
    return _dt.datetime.fromisoformat(treffer.group(1)) if treffer else None


async def _fahrplan_abfragen(parameter: dict[str, Any]) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        antwort = await client.get("https://transport.opendata.ch/v1/connections", params=parameter)
    antwort.raise_for_status()
    return antwort.json()


# --- Wetter -----------------------------------------------------------------------

_WETTER = {
    0: "klar", 1: "meist sonnig", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Reifnebel",
    51: "leichter Niesel", 53: "Niesel", 55: "starker Niesel", 56: "gefrierender Niesel",
    57: "gefrierender Niesel", 61: "leichter Regen", 63: "Regen", 65: "starker Regen",
    66: "gefrierender Regen", 67: "gefrierender Regen", 71: "leichter Schneefall",
    73: "Schneefall", 75: "starker Schneefall", 77: "Schneegriesel", 80: "Regenschauer",
    81: "Regenschauer", 82: "heftige Regenschauer", 85: "Schneeschauer", 86: "Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit Hagel",
}


async def _wetter_holen(ort: str) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": ort, "count": 1, "language": "de"},
        )
        geo.raise_for_status()
        treffer = (geo.json().get("results") or [None])[0]
        if not treffer:
            raise ValueError(f"Den Ort '{ort}' finde ich nicht.")
        antwort = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": treffer["latitude"], "longitude": treffer["longitude"],
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Europe/Zurich", "forecast_days": 3,
            },
        )
        antwort.raise_for_status()
        daten = antwort.json()
    daten["_ort"] = treffer.get("name", ort)
    return daten


def wetter_text(daten: dict[str, Any], *, tage: int = 1) -> str:
    ort = daten.get("_ort", "")
    teile = []
    jetzt = daten.get("current") or {}
    if jetzt:
        teile.append(
            f"In {ort} jetzt {round(jetzt.get('temperature_2m', 0))} Grad, "
            f"{_WETTER.get(int(jetzt.get('weather_code', -1)), 'unklar')}."
        )
    taeglich = daten.get("daily") or {}
    namen = ["Heute", "Morgen", "Übermorgen"]
    for i in range(min(max(tage, 1), len(taeglich.get("time") or []), 3)):
        regen = (taeglich.get("precipitation_probability_max") or [None] * 3)[i]
        teile.append(
            f"{namen[i]}: {_WETTER.get(int(taeglich['weather_code'][i]), 'unklar')}, "
            f"{round(taeglich['temperature_2m_min'][i])} bis {round(taeglich['temperature_2m_max'][i])} Grad"
            + (f", Regenrisiko {regen} Prozent" if regen is not None else "") + "."
        )
    return " ".join(teile)


class WetterTool(Tool):
    name = "wetter"
    description = (
        "Aktuelles Wetter und Vorhersage fuer heute bis uebermorgen (Open-Meteo). "
        "Ohne Ort gilt der Heimatort. IMMER benutzen statt der Websuche."
    )
    permission = "network"
    parameters = (
        ToolParameter("ort", "string", "Ort - leer = Heimatort.", required=False, default=""),
        ToolParameter("tage", "integer", "1 = heute, 2 = bis morgen, 3 = bis uebermorgen.",
                      required=False, default=2),
    )

    def __init__(self, *, heimatort: str = "", holen: Callable[[str], Awaitable[dict[str, Any]]] | None = None) -> None:
        super().__init__()
        self._heimatort = heimatort
        self._holen = holen or _wetter_holen

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ort = str(arguments.get("ort", "") or "").strip() or self._heimatort or "Bern"
        try:
            daten = await self._holen(ort)
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Das Wetter ist gerade nicht abrufbar: {fehler}")
        return ToolResult.success(wetter_text(daten, tage=int(arguments.get("tage") or 2)))


# --- Tagesueberblick ----------------------------------------------------------------


class Tagesueberblick:
    """Stellt Wetter, Termine, Mails und Pendelverbindung zusammen."""

    def __init__(self, *, heimatort: str = "", pendelziel: str = "", haltestelle: str = "",
                 kalender: Any = None,
                 gmail: Any = None, wetter: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
                 fahrplan: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None) -> None:
        self.heimatort = heimatort
        self.pendelziel = pendelziel
        self.haltestelle = haltestelle or heimatort
        self.kalender = kalender
        self.gmail = gmail
        self._wetter = wetter or _wetter_holen
        self._fahrplan = fahrplan or _fahrplan_abfragen

    async def erstellen(self) -> str:
        jetzt = _dt.datetime.now()
        gruss = "Guten Morgen" if jetzt.hour < 11 else ("Hallo" if jetzt.hour < 18 else "Guten Abend")
        teile = [f"{gruss}, Marc. Hier dein Überblick."]

        if self.heimatort:
            try:
                teile.append(wetter_text(await self._wetter(self.heimatort), tage=1))
            except Exception as fehler:  # noqa: BLE001
                logger.info("Briefing ohne Wetter: %s", fehler)

        if self.kalender is not None:
            try:
                from backend.integrations.kalender.zeit import ortszeit

                von = ortszeit()
                bis = ortszeit(_dt.datetime.combine(jetzt.date(), _dt.time(23, 59)))
                termine = await asyncio.to_thread(self.kalender.termine, von=von, bis=bis, limit=8)
                if termine:
                    liste = ", ".join(
                        (f"{t.beginn:%H:%M} {t.titel}" if t.beginn and not t.ganztags else t.titel)
                        for t in termine
                    )
                    teile.append(f"Heute im Kalender: {liste}.")
                else:
                    teile.append("Heute stehen keine Termine im Kalender.")
            except Exception as fehler:  # noqa: BLE001
                logger.info("Briefing ohne Kalender: %s", fehler)

        if self.gmail is not None:
            try:
                ungelesen = await self.gmail.read_unread(limit=5)
                if ungelesen:
                    wer = ", ".join(sorted({m.sender.split("<")[0].strip().strip('"') or m.sender
                                            for m in ungelesen})[:4])
                    teile.append(f"{len(ungelesen)} ungelesene Mails, unter anderem von {wer}.")
                else:
                    teile.append("Keine ungelesenen Mails.")
            except Exception as fehler:  # noqa: BLE001
                logger.info("Briefing ohne Mails: %s", fehler)

        if self.heimatort and self.pendelziel:
            try:
                daten = await self._fahrplan({"from": self.haltestelle, "to": self.pendelziel, "limit": 2})
                erste = (daten.get("connections") or [None])[0]
                if erste:
                    ab = _iso((erste.get("from") or {}).get("departure"))
                    an = _iso((erste.get("to") or {}).get("arrival"))
                    if ab and an:
                        teile.append(
                            f"Nächste Verbindung nach {self.pendelziel}: ab {ab:%H:%M}, an {an:%H:%M}."
                        )
            except Exception as fehler:  # noqa: BLE001
                logger.info("Briefing ohne Fahrplan: %s", fehler)
        return " ".join(teile)


class TagesueberblickTool(Tool):
    name = "tagesueberblick"
    description = (
        "Morgen-Briefing auf Abruf: Wetter am Heimatort, heutige Termine, ungelesene Mails "
        "und die naechste Pendelverbindung. Fuer 'was steht heute an', 'mein Briefing'."
    )
    permission = "network"
    parameters = ()

    def __init__(self, ueberblick: Tagesueberblick) -> None:
        super().__init__()
        self._ueberblick = ueberblick

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.success(await self._ueberblick.erstellen())


def build_alltag_tools(dienst: Erinnerungsdienst, ueberblick: Tagesueberblick) -> list[Tool]:
    return [
        ErinnerungSetzenTool(dienst),
        ErinnerungenZeigenTool(dienst),
        ErinnerungLoeschenTool(dienst),
        BriefingEinplanenTool(dienst),
        AbfahrtErinnernTool(dienst, heimatort=ueberblick.haltestelle),
        WetterTool(heimatort=ueberblick.heimatort),
        TagesueberblickTool(ueberblick),
    ]
