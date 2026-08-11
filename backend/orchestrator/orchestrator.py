"""Orchestrator – die Verteilungsschicht von AI-Orb.

Der Orchestrator analysiert jede Anfrage, bestimmt Intention und benötigte
Module und entscheidet insbesondere, **ob überhaupt ein Sprachmodell
benötigt wird**. Aufgaben wie "Datei öffnen", "Firefox starten" oder
"Terminal öffnen" werden vollständig lokal erledigt.

Der Orchestrator führt niemals selbst Systembefehle aus; sämtliche
Aktionen laufen über definierte Module (Sicherheitsvorgabe).

In AI-Orb v3 wird der Orchestrator vom Cognitive Core angesteuert und
arbeitet mit dem Agenten-Team zusammen; seine hier definierte Schnittstelle
bleibt dabei unverändert.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.events.event_bus import EventBus
from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.conversation_manager import ConversationManager
from backend.orchestrator.intent_classifier import IntentClassifier, IntentResult
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import ProviderError
from backend.orchestrator.speech_stream import SpeechStream, remaining_after
from backend.orchestrator.task_router import RouteResult, TaskRouter
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wörter, die eine Frage nach dem JETZT kennzeichnen.
#:
#: Eine Wortliste ist grob, und ich schreibe das hier hin, damit es
#: niemand für elegant hält: Sie wird Fälle übersehen und gelegentlich
#: einen zu viel fangen. Der Vergleich ist aber nicht "Wortliste gegen
#: perfekte Erkennung", sondern "Wortliste gegen ein Modell, das in der
#: Hälfte der Fälle nicht sucht". Ein überflüssiger Suchlauf kostet eine
#: Sekunde; eine ausgedachte Nachricht kostet das Vertrauen.
_JETZT_WOERTER: tuple[str, ...] = (
    "aktuell", "aktuelle", "aktuellen", "aktuelles", "neueste", "neuesten",
    "news", "nachricht", "nachrichten", "schlagzeile", "schlagzeilen",
    "heute", "gestern", "gerade", "momentan", "derzeit", "zurzeit",
    "inzwischen", "mittlerweile", "soeben", "eben erst", "diese woche",
    "letzte woche", "in den letzten", "stand der dinge", "wie steht es",
    "was ist los", "was gibt es neues", "was passiert", "letzter stand",
    "liveblog", "livestream", "wetter", "kurs", "preis", "börse", "boerse",
    "wechselkurs", "spielstand", "ergebnis von heute",
)

#: Wendungen, die ausdrücklich zur Suche auffordern.
_SUCHAUFTRAEGE: tuple[str, ...] = (
    "such", "suche", "recherchier", "schau nach", "sieh nach", "guck nach",
    "google", "im internet", "im netz", "nachschlagen", "nachsehen",
)


def braucht_aktuelles(text: str) -> bool:
    """Ob eine Frage Wissen von JETZT verlangt.

    Zwei Wege führen zu ja: Der Benutzer fragt nach etwas Gegenwärtigem,
    oder er bittet ausdrücklich um eine Suche. Das zweite ist eine
    Anweisung und keine Gesprächsfloskel - ihr ist zu folgen.

    Ausdrücklich NICHT dabei ist die blosse Jahreszahl. "Was geschah
    1789?" braucht keine Suche, und eine Regel, die auf Jahreszahlen
    anspringt, würde bei einem Geschichtsprofessor bei jeder zweiten
    Frage suchen.
    """

    knapp = " " + " ".join(text.lower().split()) + " "
    if any(f" {wort}" in knapp for wort in _SUCHAUFTRAEGE):
        return True
    return any(wort in knapp for wort in _JETZT_WOERTER)



@dataclass
class OrchestrationResult:
    """Vollständiges Ergebnis einer orchestrierten Anfrage."""

    response: str
    intent: str
    used_llm: bool
    provider: str | None = None
    model: str | None = None
    module: str = ""
    duration_seconds: float = 0.0
    requires_confirmation: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "intent": self.intent,
            "used_llm": self.used_llm,
            "provider": self.provider,
            "model": self.model,
            "module": self.module,
            "duration_seconds": round(self.duration_seconds, 3),
            "requires_confirmation": self.requires_confirmation,
            "data": self.data,
        }


class Orchestrator:
    """Zentrale Verteilungsstelle für Benutzeranfragen."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        provider_manager: ProviderManager,
        event_bus: EventBus | None = None,
        classifier: IntentClassifier | None = None,
        router: TaskRouter | None = None,
    ) -> None:
        self._memory = memory
        self._providers = provider_manager
        self._event_bus = event_bus
        self._config = get_config()
        self.classifier = classifier or IntentClassifier()
        self.router = router or TaskRouter()
        self.conversations = ConversationManager(memory)
        self._last_decision: dict[str, Any] = {}
        #: Die Werkzeugschleife. Wird nach dem Aufbau angeschlossen (siehe
        #: attach_tool_engine) – zur Bauzeit des Orchestrators gibt es sie
        #: noch nicht.
        self._tool_engine: Any | None = None
        #: Die Ablaufmaschine. Wird nachgereicht wie die Werkzeugschleife –
        #: zur Bauzeit des Orchestrators gibt es sie noch nicht.
        self._workflows: Any | None = None

    def attach_workflows(self, workflows: Any) -> None:
        """Schliesst die Ablaufmaschine an.

        Erst damit lassen sich Abläufe im Gespräch auslösen. Vorher gab es
        die Auslöser zwar, aber niemanden, der sie abfragte.
        """

        self._workflows = workflows

    def attach_tool_engine(self, tool_engine: Any) -> None:
        """Schließt die Werkzeugschleife an.

        Vorher konnte das Modell in Gesprächen keine Werkzeuge benutzen:
        Der Orchestrator fragte das Modell direkt, ohne ihm die Werkzeuge
        auch nur zu nennen. Auf „such das mal im Internet" blieb dem Modell
        nur die Auskunft, es könne das nicht – was klang wie ein
        Berechtigungsproblem, aber schlicht ein fehlender Anschluss war.
        """

        self._tool_engine = tool_engine

    # --- Hauptablauf ------------------------------------------------------------

    #: Die Anweisung für gesprochene Antworten.
    #:
    #: Der Grund ist gemessen, nicht vermutet: Ohne sie schrieb das Modell
    #: auf eine gewöhnliche Frage rund 260 Wörter. Das Modell braucht dafür
    #: doppelt so lange, und vorgelesen sind es fast zwei Minuten – der
    #: Benutzer sitzt also zwei Minuten vor einem Vortrag, den er nicht
    #: erbeten hat. Mit dieser Anweisung sind es 60 Wörter und eine halbe
    #: Minute. Wer mehr will, fragt nach.
    SPOKEN_BREVITY = (
        "DEINE ANTWORT WIRD VORGELESEN. Deshalb:\n"
        "- Fasse dich auf zwei bis vier Sätze. Sag das Wichtigste zuerst.\n"
        "- Keine Aufzählungen, keine Überschriften, keine Klammerzusätze – "
        "das lässt sich nicht vorlesen.\n"
        "- Ist das Thema größer, sage das Wesentliche und biete in einem "
        "kurzen Satz an, mehr auszuführen. Halte keinen Vortrag, den "
        "niemand erbeten hat.\n"
        "- Wird ausdrücklich nach einer ausführlichen Darstellung gefragt, "
        "gilt diese Beschränkung nicht."
    )

    async def handle(
        self,
        text: str,
        *,
        project_id: str | None = None,
        extra_context: str | None = None,
        spoken: bool = False,
        on_speech: Callable[[str], Awaitable[bool]] | None = None,
    ) -> OrchestrationResult:
        """Verarbeitet eine Benutzeranfrage vollständig.

        Ablauf: Intent-Klassifikation → Routing → gegebenenfalls
        Modellanfrage → Speicherung relevanter Informationen.

        Args:
            text: Die Benutzereingabe.
            project_id: Optionales aktives Projekt; sorgt dafür, dass
                Kontext und Erinnerungen projektbezogen bleiben.
            extra_context: Zusätzlicher Kontext, den übergeordnete
                Schichten (Cognitive Core, Agenten) beisteuern.

        Returns:
            Das Ergebnis inklusive Angabe, welcher Weg gewählt wurde.
        """

        started = time.perf_counter()
        self._providers.begin_conversation()

        if project_id is not None:
            self.conversations.set_project(project_id)

        intent = self.classifier.classify(text)
        await self._publish("ai.intent.classified", intent.to_dict())

        # Löst der Satz einen hinterlegten Ablauf aus?
        #
        # Das war der Sinn der Auslöser von Anfang an, nur fragte sie nie
        # jemand ab: Abläufe liessen sich ausschliesslich über ihre Kennung
        # starten – also über die Oberfläche, nie im Gespräch. Ein Ablauf,
        # den man nur mit seiner Nummer aufrufen kann, ist keine
        # Automatisierung, sondern ein Menüpunkt.
        ablauf = await self._ablauf_versuchen(text)
        if ablauf is not None:
            ablauf.duration_seconds = time.perf_counter() - started
            await self._publish("ai.response", ablauf.to_dict())
            return ablauf

        route = await self.router.route(text, intent)

        self._last_decision = {
            "text": text,
            "intent": intent.to_dict(),
            "route": route.to_dict(),
            "at": time.time(),
        }

        if route.handled_locally and not route.requires_llm:
            self.conversations.add_user_message(text)
            self.conversations.add_assistant_message(route.response)
            result = OrchestrationResult(
                response=route.response,
                intent=intent.intent,
                used_llm=False,
                module=route.module,
                requires_confirmation=route.requires_confirmation,
                data=route.data,
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        result = await self._answer_with_model(
            text,
            intent=intent,
            route=route,
            project_id=project_id,
            extra_context=extra_context,
            spoken=spoken,
            on_speech=on_speech,
        )
        result.duration_seconds = time.perf_counter() - started
        await self._publish("ai.response", result.to_dict())
        return result

    async def _ablauf_versuchen(self, text: str) -> OrchestrationResult | None:
        """Startet einen Ablauf, wenn ein Auslöser im Satz steckt.

        Gibt ``None`` zurück, wenn keiner passt – dann geht es den
        gewöhnlichen Weg weiter. Ein Fehler hier darf nie eine Antwort
        verhindern: Im Zweifel antwortet der Orb lieber selbst, als wegen
        eines Ablaufs zu schweigen.
        """

        if self._workflows is None:
            return None

        try:
            ablauf = self._workflows.find_by_trigger(text)
            if ablauf is None:
                return None

            logger.info("Ablauf '%s' durch den Satz ausgelöst.", ablauf.name)
            bericht = await self._workflows.run(ablauf.id)
        except Exception:  # noqa: BLE001
            logger.exception("Der ausgelöste Ablauf ist gescheitert.")
            return None

        # Der Bericht ist ein Objekt, kein Wörterbuch – und was es genau
        # anbietet, hängt an der Ablaufmaschine. Deshalb vorsichtig lesen
        # und im Zweifel schlicht bestätigen.
        antwort = ""
        for feld in ("summary", "zusammenfassung"):
            wert = getattr(bericht, feld, None)
            if callable(wert):
                wert = wert()
            if isinstance(wert, str) and wert.strip():
                antwort = wert.strip()
                break
        if not antwort:
            antwort = f"Der Ablauf '{ablauf.name}' ist durchgelaufen."
        self.conversations.add_user_message(text)
        self.conversations.add_assistant_message(antwort)
        return OrchestrationResult(
            response=antwort,
            intent="ablauf",
            used_llm=False,
            module="workflows",
            data={
                "ablauf": ablauf.id,
                "bericht": bericht.to_dict() if hasattr(bericht, "to_dict") else {},
            },
        )

    async def _answer_with_model(
        self,
        text: str,
        *,
        intent: IntentResult,
        route: RouteResult,
        project_id: str | None,
        extra_context: str | None,
        spoken: bool = False,
        on_speech: Callable[[str], Awaitable[bool]] | None = None,
    ) -> OrchestrationResult:
        """Beantwortet eine Anfrage mit Hilfe eines Sprachmodells."""

        self.conversations.add_user_message(text)
        await self.conversations.maybe_compress()

        memory_context = self._memory.context_for(text, project_id=project_id)
        context_block = self._format_context(memory_context, extra_context)

        # Gesprochene Antworten kurz halten – gemessen der grösste Hebel
        # gegen lange Wartezeiten.
        if spoken:
            context_block = "\n\n".join(
                part for part in (context_block, self.SPOKEN_BREVITY) if part
            )

        # Bei einer Frage nach Aktuellem wird VORHER gesucht.
        #
        # Das ist der Unterschied zwischen festverdrahtet und überredet.
        # Bisher stand in der Anweisung, das Modell solle bei allem
        # Aktuellen suchen - und es tat es mal, und mal nicht. Im
        # Protokoll des Benutzers steht beides innerhalb weniger Minuten:
        # zweimal gesucht und gelesen, dreimal aus dem Gedächtnis
        # geantwortet. Eine Anweisung, die in der Hälfte der Fälle befolgt
        # wird, ist keine Lösung, sondern eine Hoffnung.
        #
        # Wo die Entscheidung ohnehin feststeht, muss man sie nicht
        # delegieren. Fragt jemand nach Nachrichten, dann IST zu suchen -
        # da gibt es nichts zu entscheiden. Also wird gesucht, und das
        # Ergebnis liegt dem Modell vor, wenn es zu denken anfängt.
        tools_available = self._tool_engine is not None and self._tool_engine.enabled
        if tools_available and braucht_aktuelles(text):
            frisch = await self._vorab_suchen(text)
            if frisch:
                context_block = "\n\n".join(
                    part for part in (context_block, frisch) if part
                )

        # Und bei einer Fachfrage in den EIGENEN Quellen.
        #
        # Der Benutzer hat das unmissverständlich verlangt: "er soll aber
        # die Suchmaschinen die verlinkt sind auch wirklich nutzen …
        # sonst bringt die Funktion nichts."
        #
        # Er hat recht, und es ist derselbe Punkt wie oben. Die Anweisung,
        # die Favoriten zu befragen, steht seit Wochen im Systemprompt des
        # Professors - und in keinem einzigen Protokoll taucht ein Aufruf
        # auf. Was verlässlich geschehen soll, gehört nicht in eine Bitte
        # an das Sprachmodell, sondern in den Ablauf.
        if tools_available and self._ist_fachfrage(text, extra_context):
            eigenes = await self._vorab_eigene_quellen(text)
            if eigenes:
                context_block = "\n\n".join(
                    part for part in (context_block, eigenes) if part
                )
        if tools_available:
            instructions = self._tool_engine.system_instructions()
            context_block = "\n\n".join(
                part for part in (context_block, instructions) if part
            )

        messages = self.conversations.build_messages(extra_context=context_block)

        strom: SpeechStream | None = None
        #: Ob wirklich etwas zu hören war – nicht bloss, ob Text an die
        #: Sprachausgabe gereicht wurde.
        #:
        #: Der Unterschied ist der ganze Fehler, der den Orb verstummen
        #: liess: Vorher galt eine Antwort als gesprochen, sobald der Satz
        #: weitergegeben war. Schlug die Sprachausgabe still fehl, meldete
        #: der Weg trotzdem „schon gesagt" – und die Sprachschicht
        #: verzichtete darauf, sie noch einmal zu sprechen. Der Orb dachte,
        #: antwortete, hielt es für erledigt und blieb stumm.
        wirklich_gesprochen = False

        try:
            if on_speech is not None:

                async def _sprich(satz: str) -> bool:
                    nonlocal wirklich_gesprochen
                    gehoert = bool(await on_speech(satz))
                    wirklich_gesprochen = wirklich_gesprochen or gehoert
                    return gehoert

                response, strom = await self._stream_and_speak(messages, _sprich)
            else:
                response = await self._providers.chat(messages)
        except ProviderError as error:
            logger.error("Keine Modellantwort möglich: %s", error)
            fallback = (
                "Ich kann gerade kein Sprachmodell erreichen. "
                "Prüfe bitte deine Internetverbindung oder ob Ollama lokal läuft. "
                "Lokale Aufgaben (Programme starten, Dateien suchen, Aufgaben verwalten) "
                "funktionieren weiterhin."
            )
            self.conversations.add_assistant_message(fallback)
            return OrchestrationResult(
                response=fallback,
                intent=intent.intent,
                used_llm=False,
                module="ai_provider",
                data={"error": str(error)},
            )

        answer_text = response.text
        tool_runs = 0
        if tools_available:
            # Enthält die Antwort Werkzeugaufrufe, hier ausführen – mit
            # Sicherheitsprüfung und Prüfprotokoll, im selben Gespräch.
            answer_text, runs = await self._tool_engine.continue_with_tools(
                messages, response.text, actor="gespraech"
            )
            tool_runs = len(runs)

        # Was während des Denkens schon gesprochen wurde, darf nicht noch
        # einmal kommen. Nach einem Werkzeugaufruf steht meist eine ganz
        # neue Antwort da – dann wird sie vollständig gesprochen; ohne
        # Werkzeug bleibt höchstens der Schlusssatz übrig.
        if strom is not None:
            rest = remaining_after(strom.spoken, answer_text)
            if rest and on_speech is not None:
                if await on_speech(rest):
                    wirklich_gesprochen = True

        self.conversations.add_assistant_message(answer_text)

        # Relevante Informationen aus der Benutzereingabe merken.
        self._memory.remember(
            text,
            kind="knowledge",
            project_id=project_id,
            source="gespräch",
        )

        return OrchestrationResult(
            response=answer_text,
            intent=intent.intent,
            used_llm=True,
            provider=response.provider,
            model=response.model,
            module=route.module or "ai_provider",
            data={
                "latency": round(response.latency_seconds, 3),
                "werkzeugaufrufe": tool_runs,
                # Sagt der Sprachschicht: Diese Antwort war wirklich zu
                # hören. Ohne diesen Vermerk käme sie ein zweites Mal – mit
                # einem falschen gar nicht.
                "gesprochen": wirklich_gesprochen,
            },
        )

    async def _stream_and_speak(
        self,
        messages: list[Any],
        on_speech: Callable[[str], Awaitable[bool]],
    ) -> tuple[Any, SpeechStream]:
        """Holt die Antwort stückweise und spricht jeden fertigen Satz sofort.

        Damit beginnt der Orb zu reden, während er den Rest noch denkt. Die
        gemessene Wartezeit ändert sich dadurch nicht – die empfundene
        halbiert sich, und die ist die einzige, die jemand erlebt.

        Werkzeugaufrufe stehen als eingezäunter Block mitten in der
        Antwort; :class:`SpeechStream` hält sie zurück, damit nie
        Maschinensprache vorgelesen wird.

        Scheitert der Fluss, bleibt der gewöhnliche Weg: lieber die ganze
        Antwort auf einmal als gar keine.
        """

        from backend.orchestrator.providers.base_provider import ProviderResponse

        strom = SpeechStream()
        stuecke: list[str] = []
        begonnen = time.perf_counter()

        try:
            async for stueck in self._providers.chat_stream(messages):
                stuecke.append(stueck)
                for satz in strom.feed(stueck):
                    await on_speech(satz)
            for satz in strom.finish():
                await on_speech(satz)
        except ProviderError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Der Fluss ist gescheitert; die Antwort kommt am Stück.")
            if not stuecke:
                return await self._providers.chat(messages), SpeechStream()

        return (
            ProviderResponse(
                text="".join(stuecke),
                provider=self._providers.active_name or "",
                model="",
                latency_seconds=time.perf_counter() - begonnen,
                finish_reason="stop",
            ),
            strom,
        )

    def _ist_fachfrage(self, text: str, extra_context: str | None) -> bool:
        """Ob in den eigenen Quellen des Benutzers zu suchen ist.

        Zwei Wege, und der zweite ist der wichtigere.

        Der erste ist die Wortliste des Professors (``looks_academic``).
        Sie fängt vieles, aber nicht alles: „Welche Ursachen hatte der
        Investiturstreit?" enthält kein einziges ihrer Merkmale, weil
        Eigennamen dort naturgemäss fehlen. Eine Liste, die auch
        „Investiturstreit", „Sattelzeit" und „Reichsdeputationshauptschluss"
        kennt, ist nicht zu schreiben.

        Der zweite Weg umgeht das: Ist der Professor für diesen Zug im
        Dienst, IST es eine Fachfrage - er hat das bereits entschieden,
        und zwar mit mehr Wissen als eine Wortliste (laufender Vorgang,
        ausdrücklich verlangter Modus, Lernprofil). Statt seine
        Entscheidung nachzubauen, wird sie gelesen.

        Ausgenommen bleiben Fragen nach Aktuellem. Wer nach den
        Nachrichten von heute fragt, ist mit den Nachrichtenhäusern besser
        bedient als mit einem Archivportal - und zehn Suchläufe für eine
        Frage sind ohnehin zu viele.
        """

        # Erst hier eingebunden und nicht oben: Der Professor haengt am
        # Agentenpaket, das seinerseits ueber den Cognitive Core wieder
        # hierher zeigt. Ein Import auf Modulebene waere ein Ring, und
        # Python bricht Ringe mit einer Fehlermeldung ab, die niemand mit
        # dieser Zeile in Verbindung bringt.
        from backend.agents.history_agent.bridge import looks_academic

        if braucht_aktuelles(text):
            return False
        if looks_academic(text):
            return True
        # Der Professor baut den Systemprompt, wenn er übernimmt. Steht er
        # im Zusatzkontext, hat er sich für zuständig erklärt.
        return bool(extra_context) and "Geschichtsprofessor" in str(extra_context)

    async def _vorab_eigene_quellen(self, text: str) -> str:
        """Sucht bei einer Fachfrage gezielt IN den Favoriten des Benutzers.

        Nicht in den Lesezeichen - in den Seiten, auf die sie zeigen. Das
        ist der Unterschied, wegen dem die Funktion vorher nichts brachte:
        Ein Archivportal in der Leiste war ein Link und keine Quelle.
        """

        einstellungen = self._config.get("recherche.favoriten", {}) or {}
        if not bool(einstellungen.get("nutzen", True)):
            return ""
        if self._tool_engine is None:
            return ""

        from backend.research.eigene_quellen import eigene_domaenen
        from backend.tools.web_tools import (
            mehrquellensuche,
            quellen_gegenueberstellen,
        )

        domaenen = await asyncio.to_thread(
            eigene_domaenen,
            ordner=str(einstellungen.get("ordner", "") or ""),
            hoechstens=int(einstellungen.get("max_domaenen", 4) or 4),
        )
        if not domaenen:
            logger.info(
                "Keine brauchbaren Favoriten gefunden - es bleibt bei der "
                "gewöhnlichen Suche."
            )
            return ""

        quellen = [
            {"name": f"deine Quelle: {d}", "einschraenkung": f"site:{d}"}
            for d in domaenen
        ]
        gesammelt = await mehrquellensuche(
            text,
            quellen,
            je_quelle=int(einstellungen.get("treffer_je_domaene", 3) or 3),
        )
        if not gesammelt:
            logger.info("In den eigenen Quellen war zu %r nichts zu finden.", text[:60])
            return ""

        logger.info(
            "In %d eigenen Quellen gesucht, %d davon mit Treffern.",
            len(quellen),
            len(gesammelt),
        )
        return (
            "AUS DEN EIGENEN QUELLEN DES BENUTZERS (seine Favoriten - über "
            "Jahre gesammelte, geprüfte Anlaufstellen). Diese gehen einem "
            "beliebigen Suchtreffer vor und sind eher zitierfähig. Nenne, "
            "aus welcher seiner Quellen etwas stammt, und lies mit "
            "'webseite_lesen' nach, wenn die Trefferzeile nicht reicht:\n\n"
            + quellen_gegenueberstellen(gesammelt)
        )

    async def _vorab_suchen(self, text: str) -> str:
        """Sucht zu einer Frage nach Aktuellem und gibt das Ergebnis zurück.

        Scheitert die Suche, wird das ebenfalls mitgegeben - und zwar im
        Klartext. Das ist wichtiger, als es klingt: Ein Modell, das nicht
        weiss, dass die Suche versagt hat, erfindet an ihrer Stelle etwas
        Plausibles. Eines, dem man es sagt, kann es dem Benutzer sagen.
        """

        if self._tool_engine is None:
            return ""

        # Mehrere Häuser statt eines besten Treffers.
        #
        # Der Benutzer fragte, ob auch andere Berichterstattung einfliesst -
        # Al Jazeera etwa. Vorher nicht: Der Orb las, was oben stand, und
        # das ist bei deutschen Fragen fast immer tagesschau oder zdfheute.
        #
        # Wer wissen will, wie über einen Konflikt BERICHTET wird, braucht
        # nicht den besten Treffer, sondern mehrere Darstellungen
        # nebeneinander. Der beste Treffer leistet das nicht: Er ist eine
        # Sicht, die sich als die Sache ausgibt.
        mehr = await self._vorab_mehrquellen(text)
        if mehr:
            return mehr

        try:
            lauf = await self._tool_engine.direkt_ausfuehren(
                "internet_suchen", {"suchbegriff": text, "max_treffer": 5}
            )
        except Exception:  # noqa: BLE001 - eine Vorabsuche darf nie die Antwort verhindern.
            logger.exception("Die Vorabsuche ist gescheitert.")
            return ""

        if lauf.result.ok and lauf.result.output:
            logger.info("Vorab gesucht zu %r (%.1f s).", text[:60], lauf.seconds)
            return (
                "FRISCH GESUCHT - diese Treffer sind von jetzt und gehen deinem "
                "eigenen Wissensstand vor. Stützte deine Antwort darauf und nenne, "
                "woher sie stammt. Reicht dir das nicht, lies mit 'webseite_lesen' "
                "nach:\n\n" + str(lauf.result.output)
            )

        logger.warning("Die Vorabsuche brachte nichts: %s", lauf.result.error)
        return (
            "HINWEIS: Ich habe für diese Frage zu suchen versucht, und es hat "
            "nicht geklappt: " + str(lauf.result.error or "kein Ergebnis") +
            " Sage dem Benutzer, dass die Suche gerade nicht geht, statt aus dem "
            "Gedächtnis zu antworten."
        )

    async def _vorab_mehrquellen(self, text: str) -> str:
        """Befragt mehrere Häuser parallel und stellt sie gegenüber."""

        if not bool(self._config.get("recherche.mehrquellen", True)):
            return ""
        quellen = self._config.get("recherche.quellen", []) or []
        if not quellen:
            return ""

        from backend.tools.web_tools import (
            mehrquellensuche,
            quellen_gegenueberstellen,
        )

        gesammelt = await mehrquellensuche(
            text,
            [dict(q) for q in quellen],
            je_quelle=int(self._config.get("recherche.treffer_je_quelle", 3) or 3),
            gleichzeitig=int(self._config.get("recherche.gleichzeitig", 4) or 4),
        )
        # Unter zwei Häusern gibt es nichts gegenüberzustellen - dann ist
        # die gewöhnliche Suche ehrlicher als eine "Gegenüberstellung"
        # mit einem einzigen Beteiligten.
        if len(gesammelt) < 2:
            return ""

        logger.info(
            "Mehrquellensuche zu %r: %s", text[:50], ", ".join(gesammelt)
        )
        return (
            "FRISCH GESUCHT, BEI MEHREREN HÄUSERN. Diese Treffer sind von "
            "jetzt und gehen deinem eigenen Wissensstand vor.\n\n"
            "Sie stehen absichtlich nach Herkunft getrennt. Sage in deiner "
            "Antwort, WORIN sich die Darstellungen unterscheiden - in der "
            "Wortwahl, in dem, was betont oder weggelassen wird, in den "
            "Zahlen. Wo alle dasselbe berichten, sag auch das: Es ist ein "
            "Befund und keine Selbstverständlichkeit. Nenne die Häuser "
            "beim Namen; ein 'Berichten zufolge' ist wertlos.\n\n"
            + quellen_gegenueberstellen(gesammelt)
        )

    # --- Kontextaufbereitung ---------------------------------------------------

    @staticmethod
    def _format_context(memory_context: dict[str, Any], extra: str | None) -> str:
        """Formt den Gedächtniskontext in einen kompakten Systemtext um.

        Unsichere Informationen bleiben dabei als solche gekennzeichnet
        (Reasoning-Context-Anforderung).
        """

        lines: list[str] = []

        memories = memory_context.get("memories") or []
        if memories:
            lines.append("Bekanntes aus dem Gedächtnis:")
            for entry in memories:
                marker = "" if entry.get("certainty") == "fakt" else f" [{entry.get('certainty')}]"
                lines.append(f"- {entry['content']}{marker}")

        facts = memory_context.get("user_facts") or []
        if facts:
            lines.append("Bekanntes über den Benutzer:")
            lines.extend(f"- {fact}" for fact in facts)

        tasks = memory_context.get("open_tasks") or []
        if tasks:
            lines.append("Offene Aufgaben:")
            lines.extend(f"- {task}" for task in tasks)

        conversations = memory_context.get("conversations") or []
        if conversations:
            lines.append("Frühere Gespräche (zusammengefasst):")
            lines.extend(f"- {entry['content']}" for entry in conversations)

        if extra:
            lines.append(extra)

        if not lines:
            return ""

        lines.append(
            "Nutze diese Angaben nur, wenn sie zur Frage passen. "
            "Erfinde nichts hinzu und kennzeichne Unsicherheiten."
        )
        return "\n".join(lines)

    async def _publish(self, event_name: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(event_name, payload)

    # --- Transparenz -------------------------------------------------------------

    def explain_last_decision(self) -> dict[str, Any]:
        """Erklärt die zuletzt getroffene Weiterleitungsentscheidung.

        Beantwortet die Transparenzfragen "Warum hast du so entschieden?"
        und "Welche Strategie hast du gewählt?" mit nachvollziehbaren Daten,
        ohne interne Gedankengänge offenzulegen.
        """

        if not self._last_decision:
            return {"available": False, "message": "Es liegt noch keine Entscheidung vor."}

        intent = self._last_decision["intent"]
        route = self._last_decision["route"]
        return {
            "available": True,
            "erkannte_absicht": intent["intent"],
            "sicherheit": intent["confidence"],
            "ausschlaggebende_begriffe": intent["matched_keywords"],
            "bearbeitet_durch": route["module"] or "Sprachmodell",
            "sprachmodell_genutzt": not route["handled_locally"] or route["requires_llm"],
            "aktiver_provider": self._providers.active_name,
        }

    async def end_conversation(self) -> str | None:
        """Beendet die laufende Unterhaltung und sichert deren Zusammenfassung."""

        summary = await self.conversations.finish()
        await self._providers.end_conversation()
        return summary

    def status(self) -> dict[str, Any]:
        """Statusübersicht des Orchestrators."""

        return {
            "conversation": self.conversations.status(),
            "providers": self._providers.status(),
            "known_intents": self.classifier.intents,
        }
