"""Suchen, die nicht abgewiesen werden können.

## Warum es dieses Modul gibt

Der Orb hat bisher fünf Suchmaschinen im HTML-Gewand abgefragt - Bing,
Mojeek, DuckDuckGo, Ecosia. Am 15.08.2026 stand im Protokoll des Benutzers
fünfmal dasselbe::

    Mojeek antwortete mit 403.
    Ecosia antwortete mit 403.
    DuckDuckGo Lite hat die Anfrage abgewiesen.
    DuckDuckGo HTML hat die Anfrage abgewiesen.
    Bing lieferte 1356 Zeichen, darin war aber kein Treffer zu erkennen.

Das ist kein Fehler im Code. Es ist die Antwort dieser Dienste auf einen
Zugriff, den sie für automatisiert halten - und sie haben recht damit. An
diesem Punkt hilft kein besserer Kopfzeilensatz mehr. Jede Verkleidung wird
irgendwann durchschaut, und dann steht der Benutzer wieder vor demselben
Protokoll. Ein Wettrüsten, das man nicht gewinnen kann, führt man besser
nicht.

## Der Ausweg: Dienste fragen, die gefragt werden wollen

Es gibt eine ganze Klasse von Diensten, die genau dafür da sind, von
Programmen abgefragt zu werden. Sie erkennen einen Automaten nicht als
Bedrohung, sondern als vorgesehenen Nutzer. Sie verlangen keine Tarnung,
sondern das Gegenteil: eine ehrliche Kennung, damit man sie ansprechen kann,
wenn etwas schiefgeht.

* **GDELT** durchsucht die Nachrichten der ganzen Welt, minutenaktuell, mit
  Sprach- und Länderfilter. Kein Konto, kein Schlüssel.
* **Wikipedia** beantwortet Sachfragen aus der eigenen Volltextsuche.
* **OpenAlex** und **Crossref** kennen zusammen über zweihundert Millionen
  wissenschaftliche Arbeiten - für einen Benutzer, der Geschichte studiert,
  ist das die eigentlich richtige Suche.
* **RSS** liefert die Schlagzeilen einer Zeitung direkt von der Zeitung.
  Um zu erfahren, was heute in der Tagesschau steht, muss man keine
  Suchmaschine nach ``site:tagesschau.de`` fragen.

Dazu kommt, wenn ein Schlüssel hinterlegt ist, die **Google-Suche über die
offizielle Programmable-Search-Schnittstelle** - hundert Anfragen am Tag
kostenfrei, und die wird nie abgewiesen, weil sie der vorgesehene Weg ist.

## Was das für die Trefferqualität heisst

Ehrlich gesagt: Für die Frage „welcher Laden hat sonntags offen" ist das
schlechter als Google. Für alles, wofür dieser Orb gebaut ist - Nachrichten,
Sachfragen, Forschungsliteratur, Belege - ist es besser, weil die Antworten
aus benannten Quellen mit Datum kommen statt aus einer Trefferliste. Und es
funktioniert morgen noch.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Eine ehrliche Kennung. Diese Dienste wollen wissen, wer sie ruft - und
#: bestrafen es nicht, sondern verlangen es. Wikimedia weist Zugriffe ohne
#: sprechende Kennung sogar ausdruecklich ab.
KENNUNG = "AI-Orb/0.26 (persoenlicher Sprachassistent; Kontakt ueber den Betreiber)"

_GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
_WIKIPEDIA = "https://{sprache}.wikipedia.org/w/api.php"
_OPENALEX = "https://api.openalex.org/works"
_CROSSREF = "https://api.crossref.org/works"
_GOOGLE_CSE = "https://www.googleapis.com/customsearch/v1"

#: Wie lange EINE Quelle antworten darf.
#:
#: Sechs Sekunden, nicht fünfzehn. Das ist die Lehre aus der Messung vom
#: 16.08.2026: Die Zeit bis zur ersten Frage ans Sprachmodell stieg von 6,2
#: auf 22,5 Sekunden im Median, im schlimmsten Fall auf 77. Wer eine Antwort
#: hören will, wartet nicht eine Minute auf eine Fussnote. Eine Quelle, die
#: nach sechs Sekunden nicht geantwortet hat, hilft dem Gespräch nicht mehr.
_ZEITLIMIT = 6

#: Wie lange die GESAMTE Suche dauern darf, über alle Quellen hinweg.
#: Danach wird mit dem geantwortet, was da ist. Lieber zwei Treffer sofort
#: als fünf in einer Minute.
_GESAMTBUDGET = 8.0

#: GDELT lässt ungefähr eine Anfrage alle fünf Sekunden je Adresse zu und
#: antwortet sonst mit 429. Im Protokoll des Benutzers stand fast bei jedem
#: Durchgang "antwortete mit 429" - weil die Nachrichtenrunde sechs Quellen
#: gleichzeitig fragt und damit sechs GDELT-Anfragen im selben Augenblick
#: abfeuert. Ohne diese Bremse ruft der Orb einen Dienst an, der ihn
#: garantiert abweist, und wartet dafür auch noch.
_GDELT_ABSTAND = 5.5
#: Wie lange eine Anfrage auf einen freien Platz wartet, bevor sie aufgibt.
_GDELT_WARTEN = 2.0
_gdelt_sperre = threading.Lock()
_gdelt_zuletzt = 0.0
_gdelt_pause_bis = 0.0

#: Kurzes Gedächtnis für gleiche Anfragen. Die Nachrichtenrunde stellt
#: sechsmal beinahe dieselbe Frage; ohne das hier zahlt sie sechsmal.
_SPEICHER_DAUER = 180.0
_speicher: dict[str, tuple[float, list, list]] = {}
_speicher_sperre = threading.Lock()


class OffeneQuelleFehler(RuntimeError):
    """Eine offene Quelle war nicht erreichbar oder unbrauchbar."""


# ---------------------------------------------------------------------------
#  Netz
# ---------------------------------------------------------------------------


def _holen(url: str, *, zeitlimit: int = _ZEITLIMIT, kopfzeilen: dict | None = None) -> bytes:
    anfrage = urllib.request.Request(
        url, headers={"User-Agent": KENNUNG, "Accept": "*/*", **(kopfzeilen or {})}
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
            return antwort.read(4_000_000)
    except urllib.error.HTTPError as fehler:
        raise OffeneQuelleFehler(f"antwortete mit {fehler.code}") from fehler
    except (urllib.error.URLError, TimeoutError, OSError) as fehler:
        raise OffeneQuelleFehler(f"nicht erreichbar ({fehler})") from fehler


def _json_holen(url: str, *, zeitlimit: int = _ZEITLIMIT) -> dict:
    roh = _holen(url, zeitlimit=zeitlimit)
    try:
        daten = json.loads(roh.decode("utf-8", errors="replace"))
    except ValueError as fehler:
        # GDELT antwortet bei einer unbrauchbaren Anfrage mit HTTP 200 und
        # einem Satz Klartext statt JSON. Ohne diesen Zweig sähe das wie ein
        # Netzfehler aus und man suchte an der falschen Stelle.
        auszug = roh[:200].decode("utf-8", errors="replace").strip()
        raise OffeneQuelleFehler(f"lieferte kein JSON: {auszug}") from fehler
    return daten if isinstance(daten, dict) else {"results": daten}


def _sauber(text: str) -> str:
    ohne = re.sub(r"<[^>]+>", "", html.unescape(str(text or "")))
    return re.sub(r"\s+", " ", ohne).strip()


def _treffer(titel: str, url: str, beschreibung: str = "") -> dict[str, str] | None:
    titel = _sauber(titel)
    url = str(url or "").strip()
    if not titel or not url.startswith(("http://", "https://")):
        return None
    return {
        "titel": titel[:200],
        "url": url,
        "beschreibung": _sauber(beschreibung)[:700],
    }


# ---------------------------------------------------------------------------
#  GDELT - Nachrichten aus aller Welt
# ---------------------------------------------------------------------------


def _gdelt_datum(roh: str) -> str:
    """Macht aus ``20260815T143000Z`` ein ``15.08.2026``."""

    try:
        return datetime.strptime(roh[:15], "%Y%m%dT%H%M%S").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return ""


#: Zeichen, an denen sich GDELT verschluckt. Der Dienst antwortet darauf
#: mit Klartext statt JSON: "One or more of your keywords contained an
#: illegal character. To use a dash in a word, place it in quotes."
_GDELT_VERBOTEN = re.compile(r"[-–—+~^\"'()\[\]{}:;,!?/\\*]")


def _gdelt_begriffe(query: str) -> str:
    """Macht aus einer gesprochenen Frage eine Anfrage, die GDELT annimmt.

    Bindestriche waren der Stolperstein: "Oral-History-Berichten" liess die
    ganze Anfrage scheitern. Sie werden zu Leerzeichen, und alles, was zu
    kurz ist, um zu tragen, fliegt heraus - GDELT sucht sonst nach
    Füllwörtern und liefert Beliebiges.
    """

    sauber = _GDELT_VERBOTEN.sub(" ", str(query or ""))
    worte = [w for w in sauber.split() if len(w) > 2]
    return " ".join(worte[:12])


def _gdelt_slot(budget: float) -> bool:
    """Wartet, bis GDELT wieder gefragt werden darf. ``False`` = überspringen."""

    global _gdelt_zuletzt

    jetzt = time.monotonic()
    if jetzt < _gdelt_pause_bis:
        return False
    if not _gdelt_sperre.acquire(timeout=max(0.0, budget)):
        return False
    try:
        warten = _GDELT_ABSTAND - (time.monotonic() - _gdelt_zuletzt)
        if warten > 0:
            if warten > budget:
                return False
            time.sleep(warten)
        _gdelt_zuletzt = time.monotonic()
        return True
    finally:
        _gdelt_sperre.release()


def gdelt_suchen(
    query: str,
    *,
    limit: int = 6,
    sprache: str = "",
    domain: str = "",
    zeitraum: str = "3d",
) -> list[dict[str, str]]:
    """Durchsucht die Nachrichten der Welt über GDELT.

    Args:
        query: Die Suchwörter.
        limit: Wie viele Treffer höchstens.
        sprache: ``german``, ``english`` - leer heisst alle.
        domain: Nur von dieser Seite, z.B. ``tagesschau.de``.
        zeitraum: ``3d``, ``1w``, ``24h``. GDELT reicht rund drei Monate
            zurück; für Älteres ist es die falsche Quelle.

    Returns:
        Treffer mit Titel, Adresse und Beschreibung. Leere Liste, wenn
        nichts gefunden wurde.

    Raises:
        OffeneQuelleFehler: Wenn der Dienst nicht erreichbar war.
    """

    global _gdelt_pause_bis

    begriffe = _gdelt_begriffe(query)
    if not begriffe:
        return []

    teile = [begriffe]
    if sprache.strip():
        teile.append(f"sourcelang:{sprache.strip()}")
    if domain.strip():
        teile.append(f"domain:{domain.strip()}")

    # Nur kurz auf einen freien Platz warten, nicht das ganze Zeitlimit.
    #
    # Die Nachrichtenrunde fragt sechs Haeuser auf einmal. Wuerde jede
    # Anfrage die volle Sperrfrist abwarten, dauerte die Runde allein dafuer
    # eine halbe Minute. So kommt die erste durch, die anderen treten
    # sofort beiseite - und die uebrigen Quellen antworten unterdessen.
    if not _gdelt_slot(_GDELT_WARTEN):
        raise OffeneQuelleFehler("ist gerade gesperrt (Anfragetakt)")

    frage = urllib.parse.urlencode(
        {
            "query": " ".join(teile),
            "mode": "artlist",
            "maxrecords": str(max(1, min(limit * 2, 75))),
            "format": "json",
            "sort": "datedesc",
            "timespan": zeitraum,
        }
    )
    try:
        daten = _json_holen(f"{_GDELT}?{frage}")
    except OffeneQuelleFehler as fehler:
        if "429" in str(fehler):
            # Eine Minute Ruhe. Weiter gegen eine geschlossene Tür zu laufen
            # kostet nur Zeit, die der Benutzer als Wartezeit erlebt.
            _gdelt_pause_bis = time.monotonic() + 60.0
            logger.info("GDELT bremst uns aus - eine Minute Pause.")
        raise

    treffer: list[dict[str, str]] = []
    gesehen: set[str] = set()
    for artikel in daten.get("articles") or []:
        eintrag = _treffer(
            artikel.get("title", ""),
            artikel.get("url", ""),
            " · ".join(
                teil for teil in (
                    str(artikel.get("domain", "")),
                    _gdelt_datum(str(artikel.get("seendate", ""))),
                ) if teil
            ),
        )
        if eintrag is None or eintrag["url"] in gesehen:
            continue
        gesehen.add(eintrag["url"])
        treffer.append(eintrag)
        if len(treffer) >= limit:
            break
    return treffer


# ---------------------------------------------------------------------------
#  Wikipedia - Sachfragen
# ---------------------------------------------------------------------------


def wikipedia_suchen(
    query: str, *, limit: int = 4, sprache: str = "de"
) -> list[dict[str, str]]:
    """Durchsucht die Volltextsuche der Wikipedia."""

    begriffe = " ".join(str(query or "").split())
    if not begriffe:
        return []

    frage = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": begriffe,
            "srlimit": str(max(1, min(limit, 20))),
            "srprop": "snippet",
        }
    )
    basis = _WIKIPEDIA.format(sprache=sprache)
    daten = _json_holen(f"{basis}?{frage}")

    treffer: list[dict[str, str]] = []
    for eintrag in (daten.get("query", {}) or {}).get("search", []) or []:
        titel = str(eintrag.get("title", ""))
        if not titel:
            continue
        adresse = (
            f"https://{sprache}.wikipedia.org/wiki/"
            + urllib.parse.quote(titel.replace(" ", "_"))
        )
        gefunden = _treffer(titel, adresse, eintrag.get("snippet", ""))
        if gefunden:
            treffer.append(gefunden)
    return treffer[:limit]


# ---------------------------------------------------------------------------
#  OpenAlex und Crossref - Forschungsliteratur
# ---------------------------------------------------------------------------


def openalex_suchen(query: str, *, limit: int = 4) -> list[dict[str, str]]:
    """Durchsucht OpenAlex - über zweihundert Millionen Arbeiten."""

    begriffe = " ".join(str(query or "").split())
    if not begriffe:
        return []

    frage = urllib.parse.urlencode(
        {"search": begriffe, "per-page": str(max(1, min(limit, 25)))}
    )
    daten = _json_holen(f"{_OPENALEX}?{frage}")

    treffer: list[dict[str, str]] = []
    for arbeit in daten.get("results") or []:
        ort = arbeit.get("primary_location") or {}
        adresse = (
            str(ort.get("landing_page_url") or "")
            or str(arbeit.get("doi") or "")
            or str(arbeit.get("id") or "")
        )
        zeitschrift = str((ort.get("source") or {}).get("display_name") or "")
        jahr = str(arbeit.get("publication_year") or "")
        gefunden = _treffer(
            arbeit.get("display_name") or arbeit.get("title") or "",
            adresse,
            " · ".join(teil for teil in (zeitschrift, jahr) if teil),
        )
        if gefunden:
            treffer.append(gefunden)
        if len(treffer) >= limit:
            break
    return treffer


def crossref_suchen(query: str, *, limit: int = 4) -> list[dict[str, str]]:
    """Durchsucht Crossref - die Registrierungsstelle der DOIs."""

    begriffe = " ".join(str(query or "").split())
    if not begriffe:
        return []

    frage = urllib.parse.urlencode(
        {"query": begriffe, "rows": str(max(1, min(limit, 20))), "select":
         "title,URL,container-title,issued,author"}
    )
    daten = _json_holen(f"{_CROSSREF}?{frage}")

    treffer: list[dict[str, str]] = []
    for eintrag in ((daten.get("message") or {}).get("items") or []):
        titel = eintrag.get("title") or []
        behaelter = eintrag.get("container-title") or []
        jahr = ""
        teile = ((eintrag.get("issued") or {}).get("date-parts") or [[]])[0]
        if teile:
            jahr = str(teile[0])
        gefunden = _treffer(
            titel[0] if titel else "",
            eintrag.get("URL", ""),
            " · ".join(
                teil for teil in (behaelter[0] if behaelter else "", jahr) if teil
            ),
        )
        if gefunden:
            treffer.append(gefunden)
        if len(treffer) >= limit:
            break
    return treffer


# ---------------------------------------------------------------------------
#  RSS - die Zeitung direkt fragen
# ---------------------------------------------------------------------------


#: Die Schlagzeilen-Feeds der grossen Häuser. Feste Adressen, seit Jahren
#: dieselben - und Feeds sind das Gegenteil einer Trefferseite: Sie sind
#: DAFÜR da, von Programmen abgeholt zu werden. Kein 403, kein Takt, keine
#: Sperrseite. Reuters fehlt mit Absicht: Das Haus hat seine öffentlichen
#: Feeds 2020 eingestellt.
STANDARD_FEEDS: tuple[tuple[str, str], ...] = (
    ("tagesschau (DE)", "https://www.tagesschau.de/index~rss2.xml"),
    ("NZZ (CH)", "https://www.nzz.ch/recent.rss"),
    ("BBC (UK)", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera (QA)", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Le Monde (FR)", "https://www.lemonde.fr/rss/une.xml"),
    ("NPR (US)", "https://feeds.npr.org/1001/rss.xml"),
)

#: Wörter, die in einer Nachrichtenfrage nichts tragen. "Was gibt es Neues
#: aus aller Welt" enthält vier Wörter über drei Buchstaben - und keins
#: davon taugt als Filter für Schlagzeilen.
_FUELLWOERTER = frozenset((
    "gibt", "neues", "neue", "aller", "welt", "aktuell", "aktuelle",
    "aktuellen", "aktuelles", "heute", "gestern", "gerade", "news",
    "nachricht", "nachrichten", "schlagzeile", "schlagzeilen", "lage",
    "passiert", "geschieht", "bitte", "eine", "einen", "einer", "über",
    "ueber", "sich", "sind", "wird", "werden", "diese", "dieser", "dieses",
    "presse", "medien", "bericht", "berichte", "meldung", "meldungen",
    "erzaehl", "erzähl", "sage", "sagen", "lies", "vorlesen", "such",
    "suche", "mal", "doch", "dann", "auch", "noch", "schon", "jetzt",
    # Verweiswoerter. "Ja, bitte suche gezielt danach" hat am 17.08. eine
    # woertliche Suche nach 'gezielt danach' ausgeloest - fuenf beliebige
    # Wikipedia-Treffer, als frische Suchergebnisse vorgelegt. Diese
    # Woerter benennen nie ein Thema, sie zeigen nur auf eines.
    "gezielt", "danach", "davon", "darueber", "darüber", "dazu", "damit",
    "hierzu", "genau", "genauer", "weiter", "suchet", "zusammen",
    "neuigkeiten", "neuigkeit", "mehr", "nach", "wieder", "etwas",
))


def _inhaltsworte(query: str) -> list[str]:
    """Die Wörter einer Frage, die wirklich ein Thema benennen."""

    worte = re.split(r"\W+", str(query or "").lower())
    return [w for w in worte if len(w) > 3 and w not in _FUELLWOERTER]


def schlagzeilen_suchen(
    query: str,
    *,
    limit: int = 6,
    feeds: tuple[tuple[str, str], ...] | None = None,
) -> list[dict[str, str]]:
    """Holt Schlagzeilen direkt von den Zeitungen - ohne jede Suchmaschine.

    Benennt die Frage ein Thema, werden die Schlagzeilen danach gefiltert.
    Benennt sie keins ("was gibt es Neues"), sind die obersten Schlagzeilen
    selbst die Antwort - genau dafür gibt es eine Titelseite.

    Die Feeds werden gleichzeitig geholt. Ein Feed, der nicht antwortet,
    fällt still weg; die anderen tragen trotzdem bei.
    """

    quellen = list(feeds if feeds is not None else STANDARD_FEEDS)
    if not quellen:
        return []
    thema = " ".join(_inhaltsworte(query))
    je_feed = max(2, limit // 2 if thema else 2)

    def _ein_feed(adresse: str) -> list[dict[str, str]]:
        eintraege = rss_lesen(adresse, limit=je_feed, filter_text=thema)
        if eintraege or not thema:
            return eintraege
        # Das Thema hat alles weggefiltert - haeufig, weil deutsch gefragt
        # und englisch getitelt wird ("Nahen Osten" findet "Middle East"
        # nie). Dann lieber die ECHTEN obersten Schlagzeilen als gar
        # nichts: Am 17.08. bekam das Modell in dieser Lage null Treffer
        # vorgelegt und erfand daraufhin welche. Echte, als allgemein
        # erkennbare Schlagzeilen machen das unmoeglich.
        return rss_lesen(adresse, limit=2, filter_text="")

    gesammelt: list[dict[str, str]] = []
    pool = ThreadPoolExecutor(max_workers=min(6, len(quellen)))
    try:
        auftraege = {
            pool.submit(_ein_feed, adresse): name for name, adresse in quellen
        }
        wait(auftraege, timeout=_ZEITLIMIT)
        for auftrag, name in auftraege.items():
            if not auftrag.done():
                auftrag.cancel()
                continue
            try:
                eintraege = auftrag.result()
            except Exception:  # noqa: BLE001 - ein Feed reisst die andern nicht mit.
                logger.info("Feed %s war nicht lesbar.", name)
                continue
            for eintrag in eintraege:
                eintrag["beschreibung"] = (
                    f"{name}: {eintrag['beschreibung']}".strip().rstrip(":")
                )
                gesammelt.append(eintrag)
    finally:
        pool.shutdown(wait=False)

    # Reihum mischen statt feedweise anhaengen: Sonst bestuende die ganze
    # Liste aus dem ersten Haus, und die Vielfalt der Quellen - der Grund
    # fuer mehrere Feeds - waere wieder weg.
    nach_haus: dict[str, list[dict[str, str]]] = {}
    for eintrag in gesammelt:
        haus = eintrag["beschreibung"].split(":")[0]
        nach_haus.setdefault(haus, []).append(eintrag)
    gemischt: list[dict[str, str]] = []
    while len(gemischt) < limit and any(nach_haus.values()):
        for stapel in nach_haus.values():
            if stapel:
                gemischt.append(stapel.pop(0))
            if len(gemischt) >= limit:
                break
    return gemischt


def rss_lesen(adresse: str, *, limit: int = 6, filter_text: str = "") -> list[dict[str, str]]:
    """Liest einen RSS- oder Atom-Feed.

    Der direkte Weg zu den Schlagzeilen einer Zeitung. Um zu erfahren, was
    heute in der Tagesschau steht, braucht es keine Suchmaschine, die man
    nach ``site:tagesschau.de`` fragt - und die einen dabei abweist.
    """

    try:
        wurzel = ET.fromstring(_holen(adresse))
    except ET.ParseError as fehler:
        raise OffeneQuelleFehler(f"lieferte kein gueltiges RSS ({fehler})") from fehler

    worte = [w for w in re.split(r"\W+", filter_text.lower()) if len(w) > 3]
    treffer: list[dict[str, str]] = []

    eintraege = wurzel.findall(".//item")
    atom = "{http://www.w3.org/2005/Atom}"
    if not eintraege:
        eintraege = wurzel.findall(f".//{atom}entry")

    for eintrag in eintraege:
        titel = eintrag.findtext("title") or eintrag.findtext(f"{atom}title") or ""
        adresse_eintrag = (eintrag.findtext("link") or "").strip()
        if not adresse_eintrag:
            verweis = eintrag.find(f"{atom}link")
            if verweis is not None:
                adresse_eintrag = verweis.get("href", "")
        beschreibung = (
            eintrag.findtext("description")
            or eintrag.findtext(f"{atom}summary")
            or ""
        )
        datum = (
            eintrag.findtext("pubDate")
            or eintrag.findtext(f"{atom}updated")
            or ""
        ).strip()

        gefunden = _treffer(
            titel, adresse_eintrag,
            f"{_sauber(beschreibung)} [{datum}]" if datum else beschreibung,
        )
        if gefunden is None:
            continue
        if worte:
            heuhaufen = (gefunden["titel"] + " " + gefunden["beschreibung"]).lower()
            if not any(wort in heuhaufen for wort in worte):
                continue
        treffer.append(gefunden)
        if len(treffer) >= limit:
            break
    return treffer


# ---------------------------------------------------------------------------
#  Google, aber auf dem vorgesehenen Weg
# ---------------------------------------------------------------------------


def google_verfuegbar() -> bool:
    """Ob ein Schlüssel für die offizielle Google-Suche hinterlegt ist."""

    return bool(
        os.environ.get("GOOGLE_CSE_KEY", "").strip()
        and os.environ.get("GOOGLE_CSE_ID", "").strip()
    )


def google_suchen(query: str, *, limit: int = 6, sprache: str = "de") -> list[dict[str, str]]:
    """Sucht über die Programmable-Search-Schnittstelle von Google.

    Der Unterschied zum Abgreifen der Trefferseite ist nicht die Höflichkeit,
    sondern die Verlässlichkeit: Dies ist der vorgesehene Weg, er wird nie
    als Automat abgewiesen, und er bleibt morgen derselbe. Hundert Anfragen
    am Tag sind kostenfrei; darüber hinaus antwortet Google mit 429, und der
    Orb weicht auf die offenen Quellen aus.

    Raises:
        OffeneQuelleFehler: Wenn kein Schlüssel hinterlegt ist oder der
            Dienst nicht antwortet.
    """

    if not google_verfuegbar():
        raise OffeneQuelleFehler("kein Google-Schluessel hinterlegt")

    frage = urllib.parse.urlencode(
        {
            "key": os.environ["GOOGLE_CSE_KEY"].strip(),
            "cx": os.environ["GOOGLE_CSE_ID"].strip(),
            "q": " ".join(str(query or "").split()),
            "num": str(max(1, min(limit, 10))),
            "hl": sprache,
        }
    )
    daten = _json_holen(f"{_GOOGLE_CSE}?{frage}")

    treffer: list[dict[str, str]] = []
    for eintrag in daten.get("items") or []:
        gefunden = _treffer(
            eintrag.get("title", ""), eintrag.get("link", ""), eintrag.get("snippet", "")
        )
        if gefunden:
            treffer.append(gefunden)
    return treffer[:limit]


# ---------------------------------------------------------------------------
#  Der zusammengesetzte Weg
# ---------------------------------------------------------------------------

#: Woran eine Nachrichtenfrage zu erkennen ist.
_NACHRICHTLICH = (
    "news", "nachricht", "schlagzeil", "presse", "aktuell", "heute", "gestern",
    "diese woche", "gerade", "derzeit", "momentan", "neueste", "was gibt es neues",
    "was passiert", "krieg", "wahl", "gipfel", "streik", "prozess",
    # "Neuigkeiten zu neuen AI-Modellen" lief am 17.08. als Sachfrage zu
    # OpenAlex - und bekam Fachaufsaetze statt Meldungen vorgelegt.
    "neuigkeit", "neue entwicklungen", "was tut sich",
)

#: Woran eine wissenschaftliche Frage zu erkennen ist.
_WISSENSCHAFTLICH = (
    "studie", "studien", "forschung", "forschungsstand", "literatur", "aufsatz",
    "paper", "quellenlage", "these", "thesen", "historiograf", "historiograph",
    "monografie", "monographie", "rezension", "dissertation", "fachartikel",
    "publikation", "veröffentlichung", "veroeffentlichung",
)


def _art_der_frage(query: str) -> str:
    """Nachricht, Wissenschaft oder Sachfrage - danach richtet sich die Quelle."""

    knapp = " " + " ".join(str(query or "").lower().split()) + " "
    if any(wort in knapp for wort in _WISSENSCHAFTLICH):
        return "wissenschaft"
    if any(wort in knapp for wort in _NACHRICHTLICH):
        return "nachricht"
    return "sache"


def _domain_aus(query: str) -> tuple[str, str]:
    """Trennt ein ``site:``-Vorwort vom eigentlichen Suchbegriff ab."""

    treffer = re.search(r"\bsite:([\w.-]+)", query, re.I)
    if not treffer:
        return "", query
    rest = (query[: treffer.start()] + " " + query[treffer.end():]).strip()
    return treffer.group(1).lower(), rest


def _aus_speicher(schluessel: str) -> tuple[list[dict[str, str]], list[str]] | None:
    """Dieselbe Frage innerhalb weniger Minuten kostet nichts mehr."""

    with _speicher_sperre:
        eintrag = _speicher.get(schluessel)
        if eintrag is None:
            return None
        zeitpunkt, treffer, benutzt = eintrag
        if time.monotonic() - zeitpunkt > _SPEICHER_DAUER:
            _speicher.pop(schluessel, None)
            return None
    logger.info("Offene Suche aus dem Kurzgedächtnis beantwortet.")
    return list(treffer), list(benutzt)


def _in_speicher(schluessel: str, treffer: list, benutzt: list) -> None:
    with _speicher_sperre:
        if len(_speicher) > 80:
            _speicher.clear()
        _speicher[schluessel] = (time.monotonic(), list(treffer), list(benutzt))


def offene_suche(query: str, *, limit: int = 6) -> tuple[list[dict[str, str]], list[str]]:
    """Sucht über die Dienste, die nicht abweisen können.

    Die Reihenfolge richtet sich nach der Art der Frage, nicht nach einer
    festen Liste: Eine Nachrichtenfrage geht zuerst an GDELT, eine
    Literaturfrage an OpenAlex, eine Sachfrage an Wikipedia. Liegt ein
    Google-Schlüssel vor, steht der immer vorn - er ist die beste Suche und
    wird auf diesem Weg nicht abgewiesen.

    Returns:
        Die Treffer und die Namen der Quellen, die etwas beigetragen haben.
    """

    begriffe = " ".join(str(query or "").split())
    if not begriffe:
        return [], []

    domain, ohne_domain = _domain_aus(begriffe)
    art = _art_der_frage(ohne_domain)

    wege: list[tuple[str, object]] = []
    if google_verfuegbar():
        wege.append(("Google", lambda: google_suchen(ohne_domain, limit=limit)))

    if domain:
        # Eine Suche auf EINER Seite: Das ist genau der Fall, in dem eine
        # Suchmaschine unnoetig ist. GDELT kennt den Domainfilter.
        wege.append((
            "GDELT",
            lambda: gdelt_suchen(ohne_domain or domain.split(".")[0],
                                 limit=limit, domain=domain, zeitraum="1w"),
        ))
    elif art == "nachricht":
        # ZUERST die Zeitungen selbst. Am 16.08. um 21:26 stand im
        # Protokoll, wie die Nachrichtensuche an GDELT allein zugrunde
        # ging: Taktsperre, dann SSL-Timeout, dann der Rueckfall in die
        # fuenf gesperrten Suchmaschinen. Feeds kennen das alles nicht -
        # sie sind zum Abholen gebaut.
        wege.append(("Schlagzeilen", lambda: schlagzeilen_suchen(ohne_domain, limit=limit)))
        # GDELT bleibt als Tiefensuche dahinter: Es findet auch den Artikel
        # von vorgestern, der aus keiner Titelseite mehr hervorgeht.
        wege.append((
            "GDELT",
            lambda: gdelt_suchen(ohne_domain, limit=limit, sprache="german", zeitraum="1w"),
        ))
        wege.append(("Wikipedia", lambda: wikipedia_suchen(ohne_domain, limit=3)))
    elif art == "wissenschaft":
        wege.append(("OpenAlex", lambda: openalex_suchen(ohne_domain, limit=limit)))
        wege.append(("Crossref", lambda: crossref_suchen(ohne_domain, limit=3)))
        wege.append(("Wikipedia", lambda: wikipedia_suchen(ohne_domain, limit=3)))
    else:
        # Eine Sachfrage braucht keine Nachrichtensuche. GDELT stünde hier
        # nur im Weg: Es kostet eine Sperrfrist und liefert zu "Wer war
        # Bismarck" Tagesmeldungen statt einer Auskunft.
        wege.append(("Wikipedia", lambda: wikipedia_suchen(ohne_domain, limit=limit)))
        wege.append((
            "Wikipedia (englisch)",
            lambda: wikipedia_suchen(ohne_domain, limit=3, sprache="en"),
        ))
        wege.append(("OpenAlex", lambda: openalex_suchen(ohne_domain, limit=3)))

    # Alle Quellen GLEICHZEITIG fragen, nicht nacheinander.
    #
    # Nacheinander war der Grund für die Langsamkeit: Vier Quellen mit je
    # fünfzehn Sekunden Geduld ergeben im schlechten Fall eine Minute, in
    # der der Benutzer eine stumme Kugel ansieht. Gleichzeitig kostet das
    # Ganze so lange wie die langsamste - und länger als das Gesamtbudget
    # sowieso nie.
    #
    # Die REIHENFOLGE bleibt trotzdem erhalten: Zusammengesetzt wird nach
    # der Rangfolge oben, nicht danach, wer zuerst fertig war. Sonst
    # entschiede die Tagesform des Netzes, welche Quelle vorn steht.
    schluessel = f"{limit}|{begriffe.lower()}"
    zwischengespeichert = _aus_speicher(schluessel)
    if zwischengespeichert is not None:
        return zwischengespeichert

    ende = time.monotonic() + _GESAMTBUDGET
    ergebnisse: dict[str, list[dict[str, str]]] = {}

    pool = ThreadPoolExecutor(max_workers=min(4, len(wege)) or 1)
    try:
        auftraege = {pool.submit(sucher): name for name, sucher in wege}
        wait(auftraege, timeout=max(0.5, ende - time.monotonic()))
        for auftrag, name in auftraege.items():
            if not auftrag.done():
                auftrag.cancel()
                logger.info("Offene Quelle %s: kam nicht rechtzeitig.", name)
                continue
            try:
                ergebnisse[name] = auftrag.result()
            except OffeneQuelleFehler as fehler:
                logger.info("Offene Quelle %s: %s", name, fehler)
            except Exception:  # noqa: BLE001 - eine Quelle reisst die andern nicht mit.
                logger.exception("Offene Quelle %s abgebrochen.", name)
    finally:
        # OHNE Warten beenden. Mit ``with`` wartet der Ausstieg auf jeden
        # noch laufenden Faden - dann waere das Zeitbudget oben nur eine
        # Behauptung und die langsamste Quelle bestimmte doch wieder alles.
        # Ein Nachzuegler laeuft im Hintergrund aus; laenger als das
        # Zeitlimit einer einzelnen Anfrage kann er nicht brauchen.
        pool.shutdown(wait=False)

    gesammelt: list[dict[str, str]] = []
    gesehen: set[str] = set()
    benutzt: list[str] = []

    for name, _ in wege:
        if len(gesammelt) >= limit:
            break
        neu = 0
        for eintrag in ergebnisse.get(name, []):
            adresse = eintrag["url"].rstrip("/").lower()
            if adresse in gesehen:
                continue
            gesehen.add(adresse)
            gesammelt.append(eintrag)
            neu += 1
            if len(gesammelt) >= limit:
                break
        if neu:
            benutzt.append(name)

    if gesammelt:
        logger.info(
            "Offene Suche zu '%s': %d Treffer über %s.",
            begriffe[:60], len(gesammelt), ", ".join(benutzt),
        )
        _in_speicher(schluessel, gesammelt, benutzt)
    return gesammelt, benutzt
