"""Zustimmungsverwaltung.

Heikle Aktionen führt AI-Orb erst aus, wenn der Benutzer zugestimmt hat. Die
Frage wird als Ereignis an die Oberfläche geschickt; der Orb wechselt in den
wartenden Zustand und die Aktion pausiert, bis eine Antwort kommt.

Drei Gestaltungsentscheidungen sind hier wichtig:

Erstens gilt **Schweigen als Nein**. Läuft die Frist ab, wird verweigert.
Ein Benutzer, der nicht am Rechner sitzt, soll nicht dadurch zustimmen, dass
er nichts tut.

Zweitens darf eine Zustimmung **gemerkt** werden, aber nur wenn der Benutzer
das ausdrücklich wählt und die Berechtigung es zulässt. Kritische Aktionen –
Löschen, Systembefehle, Übertragung von Quellcode – sind jedes Mal neu zu
bestätigen.

Drittens ist jede gemerkte Zustimmung **jederzeit widerrufbar**, einzeln
oder vollständig.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.events.event_bus import EventBus
from backend.security.permissions import Permission, get_permission
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)


@dataclass
class ConsentRequest:
    """Eine offene Frage an den Benutzer."""

    request_id: str
    actor: str
    permission: str
    #: Was genau geschehen soll – im Klartext, ohne Fachbegriffe.
    detail: str
    risk: str
    remembering_allowed: bool
    created_at: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "actor": self.actor,
            "permission": self.permission,
            "detail": self.detail,
            "risk": self.risk,
            "remembering_allowed": self.remembering_allowed,
            "created_at": self.created_at,
            "context": self.context,
        }


@dataclass
class ConsentDecision:
    """Die Antwort auf eine Frage."""

    granted: bool
    #: Warum – bei Verweigerung für die Rückmeldung an den Benutzer.
    reason: str = ""
    #: Ob die Entscheidung gemerkt wurde.
    remembered: bool = False


#: Ereignisnamen der Zustimmungsverwaltung.
CONSENT_REQUESTED = "security.consent.requested"
CONSENT_RESOLVED = "security.consent.resolved"
CONSENT_REVOKED = "security.consent.revoked"


class ConsentManager:
    """Fragt den Benutzer und merkt sich Entscheidungen, wenn erlaubt."""

    def __init__(
        self,
        event_bus: EventBus,
        *,
        timeout_seconds: float = 120.0,
        store_filename: str = "security/consents.json",
    ) -> None:
        """
        Args:
            event_bus: Über ihn wird gefragt und geantwortet.
            timeout_seconds: Wie lange auf eine Antwort gewartet wird.
            store_filename: Wo gemerkte Zustimmungen liegen.
        """

        self._event_bus = event_bus
        self._timeout = max(10.0, timeout_seconds)
        self._store = JsonStore(store_filename, default={"granted": {}})
        self._pending: dict[str, asyncio.Future[ConsentDecision]] = {}
        self._requests: dict[str, ConsentRequest] = {}

    # --- Gemerkte Zustimmungen -------------------------------------------------

    def _key(self, actor: str, permission: str) -> str:
        return f"{actor}::{permission}"

    def is_remembered(self, actor: str, permission: str) -> bool:
        """Ob für diesen Aufrufer und diese Berechtigung schon zugestimmt wurde."""

        granted: dict[str, Any] = self._store.get("granted", {}) or {}
        return bool(granted.get(self._key(actor, permission)))

    def remember(self, actor: str, permission: str) -> None:
        """Merkt eine Zustimmung dauerhaft."""

        granted: dict[str, Any] = dict(self._store.get("granted", {}) or {})
        granted[self._key(actor, permission)] = {
            "actor": actor,
            "permission": permission,
            "granted_at": time.time(),
        }
        self._store.set("granted", granted)
        logger.info("Zustimmung gemerkt: %s darf '%s'.", actor, permission)

    def revoke(self, actor: str, permission: str) -> bool:
        """Nimmt eine gemerkte Zustimmung zurück.

        Returns:
            ``True``, wenn es etwas zurückzunehmen gab.
        """

        granted: dict[str, Any] = dict(self._store.get("granted", {}) or {})
        removed = granted.pop(self._key(actor, permission), None)
        if removed is None:
            return False
        self._store.set("granted", granted)
        logger.info("Zustimmung widerrufen: %s darf '%s' nicht mehr.", actor, permission)
        return True

    def revoke_all(self) -> int:
        """Nimmt alle gemerkten Zustimmungen zurück.

        Returns:
            Wie viele zurückgenommen wurden.
        """

        granted: dict[str, Any] = self._store.get("granted", {}) or {}
        count = len(granted)
        self._store.set("granted", {})
        logger.info("Alle %d gemerkten Zustimmungen widerrufen.", count)
        return count

    def remembered(self) -> list[dict[str, Any]]:
        """Alle gemerkten Zustimmungen, für die Anzeige."""

        granted: dict[str, Any] = self._store.get("granted", {}) or {}
        entries = []
        for value in granted.values():
            permission = get_permission(str(value.get("permission", "")))
            entries.append(
                {
                    "actor": value.get("actor", ""),
                    "permission": value.get("permission", ""),
                    "description": permission.description if permission else "",
                    "granted_at": value.get("granted_at", 0.0),
                }
            )
        return sorted(entries, key=lambda item: item["actor"])

    # --- Fragen ------------------------------------------------------------------

    async def request(
        self,
        actor: str,
        permission: Permission,
        detail: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ConsentDecision:
        """Fragt den Benutzer um Zustimmung.

        Args:
            actor: Wer fragt – Modul, Skill, Plugin oder Agent.
            permission: Die verlangte Berechtigung.
            detail: Was genau geschehen soll, im Klartext.
            context: Zusatzangaben für die Anzeige.

        Returns:
            Die Entscheidung. Bei Zeitüberschreitung eine Verweigerung.
        """

        if permission.remembering_allowed and self.is_remembered(actor, permission.name):
            return ConsentDecision(True, "Bereits erteilt", remembered=True)

        request = ConsentRequest(
            request_id=uuid.uuid4().hex[:12],
            actor=actor,
            permission=permission.name,
            detail=detail,
            risk=permission.risk.value,
            remembering_allowed=permission.remembering_allowed,
            context=context or {},
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[ConsentDecision] = loop.create_future()
        self._pending[request.request_id] = future
        self._requests[request.request_id] = request

        await self._event_bus.publish(CONSENT_REQUESTED, request.to_dict())
        logger.info(
            "Zustimmung angefragt (%s): %s möchte '%s' – %s",
            request.request_id,
            actor,
            permission.name,
            detail,
        )

        try:
            decision = await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            decision = ConsentDecision(
                False,
                "Es kam keine Antwort. Ohne ausdrückliche Zustimmung wird nicht "
                "gehandelt.",
            )
        except asyncio.CancelledError:
            self._pending.pop(request.request_id, None)
            self._requests.pop(request.request_id, None)
            raise
        finally:
            self._pending.pop(request.request_id, None)

        self._requests.pop(request.request_id, None)

        await self._event_bus.publish(
            CONSENT_RESOLVED,
            {
                "request_id": request.request_id,
                "granted": decision.granted,
                "reason": decision.reason,
            },
        )
        return decision

    def resolve(
        self,
        request_id: str,
        granted: bool,
        *,
        remember: bool = False,
        reason: str = "",
    ) -> bool:
        """Beantwortet eine offene Frage.

        Wird von der Oberfläche über den API-Endpunkt aufgerufen.

        Args:
            request_id: Die Kennung aus der Frage.
            granted: Ob zugestimmt wird.
            remember: Ob die Zustimmung gemerkt werden soll.
            reason: Optionale Begründung bei Ablehnung.

        Returns:
            ``True``, wenn die Frage noch offen war.
        """

        future = self._pending.get(request_id)
        request = self._requests.get(request_id)
        if future is None or future.done() or request is None:
            return False

        remembered = False
        if granted and remember and request.remembering_allowed:
            self.remember(request.actor, request.permission)
            remembered = True

        decision = ConsentDecision(
            granted=granted,
            reason=reason or ("Zugestimmt" if granted else "Vom Benutzer abgelehnt"),
            remembered=remembered,
        )
        future.get_loop().call_soon_threadsafe(
            lambda: None if future.done() else future.set_result(decision)
        )
        return True

    def pending(self) -> list[dict[str, Any]]:
        """Die derzeit offenen Fragen."""

        return [request.to_dict() for request in self._requests.values()]

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "pending": len(self._requests),
            "remembered": len(self._store.get("granted", {}) or {}),
            "timeout_seconds": self._timeout,
        }
