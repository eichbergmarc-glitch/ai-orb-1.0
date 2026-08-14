"""Eine Datei finden, auch wenn der Pfad nur ungefähr stimmt.

Der Anlass steht im Protokoll des Benutzers. Er bat den Orb, seinen
Studienplan einzulesen. Der Orb versuchte:

    C:\\Users\\info\\AI-Orb\\OneDrive\\Dokumente\\Geschichtswissenschaft\\
        Studienplan_Geschichte BA Zeitgeschichte.md      -> gibt es nicht
    C:\\Users\\info\\OneDrive\\Dokumente\\Geschichtswissenschaft\\
        Studienplan_Geschichte BA Zeitgeschichte.md      -> gibt es nicht

und gab auf. Die Datei lag in Wahrheit unter ``OneDrive\\Daniel -
Persönlich\\Dokumente\\Geschichtswissenschaft\\`` und hiess
``Studienplan_Geschichte_BA_Zeitgeschichte.md`` – mit Unterstrichen.

Der Orb hatte den Namen also fast richtig und den Ordner fast richtig. Was
ihm fehlte, war nicht ein besseres Gedächtnis, sondern die schlichte
Gewohnheit, NACHZUSEHEN, wenn ein geratener Pfad ins Leere geht. Genau das
leistet dieses Modul: Es nimmt den geratenen Pfad, zieht den Dateinamen
heraus und sucht ihn in den freigegebenen Ordnern – unempfindlich gegen
Unterstriche, Bindestriche und Grossschreibung.

Bewusst KEINE Rate-Automatik: Gibt es mehrere Kandidaten, wird nicht der
erstbeste genommen, sondern die Auswahl zurückgemeldet. Eine falsche Datei
zu lesen ist schlimmer, als noch einmal zu fragen.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Ordner, in denen nichts liegt, was ein Benutzer sucht.
_UEBERSPRINGEN = {
    "node_modules", "__pycache__", ".venv", ".git", "site-packages",
    "AppData", "Windows", "Program Files", "Program Files (x86)",
}

#: Wie lange höchstens gesucht wird. Eine Suche, die eine Antwort aufhält,
#: ist ihrerseits ein Fehler.
_FRIST = 8.0


def _vergleichbar(name: str) -> str:
    """Macht einen Dateinamen vergleichbar.

    Unterstrich, Bindestrich und Leerzeichen sind für einen Menschen
    dasselbe Wort – und genau daran scheiterte der Orb: Er schrieb
    „Studienplan_Geschichte BA" und die Datei hiess
    „Studienplan_Geschichte_BA".
    """

    return re.sub(r"[\s_\-]+", "", name.strip().lower())


def datei_finden(
    pfad_text: str, wurzeln: list[str] | tuple[str, ...], *, hoechstens: int = 8
) -> tuple[Path | None, list[Path]]:
    """Sucht die gemeinte Datei.

    Args:
        pfad_text: Der geratene Pfad oder blosse Dateiname.
        wurzeln: Die freigegebenen Ordner, in denen gesucht werden darf.
        hoechstens: Wie viele Kandidaten höchstens gesammelt werden.

    Returns:
        Ein Paar: die eindeutig gefundene Datei (oder ``None``) und die
        Liste aller Kandidaten. Genau ein Kandidat heisst gefunden;
        mehrere heissen „bitte auswählen".
    """

    roh = (pfad_text or "").strip().strip('"').strip("'")
    if not roh:
        return None, []

    # Steht die Datei einfach da, ist nichts zu suchen.
    direkt = Path(roh)
    try:
        if direkt.is_file():
            return direkt, [direkt]
    except OSError:
        pass

    # Den Dateinamen über BEIDE Trennzeichen bestimmen.
    #
    # ``Path`` kennt unter Linux den Rückstrich nicht als Trenner - ein
    # Windows-Pfad käme dort als EIN langer Name an, und die Suche liefe
    # ins Leere. Der Orb läuft zwar unter Windows, seine Tests aber nicht,
    # und ein Name, der nur auf einem Betriebssystem stimmt, ist ein
    # Fehler, der sich vor den Tests versteckt.
    name = re.split(r"[\\/]", roh)[-1].strip()
    gesucht = _vergleichbar(name)
    if not gesucht:
        return None, []
    # Auch ohne Endung vergleichen: Das Modell hängt gern ".md" an, wo in
    # Wahrheit ".docx" steht.
    stamm = _vergleichbar(name.rsplit(".", 1)[0] if "." in name else name)

    treffer: list[Path] = []
    begonnen = time.perf_counter()

    for wurzel in wurzeln:
        if time.perf_counter() - begonnen > _FRIST:
            break
        try:
            for ordner, unterordner, dateien in os.walk(wurzel):
                unterordner[:] = [
                    name for name in unterordner
                    if not name.startswith(".") and name not in _UEBERSPRINGEN
                ]
                for datei in dateien:
                    verglichen = _vergleichbar(datei)
                    if verglichen == gesucht or _vergleichbar(Path(datei).stem) == stamm:
                        treffer.append(Path(ordner) / datei)
                        if len(treffer) >= hoechstens:
                            break
                if len(treffer) >= hoechstens:
                    break
                if time.perf_counter() - begonnen > _FRIST:
                    break
        except OSError:
            continue

    if treffer:
        logger.info(
            "Der Pfad %r stimmte nicht - gefunden wurden %d passende Dateien.",
            roh[:120], len(treffer),
        )
    return (treffer[0] if len(treffer) == 1 else None), treffer


def hinweis_zu(pfad_text: str, kandidaten: list[Path]) -> str:
    """Formuliert, was mit den Kandidaten zu tun ist – im Klartext."""

    if not kandidaten:
        return (
            f"Die Datei '{pfad_text}' gibt es nicht, und unter diesem Namen "
            "war in deinen freigegebenen Ordnern auch nichts zu finden. "
            "Nenn mir den genauen Namen oder den Ordner, dann sehe ich dort nach."
        )
    zeilen = "\n".join(f"  - {p}" for p in kandidaten[:8])
    return (
        f"Die Datei '{pfad_text}' gibt es unter diesem Pfad nicht. Es passen "
        f"aber {len(kandidaten)} Dateien zum Namen:\n{zeilen}\n"
        "Sag mir, welche gemeint ist, dann nehme ich die."
    )
