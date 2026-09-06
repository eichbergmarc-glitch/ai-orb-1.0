"""Die Brücke zwischen dem Professor und dem gewöhnlichen Gespräch.

Der Professor war vollständig gebaut – sokratisches Lehren, Quellenkritik,
Forschungsfragen, Debatte, Lernprofil – und wurde
trotzdem nie wirksam. Der Grund war kein Fehler in seinen Modulen, sondern
eine fehlende Verbindung: Der Antwortweg des Orb führt über den
Orchestrator direkt zum Sprachmodell, und der Agent stand daneben, ohne
dass ihn je jemand fragte.

Diese Brücke schließt die Lücke – aber nicht, indem sie den Antwortweg
umleitet. Das wäre der teure Weg: Der Agent redet direkt mit dem
Sprachmodell und verlöre dabei alles, was am Hauptweg hängt – Werkzeuge
(also auch die Internetsuche), Gedächtnis, Gesprächsverlauf.

Stattdessen wird der Professor als **Blickwinkel** eingehängt: Er baut den
Systemprompt, der Hauptweg benutzt ihn. Der Orb bleibt derselbe, er denkt
nur wie ein Historiker – mit allen Werkzeugen in der Hand.

## Wann der Professor übernimmt

Nicht immer. „Öffne den Browser" sokratisch zu beantworten wäre albern.
Er meldet sich, wenn

* ein Modus ausdrücklich verlangt wird („prüfe mich", „Quellenkritik"),
* ein Vorgang schon läuft (eine begonnene Quellenanalyse endet nicht, weil
  zwischendurch etwas anderes gefragt wurde),
* oder das Thema erkennbar wissenschaftlich oder historisch ist.

Sonst schweigt er, und der Orb antwortet wie gewohnt.
"""

from __future__ import annotations

import re
import time
from typing import Any

from backend.agents.history_agent import (
    debate_engine,
    professor_engine,
    research_question_engine,
    socratic_engine,
    source_criticism,
)
from backend.agents.history_agent.learning_profile import LearningProfile
from backend.config import get_config
from backend.agents.history_agent.mentor_engine import MentorEngine
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


def _kennung() -> str:
    """Die Korrelations-Kennung des laufenden Zuges, falls eine anliegt."""

    from backend.system.performance_trace import current_turn_trace

    trace = current_turn_trace()
    return getattr(trace, "turn_id", "-") if trace is not None else "-"


_GENERAL_EXPLANATION_PROMPT = (
    "Du erklaerst wie ein ruhiger, klarer Professor: anschaulich, menschlich "
    "und ohne unnoetige Fachsprache. Antworte direkt in hoechstens drei "
    "kurzen Saetzen. Dies ist eine allgemeine Erklaerung, keine historische "
    "Recherche; fordere weder Quellen noch eine wissenschaftliche Analyse an."
)


#: Woran ein wissenschaftliches oder historisches Anliegen zu erkennen ist.
#:
#: Bewusst breit: Lieber einmal zu viel den Professor fragen als den
#: Benutzer bei einer Fachfrage mit einer beliebigen Auskunft abspeisen.
#: Die Liste deckt alle Lehrfelder des Orb ab.
_ACADEMIC_MARKERS: tuple[str, ...] = (
    # Fach und Methode
    "geschicht", "historisch", "historiker", "historiographie", "quelle",
    "quellen", "archiv", "epoche", "chronik", "überliefer", "ueberliefer",
    "forschung", "these", "argument", "beleg", "literatur", "fußnote",
    "fussnote", "zitat", "bibliograph", "methodik", "wissenschaft",
    "seminar", "vorlesung", "hausarbeit", "seminararbeit", "bachelor",
    "master", "dissertation", "exposé", "expose", "gliederung",
    # Philosophie
    "philosoph", "ethik", "erkenntnistheorie", "metaphysik", "ontolog",
    "logik", "argument", "prämisse", "praemisse", "konklusion",
    "sokrates", "platon", "aristoteles", "kant", "hegel", "nietzsche",
    "phänomenolog", "phaenomenolog", "existential", "sinnfeld",
    # Linguistik und Germanistik
    "linguistik", "sprachwissenschaft", "phonetik", "phonolog", "phonem",
    "morpholog", "morphem", "syntax", "semantik", "pragmatik",
    "soziolingu", "korpuslingu", "grammatik", "sprachwandel",
    "germanistik", "literaturwissenschaft", "literaturgeschichte",
    "textanalyse", "hermeneutik", "narratolog", "lyrik", "drama",
    "roman", "novelle", "goethe", "schiller", "kafka", "brecht",
    # Politik, Wirtschaft, Konflikte
    "politisch", "politik", "regierung", "verfassung", "revolution",
    "wirtschaft", "ökonom", "oekonom", "handel", "inflation", "krise",
    "krieg", "schlacht", "konflikt", "militär", "militaer", "armee",
    "vertrag", "bündnis", "buendnis", "kolonial", "reich", "imperium",
    "diktatur", "demokratie", "nationalsozial", "weimar", "antike",
    "mittelalter", "neuzeit", "aufklärung", "aufklaerung", "industrialisier",
)

#: Muster, die auf eine Jahreszahl oder einen Zeitraum deuten.
_YEAR_PATTERN = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9])\b")

#: Wörter, die einen Auftrag an den Rechner kennzeichnen – dort hat der
#: Professor nichts zu suchen, auch wenn zufällig ein Fachwort vorkommt.
#:
#: Diese werden auf GANZE WÖRTER geprüft, nicht als Teilzeichenfolge.
#: „Welche Rolle spielte die Wirtschaftskrise?" enthält „spiel", ist aber
#: eine historische Frage und kein Befehl, Musik abzuspielen. Ein
#: Teilstring-Vergleich schickte solche Fragen still am Professor vorbei –
#: ein Fehler, den niemand bemerkt hätte, weil trotzdem eine Antwort kam,
#: nur eben eine beliebige.
_COMMAND_MARKERS: tuple[str, ...] = (
    "öffne", "oeffne", "öffnen", "starte", "starten", "schließe", "schliesse",
    "spiel", "spiele", "abspielen", "lautstärke", "lautstaerke",
    "programm", "browser", "termin", "uhrzeit", "wetter", "installiere",
)

#: Mehrwortige Befehle, die als Wendung geprüft werden.
_COMMAND_PHRASES: tuple[str, ...] = (
    "zeig mir", "zeige mir", "mach auf", "mach zu", "such nach",
)

_WORD_PATTERN = re.compile(r"\w+", re.UNICODE)

_FACHFORTSETZUNGEN: tuple[str, ...] = (
    "fahre fort", "fahr fort", "mach weiter", "mache weiter",
    "nächster abschnitt", "nächsten abschnitt",
    "naechster abschnitt", "naechsten abschnitt",
)


def looks_academic(text: str) -> bool:
    """Ob es sich um ein wissenschaftliches oder historisches Anliegen handelt."""

    lowered = text.lower()
    words = set(_WORD_PATTERN.findall(lowered))

    # Ein klarer Auftrag an den Rechner bleibt ein Auftrag an den Rechner –
    # es sei denn, es steckt erkennbar ein Fachthema darin („zeig mir die
    # Quellenlage zum Dreißigjährigen Krieg").
    is_command = bool(words & set(_COMMAND_MARKERS)) or any(
        phrase in lowered for phrase in _COMMAND_PHRASES
    )
    has_academic = any(marker in lowered for marker in _ACADEMIC_MARKERS)

    if is_command and not has_academic:
        return False

    if has_academic:
        return True

    # Eine Jahreszahl in einer längeren Frage deutet auf Geschichte.
    return bool(_YEAR_PATTERN.search(lowered)) and len(text) > 30


class ProfessorSession:
    """Hält den Professor über ein Gespräch hinweg am Leben.

    Der laufende Modus und die begonnenen Vorgänge (Quellenkritik,
    Debatte) gehören hierher: Ein Professor, der bei jedem Satz vergisst,
    was er gerade tat, wäre keiner.
    """

    def __init__(self) -> None:
        self.profile = LearningProfile()
        self.mentor = MentorEngine()

        self._mode = ""
        self._fach = ""
        self._source: source_criticism.SourceAnalysis | None = None
        self._debate: debate_engine.DebateSession | None = None
        self._project: Any | None = None
        self._workshop: dict[str, str] = {}
        self._attempts = 0
        self._last_question = ""
        self._last_turn: professor_engine.ProfessorTurn | None = None
        self._socratic_pending = ""
        self._socratic_answer_attempts = 0

        # Der Zustand des Fachmodus - ausdrücklich, nicht mehr abgeleitet.
        #
        # Vorher liess sich nur fragen "läuft gerade ein Vorgang?"
        # (``busy``). Wann der Fachmodus ENDET, stand nirgends: Er endete
        # nie. Am 31.08.2026 durchsuchte der Professor deshalb zur Bitte
        # "suche nach einer Wohnung in Solothurn" die Vatikanische
        # Bibliothek und historicum.net - die Fachquellen des Benutzers,
        # mustergültig angewandt auf eine Mietwohnung.
        #
        # Drei Wege hinaus, alle hier festgehalten:
        #   1. Zeitablauf    - seit der letzten Fachäusserung ist zu viel Zeit.
        #   2. Themenwechsel - ein klarer fachfremder Handlungsauftrag.
        #   3. Abschluss     - der laufende Vorgang ist beendet.
        self._letzte_fachaeusserung = 0.0
        self._verlassen_grund = ""
        self._zeitablauf_sekunden = float(
            get_config().get("studium.professor_zeitablauf_sekunden", 900) or 900
        )

    # --- Entscheidung ------------------------------------------------------------

    def busy(self) -> bool:
        """Ob ein Vorgang läuft, der nicht unterbrochen werden darf.

        Jetzt mit Zeitablauf. Ein offener Vorgang ist ein Grund, beim Fach
        zu bleiben - aber nicht auf Dauer. Wer eine Viertelstunde nichts
        mehr dazu gesagt hat, führt kein Fachgespräch mehr, sondern hat
        eines geführt.
        """

        if self._abgelaufen():
            self._verlassen("Zeitablauf")
            return False
        if self._socratic_pending:
            return True
        if self._mode in ("quellenkritik", "forschungsfrage",
                          "debatte", "arbeitsbetreuung"):
            return True
        return self._source is not None or self._debate is not None

    def _abgelaufen(self) -> bool:
        """Ob seit der letzten Fachäusserung zu viel Zeit vergangen ist."""

        if self._zeitablauf_sekunden <= 0 or self._letzte_fachaeusserung <= 0:
            return False
        return (time.time() - self._letzte_fachaeusserung) > self._zeitablauf_sekunden

    def _verlassen(self, grund: str) -> None:
        """Beendet den Fachmodus und schreibt auf, warum.

        Der Grund ist kein Zierrat: Ohne ihn lässt sich im Protokoll nicht
        unterscheiden, ob der Professor nie übernommen hat oder ob er
        ausgestiegen ist.
        """

        if not (self._mode or self._fach or self._socratic_pending):
            return
        logger.info(
            "[%s] Tor 5 Professor verlaesst den Fachmodus "
            "(Fach: %s, Modus: %s) - %s.",
            _kennung(),
            self._fach or "keins",
            self._mode or "keiner",
            grund,
        )
        self._verlassen_grund = grund
        self._mode = ""
        self._fach = ""
        self._source = None
        self._debate = None
        self._workshop = {}
        self._socratic_pending = ""
        self._socratic_answer_attempts = 0
        self._attempts = 0
        self._last_turn = None

    def zustand(self) -> dict[str, Any]:
        """Der Zustand des Fachmodus - für Protokoll und Transparenzansicht."""

        return {
            "aktiv": bool(self._mode or self._fach or self._socratic_pending),
            "fach": self._fach,
            "modus": self._mode,
            "letzte_fachaeusserung": self._letzte_fachaeusserung,
            "zeitablauf_sekunden": self._zeitablauf_sekunden,
            "abgelaufen": self._abgelaufen(),
            "zuletzt_verlassen_wegen": self._verlassen_grund,
        }

    def should_engage(self, text: str) -> bool:
        """Ob der Professor bei dieser Äußerung übernehmen soll."""

        lowered = text.lower()

        # Ein ausdrücklich verlangter Modus schlägt alles.
        for _mode, triggers in professor_engine._MODE_TRIGGERS:  # noqa: SLF001
            if any(trigger in lowered for trigger in triggers):
                return True

        # Ein Handlungsauftrag ist keine Fachfortsetzung.
        #
        # ``busy()`` hielt den Professor über Themenwechsel hinweg fest.
        # Im Protokoll vom 31.08.2026 übernahm er deshalb die Wohnungssuche:
        # Zu "suche nach einer Wohnung in Solothurn" durchsuchte der Orb
        # historicum.net, gotriple.eu und die Vatikanische Bibliothek - die
        # akademischen Quellen des Benutzers, mustergültig angewandt auf
        # eine Mietwohnung.
        #
        # Wer den Orb bittet, etwas ZU TUN, will keinen Vortrag. Eine
        # fachlich klingende Bitte ("zeig mir ein Beispiel für eine
        # Quellenkritik") bleibt beim Professor, weil sie ``looks_academic``
        # besteht.
        if not looks_academic(text) and self._verlangt_eine_handlung(text):
            self._verlassen("fachfremder Handlungsauftrag")
            return False

        if self.busy():
            return True

        # Eine ausdrücklich fortgesetzte Fachvorlesung bleibt beim gewählten
        # Fach. Der Modus "erklären" ist absichtlich nicht generell busy –
        # sonst würde später selbst ein Wetterbefehl akademisch beantwortet.
        if self._fach and any(wendung in lowered for wendung in _FACHFORTSETZUNGEN):
            return True

        return looks_academic(text)

    @staticmethod
    def _verlangt_eine_handlung(text: str) -> bool:
        """Ob der Satz den Orb zu einer Handlung auffordert.

        Der Import steht absichtlich in der Funktion: Der Orchestrator kennt
        diese Brücke, und ein Import auf Modulebene liefe im Kreis.
        """

        try:
            from backend.orchestrator.faehigkeiten import entscheiden
        except Exception:  # noqa: BLE001 - im Zweifel bleibt alles wie bisher.
            return False
        # Dieselbe Entscheidung wie an Tor 4 und Tor 6, damit derselbe Satz
        # nicht an drei Stellen verschieden beurteilt wird. Eine eigene
        # Schluesselwortliste haette genau das getan.
        entscheidung = entscheiden(text, gesprochen=False, werkzeuge_vorhanden=True)
        return entscheidung.handlungsauftrag

    # --- Der Blickwinkel ----------------------------------------------------------

    def prompt_for(self, text: str, *, presence: dict[str, Any] | None = None) -> str:
        """Baut den Systemprompt für diesen Zug – oder gibt ``""`` zurück.

        Der Rückgabewert wird dem Hauptweg als zusätzlicher Kontext
        mitgegeben. Ein leerer Text bedeutet: Der Professor hält sich
        heraus.
        """

        try:
            if not self.should_engage(text):
                return ""

            detected_mode, _reason = professor_engine.detect_mode(
                text, current=self._mode
            )
            answering_socratic = bool(self._socratic_pending)
            # Eine ausdrueckliche Bitte um eine Erklaerung beendet die
            # Frageschleife sofort. Der Benutzer bleibt Herr des Lernmodus.
            if answering_socratic and detected_mode == "erklaeren":
                self._socratic_pending = ""
                self._socratic_answer_attempts = 0
                answering_socratic = False
            fachfortsetzung = bool(self._fach) and any(
                wendung in text.lower() for wendung in _FACHFORTSETZUNGEN
            )
            if (
                detected_mode == "erklaeren"
                and not looks_academic(text)
                and not self.busy()
                and not fachfortsetzung
            ):
                # The renderer still receives an active professor mode (and
                # can show the glasses), but a general explanation does not
                # carry the multi-page history/research persona into a small
                # local model. That prompt caused ten seconds of silence for
                # a one-sentence question about a rainbow.
                self._mode = "erklaeren"
                self._last_turn = None
                self._letzte_fachaeusserung = time.time()
                logger.info(
                    "[%s] Tor 5 Professor: kompakter Allgemeinmodus.", _kennung()
                )
                return _GENERAL_EXPLANATION_PROMPT

            if self._similar_to_last(text):
                self._attempts += 1
            else:
                self._attempts = 0
            self._last_question = text

            self._prepare_state(text)
            self._fach = professor_engine.detect_fach(text, current=self._fach)

            if answering_socratic:
                self._socratic_answer_attempts += 1

            turn = professor_engine.build_prompt(
                text,
                profile=self.profile,
                project=self._project,
                source=self._source,
                debate=self._debate,
                workshop=self._workshop if self._mode == "forschungsfrage" else None,
                attempts=(
                    self._socratic_answer_attempts
                    if answering_socratic
                    else self._attempts
                ),
                presence=presence,
                current_mode=self._mode,
                fach=self._fach,
            )

            if answering_socratic:
                turn.system_prompt += "\n\n" + socratic_engine.feedback_for_answer(
                    self._socratic_pending,
                    attempt=self._socratic_answer_attempts,
                    continue_with_question=bool(
                        turn.socratic is not None and turn.socratic.ask
                    ),
                )

            self._mode = turn.mode
            self._last_turn = turn
            self._letzte_fachaeusserung = time.time()
            logger.info(
                "[" + _kennung() + "] Tor 5 Professor übernimmt (Fach: %s, Modus: %s).",
                turn.field,
                turn.mode,
            )
            return turn.system_prompt
        except Exception:  # noqa: BLE001 - der Professor darf nie das Gespräch kippen.
            logger.exception("Der Professor-Blickwinkel ließ sich nicht bauen.")
            return ""

    def after_turn(self, text: str, answer: str) -> None:
        """Schreibt fort, was sich aus diesem Zug ergibt – das Lernen."""

        try:
            turn = self._last_turn
            if turn is None:
                return

            if turn.mode == "debatte" and self._debate is not None:
                self._debate.rounds.append(
                    debate_engine.DebateRound(user_argument=text, counter=answer)
                )

            elif turn.mode == "forschungsfrage":
                step = research_question_engine.next_workshop_step(self._workshop)
                if step is not None:
                    erledigt = [
                        key for key, _ in research_question_engine.WORKSHOP_STEPS
                        if self._workshop.get(key, "").strip()
                    ]
                    if erledigt or len(text) > 20:
                        self._workshop[step[0]] = text

            elif turn.mode == "arbeitsbetreuung" and self._project is not None:
                self.mentor.save(self._project)

            if turn.mode == "socratic":
                if turn.socratic is not None and turn.socratic.ask and "?" in answer:
                    # Die tatsaechlich formulierte Frage merken, nicht bloss
                    # die Vorlage aus der Fragenbank. So kann eine knappe
                    # Antwort wie "wegen der Steuern" korrekt eingeordnet
                    # werden.
                    self._socratic_pending = " ".join(answer.split())[-900:]
                else:
                    self._socratic_pending = ""
                    self._socratic_answer_attempts = 0

            topic = professor_engine.extract_topic(text)
            if topic:
                self.profile.record_topic(topic, 0.5)
                self.profile.save()
        except Exception:  # noqa: BLE001
            logger.exception("Der Lernfortschritt ließ sich nicht festhalten.")

    # --- Zustandspflege ------------------------------------------------------------

    def _similar_to_last(self, text: str) -> bool:
        """Ob im Kern dasselbe noch einmal gefragt wird."""

        if not self._last_question or not text:
            return False
        alt = set(self._last_question.lower().split())
        neu = set(text.lower().split())
        if not alt or not neu:
            return False
        return len(alt & neu) / max(len(alt), len(neu)) > 0.55

    def _prepare_state(self, text: str) -> None:
        """Legt an, was der erkannte Modus braucht."""

        mode, _reason = professor_engine.detect_mode(text, current=self._mode)
        lowered = text.lower()

        if mode == "quellenkritik" and self._source is None:
            self._source = source_criticism.SourceAnalysis(description=text[:200])

        elif mode == "debatte" and self._debate is None:
            self._debate = debate_engine.DebateSession(
                topic=professor_engine.extract_topic(text) or "offen",
                user_position=text[:300],
            )

        elif mode == "arbeitsbetreuung" and self._project is None:
            vorhanden = self.mentor.list_projects()
            name = (
                vorhanden[0]
                if vorhanden
                else f"Arbeit: {professor_engine.extract_topic(text) or 'unbenannt'}"
            )
            self._project = self.mentor.create(name)

        if any(word in lowered for word in ("abbrechen", "beenden", "aufhören", "aufhoeren")):
            self.reset()

    def reset(self) -> None:
        """Beendet alle laufenden Vorgänge."""

        self._source = None
        self._debate = None
        self._workshop = {}
        self._mode = ""
        self._fach = ""
        self._socratic_pending = ""
        self._socratic_answer_attempts = 0

    def status(self) -> dict[str, Any]:
        """Woran gerade gearbeitet wird."""

        return {
            "modus": self._mode or "keiner",
            "fach": self._fach or "keines",
            "niveau": self.profile.level,
            "quellenkritik_laeuft": self._source is not None,
            "debatte_laeuft": self._debate is not None,
            "lernfrage_offen": bool(self._socratic_pending),
            "themen": len(getattr(self.profile, "topics", {}) or {}),
        }
