"""Grundgerüst eines Werkzeugs.

Ein Werkzeug ist eine eng umrissene Fähigkeit, die AI-Orb ausführen kann:
die Uhrzeit nennen, eine Datei lesen, im Gedächtnis suchen. Es hat einen
Namen, eine Beschreibung, ein Schema seiner Parameter – und genau eine
Berechtigung, unter der es läuft.

Der letzte Punkt ist der wichtigste. Ein Werkzeug entscheidet **nie selbst**,
ob es etwas darf. Es nennt seine Berechtigung, und die Werkzeugmaschine holt
vor der Ausführung die Freigabe bei der Sicherheitsschicht ein. Dadurch
gibt es keinen Weg, an der Zustimmung vorbei etwas zu tun – auch nicht für
ein Werkzeug aus einem Plugin.

Das Schema ist bewusst schlicht gehalten: Name, Typ, Pflicht, Beschreibung.
Es dient dazu, dem Sprachmodell zu erklären, was es angeben muss, und dazu,
die Angaben vor der Ausführung zu prüfen. Ein Modell, das ein Feld erfindet
oder vergisst, soll eine verständliche Fehlermeldung bekommen und es erneut
versuchen können.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolParameter:
    """Ein Parameter eines Werkzeugs."""

    name: str
    #: ``string``, ``integer``, ``number``, ``boolean``
    type: str
    description: str
    required: bool = True
    #: Erlaubte Werte; leer bedeutet keine Einschränkung.
    choices: tuple[str, ...] = ()
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
        }
        if self.choices:
            entry["choices"] = list(self.choices)
        if self.default is not None:
            entry["default"] = self.default
        return entry


@dataclass
class ToolResult:
    """Das Ergebnis einer Werkzeugausführung."""

    #: Ob es geklappt hat.
    ok: bool
    #: Was zurückkommt – wird dem Sprachmodell als Text übergeben.
    output: str = ""
    #: Klartextbegründung bei Misserfolg.
    error: str = ""
    #: Zusatzangaben für Protokoll und Anzeige.
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "context": self.context,
        }

    @classmethod
    def success(cls, output: str, **context: Any) -> "ToolResult":
        return cls(ok=True, output=output, context=context)

    @classmethod
    def failure(cls, error: str, **context: Any) -> "ToolResult":
        return cls(ok=False, error=error, context=context)


def _erster_satz(text: str) -> str:
    """Der erste vollstaendige Satz eines Textes.

    Abkuerzungen mit Punkt gibt es in diesen Beschreibungen nicht, also
    genuegt die einfache Regel. Ist der erste Satz sehr kurz - manche
    beginnen mit "Sucht im Internet." -, kommt der zweite dazu, damit die
    Auskunft nicht duenner wird als noetig.
    """

    knapp = " ".join(str(text).split())
    if not knapp:
        return ""
    saetze: list[str] = []
    rest = knapp
    while rest and len(" ".join(saetze)) < 90:
        punkt = rest.find(". ")
        if punkt < 0:
            saetze.append(rest)
            break
        saetze.append(rest[: punkt + 1])
        rest = rest[punkt + 2 :]
    return " ".join(saetze).strip()


class Tool(abc.ABC):
    """Eine einzelne Fähigkeit, die das Sprachmodell aufrufen kann."""

    #: Aufrufname. Kleinbuchstaben mit Unterstrichen.
    name: str = "unbenannt"
    #: Was das Werkzeug tut – wird dem Sprachmodell wörtlich gezeigt.
    description: str = ""
    #: Die Berechtigung, unter der es läuft.
    permission: str = "compute"
    #: Die Parameter.
    parameters: tuple[ToolParameter, ...] = ()

    @abc.abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Führt das Werkzeug aus.

        Die Argumente sind zu diesem Zeitpunkt bereits geprüft und die
        Berechtigung erteilt. Das Werkzeug muss beides nicht erneut tun.
        """

    # --- Prüfung ------------------------------------------------------------------

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        """Prüft die Argumente gegen das Schema.

        Returns:
            Ein Tripel aus Erfolg, Fehlerbeschreibung und den bereinigten
            Argumenten. Unbekannte Felder werden verworfen, statt
            durchgereicht zu werden.
        """

        cleaned: dict[str, Any] = {}
        problems: list[str] = []
        known = {parameter.name for parameter in self.parameters}

        unexpected = sorted(set(arguments) - known)
        if unexpected:
            problems.append(
                "Unbekannte Angaben: " + ", ".join(unexpected)
                + ". Erlaubt sind: " + (", ".join(sorted(known)) or "keine")
            )

        for parameter in self.parameters:
            if parameter.name not in arguments:
                if parameter.required:
                    problems.append(f"Die Angabe '{parameter.name}' fehlt.")
                elif parameter.default is not None:
                    cleaned[parameter.name] = parameter.default
                continue

            value = arguments[parameter.name]
            converted, problem = self._convert(parameter, value)
            if problem:
                problems.append(problem)
            else:
                cleaned[parameter.name] = converted

        if problems:
            return False, " ".join(problems), {}
        return True, "", cleaned

    @staticmethod
    def _convert(parameter: ToolParameter, value: Any) -> tuple[Any, str]:
        """Wandelt einen Wert in den erwarteten Typ um.

        Sprachmodelle liefern Zahlen häufig als Text. Das hier nachsichtig
        umzuwandeln erspart eine Rückfrage, die niemandem hilft.
        """

        try:
            if parameter.type == "string":
                converted: Any = str(value)
            elif parameter.type == "integer":
                converted = int(str(value).strip())
            elif parameter.type == "number":
                converted = float(str(value).strip().replace(",", "."))
            elif parameter.type == "boolean":
                if isinstance(value, bool):
                    converted = value
                else:
                    lowered = str(value).strip().lower()
                    if lowered in {"true", "ja", "yes", "1"}:
                        converted = True
                    elif lowered in {"false", "nein", "no", "0"}:
                        converted = False
                    else:
                        return None, f"'{parameter.name}' muss ja oder nein sein."
            else:
                converted = value
        except (TypeError, ValueError):
            return None, f"'{parameter.name}' muss vom Typ {parameter.type} sein."

        if parameter.choices and str(converted) not in parameter.choices:
            return None, (
                f"'{parameter.name}' muss einer dieser Werte sein: "
                + ", ".join(parameter.choices)
            )

        return converted, ""

    # --- Beschreibung ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Das Werkzeug als Datensatz."""

        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
        }

    def describe_for_model(self) -> str:
        """Beschreibt das Werkzeug so, wie es dem Sprachmodell gezeigt wird.

        Knapper als zuvor, und der Grund ist gemessen: Das Verzeichnis
        aller neununddreissig Werkzeuge mass 14 500 Zeichen - rund 3 600
        Token, die bei JEDER Anfrage mitgeschickt werden, nur um zu
        erklären, was es gibt. Zum Vergleich: Für den gesamten
        Gesprächsverlauf standen 3 000 zur Verfügung.

        Gekürzt wird an der Stelle, an der am wenigsten verlorengeht:

        - Von der Beschreibung bleibt der ERSTE SATZ. Er sagt, was das
          Werkzeug tut; was danach folgt, ist Gebrauchsanweisung, und die
          braucht ein Modell erst, wenn es sich ohnehin schon für dieses
          Werkzeug entschieden hat.
        - Die Parameter stehen in EINER Zeile statt in je einer. Ihre
          eigenen Beschreibungen fallen weg - Name und Typ sagen bei
          "suchbegriff (string, Pflicht)" alles, was es zu wissen gibt.
        - Aufzählbare Werte bleiben vollständig. Sie sind keine
          Erläuterung, sondern Teil der Schnittstelle: Wer sie nicht
          kennt, ruft falsch auf.
        """

        kurz = _erster_satz(self.description)
        felder: list[str] = []
        for parameter in self.parameters:
            marke = "Pflicht" if parameter.required else "optional"
            feld = f"{parameter.name} ({parameter.type}, {marke}"
            if parameter.choices:
                feld += ": " + "|".join(parameter.choices)
            felder.append(feld + ")")

        zeile = f"- {self.name}: {kurz}"
        if felder:
            zeile += "\n    " + ", ".join(felder)
        return zeile
