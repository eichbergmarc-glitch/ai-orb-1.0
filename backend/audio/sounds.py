"""Klänge, die den Zustand des Orb hörbar machen.

Bisher zeigte der Orb nur, dass er nachdenkt: rot, wirbelnder Nebel. Wer
gerade nicht hinsieht – und das ist bei einem Sprachassistenten die Regel,
sonst bräuchte man ihn nicht –, hörte nach der Frage bloss Stille und
konnte nicht wissen, ob sie überhaupt angekommen ist.

Ein kurzer Klang beantwortet das, ohne ein Wort zu kosten. Er ist die
akustische Entsprechung des roten Leuchtens: „Ich habe dich gehört, ich
arbeite."

Zwei Regeln gelten hier durchgehend:

**Ein Klang darf nie etwas aufhalten.** Er läuft in einem eigenen Faden,
und fehlt die Datei oder scheitert die Ausgabe, geschieht schlicht nichts.
Ein Assistent, der wegen eines Signaltons nicht antwortet, wäre absurd.

**Und nie ins Wort fallen.** Gesprochen wird über den Sprach-Player;
Klänge laufen über einen eigenen. Sie teilen sich weder Zustand noch
Abbruch – sonst hielte der Kern eine laufende Sprachausgabe für beendet,
weil ein Signalton fertig ist.
"""

from __future__ import annotations

import threading
from pathlib import Path

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir, get_project_root

logger = get_logger(__name__)


class Klaenge:
    """Spielt kurze Zustandsklänge ab."""

    def __init__(
        self,
        *,
        denk_klang: str = "",
        hoer_klang: str = "",
        tat_klang: str = "",
        start_klang: str = "",
        aktiv: bool = True,
    ) -> None:
        """
        Args:
            denk_klang: Pfad der Datei für „ich denke nach". Relativ zum
                Programmordner oder absolut. Leer heisst: kein Klang.
            hoer_klang: Pfad der Datei für „ich höre dir zu".
            tat_klang: Pfad der Datei für „ich greife gerade zu" – wenn der
                Orb ein Programm startet, eine Seite öffnet oder sonst
                etwas auf dem Bildschirm tut.
            start_klang: Pfad der Datei für „ich bin da" beim Hochfahren.
            aktiv: Ob überhaupt gespielt wird.
        """

        self._aktiv = aktiv
        self._denken = self._finden(denk_klang)
        self._zuhoeren = self._finden(hoer_klang)
        self._tat = self._finden(tat_klang)
        self._start = self._finden(start_klang)
        self._player = None

        for name, eintrag, gefunden in (
            ("Denk-Klang", denk_klang, self._denken),
            ("Hör-Klang", hoer_klang, self._zuhoeren),
            ("Tat-Klang", tat_klang, self._tat),
            ("Start-Klang", start_klang, self._start),
        ):
            if aktiv and eintrag and gefunden is None:
                logger.warning(
                    "Der %s '%s' wurde nicht gefunden. Gesucht wurde im "
                    "Datenordner und im Programmordner.",
                    name,
                    eintrag,
                )

    @staticmethod
    def _finden(eintrag: str) -> Path | None:
        """Sucht die Klangdatei an den Orten, an denen sie liegen kann."""

        if not eintrag:
            return None

        kandidat = Path(eintrag).expanduser()
        if kandidat.is_absolute():
            return kandidat if kandidat.is_file() else None

        # Der Datenordner zuerst: Wer eine eigene Datei hinterlegt, will
        # sie hören und nicht die mitgelieferte.
        for wurzel in (get_data_dir(), get_project_root()):
            pfad = wurzel / eintrag
            if pfad.is_file():
                return pfad
        return None

    @property
    def denk_klang(self) -> Path | None:
        """Die Datei, die beim Nachdenken erklingt."""

        return self._denken

    @property
    def hoer_klang(self) -> Path | None:
        """Die Datei, die beim Zuhören erklingt."""

        return self._zuhoeren

    @property
    def tat_klang(self) -> Path | None:
        """Die Datei, die beim Zugreifen erklingt."""

        return self._tat

    @property
    def start_klang(self) -> Path | None:
        """Die Datei, die beim Hochfahren erklingt."""

        return self._start

    def denken(self) -> None:
        """Spielt den Denk-Klang – ohne zu warten und ohne je zu stören."""

        if not self._aktiv or self._denken is None:
            return
        self._abspielen(self._denken)

    def zuhoeren(self) -> None:
        """Spielt den Hör-Klang: „Ich bin wach, sprich."

        Er ist die hörbare Antwort auf das Weckwort. Ohne ihn beginnt man
        zu sprechen und weiss erst hinterher, ob überhaupt jemand zugehört
        hat.
        """

        if not self._aktiv or self._zuhoeren is None:
            return
        self._abspielen(self._zuhoeren)

    def tat(self) -> None:
        """Spielt den Tat-Klang: „Ich greife gerade zu."

        Er gehört zu allem, was der Orb nicht sagt, sondern tut – ein
        Programm starten, eine Seite öffnen, etwas installieren. Das ist
        die Gattung von Vorgang, bei der man am ehesten wissen will, dass
        sie läuft, weil sie den Rechner verändert und nicht nur das
        Gespräch.
        """

        if not self._aktiv or self._tat is None:
            return
        self._abspielen(self._tat)

    def start(self) -> None:
        """Spielt den Start-Klang: „Ich bin da."

        Beim Hochfahren gibt es sonst kein Zeichen. Der Orb erscheint
        stumm, und ob er auch hört, erfährt man erst beim ersten Versuch.
        """

        if not self._aktiv or self._start is None:
            return
        self._abspielen(self._start)

    # --- Innenleben --------------------------------------------------------------

    def _abspielen(self, pfad: Path) -> None:
        faden = threading.Thread(
            target=self._blockierend,
            args=(pfad,),
            name="ai-orb-klang",
            daemon=True,
        )
        faden.start()

    def _blockierend(self, pfad: Path) -> None:
        try:
            player = self._eigener_player()
            if player is None:
                return
            player.play_blocking(pfad)
        except Exception:  # noqa: BLE001 - ein Klang darf nie etwas reissen.
            logger.debug("Der Klang ließ sich nicht abspielen.", exc_info=True)

    def _eigener_player(self):
        """Ein eigener Player – ausdrücklich nicht der für die Sprache.

        Teilten sie sich einen, hielte der Kern eine laufende Sprachausgabe
        für beendet, sobald ein Signalton fertig ist – und der Orb bräche
        mitten im Satz ab.
        """

        if self._player is not None:
            return self._player
        try:
            from backend.audio.player import AudioPlayer

            self._player = AudioPlayer()
        except Exception:  # noqa: BLE001
            logger.debug("Kein Player für Klänge verfügbar.", exc_info=True)
            return None
        return self._player

    def status(self) -> dict[str, object]:
        return {
            "aktiv": self._aktiv,
            "denk_klang": str(self._denken) if self._denken else "",
            "hoer_klang": str(self._zuhoeren) if self._zuhoeren else "",
            "tat_klang": str(self._tat) if self._tat else "",
            "start_klang": str(self._start) if self._start else "",
        }


# --- Der gemeinsame Satz Klänge ---------------------------------------------------

_gemeinsam: Klaenge | None = None


def klaenge() -> Klaenge:
    """Liefert die Klänge, die im ganzen Programm dieselben sind.

    Warum überhaupt geteilt? Weil die Klänge inzwischen an zwei ganz
    verschiedenen Stellen gebraucht werden: Die Sprachschleife spielt sie
    beim Zustandswechsel, die Werkzeugschleife beim Zugreifen. Baute jede
    Stelle sich ihren eigenen Satz, gäbe es zwei Player und zwei Suchen
    nach denselben Dateien – und beim Nachsehen, warum ein Klang fehlt,
    zwei Orte statt einem.

    Gebaut wird beim ersten Zugriff, nicht beim Import: Zu diesem Zeitpunkt
    steht die Konfiguration.
    """

    global _gemeinsam
    if _gemeinsam is None:
        from backend.config import get_config

        config = get_config()
        _gemeinsam = Klaenge(
            denk_klang=str(config.get("voice.output.thinking_sound", "")),
            hoer_klang=str(config.get("voice.output.listening_sound", "")),
            tat_klang=str(config.get("voice.output.action_sound", "")),
            start_klang=str(config.get("voice.output.startup_sound", "")),
            aktiv=bool(config.get("voice.sounds_enabled", True)),
        )
    return _gemeinsam


def klaenge_zuruecksetzen() -> None:
    """Vergisst die gemeinsamen Klänge – für Tests mit anderer Konfiguration."""

    global _gemeinsam
    _gemeinsam = None
