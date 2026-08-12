"""Die Kern-Logik des Diktiermodus – ohne Sprache, ohne Pipeline, prüfbar.

Der Benutzer will mitschreiben, während der Orb diktiert. Zwei Dinge machen
das brauchbar:

1. **Das Tempo wird gemessen, nicht geraten.** Am Anfang schreibt der
   Benutzer einen festen Satz mit und sagt „weiter", sobald er fertig ist.
   Aus der Länge des Satzes und der gebrauchten Zeit ergibt sich, wie viele
   Zeichen er pro Sekunde schafft. Danach richtet sich alles Weitere.

2. **Diktiert wird in Abschnitten, die zum Tempo passen.** Ein Abschnitt ist
   ungefähr so lang, dass man ihn in der angepeilten Zeit (z. B. zwölf
   Sekunden) mitschreiben kann – gemessen am eigenen Tempo. Wer schnell
   schreibt, bekommt längere Stücke und wird seltener unterbrochen; wer
   langsam schreibt, kürzere. „langsamer" und „schneller" verschieben das
   zusätzlich.

Diese Klasse kennt weder Mikrofon noch Lautsprecher. Sie sagt nur, WAS als
Nächstes zu diktieren ist und WIE LANG ein Stück sein soll. Das Sprechen und
Zuhören erledigt die Sprachpipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Der feste Satz, den der Benutzer zum Tempo-Messen mitschreibt. Bewusst
#: mittellang und ohne Fremdwörter – gemessen wird das Schreiben, nicht das
#: Nachdenken.
KALIBRIERSATZ = "Der Orb misst jetzt kurz mein Schreibtempo."


@dataclass
class Diktierer:
    """Führt durch einen Diktattext – abschnittsweise, im Tempo des Benutzers."""

    #: Wie lange (Sekunden) das Mitschreiben eines Abschnitts etwa dauern soll.
    ziel_sekunden: float = 12.0
    #: Untergrenze/Obergrenze der Abschnittslänge in Zeichen. Ein Abschnitt
    #: soll nie zu einem einzelnen Wort schrumpfen und nie zu einem Absatz
    #: wachsen, egal wie das gemessene Tempo ausfällt.
    min_zeichen: int = 40
    max_zeichen: int = 240

    _woerter: list[str] = field(default_factory=list, init=False, repr=False)
    _pos: int = field(default=0, init=False)
    _letzter_start: int = field(default=0, init=False)
    #: Zeichen pro Sekunde. Vorbelegt mit einem gemächlichen Wert, bis
    #: kalibriert wurde (etwa Handschrift-Durchschnitt).
    _zeichen_pro_sek: float = field(default=1.5, init=False)
    #: Feinregelung über „langsamer"/„schneller".
    _tempo: float = field(default=1.0, init=False)
    kalibriert: bool = field(default=False, init=False)

    # --- Aufsetzen -------------------------------------------------------------

    def beginnen(self, volltext: str) -> None:
        """Legt den zu diktierenden Text an (in Wörter zerlegt)."""

        self._woerter = str(volltext).split()
        self._pos = 0
        self._letzter_start = 0

    @property
    def fertig(self) -> bool:
        """Ob der ganze Text diktiert ist."""

        return self._pos >= len(self._woerter)

    @property
    def hat_text(self) -> bool:
        return bool(self._woerter)

    # --- Tempo -----------------------------------------------------------------

    def kalibrieren(self, zeichen: int, sekunden: float) -> float:
        """Errechnet aus einer Mitschreib-Probe die Zeichen pro Sekunde.

        Robust geklammert: Ein verrutschter „weiter"-Ruf (zu früh, zu spät)
        soll das Tempo nicht ins Unbrauchbare ziehen.
        """

        sek = max(0.5, float(sekunden))
        cps = max(0.4, min(8.0, float(zeichen) / sek))
        self._zeichen_pro_sek = cps
        self.kalibriert = True
        return cps

    @property
    def zeichen_pro_sekunde(self) -> float:
        return self._zeichen_pro_sek

    def langsamer(self) -> None:
        """Kürzere Abschnitte – man muss weniger auf einmal fassen."""

        self._tempo = max(0.4, round(self._tempo * 0.75, 3))

    def schneller(self) -> None:
        """Längere Abschnitte – weniger Unterbrechungen."""

        self._tempo = min(2.5, round(self._tempo * 1.33, 3))

    def _abschnitt_zeichen(self) -> int:
        roh = self._zeichen_pro_sek * self.ziel_sekunden * self._tempo
        return int(max(self.min_zeichen, min(self.max_zeichen, roh)))

    # --- Fortschritt -----------------------------------------------------------

    def naechster_abschnitt(self) -> str | None:
        """Das nächste zu diktierende Stück – oder ``None``, wenn fertig.

        Ein Stück reicht bis knapp an die Zielgröße und schließt, wenn
        möglich, an einem Satzende ab, damit man nicht mitten im Satz auf
        das nächste Stück warten muss.
        """

        if self.fertig:
            return None

        ziel = self._abschnitt_zeichen()
        self._letzter_start = self._pos
        stueck: list[str] = []
        laenge = 0
        while self._pos < len(self._woerter):
            wort = self._woerter[self._pos]
            # Passt das Wort nicht mehr und haben wir schon etwas, ist Schluss.
            if stueck and laenge + 1 + len(wort) > ziel:
                break
            stueck.append(wort)
            laenge += len(wort) + 1
            self._pos += 1
            # Sind wir über der Zielgröße und ein Satz endet hier, schließen
            # wir sauber ab.
            if laenge >= ziel and wort.endswith((".", "!", "?", ":", ";")):
                break
        return " ".join(stueck)

    def wiederholen(self) -> str | None:
        """Gibt den zuletzt diktierten Abschnitt noch einmal aus.

        Setzt die Position auf dessen Anfang zurück und schneidet neu – so
        wirkt ein zwischenzeitliches „langsamer" auch auf die Wiederholung.
        """

        if not self._woerter:
            return None
        self._pos = self._letzter_start
        return self.naechster_abschnitt()

    @property
    def fortschritt(self) -> tuple[int, int]:
        """(bereits diktierte Wörter, Wörter gesamt)."""

        return (min(self._pos, len(self._woerter)), len(self._woerter))
