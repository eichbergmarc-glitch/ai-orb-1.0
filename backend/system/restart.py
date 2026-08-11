"""Der Neustart – wie AI-Orb sich selbst neu startet.

Nötig wird das, sobald der Orb etwas an seinem eigenen Code ändert. Python
liest eine Moduldatei genau einmal, beim Import. Ohne Neustart hätte er
eine Datei geändert, aber kein Programm.

Warum das aufwendiger ist, als es klingt: Der Python-Kern ist ein
Kindprozess der Electron-Hülle. Er kann sich nicht einfach selbst neu
starten – beendet er sich, sieht die Hülle einen abgestürzten Kern und
meldet genau das. Und ``os.execv``, das unter Linux den Prozess an Ort und
Stelle ersetzt, ist unter Windows ein verkleidetes „starte neu und beende
dich": Die Prozessnummer ändert sich, die Hülle verliert ihr Kind.

Deshalb der Umweg über einen kleinen Helfer, der ausserhalb von beiden
lebt: Er wartet kurz, beendet die laufende Anwendung ganz und startet sie
wieder. Das Warten ist kein Schönheitsfehler, sondern Absicht – der Orb
soll seinen Satz zu Ende sprechen dürfen, bevor ihm der Boden weggezogen
wird.

Gefunden wird der Startweg selbst, ohne feste Benutzerpfade: Bei der
installierten Fassung liegt ``AI-Orb.exe`` zwei Ebenen über dem
Programmordner (``…/AI-Orb/resources/app``), bei der Arbeitsfassung liegt
``ORB-STARTEN.bat`` daneben. Wer es anders eingerichtet hat, trägt den
Befehl unter ``system.restart_command`` in die config.yaml ein.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir, get_project_root

logger = get_logger(__name__)

#: Wie lange der Helfer wartet, bevor er zuschlägt.
#:
#: Lang genug, dass „Ich starte mich neu" noch gesprochen wird; kurz genug,
#: dass niemand glaubt, es sei nichts passiert.
_WARTEN_SEKUNDEN = 6


def finde_startweg(root: Path | None = None) -> Path | None:
    """Sucht den Weg, auf dem AI-Orb gestartet wird.

    Bewusst in dieser Reihenfolge: Die installierte Fassung zuerst, denn
    wer sie benutzt, hat sie im Startmenü – die Arbeitsfassung startet
    ohnehin meist von Hand.

    Returns:
        Der Startweg oder ``None``, wenn keiner gefunden wurde.
    """

    wurzel = root or get_project_root()
    kandidaten: list[Path] = []

    # Installierte Fassung: …/AI-Orb/resources/app -> …/AI-Orb/AI-Orb.exe
    if len(wurzel.parents) >= 2:
        kandidaten.append(wurzel.parents[1] / "AI-Orb.exe")

    # Arbeitsfassung: die Startdatei liegt im Projektordner.
    kandidaten.append(wurzel / "ORB-STARTEN.bat")
    kandidaten.append(wurzel.parent / "ORB-STARTEN.bat")

    for kandidat in kandidaten:
        try:
            if kandidat.is_file():
                return kandidat
        except OSError:
            continue
    return None


def helferskript(
    startweg: Path, *, warten: int = _WARTEN_SEKUNDEN, eltern_pid: int = 0
) -> str:
    """Baut den Text des Helfers, der den Neustart ausführt.

    Als eigene Funktion, damit sich prüfen lässt, was da erzeugt wird,
    ohne dass dabei irgendetwas beendet würde.

    Args:
        startweg: Womit AI-Orb wieder gestartet wird.
        warten: Sekunden bis zum Zugriff.
        eltern_pid: Die Prozessnummer der Hülle, die den Kern gestartet
            hat. Über sie wird beendet – und zwar aus gutem Grund:

            Beendete man stattdessen über den Programmnamen, träfe das bei
            der installierten Fassung ``AI-Orb.exe``, bei der
            Arbeitsfassung aber ``electron.exe`` – und davon laufen auf
            einem Entwicklerrechner gern mehrere, die nichts miteinander zu
            tun haben. Über die Prozessnummer wird genau der Prozess
            beendet, der uns gestartet hat, und kein anderer.
    """

    if os.name == "nt":
        # timeout statt ping: verständlicher, und /nobreak verhindert, dass
        # ein Tastendruck das Warten abkürzt.
        # /T nimmt den Prozessbaum mit – der Python-Kern ist ein Kind der
        # Hülle und bliebe sonst als Waise zurück und hielte den Port.
        zeilen = [
            "@echo off",
            "rem Von AI-Orb erzeugt, um sich selbst neu zu starten.",
            f"timeout /t {warten} /nobreak >nul",
        ]
        if eltern_pid > 0:
            zeilen.append(f"taskkill /PID {eltern_pid} /T /F >nul 2>&1")
        else:
            # Ohne bekannte Prozessnummer bleibt nur der Name. Trifft nur
            # die installierte Fassung.
            zeilen.append('taskkill /IM "AI-Orb.exe" /T /F >nul 2>&1')
        zeilen.append("timeout /t 3 /nobreak >nul")
        zeilen.append(f'start "" "{startweg}"')
        return "\r\n".join(zeilen) + "\r\n"

    # Unter Linux und macOS gibt es die installierte Fassung nicht; der
    # Zweig existiert, damit sich der Weg überhaupt prüfen lässt.
    beenden = f"kill -9 {eltern_pid}" if eltern_pid > 0 else "pkill -f AI-Orb"
    return (
        "#!/bin/sh\n"
        "# Von AI-Orb erzeugt, um sich selbst neu zu starten.\n"
        f"sleep {warten}\n"
        f"{beenden} >/dev/null 2>&1\n"
        "sleep 3\n"
        f'exec "{startweg}"\n'
    )


class Neustarter:
    """Fordert einen Neustart an und führt ihn über einen Helfer aus."""

    def __init__(self, *, startweg: Path | None = None, warten: int = _WARTEN_SEKUNDEN) -> None:
        """
        Args:
            startweg: Der Startweg. ``None`` sucht ihn selbst.
            warten: Sekunden, die der Helfer wartet, bevor er beendet.
        """

        self._startweg = startweg
        self._warten = warten
        #: Ob bereits ein Neustart läuft. Zweimal hintereinander wäre kein
        #: doppelter Neustart, sondern ein Wettlauf zweier Helfer.
        self._laeuft = False

    @property
    def laeuft(self) -> bool:
        """Ob schon ein Neustart angefordert wurde."""

        return self._laeuft

    def startweg(self) -> Path | None:
        """Der Startweg, gesucht und gemerkt."""

        if self._startweg is None:
            self._startweg = finde_startweg()
        return self._startweg

    def anfordern(self, grund: str = "auf Wunsch") -> tuple[bool, str]:
        """Stösst den Neustart an.

        Returns:
            Ob es angestossen wurde und eine Meldung im Klartext – die
            geht an den Benutzer, also erklärt sie im Zweifel, was fehlt.
        """

        if self._laeuft:
            return True, "Der Neustart läuft bereits – gleich bin ich wieder da."

        weg = self.startweg()
        if weg is None:
            return False, (
                "Ich finde meinen eigenen Startweg nicht und starte mich "
                "deshalb nicht neu – ich käme sonst vielleicht nicht wieder. "
                "Schliess mich bitte und starte mich von Hand; oder trag den "
                "Startbefehl unter 'system.restart_command' in die config.yaml "
                "ein."
            )

        try:
            helfer = self._schreibe_helfer(weg)
        except OSError as fehler:
            return False, f"Ich konnte den Neustart nicht vorbereiten: {fehler}"

        try:
            self._starte_helfer(helfer)
        except OSError as fehler:
            logger.exception("Der Neustart-Helfer ließ sich nicht starten.")
            return False, f"Der Neustart ließ sich nicht anstossen: {fehler}"

        self._laeuft = True
        logger.info("Neustart angefordert (%s) über %s.", grund, weg)
        return True, (
            f"Ich starte mich in {self._warten} Sekunden neu ({grund}). "
            "Das Fenster verschwindet kurz und kommt von selbst zurück."
        )

    # --- Innenleben --------------------------------------------------------------

    @staticmethod
    def _eltern_pid() -> int:
        """Die Prozessnummer der Hülle, die den Kern gestartet hat.

        Null bedeutet: unbekannt. Dann beendet der Helfer über den
        Programmnamen – ungenauer, aber besser als gar nicht.
        """

        try:
            eltern = os.getppid()
        except (AttributeError, OSError):
            return 0
        # 0 und 1 sind keine sinnvollen Ziele: Der Kern läuft dann ohne
        # Hülle, etwa direkt aus einer Eingabeaufforderung.
        return eltern if eltern > 1 else 0

    def _schreibe_helfer(self, startweg: Path) -> Path:
        """Legt den Helfer im Datenordner ab."""

        ordner = get_data_dir()
        ordner.mkdir(parents=True, exist_ok=True)
        pfad = ordner / ("neustart.cmd" if os.name == "nt" else "neustart.sh")
        pfad.write_text(
            helferskript(startweg, warten=self._warten, eltern_pid=self._eltern_pid()),
            encoding="utf-8" if os.name != "nt" else "ascii",
            errors="replace",
        )
        if os.name != "nt":
            pfad.chmod(0o755)
        return pfad

    def _starte_helfer(self, helfer: Path) -> None:
        """Startet den Helfer losgelöst vom eigenen Prozess.

        Losgelöst ist hier das Entscheidende: Der Helfer bringt gleich den
        Prozess um, der ihn gestartet hat. Hinge er an ihm, stürbe er mit –
        und der Neustart bliebe auf halbem Weg stehen.
        """

        if os.name == "nt":
            flags = 0
            flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            subprocess.Popen(  # noqa: S603
                ["cmd", "/c", str(helfer)],
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(helfer.parent),
            )
            return

        subprocess.Popen(  # noqa: S603
            [str(helfer)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(helfer.parent),
        )


def baue_neustarter(config: object | None = None) -> Neustarter:
    """Erzeugt den Neustarter, mit dem Startweg aus der Konfiguration.

    Ein eingetragener ``system.restart_command`` hat Vorrang: Wer seine
    Installation eigenhändig zurechtgelegt hat, weiss besser als jede
    Suche, womit sie startet.
    """

    eigener = ""
    if config is not None:
        try:
            eigener = str(config.get("system.restart_command", "") or "").strip()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            eigener = ""

    if eigener:
        pfad = Path(os.path.expanduser(eigener))
        if pfad.is_file():
            return Neustarter(startweg=pfad)
        logger.warning(
            "'system.restart_command' zeigt auf %s – dort ist nichts. Der "
            "Startweg wird stattdessen gesucht.",
            pfad,
        )

    return Neustarter()
