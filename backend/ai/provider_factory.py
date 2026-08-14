"""Erzeugung von Anbietern aus der Konfiguration (Phase 20).

Nimmt einen Abschnitt aus ``config.yaml`` und macht einen einsatzbereiten
Anbieter daraus – oder sagt im Klartext, warum nicht.

Der zweite Teil ist der wichtigere. Ein Anbieter, der beim ersten Aufruf mit
„401 Unauthorized" scheitert, hilft niemandem; die Fabrik prüft deshalb
schon beim Bauen, ob Modellname und Schlüssel vorhanden sind, und nennt
fehlende Angaben mit dem Ort, an dem sie hingehören.

Die Vorgabe, dass Modellnamen **niemals im Code stehen**, wird hier
durchgesetzt: Fehlt der Modellname in der Konfiguration, wird kein
Vorgabewert eingesetzt, sondern der Aufbau abgelehnt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from backend.ai.provider_registry import ProviderRegistry, get_provider_registry
from backend.orchestrator.providers.base_provider import BaseProvider
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class BuildResult:
    """Das Ergebnis eines Bauversuchs."""

    provider: BaseProvider | None = None
    engine: str = ""
    role: str = ""
    #: Was fehlt oder nicht stimmt – im Klartext.
    problems: list[str] = field(default_factory=list)
    #: Hinweise, die den Betrieb nicht verhindern.
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.provider is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "role": self.role,
            "ok": self.ok,
            "problems": self.problems,
            "warnings": self.warnings,
        }


class ProviderFactory:
    """Baut Anbieter aus Konfigurationsabschnitten."""

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self._registry = registry or get_provider_registry()

    def build(self, section: dict[str, Any], *, role: str = "") -> BuildResult:
        """Baut einen Anbieter.

        Args:
            section: Der Abschnitt aus ``config.yaml``, etwa ``ai.primary``.
            role: Wofür er gedacht ist – nur für Meldungen.

        Returns:
            Der Anbieter oder die Gründe, warum keiner entstand.
        """

        engine = str(section.get("engine", "")).strip().lower()
        result = BuildResult(engine=engine, role=role)

        if not engine:
            result.problems.append(
                f"Im Abschnitt 'ai.{role or '?'}' fehlt der Eintrag 'engine'."
            )
            return result

        info = self._registry.get(engine)
        if info is None:
            result.problems.append(
                f"'{engine}' ist kein bekannter Anbieter. Möglich sind: "
                + ", ".join(self._registry.names())
            )
            return result

        # --- Modellname ---------------------------------------------------------
        model = str(section.get("model", "")).strip()
        if not model:
            result.problems.append(
                f"Im Abschnitt 'ai.{role or engine}' fehlt der Eintrag 'model'. "
                "Modellnamen stehen ausschließlich in config.yaml und werden "
                "nicht im Code vorgegeben."
            )
            return result

        # --- Zugangsdaten -------------------------------------------------------
        if info.requires_api_key:
            variable = str(section.get("api_key_env", "")).strip()
            if not variable:
                result.problems.append(
                    f"'{engine}' braucht einen API-Schlüssel, aber es ist kein "
                    "'api_key_env' eingetragen."
                )
                return result

            if not os.environ.get(variable, "").strip():
                result.problems.append(
                    f"Die Umgebungsvariable '{variable}' ist leer. Trage den "
                    f"Schlüssel in die Datei .env ein: {variable}=..."
                )
                return result

        # --- Bauen ----------------------------------------------------------------
        try:
            provider = info.provider_class(dict(section))
        except Exception as error:  # noqa: BLE001 - jede Ursache soll verständlich sein.
            logger.exception("Der Anbieter '%s' ließ sich nicht bauen.", engine)
            result.problems.append(f"Der Anbieter ließ sich nicht bauen: {error}")
            return result

        result.provider = provider

        # --- Hinweise ---------------------------------------------------------------
        if info.requires_internet:
            result.warnings.append(
                f"'{engine}' braucht eine Internetverbindung. Trage unter "
                "'ai.fallback' einen lokalen Anbieter ein, damit AI-Orb auch "
                "ohne Netz antwortet."
            )

        timeout = float(section.get("timeout", 0) or 0)
        if timeout <= 0:
            result.warnings.append(
                f"Für '{engine}' ist kein Zeitlimit eingetragen. Ohne 'timeout' "
                "kann eine Anfrage sehr lange hängen."
            )
        elif timeout > 300:
            result.warnings.append(
                f"Das Zeitlimit von '{engine}' liegt bei {timeout:.0f} Sekunden. "
                "Das ist lang – der Orb wirkt in dieser Zeit eingefroren."
            )

        logger.info(
            "Anbieter '%s' gebaut (Rolle=%s, Modell=%s).", engine, role or "-", model
        )
        return result

    def build_all(self, ai_config: dict[str, Any]) -> dict[str, BuildResult]:
        """Baut alle konfigurierten Anbieter.

        Returns:
            Die Ergebnisse je Rolle. Auch gescheiterte sind enthalten, damit
            der Benutzer sieht, was fehlt.
        """

        results: dict[str, BuildResult] = {}

        for role in ("primary", "fallback"):
            section = ai_config.get(role) or {}
            if not section:
                continue
            results[role] = self.build(dict(section), role=role)

        for name, section in (ai_config.get("additional") or {}).items():
            if not bool(section.get("enabled", True)):
                continue
            merged = dict(section)
            merged.setdefault("engine", name)
            results[f"additional:{name}"] = self.build(merged, role=name)

        return results

    def diagnose(self, ai_config: dict[str, Any]) -> str:
        """Fasst zusammen, welche Anbieter einsatzbereit sind.

        Der Text ist für das Startprotokoll gedacht: Wer beim Start liest,
        dass der Rückfallanbieter fehlt, weiß Bescheid, bevor das Internet
        ausfällt.
        """

        results = self.build_all(ai_config)
        if not results:
            return (
                "Es ist kein Anbieter eingetragen. Trage unter 'ai.primary' in "
                "config.yaml einen ein."
            )

        lines: list[str] = []
        working = [role for role, result in results.items() if result.ok]

        for role, result in results.items():
            if result.ok:
                lines.append(f"  {role}: {result.engine} – bereit")
                for warning in result.warnings:
                    lines.append(f"      Hinweis: {warning}")
            else:
                lines.append(f"  {role}: {result.engine or '?'} – NICHT bereit")
                for problem in result.problems:
                    lines.append(f"      {problem}")

        header = (
            f"{len(working)} von {len(results)} Anbietern einsatzbereit."
            if working
            else "Kein Anbieter ist einsatzbereit. AI-Orb kann nicht antworten."
        )

        if working and not any(
            not self._registry.get(results[role].engine).requires_internet  # type: ignore[union-attr]
            for role in working
            if self._registry.get(results[role].engine) is not None
        ):
            header += (
                " Alle brauchen Internet – ohne Netz antwortet AI-Orb nicht. "
                "Ein lokaler Anbieter unter 'ai.fallback' behebt das."
            )

        return header + "\n" + "\n".join(lines)


def build_provider(section: dict[str, Any], *, role: str = "") -> BuildResult:
    """Bequemlichkeitsfunktion für einen einzelnen Anbieter."""

    return ProviderFactory().build(section, role=role)
