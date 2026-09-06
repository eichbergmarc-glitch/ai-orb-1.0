"""Wo der Lernende steht - gelesen aus Gesprächen, nicht aus Prüfungen.

## Zwei Korrekturen stecken in dieser Datei

**Die erste** betrifft den Vorgänger. Es gab schon ein Lernprofil,
446 Zeilen unter ``backend/agents/history_agent``. Es hat nie
funktioniert, weil es nicht gefüttert wurde: ``record_competence()``
rief nur eine Prüfungsmaschine auf, die von nirgends erreichbar war,
``record_error()`` rief niemand. Die Datei ``lernprofil.json`` existierte
am 19.08.2026 nicht einmal.

**Die zweite** betrifft meinen eigenen ersten Versuch. Ich hatte den
Stand aus bewerteten Prüfungsantworten gebildet. Der Benutzer hat das
zurückgewiesen::

    "Der Orb soll auch nicht einfach plump irgendwelche Tests mit mir
     machen um sich meinen Wissensstand zu merken, er soll dies durch das
     Gespräch mit mir feststellen."

Gefüttert wird der Stand deshalb jetzt aus :mod:`backend.studium.mitlesen` -
aus dem, was im Gespräch ohnehin gesagt wird.

## Was für ein Ding ein Stand ist

Eine **Vermutung**, keine Note. Sie hat drei Eigenschaften, und alle drei
folgen daraus, dass sie aus Gesprächen kommt und nicht aus Messungen:

* **Sie altert.** Was vor einem halben Jahr sicher sass, sitzt heute
  vielleicht nicht mehr. Jede Beobachtung verblasst.
* **Sie verträgt Widerspruch.** Wer sich fortgeschritten zeigt und
  danach eine Grundfrage stellt, verliert nichts - es kommt eine
  Beobachtung hinzu. Der Stand ist ein Schwerpunkt, kein Höchststand.
* **Sie merkt sich Interessen.** Wohin es weitergeht, entscheidet nicht
  eine Ordnung, sondern was den Lernenden umtreibt. Genau darum ging es
  dem Benutzer.
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from typing import Any

from backend.studium.landkarte import TIEFEN
from backend.studium.mitlesen import Beobachtung
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Nach dieser Zeit gilt eine Beobachtung als halb so aussagekräftig.
#: Ein halbes Jahr ohne Berührung - dann ist eine Vermutung von damals
#: eben nur noch eine halbe.
_HALBWERT_TAGE = 180.0

#: So viel Gewicht muss zusammenkommen, bevor eine Tiefe als erreicht
#: gilt. Eine einzelne Bemerkung reicht nicht - Menschen sagen vieles.
_GENUG = 1.5


@dataclass(slots=True)
class Themenstand:
    """Was über EIN Thema zusammengekommen ist."""

    thema: str
    #: Je Tiefe: gesammeltes Gewicht der Beobachtungen.
    gewichte: dict[str, float] = field(default_factory=dict)
    zuletzt: float = field(default_factory=time.time)
    #: Wie oft darüber gesprochen wurde.
    beruehrungen: int = 0
    #: Begriffe, die der Benutzer selbst benutzt hat.
    eigene_begriffe: list[str] = field(default_factory=list)
    #: Was er ausdrücklich gesagt hat - zuletzt zuerst.
    auskuenfte: list[str] = field(default_factory=list)
    #: Interesse: steigt und fällt mit dem, was er äussert.
    interesse: float = 0.0

    def wert(self, tiefe: str, *, jetzt: float | None = None) -> float:
        roh = self.gewichte.get(tiefe, 0.0)
        if not roh:
            return 0.0
        vergangen = max(0.0, (jetzt or time.time()) - self.zuletzt) / 86400.0
        return roh * (0.5 ** (vergangen / _HALBWERT_TAGE))

    def erreicht(self, tiefe: str) -> bool:
        return self.wert(tiefe) >= _GENUG

    def schwerpunkt(self) -> str:
        """Die Tiefe, auf der bisher am meisten gesprochen wurde."""

        beste, hoechster = TIEFEN[0], 0.0
        for tiefe in TIEFEN:
            wert = self.wert(tiefe)
            if wert > hoechster:
                beste, hoechster = tiefe, wert
        return beste

    def to_dict(self) -> dict[str, Any]:
        return {
            "thema": self.thema,
            "gewichte": dict(self.gewichte),
            "zuletzt": self.zuletzt,
            "beruehrungen": self.beruehrungen,
            "eigene_begriffe": list(self.eigene_begriffe[-30:]),
            "auskuenfte": list(self.auskuenfte[-8:]),
            "interesse": round(self.interesse, 2),
        }

    @classmethod
    def from_dict(cls, roh: dict[str, Any]) -> Themenstand:
        return cls(
            thema=str(roh.get("thema", "")),
            gewichte={str(k): float(v) for k, v in (roh.get("gewichte") or {}).items()},
            zuletzt=float(roh.get("zuletzt", time.time())),
            beruehrungen=int(roh.get("beruehrungen", 0)),
            eigene_begriffe=[str(b) for b in (roh.get("eigene_begriffe") or [])],
            auskuenfte=[str(a) for a in (roh.get("auskuenfte") or [])],
            interesse=float(roh.get("interesse", 0.0)),
        )


class Lernstand:
    """Was der Orb über den Lernenden vermutet.

    Liegt in ``data/studium/lernstand.json`` und wird bei jeder Änderung
    geschrieben - nicht erst beim Beenden. Der Orb wird nicht sauber
    beendet, sondern geschlossen; genau daran ist der Vorgänger gestorben.
    """

    def __init__(self, dateiname: str = "studium/lernstand.json") -> None:
        self._store = JsonStore(dateiname, default={"felder": {}})
        self._felder: dict[str, dict[str, Themenstand]] = {}
        #: Woran gerade gearbeitet wird und seit wie vielen Wortwechseln.
        #:
        #: Nicht gespeichert, sondern nur fuer diese Sitzung: Nach einem
        #: Neustart faengt die Beharrlichkeit von vorn an, und das ist
        #: richtig - wer den Orb neu startet, hat eine Pause gemacht.
        self._laufend: tuple[str, str] | None = None
        self._laufend_seit = 0
        profil = self._store.get("lernprofil", {}) or {}
        self._lernwege: dict[str, float] = {
            str(k): float(v) for k, v in (profil.get("lernwege", {}) or {}).items()
        }
        self._lernweg_belege: int = int(profil.get("belege", 0) or 0)
        self._letzte_lehrwege: list[str] = []
        for feld, themen in (self._store.get("felder", {}) or {}).items():
            self._felder[str(feld)] = {
                str(k): Themenstand.from_dict(v)
                for k, v in (themen or {}).items()
                if isinstance(v, dict)
            }

    def _speichern(self) -> None:
        self._store.set(
            "felder",
            {
                feld: {k: t.to_dict() for k, t in themen.items()}
                for feld, themen in self._felder.items()
            },
        )
        self._store.set(
            "lernprofil",
            {"lernwege": self._lernwege, "belege": self._lernweg_belege},
        )

    # --- Wie Lernen beim Benutzer funktioniert -----------------------------

    @staticmethod
    def _lehrwege_in(text: str) -> list[str]:
        klein = str(text or "").lower()
        marker = {
            "konkrete_beispiele": ("beispiel", "zum beispiel", "konkret"),
            "analogien": ("vergleich", "stell dir vor", "wie bei", "analogie"),
            "ursache_wirkung": ("weil", "deshalb", "führt dazu", "ursache"),
            "bilder_und_schaubilder": ("bild", "grafik", "diagramm", "schaubild"),
            "geschichten_und_faelle": ("geschichte", "fallbeispiel", "erzählen wir"),
            "dialog_und_rueckfragen": ("was meinst du", "warum glaubst du", "frage"),
            "schritte_und_struktur": ("schritt", "erstens", "zweitens", "ablauf"),
            "anwenden_und_ueben": ("übung", "uebung", "probier", "anwenden", "selbst lösen"),
            "wiederholen_und_verknuepfen": ("noch einmal", "wiederhol", "erinnerst du", "knüpft an"),
        }
        return [weg for weg, worte in marker.items() if any(w in klein for w in worte)]

    def lehrweg_notieren(self, antwort: str) -> None:
        """Merkt, welche Vermittlungswege die letzte Erklärung benutzte."""

        self._letzte_lehrwege = self._lehrwege_in(antwort)

    def lernweg_beobachten(self, aeusserung: str) -> None:
        """Bewertet die letzte Erklärungsform nur anhand echter Rückmeldung."""

        klein = " ".join(str(aeusserung or "").lower().split())
        positiv = bool(re.search(
            r"\b(jetzt verstanden|jetzt klar|jetzt ist es klar|das hilft|gut gemerkt|kann ich mir merken|"
            r"so verstehe ich|genau so|leuchtet ein)\b", klein,
        ))
        negativ = bool(re.search(
            r"\b(nicht verstanden|verstehe ich nicht|zu abstrakt|zu kompliziert|"
            r"kann ich mir nicht merken|noch unklar|anders erklären|anders erklaeren)\b",
            klein,
        ))
        if not (positiv or negativ) or not self._letzte_lehrwege:
            return
        delta = 1.0 if positiv else -0.7
        for weg in self._letzte_lehrwege:
            self._lernwege[weg] = round(
                max(-5.0, min(10.0, self._lernwege.get(weg, 0.0) + delta)), 2
            )
        self._lernweg_belege += 1
        self._speichern()

    def lernprofil_hinweis(self) -> str:
        """Konkrete Lehrregie aus wiederholt beobachteter Wirksamkeit."""

        if self._lernweg_belege < 2 or not self._lernwege:
            return (
                "LERNWEG: Es gibt noch zu wenig Belege. Variiere zwischen konkreten "
                "Beispielen, Ursache-Wirkung, Analogien, Anwendung, Bildern und "
                "Rückfragen; beobachte echte Verstehens- und Erinnerungsreaktionen."
            )
        gereiht = sorted(self._lernwege.items(), key=lambda p: p[1], reverse=True)
        gut = [name for name, wert in gereiht if wert > 0][:3]
        schlecht = [name for name, wert in reversed(gereiht) if wert < 0][:2]
        return (
            "LERNWEG AUS BEOBACHTUNG: Bevorzuge " + (", ".join(gut) or "Variation")
            + ("; vermeide als alleinigen Weg " + ", ".join(schlecht) if schlecht else "")
            + f". Grundlage: {self._lernweg_belege} echte Rückmeldungen, kein Lerntyp-Etikett."
        )

    # --- Eintragen ----------------------------------------------------------

    def beobachten(self, feld: str, beobachtung: Beobachtung) -> Themenstand | None:
        """Nimmt auf, was im Gespräch sichtbar wurde.

        Der einzige Weg, auf dem hier etwas hineinkommt. Keine Noten,
        keine Prüfungen - was gesagt wurde, mehr nicht.
        """

        if not beobachtung.sagt_etwas or not beobachtung.thema:
            return None
        stand = self._stand(feld, beobachtung.thema)
        stand.beruehrungen += 1
        stand.zuletzt = time.time()

        # Mitzaehlen, wie lange schon an derselben Sache gearbeitet wird.
        jetzt = (feld, beobachtung.thema)
        if self._laufend == jetzt:
            self._laufend_seit += 1
        else:
            self._laufend, self._laufend_seit = jetzt, 1

        if beobachtung.tiefe in TIEFEN and beobachtung.gewicht > 0:
            stand.gewichte[beobachtung.tiefe] = (
                stand.gewichte.get(beobachtung.tiefe, 0.0) + beobachtung.gewicht
            )
        for begriff in beobachtung.eigene_begriffe:
            if begriff not in stand.eigene_begriffe:
                stand.eigene_begriffe.append(begriff)
        if beobachtung.selbstauskunft:
            stand.auskuenfte.append(beobachtung.selbstauskunft)
            stand.auskuenfte = stand.auskuenfte[-8:]
        # Interesse steigt schnell und faellt langsam: Wer einmal abwinkt,
        # meint vielleicht nur diesen Tag.
        if beobachtung.interesse > 0:
            stand.interesse = min(5.0, stand.interesse + 1.0)
        elif beobachtung.interesse < 0:
            stand.interesse = max(-3.0, stand.interesse - 0.5)

        self._speichern()
        logger.info(
            "Aus dem Gespräch gelernt – %s/%s: %s (%s).",
            feld, beobachtung.thema, beobachtung.tiefe or "ohne Tiefe",
            "; ".join(beobachtung.gruende[:2]) or "–",
        )
        return stand

    def erklaert(self, feld: str, thema: str) -> Themenstand:
        """Hält fest, dass der Orb darüber gesprochen hat.

        Zugehört zu haben ist kein Können - das zählt deshalb nicht auf
        die Tiefe. Festgehalten wird es trotzdem, damit der Orb nicht
        zweimal dasselbe erzählt, ohne es zu merken.
        """

        stand = self._stand(feld, thema)
        stand.beruehrungen += 1
        stand.zuletzt = time.time()
        self._speichern()
        return stand

    def _stand(self, feld: str, thema: str) -> Themenstand:
        themen = self._felder.setdefault(feld, {})
        if thema not in themen:
            themen[thema] = Themenstand(thema=thema)
        return themen[thema]

    # --- Auskunft -----------------------------------------------------------

    def stand(self, feld: str, thema: str) -> Themenstand | None:
        return self._felder.get(feld, {}).get(thema)

    def beruehrt(self, feld: str) -> set[str]:
        """Alle Themen, über die schon gesprochen wurde."""

        return set(self._felder.get(feld, {}))

    def tiefe_fuer(self, feld: str, thema: str) -> str:
        """Wie tief bei diesem Thema anzusetzen ist.

        Der bisherige Schwerpunkt, nicht die nächsthöhere Stufe. Der
        Unterschied ist wichtig: Es gibt hier keine Leiter, die man
        hochsteigt, sondern eine Vermutung darüber, auf welcher Höhe das
        Gespräch bisher lief.
        """

        vorhanden = self.stand(feld, thema)
        if vorhanden is None or not vorhanden.gewichte:
            return TIEFEN[0]
        return vorhanden.schwerpunkt()

    def interessen(self, feld: str, limit: int = 5) -> list[str]:
        """Themen, für die der Lernende Interesse gezeigt hat."""

        themen = self._felder.get(feld, {})
        gereiht = sorted(
            (t for t in themen.values() if t.interesse > 0),
            key=lambda t: (-t.interesse, -t.zuletzt),
        )
        return [t.thema for t in gereiht[:limit]]

    def offene_stellen(self, feld: str, limit: int = 5) -> list[str]:
        """Wo der Lernende gesagt hat, dass er nicht mitkommt.

        Das ist wertvoller als jedes Prüfungsergebnis: Er hat es selbst
        gesagt, und zwar unaufgefordert.
        """

        themen = self._felder.get(feld, {})
        offen = [
            t for t in themen.values()
            if t.auskuenfte and t.auskuenfte[-1] == "kennt es nicht"
        ]
        offen.sort(key=lambda t: -t.zuletzt)
        return [t.thema for t in offen[:limit]]

    def woran_weiter(self, feld_kennung: str) -> dict[str, Any]:
        """Ein Vorschlag - kein Lehrplan.

        Die Reihenfolge der Gründe ist die eigentliche Aussage dieser
        Methode, und sie folgt aus dem, was der Benutzer verlangt hat:
        Zuerst zählt, was ihn interessiert. Dann, wo er selbst gesagt hat,
        dass es hakt. Erst danach schaut der Orb auf die Landkarte - und
        auch dort schlägt er einen Einstieg vor, statt einen Weg
        vorzuschreiben.
        """

        from backend.studium.landkarte import feld as feld_holen

        das_feld = feld_holen(feld_kennung)
        if das_feld is None:
            return {"feld": feld_kennung, "grund": "unbekanntes Gebiet"}

        beruehrt = self.beruehrt(feld_kennung)

        for thema in self.interessen(feld_kennung):
            weiter = das_feld.nachbarschaft(thema).get("fuehrt_zu", ())
            for naechstes in weiter:
                if naechstes not in beruehrt:
                    return {
                        "feld": feld_kennung,
                        "thema": naechstes,
                        "grund": f"schliesst an {thema} an, wofür er Interesse zeigte",
                        "tiefe": self.tiefe_fuer(feld_kennung, thema),
                    }

        for thema in self.offene_stellen(feld_kennung):
            return {
                "feld": feld_kennung,
                "thema": thema,
                "grund": "er hat selbst gesagt, dass es hier hakt",
                "tiefe": "kennen",
            }

        # Was lange liegt, wird schal. Bevor eine ganz neue Gegend
        # aufgemacht wird, lohnt ein Blick auf das, was verblasst.
        for thema in self.veraltet(feld_kennung, limit=1):
            titel = das_feld.thema(thema)
            return {
                "feld": feld_kennung,
                "thema": thema,
                "titel": titel.titel if titel else thema,
                "grund": "lange nicht berührt – auffrischen und auf den Stand bringen",
                "tiefe": self.tiefe_fuer(feld_kennung, thema),
            }

        for einstieg in das_feld.einstiege:
            if einstieg not in beruehrt:
                thema = das_feld.thema(einstieg)
                return {
                    "feld": feld_kennung,
                    "thema": einstieg,
                    "titel": thema.titel if thema else einstieg,
                    "grund": "ein Einstieg, der nichts voraussetzt",
                    "tiefe": "kennen",
                }

        for thema in das_feld.alle_themen():
            if thema.kennung in beruehrt:
                continue
            fehlt = das_feld.was_fehlt(thema.kennung, beruehrt)
            if not fehlt:
                return {
                    "feld": feld_kennung,
                    "thema": thema.kennung,
                    "titel": thema.titel,
                    "grund": "dafür ist alles Nötige schon besprochen",
                    "tiefe": "kennen",
                }

        return {
            "feld": feld_kennung,
            "grund": "überall schon gewesen – jetzt lohnt das Vertiefen",
            "tiefe": "beurteilen",
        }

    def wechselurteil(self, *, winkt_ab: bool = False, will_wechseln: bool = False):
        """Ob jetzt ein Themenwechsel angebracht ist.

        Der Benutzer hat es ausdruecklich verlangt: dem Interesse folgen,
        aber nicht alle paar Minuten das Gebiet wechseln. Die Regel selbst
        steht in :func:`backend.studium.antrieb.beharrlich`; hier kommt
        nur die Zahl dazu, die sie braucht.
        """

        from backend.studium.antrieb import beharrlich

        return beharrlich(
            wechsel_beim_thema=self._laufend_seit,
            will_wechseln=will_wechseln,
            winkt_ab=winkt_ab,
        )

    @property
    def laufendes_thema(self) -> str:
        return self._laufend[1] if self._laufend else ""

    def veraltet(self, feld: str, tage: float = 120.0, limit: int = 5) -> list[str]:
        """Themen, die lange nicht mehr berührt wurden.

        Die andere Haelfte der Aktualisierungstendenz: Es werden nicht nur
        neue Gegenden erschlossen, die bekannten werden auch vertieft und
        auf dem Stand gehalten. Forschung geht weiter - was vor drei
        Jahren galt, gilt vielleicht nicht mehr.
        """

        grenze = time.time() - tage * 86400.0
        alt = [t for t in self._felder.get(feld, {}).values() if t.zuletzt < grenze]
        alt.sort(key=lambda t: t.zuletzt)
        return [t.thema for t in alt[:limit]]

    def uebersicht(self) -> dict[str, Any]:
        """Was der Orb sagen kann, wenn man ihn fragt: Wo stehe ich?"""

        fachstand = {
            feld: {
                "themen": len(themen),
                "gespraeche": sum(t.beruehrungen for t in themen.values()),
                "schwerpunkt": _haeufigste(
                    [t.schwerpunkt() for t in themen.values() if t.gewichte]
                ),
                "interessen": self.interessen(feld),
                "haken": self.offene_stellen(feld),
                "eigene_begriffe": sorted(
                    {b for t in themen.values() for b in t.eigene_begriffe}
                )[:20],
            }
            for feld, themen in self._felder.items()
        }
        return {
            **fachstand,
            "lernprofil": {
                "belege": self._lernweg_belege,
                "lernwege": dict(sorted(
                    self._lernwege.items(), key=lambda p: p[1], reverse=True
                )),
            },
        }


def _haeufigste(werte: list[str]) -> str:
    if not werte:
        return "noch nichts"
    zaehler: dict[str, int] = {}
    for w in werte:
        zaehler[w] = zaehler.get(w, 0) + 1
    return max(zaehler.items(), key=lambda p: p[1])[0]
