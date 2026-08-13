"""Stimmerkennung – auf wen der Orb hört und auf wen nicht.

Das Mikrofon hört alles: den Fernseher, ein Gespräch am Nebentisch, eine
Videokonferenz. Bisher war dem Orb jede Stimme gleich viel wert, und er
nahm Sätze als Anweisung entgegen, die niemand an ihn gerichtet hatte.

Dieses Modul beantwortet die eine Frage davor: Ist das die Stimme, auf die
der Orb hören soll? Es tut das ohne Netz, ohne Dienst und ohne grosses
Modell – mit den Mitteln, die ohnehin da sind (NumPy und das WAV-Modul der
Standardbibliothek).

**Wie es arbeitet.** Aus der Aufnahme werden MFCC-Merkmale gewonnen: eine
kompakte Beschreibung der Klangfarbe, wie sie in der Sprachverarbeitung
seit Jahrzehnten benutzt wird. Grob gesagt beschreibt sie die Form des
Vokaltrakts – und die ist bei jedem Menschen anders, unabhängig davon,
welche Wörter er gerade sagt. Aus Mittelwert und Streuung dieser Merkmale
über die stimmhaften Teile der Aufnahme entsteht ein kurzer Zahlenvektor,
der Abdruck. Zwei Aufnahmen derselben Person haben ähnliche Abdrücke.

Der erste Koeffizient wird ausdrücklich weggelassen: Er misst im
Wesentlichen die Lautstärke, und wie laut jemand spricht oder wie weit er
vom Mikrofon entfernt sitzt, hat mit seiner Identität nichts zu tun.

**Was es kann und was nicht.** Das erkennt zuverlässig, dass eine deutlich
andere Stimme spricht – der Fernseher, eine andere Person im Raum. Es ist
kein Stimmschloss: Eine sehr ähnliche Stimme, eine starke Erkältung oder
ein anderes Mikrofon können es täuschen. Deshalb ist die Voreinstellung
nachsichtig: Im Zweifel wird zugehört. Lieber einmal auf den Fernseher
reagieren als die eigene Stimme nicht mehr zu erkennen – wer ausgesperrt
wird, kann es dem Orb nicht einmal mehr sagen.
"""

from __future__ import annotations

import json
import math
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Aufnahmen kommen mit dieser Abtastrate; alles andere wird abgelehnt.
SAMPLE_RATE = 16000

#: Fensterlänge und Schrittweite der Merkmalsberechnung.
#:
#: 25 ms sind lang genug, dass eine Tonhöhenperiode hineinpasst, und kurz
#: genug, dass sich der Klang darin nicht wesentlich ändert. Das ist der
#: Standardwert der Sprachverarbeitung, und es gibt keinen Grund, davon
#: abzuweichen.
FRAME_MS = 25.0
HOP_MS = 10.0

#: Anzahl der Mel-Filter und der behaltenen Koeffizienten.
MEL_FILTERS = 26
#: Ohne den nullten: Der misst die Lautstärke, nicht die Person.
MFCC_COUNT = 12

#: Kürzere Aufnahmen ergeben keinen verlässlichen Abdruck.
#:
#: Bei einer halben Sekunde bleiben nach Abzug der stillen Teile oft nur
#: eine Handvoll Rahmen übrig, und aus einer Handvoll lässt sich kein
#: Mittelwert bilden, auf den man etwas geben möchte.
MIN_SPEECH_SECONDS = 0.7

#: Wie weit ein Rahmen unter dem lautesten liegen darf, in Dezibel.
#:
#: In einem gesprochenen Satz liegen zwischen dem lautesten Vokal und einem
#: unbetonten Konsonanten leicht zwanzig Dezibel. Wer den Abstand enger
#: zieht, behält nur die Gipfel – und aus vier Sätzen wird eine Drittel
#: Sekunde Sprache, zu wenig für einen Abdruck. Genau das war der Fall:
#: Die Grenze stand nominell auf 25, war aber in einer Einheit notiert, in
#: der das 4,2 dB bedeutete.
#:
#: Fünfundzwanzig lässt einen ganzen Satz durch und schneidet trotzdem
#: die Pausen weg, in denen nur der Raum klingt.
ABSTAND_ZUM_GIPFEL_DB = 25.0


@dataclass
class Urteil:
    """Das Ergebnis einer Stimmprüfung."""

    #: Ob zugehört werden soll.
    akzeptiert: bool
    #: Wie ähnlich die Stimme dem Profil ist (-1 bis 1).
    aehnlichkeit: float = 0.0
    #: Die Schwelle, gegen die geprüft wurde.
    schwelle: float = 0.0
    #: Warum so entschieden wurde – im Klartext.
    grund: str = ""
    #: Ob überhaupt geprüft werden konnte.
    geprueft: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "akzeptiert": self.akzeptiert,
            "aehnlichkeit": round(self.aehnlichkeit, 3),
            "schwelle": round(self.schwelle, 3),
            "grund": self.grund,
            "geprueft": self.geprueft,
        }


# --- Merkmalsberechnung ---------------------------------------------------------


def _numpy():
    """Holt NumPy oder sagt verständlich, dass es fehlt."""

    try:
        import numpy
    except ImportError as fehler:  # pragma: no cover - hängt von der Umgebung ab
        raise RuntimeError(
            "Für die Stimmerkennung fehlt das Paket 'numpy'. Sag mir "
            "'Rüste dir das Paket numpy nach', dann hole ich es."
        ) from fehler
    return numpy


def _hertz_zu_mel(hertz: float) -> float:
    return 2595.0 * math.log10(1.0 + hertz / 700.0)


def _mel_zu_hertz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def mel_filterbank(fft_size: int, sample_rate: int = SAMPLE_RATE, filters: int = MEL_FILTERS):
    """Baut die Mel-Filterbank – dreieckige Filter auf der Mel-Skala.

    Die Mel-Skala bildet ab, wie das Ohr Tonhöhen wahrnimmt: Unten fein,
    oben grob. Ein Unterschied von 100 Hz ist bei tiefen Tönen deutlich
    hörbar und bei hohen kaum. Die Filter folgen dieser Auflösung, statt
    das Spektrum gleichmässig zu zerteilen.
    """

    np = _numpy()

    tief_mel = _hertz_zu_mel(80.0)
    hoch_mel = _hertz_zu_mel(min(7600.0, sample_rate / 2.0))
    punkte_mel = np.linspace(tief_mel, hoch_mel, filters + 2)
    punkte_hz = np.array([_mel_zu_hertz(float(m)) for m in punkte_mel])
    bins = np.floor((fft_size + 1) * punkte_hz / sample_rate).astype(int)
    bins = np.clip(bins, 0, fft_size // 2)

    bank = np.zeros((filters, fft_size // 2 + 1), dtype=np.float64)
    for index in range(filters):
        links, mitte, rechts = bins[index], bins[index + 1], bins[index + 2]
        if mitte == links:
            mitte = links + 1
        if rechts <= mitte:
            rechts = mitte + 1
        if rechts > fft_size // 2:
            rechts = fft_size // 2
        if mitte >= rechts or links >= mitte:
            continue
        for k in range(links, mitte):
            bank[index, k] = (k - links) / (mitte - links)
        for k in range(mitte, rechts):
            bank[index, k] = (rechts - k) / (rechts - mitte)
    return bank


def _dct_matrix(zeilen: int, spalten: int):
    """Die DCT-II-Matrix, mit der aus dem Mel-Spektrum die MFCC werden."""

    np = _numpy()
    n = np.arange(spalten)
    matrix = np.zeros((zeilen, spalten), dtype=np.float64)
    for k in range(zeilen):
        matrix[k] = np.cos(math.pi * k / spalten * (n + 0.5))
    return matrix


def lese_wav(pfad: Path):
    """Liest eine WAV-Datei als Zahlenreihe zwischen -1 und 1.

    Raises:
        ValueError: Bei einem Format, das nicht von der Aufnahme stammt.
    """

    np = _numpy()

    with wave.open(str(pfad), "rb") as datei:
        if datei.getsampwidth() != 2:
            raise ValueError("Nur 16-Bit-Aufnahmen werden ausgewertet.")
        kanaele = datei.getnchannels()
        rate = datei.getframerate()
        rohdaten = datei.readframes(datei.getnframes())

    proben = np.frombuffer(rohdaten, dtype="<i2").astype(np.float64) / 32768.0
    if kanaele > 1:
        # Mehrkanal zusammenlegen; die Aufnahme ist einkanalig, aber eine
        # fremde Datei muss nicht daran scheitern.
        proben = proben.reshape(-1, kanaele).mean(axis=1)
    return proben, rate


def merkmale(pfad: Path):
    """Berechnet die MFCC-Merkmale einer Aufnahme, Rahmen für Rahmen.

    Returns:
        Eine Matrix (Rahmen × Koeffizienten) und die Energie je Rahmen.
    """

    np = _numpy()

    proben, rate = lese_wav(pfad)
    if rate != SAMPLE_RATE:
        raise ValueError(f"Erwartet werden {SAMPLE_RATE} Hz, gelesen wurden {rate}.")
    if proben.size == 0:
        return np.zeros((0, MFCC_COUNT)), np.zeros(0)

    # Preemphase: hebt die hohen Anteile an, die im Sprachsignal schwächer
    # sind. Ohne sie beherrschen die tiefen Frequenzen das Bild, und die
    # Unterschiede zwischen Stimmen sitzen gerade oben.
    betont = np.append(proben[0], proben[1:] - 0.97 * proben[:-1])

    rahmenlaenge = int(SAMPLE_RATE * FRAME_MS / 1000.0)
    schritt = int(SAMPLE_RATE * HOP_MS / 1000.0)
    if betont.size < rahmenlaenge:
        return np.zeros((0, MFCC_COUNT)), np.zeros(0)

    anzahl = 1 + (betont.size - rahmenlaenge) // schritt
    indizes = np.arange(rahmenlaenge)[None, :] + schritt * np.arange(anzahl)[:, None]
    rahmen = betont[indizes] * np.hamming(rahmenlaenge)[None, :]

    fft_size = 512
    spektrum = np.abs(np.fft.rfft(rahmen, n=fft_size)) ** 2 / fft_size

    bank = mel_filterbank(fft_size)
    mel = spektrum @ bank.T
    # Der kleine Zuschlag verhindert den Logarithmus von null – bei
    # vollkommener Stille käme sonst minus unendlich heraus und mit ihm
    # NaN durch die ganze Rechnung.
    mel = np.log(np.maximum(mel, 1e-10))

    dct = _dct_matrix(MFCC_COUNT + 1, MEL_FILTERS)
    koeffizienten = mel @ dct.T

    # Der nullte Koeffizient ist die Lautstärke – aber in einer eigenen
    # Einheit, und die war der Grund, warum sich keine Stimme lernen liess.
    #
    # Er ist die Summe der logarithmierten Mel-Werte über alle Filter, im
    # natürlichen Logarithmus. Ein Punkt darin sind also nicht ein Dezibel,
    # sondern 10/ln(10)/MEL_FILTERS ≈ 0,167 dB. Wer diesen Wert für Dezibel
    # hält und "25 unter dem Maximum" schreibt, meint 25 dB und bekommt
    # 4,2 – und damit fällt fast eine ganze Aufnahme weg, weil in einem
    # gesprochenen Satz nur die lautesten Vokale so nah am Gipfel liegen.
    #
    # Umgerechnet wird deshalb hier, an der Quelle, und nicht beim
    # Vergleichen: Was diese Funktion herausgibt, sind Dezibel, und damit
    # bedeutet eine Zahl beim Aufrufer das, was dort steht.
    energie = koeffizienten[:, 0] * (10.0 / math.log(10.0) / MEL_FILTERS)

    # Ab dem ersten: Der nullte ist die Lautstärke.
    return koeffizienten[:, 1:], energie


def abdruck(pfad: Path):
    """Verdichtet eine Aufnahme zu einem Abdruck der Stimme.

    Genommen werden nur die lauteren Rahmen: In den Pausen zwischen den
    Wörtern steht der Klang des Raumes, nicht der der Person.

    Returns:
        Ein Vektor der Länge ``2 * MFCC_COUNT`` – oder ``None``, wenn zu
        wenig Sprache darin war.
    """

    np = _numpy()

    koeffizienten, energie = merkmale(pfad)
    if koeffizienten.shape[0] == 0:
        return None

    # Ausgewählt wird nach Rangfolge, nicht nach einem festen Pegel: die
    # lauteren sechzig Prozent der Rahmen.
    #
    # Eine feste Schwelle in Dezibel wäre von der Aussteuerung abhängig –
    # dieselbe Stimme, einmal nah und einmal fern aufgenommen, ergäbe
    # einmal viele und einmal fast keine Rahmen. Der Rang innerhalb der
    # eigenen Aufnahme ist davon unabhängig. Die zweite Bedingung wirft
    # zusätzlich weg, was weit unter dem Maximum liegt: In einer Aufnahme,
    # die fast nur aus Stille besteht, wären auch die „lauteren sechzig
    # Prozent" noch Stille.
    untergrenze = max(
        float(np.percentile(energie, 40.0)),
        float(np.max(energie)) - ABSTAND_ZUM_GIPFEL_DB,
    )
    laut = energie >= untergrenze

    gewaehlt = koeffizienten[laut]
    if gewaehlt.shape[0] * HOP_MS / 1000.0 < MIN_SPEECH_SECONDS:
        return None

    vektor = np.concatenate([gewaehlt.mean(axis=0), gewaehlt.std(axis=0)])
    laenge = float(np.linalg.norm(vektor))
    if laenge < 1e-9:
        return None
    return vektor / laenge


def aehnlichkeit(einer, anderer) -> float:
    """Kosinus-Ähnlichkeit zweier Abdrücke (beide bereits normiert)."""

    np = _numpy()
    return float(np.clip(np.dot(einer, anderer), -1.0, 1.0))


def sprechrhythmus(pfad: Path) -> tuple[float, int] | None:
    """Misst relative Sprechdichte und typische Pausen, niemals Klangfarbe."""

    np = _numpy()
    proben, rate = lese_wav(pfad)
    if proben.size < rate:
        return None
    frame = max(1, int(rate * 0.02))
    usable = (proben.size // frame) * frame
    frames = proben[:usable].reshape(-1, frame)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    db = 20.0 * np.log10(np.maximum(rms, 1e-8))
    threshold = max(float(np.percentile(db, 55.0)), float(np.max(db)) - 28.0)
    active = db >= threshold
    active_ratio = float(np.mean(active))
    if active_ratio < 0.12:
        return None

    pauses: list[int] = []
    start = 0
    while start < len(active):
        if active[start]:
            start += 1
            continue
        end = start
        while end < len(active) and not active[end]:
            end += 1
        milliseconds = (end - start) * 20
        if start > 0 and end < len(active) and 80 <= milliseconds <= 1200:
            pauses.append(milliseconds)
        start = end

    pause_ms = int(round(float(np.median(pauses)))) if pauses else 180
    tempo = max(0.88, min(1.08, 0.90 + active_ratio * 0.30))
    return round(tempo, 3), max(130, min(420, pause_ms))


# --- Das Profil -----------------------------------------------------------------


@dataclass
class Stimmprofil:
    """Die gelernte Stimme – mehrere Abdrücke und ihre Schwelle."""

    abdruecke: list[list[float]] = field(default_factory=list)
    #: Ab welcher Ähnlichkeit die Stimme als bekannt gilt.
    schwelle: float = 0.0
    #: Wie viele Aufnahmen eingeflossen sind.
    aufnahmen: int = 0
    #: Ausschliesslich Rhythmuswerte; daraus laesst sich keine Stimme
    #: rekonstruieren. 1.0 bedeutet das normale TTS-Tempo.
    sprechtempo: float = 1.0
    pause_ms: int = 180

    @property
    def gelernt(self) -> bool:
        return len(self.abdruecke) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "abdruecke": self.abdruecke,
            "schwelle": self.schwelle,
            "aufnahmen": self.aufnahmen,
            "sprechstil": {
                "tempo": round(self.sprechtempo, 3),
                "pause_ms": self.pause_ms,
            },
        }

    @classmethod
    def from_dict(cls, daten: dict[str, Any]) -> "Stimmprofil":
        stil = daten.get("sprechstil", {}) or {}
        return cls(
            abdruecke=[list(map(float, eintrag)) for eintrag in daten.get("abdruecke", [])],
            schwelle=float(daten.get("schwelle", 0.0)),
            aufnahmen=int(daten.get("aufnahmen", 0)),
            sprechtempo=float(stil.get("tempo", 1.0)),
            pause_ms=int(stil.get("pause_ms", 180)),
        )


class Stimmerkennung:
    """Lernt eine Stimme und prüft später, ob sie es wieder ist."""

    def __init__(
        self,
        *,
        profil_pfad: Path,
        mindestaehnlichkeit: float = 0.55,
        hoechstschwelle: float = 0.80,
        sicherheitsabstand: float = 0.06,
        aktiv: bool = True,
    ) -> None:
        """
        Args:
            profil_pfad: Wohin das Profil geschrieben wird.
            mindestaehnlichkeit: Die Untergrenze der Schwelle. Auch eine
                sehr gleichmässige Stimme senkt sie nicht darunter.
            hoechstschwelle: Die Obergrenze. Klangen die Lernaufnahmen
                einander sehr ähnlich – etwa, weil sie kurz nacheinander
                im selben Ton entstanden –, ergäbe die Rechnung eine
                Schwelle, an der später die eigene Stimme scheitert, sobald
                sie müde, erkältet oder weiter weg ist. Die Obergrenze ist
                die Decke der Strenge.
            sicherheitsabstand: Wie weit die Schwelle unter der geringsten
                Ähnlichkeit der Lernaufnahmen untereinander liegt. Der
                Abstand ist Nachsicht in Zahlen: Die eigene Stimme klingt
                erkältet, müde oder aus anderer Entfernung anders als beim
                Lernen, und sie soll trotzdem durchkommen.
            aktiv: Ob überhaupt geprüft wird.
        """

        self._pfad = profil_pfad
        self._mindest = mindestaehnlichkeit
        self._hoechst = max(mindestaehnlichkeit, hoechstschwelle)
        self._abstand = sicherheitsabstand
        self._aktiv = aktiv
        self._profil = self._laden()
        self._rhythmus_updates = 0

    # --- Zustand ----------------------------------------------------------------

    @property
    def gelernt(self) -> bool:
        """Ob eine Stimme hinterlegt ist."""

        return self._profil.gelernt

    @property
    def aktiv(self) -> bool:
        """Ob geprüft wird – nur mit gelernter Stimme sinnvoll."""

        return self._aktiv and self._profil.gelernt

    def status(self) -> dict[str, Any]:
        return {
            "aktiv": self.aktiv,
            "gelernt": self.gelernt,
            "aufnahmen": self._profil.aufnahmen,
            "schwelle": round(self._profil.schwelle, 3),
            "sprechstil": {
                "tempo": round(self._profil.sprechtempo, 3),
                "pause_ms": self._profil.pause_ms,
            },
        }

    @property
    def sprechstil(self) -> dict[str, float | int]:
        return {
            "tempo": self._profil.sprechtempo if self.gelernt else 1.0,
            "pause_ms": self._profil.pause_ms if self.gelernt else 180,
        }

    def rhythmus_aktualisieren(self, pfad: Path) -> bool:
        """Lernt nach sicherer Erkennung nur Tempo/Pausen gleitend weiter."""

        if not self.gelernt:
            return False
        try:
            gemessen = sprechrhythmus(pfad)
        except Exception as fehler:  # noqa: BLE001 - Stil darf Erkennung nie stören.
            logger.debug("Sprechrhythmus nicht messbar: %s", fehler)
            return False
        if gemessen is None:
            return False
        tempo, pause_ms = gemessen
        anteil = 0.18
        self._profil.sprechtempo = max(
            0.88,
            min(1.08, self._profil.sprechtempo * (1.0 - anteil) + tempo * anteil),
        )
        self._profil.pause_ms = max(
            130,
            min(420, round(self._profil.pause_ms * (1.0 - anteil) + pause_ms * anteil)),
        )
        self._rhythmus_updates += 1
        # Erste Beobachtung sichern, danach gebündelt statt bei jedem Satz.
        if self._rhythmus_updates == 1 or self._rhythmus_updates % 4 == 0:
            self._speichern()
        return True

    # --- Lernen -----------------------------------------------------------------

    def lernen(self, aufnahmen: list[Path]) -> tuple[bool, str]:
        """Lernt die Stimme aus mehreren Aufnahmen.

        Mehrere sind nötig, nicht bloss nett: Aus einer einzigen Aufnahme
        liesse sich nicht abschätzen, wie sehr die eigene Stimme von Mal zu
        Mal schwankt – und genau daraus entsteht die Schwelle.

        Returns:
            Ob es geklappt hat und eine Meldung im Klartext.
        """

        neue: list[Any] = []
        rhythmen: list[tuple[float, int]] = []
        zu_kurz = 0
        for pfad in aufnahmen:
            try:
                vektor = abdruck(pfad)
            except Exception as fehler:  # noqa: BLE001 - siehe pruefen()
                logger.warning("Aufnahme %s nicht auswertbar: %s", pfad, fehler)
                continue
            if vektor is None:
                zu_kurz += 1
                continue
            neue.append(vektor)
            rhythmus = sprechrhythmus(pfad)
            if rhythmus is not None:
                rhythmen.append(rhythmus)

        if len(neue) < 2:
            fehlend = "zu kurz" if zu_kurz else "nicht auswertbar"
            return False, (
                f"Ich konnte mir die Stimme nicht merken – die Aufnahmen waren "
                f"{fehlend}. Sag mir bitte zwei bis drei ganze Sätze, jeweils "
                "ein paar Sekunden lang."
            )

        np = _numpy()
        tempo = float(np.median([wert[0] for wert in rhythmen])) if rhythmen else 1.0
        pause_ms = int(round(float(np.median([wert[1] for wert in rhythmen])))) if rhythmen else 180
        self._profil = Stimmprofil(
            abdruecke=[list(map(float, vektor)) for vektor in neue],
            schwelle=self._schwelle_aus(neue),
            aufnahmen=len(neue),
            sprechtempo=max(0.88, min(1.08, tempo)),
            pause_ms=max(130, min(420, pause_ms)),
        )
        self._speichern()

        logger.info(
            "Stimme gelernt: %d Aufnahmen, Schwelle %.3f.",
            self._profil.aufnahmen,
            self._profil.schwelle,
        )
        return True, (
            f"Ich habe mir deine Stimme aus {len(neue)} Aufnahmen gemerkt. "
            "Ab jetzt höre ich nur noch auf dich und passe meinen "
            "Sprechrhythmus behutsam an deinen an."
        )

    def vergessen(self) -> str:
        """Löscht das Profil – danach hört der Orb wieder auf jeden."""

        self._profil = Stimmprofil()
        try:
            self._pfad.unlink(missing_ok=True)
        except OSError as fehler:
            logger.warning("Das Stimmprofil ließ sich nicht löschen: %s", fehler)
        logger.info("Stimmprofil gelöscht.")
        return "Ich habe deine Stimme vergessen und höre wieder auf jeden."

    def _schwelle_aus(self, vektoren: list[Any]) -> float:
        """Leitet die Schwelle daraus ab, wie ähnlich sich die Lernaufnahmen sind.

        Eine feste Schwelle für alle wäre entweder für die einen zu streng
        oder für die anderen zu lasch. Wessen Stimme von Aufnahme zu
        Aufnahme stark schwankt, braucht eine niedrigere.
        """

        werte = [
            aehnlichkeit(vektoren[i], vektoren[j])
            for i in range(len(vektoren))
            for j in range(i + 1, len(vektoren))
        ]
        if not werte:
            return self._mindest
        return min(self._hoechst, max(self._mindest, min(werte) - self._abstand))

    # --- Prüfen -----------------------------------------------------------------

    def pruefen(self, pfad: Path) -> Urteil:
        """Prüft, ob eine Aufnahme von der gelernten Stimme stammt.

        Im Zweifel fällt die Entscheidung zugunsten des Zuhörens. Wer
        fälschlich ausgesperrt wird, kann dem Orb nicht einmal mehr sagen,
        dass etwas nicht stimmt – ein falsches Nein wiegt hier schwerer als
        ein falsches Ja.
        """

        if not self.aktiv:
            return Urteil(True, grund="Es ist keine Stimme hinterlegt.", geprueft=False)

        try:
            vektor = abdruck(pfad)
        except Exception as fehler:  # noqa: BLE001
            # Hier wird bewusst alles gefangen, nicht eine Auswahl.
            #
            # Eine unlesbare Datei, ein unerwartetes Format, ein Fehler in
            # der Rechnung – was auch immer schiefgeht, es darf nie dazu
            # führen, dass der Benutzer ausgesperrt wird. Eine Ausnahme an
            # dieser Stelle machte den Orb taub, und zwar für den, der ihm
            # als Einziger sagen könnte, dass etwas nicht stimmt.
            logger.debug("Stimmprüfung nicht möglich: %s", fehler)
            return Urteil(True, grund=f"Nicht prüfbar: {fehler}", geprueft=False)

        if vektor is None:
            return Urteil(
                True,
                grund="Zu kurz für eine verlässliche Prüfung.",
                geprueft=False,
            )

        np = _numpy()
        werte = [
            aehnlichkeit(vektor, np.asarray(bekannt, dtype=np.float64))
            for bekannt in self._profil.abdruecke
        ]
        beste = max(werte) if werte else 0.0
        # Die Obergrenze aus der Konfiguration gilt AUCH FUER EIN SCHON
        # GELERNTES Profil, nicht nur beim Lernen.
        #
        # Der Anlass stand im Protokoll: Der Orb wies die eigene Stimme des
        # Benutzers ab ("Fremde Stimme ueberhoert", Aehnlichkeit 0.62-0.79,
        # Schwelle 0.80). Die 0.80 waren beim Lernen in das Profil
        # eingebrannt worden - die Lernaufnahmen klangen sich sehr aehnlich,
        # also wurde die Schwelle bis zur Obergrenze hochgezogen. Im Alltag
        # aber schwankt die Stimme (Abstand zum Mikrofon, Nebengeraeusch),
        # und dann reicht es nicht mehr. Wer die Obergrenze spaeter senkt,
        # damit ihn der Orb wieder hoert, hilft sich sonst nichts: Die alte,
        # zu strenge Schwelle steckt ja im gespeicherten Profil. Mit diesem
        # min() greift die neue Obergrenze sofort - ohne die Stimme neu
        # lernen zu muessen.
        schwelle = min(self._profil.schwelle, self._hoechst)

        if beste >= schwelle:
            return Urteil(True, beste, schwelle, "Bekannte Stimme.", True)

        return Urteil(
            False,
            beste,
            schwelle,
            "Eine andere Stimme – es wird nicht darauf reagiert.",
            True,
        )

    # --- Ablage -----------------------------------------------------------------

    def _laden(self) -> Stimmprofil:
        if not self._pfad.is_file():
            return Stimmprofil()
        try:
            daten = json.loads(self._pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as fehler:
            logger.warning("Das Stimmprofil ließ sich nicht lesen: %s", fehler)
            return Stimmprofil()
        return Stimmprofil.from_dict(daten)

    def _speichern(self) -> None:
        try:
            self._pfad.parent.mkdir(parents=True, exist_ok=True)
            self._pfad.write_text(
                json.dumps(self._profil.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as fehler:
            logger.error("Das Stimmprofil ließ sich nicht speichern: %s", fehler)
