"""Skill Manager – die zentrale Schnittstelle des Skill-Systems.

Der Manager bündelt Registry, Loader, Validator, Berechtigungen,
Installation, Aktualisierung, Dokumentation und Katalog. Er ist die einzige
Stelle, über die das Cognitive Core mit Skills spricht.

Jeder Skill kommuniziert ausschließlich über die Skill-API mit dem
Cognitive Core und dem Orchestrator – direkte Systemzugriffe finden nicht
statt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.skills.skill_documentation import SkillDocumentation
from backend.skills.skill_installer import InstallProposal, SkillInstaller
from backend.skills.skill_loader import SkillLoader
from backend.skills.skill_marketplace import SkillMarketplace
from backend.skills.skill_permissions import SkillPermissions
from backend.skills.skill_registry import SkillRegistry
from backend.skills.skill_updater import SkillUpdater
from backend.skills.skill_validator import SkillValidator
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class SkillManager:
    """Verwaltet alle Skills von AI-Orb."""

    def __init__(
        self,
        *,
        memory: Any | None = None,
        event_bus: Any | None = None,
        capability_registry: Any | None = None,
    ) -> None:
        self.registry = SkillRegistry()
        self.permissions = SkillPermissions()
        self.validator = SkillValidator(self.permissions)
        self.installer = SkillInstaller(self.registry, self.validator, self.permissions)
        self.updater = SkillUpdater(self.registry, self.validator, self.installer)
        self.loader = SkillLoader(memory=memory, event_bus=event_bus)
        self.documentation = SkillDocumentation(self.registry)
        self.marketplace = SkillMarketplace()

        self._capabilities = capability_registry

    # --- Lebenszyklus ---------------------------------------------------------

    async def load_active(self) -> list[str]:
        """Lädt alle als aktiv markierten Skills.

        Wird beim Start aufgerufen. Fehlerhafte Skills werden als
        ``fehlerhaft`` markiert und übersprungen, statt den Start zu
        verhindern.
        """

        loaded: list[str] = []
        for record in self.registry.list():
            if record.status not in ("aktiv", "installiert"):
                continue
            try:
                await self.loader.load(
                    record.manifest, Path(record.path), record.granted_permissions
                )
            except Exception as error:  # noqa: BLE001 - ein Skill darf den Start nicht verhindern.
                logger.exception("Skill '%s' konnte nicht geladen werden.", record.manifest.name)
                self.registry.set_status(record.manifest.name, "fehlerhaft", error=str(error))
                continue

            self.registry.set_status(record.manifest.name, "aktiv")
            self._register_capabilities(record.manifest.name)
            loaded.append(record.manifest.name)

        if loaded:
            logger.info("Aktive Skills geladen: %s", ", ".join(loaded))
        return loaded

    async def activate(self, name: str) -> dict[str, Any]:
        """Aktiviert einen installierten Skill."""

        record = self.registry.get(name)
        if record is None:
            return {"activated": False, "message": f"Kein Skill mit dem Namen „{name}“."}

        try:
            await self.loader.load(record.manifest, Path(record.path), record.granted_permissions)
        except Exception as error:  # noqa: BLE001
            self.registry.set_status(name, "fehlerhaft", error=str(error))
            return {"activated": False, "message": f"Skill konnte nicht geladen werden: {error}"}

        self.registry.set_status(name, "aktiv")
        self._register_capabilities(name)
        self.marketplace.mark_installed(name, True)
        return {"activated": True, "message": f"Skill „{name}“ ist jetzt aktiv."}

    async def deactivate(self, name: str) -> dict[str, Any]:
        """Deaktiviert einen Skill, ohne ihn zu entfernen."""

        await self.loader.unload(name)
        self.registry.set_status(name, "deaktiviert")
        if self._capabilities is not None:
            self._capabilities.unregister_provider(f"skill:{name}")
        return {"deactivated": True, "message": f"Skill „{name}“ wurde deaktiviert."}

    def _register_capabilities(self, name: str) -> None:
        """Meldet die Fähigkeiten eines Skills in der Capability Registry an."""

        record = self.registry.get(name)
        if record is None or self._capabilities is None:
            return
        for capability in record.manifest.capabilities:
            self._capabilities.register(
                capability,
                provider=f"skill:{name}",
                kind="skill",
                permissions=record.granted_permissions,
                api=f"skills.{name}.invoke",
            )
            for permission in record.granted_permissions:
                self._capabilities.grant(f"skill:{name}", permission)

    # --- Installation ----------------------------------------------------------

    def prepare_install(self, source: str | Path) -> InstallProposal:
        """Prüft einen Skill und legt den Installationsvorschlag vor."""

        return self.installer.prepare(source)

    def install(self, proposal: InstallProposal, *, confirmed: bool = False) -> dict[str, Any]:
        """Installiert einen Skill nach Bestätigung."""

        result = self.installer.install(proposal, confirmed=confirmed)
        if result.get("installed"):
            self.marketplace.mark_installed(proposal.manifest.name, True)
        return result

    async def uninstall(self, name: str, *, confirmed: bool = False) -> dict[str, Any]:
        """Entfernt einen Skill vollständig."""

        await self.loader.unload(name)
        result = self.installer.uninstall(name, confirmed=confirmed)
        if result.get("removed"):
            self.marketplace.mark_installed(name, False)
            if self._capabilities is not None:
                self._capabilities.unregister_provider(f"skill:{name}")
        return result

    # --- Berechtigungen ---------------------------------------------------------

    def grant(self, name: str, permission: str) -> dict[str, Any]:
        """Erteilt einem Skill eine Berechtigung."""

        if self.registry.get(name) is None:
            return {"granted": False, "message": f"Kein Skill mit dem Namen „{name}“."}
        self.registry.grant(name, permission)
        if self._capabilities is not None:
            self._capabilities.grant(f"skill:{name}", permission)
        return {
            "granted": True,
            "message": f"Der Skill „{name}“ darf jetzt: {permission}.",
        }

    def revoke(self, name: str, permission: str) -> dict[str, Any]:
        """Entzieht einem Skill eine Berechtigung."""

        self.registry.revoke(name, permission)
        if self._capabilities is not None:
            self._capabilities.revoke(f"skill:{name}", permission)
        return {"revoked": True, "message": f"Berechtigung „{permission}“ wurde entzogen."}

    # --- Aufrufe ------------------------------------------------------------------

    def has_capability(self, capability: str) -> bool:
        """Ob ein aktiver Skill eine bestimmte Fähigkeit bereitstellt."""

        for record in self.registry.active():
            if capability in record.manifest.capabilities:
                return self.loader.get(record.manifest.name) is not None
        return False

    async def invoke(self, capability: str, payload: dict[str, Any]) -> Any:
        """Ruft eine Fähigkeit auf, die von einem Skill bereitgestellt wird.

        Raises:
            LookupError: Wenn kein aktiver Skill die Fähigkeit anbietet.
        """

        for record in self.registry.active():
            if capability not in record.manifest.capabilities:
                continue
            skill = self.loader.get(record.manifest.name)
            if skill is None:
                continue
            return await skill.invoke(capability, payload)

        raise LookupError(f"Keine aktive Fähigkeit '{capability}' gefunden.")

    # --- Transparenz ----------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Übersicht über alle Skills."""

        return {
            "installed": self.registry.snapshot(),
            "loaded": self.loader.loaded_names(),
            "permissions": self.permissions.describe_all(),
            "catalog_categories": self.marketplace.categories(),
            "skills_directory": str(self.installer.skills_directory),
        }

    def suggest(self, activity: str) -> list[dict[str, Any]]:
        """Schlägt passende, noch nicht installierte Skills vor."""

        return [entry.to_dict() for entry in self.marketplace.suggest_for(activity)]
