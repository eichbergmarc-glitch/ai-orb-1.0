"""Capability Registry – wer kann was?

Verwaltet, welcher Agent welche Fähigkeit besitzt, welche APIs verfügbar
sind und welche Berechtigungen bestehen. Der Agent Router nutzt dieses
Verzeichnis, um Aufgaben nur an dafür vorgesehene Agenten zu geben.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from backend.agents.base_agent import BaseAgent
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Berechtigungen, die ein Agent oder Skill besitzen kann.
PERMISSIONS: tuple[str, ...] = (
    "file_read",
    "file_write",
    "internet",
    "browser_control",
    "microphone",
    "camera",
    "system_commands",
    "database",
    "screen_capture",
)


@dataclass
class CapabilityEntry:
    """Eine registrierte Fähigkeit."""

    capability: str
    provider: str
    kind: str = "agent"
    permissions: list[str] = field(default_factory=list)
    api: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "provider": self.provider,
            "kind": self.kind,
            "permissions": self.permissions,
            "api": self.api,
        }


class CapabilityRegistry:
    """Verzeichnis aller Fähigkeiten und Berechtigungen."""

    def __init__(self) -> None:
        self._entries: dict[str, list[CapabilityEntry]] = {}
        self._granted: dict[str, set[str]] = {}
        self._lock = threading.RLock()

    def register_agent(self, agent: BaseAgent, permissions: list[str] | None = None) -> None:
        """Registriert alle Fähigkeiten eines Agenten."""

        for capability in agent.capabilities:
            self.register(
                capability,
                provider=agent.name,
                kind="agent",
                permissions=permissions or [],
                api=f"agents.{agent.name}.handle",
            )

    def register(
        self,
        capability: str,
        *,
        provider: str,
        kind: str = "agent",
        permissions: list[str] | None = None,
        api: str = "",
    ) -> CapabilityEntry:
        """Registriert eine einzelne Fähigkeit."""

        entry = CapabilityEntry(
            capability=capability,
            provider=provider,
            kind=kind,
            permissions=list(permissions or []),
            api=api,
        )
        with self._lock:
            self._entries.setdefault(capability, [])
            existing = [
                item for item in self._entries[capability] if item.provider == provider
            ]
            if not existing:
                self._entries[capability].append(entry)
        return entry

    def unregister_provider(self, provider: str) -> int:
        """Entfernt alle Fähigkeiten eines Anbieters (z. B. eines Skills)."""

        removed = 0
        with self._lock:
            for capability, entries in list(self._entries.items()):
                keep = [entry for entry in entries if entry.provider != provider]
                removed += len(entries) - len(keep)
                if keep:
                    self._entries[capability] = keep
                else:
                    self._entries.pop(capability, None)
            self._granted.pop(provider, None)
        return removed

    def providers_for(self, capability: str) -> list[str]:
        """Alle Anbieter, die eine Fähigkeit bereitstellen."""

        with self._lock:
            return [entry.provider for entry in self._entries.get(capability, [])]

    def has(self, capability: str) -> bool:
        """Ob eine Fähigkeit überhaupt verfügbar ist."""

        with self._lock:
            return bool(self._entries.get(capability))

    def capabilities_of(self, provider: str) -> list[str]:
        """Alle Fähigkeiten eines Anbieters."""

        with self._lock:
            return sorted(
                capability
                for capability, entries in self._entries.items()
                if any(entry.provider == provider for entry in entries)
            )

    # --- Berechtigungen -------------------------------------------------------

    def grant(self, provider: str, permission: str) -> bool:
        """Erteilt einem Anbieter eine Berechtigung.

        Returns:
            ``False``, wenn die Berechtigung unbekannt ist.
        """

        if permission not in PERMISSIONS:
            logger.warning("Unbekannte Berechtigung angefragt: %s", permission)
            return False
        with self._lock:
            self._granted.setdefault(provider, set()).add(permission)
        logger.info("Berechtigung '%s' an '%s' erteilt.", permission, provider)
        return True

    def revoke(self, provider: str, permission: str) -> None:
        """Entzieht eine Berechtigung."""

        with self._lock:
            self._granted.get(provider, set()).discard(permission)
        logger.info("Berechtigung '%s' von '%s' entzogen.", permission, provider)

    def is_allowed(self, provider: str, permission: str) -> bool:
        """Prüft, ob ein Anbieter eine Berechtigung besitzt."""

        with self._lock:
            return permission in self._granted.get(provider, set())

    def permissions_of(self, provider: str) -> list[str]:
        """Alle einem Anbieter erteilten Berechtigungen."""

        with self._lock:
            return sorted(self._granted.get(provider, set()))

    def snapshot(self) -> dict[str, Any]:
        """Vollständige Übersicht für die Transparenzansicht."""

        with self._lock:
            return {
                "capabilities": {
                    capability: [entry.to_dict() for entry in entries]
                    for capability, entries in self._entries.items()
                },
                "permissions": {
                    provider: sorted(permissions)
                    for provider, permissions in self._granted.items()
                },
            }
