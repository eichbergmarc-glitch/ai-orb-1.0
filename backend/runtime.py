"""Runtime – startet und verbindet alle Bestandteile von AI-Orb.

Die Runtime besitzt genau eine asyncio-Event-Loop, die in einem eigenen
Thread läuft. Sämtliche kognitive Arbeit findet dort statt; der lokale
HTTP-Server läuft in eigenen Threads und reicht Anfragen threadsicher in
diese Loop hinein. Dadurch blockiert nichts die Oberfläche.

Aufbau der Schichten (von unten nach oben):

    Config · Logging · Event Bus
        → Sicherheitsschicht (jede heikle Aktion läuft hierüber)
        → Memory Engine · Wissensbasis · Knowledge Graph · Lernen
        → Provider Manager · Orchestrator · Antwortpipeline
        → Werkzeuge · Cognitive Core mit Reasoning, Projekten, Zielen
        → Evolution · Skills · Agenten · Plugins · Arbeitsabläufe
        → Präsenz · Sprachsteuerung · Bildverstehen · Forschung
        → API-Server (Brücke zum Electron-Frontend)

Die Reihenfolge ist keine Willkür: Die Sicherheitsschicht kommt vor allem
anderen, weil jede Schicht darüber sie braucht und keine ohne sie handeln
darf.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from pathlib import Path
from typing import Any, Coroutine, TypeVar

from backend import __version__
from backend.agents.agent_manager import AgentManager
from backend.ai.response_pipeline import ResponsePipeline
from backend.behavior.behavior_engine import BehaviorEngine
from backend.behavior.usage_heatmap import UsageHeatmap
from backend.cognitive.cognitive_core import CognitiveCore, CognitiveResponse
from backend.config import get_config, load_env_file
from backend.events import event_types
from backend.events.event_bus import EventBus, get_event_bus
from backend.evolution.evolution_engine import EvolutionEngine
from backend.graph.knowledge_graph import KnowledgeGraph
from backend.knowledge.knowledge_base import KnowledgeBase
from backend.learning.flashcards import FlashcardDeck
from backend.learning.preference_learner import PreferenceLearner
from backend.learning.study_plan import StudyPlanner
from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.orchestrator import Orchestrator
from backend.orchestrator.provider_manager import ProviderManager
from backend.plugins.plugin_manager import PluginManager
from backend.presence.presence_engine import PresenceEngine
from backend.research.research_engine import ResearchEngine
from backend.research.source_criticism import SourceCriticism
from backend.security.security_engine import SecurityEngine
from backend.skills.skill_manager import SkillManager
from backend.system.desktop_control import DesktopControl
from backend.system.logging_setup import get_logger, setup_logging
from backend.system.task_manager import BackgroundTaskManager
from backend.system.window_control import WindowControl
from backend.tools.registry import ToolRegistry
from backend.tools.standard_tools import build_standard_tools
from backend.tools.tool_engine import ToolEngine
from backend.vision.vision_engine import VisionEngine
from backend.voice.voice_pipeline import VoicePipeline
from backend.workflows.workflow_engine import WorkflowEngine

logger = get_logger(__name__)

T = TypeVar("T")


class Runtime:
    """Bündelt alle Bestandteile von AI-Orb und deren Lebenszyklus."""

    def __init__(self) -> None:
        # Vor allem anderen: die Benutzerordner anlegen und, falls dies der
        # erste Start nach einer Installation ist, die Daten der früheren
        # Fassung übernehmen. Danach erst darf irgendetwas protokollieren
        # oder speichern – sonst schriebe es an den falschen Ort.
        self._prepare_user_directories()

        setup_logging()

        # Zugangsdaten aus .env übernehmen, bevor irgendein Provider erzeugt
        # wird – diese lesen ihre Schlüssel aus den Umgebungsvariablen.
        load_env_file()

        self.config = get_config()
        self.event_bus: EventBus = get_event_bus()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._started_at = 0.0
        self.background_tasks = BackgroundTaskManager()

        # --- Schicht 0: Sicherheit -------------------------------------------
        # Kommt vor allem anderen. Jedes Modul, das mehr tut als antworten,
        # fragt hier um Erlaubnis – es gibt keinen Weg daran vorbei.
        self.security = SecurityEngine(self.event_bus)

        # --- Schicht 1: Gedächtnis und Wissen ---------------------------------
        self.memory = MemoryEngine()
        self.knowledge = KnowledgeBase()
        self.graph = KnowledgeGraph()
        self.learning = PreferenceLearner()
        self.flashcards = FlashcardDeck()
        self.study = StudyPlanner()

        # --- Schicht 2: Modelle und Orchestrierung ---------------------------
        self.providers = ProviderManager(self.event_bus)
        self.memory.summaries = type(self.memory.summaries)(self.providers)
        self.orchestrator = Orchestrator(
            memory=self.memory,
            provider_manager=self.providers,
            event_bus=self.event_bus,
        )

        # --- Schicht 3: Cognitive Core ----------------------------------------
        self.cognitive = CognitiveCore(
            memory=self.memory,
            provider_manager=self.providers,
            orchestrator=self.orchestrator,
            event_bus=self.event_bus,
            # Derselbe Lerner, nicht ein zweiter: Zwei Instanzen desselben
            # Gedaechtnisses sind kein Gedaechtnis - jede laedt ihre Datei
            # beim Erzeugen und sieht danach nicht mehr, was die andere
            # lernt.
            preferences=self.learning,
        )

        # --- Schicht 4: Selbstverbesserung, Skills, Agenten --------------------
        self.evolution = EvolutionEngine()
        self.desktop = DesktopControl()
        self.windows = WindowControl()
        self.behavior = BehaviorEngine()
        self.heatmap = UsageHeatmap()
        self.research = ResearchEngine()
        self.sources = SourceCriticism()

        self.agents = AgentManager(
            provider_manager=self.providers,
            memory=self.memory,
            project_engine=self.cognitive.project_engine,
            execution_manager=self.cognitive.reasoning.execution,
            desktop_control=self.desktop,
            evolution_engine=self.evolution,
            security=self.security,
        )

        self.skills = SkillManager(
            memory=self.memory,
            event_bus=self.event_bus,
            capability_registry=self.agents.capabilities,
        )

        # --- Schicht 5: Werkzeuge und Plugins -----------------------------------
        self.tools = ToolRegistry()
        self.tools.register_many(
            build_standard_tools(
                security=self.security,
                memory=self.memory,
                desktop=self.desktop,
            )
        )

        # Schreiben, an sich selbst arbeiten, sich neu starten.
        #
        # Die Maschinerie dafuer gab es laengst - die Evolution Engine mit
        # ihren Wiederherstellungspunkten seit Beginn. Sie war nur nie als
        # Werkzeug angeschlossen und damit fuer den Orb unerreichbar: Er
        # konnte an sich arbeiten, aber niemand hatte ihm gesagt, wie.
        from backend.system.restart import baue_neustarter
        from backend.tools.file_tools import build_file_tools
        from backend.tools.self_tools import build_self_tools

        self.neustarter = baue_neustarter(self.config)
        self.tools.register_many(build_file_tools(self.security))
        self.tools.register_many(
            build_self_tools(
                rollback=self.evolution.rollback,
                neustart=self.neustarter,
            )
        )
        self.tool_engine = ToolEngine(
            registry=self.tools,
            security=self.security,
            provider_manager=self.providers,
            event_bus=self.event_bus,
        )
        # Erst jetzt gibt es die Werkzeugschleife – dem Orchestrator
        # nachreichen, damit Gespräche Werkzeuge benutzen können (Internet,
        # Dateien, Programme). Ohne diesen Anschluss kennt das Modell im
        # Gespräch kein einziges Werkzeug.
        self.orchestrator.attach_tool_engine(self.tool_engine)
        self.plugins = PluginManager(
            security=self.security,
            tool_registry=self.tools,
            event_bus=self.event_bus,
            orb_version=__version__,
        )
        self.workflows = WorkflowEngine(registry=self.tools, security=self.security)
        # Erst jetzt gibt es Ablaeufe - dem Orchestrator nachreichen, damit
        # ein Satz sie ausloesen kann. Bisher liessen sie sich nur ueber
        # ihre Kennung starten, also nie im Gespraech.
        self.orchestrator.attach_workflows(self.workflows)
        self.pipeline = ResponsePipeline()

        # --- Schicht 6: Präsenz, Sprache, Bild ------------------------------------
        self.presence = PresenceEngine(
            behavior_engine=self.behavior,
            learner=self.learning,
        )
        self.vision = VisionEngine(
            security=self.security,
            provider_manager=self.providers,
        )

        # Die Bildschirm-Werkzeuge erst hier anmelden: Die Bildverarbeitung
        # entsteht nach der Werkzeugliste, und ein Werkzeug ohne seine
        # Maschinerie wäre ein Versprechen, das beim Aufruf bricht.
        from backend.tools.vision_tools import DescribeScreenTool, ReadScreenTool

        self.tools.register_many([
            ReadScreenTool(self.vision),
            DescribeScreenTool(self.vision),
        ])
        self.voice = VoicePipeline(
            event_bus=self.event_bus,
            security=self.security,
            answer=self._answer_spoken,
            answer_stream=self._answer_spoken_stream,
        )

        # Die Stimmwerkzeuge erst hier: Sie brauchen die Sprachschicht, und
        # die entsteht nach der Werkzeugliste. Ein Werkzeug ohne seine
        # Maschinerie waere ein Versprechen, das beim Aufruf bricht.
        # Das Themenwissen.
        #
        # Es steht hier und nicht weiter oben, weil es den Provider braucht:
        # Aus gelesenem Text belegte Aussagen zu destillieren ist die
        # eigentliche Arbeit, und die kann keine Regel leisten.
        from backend.learning.themenlerner import Themenlerner
        from backend.learning.themenwissen import Themenspeicher
        from backend.tools.learning_tools import build_learning_tools

        self.themen = Themenspeicher()
        self.themenlerner = Themenlerner(
            speicher=self.themen,
            provider_manager=self.providers,
            memory=self.memory,
        )
        self.tools.register_many(
            build_learning_tools(
                lerner=self.themenlerner,
                speicher=self.themen,
                security=self.security,
            )
        )
        # Der Lehrplan: die Gebiete, die sich der Benutzer gewuenscht hat.
        #
        # Eingetragen werden FRAGEN, keine Stichworte. Ein Thema wie
        # "Mittelalter" ist als Suchauftrag wertlos - die ersten drei
        # Treffer sind Uebersichtsartikel, und was dabei herauskommt, ist
        # eine Lexikoneinleitung. Eine Frage dagegen fuehrt zu Texten, in
        # denen jemand etwas behauptet und begruendet.
        from backend.learning.lehrplan import lehrplan_anlegen

        if bool(self.config.get("learning.curriculum", True)):
            with contextlib.suppress(Exception):
                lehrplan_anlegen(self.themen)

        # Und das Gelernte dem Denken zurueckgeben. Ohne diesen Anschluss
        # waere das Themenwissen eine abgeschottete Ablage: Der Orb wuesste
        # etwas und kaeme im Gespraech nicht darauf.
        self.cognitive.attach_topics(self.themen)

        from backend.tools.voice_tools import build_voice_tools

        self.tools.register_many(build_voice_tools(self.voice))

        # Die Animations-Werkzeuge: der Orb veraendert seine eigene
        # Darstellung. Der Benutzer will sie ihm erklaeren koennen, statt
        # Werte von Hand zu aendern. Braucht den Ereignisbus, um die
        # Oberflaeche nach einer Aenderung neu laden zu lassen.
        from backend.tools.animation_tools import build_animation_tools

        self.tools.register_many(build_animation_tools(self.event_bus))

        # Die Browsersteuerung: der Orb bedient ein echtes Browserfenster -
        # scrollen, klicken, tippen. Eine einzige, geteilte Steuerung, damit
        # alle Aktionen auf DASSELBE Fenster wirken. Playwright wird erst
        # beim ersten Gebrauch geladen; fehlt es, meldet das Werkzeug es
        # ruhig, statt den Start zu gefaehrden.
        if bool(self.config.get("browser.enabled", True)):
            from backend.browser.steuerung import Browsersteuerung
            from backend.tools.browser_tools import build_browser_tools
            from backend.utils.paths import get_project_root

            standard_profil = get_project_root() / "models" / "browser-profil"
            self.browsersteuerung = Browsersteuerung(
                profil_pfad=Path(
                    self.config.get("browser.profil_pfad", str(standard_profil))
                ),
                sichtbar=bool(self.config.get("browser.sichtbar", True)),
                cdp_url=str(self.config.get("browser.cdp_url", "") or ""),
                kanal=str(self.config.get("browser.kanal", "chrome") or "chrome"),
                zeitlimit_ms=int(self.config.get("browser.zeitlimit_ms", 15000)),
            )
            self.tools.register_many(build_browser_tools(self.browsersteuerung))

        # Sich etwas ueber den Benutzer merken - und es spaeter benutzen.
        # Die zweite Haelfte davon steckt im Cognitive Core, der das
        # Gemerkte in jeden Gedanken einfliessen laesst.
        # Gmail: vollstaendig gebaut und bis jetzt unerreichbar.
        #
        # Der Agent haengt am Agenten-Team, und das wird von keiner Stelle
        # beauftragt. Zugangsdaten eingerichtet, alles fertig - und der Orb
        # konnte trotzdem keine einzige Mail lesen. Hier bekommt er den
        # kurzen Weg, ohne den Umweg ueber das Team.
        try:
            from backend.agents.gmail_agent import GmailAgent
            from backend.tools.gmail_tools import build_gmail_tools

            self.gmail = GmailAgent(self.security)
            self.tools.register_many(build_gmail_tools(self.gmail))
        except Exception:  # noqa: BLE001 - ohne Gmail laeuft der Rest weiter.
            logger.exception("Die Gmail-Werkzeuge liessen sich nicht anmelden.")
            self.gmail = None

        from backend.tools.memory_tools import build_memory_tools

        self.tools.register_many(
            build_memory_tools(
                long_term=self.cognitive.long_term_memory,
                preferences=self.cognitive.preferences,
                user_memory=self.memory.user,
            )
        )

        logger.info(
            "AI-Orb %s: alle Bestandteile erzeugt (%d Werkzeuge).",
            __version__,
            len(self.tools),
        )

    # --- Erster Start -------------------------------------------------------------

    @staticmethod
    def _prepare_user_directories() -> None:
        """Legt die Benutzerordner an und übernimmt frühere Daten.

        Die Übernahme geschieht genau einmal – erkennbar an der Datei
        ``.uebernommen``. Ohne diese Marke liefe sie bei jedem Start und
        würde jedes Mal dieselben Dateien prüfen; mit ihr bleibt sie ein
        einmaliger Vorgang beim Umstieg von der Skriptfassung auf die
        installierte.

        Fehler hier dürfen den Start nicht verhindern: Wer sein altes
        Gedächtnis nicht mitnehmen kann, soll wenigstens ein neues anlegen
        können.
        """

        from backend.utils.paths import (
            ensure_user_config,
            ensure_user_directories,
            get_user_dir,
            is_portable,
            migrate_from_project,
        )

        try:
            ensure_user_directories()
            ensure_user_config()
        except OSError:
            # Ohne Ordner läuft nichts – aber die Meldung dazu kommt aus der
            # Startprüfung, die das verständlich erklärt.
            return

        if is_portable():
            return

        marker = get_user_dir() / ".uebernommen"
        if marker.exists():
            return

        try:
            outcome = migrate_from_project()
            marker.write_text(
                f"Übernommen: {len(outcome.get('files', []))} Dateien\n", encoding="utf-8"
            )
        except Exception:  # noqa: BLE001 - eine misslungene Übernahme darf nichts blockieren.
            return

    # --- Sprachantwort ----------------------------------------------------------

    async def _answer_spoken_stream(self, text: str):
        """Streamt eine gesprochene Antwort im Fluss (nur bei stream_speech).

        Dies ist der direkte, lockere Gespraechsweg: Er redet unmittelbar
        mit dem Sprachmodell und laesst die Denkschicht aus, damit der erste
        Satz kommt, waehrend der Rest noch entsteht. Persoenlichkeit und ein
        knapper Gedaechtniskontext gehen mit; das Einordnen der Absicht, der
        Professor und die Werkzeuge nicht - dafuer ist der gewoehnliche Weg
        da.
        """

        from backend.orchestrator.providers.base_provider import ChatMessage

        self.presence.on_interaction(woke=True)

        system = (
            "Du bist AI-Orb, ein gesprochener Assistent. Antworte natuerlich "
            "und knapp, in ganzen Saetzen, ohne Aufzaehlungen oder "
            "Formatierung - deine Antwort wird vorgelesen. Erfinde nichts."
        )
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=text),
        ]

        gesamt = []
        try:
            async for stueck in self.providers.chat_stream(messages):
                gesamt.append(stueck)
                yield stueck
        finally:
            # Den Austausch festhalten wie beim gewoehnlichen Weg.
            antwort = "".join(gesamt).strip()
            if antwort:
                try:
                    # Gelernt wird im Cognitive Core – dieser Weg laesst ihn
                    # aus, deshalb hier. Der gewoehnliche Weg lernt dort.
                    self.learning.observe_interaction(
                        question=text, answer=antwort, via_voice=True
                    )
                    self.presence.on_interaction(succeeded=True)
                except Exception:  # noqa: BLE001
                    logger.debug("Austausch nicht festgehalten.", exc_info=True)

    async def _answer_spoken(self, text: str, *, on_speech=None) -> tuple[str, bool]:
        """Beantwortet eine gesprochene Frage.

        Der Weg ist derselbe wie beim Tippen, mit zwei Unterschieden: Die
        Präsenz bekommt mit, dass gesprochen wurde, und die Antwort wird für
        das Vorlesen aufbereitet. Was am Bildschirm gut aussieht – Listen,
        Tabellen, Code – klingt vorgelesen unbrauchbar.

        Args:
            on_speech: Wird mit jedem fertigen Satz aufgerufen, sobald er
                gedacht ist. Damit redet der Orb schon, während er den Rest
                noch denkt. Werkzeugaufrufe kommen dabei nie zur Sprache.

        Returns:
            Die Antwort und ob sie unterwegs bereits gesprochen wurde.
        """

        self.presence.on_interaction(woke=True)

        try:
            # spoken=True: Die Antwort wird vorgelesen und muss deshalb
            # kurz sein. Das ist der grösste gemessene Hebel gegen die
            # Wartezeit - ein 260-Woerter-Aufsatz braucht doppelt so lange
            # zum Erzeugen und fast zwei Minuten zum Vorlesen.
            response = await self.cognitive.process(
                text, spoken=True, on_speech=on_speech
            )
            answer = response.response
            gesprochen = response.already_spoken
            self.presence.on_interaction(succeeded=True)
        except Exception:  # noqa: BLE001 - die Sprachsteuerung darf nie abstürzen.
            logger.exception("Die gesprochene Anfrage konnte nicht beantwortet werden.")
            self.presence.on_error()
            return (
                "Da ist bei mir etwas schiefgegangen. Die Einzelheiten stehen "
                "im Protokoll.",
                False,
            )

        # Gelernt wird jetzt im Cognitive Core – fuer den gesprochenen wie
        # fuer den getippten Weg. Hier noch einmal zu lernen hiesse, jeden
        # gesprochenen Austausch doppelt zu zaehlen.
        return answer, gesprochen

    # --- Lebenszyklus ---------------------------------------------------------

    def start(self) -> None:
        """Startet die Event-Loop in einem eigenen Thread und bootet alles."""

        if self._thread is not None:
            return

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self.background_tasks.create("ai-orb-boot", self._boot())
            self._ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_run, name="ai-orb-core", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10.0)
        self._started_at = time.time()
        logger.info("AI-Orb Kern gestartet.")

    async def _boot(self) -> None:
        """Führt alle asynchronen Startschritte aus."""

        await self.providers.start()
        await self.agents.test_all()
        await self.skills.load_active()
        await self.plugins.load_enabled()

        await self.event_bus.publish(
            event_types.SYSTEM_READY,
            {
                "version": __version__,
                "provider": self.providers.active_name,
                "agents": self.agents.registry.names(),
                "tools": self.tools.names(),
            },
        )

        self.background_tasks.create("ai-orb-maintenance", self._maintenance_loop())

        # „Ich bin da." – der einzige Moment, in dem der Orb von sich aus
        # etwas meldet, ohne gefragt worden zu sein. Er steht hier und
        # nicht in start(): Dort ist erst der Faden da, hier ist der Kern
        # wirklich bereit. Ein Klang, der zu früh kommt, verspricht etwas,
        # was noch nicht gilt.
        try:
            from backend.audio.sounds import klaenge

            klaenge().start()
        except Exception:  # noqa: BLE001 - ein Signalton darf keinen Start verhindern.
            logger.debug("Der Start-Klang ließ sich nicht abspielen.", exc_info=True)

        # Die Sprachsteuerung wird zuletzt gestartet: Sie fragt nach dem
        # Mikrofon, und diese Frage soll nicht erscheinen, während der Rest
        # noch hochfährt.
        if bool(self.config.get("voice.enabled", True)) and bool(
            self.config.get("voice.autostart", True)
        ):
            self.background_tasks.create("ai-orb-voice-start", self._start_voice())

    async def _start_voice(self) -> None:
        """Startet die Sprachsteuerung und meldet das Ergebnis im Klartext."""

        try:
            started = await self.voice.start()
        except Exception:  # noqa: BLE001 - ohne Sprache läuft der Rest weiter.
            logger.exception("Die Sprachsteuerung ließ sich nicht starten.")
            return

        if started:
            logger.info(self.voice.requirements_report())
        else:
            logger.warning(
                "Die Sprachsteuerung läuft nicht. %s", self.voice.requirements_report()
            )

    async def _maintenance_loop(self) -> None:
        """Führt regelmäßig Pflegearbeiten aus (Vergessen, Aufräumen)."""

        interval = float(self.config.get("cognitive.maintenance_interval", 1800))
        while True:
            await asyncio.sleep(max(300.0, interval))
            try:
                report = await self.cognitive.maintenance()
                logger.debug("Wartung: %s", report)
            except Exception:  # noqa: BLE001 - Wartung darf den Kern nicht stoppen.
                logger.exception("Fehler bei der Wartung.")

            try:
                await self._offene_frage_bearbeiten()
            except Exception:  # noqa: BLE001 - dasselbe gilt hier.
                logger.exception("Fehler beim selbststaendigen Weiterlernen.")

    async def _offene_frage_bearbeiten(self) -> None:
        """Geht einer offenen Frage nach, wenn gerade niemand etwas will.

        Der Benutzer wollte, dass der Orb von sich aus weiterarbeitet. Drei
        Bedingungen halten das im Rahmen:

        **Nur, wenn nichts laeuft.** Waehrend einer Anweisung Bandbreite und
        Rechenzeit fuer eine Nebensache zu verbrauchen, hiesse, die
        Antwortzeit fuer etwas zu opfern, worum niemand gebeten hat.

        **Nur eine Frage je Durchgang.** Nicht, weil mehr zu teuer waere,
        sondern weil eine Frage, die sich in fuenf Schritten selbst
        weitertreibt, nach einer Nacht ein Thema mit dreihundert Aussagen
        ergibt, die niemand mehr durchsieht.

        **Und es wird nicht dazwischengeredet.** Das Ergebnis geht ins
        Protokoll und in den Ereigniskanal, nicht in die Sprachausgabe. Ein
        Assistent, der unaufgefordert zu sprechen beginnt, weil er gerade
        etwas gelesen hat, ist eine Zumutung. Wer wissen will, was
        dazugekommen ist, fragt danach.
        """

        if not bool(self.config.get("learning.autonomous", True)):
            return
        if getattr(self.voice, "is_busy", False):
            return

        naechste = self.themenlerner.naechste_luecke()
        if naechste is None:
            return

        thema, frage = naechste
        logger.info("Arbeite selbststaendig weiter an '%s': %s", thema, frage)

        ergebnis = await self.themenlerner.aus_dem_netz(thema, quellen=2, frage=frage)
        if ergebnis.ok and ergebnis.neue_aussagen:
            logger.info(
                "Selbststaendig dazugelernt: %d Aussagen zu '%s'.",
                ergebnis.neue_aussagen,
                thema,
            )
            await self.event_bus.publish("learning.progressed", ergebnis.to_dict())

    def is_running(self) -> bool:
        """Ob der Kern arbeitet.

        Vom Launcher zur Überwachung benutzt: Geprüft wird nicht nur, ob
        ein Thread existiert, sondern ob die Event-Loop tatsächlich noch
        läuft. Ein abgestürzter Kern hinterlässt sonst einen Thread, der
        lebendig aussieht und nichts mehr tut.
        """

        if self._loop is None or self._thread is None:
            return False
        return self._thread.is_alive() and self._loop.is_running()

    def stop(self) -> None:
        """Fährt AI-Orb geordnet herunter."""

        if self._loop is None:
            return

        async def _shutdown() -> None:
            # Das Mikrofon zuerst freigeben. Ein Assistent, der beim
            # Beenden noch eine Sekunde weiterhört, wäre genau das, was die
            # Datenschutzvorgabe ausschließt.
            await self.voice.stop()

            # Ein etwaig offenes Browserfenster mit schliessen.
            browser = getattr(self, "browsersteuerung", None)
            if browser is not None:
                with contextlib.suppress(Exception):
                    await browser.schliessen()

            await self.plugins.unload_all()
            await self.cognitive.projects.end_session()
            await self.orchestrator.end_conversation()
            await self.agents.shutdown()
            await self.providers.stop()
            await self.event_bus.publish(event_types.SYSTEM_SHUTDOWN, {})

            # Nur Aufgaben beenden, die der Runtime auch wirklich gehören.
            # Global alle Tasks der Event-Loop abzubrechen konnte fremde
            # Aufräumarbeiten mitten im Abschluss zerstören.
            await self.background_tasks.shutdown()

        try:
            self.run(_shutdown(), timeout=15.0)
        except Exception:  # noqa: BLE001
            logger.exception("Fehler beim Herunterfahren.")

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info("AI-Orb Kern beendet.")

    # --- Ausführung aus anderen Threads ----------------------------------------

    def run(self, coroutine: Coroutine[Any, Any, T], *, timeout: float = 180.0) -> T:
        """Führt eine Coroutine auf der Kern-Loop aus und wartet auf das Ergebnis.

        Wird vom HTTP-Server genutzt, der in eigenen Threads läuft.

        Args:
            coroutine: Die auszuführende Coroutine.
            timeout: Zeitlimit in Sekunden.

        Returns:
            Das Ergebnis der Coroutine.

        Raises:
            RuntimeError: Wenn der Kern nicht läuft.
        """

        if self._loop is None:
            raise RuntimeError("Der AI-Orb Kern läuft nicht.")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=timeout)

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """Veröffentlicht ein Event threadsicher auf dem Event Bus."""

        if self._loop is None:
            return
        self.event_bus.publish_threadsafe(self._loop, event_name, payload or {})

    # --- Hauptfunktionen --------------------------------------------------------

    async def ask(self, text: str) -> CognitiveResponse:
        """Verarbeitet eine Benutzereingabe über das Cognitive Core."""

        return await self.cognitive.process(text)

    def status(self) -> dict[str, Any]:
        """Gesamtstatus von AI-Orb für die Transparenzansicht."""

        return {
            "version": __version__,
            "uptime_seconds": round(time.time() - self._started_at, 1) if self._started_at else 0.0,
            "providers": self.providers.status(),
            "background_tasks": self.background_tasks.snapshot(),
            "cognitive": self.cognitive.status(),
            "agents": self.agents.status(),
            "skills": self.skills.status(),
            "behavior": self.behavior.snapshot(),
            "evolution": {
                "security_policy": self.evolution.security_policy(),
                "pending_patches": self.evolution.pending_patches(),
            },
            "security": self.security.status(),
            "voice": self.voice.status(),
            "tools": self.tool_engine.status(),
            "plugins": self.plugins.status(),
            "workflows": self.workflows.status(),
            "vision": self.vision.status(),
            "presence": self.presence.snapshot(),
            "knowledge": self.knowledge.status(),
            "graph": self.graph.status(),
            "learning": self.learning.status(),
            "flashcards": self.flashcards.status(),
            "study": self.study.status(),
            "heatmap": self.heatmap.status(),
            "windows": self.windows.status(),
            "pipeline": self.pipeline.status(),
        }


_instance_lock = threading.Lock()
_instance: Runtime | None = None


def get_runtime() -> Runtime:
    """Gibt die prozessweite Runtime-Instanz zurück."""

    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Runtime()
    return _instance
