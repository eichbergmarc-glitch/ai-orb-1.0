"""Das Aktuellhalten - die zweite Hälfte der Aktualisierungstendenz.

## Der Auftrag

Der Benutzer, wörtlich: „Der Orb muss sich regelmässig auf dem aktuellen
Wissensstand aller Themenbereiche halten, aktuelle Publikationen kennen
und ebenfalls in sein Gedächtnis aufnehmen. Nur so wird er ein richtiger
Professor." Und in der Lehrhaltung steht die Entsprechung: Zu den bereits
entdeckten Orten wird das Fachwissen vertieft und aktuell gehalten.

## Wie es funktioniert

Ein stiller Kreislauf. In einem festen Takt nimmt sich der Orb EIN Thema
seiner Landkarte vor und fragt zwei Quellen nach Arbeiten, die seit der
letzten Prüfung erschienen sind:

* **OpenAlex** - der offene Katalog über zweihundert Millionen
  wissenschaftlicher Arbeiten, mit Datumsfilter und für den
  programmatischen Zugriff gebaut.
* **Crossref** - die Registrierungsstelle der DOIs; was eine DOI bekommt,
  taucht hier auf, oft am Tag der Veröffentlichung.

Beide sind absichtlich dieselben Quellen wie in ``offene_quellen``: kein
Schlüssel, keine Sperren, keine Trefferseiten-Kratzerei. Die Funde landen
in ``data/studium/aktuell.json`` und - das war der ausdrückliche Wunsch -
im Gedächtnis, damit der Orb sie im Gespräch von sich aus erwähnen kann.

## Drei Entscheidungen, die man kennen sollte

**Ein Thema je Takt, nicht alle.** 45 Themen mal zwei Anfragen im
Minutentakt wäre Stossbetrieb - genau das, wofür Wikimedia den Orb schon
einmal mit 429ern bestraft hat. Ein Thema alle halbe Stunde heisst: Jedes
Thema kommt etwa alle zehn Tage an die Reihe, und die berührten zuerst.

**Die berührten Themen zuerst.** Aktuell gehalten wird, was der Benutzer
tatsächlich bearbeitet - sein Fossilien-Thema verdient den Vorrang vor
einem Thema, das er nie angefasst hat. Das ist dieselbe Regel wie beim
Lernen selbst: dem Interesse folgen.

**Funde sind Hinweise, keine Wahrheiten.** Eine Suchmaschine für
Publikationen liefert auch Halbpassendes. Die Funde werden dem Modell
deshalb als das vorgelegt, was sie sind - automatisch gesammelt,
ungeprüft, mit Quelle - und nie als eigenes Wissen ausgegeben.
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.studium.landkarte import Thema, felder
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: So viele Funde bleiben je Thema liegen - die neuesten zuerst. Mehr
#: liest niemand, und das Gedächtnis soll kein Publikationsarchiv werden.
_FUNDE_JE_THEMA = 6

#: Erst nach dieser Zeit wird ein Thema erneut geprüft. Wissenschaft
#: erscheint nicht im Stundentakt.
_ABSTAND_TAGE = 7.0

#: Wie weit zurück beim ALLERERSTEN Lauf gesucht wird. Ein Jahr genügt:
#: Was älter ist, gehört in die Literaturliste des Themas, nicht in die
#: Neuigkeiten.
_ERSTER_BLICK_TAGE = 365.0

_OPENALEX = "https://api.openalex.org/works"
_CROSSREF = "https://api.crossref.org/works"


def _datum(zeitstempel: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(zeitstempel))


def suchbegriff_fuer(thema: Thema) -> str:
    """Wonach für ein Thema gesucht wird.

    Der Titel allein taugt selten: „Was Sprachwissenschaft ist und was
    sie nicht ist" ist eine Überschrift, kein Suchbegriff. Genommen wird
    der Kern des Titels (vor dem Doppelpunkt, ohne Frageanhängsel) plus
    die ersten Fachbegriffe - die sind dafür da.
    """

    kern = thema.titel.split(":")[0]
    for anhang in (" und was sie nicht ist", " und was er nicht ist"):
        kern = kern.replace(anhang, "")
    teile = [kern.strip()]
    teile.extend(thema.begriffe[:2])
    # Doppelte Woerter kosten nur Platz im Suchfeld.
    gesehen: set[str] = set()
    woerter: list[str] = []
    for teil in teile:
        for wort in teil.split():
            if wort.lower() not in gesehen:
                gesehen.add(wort.lower())
                woerter.append(wort)
    return " ".join(woerter)[:120]


# ---------------------------------------------------------------------------
#  Die zwei Quellen - mit Datumsfilter, den die Suche in offene_quellen
#  nicht hat: Dort geht es um PASSENDE Arbeiten, hier um NEUE.
# ---------------------------------------------------------------------------


def openalex_neues(
    query: str, *, seit: str, limit: int = 5
) -> list[dict[str, str]]:
    """Arbeiten aus OpenAlex, erschienen seit einem Datum."""

    from backend.research.offene_quellen import _json_holen, _treffer

    frage = urllib.parse.urlencode({
        "search": query,
        "filter": f"from_publication_date:{seit}",
        "sort": "publication_date:desc",
        "per-page": str(max(1, min(limit, 25))),
    })
    daten = _json_holen(f"{_OPENALEX}?{frage}")

    funde: list[dict[str, str]] = []
    for arbeit in daten.get("results") or []:
        ort = arbeit.get("primary_location") or {}
        adresse = (
            str(ort.get("landing_page_url") or "")
            or str(arbeit.get("doi") or "")
            or str(arbeit.get("id") or "")
        )
        zeitschrift = str((ort.get("source") or {}).get("display_name") or "")
        datum = str(arbeit.get("publication_date") or "")
        gefunden = _treffer(
            arbeit.get("display_name") or arbeit.get("title") or "",
            adresse,
            " · ".join(t for t in (zeitschrift, datum) if t),
        )
        if gefunden:
            gefunden["datum"] = datum
            funde.append(gefunden)
        if len(funde) >= limit:
            break
    return funde


def crossref_neues(
    query: str, *, seit: str, limit: int = 5
) -> list[dict[str, str]]:
    """Arbeiten aus Crossref, erschienen seit einem Datum."""

    from backend.research.offene_quellen import _json_holen, _treffer

    frage = urllib.parse.urlencode({
        "query": query,
        "filter": f"from-pub-date:{seit}",
        "sort": "published",
        "order": "desc",
        "rows": str(max(1, min(limit, 20))),
        "select": "title,URL,container-title,issued",
    })
    daten = _json_holen(f"{_CROSSREF}?{frage}")

    funde: list[dict[str, str]] = []
    for eintrag in ((daten.get("message") or {}).get("items") or []):
        titel = eintrag.get("title") or []
        behaelter = eintrag.get("container-title") or []
        teile = ((eintrag.get("issued") or {}).get("date-parts") or [[]])[0]
        datum = "-".join(f"{t:02d}" if i else str(t) for i, t in enumerate(teile))
        gefunden = _treffer(
            titel[0] if titel else "",
            eintrag.get("URL", ""),
            " · ".join(
                t for t in (behaelter[0] if behaelter else "", datum) if t
            ),
        )
        if gefunden:
            gefunden["datum"] = datum
            funde.append(gefunden)
        if len(funde) >= limit:
            break
    return funde


# ---------------------------------------------------------------------------
#  Der Kreislauf
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Auffrischung:
    """Das Ergebnis eines Laufs über ein Thema."""

    feld: str
    thema: str
    neue: list[dict[str, str]] = field(default_factory=list)
    fehler: str = ""


class Aktualisierung:
    """Hält die Themen der Landkarte auf dem Stand der Forschung.

    Der Zustand liegt in ``data/studium/aktuell.json`` und wird bei jeder
    Änderung geschrieben - dieselbe Regel wie überall im Studium: Der Orb
    wird geschlossen, nicht heruntergefahren.
    """

    def __init__(
        self,
        dateiname: str = "studium/aktuell.json",
        *,
        abstand_tage: float = _ABSTAND_TAGE,
        quellen: tuple[Callable[..., list[dict[str, str]]], ...] | None = None,
        merken: Callable[[str, str], None] | None = None,
    ) -> None:
        """
        Args:
            quellen: Die Suchfunktionen - austauschbar, damit sich der
                Kreislauf ohne Netz prüfen lässt. Ohne Angabe: OpenAlex
                und Crossref.
            merken: Bekommt (text, quelle) für jeden wirklich neuen Fund
                und legt ihn ins Gedächtnis. Genau das hat der Benutzer
                verlangt: aktuelle Publikationen „ebenfalls in sein
                Gedächtnis aufnehmen".
        """

        self._store = JsonStore(dateiname, default={"themen": {}})
        self._abstand = max(0.25, abstand_tage) * 86400.0
        self._quellen = quellen if quellen is not None else (
            openalex_neues, crossref_neues,
        )
        self._merken = merken
        self._daten: dict[str, dict[str, Any]] = {
            str(k): dict(v)
            for k, v in (self._store.get("themen", {}) or {}).items()
            if isinstance(v, dict)
        }

    def _speichern(self) -> None:
        self._store.set("themen", self._daten)

    @staticmethod
    def _schluessel(feld: str, thema: str) -> str:
        return f"{feld}/{thema}"

    # --- Auswahl -------------------------------------------------------------

    def naechstes(self, beruehrte: dict[str, set[str]] | None = None
                  ) -> tuple[str, str] | None:
        """Welches Thema als Nächstes an die Reihe kommt.

        Die berührten Themen zuerst - aktuell gehalten wird vor allem,
        woran der Benutzer arbeitet. Innerhalb dessen: das am längsten
        ungeprüfte. Ist nichts fällig, kommt ``None`` - dann ist Ruhe die
        richtige Tätigkeit.
        """

        beruehrte = beruehrte or {}
        jetzt = time.time()
        kandidaten: list[tuple[int, float, str, str]] = []
        for f in felder():
            angefasst = beruehrte.get(f.kennung, set())
            for t in f.alle_themen():
                stand = self._daten.get(self._schluessel(f.kennung, t.kennung), {})
                # Der VERSUCH bestimmt die Reihenfolge, nicht der Erfolg.
                # Sonst bliebe ein Thema, dessen Quellen gerade schweigen,
                # dauerhaft ganz vorn und verdraengte alle anderen.
                versucht = float(
                    stand.get("zuletzt_versucht_am", stand.get("geprueft_am", 0.0))
                )
                if jetzt - versucht < self._abstand:
                    continue
                rang = 0 if t.kennung in angefasst else 1
                kandidaten.append((rang, versucht, f.kennung, t.kennung))
        if not kandidaten:
            return None
        kandidaten.sort()
        _, _, feld_k, thema_k = kandidaten[0]
        return feld_k, thema_k

    # --- Auffrischen -----------------------------------------------------------

    def auffrischen(self, feld_kennung: str, thema_kennung: str) -> Auffrischung:
        """Fragt die Quellen nach Neuem zu einem Thema.

        Läuft blockierend (urllib) - der Aufrufer legt es in einen
        Thread. Scheitert eine Quelle, zählt die andere trotzdem.

        Scheitern BEIDE, werden zwei verschiedene Zeitstempel gesetzt, und
        auf dem Unterschied beruht die ganze Korrektur:

        ``zuletzt_versucht_am`` rückt immer vor. Daran hängt die Frage,
        welches Thema als Nächstes an die Reihe kommt - der Kreislauf geht
        also weiter und hämmert bei einer Netzstörung nicht im Takt auf
        dasselbe Thema ein.

        ``geprueft_am`` bleibt bei einem Fehlschlag stehen. Daran hängt das
        "seit"-Datum der nächsten Suche. Vorher rückte es mit vor, und
        alles, was während einer Offline-Phase erschienen ist, wurde nie
        wieder gesucht: ein dauerhaftes Loch in der Literaturliste, das
        niemandem auffällt, weil dort ja Einträge stehen.
        """

        from backend.studium.landkarte import feld as feld_holen

        ergebnis = Auffrischung(feld=feld_kennung, thema=thema_kennung)
        das_feld = feld_holen(feld_kennung)
        das_thema = das_feld.thema(thema_kennung) if das_feld else None
        if das_thema is None:
            ergebnis.fehler = "unbekanntes Thema"
            return ergebnis

        schluessel = self._schluessel(feld_kennung, thema_kennung)
        stand = self._daten.setdefault(
            schluessel, {"funde": [], "geprueft_am": 0.0}
        )
        seit = _datum(
            stand["geprueft_am"] if stand["geprueft_am"]
            else time.time() - _ERSTER_BLICK_TAGE * 86400.0
        )
        begriff = suchbegriff_fuer(das_thema)

        bekannt = {str(f.get("url", "")) for f in stand.get("funde", [])}
        fehler: list[str] = []
        for quelle in self._quellen:
            try:
                for fund in quelle(begriff, seit=seit, limit=4):
                    url = str(fund.get("url", ""))
                    if not url or url in bekannt:
                        continue
                    bekannt.add(url)
                    fund["gefunden_am"] = _datum(time.time())
                    ergebnis.neue.append(fund)
            except Exception as ausnahme:  # noqa: BLE001,PERF203
                fehler.append(str(ausnahme))
                logger.info(
                    "Quelle %s zu %r nicht erreichbar: %s",
                    getattr(quelle, "__name__", "?"), begriff, ausnahme,
                )

        if fehler and not ergebnis.neue and len(fehler) == len(self._quellen):
            ergebnis.fehler = "; ".join(fehler)[:200]

        stand["funde"] = (ergebnis.neue + list(stand.get("funde", [])))[
            :_FUNDE_JE_THEMA
        ]
        stand["zuletzt_versucht_am"] = time.time()
        if ergebnis.fehler:
            logger.info(
                "Thema %s konnte nicht aufgefrischt werden; der Prüfstand "
                "bleibt beim %s, damit nichts übersprungen wird.",
                thema_kennung,
                seit,
            )
        else:
            stand["geprueft_am"] = time.time()
        stand["suchbegriff"] = begriff
        self._speichern()

        # Ins Gedaechtnis - aber sparsam: hoechstens zwei je Lauf, sonst
        # muellt der Kreislauf zu, was er pflegen soll.
        if self._merken is not None:
            for fund in ergebnis.neue[:2]:
                try:
                    # Mit Abstract und Schlagworten, wenn die Quelle sie
                    # hergibt. Vorher stand hier Titel plus "Zeitschrift ·
                    # Jahr" - fachlich nicht durchsuchbar, und die Suche
                    # traf nur, wer den Titel schon kannte.
                    teile = [
                        f"Neue Publikation zu {das_thema.titel}: "
                        f"{fund.get('titel', '')} ({fund.get('beschreibung', '')})"
                    ]
                    if fund.get("schlagworte"):
                        teile.append(f"Schlagworte: {fund['schlagworte']}")
                    if fund.get("abstract"):
                        teile.append(str(fund["abstract"]))
                    self._merken(
                        "\n".join(teil for teil in teile if teil),
                        str(fund.get("url", "")),
                    )
                except Exception:  # noqa: BLE001,PERF203
                    logger.exception("Fund liess sich nicht merken.")

        logger.info(
            "Thema %s aufgefrischt: %d neue Funde (seit %s, Suchbegriff %r).",
            thema_kennung, len(ergebnis.neue), seit, begriff,
        )
        return ergebnis

    # --- Auskunft ---------------------------------------------------------------

    def neues_zu(self, feld_kennung: str, thema_kennung: str) -> list[dict[str, str]]:
        stand = self._daten.get(self._schluessel(feld_kennung, thema_kennung), {})
        return list(stand.get("funde", []))

    def hinweis(self, feld_kennung: str, thema_kennung: str) -> str:
        """Der Textblock für das Sprachmodell - oder leer.

        Mit der Einordnung, die der Sache angemessen ist: automatisch
        gesammelt und ungeprüft. Ein Fund ist ein Hinweis auf Forschung,
        kein Wissen - und so soll der Orb ihn auch aussprechen.
        """

        funde = self.neues_zu(feld_kennung, thema_kennung)
        if not funde:
            return ""
        zeilen = [
            "NEUES AUS DER FORSCHUNG (automatisch aus OpenAlex und Crossref "
            "gesammelt, UNGEPRÜFT - als Hinweis nennen, nicht als eigenes "
            "Wissen ausgeben, und die Quelle dazu sagen):"
        ]
        for fund in funde[:4]:
            zeile = f"- {fund.get('titel', '')}"
            if fund.get("beschreibung"):
                zeile += f" ({fund['beschreibung']})"
            if fund.get("url"):
                zeile += f" – {fund['url']}"
            zeilen.append(zeile)
        return "\n".join(zeilen)

    def status(self) -> dict[str, Any]:
        gesamt = sum(len(v.get("funde", [])) for v in self._daten.values())
        geprueft = sum(1 for v in self._daten.values() if v.get("geprueft_am"))
        return {
            "themen_geprueft": geprueft,
            "funde_gesamt": gesamt,
            "abstand_tage": round(self._abstand / 86400.0, 1),
        }
