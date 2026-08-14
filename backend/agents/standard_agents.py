"""Die Standard-Agenten von AI-Orb.

Jeder Agent besitzt eigene Prompts, eigene Werkzeuge, eigene Regeln und
eigene Fähigkeiten. Kein Agent übernimmt Aufgaben, für die er nicht
vorgesehen ist.

Agenten sprechen niemals direkt miteinander: Sie erhalten ihre Aufgabe vom
Agent Manager und geben ihr Ergebnis dorthin zurück.
"""

from __future__ import annotations

from typing import Any

from backend.agents.base_agent import AgentResult, AgentTask, BaseAgent
from backend.orchestrator.providers.base_provider import ChatMessage, ProviderError
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class LlmAgent(BaseAgent):
    """Gemeinsame Basis für alle Agenten, die ein Sprachmodell nutzen."""

    #: Welches Modell dieser Agent bevorzugt (Providername, z.B.
    #: ``"claude_code"`` oder ``"ollama"``). Leer = der gerade aktive
    #: Provider. Wird beim Bau aus der Konfiguration (``agents.modelle``)
    #: gesetzt und ist der Kern der Aufgabenverteilung: Laufen mehrere
    #: Agenten gleichzeitig, koennen sie so auf VERSCHIEDENEN Modellen
    #: arbeiten (Claude UND lokal) und damit wirklich parallel - statt sich
    #: hintereinander am selben Modell anzustellen.
    bevorzugtes_modell: str = ""

    def __init__(self, provider_manager: Any) -> None:
        super().__init__()
        self._providers = provider_manager

    async def handle(self, task: AgentTask) -> AgentResult:
        """Stellt die Aufgabe mit dem agenteneigenen Systemprompt an das Modell."""

        messages = [ChatMessage(role="system", content=self.system_prompt)]
        if task.context:
            messages.append(ChatMessage(role="system", content=task.context))
        messages.append(ChatMessage(role="user", content=task.text))

        try:
            response = await self._providers.chat(
                messages, preferred=self.bevorzugtes_modell or None
            )
        except ProviderError as error:
            return AgentResult(
                agent=self.name,
                success=False,
                error=str(error),
                response="",
                confidence="niedrig",
            )

        return AgentResult(
            agent=self.name,
            response=response.text,
            data={"provider": response.provider, "model": response.model},
        )


class ConversationAgent(LlmAgent):
    """Verantwortlich für Dialog, Antwortstil und Gesprächsfluss."""

    name = "conversation"
    description = "Dialog, Antwortstil und Gesprächsfluss"
    capabilities = ("dialog", "antwortstil", "gesprächsfluss")
    system_prompt = (
        "Du bist die Gesprächsstimme von AI-Orb. Antworte natürlich, präzise und "
        "in der Sprache des Benutzers. Halte den Gesprächsfluss aufrecht, ohne "
        "belehrend zu wirken. Erfinde keine Fakten; sage offen, wenn du etwas "
        "nicht weißt."
    )


class ReasoningAgent(LlmAgent):
    """Verantwortlich für Planung, Analyse, Entscheidungen und Problemlösung."""

    name = "reasoning"
    description = "Planung, Analyse, Entscheidungen, Problemlösung"
    capabilities = ("planung", "analyse", "entscheidung", "problemlösung")
    system_prompt = (
        "Du bist der analytische Teil von AI-Orb. Zerlege Probleme in klare "
        "Schritte, benenne Annahmen ausdrücklich und trenne Fakten von "
        "Vermutungen. Liefere eine begründete Empfehlung, keine bloße Aufzählung."
    )


class ResearchAgent(LlmAgent):
    """Verantwortlich für Recherche, Quellenvergleich, Zusammenfassungen, Literatur."""

    name = "research"
    description = "Recherche, Quellenvergleich, Zusammenfassungen, Literatur"
    capabilities = ("recherche", "quellenvergleich", "zusammenfassung", "literatur")
    system_prompt = (
        "Du bist der Rechercheteil von AI-Orb. Arbeite quellenorientiert: Nenne "
        "für jede inhaltliche Aussage, worauf sie beruht. Wenn dir keine Quelle "
        "vorliegt, sage das ausdrücklich, statt eine zu erfinden. Vergleiche "
        "abweichende Darstellungen, statt eine davon stillschweigend zu wählen."
    )


class HistoryAgent(LlmAgent):
    """Verantwortlich für Geschichtswissenschaft, Quellenkritik und Methodik."""

    name = "history"
    description = "Geschichtswissenschaft, Quellenkritik, Methodik, Forschungskontroversen"
    capabilities = (
        "geschichtswissenschaft",
        "quellenkritik",
        "methodik",
        "forschungskontroversen",
        "historische_einordnung",
    )
    system_prompt = (
        "Du bist der geschichtswissenschaftliche Teil von AI-Orb. Trenne strikt "
        "zwischen Quellen, Forschungsliteratur, gesicherten Fakten, "
        "Interpretationen, Hypothesen und Forschungskontroversen. Benenne bei "
        "umstrittenen Fragen die wesentlichen Positionen samt ihren Vertretern. "
        "Kennzeichne unsichere Aussagen ausdrücklich. Du unterstützt bei der "
        "wissenschaftlichen Arbeit, ersetzt aber nicht die Eigenleistung des "
        "Benutzers – verfasse daher keine Texte, die als eigene Leistung "
        "eingereicht werden sollen, sondern liefere Struktur, Material und "
        "kritische Rückmeldung."
    )


class CodingAgent(LlmAgent):
    """Verantwortlich für Programmierung, Refactoring, Debugging, Architektur, Tests."""

    name = "coding"
    description = "Programmierung, Refactoring, Debugging, Architektur, Tests"
    capabilities = ("programmierung", "refactoring", "debugging", "architektur", "tests")
    system_prompt = (
        "Du bist der Programmierteil von AI-Orb. Gehe immer in dieser Reihenfolge "
        "vor: Problem analysieren, Architektur überlegen, Plan entwickeln, Code "
        "erzeugen, Code prüfen, Fehler suchen, Verbesserungen vorschlagen. "
        "Schreibe vollständigen, lauffähigen Code ohne Platzhalter und "
        "dokumentiere jede Funktion."
    )


class DesktopAgent(BaseAgent):
    """Verantwortlich für Fenster, Programme, Dateien und Automatisierung."""

    name = "desktop"
    description = "Fenster, Programme, Dateien, Automatisierung"
    capabilities = ("programm_starten", "programm_beenden", "datei_suchen", "fenster")
    requires_llm = False
    system_prompt = "Führt ausschließlich freigegebene Desktop-Aktionen aus."

    def __init__(self, execution_manager: Any, desktop_control: Any) -> None:
        super().__init__()
        self._execution = execution_manager
        self._desktop = desktop_control

    async def handle(self, task: AgentTask) -> AgentResult:
        """Führt eine Desktop-Aktion aus.

        Die eigentliche Ausführung übernimmt der Execution Manager, der den
        Ablauf (Befehl verstehen → Programm finden → ausführen → prüfen →
        informieren) samt Alternativen sicherstellt.
        """

        action = str(task.metadata.get("action", "launch"))
        target = str(task.metadata.get("target", "")).strip()

        if action == "close":
            report = self._execution.close(target, confirmed=bool(task.metadata.get("confirmed")))
        elif action == "open":
            report = self._execution.open_document(target)
        elif action == "search":
            result = self._desktop.find_files(target)
            return AgentResult(
                agent=self.name,
                response=result.message,
                success=result.success,
                data=result.to_dict(),
                confidence="hoch",
            )
        else:
            report = self._execution.launch(
                target, risk_confirmed=bool(task.metadata.get("confirmed", True))
            )

        return AgentResult(
            agent=self.name,
            response=report.message,
            success=report.success,
            data=report.to_dict(),
            confidence="hoch" if report.success else "niedrig",
        )


class VisionAgent(BaseAgent):
    """Verantwortlich für Bildschirm, OCR, Bilder, Diagramme und UI-Erkennung.

    Die Bildauswertung benötigt zusätzliche Komponenten (Bildschirmaufnahme
    und OCR), die nicht Teil der Grundinstallation sind. Fehlen sie, meldet
    der Agent dies ausdrücklich, statt stillschweigend nichts zu tun.
    """

    name = "vision"
    description = "Bildschirm, OCR, Bilder, Diagramme, UI-Erkennung"
    capabilities = ("bildschirm", "ocr", "bildanalyse", "ui_erkennung")
    requires_llm = False
    system_prompt = "Wertet Bildschirminhalte und Bilder aus."

    async def handle(self, task: AgentTask) -> AgentResult:
        available, missing = self._check_dependencies()
        if not available:
            return AgentResult(
                agent=self.name,
                success=False,
                response=(
                    "Für die Bildauswertung fehlen noch Komponenten auf diesem System: "
                    + ", ".join(missing)
                    + ". Installiere sie, damit ich Bildschirminhalte auswerten kann."
                ),
                error="dependencies_missing",
                data={"missing": missing},
            )

        # Die konkrete Auswertung wird über einen Skill bereitgestellt
        # (Skill-System, v3 Phase 6) und hier eingehängt.
        return AgentResult(
            agent=self.name,
            success=False,
            response=(
                "Es ist derzeit kein Vision-Skill installiert. "
                "Ich kann einen entsprechenden Skill vorschlagen, wenn du möchtest."
            ),
            error="no_vision_skill",
        )

    @staticmethod
    def _check_dependencies() -> tuple[bool, list[str]]:
        """Prüft, ob die für die Bildauswertung nötigen Pakete vorhanden sind."""

        missing: list[str] = []
        for module, package in (("PIL", "Pillow"), ("pytesseract", "pytesseract")):
            try:
                __import__(module)
            except ImportError:
                missing.append(package)
        return (not missing), missing


class VoiceAgent(BaseAgent):
    """Verantwortlich für Sprachausgabe, Prosodie, Streaming und Sprachplanung.

    Die Sprachsynthese wird über einen Skill bereitgestellt. Ohne
    installierten Skill meldet der Agent dies ausdrücklich.
    """

    name = "voice"
    description = "Sprachausgabe, Prosodie, Streaming, Sprachplanung"
    capabilities = ("sprachausgabe", "prosodie", "streaming")
    requires_llm = False
    system_prompt = "Erzeugt gesprochene Ausgabe."

    def __init__(self, skill_manager: Any | None = None) -> None:
        super().__init__()
        self._skills = skill_manager

    async def handle(self, task: AgentTask) -> AgentResult:
        if self._skills is not None and self._skills.has_capability("sprachausgabe"):
            return await self._skills.invoke("sprachausgabe", {"text": task.text})

        return AgentResult(
            agent=self.name,
            success=False,
            response=(
                "Es ist keine Sprachausgabe installiert. "
                "Sobald ein Sprachausgabe-Skill eingerichtet ist, kann ich Antworten vorlesen."
            ),
            error="no_voice_skill",
        )


class MemoryAgent(BaseAgent):
    """Verantwortlich für Projektwissen, Langzeitgedächtnis, Kontext und Wissensgraph."""

    name = "memory"
    description = "Projektwissen, Langzeitgedächtnis, Kontext, Wissensgraph"
    capabilities = ("gedächtnis", "projektwissen", "wissensgraph", "kontext")
    requires_llm = False
    system_prompt = "Verwaltet das Gedächtnis von AI-Orb."

    def __init__(self, memory: Any, project_engine: Any) -> None:
        super().__init__()
        self._memory = memory
        self._projects = project_engine

    async def handle(self, task: AgentTask) -> AgentResult:
        """Sucht relevante Erinnerungen und Projektinformationen."""

        matches = self._memory.recall(task.text, limit=5, project_id=task.project_id)
        if not matches:
            return AgentResult(
                agent=self.name,
                response="Dazu habe ich nichts im Gedächtnis gespeichert.",
                confidence="hoch",
                data={"hits": 0},
            )

        lines = ["Das habe ich dazu gespeichert:"]
        sources: list[dict[str, str]] = []
        for match in matches:
            certainty = str(match.record.metadata.get("certainty", "fakt"))
            marker = "" if certainty == "fakt" else f" [{certainty}]"
            lines.append(f"  • {match.record.content}{marker}")
            source = match.record.metadata.get("source")
            if source:
                sources.append({"title": match.record.content[:60], "url": str(source)})

        return AgentResult(
            agent=self.name,
            response="\n".join(lines),
            confidence="hoch",
            sources=sources,
            data={"hits": len(matches)},
        )


class EvolutionAgent(BaseAgent):
    """Verantwortlich für Selbstverbesserung, Codeanalyse, Patches und Benchmarks."""

    name = "evolution"
    description = "Selbstverbesserung, Codeanalyse, Patches, Benchmarks"
    capabilities = ("codeanalyse", "patches", "benchmarks", "skillvorschläge")
    requires_llm = False
    system_prompt = "Analysiert und verbessert AI-Orb selbst."

    def __init__(self, evolution_engine: Any) -> None:
        super().__init__()
        self._evolution = evolution_engine

    async def handle(self, task: AgentTask) -> AgentResult:
        """Beantwortet Fragen zur Selbstverbesserung."""

        # Der Start-Selbsttest prueft nur, ob der Agent ansprechbar ist.
        # Eine vollstaendige Analyse aller Projektmodule dauerte hier zuletzt
        # 46 Sekunden und konkurrierte direkt mit der ersten Benutzerfrage.
        if task.metadata.get("selftest") is True:
            return AgentResult(
                agent=self.name,
                response="Die Evolution-Schnittstelle ist bereit.",
                data={"selftest": True},
            )

        lowered = task.text.lower()

        if "patch" in lowered:
            patches = self._evolution.pending_patches()
            if not patches:
                return AgentResult(
                    agent=self.name,
                    response="Derzeit liegen keine fertigen Patches zur Übernahme bereit.",
                )
            lines = ["Bereitstehende Patches:"]
            lines.extend(
                f"  • {patch['title']} (Branch {patch['branch']}, Tests: {patch['test_status']})"
                for patch in patches
            )
            return AgentResult(agent=self.name, response="\n".join(lines), data={"patches": patches})

        report = self._evolution.analyze()
        lines = [
            f"Ich habe {len(report['findings'])} Verbesserungsmöglichkeit(en) gefunden."
        ]
        lines.extend(
            f"  • [{finding['severity']}] {finding['message']} ({finding['location']})"
            for finding in report["findings"][:10]
        )
        return AgentResult(agent=self.name, response="\n".join(lines), data=report)
