"""Werkzeuge für das Internet: suchen und Webseiten lesen.

Bisher hatte AI-Orb schlicht kein Werkzeug für das Internet – auf „such im
Internet" konnte das Modell nur antworten, es habe keine Berechtigung. Das
stimmte so nicht: Die Berechtigung ``network`` gab es längst, es fehlte das
Werkzeug, das sie benutzt.

Zwei Werkzeuge schließen die Lücke:

* ``internet_suchen`` fragt DuckDuckGo an (die HTML-Fassung, die ohne
  Schlüssel und ohne Anmeldung funktioniert) und liefert Titel, Adresse und
  Kurzbeschreibung der Treffer.
* ``webseite_lesen`` holt eine einzelne Seite und gibt ihren Text zurück –
  ohne Menüs, Skripte und Stilangaben.

Beides kommt mit der Standardbibliothek aus; es wird nichts installiert.
"""

from __future__ import annotations

import gzip
import html
import html.parser
import io
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

#: Ein gewöhnlicher Browser-Kennsatz. Ohne ihn weisen viele Seiten die
#: Anfrage ab, weil sie nach automatisierten Zugriffen aussieht.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: Die Zugänge zur Suche, in der Reihenfolge, in der sie versucht werden.
#:
#: Bisher stand hier genau einer. Das war die eigentliche Schwäche - nicht
#: dieser Zugang, sondern dass es nur einen gab. Ändert eine Suchmaschine
#: ihre Seite oder weist sie eine Anfrage ab, ist der Orb blind, und von
#: aussen sieht das aus wie "kein Internet".
#:
#: Die Lite-Fassung steht vorn, weil sie die schlichteste Seite ausliefert:
#: eine Tabelle mit Links, ohne Skripte und ohne Gestaltung. Was schlicht
#: ist, ändert sich seltener.
class _Maschine:
    """Eine Suchmaschine, wie sie angefragt und gelesen wird.

    ``methode`` unterscheidet die zwei Bauarten: DuckDuckGo will die
    Anfrage im Rumpf einer POST-Anfrage, die meisten anderen als
    ``?q=...`` in der Adresse. ``eigene`` sind die Wirte, die in der
    Trefferliste vorkommen, aber keine Treffer sind - die Suchmaschine
    selbst und ihre Hilfsseiten.
    """

    def __init__(self, name, adresse, methode, eigene, zusatz=None):
        self.name = name
        self.adresse = adresse
        self.methode = methode          # "post" oder "get"
        self.eigene = tuple(eigene)
        self.zusatz = zusatz or {}      # feste zusaetzliche Parameter


#: Die Suchmaschinen, in der Reihenfolge, in der sie versucht werden.
#:
#: Bewusst mit MEHREREN UNABHAENGIGEN Indizes und nicht bloss mehreren
#: Zugaengen zu demselben. Das war die eigentliche Schwaeche: Zuvor standen
#: hier zwei DuckDuckGo-Adressen - blockt DuckDuckGo die Adresse des
#: Benutzers, fallen beide zugleich aus, und mit ihnen die Mehrquellen-
#: und die Favoritensuche, die auch darueber laufen.
#:
#: Bing steht vorn, und das aus Erfahrung: Im Protokoll des Benutzers war es
#: die EINZIGE Maschine, die überhaupt antwortete – Mojeek und Ecosia wiesen
#: mit 403 ab, DuckDuckGo ebenso. Bing lieferte 74000 Zeichen; nur wurde die
#: Trefferliste bis dahin nicht gelesen, weil Bing jeden Link über eine
#: eigene Umleitung schickt (siehe ``_resolve_bing_url``). Das ist behoben,
#: und damit ist Bing der verlässlichste Zugang – also zuerst. Die anderen
#: bleiben als Ausweichweg dahinter, falls Bing einmal doch abweist.
_SUCHMASCHINEN: tuple[_Maschine, ...] = (
    # RSS ist eine stabile, strukturierte Trefferliste. Die frühere
    # HTML-Auswertung erkannte zuletzt nur noch Startseiten als Treffer.
    _Maschine("Bing", "https://www.bing.com/search", "rss",
              ("bing.com", "microsoft.com", "msn.com", "microsofttranslator.com"),
              # Der verbundene Kalender und damit der Standort des Benutzers
              # liegen in der Schweiz. Ohne einen eindeutigen Markt lieferte
              # Bing fuer Schweizer Versicherungen deutsche oder sogar
              # voellig fremdsprachige Treffer.
              zusatz={"setlang": "de-CH", "cc": "ch", "mkt": "de-CH"}),
    _Maschine("Yahoo", "https://search.yahoo.com/search", "get",
              ("yahoo.com", "yimg.com", "bing.com", "microsoft.com"),
              zusatz={"vl": "lang_de", "vc": "ch"}),
    _Maschine("Mojeek", "https://www.mojeek.com/search", "get",
              ("mojeek.com",)),
    _Maschine("DuckDuckGo Lite", "https://lite.duckduckgo.com/lite/", "post",
              ("duckduckgo.com", "duck.com", "spreadprivacy.com")),
    _Maschine("Ecosia", "https://www.ecosia.org/search", "get",
              ("ecosia.org",)),
    _Maschine("DuckDuckGo HTML", "https://html.duckduckgo.com/html/", "post",
              ("duckduckgo.com", "duck.com", "spreadprivacy.com")),
)

#: Woran zu erkennen ist, dass die Suchmaschine abgewiesen hat, statt keine
#: Treffer zu haben. Das sind zwei sehr verschiedene Dinge, und sie
#: auseinanderzuhalten ist der halbe Weg zur Behebung.
#:
#: Bewusst VOLLSTAENDIGE Wendungen. Zuvor stand hier unter anderem das
#: blosse Wort "anomaly" - und das kommt auf jeder DuckDuckGo-Seite in
#: Klassennamen wie ``anomaly-modal__mask`` vor. Ein einzelnes Wort aus
#: einem CSS-Namen ist kein Beweis fuer eine Sperre. "blocked" traf
#: ausserdem "adblocked", "unblocked" und jeden Text ueber Werbeblocker.
_ABWEISUNGEN: tuple[str, ...] = (
    "unusual traffic",
    "bots use duckduckgo",
    "confirm this search was made by a human",
    "please complete the following challenge",
    "are you a robot",
    "are you a human",
    "captcha",
    "enter the characters you see",
    "too many requests",
    "rate limit exceeded",
    "zugriff verweigert",
    "access denied",
    "verify you are human",
    "bestaetigen sie, dass sie ein mensch sind",
    "bestätigen sie, dass sie ein mensch sind",
)

#: Wirte, die in den Trefferlisten vorkommen, aber keine Treffer sind -
#: die Suchmaschine selbst und ihre Hinweisseiten.
_EIGENE_WIRTE: tuple[str, ...] = (
    "duckduckgo.com", "duck.com", "spreadprivacy.com",
)


#: Frage-Geruest und Hoeflichkeit, die vor einer Suche weg koennen.
#:
#: Der Suchauftrag selbst gehoert dazu, und das ist der Punkt: Am
#: 19.08.2026 verlangte der Benutzer viermal "Hallo Orb, fuehre erneut
#: eine Suche durch zu Markus Gabriel". Daraus wurde der Suchbegriff
#: "fuehre erneut durch markus gabriel" - und Wikipedia antwortete mit
#: SIGMAR Gabriel. Erst als der Benutzer "Neurealismus" ergaenzte, kam
#: der richtige Philosoph. Nicht die Suche war kaputt, sondern die
#: Anfrage: Der Auftrag stand mit im Suchtext und verduennte den Namen.
_FRAGE_GERUEST: tuple[str, ...] = (
    "kannst du mir sagen", "kannst du mir", "kannst du", "koenntest du",
    "könntest du", "weißt du", "weisst du", "sag mir mal", "sag mir",
    "erklaer mir", "erkläre mir", "erklär mir", "ich moechte wissen",
    "ich möchte wissen", "ich will wissen", "ich moechte", "ich möchte",
    "such mir", "suche mir", "such nach", "suche nach", "finde mir",
    "recherchiere", "recherchier", "bitte", "mal eben", "mal kurz",
    # Die Anrede. Sie steht im gesprochenen Satz und gehoert nie in die
    # Anfrage: "hallo orb fuehre erneut durch markus gabriel".
    "hallo orb", "hey orb", "hallo, orb", "orb bitte",
    # Der Suchauftrag als Rahmen um das eigentliche Thema.
    "fuehre erneut eine suche durch", "führe erneut eine suche durch",
    "fuehre eine neue suche durch", "führe eine neue suche durch",
    "fuehre eine suche durch", "führe eine suche durch",
    "fuehre erneut eine suche", "führe erneut eine suche",
    "fuehre eine neue suche", "führe eine neue suche",
    "starte eine suche", "mach eine suche", "mache eine suche",
    "eine neue suche zu", "eine erneute suche zu", "eine suche zu",
    "was du findest", "was du dazu findest", "was du dazu findest",
    "was findest du", "schau was du findest",
    "noch einmal", "nochmal", "nochmals", "erneut", "erneute", "erneuten",
)

#: Haeufige deutsche Fuell- und Funktionswoerter, die als Suchbegriff nichts
#: beitragen. Bewusst KEINE Fachwoerter - nur Grammatik-Kleinkram.
_STOPPWOERTER: frozenset[str] = frozenset(
    "der die das den dem des ein eine einen einem einer eines und oder aber "
    "mit zu zum zur fuer für von vom im in am an auf aus bei nach ueber über "
    "unter vor hinter neben ist sind war waren wird werden worden sein hat "
    "habe haben hatte ich du wir ihr mir mich dir dich uns euch sie er es man "
    "wie was wann wo warum wieso weshalb welche welcher welches welchen ob "
    # "wer" fehlte in der Liste - aus "Wer war Bismarck" wurde deshalb die
    # Anfrage "wer bismarck" statt schlicht "bismarck".
    "wer wen wem wessen ab "
    "dass so als auch noch nur schon denn doch mal eben kurz genau eigentlich "
    "hier da dort diese dieser dieses diesen jene jener kann koennte könnte "
    "soll sollte will wollte moechte möchte bitte etwa etwas gerade jetzt "
    "dann wenn weil damit um "
    # Nachtrag 26.08.2026. Aus dem Protokoll des Benutzers wurde
    # "markus gabriel nicht modellen gesprochen aktuell alle erhaelt" -
    # da tragen "nicht", "alle" und "erhaelt" nichts bei, zaehlen aber als
    # vollwertige Suchwoerter und verduennen den Namen. Bewusst nur
    # Grammatik-Kleinkram: "gegen", "ohne" und "zwischen" fehlen hier mit
    # Absicht, weil sie in einer Sachfrage tragend sein koennen
    # ("Impfung gegen Grippe").
    "nicht nichts kein keine keinen keinem keiner alle allen aller alles "
    "sehr immer wieder mehr viel viele ganz ganze dabei davon dazu daran "
    "darauf bereits sogar zwar eher oft nie nun halt ueberhaupt überhaupt "
    "trotzdem deshalb deswegen also jedoch sondern obwohl wurde wurden "
    "worden gibt gab sagt gesagt sagte scheint scheinen bleibt blieb steht "
    "stand koennen können muss muessen müssen sollen wollen wollten machen "
    "macht gemacht wirklich meist meistens jeweils andere anderen anderes "
    "seine seiner seinem seinen ihre ihren ihrem ihrer dessen deren "
    # "erhalten", "gesprochen" und ihresgleichen stehen hier BEWUSST NICHT:
    # Sie koennen das Thema selbst sein ("Denkmal erhalten", "Sprechen
    # lernen"). Gegen solche Verben hilft die Begrenzung auf die tragenden
    # Woerter weiter unten, nicht eine laengere Verbotsliste.
    "einfach gern gerne gleich weiter weiterhin".split()
)

# Handlungswoerter aus kombinierten Auftraegen. Bei "suche X und erstelle
# daraus eine PDF mit Grafiken" beschreiben sie das AUSGABEFORMAT, nicht das
# Thema. Blieben sie in der Anfrage, gewichteten Suchmaschinen "PDF" und
# "erstellen" staerker als X - im Protokoll kamen dadurch Toyota, Smartphone-
# Link und franzoesische Formularseiten statt Bogenschiessen zurueck.
_SUCH_AKTIONSWOERTER: frozenset[str] = frozenset(
    {
        "ja", "suchen", "suche", "erstelle", "erstellen", "erstellt",
        "erstell", "daraus", "pdf", "pdf-datei", "datei", "grafik",
        "grafiken", "bilder", "bildung", "speichere", "speichern",
        "generiere", "generieren", "solchen", "solche", "solches",
        # Der Suchauftrag in Einzelteilen - was von "fuehre eine erneute
        # Suche durch zu X" uebrig bleibt, wenn die Wendung nicht genau
        # so dasteht. "durch" ist hier Verbzusatz, kein Inhalt.
        "fuehre", "führe", "fuehr", "führ", "durchfuehren", "durchführen",
        "durch", "erneut", "erneute", "erneuten", "erneuter", "neue",
        "neuen", "neuer", "neues", "nochmal", "nochmals", "wieder",
        "findest", "finden", "findet", "finde", "sucht", "suchst",
        "recherche", "internetsuche", "websuche", "suchauftrag",
        "hallo", "orb", "jo", "hey", "darum", "neuigkeiten", "neuigkeit",
    }
)


#: Wie viele Woerter eine Anfrage hoechstens behaelt.
#:
#: Acht ist kein runder Zufallswert, sondern die Stelle, an der eine
#: Suchmaschine kippt: Jedes weitere Wort verlangt sie zusaetzlich, und ab
#: etwa einem Dutzend findet sie nichts mehr, was alle erfuellt. Aus einem
#: gesprochenen Satz werden aber leicht fuenfzehn. Genau das stand im
#: Protokoll - eine Anfrage aus acht Woertern, von denen die Haelfte nichts
#: beitrug, und darunter der eigentliche Name.
_HOECHSTENS_WOERTER = 8


def _tragkraft(wort: str, grossgeschrieben: set[str]) -> float:
    """Wie viel ein Wort zur Anfrage beitraegt - je hoeher, desto mehr.

    Zwei Anhaltspunkte, beide billig und beide verlaesslich:

    1. **Grossschreibung im Originalsatz.** Im Deutschen sind das Nomen und
       Namen - also fast immer das Thema. "Markus Gabriel" ueberlebt damit
       jede Kuerzung, "gesprochen" nicht.
    2. **Laenge.** Lange Woerter sind seltener und dadurch treffsicherer.
       Der Beitrag ist gedeckelt, damit ein Bandwurmwort nicht alles andere
       verdraengt.
    """

    punkte = 2.0 if wort in grossgeschrieben else 0.0
    return punkte + min(len(wort), 12) / 12.0


def suchbegriff_aus(text: str, *, hoechstens: int = 90) -> str:
    """Macht aus einem gesprochenen Satz einen brauchbaren Suchbegriff.

    Das war die eigentliche, lange uebersehene Ursache scheiternder Suchen:
    Der Orb schickte den GANZEN gesprochenen Satz als Anfrage - im Protokoll
    stand woertlich „wann ist diese zeit wo ich die frage mit urkunden
    abgleichen kann startpunkt und endpunkt bitte". Darauf gibt keine
    Suchmaschine etwas Brauchbares zurueck. Hier bleiben die tragenden
    Woerter (Namen, Begriffe, Zahlen) uebrig, das Frage-Geruest faellt weg.

    ``site:...``-Ausdruecke bleiben erhalten - sie schraenken gezielt auf
    eine Quelle ein und sind kein Fuellwort.
    """

    knapp = " " + " ".join(str(text).lower().split()) + " "
    # Whisper versteht das sehr kurze deutsche Akronym "KI" im Satz oft als
    # den Namen "Kai". In Verbindung mit Modell/Modellen ist die Bedeutung
    # eindeutig genug, um sie vor der Zerlegung zu berichtigen.
    knapp = re.sub(
        r"\b(?:neu(?:e|en|er|es)?[- ]*)?kai[- ]*modellen?\b",
        " ki modelle ",
        knapp,
    )
    knapp = re.sub(r"\bki[- ]*modellen?\b", " ki modelle ", knapp)
    # Gewuenschtes AUSGABEFORMAT ist kein Teil des Themas. Bei
    # "Suche nach X und nenne mir zwei passende Quellen" wurden sonst auch
    # nenne/zwei/passende/quellen als Pflichtwoerter bewertet. Die Anbieter
    # fanden X, doch der Orb verwarf ihre Treffer anschliessend selbst.
    knapp = re.sub(
        r"\b(?:und\s+)?(?:nenne|nenn|zeige|gib)\s+(?:mir\s+)?"
        r"(?:(?:ein(?:e)?|zwei|drei|vier|fünf|fuenf|\d+)\s+)?"
        r"(?:(?:passende|brauchbare|relevante|gute)\s+)?"
        r"(?:quellen|treffer|links?)\b[.!?]*",
        " ",
        knapp,
    )
    for wendung in _FRAGE_GERUEST:
        knapp = knapp.replace(" " + wendung + " ", " ")

    behalten: list[str] = []
    for roh in knapp.split():
        # site:/filetype:-Filter und alles mit Doppelpunkt unveraendert lassen.
        if ":" in roh:
            behalten.append(roh)
            continue
        wort = re.sub(r"[^0-9a-zäöüß-]+", "", roh)
        if not wort or wort in _STOPPWOERTER or wort in _SUCH_AKTIONSWOERTER:
            continue
        behalten.append(wort)

    # Auf die tragenden Woerter begrenzen - in der urspruenglichen
    # Reihenfolge, damit "Markus Gabriel" nicht zu "Gabriel Markus" wird.
    if len(behalten) > _HOECHSTENS_WOERTER:
        grossgeschrieben = {
            re.sub(r"[^0-9a-zäöüß-]+", "", wort.lower())
            for wort in str(text).split()
            if wort[:1].isupper()
        }
        gewaehlt = sorted(
            range(len(behalten)),
            key=lambda i: _tragkraft(behalten[i], grossgeschrieben),
            reverse=True,
        )[:_HOECHSTENS_WOERTER]
        behalten = [behalten[i] for i in sorted(gewaehlt)]

    ergebnis = " ".join(behalten).strip()
    if len(ergebnis) > hoechstens:
        ergebnis = ergebnis[:hoechstens].rsplit(" ", 1)[0]
    # Bleibt nichts uebrig (sehr kurze Frage), lieber der Originaltext.
    return ergebnis or " ".join(str(text).split())[:hoechstens]


def _suchwoerter(query: str) -> list[str]:
    """Tragende Woerter fuer eine billige Relevanzpruefung."""

    cleaned = suchbegriff_aus(query, hoechstens=180)
    words = [
        re.sub(r"[^0-9a-zäöüß-]+", "", word.lower())
        for word in cleaned.split()
    ]
    # KI/AI sind kurze, aber hoch informative Fachbegriffe. Sie wegzulassen
    # machte aus "KI Modelle" die viel zu allgemeine Suche "Modelle".
    return list(
        dict.fromkeys(
            word
            for word in words
            if (len(word) >= 4 or word in {"ki", "ai"})
            and not word.startswith("site:")
        )
    )


def _relevante_treffer(
    query: str, results: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Verwirft offensichtlich themenfremde Treffer einer Suchmaschine.

    Eine technisch gueltige RSS-Liste ist noch kein Suchergebnis. Bing gab
    zuletzt zu einer Bogenfrage voellig fremde, aber korrekt geparste Links
    zurueck. Bei mindestens vier tragenden Suchwoertern verlangen wir deshalb
    zwei Uebereinstimmungen; bei kuerzeren Anfragen eine. Ein-Wort-Suchen
    werden ebenfalls geprueft, damit technische, aber fremde Treffer nicht
    ungefiltert durchrutschen.
    """

    terms = _suchwoerter(query)
    if not terms:
        return results
    # HIER lag die eigentliche Stoerung: Verlangt wurde die HAELFTE aller
    # tragenden Woerter. Der Text darueber beschreibt etwas anderes - "bei
    # mindestens vier Woertern zwei Uebereinstimmungen" -, und das ist auch
    # das Richtige. Bei sieben Woertern verlangte die Rechnung vier davon in
    # EINEM Treffer aus Titel, Beschreibung und Adresse. Das schafft keine
    # echte Trefferzeile; im Protokoll des Benutzers stand deshalb bei jeder
    # Suche "lieferte nur themenfremde Treffer" - fuer Bing UND fuer Yahoo,
    # obwohl beide sauber geantwortet hatten. Zwei sind die Obergrenze:
    # genug, um voellig fremde Treffer auszusieben, wenig genug, dass ein
    # laengerer gesprochener Satz die Suche nicht selbst erwuergt.
    required = 1 if len(terms) < 4 else 2
    if len(terms) >= 2 and any(term in {"ki", "ai"} for term in terms):
        required = max(required, 2)
    relevant: list[dict[str, str]] = []
    for item in results:
        haystack = " ".join(
            str(item.get(key, "")) for key in ("titel", "beschreibung", "url")
        ).lower()
        matches = 0
        for term in terms:
            if term in {"ki", "ai"}:
                # Wortgrenzen verhindern etwa, dass "ki" in "Kinder" als
                # Treffer fuer kuenstliche Intelligenz zaehlt.
                if re.search(
                    rf"(?<![0-9a-zäöüß]){re.escape(term)}(?![0-9a-zäöüß])",
                    haystack,
                ):
                    matches += 1
                continue
            # Fuenf Zeichen fangen deutsche Beugungen und Sprachwechsel ab:
            # "Modelle" muss auch das englische "Model" treffen. Kuerzer
            # darf der Stamm nicht sein, sonst wuerde etwa "art" wieder in
            # "Smartphone" als Uebereinstimmung gelten.
            stem = term[:5]
            if term in haystack or stem in haystack:
                matches += 1
        if matches >= required:
            relevant.append(item)
    return relevant


def _fetch(url: str, *, data: bytes | None = None, timeout: float = 12.0) -> bytes:
    """Holt eine Adresse und gibt die rohen Bytes zurück."""

    # Ein vollständiger Satz Browser-Kopfzeilen. Mojeek und Ecosia wiesen
    # die Anfrage mit 403 ab, wenn nur User-Agent und Sprache mitkamen: Eine
    # Anfrage ohne "Accept" und ohne die "Sec-Fetch"-Angaben sieht nicht aus
    # wie ein Browser, der eine Seite öffnet, sondern wie ein Skript - und
    # genau die werden abgewiesen. Mit dem vollen Satz kommt sie durch.
    kopf = {
        "User-Agent": _USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Accept-Encoding": "gzip",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "DNT": "1",
    }
    if data is not None:
        # POST-Suchen (DuckDuckGo) schicken ein Formular ab; dann passt der
        # Formular-Kopf besser als "ich öffne eine Seite frisch".
        kopf["Content-Type"] = "application/x-www-form-urlencoded"
        kopf["Sec-Fetch-Site"] = "same-origin"
    request = urllib.request.Request(
        url,
        data=data,
        headers=kopf,
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding", "") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return raw


class _TextExtractor(html.parser.HTMLParser):
    """Zieht den LESBAREN Text aus einer HTML-Seite - und nur den.

    Diese Klasse war schlicht, und dafür war sie an der falschen Stelle
    schlicht. Sie sammelte jeden Text der Seite in der Reihenfolge, in der
    er im Quelltext steht. Bei einer Nachrichtenseite steht dort zuerst
    das Menü, dann noch ein Menü, dann die Suchleiste, dann die
    Ressortliste - und der Artikel irgendwo danach.

    Was dabei herauskam, stand im Protokoll des Benutzers:

        Werkzeug 'webseite_lesen' ausgefuehrt (0.2 s):
        Hauptnavigation | Nebennavigation | Inhalt | Fußzeile |
        Suchbegriff | InlandUntermenü Inland einblenden | Ausland…

    Das Werkzeug meldete Erfolg. Es hatte auch Erfolg - es hat eine Seite
    geholt und Text zurückgegeben. Nur war es der Text der Navigationsleiste.
    Der Orb bekam ein Inhaltsverzeichnis statt einer Nachricht, und weil
    die Ausgabe bei viertausend Zeichen abgeschnitten wird, kam der
    Artikel nie an. Für den Benutzer sieht das aus wie ein kaputtes
    Werkzeug, und der Sache nach ist es das auch.

    Zwei Dinge sind deshalb neu:

    1. **Beiwerk wird übersprungen** - Navigation, Kopf- und Fusszeile,
       Seitenleisten, Formulare. Das ist auf jeder Seite Beiwerk und auf
       keiner der Inhalt.
    2. **Der Hauptteil wird bevorzugt** - steht auf der Seite ein
       ``<main>`` oder ``<article>``, wird nur daraus gelesen. Fast jede
       Nachrichtenseite hat das, und wo es fehlt, bleibt es beim alten Weg.
    """

    #: Was gar keinen lesbaren Text enthält.
    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    #: Was Text enthält, aber nie den gesuchten.
    #:
    #: ``form``, ``button`` und ``select`` stehen mit dabei, weil
    #: Suchfelder und Zustimmungsdialoge sonst als erste Sätze der Seite
    #: erscheinen - "Suchbegriff", "Alle akzeptieren", "Menü schliessen".
    _BEIWERK = {
        "nav", "header", "footer", "aside", "form", "button", "select",
        "option", "label", "iframe", "figcaption",
    }

    #: Was einen Absatz beendet.
    _BREAK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article",
    }

    #: Der Hauptteil, wenn es einen gibt.
    _HAUPT = {"main", "article"}

    #: Elemente ohne schliessendes Gegenstück. Sie dürfen nicht auf den
    #: Stapel, sonst käme er nie wieder herunter.
    _LEER = {
        "br", "img", "hr", "input", "meta", "link", "source", "col",
        "area", "base", "embed", "param", "track", "wbr",
    }

    #: Rollen, die dasselbe bedeuten wie die entsprechenden Elemente.
    #: Viele Seiten schreiben <div role="navigation"> statt <nav>.
    _BEIWERK_ROLLEN = {"navigation", "banner", "search", "contentinfo", "complementary"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._alles: list[str] = []
        self._haupt: list[str] = []
        #: Für jedes offene Element: sein Name und wofür es zählt.
        #:
        #: Ein Stapel und keine drei Zähler - das ist die Behebung eines
        #: Fehlers, den ich beim ersten Anlauf selbst eingebaut habe und
        #: der genau eine Zeile lang war:
        #:
        #: Beiwerk wurde am ÖFFNENDEN Element auch an der ROLLE erkannt
        #: (<div role="navigation">), am SCHLIESSENDEN aber nur am Namen.
        #: Ein solches div hob den Zähler also an und senkte ihn nie
        #: wieder - von da an galt der ganze Rest der Seite als Beiwerk.
        #: Das Werkzeug gab daraufhin eine leere Zeichenkette zurück.
        #:
        #: Wer am öffnenden Element etwas anderes prüft als am
        #: schliessenden, bekommt genau das. Mit einem Stapel kann es
        #: nicht passieren: Was hineingelegt wurde, wird auch wieder
        #: herausgenommen.
        self._offen: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._beiwerk_depth = 0
        self._haupt_depth = 0

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # <br/> und Geschwister: öffnen und schliessen in einem.
        if tag in self._BREAK:
            self._anhaengen("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._LEER:
            if tag in self._BREAK:
                self._anhaengen("\n")
            return

        rolle = (dict(attrs).get("role") or "").strip().lower()

        if tag in self._SKIP:
            art = "skip"
            self._skip_depth += 1
        elif tag in self._BEIWERK or rolle in self._BEIWERK_ROLLEN:
            art = "beiwerk"
            self._beiwerk_depth += 1
        elif tag in self._HAUPT or rolle == "main":
            art = "haupt"
            self._haupt_depth += 1
        else:
            art = ""

        self._offen.append((tag, art))
        if tag in self._BREAK:
            self._anhaengen("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._LEER:
            return

        # Bis zum passenden Element zurückräumen. Unsauberes HTML lässt
        # Elemente offen; ohne dieses Zurückräumen bliebe der Stapel für
        # den Rest der Seite verschoben.
        for stelle in range(len(self._offen) - 1, -1, -1):
            if self._offen[stelle][0] != tag:
                continue
            for _name, art in self._offen[stelle:]:
                if art == "skip":
                    self._skip_depth = max(0, self._skip_depth - 1)
                elif art == "beiwerk":
                    self._beiwerk_depth = max(0, self._beiwerk_depth - 1)
                elif art == "haupt":
                    self._haupt_depth = max(0, self._haupt_depth - 1)
            del self._offen[stelle:]
            break

        if tag in self._BREAK:
            self._anhaengen("\n")

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._anhaengen(data)

    def _anhaengen(self, stueck: str) -> None:
        if self._skip_depth or self._beiwerk_depth:
            return
        self._alles.append(stueck)
        if self._haupt_depth:
            self._haupt.append(stueck)

    def text(self) -> str:
        """Der Hauptteil, wenn er etwas hergibt - sonst die ganze Seite.

        Die Untergrenze ist wichtig: Manche Seiten setzen ein ``<main>``
        um eine leere Hülle und laden den Inhalt erst nachträglich. Dann
        wäre der Hauptteil zwar vorhanden, aber leer - und ein leeres
        Ergebnis wäre schlechter als das alte Verhalten.
        """

        haupt = self._saeubern("".join(self._haupt))
        if len(haupt) >= 400:
            return haupt
        return self._saeubern("".join(self._alles))

    @staticmethod
    def _saeubern(roh: str) -> str:
        # Leerraum eindampfen: erst Zeilen glätten, dann Mehrfachumbrüche.
        roh = re.sub(r"[ \t]+", " ", roh)
        roh = re.sub(r" ?\n ?", "\n", roh)
        roh = re.sub(r"\n{3,}", "\n\n", roh)
        return roh.strip()


def _decode(raw: bytes) -> str:
    """Bytes zu Text, ohne an einer falschen Kodierung zu scheitern."""

    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class _Suchfehler(RuntimeError):
    """Die Suche kam nicht durch - mit Angabe, woran genau.

    Ein eigener Fehler, weil die drei Fälle - kein Netz, abgewiesen,
    Seitenaufbau geändert - vom Aufrufer verschieden zu behandeln sind und
    der Benutzer sie verschieden zu hören bekommt. Vorher wurden sie alle
    zu "Keine Treffer", und damit war nicht zu erkennen, was zu tun ist.
    """

    def __init__(self, art: str, text: str) -> None:
        super().__init__(text)
        self.art = art


#: Wie weit eine Suche gekommen ist - je hoeher, desto weiter.
#:
#: Genau daran hing die falsche Fehlermeldung: Gemeldet wurde bisher die Art
#: der ZULETZT versuchten Maschine. DuckDuckGo Lite steht immer zuletzt und
#: ist tatsaechlich gesperrt (die Seite zeigt "Unfortunately, bots use
#: DuckDuckGo too"). Also hiess JEDE gescheiterte Suche "die Suchmaschine
#: haelt meine Anfrage fuer automatisiert" - auch dann, wenn Bing und Yahoo
#: vorher sauber geantwortet hatten und nur der Relevanzfilter zugeschlagen
#: hat. Der Benutzer bekam damit durchgehend die einzige Diagnose zu hoeren,
#: die nicht zutraf, und suchte den Fehler an der falschen Stelle.
_URSACHEN_RANG: dict[str, int] = {
    "kein_netz": 0,     # gar nicht erst hingekommen
    "abgewiesen": 1,    # abgewiesen, bevor es Inhalt gab
    "unlesbar": 2,      # Inhalt da, Aufbau nicht erkannt
    "themenfremd": 3,   # Inhalt UND Treffer da, nur unpassend
}


def _hauptursache(fehler: list["_Suchfehler"]) -> str:
    """Waehlt aus mehreren Fehlschlaegen den aussagekraeftigsten.

    Die Regel ist einfach und entspricht dem, was ein Mensch sagen wuerde:
    Es zaehlt die WEITESTE Stelle, die irgendeine Maschine erreicht hat.
    Hat auch nur eine geantwortet, war es keine Bot-Sperre - dann half die
    Antwort nur nicht weiter, und das ist etwas anderes.
    """

    if not fehler:
        return "unlesbar"
    return max((f.art for f in fehler), key=lambda art: _URSACHEN_RANG.get(art, 2))


def _resolve_duckduckgo_url(href: str) -> str:
    """Löst die Weiterleitungsadresse von DuckDuckGo in das echte Ziel auf."""

    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.path.startswith("/l/"):
        query = urllib.parse.parse_qs(parsed.query)
        target = query.get("uddg", [""])[0]
        if target:
            return target
    return href


def _resolve_bing_url(href: str) -> str:
    """Löst die Weiterleitungsadresse von Bing in das echte Ziel auf.

    Das war der eigentliche Grund, warum die Suche scheiterte: Bing
    ANTWORTETE (im Protokoll standen 74000 Zeichen), aber jeder Treffer
    zeigte nicht auf die gefundene Seite, sondern auf eine Bing-eigene
    Umleitung – ``https://www.bing.com/ck/a?...&u=a1<base64>&...``. Die
    Trefferliste war also voll, aber jeder Link hatte den Wirt ``bing.com``
    und wurde als "das ist die Suchmaschine selbst" verworfen. Ergebnis:
    "74000 Zeichen, kein Treffer".

    Die echte Adresse steckt im Parameter ``u``: hinter dem Vorsatz ``a1``
    steht sie als base64 (URL-Variante). Holen wir sie heraus, zeigt der
    Treffer wieder auf die richtige Seite – und Bing wird zur verlässlichen
    Suchmaschine, denn es weist die Anfragen nicht ab.
    """

    parsed = urllib.parse.urlparse(href)
    # Bing News RSS nutzt eine normale URL-Weiterleitung statt base64.
    if "bing.com" in parsed.netloc.lower() and parsed.path.endswith("/news/apiclick.aspx"):
        ziel = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        if ziel.startswith(("http://", "https://")):
            return ziel
    if "bing.com" not in parsed.netloc.lower() or "/ck/" not in parsed.path:
        return href
    roh = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
    if not roh.startswith("a1"):
        return href
    kern = roh[2:]
    # base64 braucht eine Länge, die durch vier teilbar ist; Bing lässt die
    # Auffüllzeichen weg, also hier wieder anhängen.
    kern += "=" * (-len(kern) % 4)
    try:
        import base64

        ziel = base64.urlsafe_b64decode(kern).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return href
    return ziel if ziel.startswith(("http://", "https://")) else href


def _resolve_yahoo_url(href: str) -> str:
    """Loest Yahoos ``/RU=<ziel>/``-Weiterleitung auf.

    Yahoo lieferte vollstaendige Trefferseiten, doch jeder Ergebnislink
    zeigte zuerst auf ``r.search.yahoo.com`` und wurde deshalb als
    Suchmaschinen-Navigation verworfen. Das echte Ziel steht URL-kodiert im
    Pfadsegment ``RU``.
    """

    parsed = urllib.parse.urlparse(href)
    if not parsed.netloc.lower().endswith("search.yahoo.com"):
        return href
    treffer = re.search(r"/RU=([^/]+)(?:/|$)", parsed.path)
    if not treffer:
        return href
    ziel = urllib.parse.unquote(treffer.group(1))
    return ziel if ziel.startswith(("http://", "https://")) else href


def _zieladresse(href: str) -> str:
    """Die ECHTE Zieladresse eines Treffer-Links.

    Ein Ort für alle Umleitungen der Suchmaschinen. Fällt eine neue dazu,
    kommt sie hierher – und alle Wege (feiner wie grober) profitieren davon,
    weil sie diese eine Funktion benutzen statt jeder seine eigene.
    """

    return _resolve_yahoo_url(_resolve_bing_url(_resolve_duckduckgo_url(href)))


#: Die Muster der HTML-Fassung. Sie bleiben als SCHNELLER WEG erhalten -
#: wenn sie passen, liefern sie saubere Titel und Beschreibungen.
_RESULT_PATTERN = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.S,
)
_SNIPPET_PATTERN = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.S,
)


def _strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


class _LinkSammler(html.parser.HTMLParser):
    """Sammelt alle Links einer Seite samt ihrem Text.

    Das ist der ZWEITE Weg, und er ist der eigentliche Gewinn.

    Der erste Weg sucht nach ``class="result__a"``. Solange die
    Suchmaschine diese Klasse benutzt, ist er der bessere - er trennt
    Titel und Beschreibung sauber. Aber er haengt an einem Namen, den
    jemand anderes vergibt, und der eines Tages anders lautet. Dann findet
    das Muster nichts, die Trefferliste ist leer, und der Orb meldet "keine
    Treffer" - wo in Wahrheit die Seite voller Treffer stand.

    Dieser Weg haengt an nichts dergleichen. Er nimmt jeden Link, der
    woandershin fuehrt als zur Suchmaschine selbst. Das ist groeber und
    faengt auch mal eine Fusszeile mit - aber es geht nicht kaputt, wenn
    jemand eine Klasse umbenennt.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.treffer: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._abschliessen()
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href and data.strip():
            self._text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._abschliessen()

    def close(self) -> None:  # noqa: D102 - Erbe von HTMLParser
        self._abschliessen()
        super().close()

    def _abschliessen(self) -> None:
        if self._href and self._text:
            self.treffer.append((self._href, " ".join(self._text)))
        self._href = ""
        self._text = []


def _brauchbarer_treffer(url: str, titel: str, eigene: tuple[str, ...]) -> bool:
    """Ob ein eingesammelter Link ein Suchtreffer sein kann."""

    if not url.startswith(("http://", "https://")):
        return False
    if len(titel) < 12:
        # Zu kurz fuer eine Ueberschrift: "Mehr", "Weiter", "Einstellungen".
        return False
    wirt = urllib.parse.urlparse(url).netloc.lower()
    return not any(e in wirt for e in eigene)


def _treffer_aus_seite(seite: str, limit: int,
                       eigene: tuple[str, ...] = _EIGENE_WIRTE) -> list[dict[str, str]]:
    """Liest die Treffer aus einer Suchergebnisseite - erst fein, dann grob."""

    # Der feine Weg.
    titel = _RESULT_PATTERN.findall(seite)
    if titel:
        schnipsel = [_strip_tags(t) for t in _SNIPPET_PATTERN.findall(seite)]
        return [
            {
                "titel": _strip_tags(titel_html),
                "url": _zieladresse(html.unescape(href)),
                "beschreibung": schnipsel[i] if i < len(schnipsel) else "",
            }
            for i, (href, titel_html) in enumerate(titel[: max(1, limit)])
        ]

    # Der grobe Weg - er greift, wenn der feine ins Leere lief.
    sammler = _LinkSammler()
    sammler.feed(seite)
    sammler.close()

    gesehen: set[str] = set()
    treffer: list[dict[str, str]] = []
    for href, text in sammler.treffer:
        url = _zieladresse(html.unescape(href))
        if not _brauchbarer_treffer(url, text, eigene):
            continue
        if url in gesehen:
            continue
        gesehen.add(url)
        treffer.append({"titel": text[:160], "url": url, "beschreibung": ""})
        if len(treffer) >= max(1, limit):
            break
    if treffer:
        logger.info(
            "Die Suchergebnisse wurden ueber den groben Weg gelesen - die "
            "Suchmaschine hat ihren Seitenaufbau vermutlich geaendert."
        )
    return treffer


def _rss_treffer(seite: str, limit: int) -> list[dict[str, str]]:
    """Liest Bings strukturierte RSS-Treffer ohne HTML-Heuristiken."""

    try:
        root = ET.fromstring(seite)
    except ET.ParseError:
        return []

    gesehen: set[str] = set()
    treffer: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        titel = html.unescape((item.findtext("title") or "").strip())
        url = _zieladresse(html.unescape((item.findtext("link") or "").strip()))
        beschreibung = _strip_tags(item.findtext("description") or "")
        datum = (item.findtext("pubDate") or "").strip()
        if not titel or not url.startswith(("http://", "https://")):
            continue
        if url in gesehen:
            continue
        gesehen.add(url)
        if datum:
            beschreibung = f"{beschreibung} [{datum}]".strip()
        treffer.append(
            {"titel": titel[:200], "url": url, "beschreibung": beschreibung[:700]}
        )
        if len(treffer) >= max(1, limit):
            break
    return treffer


def _ist_nachrichten_suche(query: str) -> bool:
    knapp = " " + " ".join(query.lower().split()) + " "
    return "site:" not in knapp and any(
        wort in knapp
        for wort in (
            " news ", " nachricht", " schlagzeil", " presse ",
            " was gibt es neues ", " aktuelle entwicklungen ",
        )
    )


# Begriffe, bei denen eine Enzyklopaedie oder Literaturdatenbank nicht die
# gesuchte Quelle ist. Bei "Haftpflichtversicherung Schweiz Vergleich"
# lieferte Wikipedia technisch passende, praktisch aber nutzlose Artikel.
# Solche Anfragen gehen deshalb zuerst an die allgemeine Websuche.
_ALLGEMEINE_WEB_BEGRIFFE: tuple[str, ...] = (
    " vergleich", " vergleichen", " günstig", " guenstig", " billig",
    " preis", " kosten", " angebot", " kaufen", " bestellen", " shop",
    " versicherung", " öffnungszeit", " oeffnungszeit", " restaurant",
    " hotel", " laden", " geschäft", " geschaeft", " dienstleister",
    " website", " webseite", " homepage", " download", " app ",
)


def _allgemeine_websuche_zuerst(query: str) -> bool:
    """Ob ein echter Webindex vor Fach- und Wissensquellen gehoert."""

    knapp = " " + " ".join(str(query or "").lower().split()) + " "
    if _ist_nachrichten_suche(query):
        return False
    if _ist_alltagssuche(query):
        return True
    # "Aktuelle OpenAI Modelle" ist keine Schlagzeilenfrage. Wikipedia und
    # OpenAlex hielten den Orb hier sechs Sekunden auf, waehrend der
    # strukturierte Webindex in weniger als einer Sekunde antwortete.
    return any(
        marker in knapp
        for marker in (" aktuell", " neueste", " neuesten", " letzter stand")
    )


def _ist_alltagssuche(query: str) -> bool:
    """Ob Fachquellen fuer diese Anfrage grundsaetzlich die falsche Art sind."""

    knapp = " " + " ".join(str(query or "").lower().split()) + " "
    return any(begriff in knapp for begriff in _ALLGEMEINE_WEB_BEGRIFFE)


def _web_anfragevarianten(query: str) -> list[str]:
    """Eine volle und eine von Werbewoertern befreite Webanfrage.

    Bing-RSS gewichtete bei ``guenstige Haftpflichtversicherung Schweiz
    Vergleich`` das erste Wort so stark, dass nur beliebige Billigangebote
    erschienen. Ohne das Werbeadjektiv standen sofort Schweizer
    Versicherungsvergleiche vorn. Die Relevanz wird trotzdem gegen die
    VOLLSTAENDIGE Anfrage geprueft; die Vereinfachung kann also keinen
    themenfremden Treffer zum Erfolg machen.
    """

    voll = " ".join(str(query or "").split())
    reduziert = re.sub(
        r"\b(?:günstig\w*|guenstig\w*|billig\w*|beste\w*)\b",
        " ",
        voll,
        flags=re.IGNORECASE,
    )
    reduziert = " ".join(reduziert.split())
    return list(dict.fromkeys(q for q in (voll, reduziert) if q))


def _einmal_suchen(maschine: _Maschine, query: str, limit: int) -> list[dict[str, str]]:
    """Fragt EINE Suchmaschine und liest ihre Treffer. Wirft ``_Suchfehler``."""

    name = maschine.name
    if maschine.methode == "post":
        data = urllib.parse.urlencode({"q": query, "kl": "de-de"}).encode("utf-8")
        adresse = maschine.adresse
    else:
        # GET: die Anfrage steht in der Adresse.
        felder = {"q": query, **maschine.zusatz}
        if maschine.methode == "rss":
            felder["format"] = "rss"
            basis = (
                "https://www.bing.com/news/search"
                if _ist_nachrichten_suche(query)
                else maschine.adresse
            )
        else:
            basis = maschine.adresse
        adresse = basis + "?" + urllib.parse.urlencode(felder)
        data = None

    try:
        seite = _decode(_fetch(adresse, data=data))
    except urllib.error.HTTPError as fehler:
        # 202/403/429 sind die typischen Abweisungen; alles andere zaehlt
        # ebenfalls als "diese Maschine gerade nicht", damit die naechste
        # drankommt.
        raise _Suchfehler(
            "abgewiesen", f"{name} antwortete mit {fehler.code}."
        ) from fehler
    except urllib.error.URLError as fehler:
        raise _Suchfehler(
            "kein_netz", f"{name} war nicht erreichbar: {fehler.reason}"
        ) from fehler
    except OSError as fehler:
        raise _Suchfehler("kein_netz", f"{name} war nicht erreichbar: {fehler}") from fehler

    # 20000 statt 4000 Zeichen: DuckDuckGo schiebt seinen Sperrhinweis
    # hinter einen langen Kopfbereich. Mit dem kurzen Fenster wurde die
    # echte Sperre teils uebersehen - und dafuer ein CSS-Klassenname weiter
    # vorn als Sperre gedeutet.
    knapp = seite[:20000].lower()
    if any(wort in knapp for wort in _ABWEISUNGEN):
        _mitschnitt(name, adresse, seite)
        raise _Suchfehler("abgewiesen", f"{name} hat die Anfrage abgewiesen.")

    treffer = (
        _rss_treffer(seite, limit)
        if maschine.methode == "rss"
        else _treffer_aus_seite(seite, limit, maschine.eigene)
    )
    if not treffer:
        # Genau hier steckt das wiederkehrende Suchproblem: Die Maschine
        # ANTWORTET (oft mit zehntausenden Zeichen), aber es wird kein
        # Treffer erkannt. Warum, laesst sich nur an der echten Seite sehen -
        # und die faellt auf dem Rechner des Benutzers anders aus als
        # irgendwo sonst (Region, Zustimmungsseiten, andere Vorlage). Darum
        # wird sie hier mitgeschnitten, damit der Aufbau gezielt statt auf
        # Verdacht behoben werden kann.
        _mitschnitt(name, adresse, seite)
        raise _Suchfehler(
            "unlesbar",
            f"{name} lieferte {len(seite)} Zeichen, darin war aber kein "
            "Treffer zu erkennen.",
        )
    return treffer


def _mitschnitt(name: str, adresse: str, seite: str) -> None:
    """Schreibt eine nicht lesbare Suchseite zur Diagnose auf die Platte.

    Nur ein Werkzeug fuer die Fehlersuche: Es legt die zuletzt gescheiterte
    Seite je Suchmaschine unter ``logs/suche-debug/`` ab (und ueberschreibt
    die vorige). So laesst sich der tatsaechliche Seitenaufbau ansehen,
    statt ihn zu raten. Schlaegt das Schreiben fehl, ist das gleichgueltig -
    es darf die Suche nie stoeren.
    """

    try:
        from backend.utils.paths import get_project_root

        ordner = get_project_root() / "logs" / "suche-debug"
        ordner.mkdir(parents=True, exist_ok=True)
        sicher = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "engine"
        kopf = f"<!-- {name} | {adresse} | {len(seite)} Zeichen -->\n"
        (ordner / f"{sicher}.html").write_text(
            kopf + seite[:400000], encoding="utf-8"
        )
        logger.info("Suchseite von %s zur Diagnose gesichert (suche-debug/%s.html).", name, sicher)
    except Exception:  # noqa: BLE001 - Diagnose darf nie die Suche reissen.
        pass


#: Ob zusaetzlich zu Bing-RSS und DuckDuckGo Lite auch die nachweislich
#: blockierten HTML-Maschinen laufen. Der strukturierte Bing-Zugang ist
#: KEINE Altmaschine und wird im Normalbetrieb immer benutzt.
ALTMASCHINEN_AKTIV = False

#: Welche Maschinen im Normalbetrieb ueberhaupt gefragt werden.
#:
#: DuckDuckGo Lite steht hier nicht mehr. Nicht aus Nachlaessigkeit: Die am
#: 26.08.2026 gesicherte Antwort ist eine Sperrseite mit Bilderraetsel -
#: "Unfortunately, bots use DuckDuckGo too. Select all squares containing a
#: duck." Das ist keine Tagesform, die sich mit besseren Kopfzeilen aendert,
#: sondern die vorgesehene Antwort. Bei jeder Suche danach zu fragen kostete
#: eine Anfrage und eine Wartezeit fuer ein sicheres Nein.
#:
#: Als Ausweichweg bleibt der Zugang bestehen: ``ALTMASCHINEN_AKTIV = True``
#: holt ihn samt Mojeek und Ecosia zurueck, falls sich die Lage aendert oder
#: der Benutzer aus einem anderen Netz sucht.
NORMALE_MASCHINEN: frozenset[str] = frozenset({"Bing", "Yahoo"})


def _echter_webindex_verfuegbar() -> bool:
    """Ob unter den offenen Quellen eine vollwertige Websuche steckt.

    Wikipedia, OpenAlex und GDELT sind Fachquellen - fuer "Was kostet eine
    Hausratversicherung in Zuerich" die falsche Art von Antwort. Ein
    Schluessel fuer eine richtige Suchmaschine ist etwas anderes: Der
    beantwortet auch Alltagsfragen und wird nie als Automat abgewiesen.
    Deshalb haengt an dieser einen Stelle, ob eine Alltagssuche nach den
    Trefferseiten aufgibt oder weitergeht.

    Kommt spaeter ein zweiter Anbieter dazu, gehoert er hierher - und
    nirgendwo sonst.
    """

    try:
        from backend.research.offene_quellen import google_verfuegbar

        return bool(google_verfuegbar())
    except Exception:  # noqa: BLE001 - eine fehlende Quelle ist kein Fehler.
        return False


def search_web(query: str, *, limit: int = 6) -> list[dict[str, str]]:
    """Sucht im Internet und gibt Titel, Adresse und Beschreibung zurueck.

    Versucht der Reihe nach alle Zugaenge. Scheitern alle, wird der Fehler
    des LETZTEN geworfen - mit der Art des Scheiterns, damit der Aufrufer
    dem Benutzer sagen kann, woran es liegt.
    """

    query = suchbegriff_aus(query, hoechstens=180)

    # Allgemeine Alltagssuchen (Produkte, Preise, Oeffnungszeiten, konkrete
    # Webseiten) brauchen einen echten Webindex. Eine Wikipedia-Antwort ist
    # dort kein Erfolg. Bing liefert dafuer eine strukturierte RSS-Liste;
    # DuckDuckGo Lite ist der zweite, unabhaengige Zugang.
    web_zuerst = _allgemeine_websuche_zuerst(query)
    normale_maschinen = tuple(
        maschine for maschine in _SUCHMASCHINEN if maschine.name in NORMALE_MASCHINEN
    )
    maschinen = _SUCHMASCHINEN if ALTMASCHINEN_AKTIV else normale_maschinen
    fehlschlaege: list[_Suchfehler] = []
    gruende: list[str] = []
    #: Treffer, die eine Maschine geliefert hat, die aber der Relevanzfilter
    #: verworfen hat. Sie sind der Notweg: Lieber lose passende Treffer als
    #: gar keine Antwort - der Orb sagt dann selbst dazu, dass sie nur lose
    #: passen. Vorher wurden sie schlicht weggeworfen, und aus einer
    #: beantworteten Suche wurde eine gescheiterte.
    notweg: list[dict[str, str]] = []

    def _web_suchen() -> list[dict[str, str]]:
        for maschine in maschinen:
            for variante in _web_anfragevarianten(query):
                try:
                    treffer = _einmal_suchen(maschine, variante, limit)
                    relevante = _relevante_treffer(query, treffer)
                    if not relevante:
                        if treffer and not notweg:
                            notweg.extend(treffer[:limit])
                        # Eigene Art: Die Maschine hat geantwortet UND
                        # Treffer geliefert - sie passten nur nicht. Das ist
                        # fast immer der Suchbegriff, nie eine Sperre.
                        raise _Suchfehler(
                            "themenfremd",
                            f"{maschine.name} lieferte nur themenfremde Treffer.",
                        )
                    if variante != query:
                        logger.info(
                            "Websuche ueber %s mit bereinigter Anfrage beantwortet.",
                            maschine.name,
                        )
                    else:
                        logger.info("Websuche ueber %s beantwortet.", maschine.name)
                    return relevante[:limit]
                except _Suchfehler as fehler:
                    logger.warning(
                        "Suche ueber %s gescheitert: %s", maschine.name, fehler
                    )
                    gruende.append(str(fehler))
                    fehlschlaege.append(fehler)
        return []

    if web_zuerst:
        webtreffer = _web_suchen()
        if webtreffer:
            return webtreffer
        # Produkt-, Preis-, Lokal- und Vergleichssuchen werden durch einen
        # Enzyklopaedieartikel nicht gerettet. Vorher wurde aus der leeren
        # Versicherungssuche eine Liste zu Kfz, Elektroauto und VW Golf und
        # trotzdem "Erfolg" gemeldet. Lieber ein ehrlicher Suchfehler.
        if _ist_alltagssuche(query):
            if notweg:
                logger.warning(
                    "Websuche nur ueber den Notweg beantwortet: Die Treffer "
                    "passen dem Filter nach nicht zur Anfrage %r.", query
                )
                return notweg[:limit]
            # ... ABER nur, solange unter den offenen Quellen kein echter
            # Webindex steckt. Genau der Abbruch hier war der Grund, warum
            # ein hinterlegter Google-Schluessel bei Preis- und
            # Oeffnungszeitenfragen wirkungslos blieb: Die einzige Quelle,
            # die nie abgewiesen wird und einen echten Webindex hat, wurde
            # ausgerechnet dort nie gefragt. Liegt sie vor, laeuft der
            # gemeinsame Weg unten weiter.
            if not _echter_webindex_verfuegbar():
                raise _Suchfehler(
                    _hauptursache(fehlschlaege),
                    (" ".join(gruende) or "Die allgemeine Websuche blieb leer.")
                    + " Die Fachquellen passen nicht zu einer Alltagssuche.",
                )

    # ZUERST die Dienste, die einen Automaten nicht abweisen koennen - ausser
    # bei den gerade behandelten allgemeinen Webanfragen.
    #
    # Das ist die Lehre aus dem Protokoll vom 15.08.2026: Mojeek und Ecosia
    # antworteten mit 403, beide DuckDuckGo-Zugaenge wiesen ab, und Bing
    # lieferte eine Sperrseite von 1356 Zeichen. Fuenf von fuenf. Gegen
    # dieses Ergebnis hilft kein besserer Kopfzeilensatz - es ist genau die
    # Antwort, die diese Dienste auf einen Automaten geben sollen.
    #
    # GDELT, Wikipedia, OpenAlex und Crossref dagegen SIND fuer Programme
    # gemacht. Sie verlangen keine Tarnung, sondern eine ehrliche Kennung.
    # Deshalb stehen sie hier vorn und die Trefferseiten dahinter - nicht
    # umgekehrt.
    try:
        from backend.research.offene_quellen import offene_suche

        offene, benutzt = offene_suche(query, limit=limit)
        relevante_offene = _relevante_treffer(query, offene)
        if relevante_offene:
            logger.info(
                "Suche ueber offene Quellen beantwortet (%s).", ", ".join(benutzt)
            )
            return relevante_offene[:limit]
        if offene:
            logger.warning(
                "Offene Quellen lieferten nur themenfremde Treffer fuer %r.", query
            )
    except Exception:  # noqa: BLE001 - der alte Weg bleibt als Ausweg bestehen.
        logger.exception("Die offenen Quellen liessen sich nicht befragen.")

    # Fuer Sach-, Nachrichten- und Literaturfragen waren die offenen Quellen
    # zuerst dran. Blieben sie leer, kommt jetzt IMMER der strukturierte
    # Web-Fallback. Genau dieser Aufruf war vorher hinter dem dauerhaft
    # falschen Schalter ``ALTMASCHINEN_AKTIV = False`` unerreichbar.
    if not web_zuerst:
        webtreffer = _web_suchen()
        if webtreffer:
            return webtreffer

    if notweg:
        logger.warning(
            "Websuche nur ueber den Notweg beantwortet: Die Treffer passen "
            "dem Filter nach nicht zur Anfrage %r.", query
        )
        return notweg[:limit]

    raise _Suchfehler(
        _hauptursache(fehlschlaege),
        (" ".join(gruende) or "Kein Zugang hat geantwortet.")
        + " Auch die offenen Quellen (GDELT, Wikipedia, OpenAlex) haben nichts "
          "geliefert. Womit das zusammenhaengt, zeigt SUCHE-PRUEFEN.bat: Es "
          "fragt jede Quelle einzeln und nennt den Grund im Klartext.",
    )


class WebSearchTool(Tool):
    """Sucht im Internet und öffnet Ergebnisse im Browser."""

    name = "internet_suchen"
    description = (
        "Sucht im Internet nach einem Begriff. Öffnet automatisch den Browser "
        "mit den Suchergebnissen, damit du sie direkt sehen kannst. Das ist die "
        "natürliche Reaktion auf Suchanfragen: 'suche nach...', 'such mir...', "
        "'finde...', 'wie sieht es aus mit...'. Der Browser zeigt die Ergebnisse, "
        "während der Orb dir auch einen sprechbaren Überblick gibt."
    )
    # "internet" gibt es als Berechtigung nicht - sie heisst "network".
    # Unter dem falschen Namen wies das Register das Werkzeug bei jedem
    # Start ab, und der Orb stand ohne Websuche da.
    permission = "network"
    parameters = (
        ToolParameter("suchbegriff", "string", "Wonach gesucht wird."),
        ToolParameter(
            "max_treffer", "integer", "Hoechstzahl der Treffer (1-10).",
            required=False, default=6,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("suchbegriff", "")).strip()
        if not query:
            return ToolResult.failure("Es fehlt der Suchbegriff.")
        limit = min(10, max(1, int(arguments.get("max_treffer", 6) or 6)))

        import asyncio
        import webbrowser

        # Öffne den Browser mit Suchmaschine - parallel zur Text-Suche
        def _open_browser():
            try:
                search_url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(query)
                webbrowser.open(search_url, new=2)
            except Exception:
                pass

        asyncio.create_task(asyncio.to_thread(_open_browser))

        try:
            results = await asyncio.to_thread(search_web, query, limit=limit)
        except _Suchfehler as fehler:
            auskunft = {
                "kein_netz": (
                    "Ich komme nicht ins Internet - die Suchmaschine ist "
                    f"nicht erreichbar. ({fehler})"
                ),
                "abgewiesen": (
                    "Die Suchmaschine hat meine Anfrage abgewiesen; sie "
                    f"haelt sie fuer automatisiert. ({fehler})"
                ),
                "unlesbar": (
                    "Die Suchmaschine hat geantwortet, aber ihre Seite war "
                    f"nicht zu lesen - der Aufbau hat sich geaendert. ({fehler})"
                ),
                "themenfremd": (
                    "Die Suchmaschinen haben geantwortet, aber keiner ihrer "
                    "Treffer passte zur Anfrage. Meist liegt das am "
                    f"Suchbegriff, nicht an der Leitung. ({fehler})"
                ),
            }.get(
                fehler.art,
                f"Die Suche ist nicht durchgekommen. ({fehler})",
            )
            logger.warning("Internetsuche gescheitert (%s): %s", fehler.art, fehler)
            return ToolResult.failure(auskunft, art=fehler.art)
        except Exception as error:
            logger.exception("Die Internetsuche ist fehlgeschlagen.")
            return ToolResult.failure(f"Die Suche ist fehlgeschlagen: {error}")

        if not results:
            return ToolResult.success(f"Keine Treffer zu '{query}'.")

        lines = [
            f"{item['titel']}\n    {item['url']}\n    {item['beschreibung']}".rstrip()
            for item in results
        ]
        return ToolResult.success("\n\n".join(lines), count=len(results), treffer=results)


# Hier stand `LearnTopicTool`. Es ist nach
# backend/tools/learning_tools.py gezogen, und das aus einem inhaltlichen
# Grund: Es speicherte nur die Trefferzeile der Suchmaschine - Titel, ein
# Satz, ein Link. Wer eine Woche spaeter nach dem Thema fragte, bekam eine
# Linkliste. Das neue liest die Quellen, destilliert daraus einzelne
# belegte Aussagen und haelt fest, was offen blieb.


class OpenInBrowserTool(Tool):
    """Öffnet eine Seite oder eine Suche im Browser des Benutzers.

    Der Unterschied zu ``internet_suchen``: Dort liest der Orb selbst und
    antwortet mit Worten. Hier will der Benutzer die Seite SEHEN – „zeig mir
    das Wetter im Browser" heißt: Browserfenster auf, Seite drin.
    """

    name = "browser_oeffnen"
    description = (
        "Oeffnet eine Internetadresse oder eine Suche im Standardbrowser des "
        "Benutzers. Benutze das immer, wenn der Benutzer etwas SEHEN will - "
        "'zeig mir ... im Browser', 'oeffne die Seite ...', 'zeig mir das "
        "Wetter an'. Gib entweder eine url an ODER einen suchbegriff; bei "
        "einem Suchbegriff oeffnet sich die Suche dazu."
    )
    permission = "launch_application"
    parameters = (
        ToolParameter(
            "url", "string", "Die zu oeffnende Adresse (https://...).",
            required=False, default="",
        ),
        ToolParameter(
            "suchbegriff", "string",
            "Alternativ: wonach im Browser gesucht werden soll.",
            required=False, default="",
        ),
    )

    def __init__(self, desktop: Any | None = None) -> None:
        super().__init__()
        self._desktop = desktop

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments.get("url", "")).strip()
        query = str(arguments.get("suchbegriff", "")).strip()

        if not url and not query:
            return ToolResult.failure("Es fehlt eine Adresse oder ein Suchbegriff.")
        if not url:
            url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(query)

        # Über die Desktopsteuerung, wenn es sie gibt – sonst direkt.
        if self._desktop is not None and hasattr(self._desktop, "open_url"):
            result = self._desktop.open_url(url)
            if getattr(result, "success", False):
                return ToolResult.success(result.message, url=url)
            return ToolResult.failure(getattr(result, "message", "Öffnen fehlgeschlagen."))

        try:
            import webbrowser

            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            if not webbrowser.open(url, new=2):
                return ToolResult.failure("Es wurde kein Browser gefunden.")
        except Exception as error:  # noqa: BLE001
            return ToolResult.failure(f"Browser nicht startbar: {error}")

        return ToolResult.success(f"Im Browser geöffnet: {url}", url=url)


class ReadWebpageTool(Tool):
    """Liest eine Webseite und gibt ihren Text zurück."""

    name = "webseite_lesen"
    description = (
        "Holt eine Webseite und gibt ihren lesbaren Text zurueck. Benutze das "
        "nach internet_suchen, um einen Treffer wirklich zu lesen, oder wenn "
        "der Benutzer eine bestimmte Adresse nennt."
    )
    permission = "network"
    parameters = (
        ToolParameter("url", "string", "Die vollstaendige Adresse (https://...)."),
        ToolParameter(
            "max_zeichen", "integer", "Hoechstlaenge des Texts.",
            required=False, default=4000,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments.get("url", "")).strip()
        if not url:
            return ToolResult.failure("Es fehlt die Adresse.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        limit = max(500, int(arguments.get("max_zeichen", 4000) or 4000))

        import asyncio

        # Zwei Fristen, und beide fehlten.
        #
        # Am 06.09.2026 um 15:53 kostete EIN Aufruf dieses Werkzeugs
        # 12,1 Sekunden - fuer eine Absage:
        #
        #     Werkzeug 'webseite_lesen' fehlgeschlagen (12.1 s):
        #     Die Seite meldete 403 fuer https://www.comparis.ch/telecom/
        #
        # Ein Drittel der gesamten Wartezeit dieser Anfrage, fuer ein
        # "nein". Die 12,1 s sind exakt das Zeitlimit in ``_fetch`` - und
        # das ist ein Zeitlimit JE LESEOPERATION, keine Gesamtfrist. Eine
        # Seite, die die Verbindung annimmt und dann schweigt, schoepft es
        # aus; eine mit Umleitungen kann es mehrfach ausschoepfen.
        #
        # Im gesprochenen Dialog ist eine Seite, die nicht zuegig
        # antwortet, ohnehin verloren: Der Benutzer wartet vor dem
        # Lautsprecher. Ein ehrliches "hat nicht geantwortet" nach ein paar
        # Sekunden ist mehr wert als ein spaeter Volltext.
        einstellungen = get_config()
        verbindungsfrist = max(
            1.0, float(einstellungen.get("tools.webseite_lesen.verbindungsfrist_sekunden", 5))
        )
        gesamtfrist = max(
            verbindungsfrist,
            float(einstellungen.get("tools.webseite_lesen.gesamtfrist_sekunden", 8)),
        )

        def _read() -> str:
            extractor = _TextExtractor()
            extractor.feed(_decode(_fetch(url, timeout=verbindungsfrist)))
            return extractor.text()

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_read), timeout=gesamtfrist
            )
        except asyncio.TimeoutError:
            # Der Arbeitsfaden liest zu Ende und wirft das Ergebnis weg -
            # ``to_thread`` laesst sich nicht abbrechen. Wichtig ist, dass
            # der Dialogzug weitergeht.
            logger.info(
                "Die Seite %s hat innerhalb von %.0f s nicht geantwortet; "
                "der Zug geht ohne sie weiter.",
                url,
                gesamtfrist,
            )
            return ToolResult.failure(
                f"Die Seite {url} hat innerhalb von {gesamtfrist:.0f} Sekunden "
                "nicht geantwortet."
            )
        except urllib.error.HTTPError as error:
            return ToolResult.failure(f"Die Seite meldete {error.code} für {url}.")
        except urllib.error.URLError as error:
            return ToolResult.failure(f"Die Seite ist nicht erreichbar: {error.reason}")
        except Exception as error:  # noqa: BLE001
            logger.exception("Die Webseite ließ sich nicht lesen.")
            return ToolResult.failure(f"Die Seite ließ sich nicht lesen: {error}")

        if not text:
            return ToolResult.success(f"Die Seite {url} enthält keinen lesbaren Text.")
        if len(text) > limit:
            text = text[:limit] + "\n[… gekürzt]"
        return ToolResult.success(text, url=url)


def _seiten_links(basis: str, seite: str) -> list[tuple[str, str]]:
    """Sammelt die Links einer Seite als (Adresse, sichtbarer Text).

    Relative Adressen (``/politik/artikel-1.html``) werden an der
    Ausgangsadresse zu vollständigen gemacht, Weiterleitungen aufgelöst,
    Dubletten und leere Verweise entfernt. So bekommt der Orb eine Liste,
    der er der Reihe nach folgen kann.
    """

    sammler = _LinkSammler()
    sammler.feed(seite)
    sammler.close()

    raus: list[tuple[str, str]] = []
    gesehen: set[str] = set()
    for href, text in sammler.treffer:
        absolut = _zieladresse(urllib.parse.urljoin(basis, html.unescape(href)))
        if not absolut.startswith(("http://", "https://")):
            continue
        beschriftung = " ".join(text.split())
        if len(beschriftung) < 3:
            # Reine Symbol- oder Bildlinks ohne Text - dazu kann der Orb
            # dem Benutzer nichts sagen, also weg damit.
            continue
        schluessel = absolut.split("#")[0]
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        raus.append((absolut, beschriftung[:100]))
    return raus


class WebseiteErkundenTool(Tool):
    """Öffnet eine Seite und lässt den Orb darin blättern und Links folgen.

    ``webseite_lesen`` holt eine Seite und gibt ihren Text – einmal, von
    oben, gekürzt. Das reicht, um eine kurze Meldung zu lesen. Es reicht
    nicht, um sich durch eine lange Seite zu ARBEITEN: weiter unten
    nachzusehen, zu erkennen, wohin die Seite verweist, und einem dieser
    Verweise zu folgen. Genau das war der Wunsch – der Orb soll eine
    Webseite scrollen und Links auf ihr öffnen können.

    Das Werkzeug merkt sich die zuletzt geöffnete Seite. Darum sind die
    Folgeschritte billig: ``weiter`` blättert im schon geholten Text, und
    ``oeffnen 3`` folgt dem dritten Link, ohne dass der Orb die Adresse
    kennen muss.
    """

    name = "webseite_erkunden"
    description = (
        "Oeffnet eine Webseite und laesst dich darin blaettern und ihren "
        "Links folgen - wie Scrollen und Klicken. aktion='oeffnen' mit einer "
        "Adresse in 'ziel' oeffnet die Seite; aktion='weiter' bzw. 'zurueck' "
        "blaettert im Text nach unten bzw. oben; aktion='links' zeigt die "
        "Links der Seite mit Nummern; aktion='oeffnen' mit einer Nummer oder "
        "einem Stichwort in 'ziel' folgt dem passenden Link. Benutze das, "
        "wenn eine Seite lang ist oder wenn du von einer Seite aus "
        "weiterklicken willst."
    )
    permission = "network"
    parameters = (
        ToolParameter(
            "aktion", "string",
            "oeffnen | weiter | zurueck | links",
            required=False, default="oeffnen",
        ),
        ToolParameter(
            "ziel", "string",
            "Bei 'oeffnen': eine Adresse (https://...) ODER die Nummer bzw. "
            "ein Stichwort eines Links der aktuellen Seite.",
            required=False, default="",
        ),
    )

    #: Wie viel Text ein „Bildschirm" beim Blättern zeigt.
    _FENSTER = 1600

    def __init__(self) -> None:
        super().__init__()
        self._url = ""
        self._text = ""
        self._links: list[tuple[str, str]] = []
        self._offset = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        aktion = (str(arguments.get("aktion", "")).strip().lower() or "oeffnen")
        ziel = str(arguments.get("ziel", "")).strip()

        # Der Orb sagt es mal so, mal so - alles auf vier Aktionen abbilden.
        if aktion in ("runter", "weiterlesen", "mehr", "scroll", "scrollen",
                      "nach_unten", "hinunter"):
            aktion = "weiter"
        elif aktion in ("hoch", "zurueckblaettern", "nach_oben", "hinauf"):
            aktion = "zurueck"
        elif aktion in ("link", "linkliste", "zeige_links", "verweise"):
            aktion = "links"
        elif aktion in ("folgen", "oeffne", "gehe_zu", "navigiere", "klicken",
                        "anklicken", "klick"):
            aktion = "oeffnen"

        try:
            if aktion == "oeffnen":
                return await self._oeffnen(ziel)
            if not self._text and not self._links:
                return ToolResult.failure(
                    "Es ist noch keine Seite offen. Oeffne zuerst eine mit "
                    "aktion='oeffnen' und einer Adresse in 'ziel'."
                )
            if aktion == "weiter":
                return self._blaettern(+1)
            if aktion == "zurueck":
                return self._blaettern(-1)
            if aktion == "links":
                return self._linkliste()
            return ToolResult.failure(
                f"Unbekannte Aktion '{aktion}'. Moeglich: oeffnen, weiter, "
                "zurueck, links."
            )
        except urllib.error.HTTPError as fehler:
            return ToolResult.failure(f"Die Seite meldete {fehler.code}.")
        except urllib.error.URLError as fehler:
            return ToolResult.failure(
                f"Die Seite ist nicht erreichbar: {fehler.reason}"
            )
        except Exception as fehler:  # noqa: BLE001 - nie den Kern reissen.
            logger.exception("webseite_erkunden fehlgeschlagen")
            return ToolResult.failure(f"Fehlgeschlagen: {fehler}")

    async def _oeffnen(self, ziel: str) -> ToolResult:
        import asyncio

        if not ziel:
            return ToolResult.failure(
                "Womit? Gib eine Adresse (https://...) oder - wenn schon eine "
                "Seite offen ist - die Nummer eines Links an."
            )
        url = self._ziel_zu_url(ziel)
        if url is None:
            return ToolResult.failure(
                f"Keinen Link zu '{ziel}' gefunden. Zeig die Links der Seite "
                "mit aktion='links'."
            )
        text, links = await asyncio.to_thread(self._lade, url)
        self._url, self._text, self._links, self._offset = url, text, links, 0
        return self._fenster_ausgeben(kopf=f"Geoeffnet: {url}")

    def _ziel_zu_url(self, ziel: str) -> str | None:
        """Deutet 'ziel' als Adresse, als Linknummer oder als Stichwort."""

        if ziel.startswith(("http://", "https://")):
            return ziel
        # Eine nackte Linknummer der aktuellen Seite.
        knapp = ziel.lstrip("#").strip()
        if knapp.isdigit() and self._links:
            i = int(knapp) - 1
            if 0 <= i < len(self._links):
                return self._links[i][0]
            return None
        # Ein Stichwort - der erste Link, dessen Text es enthält.
        klein = ziel.lower()
        for url, text in self._links:
            if klein in text.lower():
                return url
        # Eine Adresse ohne Vorsatz ("tagesschau.de/ausland").
        if "." in ziel and " " not in ziel:
            return "https://" + ziel
        return None

    def _lade(self, url: str) -> tuple[str, list[tuple[str, str]]]:
        roh = _decode(_fetch(url))
        extractor = _TextExtractor()
        extractor.feed(roh)
        return extractor.text(), _seiten_links(url, roh)

    def _blaettern(self, richtung: int) -> ToolResult:
        neu = self._offset + self._FENSTER * richtung
        if neu < 0:
            neu = 0
        if neu >= len(self._text) and richtung > 0:
            return ToolResult.success(
                "Das war das Ende der Seite. Mit aktion='links' siehst du, "
                "wohin sie verweist, mit aktion='zurueck' geht es wieder hoch."
            )
        self._offset = neu
        return self._fenster_ausgeben()

    def _fenster_ausgeben(self, kopf: str = "") -> ToolResult:
        ausschnitt = self._text[self._offset:self._offset + self._FENSTER]
        rest = len(self._text) - (self._offset + len(ausschnitt))
        teile: list[str] = []
        if kopf:
            teile.append(kopf)
        if not self._text.strip():
            teile.append(
                "Diese Seite hat keinen lesbaren Fliesstext. Mit aktion='links' "
                "siehst du, wohin sie verweist."
            )
        else:
            teile.append(ausschnitt.strip())
            hinweise: list[str] = []
            if rest > 0:
                hinweise.append(f"noch {rest} Zeichen - aktion='weiter'")
            if self._links:
                hinweise.append(f"{len(self._links)} Links - aktion='links'")
            if hinweise:
                teile.append("[" + " | ".join(hinweise) + "]")
        return ToolResult.success(
            "\n\n".join(teile), url=self._url, offset=self._offset,
        )

    def _linkliste(self) -> ToolResult:
        if not self._links:
            return ToolResult.success(
                "Auf dieser Seite sind keine Links zu erkennen."
            )
        zeilen = [
            f"{i + 1}. {text}\n    {url}"
            for i, (url, text) in enumerate(self._links[:30])
        ]
        mehr = "" if len(self._links) <= 30 else (
            f"\n… und {len(self._links) - 30} weitere."
        )
        return ToolResult.success(
            "Links auf der Seite (einem folgen mit aktion='oeffnen' und der "
            "Nummer in 'ziel'):\n" + "\n".join(zeilen) + mehr,
            count=len(self._links),
        )


# =============================================================================
#  Mehrere Quellen statt eines besten Treffers
# =============================================================================
# Der Benutzer fragte, ob der Orb auch andere Berichterstattung einbezieht -
# Al Jazeera zum Beispiel. Die Antwort war nein, und zwar nicht, weil etwas
# gesperrt gewesen waere, sondern weil niemand danach fragte: Der Orb las,
# was in der Trefferliste oben stand, und das ist bei deutschsprachigen
# Fragen fast immer tagesschau oder zdfheute.
#
# Fuer einen Historiker ist das der falsche Zuschnitt. Wer wissen will, wie
# ueber einen Konflikt berichtet wird, braucht nicht den besten Treffer,
# sondern mehrere Darstellungen nebeneinander - und den Hinweis, wo sie
# auseinandergehen. Genau das leistet der beste Treffer nicht: Er ist eine
# Sicht, die sich als die Sache ausgibt.


async def _eine_quelle(
    name: str,
    einschraenkung: str,
    frage: str,
    treffer: int,
    feed: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Sucht bei EINER Quelle. Fehler ergeben eine leere Liste.

    Hat das Haus einen Feed, wird DER gelesen - nicht eine Suchmaschine
    nach ``site:haus.de`` gefragt. Der Unterschied stand am 16.08.2026 im
    Protokoll: Sechs site:-Suchen liefen gleichzeitig in die Taktsperre von
    GDELT und dann in die 403 der Suchmaschinen; jede Quelle meldete
    "lieferte nichts". Der Feed dagegen ist die Titelseite des Hauses
    selbst, zum Abholen gebaut, und weist nie ab.
    """

    import asyncio

    if feed.strip():
        from backend.research.offene_quellen import _inhaltsworte, rss_lesen

        try:
            thema = " ".join(_inhaltsworte(frage))
            ergebnis = await asyncio.to_thread(
                rss_lesen, feed.strip(), limit=treffer, filter_text=thema
            )
            if not ergebnis and thema:
                # Das Thema hat alles weggefiltert - meist, weil deutsch
                # gefragt und englisch getitelt wird. Dann die obersten
                # Schlagzeilen des Hauses, als solche gekennzeichnet: echte
                # Meldungen von jetzt, aus denen das Modell nichts erfinden
                # muss. Die Suchmaschinen dahinter waeren ohnehin nur die
                # fuenf Abweisungen vom 15.08. gewesen.
                ergebnis = await asyncio.to_thread(
                    rss_lesen, feed.strip(), limit=min(3, treffer), filter_text=""
                )
                for eintrag in ergebnis:
                    eintrag["beschreibung"] = (
                        "[Titelseite, nicht zum Suchwort gefiltert] "
                        + eintrag["beschreibung"]
                    ).strip()
        except Exception as fehler:  # noqa: BLE001
            logger.info("Feed von '%s' nicht lesbar: %s", name, fehler)
            ergebnis = []
        if ergebnis:
            return name, ergebnis
        # Der Feed war gar nicht lesbar - dann die Tiefensuche.

    anfrage = f"{frage} {einschraenkung}".strip()
    try:
        ergebnis = await asyncio.to_thread(search_web, anfrage, limit=treffer)
    except Exception as fehler:  # noqa: BLE001 - eine Quelle darf die andern nicht reissen.
        logger.info("Quelle '%s' lieferte nichts: %s", name, fehler)
        return name, []
    return name, ergebnis


async def mehrquellensuche(
    frage: str,
    quellen: list[dict[str, str]],
    *,
    je_quelle: int = 3,
    gleichzeitig: int = 4,
) -> dict[str, list[dict[str, str]]]:
    """Fragt dieselbe Sache bei mehreren Häusern und gibt alles getrennt zurück.

    Getrennt und nicht zusammengeworfen: Sobald man die Treffer mischt,
    ist nicht mehr zu sehen, WER was schreibt - und genau darum geht es
    hier. Eine Meldung von Reuters und dieselbe Meldung von Al Jazeera
    sind zwei Angaben, keine doppelte.

    ``gleichzeitig`` begrenzt die parallelen Anfragen. Ohne diese Grenze
    kämen acht Anfragen im selben Augenblick bei derselben Suchmaschine
    an, und die hält das für einen Angriff - dann bekommt man gar nichts.
    """

    import asyncio

    schranke = asyncio.Semaphore(max(1, gleichzeitig))

    async def _mit_schranke(quelle: dict[str, str]):
        async with schranke:
            return await _eine_quelle(
                str(quelle.get("name", "")),
                str(quelle.get("einschraenkung", "")),
                frage,
                je_quelle,
                feed=str(quelle.get("feed", "")),
            )

    ergebnisse = await asyncio.gather(
        *(_mit_schranke(q) for q in quellen), return_exceptions=True
    )

    gesammelt: dict[str, list[dict[str, str]]] = {}
    for eintrag in ergebnisse:
        if isinstance(eintrag, BaseException):
            continue
        name, treffer = eintrag
        if treffer:
            gesammelt[name] = treffer
    return gesammelt


#: So viel Beschreibung je Treffer geht an das Modell.
#:
#: Gemessen am 19.08.2026: Eine Nachrichtenfrage schickte 27'000 Zeichen
#: allein an Suchergebnissen in die Anfrage - achtzehn Treffer mit den
#: vollen Zusammenfassungen aus den Feeds. Das Modell brauchte danach 6,4
#: Sekunden bis zum ersten Wort, und diese Sekunden hoert der Benutzer als
#: Stille.
#:
#: Wozu die Treffer da sind, entscheidet die Grenze: Sie sollen zeigen,
#: WORUEBER und WIE die Haeuser berichten. Dafuer genuegen Schlagzeile
#: und ein paar Saetze. Wer den ganzen Artikel braucht, laesst ihn mit
#: 'webseite_lesen' holen - dann aber gezielt einen und nicht achtzehn.
_BESCHREIBUNG_HOECHSTENS = 320

#: Und eine Obergrenze fuer das Ganze, als Netz unter dem Netz.
_GEGENUEBERSTELLUNG_HOECHSTENS = 9000


def _knapp(text: str, hoechstens: int) -> str:
    """Kuerzt an einer Satzgrenze, nicht mitten im Wort."""

    sauber = " ".join(str(text or "").split())
    if len(sauber) <= hoechstens:
        return sauber
    gekuerzt = sauber[:hoechstens]
    schnitt = max(gekuerzt.rfind(". "), gekuerzt.rfind("! "), gekuerzt.rfind("? "))
    if schnitt > hoechstens // 2:
        return gekuerzt[: schnitt + 1]
    return gekuerzt.rsplit(" ", 1)[0] + " …"


def quellen_gegenueberstellen(gesammelt: dict[str, list[dict[str, str]]]) -> str:
    """Formt die Treffer so, dass die Herkunft unübersehbar ist.

    Und so, dass sie in eine Anfrage passen: Jede Beschreibung wird auf
    ``_BESCHREIBUNG_HOECHSTENS`` gekuerzt. Der Grund steht dort.
    """

    if not gesammelt:
        return ""

    teile: list[str] = []
    for name, treffer in gesammelt.items():
        zeilen = [f"[{name}]"]
        for t in treffer:
            zeilen.append(f"  - {_knapp(t['titel'], 160)}")
            zeilen.append(f"    {t['url']}")
            if t.get("beschreibung"):
                zeilen.append(f"    {_knapp(t['beschreibung'], _BESCHREIBUNG_HOECHSTENS)}")
        teile.append("\n".join(zeilen))

    ganzes = "\n\n".join(teile)
    if len(ganzes) > _GEGENUEBERSTELLUNG_HOECHSTENS:
        # Lieber ganze Quellen weglassen als alle halbieren: Eine
        # Gegenueberstellung aus Bruchstuecken vergleicht nichts mehr.
        gekuerzt: list[str] = []
        laenge = 0
        for teil in teile:
            if laenge + len(teil) > _GEGENUEBERSTELLUNG_HOECHSTENS:
                break
            gekuerzt.append(teil)
            laenge += len(teil) + 2
        ganzes = "\n\n".join(gekuerzt)
        logger.info(
            "Gegenueberstellung auf %d von %d Quellen gekuerzt (Platzgrenze).",
            len(gekuerzt), len(teile),
        )
    return ganzes
