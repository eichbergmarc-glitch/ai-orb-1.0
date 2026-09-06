"""Der Werkzeugkasten für den Messlauf - echt, aber eingehegt.

Die Kategorien 4 bis 6 lassen sich nicht an einer Textantwort messen. Ob
der Orb eine Datei auflisten kann, zeigt sich daran, dass ``ordner_auflisten``
wirklich lief und wirklich etwas zurückgab - nicht daran, dass das Modell
sagt, es habe nachgesehen.

Gemessen wird deshalb mit den echten Werkzeugen. Zwei Vorkehrungen halten
den Schaden klein:

**Eine Erlaubnisliste.** Nur Werkzeuge, deren Berechtigung hier steht,
kommen ins Messregister. Alles, was löscht, versendet, installiert,
Systembefehle ausführt oder am eigenen Quelltext arbeitet, bleibt draussen -
nicht weil es unwichtig wäre, sondern weil ein Messlauf nichts anrichten
darf, was er nicht wieder aufräumen kann.

**Ein eigenes Datenverzeichnis.** ``AI_ORB_DATA_DIR`` zeigt während des
Laufs in einen Messordner. Was der Lauf schreibt - eine gemerkte Vorliebe,
eine Karteikarte -, landet dort und nicht im Gedächtnis des Benutzers.

Was hier ausdrücklich NICHT passiert: Es werden keine Attrappen eingesetzt.
Ein Messregister aus Attrappen würde messen, wie gut die Attrappen sind.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from backend.system.logging_setup import get_logger
from backend.utils.paths import DATA_DIRECTORY_ENVIRONMENT_VARIABLE

logger = get_logger(__name__)

#: Berechtigungen, die im Messlauf erlaubt sind. Lesen, rechnen, suchen,
#: sich etwas merken - alles rücknehmbar oder folgenlos.
ERLAUBTE_BERECHTIGUNGEN: frozenset[str] = frozenset(
    {
        "compute",
        "read_time",
        "read_memory",
        "read_files",
        "list_directory",
        "search_files",
        "read_calendar",
        "read_bookmarks",
        "network",
    }
)

#: Werkzeuge, die trotz erlaubter Berechtigung draussen bleiben. Sie
#: schreiben in Bereiche, die sich nicht sauber in einen Messordner
#: umlenken lassen, oder starten lange Hintergrundarbeit.
AUSGENOMMEN: frozenset[str] = frozenset(
    {
        "wissen_aneignen",
        "wissen_vertiefen",
        "webseite_erkunden",
        "neu_starten",
        "oberflaeche_neu_bauen",
    }
)


@contextmanager
def messumgebung(ordner: Path) -> Iterator[Path]:
    """Lenkt die Benutzerdaten für die Dauer des Laufs in einen Messordner.

    Danach steht die Umgebungsvariable wieder wie vorher - auch wenn im
    Lauf etwas schiefgeht.
    """

    ordner.mkdir(parents=True, exist_ok=True)
    vorher = os.environ.get(DATA_DIRECTORY_ENVIRONMENT_VARIABLE)
    os.environ[DATA_DIRECTORY_ENVIRONMENT_VARIABLE] = str(ordner)
    logger.info("Messlauf schreibt nach %s statt in die Benutzerdaten.", ordner)
    try:
        yield ordner
    finally:
        if vorher is None:
            os.environ.pop(DATA_DIRECTORY_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[DATA_DIRECTORY_ENVIRONMENT_VARIABLE] = vorher


def messregister(werkzeuge: list[Any]) -> Any:
    """Baut ein Register aus den erlaubten Werkzeugen.

    Returns:
        Das Register. Was nicht hineindurfte, steht als Abweisung darin und
        ist über ``abgewiesene()`` nachlesbar - auch der Messlauf soll
        nichts stillschweigend verschlucken.
    """

    from backend.tools.registry import ToolRegistry

    register = ToolRegistry()
    for werkzeug in werkzeuge:
        name = str(getattr(werkzeug, "name", "")).strip().lower()
        berechtigung = str(getattr(werkzeug, "permission", ""))
        if name in AUSGENOMMEN:
            continue
        if berechtigung not in ERLAUBTE_BERECHTIGUNGEN:
            continue
        register.register(werkzeug, source="messlauf")
    return register


def alle_messwerkzeuge(security: Any) -> list[Any]:
    """Sammelt die Werkzeuge, die für den Messlauf in Frage kommen.

    Dieselben Bauanleitungen wie im Betrieb - der Messlauf soll nicht an
    einer eigenen, kleineren Wirklichkeit messen.
    """

    from backend.learning.flashcards import FlashcardDeck
    from backend.memory.memory_engine import MemoryEngine
    from backend.tools.karteikarten_tools import build_karteikarten_tools
    from backend.tools.standard_tools import build_standard_tools

    gedaechtnis = MemoryEngine()
    werkzeuge: list[Any] = list(
        build_standard_tools(security=security, memory=gedaechtnis)
    )
    werkzeuge.extend(build_karteikarten_tools(FlashcardDeck()))

    # Die Gedaechtniswerkzeuge brauchen dieselben Bauteile wie im Betrieb:
    # das Langzeitgedaechtnis (nicht die Memory Engine selbst), die
    # Vorliebenerkennung und das Benutzergedaechtnis. Mit dem falschen
    # Bauteil laufen sie an und scheitern beim Schreiben - das ist im
    # Messlauf aufgefallen und hier richtiggestellt.
    try:
        from backend.learning.preference_learner import PreferenceLearner
        from backend.cognitive.long_term_memory import LongTermMemory
        from backend.tools.memory_tools import build_memory_tools

        werkzeuge.extend(
            build_memory_tools(
                long_term=LongTermMemory(gedaechtnis),
                preferences=PreferenceLearner(),
                user_memory=getattr(gedaechtnis, "user", None),
            )
        )
    except Exception:  # noqa: BLE001 - fehlt das Modul, fehlt die Kategorie.
        logger.debug("Gedaechtniswerkzeuge nicht verfuegbar.", exc_info=True)

    # Der Kalender: im Messlauf IMMER der Probekalender.
    #
    # Bis zum 01.09.2026 stand hier der echte Google-Client, und ohne
    # Anmeldung fehlte das Werkzeug ganz. Beide Modelle standen deshalb in
    # fuenf Laeufen bei rechner_02 auf "nicht bestanden" - fuer etwas, das
    # sie nicht zu verantworten hatten.
    #
    # Der Probekalender tauscht ausschliesslich die DATENQUELLE: Gebaut
    # wird mit `build_kalender_tools`, also mit dem echten
    # `termine_ansehen` - gleicher Name, gleiche Parameter, gleiches
    # Rueckgabeformat, gleiches Fehlerverhalten. Beide Modelle bekommen
    # dieselben Termine.
    #
    # Der echte Kalender gehoert in einen Integrationstest, nicht in eine
    # Modellmessung: Ein Messwert, der von einem fremden Anmeldezustand
    # abhaengt, misst die Umgebung und nicht das Modell.
    try:
        from backend.lernen.kalenderprobe import probekalender_werkzeuge

        werkzeuge.extend(probekalender_werkzeuge())
        logger.info(
            "Kalenderwerkzeuge aus dem Probekalender - feste Termine, kein "
            "Google-Konto noetig."
        )
    except Exception:  # noqa: BLE001
        logger.warning("Der Probekalender liess sich nicht bauen.", exc_info=True)

    return werkzeuge


__all__ = [
    "AUSGENOMMEN",
    "ERLAUBTE_BERECHTIGUNGEN",
    "alle_messwerkzeuge",
    "messregister",
    "messumgebung",
]
