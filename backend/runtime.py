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
import uuid
from collections import OrderedDict
import concurrent.futures
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
        #: Ob ``_boot`` durchgelaufen ist - nicht nur der Faden steht.
        self._boot_fertig = False
        #: Startschritte, die nicht geklappt haben: Name -> Grund.
        self.startfehler: dict[str, str] = {}
        self._started_at = 0.0
        self.background_tasks = BackgroundTaskManager()
        #: Laufende Sprechauftraege fuer Geraete ohne eigenen Orb.
        #: Aelteste fliegen zuerst hinaus - siehe AUFTRAEGE_MERKEN.
        self._sprechauftraege: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

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
        from backend.evolution.live_development import LiveDevelopmentService
        from backend.tools.development_tools import build_development_tools
        from backend.tools.file_tools import build_file_tools
        from backend.tools.grafik_tools import build_grafik_tools
        from backend.tools.pdf_tools import build_pdf_tools
        from backend.tools.self_tools import build_self_tools

        self.neustarter = baue_neustarter(self.config)
        self.tools.register_many(build_file_tools(self.security))
        self.tools.register_many(build_pdf_tools(self.security))
        # Bilder: selbst gezeichnete Diagramme, gesuchte Fotos, erzeugte
        # Illustrationen. Sie stehen direkt neben dem PDF-Werkzeug, weil sie
        # fast immer dafuer gebraucht werden - alle drei liefern einen Pfad,
        # und genau den nimmt 'pdf_erstellen' entgegen.
        self.tools.register_many(build_grafik_tools(self.security))
        self.tools.register_many(
            build_self_tools(
                rollback=self.evolution.rollback,
                neustart=self.neustarter,
            )
        )
        self.live_development = LiveDevelopmentService(
            providers=self.providers,
            evolution=self.evolution,
            event_bus=self.event_bus,
            neustart=self.neustarter,
        )
        self.tools.register_many(build_development_tools(self.live_development))
        # Das Handy (12.11.2026): anrufen, SMS/WhatsApp, Apps, Kurzbefehle.
        try:
            from backend.integrations.gmail.oauth import GmailAuth
            from backend.tools.handy_tools import Kontaktbuch, build_handy_tools

            self.kontakte = Kontaktbuch(GmailAuth())
            self.tools.register_many(build_handy_tools(self.kontakte))
        except Exception:  # noqa: BLE001 - ohne Handy-Werkzeuge laeuft der Orb weiter.
            logger.exception("Die Handy-Werkzeuge liessen sich nicht anmelden.")
        # Fahrplan (12.11.2026): Zug-, Bus- und Postautoverbindungen.
        try:
            from backend.tools.fahrplan_tools import VerbindungSuchenTool

            self.tools.register_many([VerbindungSuchenTool()])
        except Exception:  # noqa: BLE001 - ohne Fahrplan laeuft der Orb weiter.
            logger.exception("Das Fahrplan-Werkzeug liess sich nicht anmelden.")
        # Abgewiesene Werkzeuge sind ein Startfehler, keine Randnotiz.
        #
        # Achtzehn Tage lang wies das Register 'internet_suchen' bei jedem
        # Start ab, weil dort die Berechtigung "internet" stand statt
        # "network". Der Orb lief, meldete sich gesund und hatte keine
        # Websuche. Genau das soll ab jetzt auffallen: Der Eintrag steht in
        # startfehler, geht in SYSTEM_READY mit und laesst die
        # Startpruefung rot werden.
        abgewiesen = self.tools.abgewiesene()
        if abgewiesen:
            beschreibung = "; ".join(
                f"{eintrag['name']} ({eintrag['grund']})" for eintrag in abgewiesen
            )
            self.startfehler["Werkzeuge"] = beschreibung
            logger.error(
                "%d Werkzeug(e) konnten nicht angemeldet werden: %s. Der Orb "
                "ist unvollstaendig.",
                len(abgewiesen),
                beschreibung,
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
        # Und der Anschluss ans Gedaechtnis: Was gelesen wird, soll der Orb
        # morgen noch wissen. Ohne diese Zeile ging jedes eingelesene
        # Dokument nach der einen Antwort verloren - genau die Klage des
        # Benutzers vom 19.08.2026.
        self.tool_engine.gelesenes_behalten = (
            lambda inhalt, quelle: self.orchestrator._gelesenes_merken(
                inhalt, quelle=quelle
            )
        )
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

        # Die Webcam (07.11.2026): ansehen und Marc wiedererkennen.
        if bool(self.config.get("vision.kamera.enabled", True)):
            try:
                from backend.tools.vision_tools import GesichtMerkenTool, KameraAnsehenTool
                from backend.vision.kamera import Kamera

                self.kamera = Kamera(
                    provider_manager=self.providers,
                    einstellungen=dict(self.config.get("vision.kamera", {}) or {}),
                )
                self.tools.register_many([
                    KameraAnsehenTool(self.kamera),
                    GesichtMerkenTool(self.kamera),
                ])
            except Exception:  # noqa: BLE001 - ohne Kamera laeuft der Orb weiter.
                logger.exception("Die Kamera-Werkzeuge liessen sich nicht anmelden.")
        self.voice = VoicePipeline(
            event_bus=self.event_bus,
            security=self.security,
            answer=self._answer_spoken,
            answer_stream=self._answer_spoken_stream,
        )
        # Ein Providerwechsel wird auch auf die Stimme angewendet. Dadurch
        # nutzt die Bestaetigung "Offlinebetrieb ist aktiv" bereits Piper/
        # SAPI und nicht versehentlich ElevenLabs.
        self.event_bus.subscribe("ai.provider.changed", self._sync_provider_mode)
        # Gelingt die Google-Anmeldung, sagt der Orb es auch. Der Benutzer
        # sieht sonst nur die Browserseite und fragt sich, ob der Orb es
        # mitbekommen hat.
        self.event_bus.subscribe("gmail.login.completed", self._gmail_angemeldet)

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

        # Das Studium: Studienplan, Einstufung, Vorlesung mit Präsentation.
        #
        # Der Anschluss steht HIER und nicht irgendwo - denn genau daran ist
        # der Vorgänger gestorben. Der alte Professor-Apparat unter
        # ``backend/agents/history_agent`` hatte 3.500 Zeilen und keinen
        # Werkzeugnamen, den ein Sprachmodell hätte aufrufen können. Er hat
        # seit dem 09.08.2026 dreimal gefeuert. Was ein Modell nicht
        # aufrufen kann, gibt es für den Benutzer nicht.
        from backend.studium.lernstand import Lernstand
        from backend.tools.studium_tools import build_studium_tools

        self.lernstand = Lernstand()

        # Das Aktuellhalten: Der Benutzer hat es woertlich verlangt - "Der
        # Orb muss sich regelmaessig auf dem aktuellen Wissensstand aller
        # Themenbereiche halten, aktuelle Publikationen kennen und
        # ebenfalls in sein Gedaechtnis aufnehmen." Der Kreislauf selbst
        # startet in _boot; hier entsteht nur das Geraet, damit die
        # Werkzeuge seine Funde zeigen koennen.
        from backend.studium.aktualisierung import Aktualisierung

        self.aktualisierung = Aktualisierung(
            abstand_tage=float(
                self.config.get("studium.aktualisierung_abstand_tage", 7)
            ),
            # kind="publikation": Das Vergessen laesst diese Eintraege
            # stehen. Als "knowledge" verschwanden sie nach der
            # Halbwertszeit wieder - der Kreislauf trug ein, was er
            # anschliessend selbst wieder verlor.
            merken=lambda text, quelle: self.memory.remember(
                text,
                kind="publikation",
                tags=["fachliteratur"],
                source=quelle,
                force=True,
            ),
        )
        self.tools.register_many(
            build_studium_tools(self.lernstand, self.aktualisierung)
        )

        # Die Karteikarten - endlich auch als Werkzeug.
        #
        # Der Stapel wurde beim Start immer angelegt (self.flashcards),
        # aber nie angemeldet. Was nicht in der Werkzeugliste steht,
        # existiert fuer das Sprachmodell nicht: Der Orb konnte abgestufte
        # Wiederholungen fuehren und kam nicht an sie heran. Genau hier lag
        # die Luecke zwischen "Lernstand und Karteikarten existieren" und
        # der Vorgabe "Mentor und Professor".
        from backend.tools.karteikarten_tools import build_karteikarten_tools

        self.tools.register_many(build_karteikarten_tools(self.flashcards))

        # Das Tagebuch: diktierte Eintraege, wortgetreu aufbewahrt und als
        # gestaltete Seite jederzeit nachlesbar (Wunsch vom 20.08.2026).
        # Die Ablage steht auf der Schutzliste, und data/ verlaesst den
        # Rechner nie - ein Tagebuch ist Privatsache.
        from backend.tagebuch import Tagebuch, _dokumente_ordner
        from backend.tools.tagebuch_tools import build_tagebuch_tools
        from backend.utils.paths import get_data_dir as _daten

        # Die Ablage (Wahrheit) liegt geschuetzt in den Anwendungsdaten,
        # das LESBARE Buch bei den Dokumenten des Benutzers - ein echtes
        # Tagebuch muss sich ohne den Orb aufschlagen lassen.
        self.tagebuch = Tagebuch(ordner=_daten(), lese_ordner=_dokumente_ordner())
        self.tools.register_many(build_tagebuch_tools(self.tagebuch))

        # Und das Mitlesen: Der Orchestrator sieht jede Aeusserung, und
        # dort wird abgelesen, wo der Benutzer steht - im Gespraech, nicht
        # in einem Test.
        self.orchestrator.attach_lernstand(self.lernstand)
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

        # Der grosse Lehrplan: Personen und Gebiete des Denkens.
        #
        # Auftrag des Benutzers vom 18.08.2026 - Philosophie, Mathematik,
        # Geschichtswissenschaft, Quantenphysik, Physik, Chemie, Biologie,
        # Religionen, Sprachwissenschaft, und die Personen dahinter. Jede
        # Person wird ein eigenes Thema; die Fragen zielen auf Kern,
        # Beleg, Einwand und heutige Geltung - das, was einen Lehrenden
        # ausmacht.
        if bool(self.config.get("learning.grosser_lehrplan", True)):
            with contextlib.suppress(Exception):
                from backend.learning.lehrplan_wissenschaft import (
                    umfang,
                    wissenschaftlicher_lehrplan,
                )

                neu = lehrplan_anlegen(self.themen, wissenschaftlicher_lehrplan())
                themen_anzahl, fragen_anzahl = umfang()
                if neu:
                    logger.info(
                        "Grosser Lehrplan: %d neue Fragen (insgesamt %d Themen, "
                        "%d Fragen).", neu, themen_anzahl, fragen_anzahl,
                    )

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
            # Gekapselt, weil die Browsersteuerung an etwas haengt, das
            # ausserhalb des Orb liegt: Playwright und ein installierter
            # Chrome. Fehlt eines davon oder ist das Profil beschaedigt,
            # scheiterte bisher der GANZE Aufbau - kein Gedaechtnis, keine
            # Stimme, kein Orb, wegen einer Browsererweiterung.
            try:
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
            except Exception:  # noqa: BLE001 - ohne Browser laeuft der Rest weiter.
                self.browsersteuerung = None
                logger.exception(
                    "Die Browsersteuerung liess sich nicht aufbauen. AI-Orb "
                    "laeuft ohne sie weiter; Internetsuche und Seitenlesen "
                    "gehen unabhaengig davon."
                )

        # Sich etwas ueber den Benutzer merken - und es spaeter benutzen.
        # Die zweite Haelfte davon steckt im Cognitive Core, der das
        # Gemerkte in jeden Gedanken einfliessen laesst.
        # Gmail: vollstaendig gebaut und bis jetzt unerreichbar.
        #
        # Der Agent haengt am Agenten-Team, und das wird von keiner Stelle
        # beauftragt. Zugangsdaten eingerichtet, alles fertig - und der Orb
        # konnte trotzdem keine einzige Mail lesen. Hier bekommt er den
        # kurzen Weg, ohne den Umweg ueber das Team.
        self.gmail = None
        try:
            from backend.agents.gmail_agent import GmailAgent
            from backend.tools.gmail_tools import build_gmail_tools

            self.gmail = GmailAgent(self.security)
            self.tools.register_many(build_gmail_tools(self.gmail))
        except Exception:  # noqa: BLE001 - ohne Gmail laeuft der Rest weiter.
            logger.exception("Die Gmail-Werkzeuge liessen sich nicht anmelden.")

        # Der Kalender: dieselbe Google-Anmeldung wie Gmail, dieselbe
        # Client-ID, dasselbe Token. Deshalb steht er hier gleich daneben -
        # wer Gmail eingerichtet hat, hat den Kalender fast schon
        # eingerichtet.
        self.kalender = None
        self.terminerinnerung = None
        if bool(self.config.get("kalender.enabled", True)):
            try:
                from backend.integrations.gmail.oauth import GmailAuth
                from backend.integrations.kalender.client import KalenderClient
                from backend.integrations.kalender.erinnerung import Terminerinnerung
                from backend.tools.kalender_tools import build_kalender_tools

                self.kalender = KalenderClient(
                    GmailAuth(),
                    kalender=str(self.config.get("kalender.kalender_id", "primary")),
                )
                self.tools.register_many(build_kalender_tools(self.kalender))

                if bool(self.config.get("kalender.erinnerung.enabled", True)):
                    self.terminerinnerung = Terminerinnerung(
                        self.kalender,
                        self._termin_ansagen,
                        vorlaufzeiten=list(
                            self.config.get("kalender.erinnerung.vorlaufzeiten", [60, 10])
                            or [60, 10]
                        ),
                        takt_sekunden=int(
                            self.config.get("kalender.erinnerung.takt_sekunden", 180)
                        ),
                        # Die einzige Regel der Praesenzschicht, die auch
                        # fuer Termine gilt: Wer um Ruhe gebeten hat,
                        # bekommt sie.
                        darf_sprechen=lambda: not self.presence.is_suppressed,
                    )
            except Exception:  # noqa: BLE001 - ohne Kalender laeuft der Rest weiter.
                logger.exception("Die Kalender-Werkzeuge liessen sich nicht anmelden.")

        # TIDAL: Musik suchen, in der App abspielen, Playlists anlegen.
        # Suchen geht schon mit Client-ID und -Secret aus der .env, fuer
        # Playlists braucht es einmal "Melde mich bei TIDAL an".
        self.tidal = None
        if bool(self.config.get("tidal.enabled", True)):
            try:
                from backend.integrations.tidal.client import TidalClient
                from backend.integrations.tidal.oauth import TidalAuth, TidalOAuthConfig
                from backend.tools.tidal_tools import TidalDienst, build_tidal_tools

                tidal_auth = TidalAuth(
                    TidalOAuthConfig.from_env(
                        scope=str(self.config.get("tidal.scope", "") or ""),
                        redirect_uri=str(self.config.get("tidal.redirect_uri", "") or ""),
                    )
                )
                self.tidal = TidalDienst(
                    TidalClient(tidal_auth, land=str(self.config.get("tidal.land", "CH"))),
                    danach_abspielen=bool(self.config.get("tidal.nach_oeffnen_abspielen", True)),
                    warte_sekunden=float(self.config.get("tidal.warte_sekunden", 4.0)),
                )
                self.tools.register_many(build_tidal_tools(self.tidal))
                if not tidal_auth.is_configured:
                    logger.info("TIDAL: TIDAL_CLIENT_ID/TIDAL_CLIENT_SECRET fehlen in der .env.")
            except Exception:  # noqa: BLE001 - ohne TIDAL laeuft der Rest weiter.
                logger.exception("Die TIDAL-Werkzeuge liessen sich nicht anmelden.")

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

        from backend.orchestrator.orchestrator import provider_mode_command
        from backend.orchestrator.providers.base_provider import ChatMessage

        self.presence.on_interaction(woke=True)

        # Auch der optionale schnelle Streamingweg muss den Modusbefehl vor
        # jeder Modellanfrage abfangen. Sonst funktionierte "geh offline"
        # ausgerechnet dann nicht, wenn stream_speech eingeschaltet ist.
        if provider_mode_command(text):
            response = await self.cognitive.process(text, spoken=True)
            if response.response:
                yield response.response
            return

        # Auch dieser schnelle Weg bekommt dieselbe Persona wie der
        # gewoehnliche Denkweg. Ein eigener Kurzprompt liess den Orb bisher
        # je nach Route ploetzlich anders sprechen.
        base_prompt = str(self.config.get("conversation.system_prompt", ""))
        system = self.presence.system_prompt(base=base_prompt)
        system += (
            "\n\nDiese Antwort wird unmittelbar vorgelesen. Fasse dich bei einer "
            "einfachen Frage kurz und benutze keine sichtbare Formatierung."
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

    async def _termin_ansagen(self, satz: str) -> bool:
        """Sagt eine Terminerinnerung an - gesprochen und in der Oberflaeche.

        Beides, nicht eines von beiden: Wer den Ton aus hat, soll die
        Erinnerung trotzdem sehen; wer nicht hinsieht, soll sie hoeren.
        """

        with contextlib.suppress(Exception):
            await self.event_bus.publish(
                "kalender.erinnerung", {"text": satz, "zeitpunkt": time.time()}
            )
        try:
            return await self.voice.say(satz, emotion="aufmerksam")
        except Exception:  # noqa: BLE001 - eine stumme Erinnerung ist besser als ein Absturz.
            logger.exception("Die Terminerinnerung liess sich nicht sprechen.")
            return False

    async def _gmail_angemeldet(self, event: Any) -> None:
        """Bestätigt die gelungene Google-Anmeldung hörbar."""

        payload = getattr(event, "payload", {}) or {}
        satz = "Die Anmeldung bei Google ist geschafft."
        if payload.get("kalender"):
            satz += " Post und Kalender sind jetzt verbunden."
        else:
            satz += " Der Kalender war nicht dabei - melde dich dafür einmal neu an."
        with contextlib.suppress(Exception):
            await self.voice.say(satz, emotion="freundlich")

    async def _sync_provider_mode(self, event: Any) -> None:
        """Haelt Modell- und Sprach-Offlinebetrieb synchron."""

        payload = getattr(event, "payload", {}) or {}
        # Auch der automatische Ollama-Ersatz muss sofort die lokale Stimme
        # verwenden. Zuvor galt das nur nach dem ausdruecklichen Sprachbefehl
        # "Offlinebetrieb"; bei echtem Netzausfall wartete die Stimme weiter
        # nacheinander auf Cloud-Dienste.
        self.voice.set_offline_mode(
            bool(
                payload.get("offline", False)
                or payload.get("temporary_local_fallback", False)
            )
        )

    async def _schritt(self, name: str, arbeit: Coroutine[Any, Any, Any]) -> bool:
        """Führt einen Startschritt aus und überlebt sein Scheitern.

        Vorher standen die Startschritte ungeschützt hintereinander. Riss
        einer - ein Anbieter ohne Schlüssel, ein Plugin mit Tippfehler -,
        endete ``_boot`` mitten im Ablauf: kein SYSTEM_READY, keine
        Wartungsschleife, keine Sprachsteuerung. Der Faden aber lebte, und
        ``is_running()`` sagte weiterhin ja. Der Wächter sah einen gesunden
        Kern, der Benutzer einen tauben Orb.

        Jetzt scheitert ein Schritt für sich allein. Was er hätte
        beitragen sollen, fehlt - der Rest fährt hoch, und was fehlt,
        steht im Protokoll und in ``self.startfehler``.
        """

        try:
            await arbeit
            return True
        except Exception as fehler:  # noqa: BLE001 - ein Schritt darf nichts mitreissen.
            self.startfehler[name] = f"{type(fehler).__name__}: {fehler}"
            logger.exception(
                "Der Startschritt '%s' ist fehlgeschlagen. AI-Orb fährt ohne "
                "ihn hoch.",
                name,
            )
            return False

    async def _boot(self) -> None:
        """Führt alle asynchronen Startschritte aus."""

        # Nur die Schritte dieses Laufs zuruecksetzen. Was schon beim
        # Aufbau schiefging (etwa abgewiesene Werkzeuge), bleibt stehen -
        # sonst loescht der Start genau die Meldung, die er tragen soll.
        for _schrittname in ("Anbieter", "Agenten", "Fertigkeiten", "Erweiterungen"):
            self.startfehler.pop(_schrittname, None)

        await self._schritt("Anbieter", self.providers.start())
        await self._schritt("Agenten", self.agents.test_all())
        await self._schritt("Fertigkeiten", self.skills.load_active())
        await self._schritt("Erweiterungen", self.plugins.load_enabled())

        if self.startfehler:
            logger.warning(
                "AI-Orb ist mit %d unvollständigen Startschritten oben: %s",
                len(self.startfehler),
                ", ".join(sorted(self.startfehler)),
            )

        with contextlib.suppress(Exception):
            await self.event_bus.publish(
                event_types.SYSTEM_READY,
                {
                    "version": __version__,
                    "provider": self.providers.active_name,
                    "agents": self.agents.registry.names(),
                    "tools": self.tools.names(),
                    # Ehrlich statt beruhigend: Wer hier nachsieht, erfährt,
                    # was beim Start nicht geklappt hat.
                    "startfehler": dict(self.startfehler),
                },
            )

        self._boot_fertig = True

        self.background_tasks.create("ai-orb-maintenance", self._maintenance_loop())
        if bool(self.config.get("learning.autonomous", True)):
            self.background_tasks.create("ai-orb-lernen", self._lernschleife())
        if bool(self.config.get("studium.aktualisierung", True)):
            self.background_tasks.create(
                "ai-orb-aktuell", self._aktualisierungsschleife()
            )
        if bool(self.config.get("nachrichten.taeglich", True)):
            self.background_tasks.create(
                "ai-orb-nachrichten", self._nachrichtenschleife()
            )

        # Der Blick in den Kalender. Erst hier und nicht im Aufbau: Dort gibt
        # es noch keine laufende Schleife, in die sich eine Daueraufgabe
        # haengen koennte.
        if self.terminerinnerung is not None:
            with contextlib.suppress(Exception):
                self.terminerinnerung.starten()

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

    async def _lernschleife(self) -> None:
        """Arbeitet im Leerlauf offene Fragen ab - in eigenem Takt.

        Vom Wartungstakt getrennt, seit der grosse Lehrplan dazukam: Der
        umfasst rund tausend Fragen, und bei einer Frage je halbe Stunde
        waere er erst in drei Wochen durchgearbeitet. Die Wartung dagegen
        soll SELTEN laufen - sie raeumt auf, und Aufraeumen im
        Sieben-Minuten-Takt waere Unfug. Zwei Aufgaben, zwei Takte.
        """

        takt = max(60.0, float(self.config.get("learning.takt_sekunden", 420)))
        while True:
            await asyncio.sleep(takt)
            try:
                await self._offene_frage_bearbeiten()
            except Exception:  # noqa: BLE001 - Lernen darf den Kern nicht stoppen.
                logger.exception("Fehler beim selbststaendigen Weiterlernen.")

    async def _nachrichtenschleife(self) -> None:
        """Der tägliche Blick in die Welt.

        Die Vorgabe verlangt ihn, die Quellen gab es, der Aufrufer fehlte:
        GDELT und die RSS-Feeds waren ausschliesslich über eine Frage des
        Benutzers erreichbar. Politik, Wirtschaft und Weltlage wurden nie
        von selbst geholt - die Vorgabe war damit nicht halb erfüllt,
        sondern gar nicht.

        Der Lauf startet nichts beim Hochfahren: Er wartet, bis die
        eingestellte Uhrzeit erreicht ist. Nur der erste Lauf darf, wenn
        gewünscht, kurz nach dem Start kommen - damit ein frisch
        eingerichteter Orb nicht bis zum nächsten Morgen so aussieht, als
        täte er nichts.
        """

        from backend.research.nachrichtenlauf import Nachrichtenlauf

        themen = self.config.get("nachrichten.themen", None)
        self.nachrichten = Nachrichtenlauf(
            memory=self.memory,
            event_bus=self.event_bus,
            themen=list(themen) if isinstance(themen, list) else None,
            uhrzeit=str(self.config.get("nachrichten.uhrzeit", "07:30")),
            hoechstens=int(self.config.get("nachrichten.hoechstens", 8)),
        )

        if bool(self.config.get("nachrichten.beim_start", True)):
            # Nicht sofort: Der Start hat Wichtigeres zu tun, als
            # Zeitungen zu lesen.
            await asyncio.sleep(
                max(30.0, float(self.config.get("nachrichten.start_verzoegerung", 180)))
            )
            try:
                await self.nachrichten.einmal_laufen()
            except Exception:  # noqa: BLE001 - der erste Lauf darf scheitern.
                logger.exception("Der erste Nachrichtenlauf ist gescheitert.")

        await self.nachrichten.schleife()

    async def _aktualisierungsschleife(self) -> None:
        """Hält die Themen der Landkarte auf dem Stand der Forschung.

        Ein Thema je Takt, die beruehrten zuerst. Bewusst ein EIGENER
        Takt, getrennt von Wartung und Lernschleife: Zwei Anfragen an
        offene Wissenschaftskataloge alle halbe Stunde sind hoeflich;
        alles auf einmal waere Stossbetrieb - und genau der hat dem Orb
        bei Wikimedia schon einmal 429er eingebracht.
        """

        takt = max(
            120.0,
            float(self.config.get("studium.aktualisierung_takt_sekunden", 1800)),
        )
        while True:
            await asyncio.sleep(takt)
            try:
                beruehrte = {
                    feld: self.lernstand.beruehrt(feld)
                    for feld in self.lernstand.uebersicht()
                }
                ziel = self.aktualisierung.naechstes(beruehrte)
                if ziel is None:
                    continue
                # Blockierendes urllib gehoert nicht in die Ereignisschleife.
                await asyncio.to_thread(
                    self.aktualisierung.auffrischen, ziel[0], ziel[1]
                )
            except Exception:  # noqa: BLE001 - Pflege darf den Kern nicht stoppen.
                logger.exception("Fehler beim Aktuellhalten der Landkarte.")

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
        # Hintergrundlernen darf nie mit einem Gespraech um denselben
        # Provider konkurrieren. Frueher wurde hier ``is_busy`` abgefragt,
        # diese Eigenschaft existierte an der VoicePipeline aber nicht. Das
        # defensive getattr lieferte dadurch immer False und alle sieben
        # Minuten konnte ein Lernlauf die Benutzerantwort ausbremsen.
        if not getattr(self.voice, "background_idle", False):
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

    def kern_gesund(self) -> bool:
        """Ob der Kern lebt UND fertig hochgefahren ist.

        Das ist die Frage, die der Wächter eigentlich stellen wollte.
        ``is_running()`` beantwortet nur, ob sich die Schleife dreht - ein
        Kern, der beim Hochfahren steckengeblieben ist, dreht sich fröhlich
        weiter und meldete deshalb „gesund".

        Mit Schonfrist, und die ist wichtig: Der Wächter schaut alle fünf
        Sekunden nach. Ohne Frist würde er jeden normalen Start für einen
        Ausfall halten und einen laufenden Startvorgang abschiessen. Erst
        ein Start, der nach Minuten nicht fertig ist, IST ein Ausfall.
        """

        if not self.is_running():
            return False
        if self._boot_fertig:
            return True
        frist = float(self.config.get("system.boot_timeout_seconds", 300))
        return (time.time() - self._started_at) < max(30.0, frist)

    def gesundheit(self) -> dict[str, Any]:
        """Der ehrliche Zustand des Kerns, für Wächter und Anzeige.

        ``is_running()`` beantwortet nur die halbe Frage - dreht sich die
        Schleife noch? Ein Kern, der beim Hochfahren mitten im Ablauf
        stehengeblieben ist, dreht sich fröhlich weiter und kann trotzdem
        nichts. Deshalb steht hier beides.
        """

        return {
            "laeuft": self.is_running(),
            "hochgefahren": self._boot_fertig,
            "startfehler": dict(self.startfehler),
            "seit": self._started_at,
        }

    def stop(self) -> None:
        """Fährt AI-Orb geordnet herunter."""

        if self._loop is None:
            return

        async def _shutdown() -> None:
            # Das Mikrofon zuerst freigeben. Ein Assistent, der beim
            # Beenden noch eine Sekunde weiterhört, wäre genau das, was die
            # Datenschutzvorgabe ausschließt.
            await self.voice.stop()

            if self.terminerinnerung is not None:
                with contextlib.suppress(Exception):
                    await self.terminerinnerung.anhalten()

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

        # Aufräumen, sonst ist der Neustart eine Attrappe.
        #
        # ``start()`` kehrt sofort zurück, solange ``_thread`` gesetzt ist,
        # und ``get_runtime()`` gibt dieselbe Instanz zurück. Ohne diese
        # drei Zeilen tat der Neustart des Wächters also nichts: Er rief
        # stop(), rief start(), bekam ein wortloses Nichts - und meldete
        # danach zu Recht, der Kern laufe nicht. Nach drei solchen
        # Versuchen galt der Kern als endgültig ausgefallen, obwohl ihn nie
        # jemand wirklich neu gestartet hatte.
        self._loop = None
        self._thread = None
        self._ready.clear()
        self._boot_fertig = False
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
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # A timed-out HTTP/API caller must not leave its model or tool
            # task running invisibly in the core loop. Such orphaned turns
            # accumulated and made every following request slower.
            future.cancel()
            logger.warning("Auftrag nach %.1f s abgebrochen (Zeitlimit).", timeout)
            raise

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """Veröffentlicht ein Event threadsicher auf dem Event Bus."""

        if self._loop is None:
            return
        self.event_bus.publish_threadsafe(self._loop, event_name, payload or {})

    # --- Hauptfunktionen --------------------------------------------------------

    async def ask(self, text: str) -> CognitiveResponse:
        """Verarbeitet eine Benutzereingabe über das Cognitive Core."""

        return await self.cognitive.process(text)

    #: Wieviel Text hoechstens gesprochen wird.
    #:
    #: Frueher standen hier 1500 Zeichen, und der Rest wurde nur
    #: geschrieben. Das war eine Notbremse gegen Wartezeit: Damals
    #: entstand die gesamte Antwort, bevor das erste Wort kam. Seit die
    #: Stuecke einzeln und auf Abruf entstehen, gibt es diesen Grund
    #: nicht mehr - wer eine Vorlesung hoeren will, soll eine Vorlesung
    #: hoeren. Die Zahl bleibt als Schutz vor Ausreissern stehen, aber
    #: so hoch, dass sie im Alltag nie greift.
    SPRECH_GRENZE = 50000

    #: Wieviele Auftraege aufgehoben werden.
    AUFTRAEGE_MERKEN = 4

    #: Laenge des ersten Stuecks. Bewusst sehr kurz: Auf dieses eine
    #: Stueck wartet der Mensch, alle weiteren entstehen waehrend er
    #: zuhoert. Die Stimme braucht etwa 0,8 Sekunden je Sekunde Ton -
    #: neunzig Zeichen sind rund vier Sekunden Arbeit, dreihundert waeren
    #: vierzehn. Genau das war der Unterschied zwischen "antwortet" und
    #: "haengt".
    ERSTES_STUECK = 90

    #: Laenge der folgenden Stuecke. Groesser, weil jeder Aufruf der
    #: Stimme einen festen Aufschlag hat und hier niemand mehr wartet.
    WEITERE_STUECKE = 220

    #: Was den Chat oeffnet. Bewusst mehrere Formulierungen: Niemand
    #: merkt sich einen Wortlaut, und Whisper hoert selten zweimal
    #: dasselbe.
    CHAT_AUF = (
        "chat aktivieren", "chat oeffnen", "chat öffnen", "chat einschalten",
        "chat anzeigen", "chat an", "chat sichtbar", "zeig den chat",
        "zeige den chat", "zeig mir den chat", "chatfenster aktivieren",
        "chatfenster oeffnen", "chatfenster öffnen", "chatfenster anzeigen",
    )

    #: Und was ihn wieder schliesst.
    CHAT_ZU = (
        "chat schliessen", "chat schließen", "chat ausschalten", "chat aus",
        "chat zu", "chat verbergen", "chat ausblenden", "chatfenster schliessen",
        "chatfenster schließen", "chatfenster zu",
    )

    @staticmethod
    def _befehl_erkennen(text: str) -> str:
        """Erkennt einen Bedienbefehl - oder gibt eine leere Zeichenkette.

        Wird hier etwas erkannt, geht die Frage **nicht** an das Modell.
        Ein Befehl soll sofort wirken; ihn erst überlegen zu lassen wäre
        eine Denkpause für etwas, das keine Frage ist.
        """

        knapp = text.strip().lower().strip(".!?,;: ")
        # Ohne diese Zeile scheitert "Chat aktivieren." an dem Punkt, den
        # Whisper ans Ende setzt, und "chat  aktivieren" an dem doppelten
        # Leerzeichen, das beim Zoegern entsteht.
        knapp = " ".join(knapp.split())

        if knapp in Runtime.CHAT_AUF:
            return "chat_auf"
        if knapp in Runtime.CHAT_ZU:
            return "chat_zu"
        return ""

    @staticmethod
    def _fuers_sprechen(text: str, grenze: int) -> tuple[str, bool]:
        """Kuerzt einen Text auf ein hoerbares Mass."""

        if len(text) <= grenze:
            return text, False

        ausschnitt = text[:grenze]
        ende = max(ausschnitt.rfind(". "), ausschnitt.rfind("! "), ausschnitt.rfind("? "))
        if ende > grenze // 3:
            return ausschnitt[: ende + 1], True
        return ausschnitt.rstrip() + " …", True

    def _stuecke_bilden(self, text: str) -> list[str]:
        """Zerlegt die Antwort - das erste Stück kurz, die übrigen länger."""

        tts = self.voice.tts
        aufbereitet = tts.prepare_text(text)
        erste = tts.split_into_chunks(aufbereitet, max_characters=self.ERSTES_STUECK)
        if not erste:
            return [aufbereitet] if aufbereitet else []
        if len(erste) == 1:
            return erste

        rest = " ".join(erste[1:]).strip()
        weitere = tts.split_into_chunks(rest, max_characters=self.WEITERE_STUECKE)
        return [erste[0]] + (weitere or [rest])

    async def _teil_sprechen(self, auftrag: str, nummer: int) -> None:
        """Erzeugt ein einzelnes Sprechstück."""

        eintrag = self._sprechauftraege.get(auftrag)
        if eintrag is None:
            return

        # Der Vermerk "wird gerade gemacht" wird beim Anstossen gesetzt.
        # Er muss auf **jedem** Weg wieder verschwinden, auch auf den
        # kurzen: Bliebe er stehen, gaelte das Stueck fuer immer als in
        # Arbeit, und niemand wuerde es je erzeugen.
        try:
            if eintrag.get("abgebrochen"):
                return
            if nummer in eintrag["dateien"] or nummer in eintrag["fehler"]:
                return

            try:
                ergebnis = await self.voice.tts.speak(
                    eintrag["teile"][nummer], emotion="freundlich"
                )
            except Exception as fehler:  # noqa: BLE001 - ein Stück reißt den Rest nicht mit.
                logger.warning(
                    "Sprechstück %d von %s scheiterte: %s", nummer, auftrag, fehler
                )
                eintrag["fehler"][nummer] = str(fehler)
                return
        finally:
            eintrag["laeuft"].discard(nummer)

        if eintrag.get("abgebrochen"):
            return

        if ergebnis.succeeded and ergebnis.audio_path is not None:
            eintrag["dateien"][nummer] = ergebnis.audio_path.name
        else:
            eintrag["fehler"][nummer] = ergebnis.error or "keine Datei"
            logger.warning(
                "Sprechstück %d von %s ergab nichts: %s", nummer, auftrag, ergebnis.error
            )

    def _stueck_anstossen(self, auftrag: str, nummer: int) -> None:
        """Lässt ein Stück erzeugen - höchstens eines im Voraus.

        Vorher wurden alle Stücke sofort und so schnell wie möglich
        erzeugt. Das klang nach einer guten Idee und war der schwerste
        Fehler im ganzen Sprachweg: Die Stimme belegt sechs Rechenkerne,
        und während sie acht Stücke am Stück herstellte, musste die
        Spracherkennung der *nächsten* Frage sich den Rest teilen. Eine
        Erkennung, die sonst zehn Sekunden dauert, brauchte so
        sechsunddreißig.

        Gehört wird ohnehin in Echtzeit. Ein Stück Vorsprung genügt -
        alles darüber ist Arbeit, die niemandem nützt und der nächsten
        Frage im Weg steht.
        """

        eintrag = self._sprechauftraege.get(auftrag)
        if eintrag is None or eintrag.get("abgebrochen"):
            return
        if nummer < 0 or nummer >= len(eintrag["teile"]):
            return
        if nummer in eintrag["dateien"] or nummer in eintrag["fehler"]:
            return
        if nummer in eintrag["laeuft"]:
            return

        if self._loop is None:
            return

        # Von einem fremden Faden aus auf die Kern-Loop legen.
        #
        # `sprechstueck` wird vom HTTP-Server aufgerufen, und der
        # bearbeitet jede Anfrage in einem eigenen Faden. Dort gibt es
        # keine laufende Ereignisschleife - `create_task` scheitert
        # zwangslaeufig mit "There is no current event loop in thread".
        # `run_coroutine_threadsafe` ist genau dafuer da: Es reicht die
        # Arbeit an die Loop des Kerns weiter, egal von wo aus gefragt
        # wurde, und wartet dabei nicht.
        eintrag["laeuft"].add(nummer)
        try:
            asyncio.run_coroutine_threadsafe(
                self._teil_sprechen(auftrag, nummer), self._loop
            )
        except RuntimeError as fehler:
            # Die Loop ist gerade gegangen - der Orb faehrt herunter.
            eintrag["laeuft"].discard(nummer)
            logger.debug("Sprechstück nicht mehr angestoßen: %s", fehler)

    def sprechstueck(self, auftrag: str, nummer: int) -> tuple[str, str]:
        """Fragt nach einem Stück und stößt das nächste an.

        ``("da", name)``, ``("kommt", "")``, ``("weg", "")`` oder
        ``("nichts", grund)``.
        """

        eintrag = self._sprechauftraege.get(auftrag)
        if eintrag is None or eintrag.get("abgebrochen"):
            return "weg", ""
        if nummer < 0 or nummer >= len(eintrag["teile"]):
            return "weg", ""

        if nummer in eintrag["dateien"]:
            # Das übernächste vorbereiten, während dieses abgespielt wird.
            self._stueck_anstossen(auftrag, nummer + 1)
            return "da", eintrag["dateien"][nummer]

        if nummer in eintrag["fehler"]:
            return "nichts", eintrag["fehler"][nummer]

        # Noch nicht da und niemand arbeitet daran: jetzt anfangen.
        self._stueck_anstossen(auftrag, nummer)
        return "kommt", ""

    async def _auftrag_anlegen(self, stuecke: "str | list[str]") -> str:
        """Legt einen Sprechauftrag an und erzeugt sein erstes Stück.

        Auf dieses eine Stück wartet der Mensch; alle weiteren entstehen
        später und nur auf Abruf.
        """

        if isinstance(stuecke, str):
            stuecke = self._stuecke_bilden(stuecke) or [stuecke]

        auftrag = uuid.uuid4().hex[:12]
        self._sprechauftraege[auftrag] = {
            "teile": stuecke,
            "dateien": {},
            "fehler": {},
            "laeuft": set(),
            "abgebrochen": False,
        }
        while len(self._sprechauftraege) > self.AUFTRAEGE_MERKEN:
            self._sprechauftraege.popitem(last=False)

        await self._teil_sprechen(auftrag, 0)

        # Cloud-Stimme (OpenAI): alle weiteren Stuecke sofort anstossen.
        # Der Grund fuer "eins nach dem anderen" war die Rechenlast der
        # LOKALEN Stimme. In der Cloud kostet das hier nichts - und das
        # Geraet muss nie auf ein Stueck warten. Gewartet hat es bisher
        # mitten in der Antwort, und auf dem iPhone brach die Stimme dabei
        # ab (12.11.2026).
        if self._stimme_in_der_cloud():
            for nummer in range(1, len(stuecke)):
                self._stueck_anstossen(auftrag, nummer)
        return auftrag

    def _stimme_in_der_cloud(self) -> bool:
        tts = getattr(getattr(self, "voice", None), "tts", None)
        aktiv = getattr(tts, "_active", None)
        if aktiv is None:
            reihe = getattr(tts, "_engines", None) or []
            aktiv = reihe[0] if reihe else None
        return str(getattr(aktiv, "name", "") or "") in {
            "openai_tts", "elevenlabs", "edge_neural", "remote_tts", "speechgen",
        }

    def _alte_auftraege_abbrechen(self) -> None:
        """Beendet das Sprechen der vorigen Antwort.

        Wer eine neue Frage stellt, hat die alte Antwort abgehakt. Ihre
        restlichen Stücke weiter zu erzeugen kostet genau die Rechenzeit,
        die die neue Frage braucht.
        """

        for eintrag in self._sprechauftraege.values():
            eintrag["abgebrochen"] = True

    #: Nach einer Antwort aufs Handy so lange ohne "Hey Synapse" weiterreden.
    GERAET_NACHFRAGE_SEKUNDEN = 120.0

    async def _dauerhoeren_pruefen(self, aufnahme: Path) -> dict[str, Any] | None:
        """Freihaendig vom Handy (12.11.2026): nur mit Weckwort antworten.

        Das Handy hoert dauerhaft und schickt jedes Stueck Sprache. Hier
        wird entschieden, ob es gemeint war: "Hey Synapse ..." oder kurz
        nach einer Antwort. Alles andere wird still verworfen - und, das ist
        wichtig, bricht die laufende Antwort NICHT ab.

        Gibt ``None`` zurueck, wenn es eine Frage ist, die beantwortet werden
        soll (der Text liegt dann in ``self._dauer_frage``), sonst das
        Ergebnis fuer das Geraet.
        """

        transcript = await self.voice.transcriber.transcribe(aufnahme)
        frage = transcript.text.strip()
        self._dauer_frage = ""
        if not frage:
            return {"frage": "", "antwort": "", "auftrag": "", "teile": 0, "grund": "still"}

        try:
            from backend.voice.voice_pipeline import (
                _ist_whisper_phantom,
                _ueberwiegend_fremde_schrift,
            )

            if _ist_whisper_phantom(frage) or _ueberwiegend_fremde_schrift(frage):
                return {"frage": "", "antwort": "", "auftrag": "", "teile": 0, "grund": "rauschen"}
        except Exception:  # noqa: BLE001
            pass

        treffer = self.voice._wake_word.detect(frage)
        offen = time.monotonic() < float(getattr(self, "_geraet_offen_bis", 0.0))
        if not treffer.detected and not offen:
            logger.info("Handy hoert mit, ohne Weckwort: %r", frage[:80])
            return {"frage": "", "antwort": "", "auftrag": "", "teile": 0,
                    "grund": "kein_weckwort"}

        self._alte_auftraege_abbrechen()
        if treffer.detected and not treffer.has_command:
            # Nur "Hey Synapse": kurz bestaetigen und zuhoeren.
            self._geraet_offen_bis = time.monotonic() + self.GERAET_NACHFRAGE_SEKUNDEN
            auftrag = await self._auftrag_anlegen("Ja?")
            return {"frage": frage, "antwort": "Ja?", "auftrag": auftrag, "teile": 1,
                    "zuhoeren": True}

        self._dauer_frage = frage
        return None

    async def stimme_vom_geraet(self, aufnahme: Path, *, dauer: bool = False) -> dict[str, Any]:
        """Eine Aufnahme von einem anderen Gerät: erkennen, antworten, sprechen.

        Das Mikrofon sitzt im iPad, und die Antwort soll dort zu hören
        sein, nicht aus Lautsprechern, vor denen niemand steht.

        Gesprochen wird stückweise und auf Abruf: Das erste, bewusst
        kurze Stück entsteht sofort, jedes weitere erst, wenn das
        vorherige abgeholt wird.

        Args:
            aufnahme: Eine WAV-Datei, 16 kHz, einkanalig.

        Returns:
            Was verstanden wurde, was geantwortet wird, und woher die
            Sprechstücke zu holen sind.
        """

        # Das PC-Mikrofon ruht, solange das Handy im Gespraech ist - sonst
        # antwortet der PC auf dasselbe, nur halb verstanden (12.11.2026).
        try:
            self.voice.lokal_ruhig_bis = time.monotonic() + float(
                self.config.get("voice.geraet_ruhe_sekunden", 600) or 0
            )
        except Exception:  # noqa: BLE001
            pass

        if dauer:
            vorab = await self._dauerhoeren_pruefen(aufnahme)
            if vorab is not None:
                return vorab
            frage = self._dauer_frage
            transcript = type("T", (), {"confidence": 0.9})()
        else:
            # Zuerst die alte Antwort verstummen lassen - sonst rechnet die
            # Stimme noch, während die Erkennung schon anfängt.
            self._alte_auftraege_abbrechen()

            transcript = await self.voice.transcriber.transcribe(aufnahme)
            frage = transcript.text.strip()

        if not frage:
            logger.info("Aufnahme vom Gerät enthielt keine erkennbare Sprache.")
            return {"frage": "", "antwort": "", "auftrag": "", "teile": 0,
                    "grund": "nichts_erkannt"}

        befehl = self._befehl_erkennen(frage)
        if befehl:
            logger.info("Bedienbefehl vom Gerät: %s (%s)", frage, befehl)
            bestaetigung = "Chat ist offen." if befehl == "chat_auf" else "Chat ist zu."
            auftrag = await self._auftrag_anlegen(bestaetigung)
            return {
                "frage": frage,
                "antwort": bestaetigung,
                "befehl": befehl,
                "auftrag": auftrag,
                "teile": 1,
                "sicherheit": round(transcript.confidence, 3),
            }

        logger.info("Frage vom Gerät: %s", frage)

        from backend.tools import handy_tools

        handy_tools.geraet_aktiv(True)
        try:
            antwort = await self.cognitive.process(frage, spoken=True)
        finally:
            handy_tools.geraet_aktiv(False)
        aktionen = handy_tools.aktionen_abholen()
        text = str(getattr(antwort, "response", "") or "").strip()

        if not text:
            return {"frage": frage, "antwort": "", "auftrag": "", "teile": 0,
                    "aktionen": aktionen}

        gesprochen, gekuerzt = self._fuers_sprechen(text, self.SPRECH_GRENZE)
        stuecke = self._stuecke_bilden(gesprochen) or [gesprochen]
        auftrag = await self._auftrag_anlegen(stuecke)
        # Nach jeder Antwort darf ohne Weckwort weitergeredet werden.
        self._geraet_offen_bis = time.monotonic() + self.GERAET_NACHFRAGE_SEKUNDEN

        logger.info(
            "Antwort für das Gerät: %d Zeichen in %d Stück(en), erstes %d Zeichen%s",
            len(text),
            len(stuecke),
            len(stuecke[0]),
            " (gekürzt gesprochen)" if gekuerzt else "",
        )

        return {
            "frage": frage,
            "antwort": text,
            "auftrag": auftrag,
            "teile": len(stuecke),
            "gekuerzt": gekuerzt,
            "sicherheit": round(transcript.confidence, 3),
            # Knoepfe fuer das Handy: anrufen, Nachricht, App, PDF (12.11.2026).
            "aktionen": aktionen,
        }

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
