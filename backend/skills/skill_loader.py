"""Skill Loader – lädt Skills dynamisch zur Laufzeit.

Skills werden dynamisch geladen; der Kern muss dafür nicht neu gebaut oder
neu gestartet werden. Skills können jederzeit aktiviert und deaktiviert
werden.

Jeder Skill kommuniziert ausschließlich über die Skill-API mit dem
Cognitive Core – direkte Systemzugriffe sind nicht vorgesehen und werden
vom Validator beanstandet.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from backend.skills.skill_registry import SkillManifest
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class SkillApi:
    """Die einzige Schnittstelle, über die ein Skill mit AI-Orb spricht.

    Ein Skill erhält beim Laden genau eine Instanz dieser Klasse. Er kann
    darüber Erinnerungen ablegen, Ereignisse melden und protokollieren –
    aber nur im Rahmen seiner erteilten Berechtigungen.
    """

    def __init__(
        self,
        skill_name: str,
        granted_permissions: list[str],
        *,
        memory: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self.skill_name = skill_name
        self._granted = set(granted_permissions)
        self._memory = memory
        self._event_bus = event_bus
        self._logger = get_logger(f"skill.{skill_name}")

    def has_permission(self, permission: str) -> bool:
        """Prüft, ob dem Skill eine Berechtigung erteilt wurde."""

        return permission in self._granted

    def require_permission(self, permission: str) -> None:
        """Stellt sicher, dass eine Berechtigung vorliegt.

        Raises:
            PermissionError: Wenn die Berechtigung fehlt.
        """

        if permission not in self._granted:
            raise PermissionError(
                f"Der Skill '{self.skill_name}' besitzt die Berechtigung "
                f"'{permission}' nicht."
            )

    def log(self, message: str) -> None:
        """Schreibt eine Meldung in das Skill-Log."""

        self._logger.info(message)

    def remember(self, content: str, *, tags: list[str] | None = None) -> bool:
        """Legt eine Information im Gedächtnis ab (falls erlaubt)."""

        if self._memory is None:
            return False
        record = self._memory.remember(
            content,
            tags=[*(tags or []), f"skill:{self.skill_name}"],
            source=f"skill:{self.skill_name}",
        )
        return record is not None

    async def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        """Veröffentlicht ein Ereignis über den Event Bus."""

        if self._event_bus is not None:
            await self._event_bus.publish(
                f"skill.{self.skill_name}.{event_name}", payload
            )


class LoadedSkill:
    """Ein geladener, einsatzbereiter Skill."""

    def __init__(self, manifest: SkillManifest, module: Any, api: SkillApi) -> None:
        self.manifest = manifest
        self.module = module
        self.api = api
        self._instance: Any | None = None

    async def setup(self) -> None:
        """Ruft die optionale ``setup``-Funktion des Skills auf."""

        factory = getattr(self.module, "create_skill", None)
        if callable(factory):
            self._instance = factory(self.api)
        setup = getattr(self._instance or self.module, "setup", None)
        if callable(setup):
            result = setup()
            if hasattr(result, "__await__"):
                await result

    async def teardown(self) -> None:
        """Ruft die optionale ``teardown``-Funktion des Skills auf."""

        teardown = getattr(self._instance or self.module, "teardown", None)
        if callable(teardown):
            result = teardown()
            if hasattr(result, "__await__"):
                await result

    async def invoke(self, capability: str, payload: dict[str, Any]) -> Any:
        """Ruft eine Fähigkeit des Skills auf.

        Der Skill muss eine Funktion ``handle_<capability>`` oder eine
        allgemeine Funktion ``handle`` bereitstellen.
        """

        target = self._instance or self.module
        handler = getattr(target, f"handle_{capability}", None) or getattr(
            target, "handle", None
        )
        if not callable(handler):
            raise AttributeError(
                f"Der Skill '{self.manifest.name}' stellt keine Funktion für "
                f"'{capability}' bereit."
            )
        result = handler(payload)
        if hasattr(result, "__await__"):
            result = await result
        return result


class SkillLoader:
    """Lädt und entlädt Skills zur Laufzeit."""

    def __init__(self, memory: Any | None = None, event_bus: Any | None = None) -> None:
        self._memory = memory
        self._event_bus = event_bus
        self._loaded: dict[str, LoadedSkill] = {}

    async def load(
        self, manifest: SkillManifest, skill_path: Path, granted_permissions: list[str]
    ) -> LoadedSkill:
        """Lädt einen Skill dynamisch.

        Raises:
            ImportError: Wenn das Modul nicht geladen werden kann.
        """

        entrypoint = skill_path / manifest.entrypoint
        module_name = f"ai_orb_skill_{manifest.name}"

        spec = importlib.util.spec_from_file_location(module_name, entrypoint)
        if spec is None or spec.loader is None:
            raise ImportError(f"Skill '{manifest.name}' konnte nicht geladen werden.")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        api = SkillApi(
            manifest.name,
            granted_permissions,
            memory=self._memory,
            event_bus=self._event_bus,
        )
        skill = LoadedSkill(manifest, module, api)
        await skill.setup()

        self._loaded[manifest.name] = skill
        logger.info("Skill geladen: %s %s", manifest.name, manifest.version)
        return skill

    async def unload(self, name: str) -> bool:
        """Entlädt einen Skill."""

        skill = self._loaded.pop(name, None)
        if skill is None:
            return False
        await skill.teardown()
        sys.modules.pop(f"ai_orb_skill_{name}", None)
        logger.info("Skill entladen: %s", name)
        return True

    def get(self, name: str) -> LoadedSkill | None:
        """Gibt einen geladenen Skill zurück."""

        return self._loaded.get(name)

    def loaded_names(self) -> list[str]:
        """Namen aller geladenen Skills."""

        return sorted(self._loaded)
