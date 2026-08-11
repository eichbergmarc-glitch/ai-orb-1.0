"""Quellenkritik (Phase 11).

Das Handwerkszeug der Geschichtswissenschaft: Was für eine Quelle liegt vor,
wer hat sie warum verfasst, und was folgt daraus für ihre Aussagekraft?

Dieses Modul ersetzt das Urteil nicht – es kann nicht wissen, ob ein
Feldpostbrief echt ist. Was es leistet, ist zweierlei: Es hält die Fragen
bereit, die zu stellen sind, und es erkennt an der Beschreibung einer Quelle
Anhaltspunkte für ihre Gattung. Beides ist ein Gerüst, kein Ergebnis.

Diese Zurückhaltung ist Absicht. Ein Programm, das nach drei Stichworten
verkündet „diese Quelle ist verlässlich", wäre in der Lehre schädlich. Der
Nutzen liegt darin, keine Prüfschritte zu vergessen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceKind(Enum):
    """Die Gattung einer Quelle."""

    PRIMARY = "primaerquelle"
    SECONDARY = "sekundaerliteratur"
    TERTIARY = "tertiaerliteratur"
    UNCLEAR = "unklar"

    def description(self) -> str:
        return {
            SourceKind.PRIMARY: (
                "Überrest oder Tradition aus der untersuchten Zeit – Urkunde, "
                "Brief, Akte, Zeitungsartikel, Bild, Gegenstand."
            ),
            SourceKind.SECONDARY: (
                "Wissenschaftliche Auseinandersetzung mit dem Gegenstand – "
                "Monographie, Aufsatz, Dissertation."
            ),
            SourceKind.TERTIARY: (
                "Zusammenfassende Darstellung – Lexikon, Handbuch, Lehrbuch, "
                "Überblickswerk."
            ),
            SourceKind.UNCLEAR: "Die Gattung geht aus der Beschreibung nicht hervor.",
        }[self]


#: Anhaltspunkte für die Gattung. Bewusst als Hinweise formuliert, nicht als
#: Entscheidung – deshalb wird die Fundstelle mitgeliefert.
_KIND_HINTS: list[tuple[SourceKind, re.Pattern[str], str]] = [
    (
        SourceKind.PRIMARY,
        re.compile(
            r"\b(urkunde|akte|brief|tagebuch|protokoll|erlass|dekret|verordnung|"
            r"flugblatt|plakat|feldpost|zeitzeug|interview|inschrift|chronik|"
            r"testament|vertrag|manuskript|handschrift)\w*\b",
            re.I,
        ),
        "Gattungsbegriff eines Überrests",
    ),
    (
        SourceKind.SECONDARY,
        re.compile(
            r"\b(monographie|aufsatz|dissertation|habilitation|studie|"
            r"untersuchung|forschungsbeitrag|zeitschrift|sammelband|rezension)\w*\b",
            re.I,
        ),
        "Gattungsbegriff der Forschungsliteratur",
    ),
    (
        SourceKind.TERTIARY,
        re.compile(
            r"\b(lexikon|enzyklop|handbuch|lehrbuch|überblick|einführung|"
            r"wikipedia|nachschlagewerk|kompendium)\w*\b",
            re.I,
        ),
        "Gattungsbegriff eines Nachschlagewerks",
    ),
]


@dataclass
class SourceAssessment:
    """Das Ergebnis einer Quellenprüfung."""

    kind: SourceKind
    #: Woran die Gattung erkannt wurde.
    reasons: list[str] = field(default_factory=list)
    #: Die Fragen, die noch zu klären sind.
    open_questions: list[str] = field(default_factory=list)
    #: Punkte, die zur Vorsicht mahnen.
    caveats: list[str] = field(default_factory=list)
    #: Was an bibliographischen Angaben fehlt.
    missing_metadata: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "kind_description": self.kind.description(),
            "reasons": self.reasons,
            "open_questions": self.open_questions,
            "caveats": self.caveats,
            "missing_metadata": self.missing_metadata,
        }

    def as_text(self) -> str:
        """Die Prüfung als lesbarer Text."""

        parts = [f"Einordnung: {self.kind.value} – {self.kind.description()}"]

        if self.reasons:
            parts.append("Anhaltspunkte: " + "; ".join(self.reasons))

        if self.missing_metadata:
            parts.append(
                "Es fehlen bibliographische Angaben: " + ", ".join(self.missing_metadata)
            )

        if self.caveats:
            parts.append("Zur Vorsicht:\n" + "\n".join(f"- {item}" for item in self.caveats))

        if self.open_questions:
            parts.append(
                "Das ist noch zu klären:\n" + "\n".join(f"- {item}" for item in self.open_questions)
            )

        return "\n\n".join(parts)


#: Die Fragen der äußeren und inneren Quellenkritik. Sie gelten für jede
#: Quelle und werden deshalb immer mitgegeben.
EXTERNAL_QUESTIONS: tuple[str, ...] = (
    "Wer hat die Quelle verfasst, und in welcher Stellung?",
    "Wann und wo ist sie entstanden?",
    "An wen richtet sie sich?",
    "Ist sie im Original erhalten oder als Abschrift, Übersetzung, Bearbeitung?",
    "In welchem Zusammenhang wurde sie überliefert – und was ist dabei verloren?",
)

INTERNAL_QUESTIONS: tuple[str, ...] = (
    "Zu welchem Zweck wurde sie verfasst?",
    "Was sagt sie aus, und was verschweigt sie?",
    "Welche Wertungen und Begriffe verwendet sie, und was verraten sie über ihren Standpunkt?",
    "Wo hatte der Verfasser eigenes Wissen, wo gibt er Hörensagen wieder?",
    "Welches Interesse hatte er daran, so und nicht anders zu schreiben?",
)

SECONDARY_QUESTIONS: tuple[str, ...] = (
    "Auf welche Quellen stützt sich die Darstellung?",
    "Welcher Forschungsrichtung folgt sie, und welche Gegenpositionen gibt es?",
    "Wie alt ist sie, und was hat die Forschung seither ergeben?",
    "Wurde sie begutachtet, und wie wurde sie rezensiert?",
)


class SourceCriticism:
    """Ordnet Quellen ein und hält die Prüffragen bereit."""

    def assess(
        self,
        description: str,
        *,
        author: str = "",
        year: str = "",
        title: str = "",
        publisher: str = "",
    ) -> SourceAssessment:
        """Prüft eine Quelle anhand ihrer Beschreibung.

        Args:
            description: Was über die Quelle bekannt ist.
            author: Der Verfasser, falls bekannt.
            year: Das Jahr, falls bekannt.
            title: Der Titel, falls bekannt.
            publisher: Verlag oder Fundort.

        Returns:
            Die Einordnung samt offener Fragen.
        """

        text = " ".join(part for part in (description, title, publisher) if part)

        kind = SourceKind.UNCLEAR
        reasons: list[str] = []

        for candidate, pattern, reason in _KIND_HINTS:
            match = pattern.search(text)
            if match:
                if kind is SourceKind.UNCLEAR:
                    kind = candidate
                reasons.append(f"{reason} („{match.group(0)}“)")

        assessment = SourceAssessment(kind=kind, reasons=reasons)

        # --- Fehlende Angaben --------------------------------------------------
        if not author.strip():
            assessment.missing_metadata.append("Verfasser")
        if not year.strip():
            assessment.missing_metadata.append("Entstehungs- oder Erscheinungsjahr")
        if not title.strip():
            assessment.missing_metadata.append("Titel")

        # --- Fragen ---------------------------------------------------------------
        assessment.open_questions.extend(EXTERNAL_QUESTIONS)
        assessment.open_questions.extend(INTERNAL_QUESTIONS)
        if kind in (SourceKind.SECONDARY, SourceKind.TERTIARY):
            assessment.open_questions.extend(SECONDARY_QUESTIONS)

        # --- Warnungen ---------------------------------------------------------------
        if kind is SourceKind.TERTIARY:
            assessment.caveats.append(
                "Nachschlagewerke sind zum Einstieg gut und als Beleg ungeeignet. "
                "Nimm sie als Wegweiser zur Forschungsliteratur, nicht als Fußnote."
            )

        if kind is SourceKind.UNCLEAR:
            assessment.caveats.append(
                "Die Gattung geht aus der Beschreibung nicht hervor. Ohne sie lässt "
                "sich nicht beurteilen, wofür die Quelle etwas belegt."
            )

        if year.strip():
            assessment.caveats.extend(self._year_caveats(year, kind))

        if re.search(r"\b(blog|forum|youtube|social|twitter|facebook|tiktok|ki-generiert|chatgpt)\b", text, re.I):
            assessment.caveats.append(
                "Der Fundort deutet auf eine nicht begutachtete Veröffentlichung. "
                "Das schließt sie nicht aus, verlangt aber, die Behauptungen "
                "einzeln zu prüfen."
            )

        return assessment

    @staticmethod
    def _year_caveats(year: str, kind: SourceKind) -> list[str]:
        """Hinweise, die sich aus dem Jahr ergeben."""

        found: list[str] = []
        match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", year)
        if not match:
            return found

        value = int(match.group(0))

        if kind in (SourceKind.SECONDARY, SourceKind.TERTIARY):
            if value < 1990:
                found.append(
                    f"Die Darstellung ist von {value}. Prüfe, ob die Forschung sie "
                    "überholt hat – gerade bei Themen, zu denen nach 1990 Archive "
                    "zugänglich wurden."
                )
            elif value < 2010:
                found.append(
                    f"Die Darstellung ist von {value}. Sieh nach, ob es Neueres gibt."
                )

        if 1933 <= value <= 1945:
            found.append(
                "Die Quelle stammt aus der Zeit des Nationalsozialismus. Rechne mit "
                "Zensur, Propaganda und Selbstzensur – auch in scheinbar sachlichen "
                "Texten."
            )
        elif 1949 <= value <= 1989:
            found.append(
                "Die Quelle stammt aus der Zeit der deutschen Teilung. Frage, aus "
                "welchem Staat und aus welcher Blickrichtung sie kommt."
            )
        elif 1914 <= value <= 1918 or 1939 <= value <= 1945:
            found.append(
                "Die Quelle stammt aus einer Kriegszeit. Kriegsberichterstattung "
                "und amtliche Meldungen sind in aller Regel gelenkt."
            )

        return found

    def checklist(self, kind: SourceKind = SourceKind.UNCLEAR) -> dict[str, list[str]]:
        """Die Prüffragen nach äußerer und innerer Kritik geordnet."""

        checklist = {
            "aeussere_kritik": list(EXTERNAL_QUESTIONS),
            "innere_kritik": list(INTERNAL_QUESTIONS),
        }
        if kind in (SourceKind.SECONDARY, SourceKind.TERTIARY):
            checklist["forschungsliteratur"] = list(SECONDARY_QUESTIONS)
        return checklist

    def guidance(self) -> str:
        """Der Zusatz zum Systemprompt für wissenschaftliches Arbeiten.

        Die Vorgabe ist eindeutig: keine erfundenen Literaturangaben,
        Unsicherheit kennzeichnen, verschiedene Forschungsperspektiven
        berücksichtigen. Das steht deshalb wörtlich im Prompt.
        """

        return (
            "Du arbeitest wissenschaftlich, mit Schwerpunkt Geschichte.\n"
            "- Erfinde niemals Literaturangaben, Seitenzahlen oder Zitate. Nenne "
            "nur Titel, deren Existenz du sicher weißt, und sage bei jedem, wie "
            "sicher du bist.\n"
            "- Unterscheide Primärquelle, Forschungsliteratur und Nachschlagewerk.\n"
            "- Nenne bei umstrittenen Fragen die Gegenposition, nicht nur eine "
            "Sicht.\n"
            "- Kennzeichne, was gesicherte Forschung ist, was umstritten und was "
            "deine eigene Überlegung.\n"
            "- Schreibe dem Benutzer keine Arbeit. Stelle Rückfragen, weise auf "
            "Lücken in der Argumentation hin und schlage vor, wo weiterzulesen ist."
        )
