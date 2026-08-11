"""Forschungsassistent (Phase 11).

Unterstützt beim wissenschaftlichen Arbeiten: Forschungsfragen schärfen,
Thesen prüfen, Gliederungen entwerfen, Argumentationen auf Lücken abklopfen.

Der Leitsatz der Vorgabe steht über allem: *„Der Orb soll nicht einfach
fertige Arbeiten produzieren, sondern den Benutzer beim wissenschaftlichen
Denken unterstützen."* Danach ist dieses Modul gebaut. Es liefert an keiner
Stelle einen fertigen Text, sondern Rückfragen, Prüfraster und Einwände.

Ein Beispiel für den Unterschied: Auf „schreib mir eine These zum Sonderweg"
antwortet der Orb nicht mit einer These, sondern damit, woran eine
brauchbare These zu erkennen ist – und prüft dann die eigene des Benutzers
daran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ThesisReview:
    """Die Prüfung einer These."""

    thesis: str
    #: Was für die These spricht.
    strengths: list[str] = field(default_factory=list)
    #: Woran sie krankt.
    weaknesses: list[str] = field(default_factory=list)
    #: Was zu klären ist.
    questions: list[str] = field(default_factory=list)
    #: Wie sie sich widerlegen ließe – der entscheidende Prüfstein.
    falsification: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "thesis": self.thesis,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "questions": self.questions,
            "falsification": self.falsification,
        }

    def as_text(self) -> str:
        parts = [f"These: {self.thesis}"]
        if self.strengths:
            parts.append("Dafür spricht:\n" + "\n".join(f"- {item}" for item in self.strengths))
        if self.weaknesses:
            parts.append("Das ist schwach:\n" + "\n".join(f"- {item}" for item in self.weaknesses))
        if self.questions:
            parts.append("Zu klären:\n" + "\n".join(f"- {item}" for item in self.questions))
        if self.falsification:
            parts.append(f"Widerlegbarkeit: {self.falsification}")
        return "\n\n".join(parts)


#: Wörter, die eine Aussage unüberprüfbar machen.
_VAGUE_TERMS = re.compile(
    r"\b(irgendwie|gewissermaßen|eigentlich|im Grunde|bekanntlich|"
    r"selbstverständlich|natürlich|offensichtlich|zweifellos|unbestreitbar)\b",
    re.I,
)

#: Verallgemeinerungen, die selten haltbar sind.
_SWEEPING_TERMS = re.compile(
    r"\b(alle|jeder|niemand|immer|nie|stets|ausnahmslos|sämtliche|"
    r"die Deutschen|die Menschen|man)\b",
    re.I,
)

#: Wertungen, die als Feststellung auftreten.
_JUDGMENT_TERMS = re.compile(
    r"\b(zwangsläufig|unvermeidlich|logischerweise|musste|natürliche Folge|"
    r"gescheitert|versagt|schuld)\b",
    re.I,
)

#: Zeitliche Eingrenzung.
_TIME_MARKER = re.compile(r"\b(1[0-9]{3}|20[0-9]{2}|jahrhundert|jahrzehnt|zwischen|ab|seit|bis)\b", re.I)

#: Räumliche Eingrenzung.
_PLACE_MARKER = re.compile(
    r"\b(deutschland|preußen|österreich|europa|frankreich|england|"
    r"reich|stadt|region|provinz|königreich|kaiserreich|republik)\w*\b",
    re.I,
)


class ResearchEngine:
    """Werkzeuge für wissenschaftliches Arbeiten."""

    # --- Forschungsfragen ---------------------------------------------------------

    def sharpen_question(self, question: str) -> dict[str, Any]:
        """Prüft eine Forschungsfrage auf Tauglichkeit.

        Eine brauchbare Forschungsfrage ist eingegrenzt, offen und mit
        Quellen zu beantworten. Daran wird geprüft.
        """

        cleaned = question.strip()
        problems: list[str] = []
        suggestions: list[str] = []

        if len(cleaned) < 15:
            problems.append("Die Frage ist so knapp, dass unklar bleibt, was gesucht wird.")

        if not cleaned.endswith("?"):
            problems.append("Das ist keine Frage. Formuliere sie als solche.")

        lowered = cleaned.lower()

        if lowered.startswith(("ist ", "war ", "hat ", "gab es", "kann ", "wurde ")):
            problems.append(
                "Die Frage lässt sich mit Ja oder Nein beantworten. Solche Fragen "
                "tragen keine Arbeit."
            )
            suggestions.append(
                "Stelle sie um: Beginne mit „Inwiefern“, „Wie“, „Warum“, „Welche Rolle spielte“."
            )

        if not _TIME_MARKER.search(cleaned):
            problems.append("Es fehlt die zeitliche Eingrenzung.")
            suggestions.append("Nenne Jahr, Jahrzehnt oder Zeitraum.")

        if not _PLACE_MARKER.search(cleaned):
            problems.append("Es fehlt die räumliche Eingrenzung.")
            suggestions.append("Nenne Ort, Region oder Staat.")

        if _SWEEPING_TERMS.search(cleaned):
            problems.append(
                "Die Frage verallgemeinert. Solche Formulierungen lassen sich mit "
                "Quellen kaum einlösen."
            )

        if lowered.startswith("warum"):
            suggestions.append(
                "„Warum“-Fragen verleiten dazu, eine Ursache zu suchen, wo mehrere "
                "wirkten. Prüfe, ob „Welche Faktoren“ besser passt."
            )

        return {
            "question": cleaned,
            "usable": not problems,
            "problems": problems,
            "suggestions": suggestions,
            "criteria": [
                "Zeitlich eingegrenzt",
                "Räumlich eingegrenzt",
                "Offen, nicht mit Ja/Nein zu beantworten",
                "Mit vorhandenen Quellen zu bearbeiten",
                "Für die Forschung anschlussfähig",
            ],
        }

    # --- Thesen -------------------------------------------------------------------------

    def review_thesis(self, thesis: str) -> ThesisReview:
        """Prüft eine These.

        Der wichtigste Punkt steht am Ende: Wie ließe sich die These
        widerlegen? Eine These, die durch nichts zu widerlegen ist, sagt
        nichts – das ist der Prüfstein, an dem die meisten scheitern.
        """

        cleaned = thesis.strip()
        review = ThesisReview(thesis=cleaned)

        if len(cleaned) < 20:
            review.weaknesses.append("Die These ist zu knapp, um geprüft werden zu können.")
            return review

        # --- Stärken -------------------------------------------------------------
        if _TIME_MARKER.search(cleaned):
            review.strengths.append("Zeitlich eingegrenzt.")
        if _PLACE_MARKER.search(cleaned):
            review.strengths.append("Räumlich eingegrenzt.")
        if re.search(r"\b(weil|da|indem|dadurch|aufgrund|infolge)\b", cleaned, re.I):
            review.strengths.append("Es wird ein Zusammenhang behauptet, nicht nur ein Zustand.")

        # --- Schwächen -----------------------------------------------------------
        vague = _VAGUE_TERMS.findall(cleaned)
        if vague:
            review.weaknesses.append(
                "Unüberprüfbare Wendungen: " + ", ".join(sorted(set(vague)))
                + ". Was „offensichtlich“ ist, muss nicht belegt werden – und "
                "genau deshalb steht es da."
            )

        sweeping = _SWEEPING_TERMS.findall(cleaned)
        if sweeping:
            review.weaknesses.append(
                "Verallgemeinerungen: " + ", ".join(sorted(set(sweeping)))
                + ". Ein einziger Gegenbeleg genügt, um sie zu kippen."
            )

        judgment = _JUDGMENT_TERMS.findall(cleaned)
        if judgment:
            review.weaknesses.append(
                "Wertung als Feststellung: " + ", ".join(sorted(set(judgment)))
                + ". Was als „zwangsläufig“ gilt, war es für die Zeitgenossen "
                "meist nicht."
            )

        if not _TIME_MARKER.search(cleaned):
            review.weaknesses.append("Es fehlt die zeitliche Eingrenzung.")

        if not re.search(r"\b(weil|da|indem|dadurch|aufgrund|infolge|führte|bewirkte)\b", cleaned, re.I):
            review.weaknesses.append(
                "Es wird kein Zusammenhang behauptet. Eine These beschreibt nicht, "
                "sie behauptet etwas, das strittig sein kann."
            )

        # --- Fragen ------------------------------------------------------------------
        review.questions = [
            "Mit welchen Quellen belegst du das?",
            "Wer in der Forschung sieht das anders, und mit welchen Gründen?",
            "Was wäre der stärkste Einwand, und wie begegnest du ihm?",
            "Verwechselst du hier zeitliche Abfolge mit Ursache?",
            "Sind die Begriffe für die untersuchte Zeit angemessen, oder überträgst du Heutiges?",
        ]

        review.falsification = (
            "Formuliere, welcher Fund deine These widerlegen würde. Fällt dir "
            "keiner ein, behauptet sie nichts Prüfbares – dann ist sie noch keine "
            "These."
        )

        return review

    # --- Argumentation ---------------------------------------------------------------------

    def check_argument(self, text: str) -> dict[str, Any]:
        """Klopft eine Argumentation auf typische Fehler ab.

        Erkannt werden nur Muster an der Oberfläche. Das ist ausdrücklich
        keine inhaltliche Prüfung – aber es fängt die Fehler, die beim
        eigenen Text am schwersten zu sehen sind.
        """

        findings: list[dict[str, str]] = []
        lowered = text.lower()

        patterns: list[tuple[str, re.Pattern[str], str]] = [
            (
                "Zeitfolge als Ursache",
                re.compile(r"\b(danach|anschließend|daraufhin|in der Folge)\b.{0,80}?\b(weil|deshalb|daher|folglich)\b", re.I | re.S),
                "Dass B auf A folgte, heißt nicht, dass A B verursachte.",
            ),
            (
                "Berufung auf Autorität",
                re.compile(r"\b(wie \w+ (schreibt|feststellt|zeigt))\b(?!.{0,120}\b(seite|s\.|vgl|ebd)\b)", re.I),
                "Eine Berufung ohne Fundstelle ist kein Beleg. Ergänze die Seitenzahl.",
            ),
            (
                "Rückprojektion",
                re.compile(r"\b(schon damals|bereits im \w+ jahrhundert)\b.{0,60}?\b(modern|demokratisch|national|rassistisch)\w*\b", re.I | re.S),
                "Prüfe, ob der Begriff für die Zeit passt oder ob du Heutiges zurückprojizierst.",
            ),
            (
                "Unbelegter Allgemeinplatz",
                re.compile(r"\b(bekanntlich|wie jeder weiß|unbestritten|es ist klar, dass)\b", re.I),
                "Was hier als bekannt gilt, ist der Punkt, der zu belegen wäre.",
            ),
            (
                "Strohmann",
                re.compile(r"\b(die (forschung|these|meinung) behauptet)\b(?!.{0,100}\b(vgl|siehe|s\.)\b)", re.I),
                "Wem genau wird das zugeschrieben? Ohne Zuordnung ist der Einwand nicht überprüfbar.",
            ),
            (
                "Entweder-oder",
                re.compile(r"\b(entweder)\b.{0,120}\b(oder)\b", re.I | re.S),
                "Prüfe, ob es wirklich nur zwei Möglichkeiten gibt.",
            ),
        ]

        for name, pattern, hint in patterns:
            match = pattern.search(text)
            if match:
                findings.append(
                    {
                        "problem": name,
                        "hint": hint,
                        "passage": match.group(0)[:160].strip(),
                    }
                )

        # --- Belegdichte ----------------------------------------------------------
        citations = len(re.findall(r"\b(vgl\.|ebd\.|s\.\s?\d+|S\.\s?\d+|\[\d+\]|\(\d{4}\))", text))
        sentences = max(1, len(re.findall(r"[.!?]+", text)))
        density = citations / sentences

        notes: list[str] = []
        if density < 0.08 and sentences > 8:
            notes.append(
                f"Auf {sentences} Sätze kommen {citations} Belege. Das ist für einen "
                "wissenschaftlichen Text wenig."
            )

        if not re.search(r"\b(allerdings|jedoch|dagegen|einwenden|kritisch|hingegen|demgegenüber)\b", text, re.I):
            notes.append(
                "Es kommt keine Gegenposition vor. Ein Argument, das keinen Einwand "
                "kennt, wirkt nicht stark, sondern ungeprüft."
            )

        return {
            "findings": findings,
            "notes": notes,
            "citation_density": round(density, 3),
            "sentences": sentences,
            "citations": citations,
            "clean": not findings and not notes,
        }

    # --- Gliederung ----------------------------------------------------------------------

    def outline_template(self, topic: str, *, kind: str = "hausarbeit") -> dict[str, Any]:
        """Liefert ein Gliederungsgerüst.

        Bewusst ein Gerüst, kein fertiger Aufbau: Die Kapitel des Hauptteils
        ergeben sich aus der Fragestellung und lassen sich nicht vorgeben,
        ohne die Arbeit vorwegzunehmen.
        """

        subject = topic.strip() or "das Thema"

        base = [
            {
                "section": "Einleitung",
                "share": "etwa 10 Prozent",
                "contains": [
                    "Hinführung zum Gegenstand",
                    f"Fragestellung zu {subject} – die eine Frage, die die Arbeit beantwortet",
                    "Forschungsstand: Wer hat was gesagt, und wo steht die Lücke?",
                    "Quellenlage und Methode",
                    "Aufbau der Arbeit",
                ],
            },
            {
                "section": "Hauptteil",
                "share": "etwa 80 Prozent",
                "contains": [
                    "Die Kapitel ergeben sich aus deiner Fragestellung, nicht aus einer Vorlage.",
                    "Ein Kapitel je Teilfrage oder je Argumentationsschritt.",
                    "Chronologisch, systematisch oder vergleichend – aber durchgehend eines davon.",
                    "Jedes Kapitel endet mit dem Ertrag für die Fragestellung.",
                ],
            },
            {
                "section": "Schluss",
                "share": "etwa 10 Prozent",
                "contains": [
                    "Die Fragestellung wird beantwortet – keine neuen Belege mehr",
                    "Was offen bleibt und warum",
                    "Anschluss an die Forschung",
                ],
            },
            {
                "section": "Verzeichnisse",
                "share": "",
                "contains": ["Quellenverzeichnis", "Literaturverzeichnis", "gegebenenfalls Anhang"],
            },
        ]

        if kind.strip().lower() in {"quellenanalyse", "quelleninterpretation"}:
            base[1] = {
                "section": "Hauptteil",
                "share": "etwa 80 Prozent",
                "contains": [
                    "Äußere Quellenkritik: Verfasser, Entstehung, Überlieferung, Adressat",
                    "Innere Quellenkritik: Aufbau, Sprache, Absicht, Auslassungen",
                    "Einordnung in den historischen Zusammenhang",
                    "Auswertung im Hinblick auf die Fragestellung",
                ],
            }

        return {
            "topic": subject,
            "kind": kind,
            "sections": base,
            "reminder": (
                "Diese Gliederung ist ein Gerüst. Der Zuschnitt des Hauptteils ist "
                "die eigentliche wissenschaftliche Leistung – den nimmt dir "
                "niemand ab."
            ),
        }

    def counterarguments(self, thesis: str) -> list[str]:
        """Nennt die Richtungen, aus denen Widerspruch zu erwarten ist.

        Keine inhaltlichen Gegenargumente – die kann nur kennen, wer die
        Forschung kennt. Was hier steht, sind die Angriffspunkte, die bei
        historischen Thesen fast immer tragen.
        """

        return [
            "Quellenkritik: Tragen deine Quellen die Behauptung, oder überdehnst du sie?",
            "Auswahl: Hast du Quellen ausgeklammert, die dagegen sprechen?",
            "Begriffe: Verwendest du Begriffe, die es in der untersuchten Zeit so nicht gab?",
            "Ursache: Verwechselst du Zusammenhang mit Ursache?",
            "Reichweite: Gilt der Befund über den untersuchten Raum und Zeitraum hinaus?",
            "Alternativerklärung: Welche andere Deutung erklärt dieselben Befunde ebenso gut?",
            "Forschungsstand: Welche Position in der Forschung sagt das Gegenteil, und warum?",
        ]

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "capabilities": [
                "Forschungsfrage schärfen",
                "These prüfen",
                "Argumentation auf Fehlschlüsse abklopfen",
                "Gliederungsgerüst",
                "Gegenargumente benennen",
            ],
            "principle": (
                "Der Orb schreibt keine Arbeiten. Er stellt Rückfragen und zeigt "
                "Lücken."
            ),
        }
