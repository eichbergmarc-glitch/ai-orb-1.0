"""Die Suchmasken der Fachportale – direkt bedient statt nur verlinkt.

Der Benutzer hat es mehrfach und deutlich gesagt: Der Orb soll die
**Suchmaschinen aus seiner Favoritenleiste** wirklich benutzen, um
geschichtswissenschaftliche Fragen zu recherchieren – „sonst bringt die
Funktion nichts."

Bis hierher tat der Orb das nur halb. ``eigene_quellen`` zog aus den
Favoriten die Domänen und suchte darin mit ``site:jstor.org …`` über Bing.
Das ist besser als nichts, aber für ein Fachportal ist es der falsche Zug:
Was in JSTOR, BASE oder der Deutschen Digitalen Bibliothek liegt, steht
hinter deren **eigener Suchmaske** und taucht in einem ``site:``-Treffer
einer allgemeinen Suchmaschine oft gar nicht auf. Eine Bibliothek
durchsucht man mit ihrem Katalog, nicht, indem man von aussen durchs
Fenster sieht.

Dieses Modul liefert die Kataloge. Zu jedem bekannten Fachportal steht
hier, wie man seine Suche **direkt** anspricht und wie man die Antwort
liest. Wo ein Portal eine Programmierschnittstelle hat (Semantic Scholar,
archive.org, Wikipedia, Wikidata), wird die genommen – sie ist verlässlich
und für den maschinellen Zugriff gedacht. Wo es nur die Web-Suchmaske gibt,
wird die geholt und mit dem allgemeinen Trefferleser ausgewertet.

Zwei Grundsätze halten das robust:

1. **Kein Portal darf die anderen reissen.** Jede Maske fängt ihre Fehler
   selbst ab und liefert im Zweifel eine leere Liste. Blockt Google Scholar
   (das tut es bei automatischen Zugriffen gern), bleiben die übrigen davon
   unberührt.
2. **Die Suche versagt nie ganz.** Wikipedia ist als Auffangquelle immer
   dabei. Ihre Programmierschnittstelle ist offen, schnell und weist keine
   Anfrage ab – wenn alles andere schweigt, kommt von dort noch etwas.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


# Diese Helfer stehen im Werkzeugmodul. Der Import steht hier oben, weil
# ``web_tools`` seinerseits dieses Modul NICHT auf Modulebene lädt – der
# Ring, den Python sonst anzeigt, entsteht also nicht.
from backend.tools.web_tools import (  # noqa: E402
    _decode,
    _fetch,
    _treffer_aus_seite,
)


Treffer = dict[str, str]


@dataclass(frozen=True)
class Suchmaske:
    """Eine Fachsuche, so wie man sie anspricht und ihre Antwort liest.

    ``domaenen`` sind die Wirte, an denen ein Favorit dieser Maske erkannt
    wird (als Endung geprüft, damit ``scholar.google.de`` und
    ``scholar.google.com`` beide greifen). ``bauen`` formt aus dem
    Suchbegriff die anzufragende Adresse, ``lesen`` macht aus der rohen
    Antwort die Trefferliste. ``name`` ist, was der Benutzer als Herkunft
    zu sehen bekommt.
    """

    name: str
    domaenen: tuple[str, ...]
    bauen: Callable[[str, int], str]
    lesen: Callable[[bytes, int], list[Treffer]]


# ---------------------------------------------------------------------------
#  Die Leser – aus roher Antwort werden Treffer
# ---------------------------------------------------------------------------
#
# Jeder Leser ist wehrhaft: Was er nicht versteht, überspringt er, und im
# Zweifel gibt er eine leere Liste zurück. Ein Portal, das sein Format
# ändert, soll den Orb nicht zum Absturz bringen, sondern nur an dieser
# einen Stelle verstummen.


def _text_kurz(wert: object, hoechstens: int = 320) -> str:
    """Macht aus einem beliebigen Feld einen knappen, sauberen Text."""

    text = str(wert or "").strip()
    text = " ".join(text.split())
    return text[:hoechstens]


def _lese_semantic_scholar(roh: bytes, limit: int) -> list[Treffer]:
    """Liest die JSON-Antwort der Semantic-Scholar-Schnittstelle."""

    try:
        daten = json.loads(roh.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return []
    treffer: list[Treffer] = []
    for eintrag in (daten.get("data") or [])[: max(1, limit)]:
        titel = _text_kurz(eintrag.get("title"), 200)
        if not titel:
            continue
        url = _text_kurz(eintrag.get("url"), 400)
        jahr = eintrag.get("year")
        beschreibung = _text_kurz(eintrag.get("abstract"))
        if jahr:
            beschreibung = f"({jahr}) {beschreibung}".strip()
        treffer.append({"titel": titel, "url": url, "beschreibung": beschreibung})
    return treffer


def _lese_archive_org(roh: bytes, limit: int) -> list[Treffer]:
    """Liest die JSON-Antwort der advancedsearch-Schnittstelle von archive.org."""

    try:
        daten = json.loads(roh.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return []
    docs = ((daten.get("response") or {}).get("docs")) or []
    treffer: list[Treffer] = []
    for eintrag in docs[: max(1, limit)]:
        kennung = _text_kurz(eintrag.get("identifier"), 200)
        titel = _text_kurz(eintrag.get("title"), 200) or kennung
        if not kennung:
            continue
        beschreibung = eintrag.get("description")
        if isinstance(beschreibung, list):
            beschreibung = " ".join(str(t) for t in beschreibung)
        treffer.append({
            "titel": titel,
            "url": f"https://archive.org/details/{urllib.parse.quote(kennung)}",
            "beschreibung": _text_kurz(beschreibung),
        })
    return treffer


def _lese_wikipedia(roh: bytes, limit: int) -> list[Treffer]:
    """Liest die JSON-Antwort der MediaWiki-Suchschnittstelle (deutsch)."""

    try:
        daten = json.loads(roh.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return []
    eintraege = ((daten.get("query") or {}).get("search")) or []
    treffer: list[Treffer] = []
    for eintrag in eintraege[: max(1, limit)]:
        titel = _text_kurz(eintrag.get("title"), 200)
        if not titel:
            continue
        # Der Schnipsel kommt als HTML mit <span>-Hervorhebungen; die weg.
        schnipsel = _text_kurz(eintrag.get("snippet"))
        for marke in ('<span class="searchmatch">', "</span>"):
            schnipsel = schnipsel.replace(marke, "")
        pfad = urllib.parse.quote(titel.replace(" ", "_"))
        treffer.append({
            "titel": titel,
            "url": f"https://de.wikipedia.org/wiki/{pfad}",
            "beschreibung": schnipsel,
        })
    return treffer


def _lese_wikidata(roh: bytes, limit: int) -> list[Treffer]:
    """Liest die JSON-Antwort von ``wbsearchentities`` (Wikidata)."""

    try:
        daten = json.loads(roh.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return []
    treffer: list[Treffer] = []
    for eintrag in (daten.get("search") or [])[: max(1, limit)]:
        titel = _text_kurz(eintrag.get("label"), 200)
        if not titel:
            continue
        url = _text_kurz(eintrag.get("concepturi") or eintrag.get("url"), 400)
        if url.startswith("//"):
            url = "https:" + url
        treffer.append({
            "titel": titel,
            "url": url,
            "beschreibung": _text_kurz(eintrag.get("description")),
        })
    return treffer


def _html_leser(eigene: tuple[str, ...]) -> Callable[[bytes, int], list[Treffer]]:
    """Baut einen Leser, der eine HTML-Suchseite mit dem allgemeinen
    Trefferleser auswertet. ``eigene`` sind die Wirte des Portals selbst,
    die nicht als Treffer zählen (Navigation, Hilfeseiten)."""

    def lesen(roh: bytes, limit: int) -> list[Treffer]:
        try:
            seite = _decode(roh)
        except Exception:  # noqa: BLE001
            return []
        try:
            return _treffer_aus_seite(seite, limit, eigene)
        except Exception:  # noqa: BLE001 - ein Portal darf nie die Suche reissen.
            logger.info("HTML-Suchseite war nicht lesbar.")
            return []

    return lesen


# ---------------------------------------------------------------------------
#  Die Adressbauer
# ---------------------------------------------------------------------------


def _baue_semantic_scholar(begriff: str, limit: int) -> str:
    felder = "title,abstract,url,year"
    q = urllib.parse.urlencode({
        "query": begriff, "limit": max(1, min(limit, 10)), "fields": felder,
    })
    return f"https://api.semanticscholar.org/graph/v1/paper/search?{q}"


def _baue_archive_org(begriff: str, limit: int) -> str:
    teile = [
        ("q", begriff),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "description"),
        ("rows", str(max(1, min(limit, 10)))),
        ("output", "json"),
    ]
    return "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(teile)


def _baue_wikipedia(begriff: str, limit: int) -> str:
    q = urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": begriff,
        "format": "json", "srlimit": max(1, min(limit, 10)),
    })
    return f"https://de.wikipedia.org/w/api.php?{q}"


def _baue_wikidata(begriff: str, limit: int) -> str:
    q = urllib.parse.urlencode({
        "action": "wbsearchentities", "search": begriff, "language": "de",
        "uselang": "de", "format": "json", "limit": max(1, min(limit, 10)),
    })
    return f"https://www.wikidata.org/w/api.php?{q}"


def _baue_base(begriff: str, limit: int) -> str:
    q = urllib.parse.urlencode({"lookfor": begriff, "type": "all"})
    return f"https://www.base-search.net/Search/Results?{q}"


def _baue_ddb(begriff: str, limit: int) -> str:
    q = urllib.parse.urlencode({"query": begriff})
    return f"https://www.deutsche-digitale-bibliothek.de/searchresults?{q}"


def _baue_google_scholar(begriff: str, limit: int) -> str:
    q = urllib.parse.urlencode({"q": begriff, "hl": "de"})
    return f"https://scholar.google.com/scholar?{q}"


def _baue_jstor(begriff: str, limit: int) -> str:
    q = urllib.parse.urlencode({"Query": begriff})
    return f"https://www.jstor.org/action/doBasicSearch?{q}"


def _baue_regesta_imperii(begriff: str, limit: int) -> str:
    # Die Volltextsuche der RI-Regesten.
    q = urllib.parse.urlencode({"tx_find_find[q][default]": begriff})
    return f"https://www.regesta-imperii.de/regesten/suche.html?{q}"


# ---------------------------------------------------------------------------
#  Die Tabelle
# ---------------------------------------------------------------------------
#
# Die Reihenfolge ist die Güte: Programmierschnittstellen zuerst (sie
# antworten verlässlich), die HTML-Suchmasken danach (sie sind
# best-effort). Wikipedia steht bewusst als Maske IN der Tabelle und wird
# zusätzlich als Auffangquelle unten fest hinzugefügt.

_MASKEN: tuple[Suchmaske, ...] = (
    Suchmaske(
        "Semantic Scholar",
        ("semanticscholar.org",),
        _baue_semantic_scholar,
        _lese_semantic_scholar,
    ),
    Suchmaske(
        "Internet Archive",
        ("archive.org",),
        _baue_archive_org,
        _lese_archive_org,
    ),
    Suchmaske(
        "Wikipedia",
        ("de.wikipedia.org", "wikipedia.org"),
        _baue_wikipedia,
        _lese_wikipedia,
    ),
    Suchmaske(
        "Wikidata",
        ("wikidata.org",),
        _baue_wikidata,
        _lese_wikidata,
    ),
    Suchmaske(
        "BASE",
        ("base-search.net",),
        _baue_base,
        _html_leser(("base-search.net",)),
    ),
    Suchmaske(
        "Deutsche Digitale Bibliothek",
        ("deutsche-digitale-bibliothek.de",),
        _baue_ddb,
        _html_leser(("deutsche-digitale-bibliothek.de",)),
    ),
    Suchmaske(
        "Google Scholar",
        ("scholar.google.com", "scholar.google.de", "scholar.google"),
        _baue_google_scholar,
        _html_leser(("scholar.google.com", "google.com")),
    ),
    Suchmaske(
        "JSTOR",
        ("jstor.org",),
        _baue_jstor,
        _html_leser(("jstor.org",)),
    ),
    Suchmaske(
        "Regesta Imperii",
        ("regesta-imperii.de", "regesten.digitale-sammlungen.de"),
        _baue_regesta_imperii,
        _html_leser(("regesta-imperii.de",)),
    ),
)

#: Die feste Auffangquelle. Ihre Schnittstelle ist offen und weist nichts
#: ab – wenn alles andere schweigt, kommt von hier noch etwas.
_WIKIPEDIA: Suchmaske = _MASKEN[2]


def maske_fuer(domaene: str) -> Suchmaske | None:
    """Die passende Suchmaske zu einer Favoritendomäne – oder ``None``.

    Geprüft wird als Endung: Ein Favorit ``scholar.google.de`` greift auf
    ``scholar.google``, ``www.jstor.org`` auf ``jstor.org``.
    """

    wirt = (domaene or "").strip().lower()
    if not wirt:
        return None
    if wirt.startswith("www."):
        wirt = wirt[4:]
    for maske in _MASKEN:
        for kandidat in maske.domaenen:
            if wirt == kandidat or wirt.endswith("." + kandidat) or wirt.endswith(kandidat):
                return maske
    return None


def direkt_suchen(maske: Suchmaske, begriff: str, *, treffer: int = 3) -> list[Treffer]:
    """Bedient EINE Suchmaske direkt und liest ihre Treffer.

    Wehrhaft: Jeder Fehler – abgewiesen, nicht erreichbar, unlesbar –
    ergibt eine leere Liste, nie eine Ausnahme. Die Aufrufer laufen darüber
    hinweg zur nächsten Quelle.
    """

    begriff = (begriff or "").strip()
    if not begriff:
        return []
    try:
        adresse = maske.bauen(begriff, treffer)
        roh = _fetch(adresse, timeout=12.0)
    except Exception as fehler:  # noqa: BLE001 - eine Quelle darf die andern nicht reissen.
        logger.info("Suchmaske '%s' lieferte nichts: %s", maske.name, fehler)
        return []
    try:
        return maske.lesen(roh, treffer)
    except Exception:  # noqa: BLE001
        logger.info("Antwort von '%s' war nicht zu lesen.", maske.name)
        return []


async def favoriten_suche(
    begriff: str,
    domaenen: list[str],
    *,
    je_quelle: int = 3,
    gleichzeitig: int = 4,
) -> dict[str, list[Treffer]]:
    """Sucht zu ``begriff`` in den Favoritendomänen – Maske vor ``site:``.

    Für jede Domäne gilt: Gibt es eine echte Suchmaske (JSTOR, BASE,
    Semantic Scholar …), wird sie direkt bedient. Für die übrigen bleibt es
    beim bewährten ``site:``-Weg über die allgemeine Suche. Alles läuft
    parallel, mit einer Schranke gegen zu viele gleichzeitige Anfragen.

    Wikipedia kommt als Auffangquelle immer hinzu – so liefert die Suche
    auch dann etwas, wenn kein Fachportal antwortet.
    """

    import asyncio

    from backend.tools.web_tools import search_web

    schranke = asyncio.Semaphore(max(1, gleichzeitig))

    async def _eine(name: str, arbeit: Callable[[], list[Treffer]]):
        async with schranke:
            try:
                return name, await asyncio.to_thread(arbeit)
            except Exception as fehler:  # noqa: BLE001
                logger.info("Quelle '%s' lieferte nichts: %s", name, fehler)
                return name, []

    aufgaben = []
    schon: set[str] = set()
    for domaene in domaenen:
        wirt = (domaene or "").strip().lower()
        if not wirt or wirt in schon:
            continue
        schon.add(wirt)
        maske = maske_fuer(wirt)
        if maske is not None:
            aufgaben.append(_eine(
                f"deine Quelle: {maske.name}",
                lambda m=maske: direkt_suchen(m, begriff, treffer=je_quelle),
            ))
        else:
            aufgaben.append(_eine(
                f"deine Quelle: {wirt}",
                lambda w=wirt: search_web(f"{begriff} site:{w}", limit=je_quelle),
            ))

    # Wikipedia als feste Auffangquelle, sofern nicht ohnehin schon dabei.
    schon_wikipedia = any(maske_fuer(w) is _WIKIPEDIA for w in schon)
    if not schon_wikipedia:
        aufgaben.append(_eine(
            "Wikipedia (Auffangquelle)",
            lambda: direkt_suchen(_WIKIPEDIA, begriff, treffer=je_quelle),
        ))

    ergebnisse = await asyncio.gather(*aufgaben, return_exceptions=True)

    gesammelt: dict[str, list[Treffer]] = {}
    for eintrag in ergebnisse:
        if isinstance(eintrag, BaseException):
            continue
        name, treffer_liste = eintrag
        if treffer_liste:
            gesammelt[name] = treffer_liste
    return gesammelt
