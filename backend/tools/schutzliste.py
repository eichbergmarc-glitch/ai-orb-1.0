"""Dateien, die der Orb nicht überschreiben darf - und Sicherungen für den Rest.

## Was passiert ist

Am 19.08.2026 um 13:34 war ``config.yaml`` plötzlich 172 Bytes gross. Sie
hatte 83 Kilobyte. An ihrer Stelle stand ein einziger Satz::

    "anstatt zu raten, dass ich Informationen aus dem Gedächtnis habe,
     rufe ich bei Fragen nach dem Wissensstand meines Gedächtnisses
     zuerst nach, bevor ich eine Antwort gebe."

Das ist keine Konfiguration. Das ist eine Notiz, die der Orb sich selbst
schreiben wollte - und er hat dafür die erstbeste Datei genommen, deren
Name ihm einfiel. Das Werkzeug ``datei_schreiben`` liess ihn: Es prüft die
Länge des Textes und ob der Pfad im freigegebenen Bereich liegt, und
danach schreibt es. Im Sicherheitsmodus "offen" liegt alles im
freigegebenen Bereich, auch die eigene Konfiguration, auch ``.env`` mit
den Zugangsschlüsseln, auch das Gedächtnis.

Der Orb lief danach mit einer Konfiguration aus einem Satz weiter.

## Zwei Vorkehrungen, nicht eine

**Erstens die Sperre.** Eine Handvoll Dateien ist unersetzlich: Sie lassen
sich nicht neu erzeugen, und ohne sie ist der Orb ein anderer. Sie
anzufassen wird abgelehnt, mit einer Begründung, die sagt, was stattdessen
zu tun ist. Diese Liste ist absichtlich kurz - eine lange Sperrliste
lädt dazu ein, sie zu umgehen.

**Zweitens die Sicherung.** Alles Übrige darf überschrieben werden, aber
nie spurlos: Vor jedem Ersetzen einer bestehenden Datei wandert die alte
Fassung nach ``data/datei_sicherungen``. Das kostet Millisekunden und ist
der Unterschied zwischen einem Ärgernis und einem verlorenen Abend.

Warum nicht einfach alles sperren? Weil der Orb seinen eigenen Quelltext
verändern können soll - das ist eine seiner Fähigkeiten, nicht ein
Versehen. Gesperrt gehört, was ihn beim Verlust unbrauchbar macht;
gesichert gehört der Rest.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Dateinamen, die unter keinen Umständen überschrieben werden.
#:
#: Verglichen wird der Name, nicht der ganze Pfad: Eine ``config.yaml``
#: ist überall im Projekt dieselbe Art von Datei, und der Orb greift auf
#: sie mal absolut, mal relativ zu.
_GESPERRTE_NAMEN: dict[str, str] = {
    "config.yaml": (
        "Das ist die Konfiguration des Orb. Sie zu überschreiben legt ihn "
        "lahm - am 19.08.2026 ist genau das passiert. Einzelne Einstellungen "
        "ändert man mit 'einstellung_setzen', nicht durch Neuschreiben der Datei."
    ),
    "config.yml": "Das ist die Konfiguration des Orb (siehe config.yaml).",
    ".env": (
        "Dort stehen die Zugangsschlüssel. Sie zu überschreiben trennt den "
        "Orb von allen Diensten, und wiederherstellen kann sie niemand ausser "
        "dem Benutzer."
    ),
    "memory.json": (
        "Das ist das Gedächtnis des Orb. Einzelne Einträge ändert man mit den "
        "Gedächtnis-Werkzeugen, nicht durch Überschreiben der ganzen Datei."
    ),
    "stimmprofil.json": (
        "Das ist die hinterlegte Stimme des Benutzers. Ohne sie erkennt der "
        "Orb ihn nicht mehr, und neu anlernen kann sie nur er selbst."
    ),
    "user_profile.json": "Das sind die gespeicherten Angaben über den Benutzer.",
    "requirements.txt": "Ohne die Abhängigkeitsliste lässt sich der Orb nicht neu aufsetzen.",
    "tagebuch.json": (
        "Das ist das Tagebuch des Benutzers - persönliche Einträge, die "
        "sich nicht wiederherstellen lassen. Neue Einträge schreibt man "
        "mit 'tagebuch_schreiben', nie durch Überschreiben der Datei."
    ),
}

#: Ordner, in denen gar nichts geschrieben wird.
_GESPERRTE_ORDNER: tuple[str, ...] = (
    ".git", "node_modules", "__pycache__", "tagebuch-bilder",
)

#: Wohin die alten Fassungen wandern.
_SICHERUNGSORDNER = Path("data") / "datei_sicherungen"

#: So viele Sicherungen je Datei bleiben liegen. Mehr braucht niemand, und
#: eine Sicherung, die den Datenträger füllt, ist selbst ein Schaden.
_HOECHSTENS = 5


def sperrgrund(pfad: Path | str) -> str | None:
    """Warum diese Datei nicht überschrieben werden darf - oder ``None``.

    Der Rückgabewert ist der Klartext, der beim Benutzer ankommt. Ein
    blosses "nicht erlaubt" hilft niemandem: Wer eine Einstellung ändern
    will, soll erfahren, womit.
    """

    p = Path(str(pfad))
    if any(teil in _GESPERRTE_ORDNER for teil in p.parts):
        return (
            f"In '{p.parent}' wird nichts geschrieben - das ist ein "
            "Verwaltungsordner, kein Arbeitsordner."
        )
    return _GESPERRTE_NAMEN.get(p.name.lower())


def sichern(pfad: Path, *, wurzel: Path | None = None) -> Path | None:
    """Legt eine Kopie der bestehenden Datei ab, bevor sie ersetzt wird.

    Fehler beim Sichern dürfen den Schreibvorgang nicht verhindern - sonst
    wäre die Vorsichtsmassnahme selbst ein Ausfallgrund. Sie werden
    protokolliert und sonst hingenommen.

    Returns:
        Der Pfad der Sicherung, oder ``None``, wenn nichts zu sichern war.
    """

    try:
        if not pfad.is_file() or pfad.stat().st_size == 0:
            return None
    except OSError:
        return None

    ordner = (wurzel or Path.cwd()) / _SICHERUNGSORDNER
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        marke = time.strftime("%Y%m%d-%H%M%S")
        ziel = ordner / f"{pfad.name}.{marke}.bak"
        # Bei mehreren Sicherungen in derselben Sekunde nicht ueberschreiben.
        zaehler = 1
        while ziel.exists():
            ziel = ordner / f"{pfad.name}.{marke}-{zaehler}.bak"
            zaehler += 1
        shutil.copy2(pfad, ziel)
    except OSError as fehler:
        logger.warning("Sicherung von %s nicht moeglich: %s", pfad, fehler)
        return None

    _aufraeumen(ordner, pfad.name)
    logger.info("Alte Fassung gesichert: %s", ziel)
    return ziel


def _aufraeumen(ordner: Path, name: str) -> None:
    """Lässt je Datei nur die jüngsten Sicherungen liegen."""

    try:
        vorhanden = sorted(
            ordner.glob(f"{name}.*.bak"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for alt in vorhanden[_HOECHSTENS:]:
        try:
            alt.unlink()
        except OSError:  # noqa: PERF203 - eine misslungene Loeschung ist harmlos.
            logger.debug("Alte Sicherung %s liess sich nicht loeschen.", alt)
