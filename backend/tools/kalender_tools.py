"""Die Werkzeuge für den Google-Kalender.

Vier Stück: ansehen, anlegen, ändern, löschen.

## Warum die drei ändernden Werkzeuge über einen Suchbegriff gehen

Google kennt Termine an einer Kennung wie ``4f8k2m9p1q``. Kein Mensch sagt
das, und ein Sprachmodell, das eine solche Kennung "erinnert", hat sie
erfunden. Deshalb nehmen ``termin_aendern`` und ``termin_loeschen`` einen
Suchbegriff entgegen und schlagen selbst nach.

Und wenn dabei mehr als ein Termin passt, wird **nicht** der erstbeste
genommen. Dann kommt die Liste zurück und die Bitte, genauer zu sagen,
welcher gemeint ist. Beim Löschen ist das der ganze Unterschied zwischen
einem hilfreichen Assistenten und einem, dem man nicht mehr trauen kann.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from backend.integrations.kalender.client import KalenderClient, KalenderFehler, Termin
from backend.integrations.kalender.zeit import ZeitFehler, dauer_lesen, zeit_lesen
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

#: Wie viele Treffer beim Auflösen eines Suchbegriffs betrachtet werden.
_TREFFER_GRENZE = 8

_ZEITRAEUME = ("heute", "morgen", "woche", "monat", "alles")


def _liste(termine: list[Termin], *, jetzt: datetime | None = None) -> str:
    if not termine:
        return "Keine Termine."
    return "\n".join(
        f"{i}. {t.zum_vorlesen(jetzt=jetzt)}  [id: {t.id}]"
        for i, t in enumerate(termine, start=1)
    )


def _zeitraum_grenzen(name: str, jetzt: datetime) -> tuple[datetime, datetime]:
    beginn_tag = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
    if name == "heute":
        return beginn_tag, beginn_tag + timedelta(days=1)
    if name == "morgen":
        return beginn_tag + timedelta(days=1), beginn_tag + timedelta(days=2)
    if name == "monat":
        return jetzt, jetzt + timedelta(days=31)
    if name == "alles":
        return jetzt - timedelta(days=365), jetzt + timedelta(days=365)
    return jetzt, jetzt + timedelta(days=7)


class _KalenderWerkzeug(Tool):
    """Gemeinsamer Unterbau: der Client und das Auflösen eines Suchbegriffs."""

    def __init__(self, client: KalenderClient) -> None:
        self._client = client

    async def _finden(self, text: str) -> tuple[Termin | None, list[Termin], str]:
        """Sucht den gemeinten Termin.

        Returns:
            Den eindeutigen Treffer (oder ``None``), alle Treffer und einen
            Klartexthinweis, falls es nicht eindeutig war.
        """

        begriff = (text or "").strip()
        if not begriff:
            return None, [], "Es fehlt die Angabe, welcher Termin gemeint ist."

        jetzt = datetime.now().astimezone()
        treffer = await asyncio.to_thread(
            self._client.termine,
            von=jetzt - timedelta(days=1),
            bis=jetzt + timedelta(days=365),
            suche=begriff,
            limit=_TREFFER_GRENZE,
        )

        if not treffer:
            # Die Volltextsuche von Google findet Teilwoerter nicht immer.
            # Deshalb noch einmal ohne Suchbegriff und selbst vergleichen.
            alle = await asyncio.to_thread(
                self._client.termine,
                von=jetzt - timedelta(days=1),
                bis=jetzt + timedelta(days=120),
                limit=100,
            )
            klein = begriff.lower()
            treffer = [t for t in alle if klein in t.titel.lower()][:_TREFFER_GRENZE]

        if not treffer:
            return None, [], f"Zu '{begriff}' war kein Termin zu finden."
        if len(treffer) == 1:
            return treffer[0], treffer, ""
        return None, treffer, (
            f"Auf '{begriff}' passen {len(treffer)} Termine. Sag genauer, "
            f"welcher gemeint ist:\n{_liste(treffer, jetzt=jetzt)}"
        )


class TermineAnsehenTool(_KalenderWerkzeug):
    """Zeigt, was ansteht."""

    name = "termine_ansehen"
    description = (
        "Zeigt die Termine aus dem Google-Kalender. Benutze dieses Werkzeug "
        "immer, wenn nach Terminen, dem Kalender, dem Tagesablauf oder danach "
        "gefragt wird, was ansteht. 'zeitraum' ist heute, morgen, woche oder "
        "monat; mit 'suche' lassen sich Termine zu einem Stichwort finden."
    )
    permission = "read_calendar"
    parameters = (
        ToolParameter(
            "zeitraum", "string", "Welcher Zeitraum.",
            required=False, default="woche", choices=_ZEITRAEUME,
        ),
        ToolParameter(
            "suche", "string", "Optionales Stichwort, z.B. 'Zahnarzt'.",
            required=False, default="",
        ),
        ToolParameter(
            "anzahl", "integer", "Wie viele Termine hoechstens.",
            required=False, default=10,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        jetzt = datetime.now().astimezone()
        zeitraum = str(arguments.get("zeitraum", "woche") or "woche").strip().lower()
        if zeitraum not in _ZEITRAEUME:
            zeitraum = "woche"
        von, bis = _zeitraum_grenzen(zeitraum, jetzt)
        try:
            anzahl = max(1, min(int(arguments.get("anzahl", 10) or 10), 50))
        except (TypeError, ValueError):
            anzahl = 10

        try:
            termine = await asyncio.to_thread(
                self._client.termine,
                von=von, bis=bis,
                suche=str(arguments.get("suche", "") or ""),
                limit=anzahl,
            )
        except KalenderFehler as fehler:
            return ToolResult.failure(str(fehler))

        if not termine:
            wann = {"heute": "heute", "morgen": "morgen"}.get(zeitraum, "in diesem Zeitraum")
            return ToolResult.success(
                f"Es steht {wann} nichts an.", termine=[], anzahl=0
            )

        return ToolResult.success(
            _liste(termine, jetzt=jetzt),
            termine=[t.to_dict() for t in termine],
            anzahl=len(termine),
        )


class TerminErstellenTool(_KalenderWerkzeug):
    """Legt einen Termin an."""

    name = "termin_erstellen"
    description = (
        "Legt einen neuen Termin im Google-Kalender an. Benutze dieses "
        "Werkzeug, wenn ein Termin eingetragen, vereinbart oder notiert werden "
        "soll. 'beginn' darf natuerlich formuliert sein - 'morgen 14 Uhr', "
        "'15.09.2026 09:30', 'naechsten Dienstag halb elf' - oder als ISO-Zeit. "
        "Ohne Dauerangabe wird eine Stunde angesetzt."
    )
    permission = "write_calendar"
    parameters = (
        ToolParameter("titel", "string", "Worum es geht, z.B. 'Zahnarzt'."),
        ToolParameter("beginn", "string", "Wann der Termin beginnt."),
        ToolParameter(
            "dauer", "string", "Wie lange, z.B. '90 Minuten' oder '2 Stunden'.",
            required=False, default="",
        ),
        ToolParameter(
            "ende", "string", "Alternativ das Ende statt der Dauer.",
            required=False, default="",
        ),
        ToolParameter(
            "ort", "string", "Wo der Termin stattfindet.",
            required=False, default="",
        ),
        ToolParameter(
            "beschreibung", "string", "Weitere Angaben zum Termin.",
            required=False, default="",
        ),
        ToolParameter(
            "ganztags", "boolean", "Ob es ein ganztaegiger Termin ist.",
            required=False, default=False,
        ),
        ToolParameter(
            "erinnerung_minuten", "integer",
            "Wie viele Minuten vorher Google erinnern soll.",
            required=False, default=None,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        titel = str(arguments.get("titel", "") or "").strip()
        if not titel:
            return ToolResult.failure("Es fehlt der Titel des Termins.")

        ganztags = bool(arguments.get("ganztags", False))
        try:
            beginn, ohne_uhrzeit = zeit_lesen(str(arguments.get("beginn", "") or ""))
        except ZeitFehler as fehler:
            return ToolResult.failure(str(fehler))
        # Wurde keine Uhrzeit genannt, ist es ein Tagestermin - das muss man
        # nicht zusaetzlich sagen.
        ganztags = ganztags or ohne_uhrzeit

        ende: datetime | None = None
        roh_ende = str(arguments.get("ende", "") or "").strip()
        if roh_ende:
            try:
                ende, _ = zeit_lesen(roh_ende)
            except ZeitFehler as fehler:
                return ToolResult.failure(f"Das Ende war nicht zu lesen: {fehler}")
        elif str(arguments.get("dauer", "") or "").strip():
            ende = beginn + timedelta(minutes=dauer_lesen(str(arguments["dauer"])))

        erinnerung = arguments.get("erinnerung_minuten")
        try:
            erinnerung = int(erinnerung) if erinnerung not in (None, "") else None
        except (TypeError, ValueError):
            erinnerung = None

        teilnehmer = arguments.get("teilnehmer") or []
        if isinstance(teilnehmer, str):
            teilnehmer = [t.strip() for t in teilnehmer.split(",") if t.strip()]

        try:
            termin = await asyncio.to_thread(
                self._client.anlegen,
                titel=titel,
                beginn=beginn,
                ende=ende,
                ganztags=ganztags,
                ort=str(arguments.get("ort", "") or ""),
                beschreibung=str(arguments.get("beschreibung", "") or ""),
                teilnehmer=list(teilnehmer),
                erinnerung_minuten=erinnerung,
            )
        except KalenderFehler as fehler:
            return ToolResult.failure(str(fehler))

        return ToolResult.success(
            f"Eingetragen: {termin.zum_vorlesen()}",
            termin=termin.to_dict(),
            id=termin.id,
        )


class TerminAendernTool(_KalenderWerkzeug):
    """Verschiebt oder ändert einen Termin."""

    name = "termin_aendern"
    description = (
        "Aendert einen bestehenden Termin im Google-Kalender - verschieben, "
        "umbenennen, Ort aendern. Den Termin ueber 'suchbegriff' benennen "
        "(z.B. 'Zahnarzt'); passen mehrere, wird nachgefragt statt geraten. "
        "Nur die Felder angeben, die sich aendern sollen. Wird nur der Beginn "
        "verschoben, bleibt die Dauer erhalten."
    )
    permission = "write_calendar"
    parameters = (
        ToolParameter("suchbegriff", "string", "Woran der Termin zu erkennen ist."),
        ToolParameter(
            "neuer_beginn", "string", "Der neue Beginn, z.B. 'morgen 16 Uhr'.",
            required=False, default="",
        ),
        ToolParameter(
            "neues_ende", "string", "Das neue Ende.", required=False, default="",
        ),
        ToolParameter(
            "neuer_titel", "string", "Der neue Titel.", required=False, default="",
        ),
        ToolParameter(
            "neuer_ort", "string", "Der neue Ort.", required=False, default="",
        ),
        ToolParameter(
            "neue_beschreibung", "string", "Die neue Beschreibung.",
            required=False, default="",
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            termin, treffer, hinweis = await self._finden(
                str(arguments.get("suchbegriff", "") or "")
            )
        except KalenderFehler as fehler:
            return ToolResult.failure(str(fehler))
        if termin is None:
            return ToolResult.failure(hinweis, treffer=[t.to_dict() for t in treffer])

        felder: dict[str, Any] = {}
        for name, ziel in (
            ("neuer_titel", "titel"),
            ("neuer_ort", "ort"),
            ("neue_beschreibung", "beschreibung"),
        ):
            wert = str(arguments.get(name, "") or "").strip()
            if wert:
                felder[ziel] = wert

        for name, ziel in (("neuer_beginn", "beginn"), ("neues_ende", "ende")):
            roh = str(arguments.get(name, "") or "").strip()
            if not roh:
                continue
            try:
                felder[ziel], _ = zeit_lesen(roh)
            except ZeitFehler as fehler:
                return ToolResult.failure(str(fehler))

        if not felder:
            return ToolResult.failure(
                f"Es wurde nicht gesagt, was sich an '{termin.titel}' aendern soll."
            )

        vorher = termin.zum_vorlesen()
        try:
            neu = await asyncio.to_thread(self._client.aendern, termin.id, **felder)
        except KalenderFehler as fehler:
            return ToolResult.failure(str(fehler))

        return ToolResult.success(
            f"Geaendert. Vorher: {vorher} Jetzt: {neu.zum_vorlesen()}",
            termin=neu.to_dict(),
            id=neu.id,
        )


class TerminLoeschenTool(_KalenderWerkzeug):
    """Löscht einen Termin."""

    name = "termin_loeschen"
    description = (
        "Loescht einen Termin aus dem Google-Kalender. Den Termin ueber "
        "'suchbegriff' benennen. Passen mehrere Termine, wird die Liste "
        "zurueckgegeben und nachgefragt - es wird nie geraten. Sage dem "
        "Benutzer immer, WELCHER Termin geloescht wurde."
    )
    permission = "write_calendar"
    parameters = (
        ToolParameter("suchbegriff", "string", "Woran der Termin zu erkennen ist."),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            termin, treffer, hinweis = await self._finden(
                str(arguments.get("suchbegriff", "") or "")
            )
        except KalenderFehler as fehler:
            return ToolResult.failure(str(fehler))
        if termin is None:
            return ToolResult.failure(hinweis, treffer=[t.to_dict() for t in treffer])

        beschreibung = termin.zum_vorlesen()
        try:
            await asyncio.to_thread(self._client.loeschen, termin.id)
        except KalenderFehler as fehler:
            return ToolResult.failure(str(fehler))

        return ToolResult.success(
            f"Geloescht: {beschreibung}", geloescht=termin.to_dict(), id=termin.id
        )


def build_kalender_tools(client: KalenderClient) -> list[Tool]:
    return [
        TermineAnsehenTool(client),
        TerminErstellenTool(client),
        TerminAendernTool(client),
        TerminLoeschenTool(client),
    ]
