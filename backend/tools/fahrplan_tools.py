"""Fahrplan: Zug- und Busverbindungen in der Schweiz (12.11.2026).

Marc fragte nach einer Verbindung von Melchnau nach Ostermundigen. Der Orb
suchte dafuer im Netz - mit "Hey Synapse" im Suchbegriff - und bekam
Seiten ueber eine Razer-Software. Eine Websuche ist fuer Fahrplaene ohnehin
der falsche Weg: Abfahrtszeiten stehen nicht verlaesslich in Suchtreffern.

Dieses Werkzeug fragt die offene Fahrplan-Schnittstelle
https://transport.opendata.ch (Daten der SBB, aller Busse und Postautos,
ohne Schluessel) und gibt die naechsten Verbindungen sprechfertig zurueck.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

_API = "https://transport.opendata.ch/v1/connections"


def _uhrzeit(stempel: str) -> str:
    """'2026-11-12T16:47:00+0100' -> '16:47'."""

    treffer = re.search(r"T(\d{2}):(\d{2})", str(stempel or ""))
    return f"{treffer.group(1)}:{treffer.group(2)}" if treffer else "?"


def _dauer(text: str) -> str:
    """'00d01:05:00' -> '1 h 05 min'."""

    treffer = re.match(r"(\d+)d(\d{2}):(\d{2})", str(text or ""))
    if not treffer:
        return ""
    tage, stunden, minuten = (int(x) for x in treffer.groups())
    stunden += tage * 24
    return f"{stunden} h {minuten:02d} min" if stunden else f"{minuten} min"


def _datum(wert: str) -> str:
    wert = str(wert or "").strip().lower()
    heute = _dt.date.today()
    if not wert or wert == "heute":
        return heute.isoformat()
    if wert == "morgen":
        return (heute + _dt.timedelta(days=1)).isoformat()
    if wert == "übermorgen" or wert == "uebermorgen":
        return (heute + _dt.timedelta(days=2)).isoformat()
    treffer = re.match(r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?$", wert)
    if treffer:
        tag, monat, jahr = treffer.groups()
        jahr = int(jahr) if jahr else heute.year
        if jahr < 100:
            jahr += 2000
        return _dt.date(jahr, int(monat), int(tag)).isoformat()
    return wert  # schon YYYY-MM-DD


def verbindungen_formatieren(daten: dict[str, Any], *, anzahl: int = 3) -> str:
    """Macht aus der API-Antwort kurze, sprechfertige Zeilen."""

    zeilen: list[str] = []
    for verbindung in (daten.get("connections") or [])[:anzahl]:
        start = verbindung.get("from") or {}
        ziel = verbindung.get("to") or {}
        teile: list[str] = []
        for abschnitt in verbindung.get("sections") or []:
            fahrt = abschnitt.get("journey")
            if not fahrt:
                continue
            linie = f"{fahrt.get('category') or ''} {fahrt.get('number') or ''}".strip()
            ab = abschnitt.get("departure") or {}
            an = abschnitt.get("arrival") or {}
            von = ((ab.get("station") or {}).get("name")) or "?"
            nach = ((an.get("station") or {}).get("name")) or "?"
            gleis = ab.get("platform")
            teile.append(
                f"{linie} {_uhrzeit(ab.get('departure'))} ab {von}"
                + (f" (Gleis/Kante {gleis})" if gleis else "")
                + f", an {nach} {_uhrzeit(an.get('arrival'))}"
            )
        umstiege = int(verbindung.get("transfers") or 0)
        kopf = (
            f"Ab {_uhrzeit(start.get('departure'))}, an {_uhrzeit(ziel.get('arrival'))}"
            f" ({_dauer(verbindung.get('duration'))}, "
            + ("direkt" if umstiege == 0 else f"{umstiege}x umsteigen")
            + ")"
        )
        zeilen.append(kopf + (": " + "; ".join(teile) if teile else ""))
    if not zeilen:
        return ""
    von = ((daten.get("from") or {}).get("name")) or ""
    nach = ((daten.get("to") or {}).get("name")) or ""
    titel = f"Verbindungen {von} -> {nach}".strip()
    return titel + "\n" + "\n".join(f"- {z}" for z in zeilen)


_OEV_WOERTER = re.compile(
    r"\b(?:zug|bus|bahn|postauto|tram|\u00f6v|oev)verbindung\w*|\w*fahrplan\w*|\bverbindung(?:en)?\b|\b(?:zug|z\u00fcge|zuege|zugs|bus|busse[ns]?|postauto|tram|s-bahn|"
    r"fahrplan|\u00f6v|oev|\u00f6ffentlich\w*|oeffentlich\w*|bahn|sbb|abfahrt\w*)\b",
    re.IGNORECASE,
)
_ENDE_ORT = (
    r"(?=\s*[,;!?]|\.\s|\.$|\s+(?:um|ab|an|abfahrt|ankunft|heute|morgen|\u00fcbermorgen|"
    r"uebermorgen|fr\u00fchestens|fruehestens|sp\u00e4testens|spaetestens|am|bis|gegen|mit|"
    r"und|bitte|so\s+dass|damit|zwischen|nach\s+\d)\b|$)"
)


def fahrplan_anfrage(text: str) -> dict[str, Any] | None:
    """Erkennt "Verbindung von X nach Y (um HH:MM)" und liefert die Argumente.

    Nur wenn sowohl ein OeV-Wort als auch "von ... nach ..." vorkommen -
    sonst ``None``, und der Orb antwortet wie bisher.
    """

    text = " ".join(str(text or "").split())
    if not _OEV_WOERTER.search(text):
        return None
    treffer = re.search(r"\bvon\s+(.+?)\s+nach\s+(.+?)" + _ENDE_ORT, text, re.IGNORECASE)
    if not treffer:
        # "Zugverbindung Bern nach Thun" - ohne "von".
        treffer = re.search(
            r"\w*(?:verbindung|zug|bus|postauto|fahrplan)\w*\s+(?:ab\s+)?(.+?)\s+(?:nach|bis)\s+(.+?)"
            + _ENDE_ORT,
            text,
            re.IGNORECASE,
        )
    if not treffer:
        treffer_umgekehrt = re.search(
            r"\bnach\s+(.+?)\s+von\s+(.+?)" + _ENDE_ORT, text, re.IGNORECASE
        )
        if not treffer_umgekehrt:
            return None
        nach, von = treffer_umgekehrt.group(1), treffer_umgekehrt.group(2)
    else:
        von, nach = treffer.group(1), treffer.group(2)
    von = von.strip(" .,;:-")
    nach = nach.strip(" .,;:-")
    if not von or not nach:
        return None
    argumente: dict[str, Any] = {"von": von, "nach": nach}

    zeit = re.search(r"\b(\d{1,2})[:.](\d{2})\b", text)
    if zeit:
        argumente["zeit"] = f"{int(zeit.group(1)):02d}:{zeit.group(2)}"
    else:
        zeit = re.search(r"\b(\d{1,2})\s*uhr(?:\s*(\d{1,2}))?\b", text, re.IGNORECASE)
        if zeit:
            argumente["zeit"] = f"{int(zeit.group(1)):02d}:{int(zeit.group(2) or 0):02d}"
    tief = text.lower()
    if "übermorgen" in tief or "uebermorgen" in tief:
        argumente["datum"] = "übermorgen"
    elif re.search(r"\bmorgen\b", tief):
        argumente["datum"] = "morgen"
    else:
        datum = re.search(r"\bam\s+(\d{1,2}\.\s?\d{1,2}\.(?:\d{2,4})?)", text)
        if datum:
            argumente["datum"] = datum.group(1).replace(" ", "")
    if re.search(r"\b(?:ankunft|ankommen|an\s+sein|dort\s+sein|sp\u00e4testens|spaetestens)\b", tief) or re.search(
        r"\bmuss\b.*\bin\s+\S+\s+sein\b", tief
    ):
        argumente["ankunft"] = True
    return argumente


def ist_fahrplanfrage(text: str) -> bool:
    """Geht es um eine OeV-Verbindung, auch wenn die Orte unklar sind?"""

    treffer = [t.lower() for t in _OEV_WOERTER.findall(str(text or ""))]
    stark = [t for t in treffer if not t.startswith("verbindung")]
    return bool(stark) and not re.search(
        r"\bwetter\b", str(text or ""), re.IGNORECASE
    )


def _ortsvarianten(ort: str) -> list[str]:
    """'Melchnau-Giuch' -> ['Melchnau-Giuch', 'Melchnau, Giuch', 'Melchnau']."""

    varianten = [ort]
    if "-" in ort:
        varianten.append(ort.replace("-", ", "))
        varianten.append(ort.split("-")[0].strip())
    elif "," in ort:
        varianten.append(ort.split(",")[0].strip())
    return [v for i, v in enumerate(varianten) if v and v not in varianten[:i]]


class VerbindungSuchenTool(Tool):
    """Sucht OeV-Verbindungen in der Schweiz."""

    name = "verbindung_suchen"
    description = (
        "Sucht Zug-, Bus- und Postauto-Verbindungen in der Schweiz (SBB-Fahrplan) "
        "von einem Ort zum anderen, mit Abfahrts- und Ankunftszeiten, Linien, "
        "Gleisen und Umstiegen. IMMER benutzen, wenn nach einer Verbindung, "
        "einem Zug, Bus oder Fahrplan gefragt wird - nicht die Websuche."
    )
    permission = "network"
    parameters = (
        ToolParameter("von", "string", "Abfahrtsort oder Haltestelle, z. B. 'Melchnau, Giuch'."),
        ToolParameter("nach", "string", "Zielort oder Haltestelle, z. B. 'Ostermundigen'."),
        ToolParameter(
            "zeit", "string", "Uhrzeit HH:MM. Leer heisst: jetzt.",
            required=False, default="",
        ),
        ToolParameter(
            "datum", "string", "'heute', 'morgen', TT.MM. oder JJJJ-MM-TT. Leer heisst: heute.",
            required=False, default="",
        ),
        ToolParameter(
            "ankunft", "boolean",
            "true, wenn die Zeit die gewuenschte ANKUNFT ist (sonst Abfahrt).",
            required=False, default=False,
        ),
    )

    def __init__(self, *, timeout: float = 10.0) -> None:
        super().__init__()
        self._timeout = timeout

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        von = str(arguments.get("von", "") or "").strip()
        nach = str(arguments.get("nach", "") or "").strip()
        if not von or not nach:
            return ToolResult.failure("Bitte Abfahrtsort und Ziel angeben.")
        parameter: dict[str, Any] = {"from": von, "to": nach, "limit": 4}
        zeit = str(arguments.get("zeit", "") or "").strip()
        if zeit:
            treffer = re.search(r"(\d{1,2})[:.h](\d{2})", zeit)
            if treffer:
                parameter["time"] = f"{int(treffer.group(1)):02d}:{treffer.group(2)}"
        try:
            parameter["date"] = _datum(str(arguments.get("datum", "") or ""))
        except ValueError:
            pass
        if str(arguments.get("ankunft", "")).lower() in ("true", "1", "ja"):
            parameter["isArrivalTime"] = 1

        # Gesprochene Ortsnamen sind oft ungenau ("Melchnau-Giuch" statt
        # "Melchnau, Giuch"). Darum einige Schreibweisen nacheinander.
        versuche = [(v, n) for v in _ortsvarianten(von) for n in _ortsvarianten(nach)][:4]
        text = ""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for start, ziel in versuche:
                    parameter["from"], parameter["to"] = start, ziel
                    antwort = await client.get(_API, params=parameter)
                    antwort.raise_for_status()
                    text = verbindungen_formatieren(antwort.json())
                    if text:
                        break
        except Exception as error:  # noqa: BLE001
            logger.warning("Fahrplanabfrage fehlgeschlagen: %s", error)
            return ToolResult.failure(f"Der Fahrplan ist gerade nicht erreichbar: {error}")

        if not text:
            return ToolResult.failure(
                f"Keine Verbindung von '{von}' nach '{nach}' gefunden. Vielleicht die "
                "Haltestelle genauer nennen (z. B. 'Melchnau, Giuch')."
            )
        hinweis = (
            f"\n(Abgefragt: {parameter.get('date', '')} "
            + ("Ankunft" if parameter.get("isArrivalTime") else "Abfahrt")
            + f" ab {parameter.get('time', 'jetzt')}. Nenne sofort die erste passende "
            "Verbindung mit Abfahrt, Umstieg und Ankunft - kurz. Frag NICHT nach "
            "Uhrzeit oder Datum: ohne Angabe gilt 'ab jetzt'.)"
        )
        return ToolResult.success(text + hinweis)
