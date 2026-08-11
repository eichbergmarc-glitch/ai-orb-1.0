"""Werkzeuge für Gmail – lesen, suchen, antworten, senden.

Der Gmail-Agent war vollständig gebaut: Anmeldung, Postfach lesen, suchen,
Entwurf anlegen, vorlesen, bestätigen, senden – samt Sicherheitsschicht für
den einen kritischen Schritt. Erreichbar war er nie. Er hing am
Agenten-Team, und das wird von keiner Stelle beauftragt. Zugangsdaten
eingerichtet, alles fertig, und trotzdem konnte der Orb keine einzige Mail
lesen.

Diese Werkzeuge schliessen ihn an, ohne den Umweg über das Agenten-Team.

Der Ablauf beim Senden ist der Kern und bleibt unangetastet: **Entwurf
anlegen → vorlesen → der Benutzer bestätigt → senden.** Es gibt bewusst
kein Werkzeug, das in einem Zug schreibt und abschickt. Eine Mail lässt
sich nicht zurückholen; zwischen 'schreib meiner Chefin ab' und einer
tatsächlich verschickten Mail gehört ein Moment, in dem jemand widersprechen
kann.

Deshalb hält der Agent immer nur *einen* wartenden Entwurf, und nach dem
Senden ist er weg – ein späteres 'ja' kann so nichts ein zweites Mal
verschicken.
"""

from __future__ import annotations

from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


def _nicht_bereit(bericht: dict[str, Any]) -> ToolResult:
    """Übersetzt die Antwort eines nicht angemeldeten Agenten."""

    return ToolResult.failure(
        str(bericht.get("hinweis") or bericht.get("fehler") or
            "Gmail ist nicht verbunden. Sag 'Melde mich bei Gmail an.'")
    )


class ReadMailTool(Tool):
    """Liest die ungelesenen Mails."""

    name = "mails_lesen"
    description = (
        "Holt die ungelesenen E-Mails aus dem Postfach und gibt Absender, "
        "Betreff und einen Auszug zurueck. Benutze das bei 'habe ich neue "
        "Mails', 'was ist im Postfach', 'lies mir meine Mails vor'."
    )
    permission = "read_email"
    parameters = (
        ToolParameter(
            "anzahl",
            "integer",
            "Wie viele Mails höchstens.",
            required=False,
            default=5,
        ),
    )

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not self._agent.is_ready:
            return _nicht_bereit(self._agent.status())

        anzahl = max(1, min(25, int(arguments.get("anzahl", 5))))
        try:
            mails = await self._agent.read_unread(limit=anzahl)
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Das Postfach ließ sich nicht lesen.")
            return ToolResult.failure(f"Das Postfach ließ sich nicht lesen: {fehler}")

        if not mails:
            return ToolResult.success("Es liegt nichts Ungelesenes im Postfach.", anzahl=0)

        zeilen = [mail.for_reading_aloud() for mail in mails]
        return ToolResult.success(
            f"{len(mails)} ungelesene Mail(s):\n\n" + "\n\n".join(zeilen),
            anzahl=len(mails),
            ids=[mail.id for mail in mails],
        )


class SearchMailTool(Tool):
    """Sucht im Postfach."""

    name = "mails_suchen"
    description = (
        "Durchsucht das Postfach nach einem Stichwort, einem Absender oder "
        "einem Betreff. Benutze das bei 'such die Mail von ...', 'was hat X "
        "geschrieben', 'finde die Mail ueber ...'."
    )
    permission = "read_email"
    parameters = (
        ToolParameter("suche", "string", "Wonach gesucht wird."),
        ToolParameter(
            "anzahl", "integer", "Wie viele Treffer höchstens.",
            required=False, default=10,
        ),
    )

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not self._agent.is_ready:
            return _nicht_bereit(self._agent.status())

        suche = str(arguments["suche"]).strip()
        if not suche:
            return ToolResult.failure("Es fehlt, wonach gesucht werden soll.")

        anzahl = max(1, min(25, int(arguments.get("anzahl", 10))))
        try:
            mails = await self._agent.search(suche, limit=anzahl)
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Die Suche ist gescheitert.")
            return ToolResult.failure(f"Die Suche ist gescheitert: {fehler}")

        if not mails:
            return ToolResult.success(f"Zu '{suche}' ist nichts im Postfach.", anzahl=0)

        zeilen = [mail.for_reading_aloud() for mail in mails]
        return ToolResult.success(
            f"{len(mails)} Treffer zu '{suche}':\n\n" + "\n\n".join(zeilen),
            anzahl=len(mails),
        )


class DraftMailTool(Tool):
    """Legt einen Entwurf an – und sendet ausdrücklich nicht."""

    name = "mail_entwerfen"
    description = (
        "Schreibt eine E-Mail und legt sie als Entwurf an. Sie wird NICHT "
        "gesendet. Lies dem Benutzer danach vor, an wen sie geht, wie der "
        "Betreff lautet und was drinsteht, und frage, ob du senden sollst. "
        "Erst wenn er zustimmt, benutze 'mail_senden'."
    )
    permission = "read_email"
    parameters = (
        ToolParameter("an", "string", "Die Empfängeradresse."),
        ToolParameter("betreff", "string", "Der Betreff."),
        ToolParameter("text", "string", "Der Text der Mail."),
        ToolParameter(
            "antwort_auf",
            "string",
            "Die Kennung der Mail, auf die geantwortet wird.",
            required=False,
            default="",
        ),
    )

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not self._agent.is_ready:
            return _nicht_bereit(self._agent.status())

        an = str(arguments["an"]).strip()
        if "@" not in an:
            return ToolResult.failure(
                f"'{an}' sieht nicht nach einer E-Mail-Adresse aus."
            )

        try:
            bericht = await self._agent.prepare_draft(
                to=an,
                subject=str(arguments["betreff"]).strip(),
                body=str(arguments["text"]),
                reply_to_id=str(arguments.get("antwort_auf", "") or ""),
            )
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Der Entwurf ließ sich nicht anlegen.")
            return ToolResult.failure(f"Der Entwurf ließ sich nicht anlegen: {fehler}")

        if not bericht.get("ok"):
            return ToolResult.failure(
                str(bericht.get("fehler") or bericht.get("hinweis") or "Unbekannter Fehler.")
            )

        vorschau = bericht.get("vorschau") or {}
        return ToolResult.success(
            "Der Entwurf ist angelegt und noch NICHT gesendet.\n"
            f"An: {vorschau.get('an', '')}\n"
            f"Betreff: {vorschau.get('betreff', '')}\n\n"
            f"{vorschau.get('text', '')}\n\n"
            "Lies das dem Benutzer vor und frage, ob du senden sollst.",
            entwurf_id=bericht.get("entwurf_id", ""),
        )


class SendMailTool(Tool):
    """Sendet den wartenden Entwurf."""

    name = "mail_senden"
    description = (
        "Sendet den zuvor angelegten Entwurf ab. Benutze das AUSSCHLIESSLICH, "
        "nachdem du dem Benutzer den Entwurf vorgelesen hast und er "
        "ausdrücklich zugestimmt hat. Ohne vorheriges 'mail_entwerfen' gibt "
        "es nichts zu senden."
    )
    permission = "send_email"
    parameters = ()

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not self._agent.is_ready:
            return _nicht_bereit(self._agent.status())

        try:
            bericht = await self._agent.confirm_and_send()
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Das Senden ist gescheitert.")
            return ToolResult.failure(f"Das Senden ist gescheitert: {fehler}")

        if not bericht.get("ok"):
            return ToolResult.failure(
                str(bericht.get("fehler") or bericht.get("hinweis") or
                    "Es wartet kein Entwurf.")
            )

        return ToolResult.success(str(bericht.get("hinweis") or "Die Mail ist unterwegs."))


class DiscardDraftTool(Tool):
    """Verwirft den wartenden Entwurf."""

    name = "entwurf_verwerfen"
    description = (
        "Verwirft den wartenden E-Mail-Entwurf. Benutze das, wenn der "
        "Benutzer die Mail doch nicht senden will oder sie neu schreiben "
        "möchte."
    )
    permission = "read_email"
    parameters = ()

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            bericht = await self._agent.discard_draft()
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Das Verwerfen ist gescheitert: {fehler}")

        if not bericht.get("ok"):
            return ToolResult.failure(str(bericht.get("hinweis") or "Es wartet kein Entwurf."))
        return ToolResult.success(str(bericht.get("hinweis") or "Der Entwurf ist verworfen."))


class GmailLoginTool(Tool):
    """Beginnt die Anmeldung bei Gmail."""

    name = "gmail_anmelden"
    description = (
        "Startet die Anmeldung bei Gmail und nennt dem Benutzer, was er tun "
        "muss. Benutze das bei 'melde mich bei Gmail an' oder wenn ein "
        "Mail-Werkzeug meldet, dass keine Verbindung besteht."
    )
    permission = "read_email"
    parameters = ()

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            bericht = self._agent.begin_login()
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Die Anmeldung ließ sich nicht starten.")
            return ToolResult.failure(f"Die Anmeldung ließ sich nicht starten: {fehler}")

        text = str(
            bericht.get("hinweis")
            or bericht.get("anweisung")
            or bericht.get("fehler")
            or "Die Anmeldung wurde angestossen."
        )
        return ToolResult.success(text, **{k: v for k, v in bericht.items() if k != "hinweis"})


def build_gmail_tools(agent: Any) -> list[Tool]:
    """Stellt die Gmail-Werkzeuge zusammen."""

    return [
        ReadMailTool(agent),
        SearchMailTool(agent),
        DraftMailTool(agent),
        SendMailTool(agent),
        DiscardDraftTool(agent),
        GmailLoginTool(agent),
    ]
