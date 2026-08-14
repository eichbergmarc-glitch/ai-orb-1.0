"""Kontrollierte Weiterentwicklung von AI-Orb aus dem laufenden Gespräch.

Ein Entwicklungswunsch wird zuerst von einem Modell geplant und als Patch in
einer isolierten Arbeitskopie erzeugt. Erst wenn Pfadschutz, Tests, Review und
Frontend-Prüfung erfolgreich sind, übernimmt die Evolution Engine den Patch.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)

ALLOWED_SUFFIXES = frozenset(
    {".py", ".ts", ".js", ".css", ".html", ".glsl", ".json", ".yaml", ".yml", ".md", ".txt", ".bat"}
)
PROTECTED_PATHS = (
    "backend/security/",
    "backend/evolution/live_development.py",
    "backend/evolution/rollback_manager.py",
    "backend/evolution/release_manager.py",
    "backend/system/restart.py",
    "backend/tools/self_tools.py",
    "backend/tools/development_tools.py",
)
IGNORED_PARTS = frozenset(
    {".git", ".pytest_cache", "__pycache__", "node_modules", "runtime", "models", "logs", "data", "dist", "dist-installer"}
)


@dataclass
class DevelopmentResult:
    ok: bool
    message: str
    files: list[str] = field(default_factory=list)
    patch_id: str = ""
    restore_point: str = ""
    needs_restart: bool = False
    renderer_reloaded: bool = False


def parse_development_request(text: str) -> str | None:
    """Erkennt ausdrückliche Änderungsaufträge an AI-Orb.

    Reine Fragen ("kannst du ...?") lösen keine Codeänderung aus. Ein Auftrag
    braucht ein Umsetzungsverb und ein Ziel aus dem Orb/Programmkontext.
    """

    compact = " ".join(str(text).strip().lower().split())
    if not compact or compact.endswith("?") and not re.search(
        r"\b(implementier|setz|ändere|aendere|pass|beheb|reparier|baue|mach)\w*\b", compact
    ):
        return None
    action = re.search(
        r"\b(implementier\w*|setz\w*|ändere\w*|aendere\w*|pass\w*\s+an|"
        r"beheb\w*|reparier\w*|entwickl\w*|programmier\w*|baue\w*|füg\w*\s+hinzu|"
        r"fueg\w*\s+hinzu|mach\w*)\b",
        compact,
    )
    if action is None:
        action = re.search(
            r"\b(?:ich\s+)?(?:möchte|moechte|will),?\s+dass\b|"
            r"\b(?:der\s+)?orb\s+soll\b",
            compact,
        )
    target = re.search(
        r"\b(orb|dein(?:en|em|er)?\s+code|dich\s+selbst|programm|app|funktion|"
        r"animation|ring|ringe|augen|farbe|stimme|chat|fenster|werkzeug|suche|offline|terminal|"
        r"cmd|powershell|oberfläche|oberflaeche|backend|renderer)\b",
        compact,
    )
    return text.strip() if action and target else None


class LiveDevelopmentService:
    """Erzeugt, prüft und übernimmt einen Entwicklungsauftrag atomar."""

    def __init__(
        self,
        *,
        providers: Any,
        evolution: Any,
        event_bus: Any,
        neustart: Any,
        root: Path | None = None,
    ) -> None:
        self._providers = providers
        self._evolution = evolution
        self._bus = event_bus
        self._neustart = neustart
        self._root = (root or get_project_root()).resolve()
        settings = get_config().section("evolution")
        self._enabled = bool(settings.get("live_development", {}).get("enabled", True))
        live_settings = dict(settings.get("live_development", {}) or {})
        self._allow_cloud = bool(live_settings.get("allow_external_code_transfer", False))
        self._max_files = int(live_settings.get("max_files", 10))
        self._max_context = int(
            live_settings.get("max_context_characters", 100_000)
        )

    async def implement(self, request: str) -> DevelopmentResult:
        if not self._enabled:
            return DevelopmentResult(False, "Der laufende Entwicklungsmodus ist deaktiviert.")
        request = request.strip()
        if not request:
            return DevelopmentResult(False, "Der Entwicklungsauftrag ist leer.")

        provider = getattr(self._providers, "active_provider", None)
        if provider is None:
            return DevelopmentResult(False, "Es ist kein Modell für die Codeentwicklung verfügbar.")
        if not getattr(provider, "is_local", False) and not self._allow_cloud:
            return DevelopmentResult(
                False,
                "Der aktive Anbieter ist online, aber die Übertragung von Quellcode ist in config.yaml gesperrt.",
            )

        await self._publish("planung", request=request)
        try:
            selection = await self._plan(request)
            context = self._source_context(selection)
            diff = await self._generate_diff(request, context)
        except Exception as error:  # noqa: BLE001 - Providerfehler verständlich melden.
            logger.exception("Entwicklungsauftrag konnte nicht erzeugt werden.")
            return DevelopmentResult(False, f"Der Änderungsvorschlag konnte nicht erzeugt werden: {error}")

        await self._publish("patch", request=request)
        try:
            changes = await asyncio.to_thread(self._materialize_diff, diff)
        except ValueError as error:
            return DevelopmentResult(False, f"Der Änderungsvorschlag wurde verworfen: {error}")

        if not changes:
            return DevelopmentResult(False, "Das Modell hat keine tatsächliche Codeänderung erzeugt.")

        title = self._title(request)
        prepared = await asyncio.to_thread(
            self._evolution.prepare_patch,
            title=title,
            description=request,
            changes=changes,
        )
        patch_id = str(prepared.get("id", ""))
        if not patch_id:
            return DevelopmentResult(False, "Die isolierte Arbeitskopie konnte nicht angelegt werden.")

        frontend_error = await asyncio.to_thread(self._frontend_check, prepared)
        if frontend_error:
            self._evolution.discard_patch(patch_id)
            return DevelopmentResult(False, f"Die TypeScript-Prüfung ist fehlgeschlagen: {frontend_error}")

        await self._publish("tests", patch_id=patch_id)
        validation = await asyncio.to_thread(
            self._evolution.validate_patch, patch_id, run_benchmark=False
        )
        if not validation.get("proposable"):
            summary = str(validation.get("summary", "Tests oder Review nicht bestanden."))
            self._evolution.discard_patch(patch_id)
            return DevelopmentResult(False, "Die Änderung wurde nicht übernommen. " + summary[-1800:])

        applied = await asyncio.to_thread(
            self._evolution.apply_patch, patch_id, confirmed=True
        )
        if not applied.get("applied"):
            return DevelopmentResult(False, str(applied.get("message", "Übernahme fehlgeschlagen.")))

        files = [str(item) for item in applied.get("applied_files", [])]
        restore_point = str(applied.get("restore_point", ""))
        runtime_files = [path for path in files if self._needs_activation(path)]
        renderer_only = bool(runtime_files) and all(
            self._is_renderer_hot_reload(path) for path in runtime_files
        )

        if renderer_only:
            build_error = await asyncio.to_thread(self._build_renderer)
            if build_error:
                await asyncio.to_thread(self._evolution.rollback.rollback, restore_point)
                return DevelopmentResult(
                    False,
                    "Der Renderer-Build ist fehlgeschlagen; die Änderung wurde automatisch zurückgenommen. "
                    + build_error,
                )
            await self._bus.publish(
                "orb.oberflaeche.neu_laden", {"grund": "live_entwicklung", "dateien": files}
            )
            await self._publish("fertig", files=files, restart=False)
            return DevelopmentResult(
                True,
                f"Umgesetzt und geprüft: {title}. Die Orb-Oberfläche wurde neu geladen.",
                files=files,
                patch_id=patch_id,
                restore_point=restore_point,
                renderer_reloaded=True,
            )

        if any(path.startswith("desktop/") for path in runtime_files):
            build_error = await asyncio.to_thread(self._build_desktop)
            if build_error:
                await asyncio.to_thread(self._evolution.rollback.rollback, restore_point)
                return DevelopmentResult(
                    False,
                    "Der Desktop-Build ist fehlgeschlagen; die Änderung wurde automatisch zurückgenommen. "
                    + build_error,
                )

        if not runtime_files:
            await self._publish("fertig", files=files, restart=False)
            return DevelopmentResult(
                True,
                f"Umgesetzt und geprüft: {title}. Die Änderung ist sofort wirksam.",
                files=files,
                patch_id=patch_id,
                restore_point=restore_point,
            )

        ok, restart_message = self._neustart.anfordern(f"Entwicklungsauftrag: {title}")
        await self._publish("fertig", files=files, restart=ok)
        message = f"Umgesetzt und geprüft: {title}. " + restart_message
        return DevelopmentResult(
            True,
            message,
            files=files,
            patch_id=patch_id,
            restore_point=restore_point,
            needs_restart=ok,
        )

    async def _plan(self, request: str) -> list[dict[str, Any]]:
        inventory = "\n".join(self._inventory())
        prompt = f"""Entwicklungsauftrag für AI-Orb:
{request}

Wähle höchstens {self._max_files} Dateien, deren Inhalt du zum Erzeugen eines minimalen Patches sehen musst.
Antworte ausschließlich als JSON:
{{"files":[{{"path":"relativer/pfad","search_terms":["KlasseOderBegriff"]}}]}}
Neue Dateien dürfen genannt werden. Keine Abhängigkeiten installieren, keine geschützten Sicherheitsdateien ändern.

Projektdateien:
{inventory}
"""
        raw = await self._providers.complete(
            prompt,
            system_prompt="Du planst eine kleine, testbare Codeänderung. Gib ausschließlich valides JSON zurück.",
            temperature=0.0,
            max_tokens=2500,
        )
        payload = _json_object(raw)
        files = payload.get("files", [])
        if not isinstance(files, list) or not files:
            raise ValueError("Die Dateiplanung war leer.")
        selected: list[dict[str, Any]] = []
        for item in files[: self._max_files]:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).replace("\\", "/").strip(" /")
            self._validate_relative(path)
            terms = [str(term) for term in item.get("search_terms", []) if str(term).strip()]
            selected.append({"path": path, "search_terms": terms[:5]})
        if not selected:
            raise ValueError("Die Dateiplanung enthielt keinen zulässigen Pfad.")
        return selected

    async def _generate_diff(self, request: str, context: str) -> str:
        prompt = f"""Setze diesen Auftrag als minimalen Patch für AI-Orb um:
{request}

Du erhältst relevante Dateien oder Ausschnitte. Erzeuge einen vollständigen Unified Diff, der mit `git apply` anwendbar ist.
Regeln: keine Abhängigkeiten installieren; keine Commits; keine Platzhalter; keine fremden Änderungen zurücksetzen; ergänze passende Tests; ändere höchstens {self._max_files} Dateien. Antworte ausschließlich mit dem Diff ab `diff --git`.

QUELLCONTEXT
{context}
"""
        raw = await self._providers.complete(
            prompt,
            system_prompt="Du bist der vorsichtige Maintainer von AI-Orb. Liefere nur einen anwendbaren Unified Diff.",
            temperature=0.1,
            max_tokens=16_000,
        )
        return _extract_diff(raw)

    def _inventory(self) -> list[str]:
        result: list[str] = []
        for path in self._root.rglob("*"):
            if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
                continue
            relative = path.relative_to(self._root).as_posix()
            if path.suffix.lower() in ALLOWED_SUFFIXES and not self._is_protected(relative):
                result.append(relative)
        return sorted(result)

    def _source_context(self, selection: list[dict[str, Any]]) -> str:
        blocks: list[str] = []
        remaining = self._max_context
        for item in selection:
            relative = item["path"]
            path = self._root / relative
            if not path.exists():
                block = f"===== NEUE DATEI: {relative} =====\n"
            else:
                source = path.read_text(encoding="utf-8", errors="replace")
                if len(source) <= 40_000:
                    body = source
                else:
                    body = _matching_excerpts(source, item.get("search_terms", []))
                block = f"===== {relative} =====\n{body}\n"
            if len(block) > remaining:
                block = block[:remaining]
            blocks.append(block)
            remaining -= len(block)
            if remaining <= 0:
                break
        return "\n".join(blocks)

    def _materialize_diff(self, diff: str) -> dict[str, str]:
        patch_id = "live-" + uuid.uuid4().hex[:10]
        workspace = self._evolution.patches.create_workspace(patch_id)
        self._evolution.patches._ensure_repository(workspace)  # isolierte interne Arbeitskopie
        try:
            for check in (True, False):
                args = ["git", "apply"]
                if check:
                    args.append("--check")
                args.append("-")
                result = subprocess.run(  # noqa: S603 - feste Argumentliste, kein Shell.
                    args,
                    cwd=str(workspace),
                    input=diff,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    check=False,
                )
                if result.returncode != 0:
                    raise ValueError((result.stderr or result.stdout or "git apply fehlgeschlagen")[-1200:])

            status = subprocess.run(  # noqa: S603
                ["git", "status", "--porcelain"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            paths: list[str] = []
            for line in status.stdout.splitlines():
                relative = line[3:].strip().strip('"').replace("\\", "/")
                if " -> " in relative:
                    raise ValueError("Umbenennungen sind im laufenden Modus nicht zulässig.")
                self._validate_relative(relative)
                if not (workspace / relative).is_file():
                    raise ValueError(f"Dateien dürfen nicht gelöscht werden: {relative}")
                paths.append(relative)
            if len(paths) > self._max_files:
                raise ValueError(f"Der Patch ändert {len(paths)} Dateien; erlaubt sind {self._max_files}.")
            return {
                relative: (workspace / relative).read_text(encoding="utf-8", errors="strict")
                for relative in paths
            }
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def _validate_relative(self, relative: str) -> None:
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"Unzulässiger Projektpfad: {relative}")
        if Path(relative).suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(f"Unzulässiger Dateityp: {relative}")
        if self._is_protected(relative):
            raise ValueError(f"Geschützte Datei: {relative}")

    @staticmethod
    def _is_protected(relative: str) -> bool:
        normalized = relative.replace("\\", "/")
        return any(normalized == item or normalized.startswith(item) for item in PROTECTED_PATHS)

    def _frontend_check(self, prepared: dict[str, Any]) -> str:
        files = [str(item) for item in prepared.get("files_changed", [])]
        if not any(path.endswith((".ts", ".js")) for path in files):
            return ""
        workspace = Path(str(prepared.get("workspace", "")))
        node = shutil.which("node") or str(self._root / "runtime" / "node" / "node.exe")
        tsc = self._root / "node_modules" / "typescript" / "bin" / "tsc"
        if not Path(node).is_file() or not tsc.is_file():
            return "Node.js oder TypeScript wurde nicht gefunden."
        for config in ("tsconfig.json", "tsconfig.renderer.json"):
            result = subprocess.run(  # noqa: S603
                [node, str(tsc), "-p", config, "--noEmit"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode != 0:
                return (result.stderr or result.stdout or "TypeScript-Fehler")[-1600:]
        return ""

    def _build_renderer(self) -> str:
        npm = "npm.cmd" if Path("C:/Windows").exists() else "npm"
        try:
            result = subprocess.run(  # noqa: S603
                [npm, "run", "build:renderer"],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return str(error)
        return "" if result.returncode == 0 else (result.stderr or result.stdout)[-1600:]

    def _build_desktop(self) -> str:
        npm = "npm.cmd" if Path("C:/Windows").exists() else "npm"
        try:
            result = subprocess.run(  # noqa: S603
                [npm, "run", "build"],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return str(error)
        return "" if result.returncode == 0 else (result.stderr or result.stdout)[-1600:]

    @staticmethod
    def _is_renderer_hot_reload(relative: str) -> bool:
        return relative.startswith("desktop/renderer/") or relative.startswith(
            "desktop/electron/dist/renderer/"
        )

    @staticmethod
    def _needs_activation(relative: str) -> bool:
        return (
            relative.startswith("backend/")
            or relative.startswith("desktop/")
            or relative in {"config.yaml", "package.json", "package-lock.json"}
        )

    @staticmethod
    def _title(request: str) -> str:
        compact = " ".join(request.split())
        return compact[:77] + ("…" if len(compact) > 77 else "")

    async def _publish(self, phase: str, **payload: Any) -> None:
        await self._bus.publish("orb.entwicklung.status", {"phase": phase, **payload})


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Erwartet wurde ein JSON-Objekt.")
    return value


def _extract_diff(raw: str) -> str:
    text = raw.strip()
    fenced = re.search(r"```(?:diff|patch)?\s*(.*?)\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("diff --git ")
    if start < 0:
        raise ValueError("Das Modell hat keinen Unified Diff geliefert.")
    return text[start:].rstrip() + "\n"


def _matching_excerpts(source: str, terms: list[str]) -> str:
    lines = source.splitlines()
    ranges: list[tuple[int, int]] = []
    lowered = [term.lower() for term in terms if term]
    for index, line in enumerate(lines):
        if lowered and any(term in line.lower() for term in lowered):
            ranges.append((max(0, index - 100), min(len(lines), index + 140)))
    if not ranges:
        ranges = [(0, min(len(lines), 300))]
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges)[:8]:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    blocks = []
    for start, end in merged:
        body = "\n".join(f"{number + 1:6d} {lines[number]}" for number in range(start, end))
        blocks.append(f"--- Zeilen {start + 1}-{end} ---\n{body}")
    return "\n".join(blocks)
