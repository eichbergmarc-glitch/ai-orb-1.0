"""Der Professor selbst – Modi, Rolle, Persona (Abschnitte 2, 24, 26, 27, 31).

Dieses Modul führt zusammen, was die anderen bereitstellen: Es erkennt,
welcher Modus gemeint ist, holt sich aus dem Lernprofil, was über den
Benutzer bekannt ist, und baut daraus den Systemprompt, mit dem Claude
antwortet.

## Warum der Systemprompt hier gebaut wird und nicht in der Konfiguration

Weil er sich von Zug zu Zug ändert. Ein Professor, der prüft, verhält sich
anders als einer, der eine Quelle mit jemandem durchgeht, und beide
verhalten sich anders als einer, der eine Gegenposition vertritt. Ein
fester Prompt könnte das nur beschreiben; hier wird es entschieden.

## Die Reihenfolge im Prompt ist Absicht

Zuerst die Person, dann das Wissen über den Benutzer, dann der Modus,
zuletzt die konkrete Anweisung. Ein Sprachmodell hält sich an das, was
zuletzt kam, deutlich zuverlässiger als an das, was zwischen zwanzig
anderen Regeln stand – und das Wichtigste an dieser Engine ist die
Anweisung, die Lösung nicht zu verraten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.agents.history_agent import (
    academic_feedback,
    debate_engine,
    historiography,
    research_question_engine,
    socratic_engine,
    source_criticism,
)
from backend.agents.history_agent.learning_profile import LearningProfile
from backend.agents.history_agent.mentor_engine import MentorEngine, Project
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


#: Die Modi aus Abschnitt 24.
MODES: dict[str, str] = {
    "erklaeren": "Einen Sachverhalt erklären.",
    "socratic": "Durch Fragen zum eigenen Denken führen.",
    "seminar": "Eine historische Fragestellung diskutieren.",
    "quellenkritik": "Eine Quelle gemeinsam analysieren.",
    "forschungsfrage": "Eine Fragestellung entwickeln.",
    "arbeitsbetreuung": "Eine wissenschaftliche Arbeit betreuen.",
    "debatte": "Die Gegenposition einnehmen.",
    "kolloquium": "Auf fortgeschrittenem Niveau diskutieren.",
    "lernplan": "Langfristiges Lernen planen.",
}

#: Die Rollen aus Abschnitt 26.
ROLES: dict[str, str] = {
    "professor": "lehrend, fordernd, mit Anspruch auf Genauigkeit",
    "mentor": "begleitend über längere Zeit, auf Entwicklung bedacht",
    "tutor": "erklärend und geduldig, näher an den Grundlagen",
    "diskussionspartner": "auf Augenhöhe, streitbar",
    "forschungsbetreuer": "auf Methode, Quellenbasis und Grenzen bedacht",
    "quellenkritiker": "genau, misstrauisch gegenüber vorschnellen Deutungen",
}

#: Woran sich ein Modus im Gesagten erkennen lässt.
_MODE_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("forschungsfrage", ("forschungsfrage", "fragestellung", "thema eingrenzen",
                         "frage entwickeln", "frage verbessern", "frage schärfen")),
    ("quellenkritik", ("quelle analysieren", "quellenkritik", "diese quelle",
                       "quelle interpretieren", "analysiere diese quelle",
                       "schau dir diese quelle")),
    ("arbeitsbetreuung", ("seminararbeit", "hausarbeit", "bachelorarbeit",
                          "masterarbeit", "meine arbeit", "mein kapitel",
                          "meine einleitung", "meine gliederung", "betreue")),
    ("debatte", ("debatte", "diskutiere gegen", "gegenposition", "widersprich mir",
                 "überzeug mich", "ueberzeug mich")),
    ("lernplan", ("lernplan", "soll ich lernen", "soll ich als nächstes",
                  "soll ich als naechstes", "wie lerne ich", "womit anfangen",
                  "prüfungsvorbereitung", "pruefungsvorbereitung",
                  "was übe ich", "was uebe ich")),
    ("kolloquium", ("kolloquium", "forschungsstand", "historiographie",
                    "forschungskontroverse")),
    ("erklaeren", ("erklär mir", "erklaer mir", "erkläre mir", "was bedeutet",
                   "was ist ein", "definiere")),
    # Sokratisches Lehren muss ausdruecklich verlangt werden.
    #
    # Bis hierher gab es dafuer keinen einzigen Ausloeser - der Modus war
    # schlicht die Vorgabe, und jede Frage ueber 25 Zeichen landete darin.
    # Das war der Grund, warum der Orb dem Benutzer staendig Gegenfragen
    # stellte, statt ihm etwas beizubringen. Wer geprueft werden will, sagt
    # das; wer etwas wissen will, will es erklaert bekommen.
    ("socratic", ("frag mich ab", "prüfe mich", "pruefe mich", "sokratisch",
                  "lass mich selbst", "hilf mir denken", "stell mir fragen",
                  "frag mich", "teste mich", "abfragen")),
)

#: Die Persona (Abschnitt 2). Sie steht als Text und nicht als Stichwortliste,
#: weil ein Modell Stichworte als Etiketten liest und Sätze als Haltung.
PERSONA = (
    "Du bist der persönliche Geschichtsprofessor des Benutzers – nicht ein "
    "Assistent mit akademischem Tonfall, sondern sein Betreuer über längere "
    "Zeit.\n\n"
    "Du bist wissenschaftlich genau, kritisch und anspruchsvoll. Du bist "
    "geduldig, aber nicht nachgiebig. Du nimmst den Benutzer ernst, und "
    "gerade deshalb benennst du Fehler klar, statt sie höflich zu "
    "umschreiben. Du bist nie herablassend und nie überfreundlich – "
    "aufgesetzte Begeisterung ist bei einem Fachgespräch eine Zumutung.\n\n"
    "Du redest wie ein Mensch im Gespräch, nicht wie ein Lehrbuch: keine "
    "Aufzählungen, keine Überschriften, keine fettgedruckten Stichworte, "
    "wenn nicht ausdrücklich danach gefragt wird. Du sprichst in Sätzen."
)

#: Die Regeln wissenschaftlicher Redlichkeit (Abschnitt 27).
#:
#: Das ist die einzige Stelle, an der die Engine dem Modell etwas verbietet
#: statt es zu lenken – und das aus gutem Grund: Eine erfundene
#: Archivsignatur ist in einer wissenschaftlichen Arbeit kein Schönheits-
#: fehler, sondern ein Kündigungsgrund.
INTEGRITY_RULES = (
    "WISSENSCHAFTLICHE REDLICHKEIT – ohne Ausnahme:\n"
    "Erfinde niemals Autoren, Buchtitel, Aufsätze, Zeitschriften, "
    "Seitenzahlen, Zitate oder Archivsignaturen. Wenn du eine Position "
    "kennst, aber nicht die Fundstelle, sage genau das: dass du die "
    "Position kennst und die Fundstelle nicht. Ein Hinweis, den der "
    "Benutzer selbst prüfen muss, ist nützlich; eine erfundene Angabe "
    "zerstört seine Arbeit.\n"
    "Kennzeichne, wie sicher eine Aussage ist: gesichert, wahrscheinlich, "
    "umstritten oder unsicher. Sage es dazu, wenn du unsicher bist."
)

#: Wo die geprüften Quellen liegen.
#:
#: Der Benutzer hat seine wissenschaftlich belastbaren Anlaufstellen über
#: Jahre in den Favoriten seines Browsers gesammelt – Archive, Editionen,
#: Fachportale, Bibliothekskataloge. Diese Sammlung ist seiner eigenen
#: Prüfung entsprungen und deshalb mehr wert als der erste Treffer einer
#: allgemeinen Suche. Der Professor muss wissen, dass es sie gibt, sonst
#: sucht er daran vorbei.
SOURCE_POLICY = (
    "WO DU SUCHST – die Reihenfolge ist verbindlich:\n"
    "1. ZUERST die Favoriten des Benutzers: Rufe das Werkzeug "
    "'favoriten_suchen' auf. Dort stehen seine geprüften, "
    "wissenschaftlich belastbaren Anlaufstellen – Archive, Quelleneditionen, "
    "Fachportale, Bibliothekskataloge. Was er selbst gesammelt hat, ist "
    "für seine Arbeit brauchbarer als ein beliebiger Suchtreffer.\n"
    "2. DANN, wenn die Favoriten nichts hergeben oder etwas Aktuelles "
    "gefragt ist, 'internet_suchen'. Wäge dabei die Herkunft ab: "
    "Universitäten, Archive, Fachzeitschriften und Editionen sind zitierfähig, "
    "beliebige Webseiten nicht. Sage dem Benutzer, was du wo gefunden hast.\n"
    "3. Soll dir etwas dauerhaft geläufig sein, benutze 'wissen_aneignen' – "
    "das legt das Ergebnis mit Quellenangabe im Gedächtnis ab.\n"
    "Nennt der Benutzer etwas, das er gerade auf dem Bildschirm hat, "
    "lies es mit 'bildschirm_lesen' selbst, statt zu raten."
)


@dataclass(slots=True)
class ProfessorTurn:
    """Was für einen Gesprächszug entschieden wurde."""

    mode: str
    role: str
    system_prompt: str
    reason: str
    socratic: socratic_engine.SocraticDecision | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "modus": self.mode,
            "rolle": self.role,
            "begruendung": self.reason,
            "sokratisch": self.socratic.to_dict() if self.socratic else None,
        }


def detect_mode(text: str, *, current: str = "") -> tuple[str, str]:
    """Erkennt den gemeinten Modus.

    Args:
        text: Was der Benutzer gesagt hat.
        current: Der laufende Modus. Er wird beibehalten, solange nichts
            deutlich dagegen spricht – ein Modus, der bei jedem Satz
            umspringt, ist keiner.

    Returns:
        Modus und Begründung.
    """

    lowered = text.lower()

    for mode, triggers in _MODE_TRIGGERS:
        hit = next((trigger for trigger in triggers if trigger in lowered), None)
        if hit:
            return mode, f"Ausdrücklich verlangt („{hit}“)."

    if current in ("quellenkritik", "forschungsfrage", "debatte",
                   "arbeitsbetreuung"):
        # Ein laufender Vorgang wird nicht durch eine Zwischenfrage beendet.
        return current, "Der laufende Vorgang wird fortgesetzt."

    # Hier stand: Jede Frage ueber 25 Zeichen fuehrt in den sokratischen
    # Modus. Das war der Grund, warum der Orb dem Benutzer staendig
    # Gegenfragen stellte, statt ihm etwas beizubringen - fast jede ernst
    # gemeinte Frage ist laenger als 25 Zeichen.
    #
    # Sokratisches Lehren ist eine grossartige Methode und ein schlechter
    # Standard. Wer etwas wissen will, will es erklaert bekommen; wer
    # geprueft werden will, sagt das. Der Benutzer hat es unmissverstaendlich
    # gesagt: Er soll es ihm BEIBRINGEN, nicht fragen, was er schon weiss.
    #
    # Der Modus bleibt also erreichbar - ueber die Ausloeser weiter oben
    # ("pruefe mich", "frag mich ab"). Er kommt nur nicht mehr ungebeten.
    return current or "erklaeren", "Vorgabe: erklaeren, nicht abfragen."


def detect_role(mode: str, profile: LearningProfile) -> str:
    """Wählt die Rolle zum Modus (Abschnitt 26)."""

    zuordnung = {
        "quellenkritik": "quellenkritiker",
        "arbeitsbetreuung": "forschungsbetreuer",
        "forschungsfrage": "forschungsbetreuer",
        "debatte": "diskussionspartner",
        "kolloquium": "diskussionspartner",
        "lernplan": "mentor",
        "erklaeren": "tutor",
    }

    if mode in zuordnung:
        return zuordnung[mode]

    # Bei Einsteigern ist der Tutor angemessener als der Professor. Wer am
    # Anfang steht, braucht zuerst Boden unter den Füßen.
    return "tutor" if profile.level in ("einsteiger", "grundwissen") else "professor"


def _presence_note(presence: dict[str, Any] | None) -> str:
    """Berücksichtigt die Human-Experience-Engine (Abschnitt 31)."""

    if not presence:
        return ""

    state = str(presence.get("zustand") or presence.get("state") or "").lower()

    if "konzentriert" in state or "focus" in state:
        return (
            "Der Benutzer arbeitet gerade konzentriert. Fasse dich kurz und "
            "stelle keine zusätzlichen Fragen, nach denen nicht gefragt war."
        )
    if "pause" in state or "idle" in state:
        return (
            "Der Benutzer kommt gerade aus einer Pause. Steig ruhig ein, "
            "ohne ihn mit Fragen zu überfallen."
        )
    return ""


def build_prompt(
    text: str,
    *,
    profile: LearningProfile,
    mode: str = "",
    project: Project | None = None,
    source: source_criticism.SourceAnalysis | None = None,
    debate: debate_engine.DebateSession | None = None,
    workshop: dict[str, str] | None = None,
    attempts: int = 0,
    presence: dict[str, Any] | None = None,
    current_mode: str = "",
) -> ProfessorTurn:
    """Baut den Systemprompt für einen Gesprächszug.

    Das ist die zentrale Funktion der Engine. Alles andere liefert
    Bausteine; hier wird entschieden, welche davon in welcher Reihenfolge
    zusammenkommen.
    """

    chosen_mode, reason = (mode, "Ausdrücklich gesetzt.") if mode else detect_mode(
        text, current=current_mode
    )
    role = detect_role(chosen_mode, profile)

    parts: list[str] = [PERSONA, "", INTEGRITY_RULES, "", SOURCE_POLICY, ""]

    # --- Was über den Benutzer bekannt ist ------------------------------------
    parts.append("WAS DU ÜBER DEN BENUTZER WEISST:")
    parts.append(profile.as_context())
    parts.append("")

    # --- Rolle und Modus -------------------------------------------------------
    parts.append(
        f"ROLLE: {role} – {ROLES.get(role, '')}.\n"
        f"MODUS: {chosen_mode} – {MODES.get(chosen_mode, '')}"
    )
    parts.append("")

    note = _presence_note(presence)
    if note:
        parts.append(note)
        parts.append("")

    socratic_decision: socratic_engine.SocraticDecision | None = None

    # --- Die modusabhängige Anweisung, zuletzt ---------------------------------
    if chosen_mode == "quellenkritik" and source is not None:
        parts.append(source_criticism.prompt_for(source))

    elif chosen_mode == "forschungsfrage":
        if workshop is not None and not workshop.get("forschungsfrage", "").strip():
            step = research_question_engine.next_workshop_step(workshop)
            if step is not None:
                key, frage = step
                parts.append(
                    f"FRAGESTELLUNGS-WERKSTATT – nächster Schritt ({key}):\n{frage}\n"
                    "Stelle diese Frage. Beantworte sie nicht für ihn."
                )
        else:
            assessment = research_question_engine.assess(text)
            parts.append(research_question_engine.improvement_prompt(assessment))

    elif chosen_mode == "arbeitsbetreuung" and project is not None:
        parts.append(f"BETREUTE ARBEIT: {MentorEngine().context(project)}")
        structure = academic_feedback.analyse_argument(text)
        parts.append(academic_feedback.feedback_prompt(structure, is_written_work=True))

    elif chosen_mode == "debatte" and debate is not None:
        parts.append(
            debate_engine.rebuttal_prompt(debate)
            if debate.rounds
            else debate_engine.opening_prompt(debate.topic, debate.user_position)
        )

    elif chosen_mode == "kolloquium":
        parts.append(historiography.controversy_prompt(text[:120]))

    elif chosen_mode == "lernplan":
        parts.append(_learning_plan_prompt(profile))

    else:
        # Der Regelfall: erklären oder sokratisch führen.
        socratic_decision = socratic_engine.decide(
            text, profile, attempts=attempts, mode=chosen_mode
        )

        structure = academic_feedback.analyse_argument(text)
        if structure.findings:
            parts.append(academic_feedback.feedback_prompt(structure))
            parts.append("")

        parts.append(socratic_engine.guidance_for_prompt(socratic_decision))

    return ProfessorTurn(
        mode=chosen_mode,
        role=role,
        system_prompt="\n".join(parts).strip(),
        reason=reason,
        socratic=socratic_decision,
    )


def _learning_plan_prompt(profile: LearningProfile) -> str:
    """Die Anweisung für einen Lernplan aus dem Profil heraus."""

    zusammenfassung = profile.summary()
    schwaechen = ", ".join(item["bereich"] for item in zusammenfassung["schwaechen"]) or "—"
    faellig = ", ".join(zusammenfassung["faellige_themen"]) or "—"

    fehler = "\n".join(
        f"  - {item['art']} bei {item['thema']} ({item['anzahl']}×)"
        for item in zusammenfassung["wiederkehrende_fehler"]
    ) or "  (keine wiederkehrenden Fehler erfasst)"

    return (
        "LERNPLAN – Grundlage ist das tatsächliche Profil, nicht eine "
        "allgemeine Empfehlung:\n"
        f"  Niveau: {zusammenfassung['niveau']}\n"
        f"  Schwache Bereiche: {schwaechen}\n"
        f"  Fällig zur Wiederholung: {faellig}\n"
        f"  Wiederkehrende Fehler:\n{fehler}\n\n"
        "Schlage drei konkrete nächste Schritte vor – keine Themenliste, "
        "sondern Übungen mit einem erkennbaren Zweck. Sage bei jedem dazu, "
        "woran du merken wirst, dass er gewirkt hat. Frage am Ende, womit er "
        "anfangen will."
    )


def extract_topic(text: str) -> str:
    """Rät das historische Thema einer Äußerung.

    Für das Lernprofil: Ohne Thema lässt sich nichts wiederholen. Die
    Erkennung ist grob und darf es sein – sie muss nur besser sein als
    gar keine.
    """

    # 1. Zwei großgeschriebene Wörter, das zweite ein historischer Grundbegriff:
    #    „Französische Revolution“, „Wiener Kongress“, „Erster Weltkrieg“.
    #
    #    Der Grundbegriff darf zusammengesetzt und gebeugt sein. Genau daran
    #    scheiterte die frühere Fassung: „des Ersten Weltkriegs“ fand sie
    #    nicht, weil sie „Krieg“ als eigenes Wort in der Grundform erwartete.
    #    Ohne erkanntes Thema notiert das Lernprofil nichts – der Orb führte
    #    hunderte Gespräche und lernte aus keinem.
    # Der Grundbegriff wird OHNE Rücksicht auf Groß- und Kleinschreibung
    # gesucht: In einer Zusammensetzung steht er klein („Welt-krieg“,
    # „Wirtschafts-krise“), allein steht er groß („Krieg“). Genau daran
    # scheiterte die Erkennung vorher – „Weltkriegs“ blieb unerkannt, und
    # ohne Thema notiert das Lernprofil nichts.
    _CORE = (
        r"(?i:krieg|revolution|kongress|reich|republik|reformation|aufstand|"
        r"vertrag|frieden|epoche|bewegung|verfassung|krise|konflikt|"
        r"schlacht|bündnis|buendnis|diktatur|demokratie|monarchie)"
        r"(?:e|en|es|s|er|n)?"
    )

    # Der Großbuchstabe wird per Vorausschau geprüft, nicht verbraucht.
    # Sonst wäre er weg, bevor der Grundbegriff gesucht wird – und
    # „Revolution“ ließe sich nicht mehr finden, weil nur noch „evolution“
    # dastünde.
    _CAP = r"(?=[A-ZÄÖÜ])[\wäöüß]*?"

    # 1. Zwei Wörter: „Französische Revolution“, „Erster Weltkrieg“.
    match = re.search(rf"\b([A-ZÄÖÜ][\wäöüß]*\s+{_CAP}{_CORE})\b", text)
    if match:
        return _tidy_topic(match.group(1))

    # 2. Ein einzelnes zusammengesetztes Wort: „Weltkrieg“, „Wirtschaftskrise“.
    match = re.search(rf"\b({_CAP}{_CORE})\b", text)
    if match:
        return _tidy_topic(match.group(1))

    # 3. Feste Begriffe, die keinem Muster folgen.
    for begriff in (
        "Französische Revolution", "Reformation", "Weimarer Republik",
        "Kaiserreich", "Mittelalter", "Antike", "Kalter Krieg",
        "Nationalsozialismus", "Industrialisierung", "Aufklärung",
        "Renaissance", "Absolutismus", "Kolonialismus", "Imperialismus",
        "Wiedervereinigung", "Holocaust", "Frühe Neuzeit", "Neuzeit",
    ):
        if begriff.lower() in text.lower():
            return begriff

    return ""


#: Wörter, die vorn am erkannten Thema kleben bleiben können.
_TOPIC_LEADERS = {
    "der", "die", "das", "des", "dem", "den", "ein", "eine", "eines", "einem",
    "einen", "zum", "zur", "beim", "vom", "im", "am", "und", "oder",
}


def _tidy_topic(raw: str) -> str:
    """Räumt einen erkannten Themenausdruck auf.

    Entfernt führende Artikel und setzt die Endung des Grundbegriffs in die
    Grundform, damit „Weltkriegs“ und „Weltkrieg“ im Lernprofil nicht als
    zwei Themen geführt werden – sonst gäbe es keine Wiederholung, sondern
    eine wachsende Liste von Fast-Dubletten.
    """

    words = [word for word in raw.split() if word.lower() not in _TOPIC_LEADERS]
    if not words:
        return ""

    # Die gebeugte Adjektivendung angleichen: „des Ersten Weltkriegs“ und
    # „der Erste Weltkrieg“ sind dasselbe Thema und dürfen im Lernprofil
    # nicht zwei Einträge werden – sonst wird nie wiederholt, sondern nur
    # gesammelt.
    for index in range(len(words) - 1):
        word = words[index]
        if len(word) > 4 and word.endswith("en"):
            words[index] = word[:-1]

    last = words[-1]
    for ending in ("es", "en", "er", "s", "e"):
        stem = last[: -len(ending)]
        # Nur kürzen, wenn ein sinnvoller Wortstamm übrig bleibt.
        if last.endswith(ending) and len(stem) >= 5:
            if re.search(
                r"(krieg|revolution|kongress|reich|republik|reformation|aufstand|"
                r"vertrag|frieden|krise|konflikt|schlacht|diktatur)$",
                stem,
                re.IGNORECASE,
            ):
                words[-1] = stem
            break

    return " ".join(words).strip()
