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
from typing import Any

from backend.agents.history_agent import (
    debate_engine,
    professor_engine,
    research_question_engine,
    source_criticism,
)
from backend.agents.history_agent.learning_profile import LearningProfile
from backend.agents.history_agent.mentor_engine import MentorEngine
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


_GENERAL_EXPLANATION_PROMPT = (
    "Du erklaerst wie ein ruhiger, klarer Professor: anschaulich, menschlich "
    "und ohne unnoetige Fachsprache. Antworte direkt in hoechstens drei "
    "kurzen Saetzen. Dies ist eine allgemeine Erklaerung, keine historische "
    "Recherche; fordere weder Quellen noch eine wissenschaftliche Analyse an."
)


#: Woran ein wissenschaftliches oder historisches Anliegen zu erkennen ist.
#:
#: Bewusst breit: Lieber einmal zu viel den Professor fragen als den
#: Benutzer bei einer historischen Frage mit einer beliebigen Auskunft
#: abspeisen. Die Liste deckt Geschichte, Politik, Wirtschaft und
#: militärische Konflikte ab – die Felder, für die der Orb gebaut wurde.
_ACADEMIC_MARKERS: tuple[str, ...] = (
    # Fach und Methode
    "geschicht", "historisch", "historiker", "historiographie", "quelle",
    "quellen", "archiv", "epoche", "chronik", "überliefer", "ueberliefer",
    "forschung", "these", "argument", "beleg", "literatur", "fußnote",
    "fussnote", "zitat", "bibliograph", "methodik", "wissenschaft",
    "seminar", "vorlesung", "hausarbeit", "seminararbeit", "bachelor",
    "master", "dissertation", "exposé", "expose", "gliederung",
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
        self._source: source_criticism.SourceAnalysis | None = None
        self._debate: debate_engine.DebateSession | None = None
        self._project: Any | None = None
        self._workshop: dict[str, str] = {}
        self._attempts = 0
        self._last_question = ""
        self._last_turn: professor_engine.ProfessorTurn | None = None

    # --- Entscheidung ------------------------------------------------------------

    def busy(self) -> bool:
        """Ob ein Vorgang läuft, der nicht unterbrochen werden darf."""

        if self._mode in ("quellenkritik", "forschungsfrage",
                          "debatte", "arbeitsbetreuung"):
            return True
        return self._source is not None or self._debate is not None

    def should_engage(self, text: str) -> bool:
        """Ob der Professor bei dieser Äußerung übernehmen soll."""

        lowered = text.lower()

        # Ein ausdrücklich verlangter Modus schlägt alles.
        for _mode, triggers in professor_engine._MODE_TRIGGERS:  # noqa: SLF001
            if any(trigger in lowered for trigger in triggers):
                return True

        if self.busy():
            return True

        return looks_academic(text)

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
            if (
                detected_mode == "erklaeren"
                and not looks_academic(text)
                and not self.busy()
            ):
                # The renderer still receives an active professor mode (and
                # can show the glasses), but a general explanation does not
                # carry the multi-page history/research persona into a small
                # local model. That prompt caused ten seconds of silence for
                # a one-sentence question about a rainbow.
                self._mode = "erklaeren"
                self._last_turn = None
                logger.info("Der Professor erklaert im kompakten Allgemeinmodus.")
                return _GENERAL_EXPLANATION_PROMPT

            if self._similar_to_last(text):
                self._attempts += 1
            else:
                self._attempts = 0
            self._last_question = text

            self._prepare_state(text)

            turn = professor_engine.build_prompt(
                text,
                profile=self.profile,
                project=self._project,
                source=self._source,
                debate=self._debate,
                workshop=self._workshop if self._mode == "forschungsfrage" else None,
                attempts=self._attempts,
                presence=presence,
                current_mode=self._mode,
            )

            self._mode = turn.mode
            self._last_turn = turn
            logger.info("Der Professor übernimmt (Modus: %s).", turn.mode)
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

    def status(self) -> dict[str, Any]:
        """Woran gerade gearbeitet wird."""

        return {
            "modus": self._mode or "keiner",
            "niveau": self.profile.level,
            "quellenkritik_laeuft": self._source is not None,
            "debatte_laeuft": self._debate is not None,
            "themen": len(getattr(self.profile, "topics", {}) or {}),
        }
