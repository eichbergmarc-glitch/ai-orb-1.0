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
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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

_ZEITLIMIT = 15


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

    begriffe = " ".join(str(query or "").split())
    if not begriffe:
        return []

    teile = [begriffe]
    if sprache.strip():
        teile.append(f"sourcelang:{sprache.strip()}")
    if domain.strip():
        teile.append(f"domain:{domain.strip()}")

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
    daten = _json_holen(f"{_GDELT}?{frage}")

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
        wege.append(("GDELT", lambda: gdelt_suchen(ohne_domain, limit=limit, zeitraum="3d")))
        wege.append((
            "GDELT (deutsch)",
            lambda: gdelt_suchen(ohne_domain, limit=limit, sprache="german", zeitraum="1w"),
        ))
        wege.append(("Wikipedia", lambda: wikipedia_suchen(ohne_domain, limit=3)))
    elif art == "wissenschaft":
        wege.append(("OpenAlex", lambda: openalex_suchen(ohne_domain, limit=limit)))
        wege.append(("Crossref", lambda: crossref_suchen(ohne_domain, limit=3)))
        wege.append(("Wikipedia", lambda: wikipedia_suchen(ohne_domain, limit=3)))
    else:
        wege.append(("Wikipedia", lambda: wikipedia_suchen(ohne_domain, limit=limit)))
        wege.append((
            "Wikipedia (englisch)",
            lambda: wikipedia_suchen(ohne_domain, limit=3, sprache="en"),
        ))
        wege.append(("GDELT", lambda: gdelt_suchen(ohne_domain, limit=3, zeitraum="1w")))
        wege.append(("OpenAlex", lambda: openalex_suchen(ohne_domain, limit=3)))

    gesammelt: list[dict[str, str]] = []
    gesehen: set[str] = set()
    benutzt: list[str] = []

    for name, sucher in wege:
        if len(gesammelt) >= limit:
            break
        try:
            gefunden = sucher()
        except OffeneQuelleFehler as fehler:
            logger.info("Offene Quelle %s: %s", name, fehler)
            continue
        except Exception:  # noqa: BLE001 - eine Quelle darf die anderen nicht mitreissen.
            logger.exception("Offene Quelle %s abgebrochen.", name)
            continue

        neu = 0
        for eintrag in gefunden:
            schluessel = eintrag["url"].rstrip("/").lower()
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
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
    return gesammelt, benutzt
