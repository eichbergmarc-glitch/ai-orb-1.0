"""Der Gmail-Client (Master-Prompt Abschnitt 35).

Spricht die Gmail-REST-API an: auflisten, suchen, lesen, Entwurf anlegen,
senden. Bewusst mit der stdlib (``urllib``) und ohne die offizielle
Google-Bibliothek – dieselbe Beschränkung wie im ganzen Projekt, und die
Gmail-API ist gewöhnliches REST über HTTPS, für das keine Bibliothek nötig
ist.

## Der einschleusbare Transport

Alle Netzaufrufe laufen durch ``self._transport``. Im Betrieb ist das eine
dünne ``urllib``-Hülle; im Test wird eine Attrappe eingesetzt. Das ist
keine Spielerei: Ein E-Mail-Client, den man nur mit einem echten Postfach
prüfen kann, wird nicht geprüft – und ausgerechnet die Sendesperre, das
Sicherheitskritischste hier, muss prüfbar sein, ohne dass eine echte Mail
das Haus verlässt.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Callable, Protocol

from backend.integrations.gmail.oauth import GmailAuth
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class Transport(Protocol):
    """Was der Client zum Sprechen braucht – eine einzige Methode."""

    def request(
        self, method: str, url: str, *, token: str, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        ...


class UrllibTransport:
    """Der echte Transport über ``urllib``."""

    def request(
        self, method: str, url: str, *, token: str, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": f"Bearer {token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:400]
            raise GmailError(f"Gmail antwortete mit {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise GmailError(f"Gmail nicht erreichbar: {error}") from error


@dataclass(slots=True)
class GmailMessage:
    """Eine E-Mail in der Form, die AI-Orb braucht."""

    id: str
    thread_id: str = ""
    sender: str = ""
    recipient: str = ""
    subject: str = ""
    snippet: str = ""
    body: str = ""
    date: str = ""
    unread: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "von": self.sender,
            "an": self.recipient,
            "betreff": self.subject,
            "auszug": self.snippet,
            "datum": self.date,
            "ungelesen": self.unread,
        }

    def for_reading_aloud(self) -> str:
        """Die Mail so, wie der Orb sie vorlesen würde (Abschnitt 35).

        Kein Header-Wust, keine Zitatgeschichte – nur, was ein Mensch hören
        will: von wem, worum es geht, und der Text.
        """

        wer = self.sender.split("<")[0].strip() or self.sender
        text = _strip_quoted(self.body or self.snippet)
        return f"Von {wer}. Betreff: {self.subject}. {text}".strip()


class GmailClient:
    """Liest und versendet E-Mails über die Gmail-API."""

    def __init__(self, auth: GmailAuth, *, transport: Transport | None = None) -> None:
        self._auth = auth
        self._transport = transport or UrllibTransport()

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._auth.access_token()
        url = path if path.startswith("http") else f"{_API_BASE}{path}"
        return self._transport.request(method, url, token=token, body=body)

    # --- Lesen ----------------------------------------------------------------

    def list_messages(self, *, query: str = "", limit: int = 10) -> list[GmailMessage]:
        """Listet Mails auf, optional nach einer Suchanfrage (Abschnitt 35).

        ``query`` ist die normale Gmail-Suchsyntax: ``from:``, ``subject:``,
        ``is:unread``, ``after:``. So kann der Orb „ungelesene von Anna aus
        dieser Woche“ als eine Anfrage stellen.
        """

        params = {"maxResults": max(1, min(limit, 50))}
        if query:
            params["q"] = query

        listing = self._call("GET", f"/messages?{urllib.parse.urlencode(params)}")
        ids = [entry["id"] for entry in (listing.get("messages") or [])]

        return [self.get_message(msg_id) for msg_id in ids[:limit]]

    def get_message(self, message_id: str) -> GmailMessage:
        """Holt eine einzelne Mail vollständig."""

        data = self._call("GET", f"/messages/{message_id}?format=full")
        return _parse_message(data)

    def search(self, text: str, *, limit: int = 10) -> list[GmailMessage]:
        """Freie Suche über den Volltext (Abschnitt 35)."""

        return self.list_messages(query=text, limit=limit)

    def unread(self, *, limit: int = 10) -> list[GmailMessage]:
        return self.list_messages(query="is:unread", limit=limit)

    # --- Schreiben ------------------------------------------------------------

    def create_draft(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        reply_to_id: str = "",
        thread_id: str = "",
    ) -> str:
        """Legt einen Entwurf an und gibt dessen ID zurück (Abschnitt 36).

        Das Anlegen eines Entwurfs ist harmlos – er verlässt das Postfach
        nicht. Deshalb ist dies der einzige Weg, auf dem Text zu einer Mail
        wird: Erst steht ein Entwurf, dann – und nur nach Bestätigung –
        wird er gesendet.
        """

        raw = _build_raw(to=to, subject=subject, body=body, reply_to_id=reply_to_id)
        payload: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id:
            payload["message"]["threadId"] = thread_id

        result = self._call("POST", "/drafts", payload)
        draft_id = str(result.get("id", ""))
        logger.info("Gmail-Entwurf angelegt: %s an %s.", draft_id, to)
        return draft_id

    def send_draft(self, draft_id: str) -> str:
        """Versendet einen bestehenden Entwurf.

        Diese Methode prüft NICHT, ob gesendet werden darf – das ist
        Aufgabe des Agenten, der die Bestätigung des Benutzers einholt.
        Hier zu prüfen und dort noch einmal wäre eine doppelte Schranke,
        die auseinanderlaufen kann. Die Regel „nur mit Bestätigung“ hat
        genau eine Stelle: den Agenten.
        """

        result = self._call("POST", "/drafts/send", {"id": draft_id})
        message_id = str(result.get("id", ""))
        logger.info("Gmail-Entwurf %s versendet (Nachricht %s).", draft_id, message_id)
        return message_id

    def get_draft(self, draft_id: str) -> GmailMessage:
        """Holt einen Entwurf zum Vorlesen vor dem Senden."""

        data = self._call("GET", f"/drafts/{draft_id}?format=full")
        return _parse_message(data.get("message", data))

    def delete_draft(self, draft_id: str) -> None:
        """Verwirft einen Entwurf, den der Benutzer nicht senden will."""

        self._call("DELETE", f"/drafts/{draft_id}")
        logger.info("Gmail-Entwurf %s verworfen.", draft_id)

    def profile(self) -> dict[str, Any]:
        """Wer ist angemeldet – für die Statusanzeige."""

        return self._call("GET", "/profile")


# ---------------------------------------------------------------------------
#  Hilfsfunktionen
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _build_raw(*, to: str, subject: str, body: str, reply_to_id: str = "") -> str:
    """Baut die roh kodierte Mail für die Gmail-API."""

    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if reply_to_id:
        # Verknüpft die Antwort mit dem ursprünglichen Nachrichtenstrang.
        message["In-Reply-To"] = reply_to_id
        message["References"] = reply_to_id
    message.set_content(body)
    return _b64url(message.as_bytes())


def _header(headers: list[dict[str, str]], name: str) -> str:
    lowered = name.lower()
    for entry in headers:
        if entry.get("name", "").lower() == lowered:
            return entry.get("value", "")
    return ""


def _decode_part(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _extract_body(payload: dict[str, Any]) -> str:
    """Holt den Textkörper aus der verschachtelten Gmail-Struktur.

    Bevorzugt wird ``text/plain``. HTML-Mails werden grob entkleidet –
    besser ein lesbarer Rest als eine Wand aus Tags, wenn der Orb es
    vorlesen soll.
    """

    mime = payload.get("mimeType", "")
    body = payload.get("body", {})

    if mime == "text/plain" and body.get("data"):
        return _decode_part(body["data"])

    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text

    if mime == "text/html" and body.get("data"):
        return _strip_html(_decode_part(body["data"]))

    return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_quoted(text: str) -> str:
    """Entfernt zitierte Vorgängernachrichten für das Vorlesen."""

    lines: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith(">"):
            break
        if re.match(r"^\s*Am .+ schrieb .+:", line) or re.match(r"^\s*On .+ wrote:", line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _parse_message(data: dict[str, Any]) -> GmailMessage:
    """Übersetzt die Gmail-Antwort in ein :class:`GmailMessage`."""

    payload = data.get("payload", {})
    headers = payload.get("headers", [])
    label_ids = data.get("labelIds", []) or []

    return GmailMessage(
        id=str(data.get("id", "")),
        thread_id=str(data.get("threadId", "")),
        sender=_header(headers, "From"),
        recipient=_header(headers, "To"),
        subject=_header(headers, "Subject"),
        snippet=str(data.get("snippet", "")),
        body=_extract_body(payload),
        date=_header(headers, "Date"),
        unread="UNREAD" in label_ids,
    )


class GmailError(RuntimeError):
    """Ein Fehler beim Gmail-Zugriff."""
