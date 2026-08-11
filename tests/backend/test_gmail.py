"""Tests des Gmail-Agenten.

Der Schwerpunkt liegt auf der einen Regel, die alles ueberstimmt
(Abschnitt 36): Der Orb sendet niemals ungefragt. Getestet wird nicht, ob
das Sprachmodell sich daran haelt - das koennte es umgehen -, sondern dass
der Ablauf es technisch unmoeglich macht:

  - Ohne Entwurf kein Senden.
  - Ohne Zustimmung kein Senden.
  - Nach dem Senden sendet ein zweites "ja" nichts noch einmal.
  - Verweigerte Zustimmung laesst den Entwurf stehen, sendet aber nicht.

Kein Test spricht ein echtes Postfach an. Der Transport ist eine Attrappe;
was "gesendet" wird, landet in einer Liste, nicht im Internet.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from backend.agents.gmail_agent import GmailAgent
from backend.integrations.gmail.client import GmailClient
from backend.integrations.gmail.oauth import GmailAuth, OAuthConfig, Token


class _FakeTransport:
    """Ein Gmail, das nur mitschreibt - nichts verlaesst den Rechner."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.drafts: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def request(self, method, url, *, token, body):
        if method == "POST" and url.endswith("/drafts"):
            self._counter += 1
            draft_id = f"entwurf-{self._counter}"
            self.drafts[draft_id] = body["message"]
            return {"id": draft_id}
        if method == "POST" and url.endswith("/drafts/send"):
            draft_id = body["id"]
            if draft_id not in self.drafts:
                raise AssertionError("Ein unbekannter Entwurf wurde gesendet!")
            self.sent.append(draft_id)
            return {"id": f"nachricht-{draft_id}"}
        if method == "DELETE":
            return {}
        if method == "GET" and "/messages" in url:
            return {"messages": []}
        return {}


class _FakeSecurity:
    """Eine Sicherheitsschicht, die man auf Ja oder Nein stellt."""

    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.asked: list[str] = []

    async def require(self, actor, permission, detail, *, context=None):
        self.asked.append(permission)

        class _Entscheidung:
            allowed = self.allow
            reason = "erlaubt" if self.allow else "vom Benutzer abgelehnt"

        return _Entscheidung()


def _agent(*, allow_send: bool) -> tuple[GmailAgent, _FakeTransport, _FakeSecurity]:
    auth = GmailAuth(
        OAuthConfig(client_id="test-id", client_secret="test-geheim"),
        token_path=_tmp_token(),
    )
    # Ein gueltiges Token vortaeuschen, damit is_ready wahr ist.
    auth._token = Token(
        access_token="a", refresh_token="r", expires_at=time.time() + 3600
    )
    transport = _FakeTransport()
    client = GmailClient(auth, transport=transport)
    security = _FakeSecurity(allow_send)
    agent = GmailAgent(security, auth=auth, client=client)
    return agent, transport, security


_token_counter = [0]


def _tmp_token():
    import tempfile
    from pathlib import Path

    _token_counter[0] += 1
    return Path(tempfile.mkdtemp()) / f"token-{_token_counter[0]}.json"


# ---------------------------------------------------------------------------
#  Die Sendesperre
# ---------------------------------------------------------------------------


def test_senden_ohne_entwurf_geht_nicht():
    agent, transport, _ = _agent(allow_send=True)
    ergebnis = asyncio.run(agent.confirm_and_send())
    assert not ergebnis["ok"]
    assert not transport.sent, "Es wurde ohne Entwurf gesendet!"


def test_entwurf_allein_sendet_nichts():
    agent, transport, security = _agent(allow_send=True)
    asyncio.run(agent.prepare_draft(to="a@b.de", subject="Test", body="Hallo"))
    assert not transport.sent, "Ein Entwurf allein hat schon gesendet!"
    assert "send_email" not in security.asked, "Beim Entwurf wurde schon gefragt."


def test_senden_braucht_zustimmung():
    agent, transport, security = _agent(allow_send=False)
    asyncio.run(agent.prepare_draft(to="a@b.de", subject="Test", body="Hallo"))
    ergebnis = asyncio.run(agent.confirm_and_send())

    assert not ergebnis["gesendet"]
    assert not transport.sent, "Trotz Ablehnung wurde gesendet!"
    assert "send_email" in security.asked, "Es wurde gar nicht um Erlaubnis gefragt."


def test_abgelehnter_entwurf_bleibt_erhalten():
    agent, transport, _ = _agent(allow_send=False)
    asyncio.run(agent.prepare_draft(to="a@b.de", subject="Test", body="Hallo"))
    asyncio.run(agent.confirm_and_send())

    # Der Entwurf ist noch da - der Benutzer hat vielleicht nur gezoegert.
    assert agent._pending_draft_id, "Der abgelehnte Entwurf wurde verworfen."


def test_vollstaendiger_ablauf_sendet_genau_einmal():
    agent, transport, security = _agent(allow_send=True)

    entwurf = asyncio.run(
        agent.prepare_draft(to="a@b.de", subject="Test", body="Hallo")
    )
    assert entwurf["ok"] and not transport.sent

    ergebnis = asyncio.run(agent.confirm_and_send())
    assert ergebnis["gesendet"]
    assert len(transport.sent) == 1

    # Ein zweites "ja" darf nichts noch einmal senden.
    nochmal = asyncio.run(agent.confirm_and_send())
    assert not nochmal["ok"]
    assert len(transport.sent) == 1, "Ein zweites Ja hat erneut gesendet!"


def test_verwerfen_loescht_den_entwurf():
    agent, transport, _ = _agent(allow_send=True)
    asyncio.run(agent.prepare_draft(to="a@b.de", subject="Test", body="Hallo"))
    ergebnis = asyncio.run(agent.discard_draft())

    assert ergebnis["ok"]
    assert not agent._pending_draft_id
    assert not transport.sent


def test_send_email_ist_kritisch():
    """Eine kritische Erlaubnis kann nie dauerhaft gemerkt werden."""

    from backend.security.permissions import RiskLevel, get_permission

    permission = get_permission("send_email")
    assert permission is not None
    assert permission.risk is RiskLevel.CRITICAL
    assert not permission.remembering_allowed


# ---------------------------------------------------------------------------
#  Anmeldung und Einrichtung
# ---------------------------------------------------------------------------


def test_ohne_einrichtung_kein_zugriff():
    auth = GmailAuth(OAuthConfig(client_id=""), token_path=_tmp_token())
    agent = GmailAgent(_FakeSecurity(True), auth=auth)
    assert not agent.is_ready
    ergebnis = asyncio.run(
        agent.prepare_draft(to="a@b.de", subject="x", body="y")
    )
    assert not ergebnis["ok"]


def test_token_wird_nicht_im_klartext_gespeichert(monkeypatch):
    """Ein Token ist ein Postfachzugang - es darf nicht offen herumliegen."""

    monkeypatch.setenv("AI_ORB_ENCRYPTION_KEY", "ein-schluessel")
    pfad = _tmp_token()
    auth = GmailAuth(OAuthConfig(client_id="x"), token_path=pfad)
    auth._save_token(
        Token(
            access_token="geheim-abc",
            refresh_token="geheim-xyz",
            expires_at=time.time() + 3600,
        )
    )

    roh = pfad.read_bytes()
    assert b"geheim-abc" not in roh, "Das Token liegt im Klartext auf der Platte!"
    assert roh.startswith(b"ENC1:")

    # Es muss sich aber wieder lesen lassen.
    auth2 = GmailAuth(OAuthConfig(client_id="x"), token_path=pfad)
    assert auth2.access_token() == "geheim-abc"
