"""Der Gmail-Agent (Master-Prompt Abschnitte 35, 36, 46).

Hier laufen zwei Dinge zusammen, die getrennt gebaut wurden: der
Gmail-Client, der lesen und senden kann, und die Sicherheitsschicht, die
über das Senden wacht. Der Agent ist die Stelle, an der die Regel aus
Abschnitt 36 durchgesetzt wird – nicht als Bitte, sondern als Ablauf:

    Entwurf  →  Vorlesen  →  Benutzer bestätigt  →  Senden

Ohne Entwurf kein Senden. Ohne Bestätigung kein Senden. Die Bestätigung
holt der Agent über die Sicherheitsschicht ein, dieselbe, die auch das
Mikrofon oder Systembefehle absichert – und ``send_email`` ist dort als
kritisch eingestuft, kann also nie stillschweigend „für immer erlaubt“
werden.

## Warum das Senden nicht im Client sitzt

Der Client *kann* senden, er *entscheidet* aber nicht, ob er darf. Diese
Trennung ist Absicht: Eine Sicherheitsregel, die an zwei Stellen steht,
läuft irgendwann auseinander. Sie hat genau einen Ort, und das ist dieser
Agent.
"""

from __future__ import annotations

import webbrowser
from typing import Any

from backend.agents.base_agent import AgentResult, AgentTask, BaseAgent
from backend.integrations.gmail.client import GmailClient, GmailError, GmailMessage
from backend.integrations.gmail.oauth import GmailAuth, GmailAuthError
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class GmailAgent(BaseAgent):
    """Liest, sucht, fasst zusammen und versendet E-Mails – Letzteres nur mit Zustimmung."""

    name = "email"
    description = "Gmail: Mails lesen, suchen, zusammenfassen, vorlesen, beantworten, senden"
    capabilities = ("email_lesen", "email_senden", "email_suchen", "internet")
    requires_llm = False
    system_prompt = (
        "Du verwaltest die E-Mails des Benutzers über Gmail. Du sendest "
        "niemals ungefragt: Erst entsteht ein Entwurf, den der Benutzer hört "
        "und ausdrücklich freigibt."
    )

    def __init__(self, security: Any, *, auth: GmailAuth | None = None, client: GmailClient | None = None) -> None:
        super().__init__()
        self._security = security
        self._auth = auth or GmailAuth()
        self._client = client or GmailClient(self._auth)

        #: Der zuletzt angelegte Entwurf, der auf Bestätigung wartet.
        #:
        #: Genau einer. Ein zweiter „Sende die Mail“-Befehl ohne neuen
        #: Entwurf bezieht sich immer auf diesen – und nach dem Senden ist
        #: er weg, damit ein späteres „ja“ nicht versehentlich noch einmal
        #: sendet.
        self._pending_draft_id = ""
        self._pending_summary = ""

        #: Die laufende Anmeldung: (verifier, redirect_uri).
        #:
        #: Ohne dieses Gedaechtnis ist der Rueckweg tot. Google schickt den
        #: Einmalcode an den lokalen Server zurueck, und der Tausch gegen
        #: das Token braucht den PKCE-Pruefwert aus Schritt eins. Am
        #: 17.08.2026 stand der Benutzer mit dem Code im Browser - und
        #: niemand nahm ihn an: begin_login gab den Pruefwert zurueck, aber
        #: keiner hob ihn auf, und die Callback-Route gab es gar nicht.
        self._pending_login: tuple[str, str] | None = None

    # --- Zustand --------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """Ob Gmail eingerichtet und angemeldet ist."""

        return self._auth.config.is_configured and self._auth.is_authenticated

    def status(self) -> dict[str, Any]:
        return {
            "eingerichtet": self._auth.config.is_configured,
            "angemeldet": self._auth.is_authenticated,
            "offener_entwurf": bool(self._pending_draft_id),
        }

    # --- Lesen ----------------------------------------------------------------

    async def read_unread(self, *, limit: int = 5) -> list[GmailMessage]:
        await self._require_read("Ungelesene E-Mails abrufen")
        return self._client.unread(limit=limit)

    async def search(self, text: str, *, limit: int = 10) -> list[GmailMessage]:
        await self._require_read(f"E-Mails durchsuchen: {text}")
        return self._client.search(text, limit=limit)

    # --- Der geschützte Sendeweg ----------------------------------------------

    async def prepare_draft(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        reply_to_id: str = "",
        thread_id: str = "",
    ) -> dict[str, Any]:
        """Legt einen Entwurf an und hält ihn zur Bestätigung bereit.

        Das Anlegen selbst ist harmlos und braucht keine kritische
        Zustimmung – gesendet wird nichts. Der Entwurf wird zurückgegeben,
        damit der Orb ihn dem Benutzer vorlesen kann, bevor irgendetwas das
        Postfach verlässt.
        """

        if not self.is_ready:
            return self._not_ready()

        try:
            draft_id = self._client.create_draft(
                to=to, subject=subject, body=body,
                reply_to_id=reply_to_id, thread_id=thread_id,
            )
        except (GmailError, GmailAuthError) as error:
            return {"ok": False, "fehler": str(error)}

        self._pending_draft_id = draft_id
        self._pending_summary = f"an {to}, Betreff „{subject}“"

        return {
            "ok": True,
            "entwurf_id": draft_id,
            "vorschau": {
                "an": to,
                "betreff": subject,
                "text": body,
            },
            "hinweis": (
                "Der Entwurf ist angelegt, aber NICHT gesendet. Lies ihn dem "
                "Benutzer vor und frage, ob du senden sollst."
            ),
        }

    async def confirm_and_send(self) -> dict[str, Any]:
        """Sendet den wartenden Entwurf – nach ausdrücklicher Zustimmung.

        Dies ist die einzige Stelle im ganzen System, die eine Mail
        tatsächlich losschickt. Sie tut es nur, wenn drei Dinge zutreffen:
        Es gibt einen Entwurf, die Sicherheitsschicht erteilt die kritische
        Erlaubnis ``send_email``, und beides bezieht sich auf genau diesen
        Entwurf.
        """

        if not self._pending_draft_id:
            return {
                "ok": False,
                "fehler": "Es gibt keinen Entwurf zum Senden. Lege zuerst einen an.",
            }

        # Die kritische Erlaubnis. Sie kann nicht dauerhaft gemerkt werden
        # (kritische Rechte nie), also wird jedes einzelne Senden gefragt.
        decision = await self._security.require(
            self.name,
            "send_email",
            f"Eine E-Mail senden ({self._pending_summary}).",
            context={"entwurf": self._pending_draft_id},
        )

        if not decision.allowed:
            # Der Entwurf bleibt bestehen – der Benutzer hat vielleicht nur
            # zögert, nicht abgelehnt. Verworfen wird nur auf Ansage.
            return {
                "ok": False,
                "gesendet": False,
                "grund": decision.reason,
                "hinweis": "Der Entwurf bleibt erhalten.",
            }

        draft_id = self._pending_draft_id
        try:
            message_id = self._client.send_draft(draft_id)
        except (GmailError, GmailAuthError) as error:
            return {"ok": False, "fehler": str(error)}
        finally:
            # In jedem Fall vergessen: Ein zweites „ja“ darf nicht noch
            # einmal senden.
            self._pending_draft_id = ""
            self._pending_summary = ""

        return {"ok": True, "gesendet": True, "nachricht_id": message_id}

    async def discard_draft(self) -> dict[str, Any]:
        """Verwirft den wartenden Entwurf."""

        if not self._pending_draft_id:
            return {"ok": True, "hinweis": "Es gab keinen Entwurf."}

        draft_id = self._pending_draft_id
        self._pending_draft_id = ""
        self._pending_summary = ""

        try:
            self._client.delete_draft(draft_id)
        except (GmailError, GmailAuthError) as error:
            return {"ok": False, "fehler": str(error)}

        return {"ok": True, "verworfen": True}

    # --- Anmeldung ------------------------------------------------------------

    def begin_login(self) -> dict[str, Any]:
        """Startet die einmalige Anmeldung im Browser (Abschnitt 35).

        Der eigentliche Loopback-Empfang liegt bewusst nicht hier, sondern
        wird vom Launcher gestartet, der ohnehin einen lokalen Port
        verwaltet. Dieser Agent stellt die URL bereit und öffnet sie – die
        Anmeldung ist eine Sache zwischen Benutzer und Google.
        """

        if not self._auth.config.is_configured:
            return {
                "ok": False,
                "fehler": (
                    "Gmail ist nicht eingerichtet. Es fehlt GMAIL_CLIENT_ID in "
                    "der .env. Wie man eine anlegt, steht in docs/GMAIL.md."
                ),
            }

        # Ein fester Loopback-Port, den der Benutzer bei Google als
        # Weiterleitungsziel einträgt.
        redirect_uri = "http://127.0.0.1:8756/gmail/callback"
        url, verifier = self._auth.build_authorization_url(redirect_uri)

        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - ein fehlender Browser ist kein Absturz.
            logger.info("Konnte den Browser nicht öffnen; URL wird nur angezeigt.")

        # Fuer den Rueckweg aufheben: Der Callback-Empfaenger braucht den
        # Pruefwert, um den Einmalcode gegen das Token zu tauschen.
        self._pending_login = (verifier, redirect_uri)

        return {
            "ok": True,
            "url": url,
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "hinweis": "Melde dich im Browser bei Google an und erteile die Erlaubnis.",
        }

    def complete_login(self, code: str) -> dict[str, Any]:
        """Schliesst die Anmeldung ab: tauscht den Einmalcode gegen das Token.

        Wird vom lokalen Server gerufen, sobald Google den Browser auf
        ``/gmail/callback`` zurueckschickt. Erst mit diesem Schritt ist die
        Anmeldung wirklich geschehen - alles davor war nur die Erlaubnis.
        """

        if not code.strip():
            return {"ok": False, "fehler": "Es kam kein Anmeldecode an."}
        if self._pending_login is None:
            return {
                "ok": False,
                "fehler": (
                    "Es laeuft gerade keine Anmeldung. Sage zuerst "
                    "„Melde mich bei Gmail an“."
                ),
            }

        verifier, redirect_uri = self._pending_login
        try:
            token = self._auth.exchange_code(code.strip(), redirect_uri, verifier)
        except Exception as fehler:  # noqa: BLE001 - der Grund gehoert in die Antwort.
            logger.exception("Der Tausch des Anmeldecodes ist fehlgeschlagen.")
            return {"ok": False, "fehler": f"Google hat den Code nicht angenommen: {fehler}"}

        # Erst nach dem Erfolg vergessen: Schlaegt der Tausch fehl (etwa
        # weil der Benutzer die Seite neu laedt), darf er es mit derselben
        # Anmeldung noch einmal versuchen.
        self._pending_login = None

        mit_kalender = "calendar" in (token.scope or "")
        logger.info(
            "Google-Anmeldung abgeschlossen (Kalender: %s).",
            "ja" if mit_kalender else "nein",
        )
        return {"ok": True, "kalender": mit_kalender}

    def logout(self) -> dict[str, Any]:
        """Meldet ab und löscht das Token."""

        return {"ok": self._auth.forget()}

    # --- Agentenschnittstelle -------------------------------------------------

    async def handle(self, task: AgentTask) -> AgentResult:
        """Führt eine Absicht aus, die der Orchestrator übergibt.

        Die konkrete Absicht steht in ``task.metadata['gmail']`` – der
        Orchestrator hat aus dem Gesagten bereits erkannt, was zu tun ist.
        Ohne Absicht liefert der Agent seinen Status; das ist der Fall,
        wenn jemand allgemein „meine Mails“ sagt.
        """

        intent = (task.metadata or {}).get("gmail", {})
        action = str(intent.get("aktion", "status"))

        try:
            data = await self._dispatch(action, intent, task)
        except (GmailError, GmailAuthError) as error:
            return AgentResult(
                agent=self.name, success=False, error=str(error), response=str(error)
            )

        return AgentResult(
            agent=self.name,
            response=data.get("_text", ""),
            data=data,
            success=bool(data.get("ok", True)),
        )

    async def _dispatch(self, action: str, intent: dict[str, Any], task: AgentTask) -> dict[str, Any]:
        if action == "senden_bestaetigen":
            return await self.confirm_and_send()
        if action == "verwerfen":
            return await self.discard_draft()
        if action == "anmelden":
            return self.begin_login()
        if action == "abmelden":
            return self.logout()

        if not self.is_ready:
            return self._not_ready()

        if action == "entwurf":
            return await self.prepare_draft(
                to=str(intent.get("an", "")),
                subject=str(intent.get("betreff", "")),
                body=str(intent.get("text", "")),
                reply_to_id=str(intent.get("antwort_auf", "")),
                thread_id=str(intent.get("thread", "")),
            )
        if action == "suchen":
            mails = await self.search(str(intent.get("suchbegriff", "")), limit=int(intent.get("anzahl", 10)))
            return {"ok": True, "mails": [m.to_dict() for m in mails]}
        if action == "ungelesen":
            mails = await self.read_unread(limit=int(intent.get("anzahl", 5)))
            return {"ok": True, "mails": [m.to_dict() for m in mails]}

        return {"ok": True, "status": self.status()}

    # --- Hilfen ---------------------------------------------------------------

    async def _require_read(self, detail: str) -> None:
        decision = await self._security.require(self.name, "read_email", detail)
        if not decision.allowed:
            raise GmailError(decision.reason)

    def _not_ready(self) -> dict[str, Any]:
        if not self._auth.config.is_configured:
            return {
                "ok": False,
                "fehler": "Gmail ist nicht eingerichtet (GMAIL_CLIENT_ID fehlt).",
            }
        return {
            "ok": False,
            "fehler": "Gmail ist nicht angemeldet. Sage „Melde mich bei Gmail an“.",
        }
