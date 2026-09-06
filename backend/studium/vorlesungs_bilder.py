"""Bestimmt passende Bildsuchbegriffe fuer gesprochene Vorlesungsabschnitte.

Die Auswahl ist absichtlich lokal und deterministisch. Fuer eine blosse
Suchwortbestimmung noch ein Sprachmodell aufzurufen, wuerde jeden Abschnitt
verzoegern und genau den fluessigen Vortragsmodus wieder beschaedigen.
"""

from __future__ import annotations

import re
import textwrap
from functools import lru_cache

_THEMA = re.compile(r"^\s*Thema\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_NAMENSGRUPPE = re.compile(
    r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]+(?:[- ][A-ZÄÖÜ][A-Za-zÄÖÜäöüß]+){0,3}\b"
)
_WISSENSCHAFTLICHER_NAME = re.compile(
    r"\b(?:Homo|Australopithecus|Paranthropus|Panthera|Canis|Felis|"
    r"Escherichia|Bacillus|Staphylococcus)\s+[a-zäöüß-]{3,}\b"
)

# Satzanfang und Vortragsregie sind keine Bildmotive.
_UNSPEZIFISCH = {
    "also",
    "abschnitt",
    "anfang",
    "beginnen",
    "begriff",
    "dabei",
    "damit",
    "das",
    "der",
    "die",
    "dies",
    "diese",
    "dieser",
    "ein",
    "eine",
    "erstens",
    "geschichte",
    "geschichtswissenschaft",
    "menschheitsgeschichte",
    "mensch",
    "menschen",
    "datierung",
    "datierungen",
    "entwicklung",
    "einwurf",
    "exkurs",
    "frage",
    "fragen",
    "gut",
    "jahr",
    "jahre",
    "jahren",
    "jahrhundert",
    "jahrhunderte",
    "jahrhunderten",
    "jahrhunderts",
    "beispiel",
    "streit",
    "unterschied",
    "zahl",
    "zahlen",
    "heute",
    "hier",
    "ich",
    "kurz",
    "kurze",
    "kurzer",
    "kurzen",
    "kurzes",
    "nun",
    "bleiben",
    "verlassen",
    "verständnis",
    "verstaendnis",
    "norden",
    "süden",
    "sueden",
    "was",
    "nach",
    "quelle",
    "quellen",
    "randbemerkung",
    "thema",
    "trat",
    "zeit",
    "zehntausend",
    "zehntausende",
    "vorlesung",
    "vor",
    "wir",
    "zunächst",
    "zunaechst",
}

_ABSTRAKTE_THEMEN = {
    "geschichte",
    "geschichtswissenschaft",
    "menschheitsgeschichte",
    "sprachwissenschaft",
    "wissenschaft",
    "einführung",
    "einfuehrung",
}

# Allein sind diese Woerter kein eindeutiges Bildmotiv. In einer festen
# Verbindung wie "Neolithische Revolution" bleiben sie dagegen erhalten.
_ABSTRAKTE_MOTIVE = {
    "erfolg", "folge", "folgen", "bedeutung", "wirkung", "wandel",
    "aufstieg", "niedergang", "entwicklung", "prinzip", "revolution",
    "situation", "schauplatz", "zeit", "phase", "prozess",
}

# Ein Vortrag nennt oft zuerst eine abstrakte Einordnung ("über
# Jahrhunderte"), obwohl wenig später ein eindeutig sichtbarer Gegenstand
# vorkommt. Die bisherige Grossschreibungs-Heuristik machte dann aus dem
# Satzanfang den Suchbegriff und zeigte beispielsweise ein beliebiges Bild zu
# "Jahrhunderte". Diese Regeln übersetzen Fachbegriffe deshalb zuerst in
# Dinge, die man tatsächlich zeigen kann. Die englischen Suchformen sind
# bewusst gewählt: Commons katalogisiert historische Objekte überwiegend so.
_OBJEKTMOTIVE: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(
            r"\b(?:vier\s+ursachen|materialursache|formursache|"
            r"wirkursache|zielursache|zweckursache|causa\s+(?:materialis|"
            r"formalis|efficiens|finalis))\b",
            re.I,
        ),
        (
            "Aristotle four causes diagram",
            "School of Athens Aristotle Raphael",
        ),
    ),
    (
        re.compile(r"\b(?:keilschrift\w*|tont[aä]fel\w*|schreibgriffel\w*)", re.I),
        ("cuneiform clay tablet", "cuneiform reed stylus clay tablet"),
    ),
    (
        re.compile(r"\b(?:hammurabi\w*|talionsprinzip\w*|rechtsstele\w*)", re.I),
        ("Code of Hammurabi stele",),
    ),
    (re.compile(r"\bsokrates\w*", re.I), ("Socrates portrait bust",)),
    (re.compile(r"\bplaton\w*", re.I), ("Plato portrait bust",)),
    (re.compile(r"\baristoteles\w*", re.I), ("Aristotle portrait bust",)),
    (re.compile(r"\bkant\w*", re.I), ("Immanuel Kant portrait",)),
    (re.compile(r"\bhegel\w*", re.I), ("Georg Wilhelm Friedrich Hegel portrait",)),
    (re.compile(r"\bnietzsche\w*", re.I), ("Friedrich Nietzsche portrait",)),
    (
        re.compile(r"\b(?:nibelungenlied\w*|mittelalterliche\s+handschrift\w*|codex\w*)", re.I),
        ("Nibelungenlied medieval manuscript",),
    ),
    (
        re.compile(r"\bgoethe\w*", re.I),
        ("Johann Wolfgang von Goethe portrait",),
    ),
    (
        re.compile(r"\bschiller\w*", re.I),
        ("Friedrich Schiller portrait",),
    ),
    (re.compile(r"\bkafka\w*", re.I), ("Franz Kafka portrait",)),
    (re.compile(r"\bbrecht\w*", re.I), ("Bertolt Brecht portrait",)),
    (re.compile(r"\bfontane\w*", re.I), ("Theodor Fontane portrait",)),
    (
        re.compile(r"\b(?:phonetik\w*|phonolog\w*|phonem\w*|lautverschiebung\w*)", re.I),
        ("International Phonetic Alphabet chart",),
    ),
    (
        re.compile(r"\b(?:syntax\w*|satzstruktur\w*|feldermodell\w*)", re.I),
        ("linguistics syntax tree diagram",),
    ),
    (
        re.compile(r"\b(?:inflation\w*|verbraucherpreis\w*)", re.I),
        ("consumer price index inflation chart",),
    ),
    (
        re.compile(r"\b(?:zentralbank\w*|leitzins\w*|geldpolitik\w*)", re.I),
        ("European Central Bank building",),
    ),
    (
        re.compile(r"\b(?:welthandel\w*|lieferkette\w*|globalisierung\w*)", re.I),
        ("container port global trade",),
    ),
    (
        re.compile(r"\b(?:assurbanipal\w*|ashurbanipal\w*|bibliothek\s+assurbanipal\w*)", re.I),
        ("Library of Ashurbanipal clay tablet", "Ashurbanipal relief"),
    ),
    (
        re.compile(r"\b(?:hieroglyph\w*|ägyptische\s+schrift\w*)", re.I),
        ("ancient Egyptian hieroglyph stone inscription",),
    ),
    (re.compile(r"\bpapyrus\w*", re.I), ("ancient Egyptian papyrus manuscript",)),
    (
        re.compile(r"\b(?:buchdruck\w*|druckerpresse\w*|gutenberg\w*)", re.I),
        ("Gutenberg printing press",),
    ),
    (
        re.compile(r"\b(?:sumer\w*|sumerisch\w*)", re.I),
        ("Sumerian cuneiform clay tablet", "Sumerian archaeological artifact"),
    ),
    (
        re.compile(r"\buruk\w*", re.I),
        ("Uruk archaeological site", "Uruk cuneiform tablet"),
    ),
    (
        re.compile(r"\b(?:akkad\w*|sargon\w*)", re.I),
        ("Sargon of Akkad relief", "Akkadian Empire artifact"),
    ),
    (
        re.compile(r"\b(?:mesopotami\w*|stadtstaat\w*|ziggurat\w*)", re.I),
        ("Mesopotamia ziggurat archaeological site",),
    ),
)

_ABSTRAKTE_ENDUNGEN = (
    "heit", "keiten", "keit", "nisse", "nis", "schaft", "täten", "taeten",
)

# Viele Commons-Titel sind englisch, selbst wenn die Suche auf Deutsch
# erfolgte. Diese kleine visuelle Fachwortbruecke ist keine Uebersetzung des
# Vortrags, sondern verhindert, dass ein passendes Foto nur wegen seiner
# englischen Dateibezeichnung als unpassend verworfen wird.
_BILDWORT_BRUECKEN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("akkad", ("akkad",)),
    ("aristotel", ("aristotle",)),
    ("archaeolog", ("archaeolog", "archeolog")),
    ("bewasser", ("irrigation",)),
    ("keilschrift", ("cuneiform", "tablet")),
    ("neolithi", ("neolithi",)),
    ("reich", ("empire",)),
    ("roemisch", ("roman",)),
    ("sargon", ("sargon",)),
    ("stadtstaat", ("citystate", "city", "state")),
    ("tafel", ("tablet",)),
    ("taefel", ("tablet",)),
    ("tempel", ("temple",)),
    ("ursach", ("cause", "causa")),
    ("zweck", ("final", "purpose")),
    ("ziel", ("final", "purpose")),
    ("verwaltungstaef", ("administrative", "cuneiform", "tablet")),
)


_VIER_URSACHEN: tuple[dict[str, str], ...] = (
    {
        "title": "Materialursache",
        "text": "Woraus etwas besteht – bei einer Statue etwa Erz oder Marmor.",
    },
    {
        "title": "Formursache",
        "text": "Welche Gestalt und Wesensform den Stoff zu genau diesem Ding macht.",
    },
    {
        "title": "Wirkursache",
        "text": "Wer oder was die Veränderung hervorbringt – etwa der Bildhauer.",
    },
    {
        "title": "Zweckursache",
        "text": "Wozu etwas entsteht oder dient – sein Ziel, das Telos.",
    },
)

_URSACHEN_MUSTER = re.compile(
    r"\b(?:vier\s+ursachen|material(?:e)?\s+ursache|materialursache|"
    r"formal(?:e)?\s+ursache|formursache|wirk(?:ende)?\s+ursache|"
    r"wirkursache|zielursache|zweckursache|finalursache|"
    r"causa\s+(?:materialis|formalis|efficiens|finalis))\b",
    re.IGNORECASE,
)

_ORDNUNGSWOERTER = {
    "erstens": "1",
    "zweitens": "2",
    "drittens": "3",
    "viertens": "4",
    "fünftens": "5",
    "fuenftens": "5",
    "sechstens": "6",
}


def vorlesungsthema(auftrag: str) -> str:
    """Liest das bereits im internen Abschnittsauftrag vorhandene Thema."""

    treffer = _THEMA.search(str(auftrag or ""))
    if not treffer:
        return ""
    thema = treffer.group(1)
    # Whisper liefert bei Fortsetzungsbefehlen gelegentlich den ganzen Rest
    # als Thema ("v a mit der Einführungsvorlässung Geschichtswissenschaft").
    # Regiewörter ergeben schlechte Bildsuchen und werden hier entfernt.
    thema = re.sub(r"\b\w*vorl\w*ung\w*\b", " ", thema, flags=re.IGNORECASE)
    thema = re.sub(r"\b(?:einführung|einfuehrung)\w*\b", " ", thema, flags=re.IGNORECASE)
    thema = re.sub(
        r"^\s*(?:v\s*a\s+)?(?:(?:ich\s+)?fahre?\s+(?:fort|vor)\s+)?(?:mit\s+der\s+)?",
        "",
        thema,
        flags=re.IGNORECASE,
    )
    return _kuerzen(thema, 90)


def bildsuchbegriffe(abschnitt: str, auftrag: str = "") -> list[str]:
    """Liefert spezifischen Begriff und robusten Rueckfall fuer ein Bild.

    Deutsche Substantive und Eigennamen sind grossgeschrieben. Diese einfache
    Spracheigenschaft ist fuer historische Personen, Orte, Epochen, Werke und
    naturwissenschaftliche Begriffe erstaunlich belastbar und kostet keine
    weitere Modellantwort.
    """

    text = " ".join(str(abschnitt or "").split())
    grundthema = vorlesungsthema(auftrag)
    kandidaten: list[tuple[int, str]] = []

    # Konkrete Gegenstände gewinnen immer gegen zufällige Grossschreibung am
    # Satzanfang. So wird bei Keilschrift eine Tontafel bzw. ein Griffel
    # gezeigt und nicht "Jahrhunderte", "Verständnis" oder "Einwurf".
    objektmotive: list[str] = []
    for muster, suchformen in _OBJEKTMOTIVE:
        if muster.search(text):
            objektmotive.extend(suchformen)
            if len(objektmotive) >= 2:
                break

    # Lateinische Artnamen sind besonders gute, eindeutige Bildbegriffe und
    # besitzen absichtlich ein kleingeschriebenes zweites Wort. Die normale
    # Grossschreibungsregel wuerde gerade "Homo sapiens" uebersehen.
    artnamen = [
        treffer.group(0) for treffer in _WISSENSCHAFTLICHER_NAME.finditer(text[:1400])
    ]
    for index, artname in enumerate(artnamen):
        kandidaten.append((120 - index, artname))

    for index, treffer in enumerate(_NAMENSGRUPPE.finditer(text[:1400])):
        if artnamen:
            break
        begriff = " ".join(treffer.group(0).split()).strip(" -–—.,:;!?")
        woerter = begriff.split()
        brauchbar = [w for w in woerter if w.casefold() not in _UNSPEZIFISCH]
        if not brauchbar:
            continue
        if len(brauchbar) == 1 and brauchbar[0].casefold() in _ABSTRAKTE_MOTIVE:
            continue
        if len(brauchbar) == 1 and brauchbar[0].casefold().endswith(_ABSTRAKTE_ENDUNGEN):
            continue
        # "Hammurabis Erfolg" sucht schlecht, "Hammurabis" dagegen fuehrt
        # direkt zu Person und Stele. Kontextualisierte feste Begriffe wie
        # "Neolithische Revolution" bleiben unberuehrt.
        if len(brauchbar) > 1 and (
            brauchbar[0].casefold() in _ABSTRAKTE_MOTIVE
            or brauchbar[0].casefold().endswith("s")
        ):
            ohne_abstrakt = [
                wort for wort in brauchbar if wort.casefold() not in _ABSTRAKTE_MOTIVE
            ]
            if ohne_abstrakt:
                brauchbar = ohne_abstrakt
        begriff = " ".join(brauchbar)
        # Mehrteilige Namen ("Römische Republik", "Marie Curie") sind
        # bildlich spezifischer. Fruehe Nennungen beschreiben meist den
        # Schwerpunkt des Abschnitts.
        punkte = len(brauchbar) * 10 + min(len(begriff), 35) - index
        kandidaten.append((punkte, begriff))

    ergebnis: list[str] = list(objektmotive)
    if kandidaten:
        # Nicht nur einen Kandidaten behalten. Bildarchive reagieren auf
        # Flexionen und Uebersetzungen sehr verschieden; drei konkrete Motive
        # sind wesentlich robuster als ein allgemeiner Rueckfallbegriff.
        max_motive = max(
            0,
            (2 if grundthema and _ist_konkret(grundthema) else 3) - len(ergebnis),
        )
        for _punkte, spezifisch in sorted(kandidaten, reverse=True):
            ergebnis.append(_kuerzen(spezifisch, 90))
            if len(ergebnis) >= len(objektmotive) + max_motive:
                break

    if grundthema and _ist_konkret(grundthema):
        ergebnis.append(grundthema)

    # Reihenfolge erhalten, leere und gleiche Varianten entfernen.
    eindeutig: list[str] = []
    gesehen: set[str] = set()
    for begriff in ergebnis:
        schluessel = begriff.casefold()
        if begriff and schluessel not in gesehen:
            gesehen.add(schluessel)
            eindeutig.append(begriff)
    return eindeutig[:3]


def bild_passt(begriff: str, eintrag: dict[str, object]) -> bool:
    """Prueft, ob Titel/Nachweis den Suchbegriff tatsaechlich widerspiegeln.

    Dabei werden Flexionen (``Sargons``/``Sargon``), nahe Wortstaemme
    (``Akkadische``/``Akkad``) und wenige fuer Bildarchive typische
    deutsch-englische Fachwortpaare beruecksichtigt.
    """

    suchwoerter = _woerter(begriff)
    if not suchwoerter:
        return False
    metadaten = " ".join(
        str(eintrag.get(name, "") or "")
        for name in ("titel", "nachweis", "seite_url", "quelle")
    )
    fundwoerter = _woerter(metadaten, auch_unspezifisch=True)
    suchformen = _bildwortformen(suchwoerter)
    fundformen = _bildwortformen(fundwoerter)
    if suchformen & fundformen:
        return True
    return any(
        _gleicher_wortstamm(suchwort, fundwort)
        for suchwort in suchformen
        for fundwort in fundformen
    )


def bild_treffer_bewerten(begriff: str, eintrag: dict[str, object]) -> int:
    """Bewertet Relevanz und Darstellungsqualitaet eines Bildtreffers.

    Der erste Treffer eines Archivs ist nicht automatisch der beste. Fuer
    eine Lehrtafel gewinnen ein klarer Titel, eine brauchbare Aufloesung und
    ein nicht zu extremes Seitenverhaeltnis. Unpassende Metadaten bleiben ein
    hartes Ausschlusskriterium.
    """

    if not bild_passt(begriff, eintrag):
        return -10_000
    titel = str(eintrag.get("titel", "") or "")
    nachweis = " ".join(
        str(eintrag.get(name, "") or "")
        for name in ("titel", "nachweis", "quelle")
    )
    suchformen = _bildwortformen(_woerter(begriff))
    titelformen = _bildwortformen(_woerter(titel, auch_unspezifisch=True))
    metadatenformen = _bildwortformen(_woerter(nachweis, auch_unspezifisch=True))
    punkte = 100
    punkte += 28 * len(suchformen & titelformen)
    punkte += 8 * len(suchformen & metadatenformen)
    if "wikimedia commons" in nachweis.casefold():
        punkte += 8

    try:
        breite = int(eintrag.get("breite", 0) or 0)
        hoehe = int(eintrag.get("hoehe", 0) or 0)
    except (TypeError, ValueError):
        breite = hoehe = 0
    if breite >= 1000 and hoehe >= 650:
        punkte += 18
    elif breite >= 700 and hoehe >= 450:
        punkte += 10
    if breite > 0 and hoehe > 0:
        verhaeltnis = breite / hoehe
        if 1.15 <= verhaeltnis <= 2.0:
            punkte += 12
        elif verhaeltnis > 3.2 or verhaeltnis < 0.42:
            punkte -= 16

    unruhig = ("logo", "icon", "thumbnail", "collage", "stamp", "coin")
    if any(wort in titel.casefold() for wort in unruhig):
        punkte -= 24
    return punkte


def _vier_ursachen_gemeint(text: str) -> bool:
    sauber = str(text or "")
    if re.search(r"\bvier\s+ursachen\b", sauber, re.IGNORECASE):
        return True
    return len(_URSACHEN_MUSTER.findall(sauber)) >= 2


def _benannte_strukturkarten(text: str) -> list[dict[str, str]]:
    """Liest explizit benannte Punkte, ohne sie thematisch umzusortieren."""

    karten: list[dict[str, str]] = []
    for satz in re.split(r"(?<=[.!?])\s+|[\r\n]+", str(text or "")):
        sauber = " ".join(satz.split()).strip(" -–—")
        if not sauber:
            continue
        ordinal = re.match(
            r"^(erstens|zweitens|drittens|viertens|fünftens|fuenftens|"
            r"sechstens)\s*[:,.-]?\s*(.+)$",
            sauber,
            flags=re.IGNORECASE,
        )
        if ordinal:
            nummer = _ORDNUNGSWOERTER[ordinal.group(1).casefold()]
            karten.append(
                {
                    "title": f"{nummer}. Punkt",
                    "text": _grafikpunkt(ordinal.group(2)),
                }
            )
            continue
        label = re.match(
            r"^(?:die|der|das)?\s*([A-Za-zÄÖÜäöüß][^:]{2,44}?)\s*:\s*(.+)$",
            sauber,
            flags=re.IGNORECASE,
        )
        if label and 1 <= len(label.group(1).split()) <= 6:
            karten.append(
                {
                    "title": _kuerzen(label.group(1), 48),
                    "text": _grafikpunkt(label.group(2)),
                }
            )
    # Eine einzelne Ueberschrift ist noch keine Struktur. Zwei oder mehr
    # benannte Punkte dagegen duerfen nie in generische Kategorien zerfallen.
    return karten[:6] if len(karten) >= 2 else []


def strukturkarten(abschnitt: str) -> list[dict[str, str]]:
    """Gibt die im Lehrstoff selbst enthaltene fachliche Ordnung zurueck."""

    sauber = " ".join(str(abschnitt or "").split())
    if _vier_ursachen_gemeint(sauber):
        return [dict(karte) for karte in _VIER_URSACHEN]
    return _benannte_strukturkarten(abschnitt)


def uebersichtsart(abschnitt: str) -> str:
    """Layout-Hinweis fuer die Lehrtafel.

    Vier Darstellungsarten statt bisher zwei. Die Reihenfolge ist eine
    Rangfolge: Eine ausdrueckliche Fachstruktur schlaegt alles, danach
    kommt, was der Abschnitt selbst hergibt.

    Der Gedanke dahinter steht in ``zeigen.py``: Ein Bild soll etwas
    zeigen, das in Worten muehsam waere. Fuer eine Abfolge von Jahren ist
    das eine Zeitleiste, fuer zwei gegeneinander gestellte Positionen eine
    Gegenueberstellung. Beides in fuenf gleich aussehende Textkarten zu
    giessen, wirft genau die Information weg, die das Auge schneller
    aufnimmt als das Ohr.
    """

    if strukturkarten(abschnitt):
        return "enumeration"
    saetze = [satz for satz in _saetze(" ".join(str(abschnitt or "").split())) if satz]
    if len(_zeitpunkte(saetze)) >= 3:
        return "timeline"
    if _gegenueberstellung(saetze):
        return "comparison"
    return "overview"


#: Wie eine Jahresangabe im gesprochenen Text aussehen kann.
_ZEITMUSTER: tuple[tuple[str, int], ...] = (
    (r"\b(\d{1,4})\s*v\.?\s*(?:chr|u\.?\s*z)\w*\.?", -1),
    (r"\b(\d{1,4})\s*n\.?\s*chr\w*\.?", 1),
    (r"\b(\d{1,2})\.\s*jahrhundert", 100),
    (r"\b(1[0-9]{3}|20[0-9]{2})\b", 1),
)


def _zeitpunkte(saetze: list[str]) -> list[tuple[int, str, str]]:
    """Findet datierbare Aussagen: (Sortierwert, Beschriftung, Satz).

    Jeder Satz zaehlt hoechstens einmal - sonst stuenden auf der Leiste
    fuenf Marken, hinter denen dreimal derselbe Satz steht.
    """

    gefunden: list[tuple[int, str, str]] = []
    belegt: set[str] = set()
    for satz in saetze:
        for muster, richtung in _ZEITMUSTER:
            # Auf dem ORIGINAL suchen, nicht auf der kleingeschriebenen
            # Fassung: Die Beschriftung der Leiste soll "1750 v. Chr."
            # heissen und nicht "1750 v. chr".
            treffer = re.search(muster, satz, flags=re.IGNORECASE)
            if treffer is None:
                continue
            try:
                zahl = int(treffer.group(1))
            except (TypeError, ValueError):
                continue
            if satz in belegt:
                break
            belegt.add(satz)
            beschriftung = " ".join(treffer.group(0).split()).strip()
            if richtung == 100:
                # "Im 6. Jahrhundert v. Chr." liegt VOR "Im 2. Jahrhundert
                # n. Chr." - ohne diese Pruefung stand die halbe Antike
                # hinter der Neuzeit auf der Leiste.
                folgt = satz[treffer.end() : treffer.end() + 24].casefold()
                vorzeichen = -1 if re.search(r"v\.?\s*(?:chr|u\.?\s*z)", folgt) else 1
                wert = zahl * 100 * vorzeichen
                if vorzeichen < 0:
                    beschriftung = f"{beschriftung} v. Chr."
            else:
                wert = zahl * (1 if richtung > 0 else -1)
            gefunden.append((wert, beschriftung, satz))
            break
    gefunden.sort(key=lambda eintrag: eintrag[0])
    return gefunden


def _gegenueberstellung(saetze: list[str]) -> tuple[str, str] | None:
    """Erkennt zwei Positionen, die im Abschnitt gegeneinander stehen.

    Gesucht wird nicht nach einer Wortliste, sondern nach dem Muster
    selbst: zwei Namen, die beide mehrfach vorkommen, und zu jedem
    mindestens ein Satz, in dem NUR er vorkommt. Genau so sieht ein
    Vergleich aus - "Bei Platon ... Bei Aristoteles ...". Kommen beide
    Namen immer zusammen vor, ist es kein Vergleich, sondern ein Thema.
    """

    zaehler: dict[str, int] = {}
    for satz in saetze:
        for name in set(re.findall(r"\b[A-ZÄÖÜ][a-zäöüß]{3,}\b", satz)):
            zaehler[name] = zaehler.get(name, 0) + 1

    haeufig = [name for name, anzahl in zaehler.items() if anzahl >= 2]
    haeufig.sort(key=lambda name: -zaehler[name])
    for i, erster in enumerate(haeufig[:4]):
        for zweiter in haeufig[i + 1 : 5]:
            nur_erster = any(erster in satz and zweiter not in satz for satz in saetze)
            nur_zweiter = any(zweiter in satz and erster not in satz for satz in saetze)
            if nur_erster and nur_zweiter:
                return erster, zweiter
    return None


def vorlesungsfolie_titel(abschnitt: str, auftrag: str = "") -> str:
    """Eine fachliche Folienueberschrift statt des technischen Suchbegriffs."""

    if _vier_ursachen_gemeint(abschnitt):
        return "Aristoteles: Die vier Ursachen"
    karten = strukturkarten(abschnitt)
    if karten:
        thema = vorlesungsthema(auftrag)
        return f"{thema}: Kernstruktur" if thema else "Kernstruktur"
    thema = vorlesungsthema(auftrag)
    return thema or "Vorlesungsabschnitt"


def folienpunkte_bereinigen(titel: str, punkte: object) -> tuple[str, ...]:
    """Normalisiert Modell-Ausgaben zu echten, kurzen Folienpunkten.

    Sprachmodelle liefern ``punkte`` gelegentlich als einen String. Die alte
    Schleife machte daraus einen Stichpunkt pro Buchstabe. Hier werden
    Zeilen, Semikola und nummerierte Folgen sauber getrennt. Bei der
    ausdruecklich genannten Vier-Ursachen-Lehre wird die kanonische
    Viererstruktur garantiert vollstaendig dargestellt.
    """

    roh: list[str] = []
    if isinstance(punkte, str):
        text = punkte.strip()
        if text:
            teile = re.split(
                r"\s*(?:\r?\n|;|\|)\s*|\s+(?=(?:[1-6][.)]|"
                r"erstens|zweitens|drittens|viertens|fünftens|fuenftens)\b)",
                text,
                flags=re.IGNORECASE,
            )
            roh.extend(teile)
    elif isinstance(punkte, (list, tuple)):
        for punkt in punkte:
            if isinstance(punkt, dict):
                name = str(
                    punkt.get("titel")
                    or punkt.get("name")
                    or punkt.get("begriff")
                    or ""
                ).strip()
                text = str(
                    punkt.get("text")
                    or punkt.get("erklaerung")
                    or punkt.get("beschreibung")
                    or ""
                ).strip()
                roh.append(f"{name} — {text}".strip(" —"))
            else:
                roh.append(str(punkt))
    elif punkte is not None:
        roh.append(str(punkte))

    sauber: list[str] = []
    for punkt in roh:
        wert = " ".join(str(punkt or "").split()).strip(" -–—•")
        wert = re.sub(r"^[1-9][.)]\s*", "", wert)
        if wert and wert.casefold() not in {p.casefold() for p in sauber}:
            sauber.append(textwrap.shorten(wert, width=170, placeholder=" …"))

    kontext = f"{titel} {' '.join(sauber)}"
    if _vier_ursachen_gemeint(kontext):
        return tuple(
            f"{karte['title']} — {karte['text']}" for karte in _VIER_URSACHEN
        )
    return tuple(sauber[:8])


def uebersichtskarten(abschnitt: str) -> list[dict[str, str]]:
    """Liefert wenige lesbare Orientierungskarten statt eines Textauszugs.

    Jede Aussage erscheint hoechstens einmal. Das beseitigt die bisherige
    Wirkung einer blossen, teilweise doppelten Mitschrift und eignet sich
    zugleich fuer eine responsive Lehrtafel neben einem echten Foto.
    """

    fachstruktur = strukturkarten(abschnitt)
    if fachstruktur:
        return fachstruktur[:5]

    sauber = " ".join(str(abschnitt or "").split())

    # Zeitleiste und Gegenueberstellung stehen VOR den Dimensionskarten:
    # Wo der Abschnitt selbst eine Ordnung mitbringt, ist sie besser als
    # jede, die nachtraeglich darueber gelegt wird.
    roh_saetze = [satz for satz in _saetze(sauber) if len(satz.strip()) >= 20]
    zeitpunkte = _zeitpunkte(roh_saetze)
    if len(zeitpunkte) >= 3:
        return [
            {"title": beschriftung.strip(" ."), "text": _grafikpunkt(satz)}
            for _, beschriftung, satz in zeitpunkte[:5]
        ]

    paar = _gegenueberstellung(roh_saetze)
    if paar is not None:
        erster, zweiter = paar
        karten: list[dict[str, str]] = []
        for name in (erster, zweiter):
            andere = zweiter if name == erster else erster
            eigene = [
                satz for satz in roh_saetze if name in satz and andere not in satz
            ]
            if eigene:
                karten.append(
                    {"title": name, "text": _grafikpunkt(max(eigene, key=len))}
                )
        gemeinsam = [
            satz for satz in roh_saetze if erster in satz and zweiter in satz
        ]
        if gemeinsam and len(karten) == 2:
            karten.append(
                {
                    "title": "Der Streitpunkt",
                    "text": _grafikpunkt(max(gemeinsam, key=len)),
                }
            )
        if len(karten) >= 2:
            return karten[:3]

    alle = [
        _grafikpunkt(satz) for satz in _saetze(sauber) if len(satz.strip()) >= 28
    ]
    alle = list(dict.fromkeys(satz for satz in alle if satz))
    if not alle:
        alle = [_grafikpunkt(sauber) or "Die wichtigsten Zusammenhaenge im Ueberblick."]

    dimensionen = _passende_dimensionen(alle)

    kern = next((satz for satz in alle if not satz.rstrip().endswith("?")), alle[0])
    verwendet: set[str] = {kern}
    karten: list[dict[str, str]] = [{"title": "Leitidee", "text": kern}]
    for titel, muster, mindestens in dimensionen:
        gefunden = _bester_kategoriesatz(alle, muster, verwendet, mindestens)
        if gefunden is None:
            continue
        verwendet.add(gefunden)
        karten.append({"title": titel, "text": gefunden})
        if len(karten) >= 5:
            break

    return karten[:5]
    return karten[:5]


def infografik_uebersicht(abschnitt: str) -> str:
    """Formt den gesprochenen Abschnitt in eine kategorisierte Konzeptkarte.

    Es werden nicht mehr beliebige Saetze gleichwertig aufgelistet. Ein
    zentraler Zusammenhang wird von fachlichen Dimensionen umgeben, die im
    Abschnitt wirklich belegt sind: Zeit, Raum/Akteure, Prozess, Quellen und
    Bedeutung. Fehlende Dimensionen bleiben weg, statt mit einem zufaelligen
    "Kernpunkt" aufgefuellt zu werden.
    """

    return "\n\n".join(
        f"## {karte['title']}\n{karte['text']}"
        for karte in uebersichtskarten(abschnitt)
    )


def _ist_konkret(thema: str) -> bool:
    woerter = _woerter(thema)
    return bool(woerter) and not all(wort in _ABSTRAKTE_THEMEN for wort in woerter)


def _woerter(text: str, *, auch_unspezifisch: bool = False) -> set[str]:
    schlicht = (
        str(text or "")
        .casefold()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    ergebnis = {
        wort
        for wort in re.findall(r"[a-z]{4,}", schlicht)
        if auch_unspezifisch or wort not in _UNSPEZIFISCH
    }
    return ergebnis


def _bildwortformen(woerter: set[str]) -> set[str]:
    formen = set(woerter)
    for wort in woerter:
        for stamm, bruecken in _BILDWORT_BRUECKEN:
            if wort.startswith(stamm):
                formen.update(bruecken)
    return formen


def _gleicher_wortstamm(links: str, rechts: str) -> bool:
    """Konservativer Stammvergleich fuer gebeugte/uebersetzte Bildtitel."""

    if links == rechts:
        return True
    kuerzer = min(len(links), len(rechts))
    if kuerzer < 5:
        return False
    gemeinsam = 0
    for a, b in zip(links, rechts):
        if a != b:
            break
        gemeinsam += 1
    # Der kuerzere Ausdruck muss fast vollstaendig derselbe Stamm sein.
    return gemeinsam >= 5 and gemeinsam / kuerzer >= 0.75


#: Abkuerzungen, nach denen KEIN neuer Satz beginnt.
#:
#: Der Punkt hinter "v." in "um 3000 v. Chr. entstehen die ersten
#: Stadtstaaten" ist kein Satzende. Die Tafel hat dort trotzdem getrennt -
#: und weil die vordere Haelfte zu kurz war, um als Karte zu zaehlen, blieb
#: "Chr. entstehen in Mesopotamien die ersten Stadtstaaten" uebrig. Auf
#: einer Tafel steht dann ein Bruchstueck, das mit einer Abkuerzung
#: anfaengt. In einer Geschichtsvorlesung ist das kein Sonderfall, sondern
#: der Normalfall.
_ABKUERZUNGEN: frozenset[str] = frozenset(
    {
        "v", "n", "chr", "jh", "jhd", "ca", "bzw", "usw", "usf", "etc",
        "z", "b", "d", "h", "u", "a", "s", "vgl", "ebd", "nr", "bd",
        "hrsg", "sog", "ggf", "evtl", "inkl", "exkl", "max", "min",
        "st", "hl", "dr", "prof", "abb", "tab", "kap",
    }
)


def _saetze(text: str) -> list[str]:
    """Zerlegt in Saetze - ohne an Abkuerzungen zu zerbrechen.

    Die Regel ist eine einzige: Endet das bisher Gesammelte auf eine
    bekannte Abkuerzung oder eine Initiale, war der Punkt kein Satzende -
    dann gehoert das naechste Stueck noch dazu.
    """

    def _endet_auf_abkuerzung(stueck: str) -> bool:
        # Eine Ordnungszahl am Ende ist nie ein Satzende: "Im 6." gehoert
        # zu "Jahrhundert v. Chr.". Ohne diesen Fall zerfiel jede
        # Jahrhundertangabe in zwei Bruchstuecke, und das erste war zu
        # kurz, um noch als Karte zu zaehlen.
        if re.search(r"\b\d{1,4}\.$", stueck):
            return True
        wort = re.search(r"([A-Za-zÄÖÜäöüß]+)\.$", stueck)
        if wort is None:
            return False
        return wort.group(1).casefold() in _ABKUERZUNGEN or len(wort.group(1)) == 1

    saetze: list[str] = []
    for teil in re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split())):
        if saetze and _endet_auf_abkuerzung(saetze[-1]):
            saetze[-1] = f"{saetze[-1]} {teil}"
            continue
        saetze.append(teil)
    return saetze


def _grafikpunkt(text: str) -> str:
    punkt = " ".join(str(text or "").split()).strip(" -–—")
    punkt = re.sub(
        r"^(?:gut|also),?\s+(?:ich\s+)?(?:fahre\s+fort|mache\s+weiter)\.?\s*",
        "",
        punkt,
        flags=re.IGNORECASE,
    )
    punkt = re.sub(
        r"^(?:nur ein\s+)?kurzer\s+(?:einwurf|exkurs|hinweis)[^:]*:\s*",
        "",
        punkt,
        flags=re.IGNORECASE,
    )
    punkt = _zahlen_als_ziffern(punkt)
    # 210 Zeichen ergeben im 3x2-Kartenraster hoechstens sechs Textzeilen.
    # textwrap markiert eine Kuerzung sichtbar, statt den Satz am Kartenrand
    # ploetzlich abzuschneiden.
    punkt = textwrap.shorten(punkt, width=210, placeholder=" …")
    if punkt and punkt[-1] not in ".!?…":
        punkt += "."
    return punkt


#: Die Ueberschriften, unter denen die Lehrtafel etwas zeigen kann.
#:
#: Der Anlass fuer diese Liste: Bis zum 26.08.2026 standen hier fuenf FESTE
#: Kategorien - "Zeit & Ausgangslage", "Akteure & Raum", "Beleg &
#: Quellenlage" und so fort. Sie waren an einer Vorlesung ueber Mesopotamien
#: abgenommen, und fuer die passten sie. Nur galten sie danach fuer JEDE
#: Vorlesung. In einem Abschnitt ueber Platon und Aristoteles trifft
#: "Akteure & Raum" auf nichts - ausser zufaellig, denn das alte Muster
#: enthielt ``ur\b`` und ``\b\d{3,4}\b``, also jede Zahl und jedes Wort,
#: das mit "ur" beginnt. Die Tafel setzte daraufhin einen beliebigen Satz
#: unter eine Ueberschrift, die etwas ganz anderes versprach. Genau das hat
#: der Benutzer als "komische Sachen" beschrieben, und er hatte recht: Eine
#: falsch beschriftete Karte ist schlimmer als keine Karte.
#:
#: Jetzt waehlt der INHALT die Ueberschriften und nicht umgekehrt. Der
#: Katalog deckt mehrere Faecher ab; welche Dimensionen erscheinen, ergibt
#: sich daraus, was im Abschnitt wirklich belegt ist. Eine Vorlesung ueber
#: Philosophie bekommt "Begriff & Unterscheidung" und "These & Einwand",
#: eine ueber Geschichte "Zeit & Ausgangslage" und "Quellen & Belege" -
#: ohne dass irgendwo ein Fach erkannt werden muesste.
#:
#: Die dritte Zahl ist die Mindestpunktzahl. Sie ist der eigentliche Schutz:
#: Ein einzelner zufaelliger Treffer erzeugt keine Karte mehr. Enge, kaum
#: verwechselbare Muster duerfen mit 1 auskommen, weite brauchen 2.
_DIMENSIONEN: tuple[tuple[str, tuple[str, ...], int], ...] = (
    # --- Geschichtliche Abschnitte --------------------------------------
    (
        "Zeit & Ausgangslage",
        (
            r"\b\d{1,4}\s*(?:v\.?\s*chr|n\.?\s*chr|vor christus|nach christus)",
            r"\b(?:jahrhundert|jahrtausend|epoche|zeitrechnung|antike|"
            r"mittelalter|neuzeit|spaetantike|spätantike)\w*",
        ),
        1,
    ),
    (
        "Akteure & Raum",
        (
            r"\b(?:koenig|könig|kaiser|herrscher|dynastie|reich|provinz|"
            r"stadtstaat|kloster|bischof|papst|feldherr)\w*",
            r"\b(?:mesopotamien|sumer|uruk|babylon|athen|sparta|rom|byzanz|"
            r"aegypten|ägypten)\w*",
        ),
        1,
    ),
    (
        "Quellen & Belege",
        (
            r"\b(?:quelle|quellen|ueberlieferung|überlieferung|inschrift|"
            r"handschrift|urkunde|chronik|ausgrabung|fundstueck|fundstück|"
            r"keilschrift|papyrus)\w*",
            # Der Gegenstand, an dem der Beleg haengt, zaehlt genauso wie
            # das Wort "Quelle" selbst: "Erhaltene Tontafeln liefern
            # konkrete Belege" ist eine Aussage ueber die Quellenlage.
            r"\b(?:beleg|befund|zeugnis|artefakt|nachweis|tontafel|"
            r"tonscherbe|siegel)\w*",
        ),
        1,
    ),
    # --- Philosophische und theoretische Abschnitte ----------------------
    (
        "Begriff & Unterscheidung",
        (
            r"\b(?:unterscheid|abgrenz|definier|bezeichnet|versteht man|"
            r"meint damit|begriff)\w*",
            r"\bim unterschied zu\b",
            r"\bnicht zu verwechseln\b",
        ),
        2,
    ),
    (
        "These & Einwand",
        (
            r"\b(?:these|behauptet|bestreitet|widerspricht|einwand|kritisiert|"
            r"entgegnet|wendet ein)\w*",
            r"\bdagegen (?:spricht|steht)\b",
        ),
        2,
    ),
    (
        "Begruendung",
        (
            r"\b(?:begruend|begründ|argument|folgt daraus|setzt voraus|"
            r"schliesst|schließt)\w*",
            r"\b(?:weil|denn|daher|deshalb|folglich|somit)\b",
        ),
        2,
    ),
    (
        "Beispiel",
        (
            r"\b(?:zum beispiel|beispielsweise|etwa wenn|man denke|"
            r"angenommen|stellen wir uns)\b",
        ),
        1,
    ),
    # --- Fachuebergreifend ------------------------------------------------
    (
        "Wirkung & Nachleben",
        (
            r"\b(?:wirkung|nachwirk|nachleben|einfluss|rezeption|praegte|"
            r"prägte|bis heute|seither)\w*",
            # Wortwahl, die eine bleibende Folge anzeigt, ohne "Wirkung" zu
            # sagen: "Diese Schrift veraenderte Herrschaft dauerhaft."
            r"\b(?:dauerhaft|nachhaltig|folgenreich|weitreichend|"
            r"von da an)\w*",
        ),
        # Mindestens 1: Diese Woerter sind eng genug, dass ein einzelner
        # Treffer schon eine Aussage ueber die Folge ist. Bei den weiten
        # Dimensionen ("Begruendung" faengt jedes "weil") bleibt es bei 2.
        1,
    ),
    (
        "Streitstand",
        (
            r"\b(?:umstritten|streit|kontrovers|uneinig|debatte|"
            r"forschungsstand)\w*",
        ),
        2,
    ),
)


def _passende_dimensionen(
    saetze: list[str],
) -> list[tuple[str, tuple[str, ...], int]]:
    """Waehlt die Dimensionen aus, die im Abschnitt wirklich vorkommen.

    Sortiert nach Belegdichte: Was am haeufigsten belegt ist, steht oben.
    Was seine Mindestpunktzahl nicht erreicht, kommt gar nicht vor - lieber
    zwei richtige Karten als fuenf, von denen drei etwas Falsches
    versprechen.
    """

    bewertet: list[tuple[int, int, tuple[str, tuple[str, ...], int]]] = []
    for rang, (titel, muster, mindestens) in enumerate(_DIMENSIONEN):
        punkte = sum(
            len(re.findall(regel, satz.casefold()))
            for satz in saetze
            for regel in muster
        )
        if punkte >= mindestens:
            # Der Rang haelt bei Gleichstand die Reihenfolge des Katalogs -
            # sonst wechselte die Tafel ihre Gliederung von Abschnitt zu
            # Abschnitt, ohne dass sich der Inhalt geaendert haette.
            bewertet.append((punkte, -rang, (titel, muster, mindestens)))
    bewertet.sort(key=lambda eintrag: (eintrag[0], eintrag[1]), reverse=True)
    return [eintrag[2] for eintrag in bewertet]


def _bester_kategoriesatz(
    saetze: list[str],
    muster: tuple[str, ...],
    verwendet: set[str],
    mindestens: int = 1,
) -> str | None:
    kandidaten: list[tuple[int, str]] = []
    for satz in saetze:
        if satz in verwendet:
            continue
        treffer = sum(len(re.findall(regel, satz.casefold())) for regel in muster)
        # Die Mindestpunktzahl gilt auch fuer den EINZELNEN Satz. Sonst
        # koennte eine Dimension, die im Abschnitt insgesamt gut belegt ist,
        # ihre Karte mit einem Satz fuellen, in dem nur ein Streiftreffer
        # steht - und die Ueberschrift laege wieder daneben.
        if treffer < mindestens:
            continue
        # Mehr klare Signale gewinnen; bei Gleichstand ist ein kompakter
        # Satz uebersichtlicher als ein langer Vortragsabsatz.
        kandidaten.append((treffer * 100 - abs(len(satz) - 125), satz))
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda eintrag: eintrag[0])[1]


@lru_cache(maxsize=1)
def _zahlwort_tabelle() -> dict[str, str]:
    # Dieselben Formen rueckwaerts lesen, die die TTS-Schicht fuer eine
    # natuerliche Aussprache erzeugt. So bleiben Audio und Grafik konsistent.
    from backend.tts.german_text import jahreszahl_in_worten, zahl_in_worten

    tabelle: dict[str, str] = {"hundert": "100", "tausend": "1000"}
    for zahl in range(10_000):
        tabelle[zahl_in_worten(zahl).casefold()] = str(zahl)
        tabelle[jahreszahl_in_worten(zahl).casefold()] = str(zahl)
    tabelle.update(
        {
            "erste": "1.", "ersten": "1.", "erstes": "1.",
            "zweite": "2.", "zweiten": "2.", "zweites": "2.",
            "dritte": "3.", "dritten": "3.", "drittes": "3.",
            "vierte": "4.", "vierten": "4.", "viertes": "4.",
            "fünfte": "5.", "fünften": "5.", "fünftes": "5.",
        }
    )
    return tabelle


def _zahlen_als_ziffern(text: str) -> str:
    tabelle = _zahlwort_tabelle()

    def ersetzen(treffer: re.Match[str]) -> str:
        return tabelle.get(treffer.group(0).casefold(), treffer.group(0))

    ergebnis = re.sub(r"\b[A-Za-zÄÖÜäöüß]+\b", ersetzen, str(text or ""))
    ergebnis = re.sub(
        r"\bvor unserer Zeitrechnung\b", "v. u. Z.", ergebnis, flags=re.IGNORECASE
    )
    ergebnis = re.sub(r"\bvor Christus\b", "v. Chr.", ergebnis, flags=re.IGNORECASE)
    return re.sub(r"\bnach Christus\b", "n. Chr.", ergebnis, flags=re.IGNORECASE)


def _kuerzen(text: str, laenge: int) -> str:
    sauber = " ".join(str(text or "").split()).strip(" -–—.,:;!?")
    if len(sauber) <= laenge:
        return sauber
    return sauber[:laenge].rsplit(" ", 1)[0].strip()
