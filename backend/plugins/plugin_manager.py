"""Verwaltung der Plugins.

Ein Plugin ist fremder Code, der im selben Prozess läuft. Python kann ihn
nicht wirklich einsperren – wer ``import os`` schreibt, hat Zugriff auf das
Dateisystem, gleichgültig was in seinem Manifest steht. Diese Grenze wird
hier offen benannt, statt sie mit einer Scheinabsicherung zu verdecken.

Was stattdessen geschieht, ist dreierlei:

**Vor dem Laden wird gefragt.** Ein Plugin wird nur geladen, wenn der
Benutzer es ausdrücklich freigegeben hat, und ihm werden dabei die
verlangten Berechtigungen im Klartext gezeigt. Der Vorgang steht im
Prüfprotokoll.

**Werkzeuge werden begrenzt.** Ein Plugin darf nur Werkzeuge anmelden, deren
Berechtigung in seinem Manifest steht. Alles andere wird abgewiesen. Und da
jeder Werkzeugaufruf über die Sicherheitsschicht läuft, kann ein Plugin auf
diesem Weg nichts tun, was nicht freigegeben wurde.

**Fehler bleiben örtlich.** Ein abstürzendes Plugin wird entladen, nicht
mitgerissen. Der Kern läuft weiter.

Wer ein Plugin aus unbekannter Quelle installiert, lädt fremden Code auf
seinen Rechner. Diesen Satz zeigt AI-Orb dem Benutzer vor der Freigabe.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.config import get_config
from backend.events.event_bus import EventBus
from backend.events import event_types
from backend.plugins.plugin_base import OrbPlugin, PluginContext
from backend.plugins.plugin_manifest import (
    MANIFEST_FILENAME,
    ManifestProblem,
    PluginManifest,
    parse_manifest,
)
from backend.security.permissions import describe
from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool
from backend.tools.registry import ToolRegistry
from backend.utils.paths import get_bundled_plugins_dir, get_data_dir, get_plugins_dir

logger = get_logger(__name__)


@dataclass
class LoadedPlugin:
    """Ein geladenes Plugin samt seinem Zustand."""

    manifest: PluginManifest
    instance: OrbPlugin
    tools: list[str] = field(default_factory=list)
    #: Paare aus Ereignisname und Horcher, damit beim Entladen genau die
    #: eigenen Horcher abgemeldet werden können und keine fremden.
    subscriptions: list[tuple[str, Callable[..., Any]]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = self.manifest.to_dict()
        data["loaded"] = True
        data["tools"] = list(self.tools)
        data["subscriptions"] = [name for name, _ in self.subscriptions]
        try:
            data["info"] = self.instance.info()
        except Exception:  # noqa: BLE001
            data["info"] = {}
        return data


class PluginManager:
    """Findet, prüft, lädt und entlädt Plugins."""

    def __init__(
        self,
        *,
        security: SecurityEngine,
        tool_registry: ToolRegistry,
        event_bus: EventBus,
        orb_version: str = "",
    ) -> None:
        config = get_config()

        self._security = security
        self._tools = tool_registry
        self._event_bus = event_bus
        self._orb_version = orb_version

        # Zwei Orte: die mitgelieferten Beispiele im Programmordner und die
        # eigenen im Benutzerordner. Getrennt, damit ein Update eigene
        # Plugins nicht überschreibt und die Beispiele nicht verdoppelt.
        self._directory = get_plugins_dir()
        self._bundled_directory = get_bundled_plugins_dir()
        self._require_confirmation = bool(config.get("plugins.require_confirmation", True))
        self._auto_load = bool(config.get("plugins.auto_load", False))

        self._loaded: dict[str, LoadedPlugin] = {}
        self._problems: dict[str, list[str]] = {}

    @property
    def directory(self) -> Path:
        """Wo die Plugins liegen."""

        return self._directory

    # --- Finden --------------------------------------------------------------------

    def discover(self) -> list[PluginManifest]:
        """Sucht Plugins und prüft ihre Manifeste.

        Fehlerhafte Plugins werden nicht stillschweigend übergangen; ihre
        Beanstandungen sind über :meth:`problems` abrufbar.
        """

        found: list[PluginManifest] = []
        self._problems.clear()

        # Eigene Plugins zuerst: Trägt eines denselben Namen wie ein
        # mitgeliefertes, gilt das eigene.
        candidates: list[Path] = []
        seen_names: set[str] = set()

        for directory in (self._directory, self._bundled_directory):
            if not directory.is_dir():
                continue
            for entry in sorted(directory.iterdir()):
                if entry.is_dir() and entry.name not in seen_names:
                    seen_names.add(entry.name)
                    candidates.append(entry)

        for entry in candidates:
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue

            if not (entry / MANIFEST_FILENAME).is_file():
                self._problems[entry.name] = [f"Es fehlt die Datei {MANIFEST_FILENAME}."]
                continue

            manifest, problems = parse_manifest(entry)
            if manifest is None:
                self._problems[entry.name] = [str(problem) for problem in problems]
                logger.warning(
                    "Das Plugin '%s' wurde abgelehnt: %s",
                    entry.name,
                    "; ".join(str(problem) for problem in problems),
                )
                continue

            found.append(manifest)

        return found

    def problems(self) -> dict[str, list[str]]:
        """Die Beanstandungen der zuletzt gefundenen Plugins."""

        return dict(self._problems)

    def review(self, manifest: PluginManifest) -> dict[str, Any]:
        """Bereitet die Freigabeansicht eines Plugins auf.

        Das ist, was der Benutzer vor der Zustimmung zu sehen bekommt.
        """

        evaluation = self._security.evaluate_manifest(manifest.permissions)
        return {
            "plugin": manifest.to_dict(),
            "permissions": evaluation["permissions"],
            "installable": evaluation["installable"],
            "summary": evaluation["summary"],
            "warning": (
                "Ein Plugin ist fremder Programmcode, der in AI-Orb mitläuft. "
                "Lade nur Plugins, deren Herkunft du kennst."
            ),
        }

    # --- Laden ---------------------------------------------------------------------

    async def load(self, name: str, *, ask: bool | None = None) -> tuple[bool, str]:
        """Lädt ein Plugin.

        Args:
            name: Der Pluginname aus dem Manifest.
            ask: Ob gefragt wird. ``None`` nimmt die Konfiguration.

        Returns:
            Erfolg und eine Begründung im Klartext.
        """

        key = name.strip().lower()

        if key in self._loaded:
            return True, f"Das Plugin '{key}' ist bereits geladen."

        manifest = next((item for item in self.discover() if item.name == key), None)
        if manifest is None:
            beanstandungen = self._problems.get(key)
            if beanstandungen:
                return False, f"Das Plugin '{key}' ist fehlerhaft: " + "; ".join(beanstandungen)
            return False, f"Ein Plugin namens '{key}' gibt es nicht in {self._directory}."

        evaluation = self._security.evaluate_manifest(manifest.permissions)
        if not evaluation["installable"]:
            return False, str(evaluation["summary"])

        should_ask = self._require_confirmation if ask is None else ask
        if should_ask:
            described = describe(manifest.permissions)
            listing = ", ".join(str(entry["description"]) for entry in described) or "keine besonderen"
            decision = await self._security.require(
                f"plugin:{key}",
                "system_commands" if "system_commands" in manifest.permissions else "read_files",
                f"Das Plugin '{manifest.name}' {manifest.version} laden. "
                f"Es verlangt: {listing}. Ein Plugin ist fremder Programmcode, "
                "der in AI-Orb mitläuft.",
                context={"plugin": manifest.to_dict()},
            )
            if not decision.allowed:
                return False, f"Das Plugin wurde nicht geladen: {decision.reason}"

        return await self._load_module(manifest)

    async def _load_module(self, manifest: PluginManifest) -> tuple[bool, str]:
        """Importiert die Plugindatei und startet das Plugin."""

        assert manifest.directory is not None
        entry_file = manifest.directory / manifest.entry_point

        module_name = f"ai_orb_plugin_{manifest.name}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, entry_file)
            if spec is None or spec.loader is None:
                return False, f"Die Datei '{manifest.entry_point}' ließ sich nicht laden."

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as error:  # noqa: BLE001 - fremder Code, jeder Fehler ist möglich.
            sys.modules.pop(module_name, None)
            logger.error(
                "Das Plugin '%s' ließ sich nicht laden:\n%s",
                manifest.name,
                traceback.format_exc(limit=5),
            )
            return False, f"Das Plugin ist beim Laden gescheitert: {error}"

        plugin_class = getattr(module, "Plugin", None)
        if plugin_class is None or not isinstance(plugin_class, type) or not issubclass(plugin_class, OrbPlugin):
            sys.modules.pop(module_name, None)
            return False, (
                f"In '{manifest.entry_point}' fehlt eine Klasse 'Plugin', die von "
                "OrbPlugin erbt."
            )

        loaded = LoadedPlugin(manifest=manifest, instance=None)  # type: ignore[arg-type]
        context = self._build_context(manifest, loaded)

        try:
            instance = plugin_class(context)
            loaded.instance = instance
            await instance.setup()
        except Exception as error:  # noqa: BLE001
            self._tools.unregister_source(f"plugin:{manifest.name}")
            sys.modules.pop(module_name, None)
            logger.error(
                "Das Plugin '%s' ist beim Start gescheitert:\n%s",
                manifest.name,
                traceback.format_exc(limit=5),
            )
            return False, f"Das Plugin ist beim Start gescheitert: {error}"

        self._loaded[manifest.name] = loaded
        self._security.record_action(
            f"plugin:{manifest.name}",
            "read_files",
            f"Plugin '{manifest.name}' {manifest.version} geladen.",
            context={"tools": loaded.tools},
        )
        await self._event_bus.publish(
            event_types.PLUGIN_LOADED,
            {"plugin": manifest.name, "version": manifest.version, "tools": loaded.tools},
        )

        logger.info(
            "Plugin '%s' %s geladen (%d Werkzeuge).",
            manifest.name,
            manifest.version,
            len(loaded.tools),
        )
        return True, (
            f"Das Plugin '{manifest.name}' ist geladen"
            + (f" und stellt bereit: {', '.join(loaded.tools)}." if loaded.tools else ".")
        )

    def _build_context(self, manifest: PluginManifest, loaded: LoadedPlugin) -> PluginContext:
        """Baut die Umgebung, die das Plugin bekommt."""

        source = f"plugin:{manifest.name}"
        data_directory = get_data_dir() / "plugins" / manifest.name
        data_directory.mkdir(parents=True, exist_ok=True)

        def register_tool(tool: Tool) -> bool:
            # Ein Plugin darf nur Werkzeuge anmelden, deren Berechtigung es
            # im Manifest angegeben hat. Sonst könnte es sich zur Laufzeit
            # Rechte nehmen, die der Benutzer nie gesehen hat.
            if tool.permission not in manifest.permissions:
                logger.warning(
                    "Das Plugin '%s' wollte das Werkzeug '%s' mit der "
                    "Berechtigung '%s' anmelden, hat sie aber nicht im "
                    "Manifest angegeben. Abgewiesen.",
                    manifest.name,
                    tool.name,
                    tool.permission,
                )
                return False

            accepted = self._tools.register(tool, source=source)
            if accepted:
                loaded.tools.append(tool.name)
            return accepted

        def subscribe(event_name: str, handler: Callable[..., Any]) -> None:
            self._event_bus.subscribe(event_name, handler)
            loaded.subscriptions.append((event_name, handler))

        def log(message: str) -> None:
            logger.info("[%s] %s", manifest.name, message)

        return PluginContext(
            name=manifest.name,
            directory=manifest.directory or self._directory / manifest.name,
            data_directory=data_directory,
            permissions=list(manifest.permissions),
            register_tool=register_tool,
            subscribe=subscribe,
            log=log,
            orb_version=self._orb_version,
        )

    # --- Entladen -------------------------------------------------------------------

    async def unload(self, name: str) -> tuple[bool, str]:
        """Entlädt ein Plugin und entfernt seine Werkzeuge."""

        key = name.strip().lower()
        loaded = self._loaded.get(key)
        if loaded is None:
            return False, f"Das Plugin '{key}' ist nicht geladen."

        try:
            await loaded.instance.teardown()
        except Exception:  # noqa: BLE001 - ein Fehler beim Aufräumen darf nicht blockieren.
            logger.exception("Das Plugin '%s' ist beim Aufräumen gescheitert.", key)

        removed = self._tools.unregister_source(f"plugin:{key}")

        for event_name, handler in loaded.subscriptions:
            try:
                self._event_bus.unsubscribe(event_name, handler)
            except Exception:  # noqa: BLE001 - beim Aufräumen wird nichts erzwungen.
                logger.debug("Ereignishorcher '%s' ließ sich nicht abmelden.", event_name)

        sys.modules.pop(f"ai_orb_plugin_{key}", None)
        self._loaded.pop(key, None)

        await self._event_bus.publish(event_types.PLUGIN_UNLOADED, {"plugin": key})
        logger.info("Plugin '%s' entladen (%d Werkzeuge entfernt).", key, removed)
        return True, f"Das Plugin '{key}' ist entladen."

    async def load_enabled(self) -> int:
        """Lädt beim Start alle Plugins, die im Manifest freigeschaltet sind.

        Nur wenn ``plugins.auto_load`` in der Konfiguration gesetzt ist.
        Andernfalls geschieht beim Start bewusst nichts – fremder Code soll
        nicht ungefragt mitlaufen.

        Returns:
            Wie viele geladen wurden.
        """

        if not self._auto_load:
            candidates = [item.name for item in self.discover() if item.enabled]
            if candidates:
                logger.info(
                    "Diese Plugins sind vorhanden, werden aber nicht automatisch "
                    "geladen (plugins.auto_load ist aus): %s",
                    ", ".join(candidates),
                )
            return 0

        count = 0
        for manifest in self.discover():
            if not manifest.enabled:
                continue
            ok, message = await self.load(manifest.name, ask=self._require_confirmation)
            if ok:
                count += 1
            else:
                logger.warning("Plugin '%s' nicht geladen: %s", manifest.name, message)
        return count

    async def unload_all(self) -> int:
        """Entlädt alle Plugins. Wird beim Herunterfahren aufgerufen."""

        names = list(self._loaded)
        for name in names:
            await self.unload(name)
        return len(names)

    # --- Auskunft ---------------------------------------------------------------------

    def loaded(self) -> list[dict[str, Any]]:
        """Die geladenen Plugins."""

        return [plugin.to_dict() for plugin in self._loaded.values()]

    def catalog(self) -> list[dict[str, Any]]:
        """Alle gefundenen Plugins, geladen oder nicht."""

        entries: list[dict[str, Any]] = []
        for manifest in self.discover():
            entry = manifest.to_dict()
            entry["loaded"] = manifest.name in self._loaded
            if entry["loaded"]:
                entry["tools"] = self._loaded[manifest.name].tools
            entries.append(entry)

        for name, beanstandungen in self._problems.items():
            entries.append(
                {"name": name, "loaded": False, "broken": True, "problems": beanstandungen}
            )

        return entries

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "directory": str(self._directory),
            "bundled_directory": str(self._bundled_directory),
            "loaded": list(self._loaded),
            "available": [manifest.name for manifest in self.discover()],
            "broken": self.problems(),
            "auto_load": self._auto_load,
            "require_confirmation": self._require_confirmation,
        }
