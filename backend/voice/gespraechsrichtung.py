"""Bin ich gemeint? - die Unterscheidung von Anrede und Hintergrundgespräch.

## Das Problem

Nach einer Antwort hört der Orb 45 Sekunden weiter zu, ohne dass man ihn
erneut wecken muss. Das ist bequem und richtig - aber in diesem Fenster
galt bisher ALLES als Anweisung, was die Stimme des Benutzers hat. Im
Protokoll vom 17.08.2026 sieht man, was daraus wird::

    13:40:12  "Ihr seid, wenn ihr sich etwas spürtzuschreifen ..."
    13:40:51  "Vielen Dank."
    13:41:12  "Die Kirchenweine und Schachtwäsche."
    13:42:07  "Ja, und in Spannung von dem Ding, was wir haben ..."

Nichts davon war an den Orb gerichtet. Es war ein Gespräch im Raum, ein
Fernseher, die eigene Lautsprecherstimme des Orb. Er hat es trotzdem
verarbeitet - mit Rechenzeit, mit Antworten, und mit dem Eindruck beim
Benutzer, der Orb rede wirr.

## Der Massstab

Nicht "verstehe ich den Satz?", sondern "ist er an MICH gerichtet?" - das
sind zwei verschiedene Fragen, und nur die zweite zählt hier. Vier
Anzeichen sprechen für eine Anrede:

* **Der Name.** "Orb" im Satz ist das stärkste Zeichen überhaupt.
* **Der Befehl.** Ein Imperativ ("such", "lies", "trag ein", "erklär")
  richtet sich an ein Gegenüber, und im Raum steht nur eines.
* **Die Frage an ein Du.** "Kannst du ...", "weisst du ...", "was machst
  du" - die zweite Person Singular ist die Anrede selbst.
* **Der Anschluss.** Eine kurze Antwort auf die eigene Rückfrage des Orb
  ("ja, mach das", "nein, lieber morgen") ist gemeint - aber nur, wenn er
  eben gefragt hat.

Und drei sprechen dagegen:

* **Andere Adressaten.** "ihr", "wir", ein anderer Name im Satz.
* **Kein Gehalt.** Gesprächsfüllsel ("vielen Dank", "ja genau", "ach so")
  ohne Frage und ohne Auftrag.
* **Zerfallene Sprache.** Sehr niedrige Erkennungssicherheit oder die
  typischen Whisper-Schleifen ("was wir haben, was wir haben") - das ist
  aufgeschnappter Ton, keine Rede an jemanden.

## Zwei Lücken aus dem Protokoll vom 18.08.2026

Am 18.08. um 11:21 lief eine fremde Stimme mit. Zwei ihrer Sätze kamen
durch, und beide zeigen einen Fehler in der ersten Fassung dieser Datei::

    11:21:48  "... Ich kann ja nicht erklären, wie das funktioniert ..."
    11:22:08  "... wie ich als Südpaulinsist, Hallo Orb!"

Der erste galt als **Befehlsform**, weil die Prüfung nach der Zeichenkette
" erklär" suchte - und die steckt auch in "erklären". Ein Infinitiv mitten
im Nebensatz ist aber kein Befehl. Ein Imperativ steht im Deutschen am
Anfang eines Satzes oder Teilsatzes ("Erklär mir die Julikrise"), nicht
hinter "ich kann ja nicht". Deshalb wird jetzt nur noch der SATZANFANG
geprüft, und dort auch nur die Imperativformen des Stammes.

Der zweite galt als **eigener Name**, weil "Hallo Orb" am Ende stand.
Whisper hängt bekanntlich vertraute Wendungen an, wenn der Ton am Schluss
undeutlich wird - und "Hallo Orb" ist die vertrauteste Wendung, die dieses
Mikrofon kennt. Fünfzig Wörter fremde Rede werden nicht dadurch zur
Anrede, dass am Schluss der Name auftaucht. Der Name zählt deshalb nicht
mehr, wenn er ALLEIN am Ende einer langen Äusserung steht, in der sonst
kein einziges Zeichen einer Anrede vorkommt.

## Die dritte Lücke: der abgeschnittene Name (19.08.2026)

Im wachen Zustand wird ein erneutes Weckwort abgeschnitten, bevor die
Frage an die KI geht - sonst stünde "Hallo Orb" mit in der Frage. Die
Richtungsprüfung bekam dadurch einen Text, aus dem die Anrede gerade
entfernt worden war, und entschied folgerichtig auf "unklar"::

    12:11:23  "Hallo Orb, genau dieses Dokument sollst du einlesen."
    12:12:30  "Hallo Orb, die Aufgabe ist klar an dich gerichtet ..."
    12:12:52  "Hallo Orb, Auftrag an dich, dieses Dokument einlesen."

Dreimal derselbe Auftrag, dreimal Schweigen. Die Prüfung wird deshalb
übersprungen, wenn das Weckwort gefallen ist - wer den Orb beim Namen
ruft, meint ihn, und das gilt unabhängig davon, was danach kommt. Zwei
Anzeichen fehlten ausserdem und sind ergänzt: die zweite Person in
Umkehrung ("sollst du einlesen") und die ausdrückliche Zuweisung
("Auftrag an dich").

## Die vierte Lücke: die Antwort auf die eigene Frage (20.08.2026)

Der Benutzer meldete wiederkehrend, dass Gesagtes im Wachfenster als
"nicht an mich gerichtet" verworfen wird, obwohl es das war. Das
Protokoll bestätigt es und benennt die Fälle::

    20.08. 04:35:36  "Ja, bitte, tu das."             -> unklar, verworfen
    20.08. 04:27:11  "Ja, wenn das reicht ... Danke." -> unklar, verworfen
    20.08. 04:24:58  "Erzählen wir etwas über den neuen Realismus
                      nach Markus Gabriel."           -> unklar, verworfen

Die Stimmerkennung war es NICHT - die Stimme kam jedes Mal durch, die
Erkennung lag bei 0.91. Es fehlten drei Dinge:

* **Die offene Frage des Orb zählte nicht.** ``wurde_gefragt`` wurde nur
  nach der Verstehens-Rückfrage gesetzt, nie wenn die eigene ANTWORT mit
  einer Frage endete ("Soll ich das eintragen?"). Die Zustimmung darauf
  ("Ja, bitte, tu das") galt als Zustimmung in einem fremden Gespräch.
  Jetzt gilt: Hat der Orb gerade selbst gefragt, ist die nächste klar
  verstandene Äusserung der zugelassenen Stimme die Antwort.
* **Der Wir-Imperativ fehlte.** "Erzählen wir ...", "Machen wir weiter"
  ist ein Auftrag in der Miteinander-Form - am Satzanfang, Verb vor
  "wir". Die Aussagestellung ("wir machen", "wir haben") bleibt dagegen
  ein Zeichen für ein Gespräch unter Menschen.
* **"tu" fehlte in den Befehlsstämmen** - das kürzeste Imperativ des
  Deutschen, und genau das, woran "Ja, bitte, tu das" auch ohne offene
  Frage erkennbar gewesen wäre.

## Warum im Zweifel geschwiegen wird

Ein übersehener Auftrag kostet eine Wiederholung. Eine Antwort auf ein
Gespräch, das dem Orb nicht galt, kostet Vertrauen - und in einem Raum
mit anderen Menschen ist sie peinlich. Schlimmer noch: Die fremden Sätze
bleiben im Gesprächsverlauf stehen und färben jede spätere Antwort ein.
Genau so entsteht der Eindruck, der Orb halluziniere und höre nicht mehr
damit auf. Deshalb: Bei ``unklar`` wird zugehört und geschwiegen, nicht
geraten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Der eigene Name in allen Formen, in denen Whisper ihn liefert.
_ANREDE = (
    "orb", "orbi", "hallo orb", "hey orb", "orb,", "ork", "orp",
)

#: Imperativstämme. Geprüft wird ausschliesslich am Anfang eines
#: Teilsatzes, und dort NUR der Imperativ: "such" und "suche". Weder
#: "sucht" (dritte Person) noch "suchen" (Infinitiv) zählen - beide
#: standen im Protokoll reihenweise in Saetzen ueber jemand anderen
#: ("und nun kommt ein besonderes Problem"). Und mitten im Satz zählt
#: gar keine Form: "ich kann ja nicht erklären" ist kein Auftrag.
_BEFEHLSSTAEMME = frozenset((
    "such", "recherchier", "find", "zeig", "lies", "vorles", "erklär",
    "erklar", "erzähl", "erzahl", "sag", "nenn", "fass", "zusammenfass",
    "öffn", "oeffn", "start", "schliess", "mach", "erstell", "schreib",
    "trag", "merk", "speicher", "lösch", "loesch", "verschieb", "rechn",
    "übersetz", "uebersetz", "vergleich", "prüf", "pruef", "hilf",
    "wiederhol", "eign", "lern", "führ", "fuehr", "erweiter", "optimier",
    "analysier", "versuch", "wechsel", "hol", "gib", "bring", "setz", "fahr",
    "füg", "fueg", "zähl", "zaehl", "überleg", "ueberleg", "korrigier",
    "änder", "aender", "entfern", "beantwort", "berechn", "beschreib",
    "nimm", "les", "spiel", "ruf", "leg", "stell", "streich", "halt",
    # Nachtraege vom 20.08.2026: "tu" ist das kuerzeste Imperativ des
    # Deutschen ("Ja, bitte, tu das" fiel durch); die uebrigen tragen
    # den Wir-Imperativ ("Fangen wir an", "Schauen wir uns das an").
    "tu", "fang", "schau", "geh", "beginn", "send", "schick", "notier",
))

#: Steuerworte, die als ganzer Teilsatz ein Befehl sind.
_STEUERWORTE = frozenset((
    "stopp", "stop", "halt", "warte", "weiter", "genauer", "ausführlicher",
    "ausfuehrlicher", "langsamer", "schneller", "lauter", "leiser",
    "abbrechen", "nochmal", "noch mal",
))

#: Mehrwortbefehle, die am Anfang eines Teilsatzes stehen.
_BEFEHLSANFAENGE = (
    "arbeite dich", "eigne dir", "trag ein", "sieh nach", "schau nach",
    "denk nach", "fass zusammen", "hör auf", "hoer auf",
)

#: Füllwörter vor dem eigentlichen Befehl. "Bitte such nach ..." und
#: "Und dann erklär mir ..." sind Befehle; das Vorgeplänkel wird
#: abgeschnitten, bevor der Satzanfang geprüft wird.
_VORLAUF = frozenset((
    "bitte", "und", "dann", "jetzt", "nun", "mal", "doch", "so", "also",
    "hey", "hallo", "orb", "ok", "okay", "ja", "nein", "aber", "noch",
    "kurz", "gleich", "dazu", "danach", "zuerst", "erst", "einmal",
    "vielleicht", "übrigens", "uebrigens", "ähm", "aehm", "äh", "aeh",
))

#: Anreden in der zweiten Person Singular - die Anrede selbst.
_DU_FORMEN = (
    "kannst du", "weisst du", "weißt du", "hast du", "bist du",
    "willst du", "kennst du", "siehst du", "verstehst du", "machst du",
    "denkst du", "meinst du", "findest du", "könntest du", "koenntest du",
    "würdest du", "wuerdest du", "sag du", "du kannst", "du weisst",
    "dir bekannt", "deine meinung", "deiner meinung",
    # Die Possessive der zweiten Person: "Erweitere dein Wissen",
    # "Optimiere deine Funktionsweise". Sie zielen auf etwas, das nur der
    # Orb hat. Das blosse " dir " und " dich " steht dagegen in jedem
    # Gespraech im Raum ("Verschiege dich endlich von Funkloechern") und
    # zaehlt deshalb NICHT - "Wie geht es dir?" kommt als Frage durch,
    # "Eigne dir das Wissen an" als Befehlsanfang.
    " dein ", " deine ", " deinen ", " deinem ", " deiner ", " deines ",
    # Die ausdrueckliche Zuweisung. "Auftrag an dich" und "die Aufgabe ist
    # klar an dich gerichtet" (Protokoll 19.08., 12:12) sind so deutlich,
    # wie eine Anrede nur sein kann.
    " an dich ", " für dich ", " fuer dich ",
)

#: Die zweite Person Singular in Aussagestellung: "du hast mir erzählt",
#: "du wolltest", "von dem du mir erzählt hast". Die Umkehrung ("hast
#: du") steht schon oben - die gerade Wortstellung fehlte, und mit ihr
#: fielen am 18.08. drei echte Aufträge durch ("Du wolltest mir noch die
#: Bilder zeigen"). Deutsche Verben der zweiten Person Singular enden
#: auf "-st"; es dürfen bis zu drei Wörter dazwischenstehen.
_DU_AUSSAGE = re.compile(r"\bdu\b(?:\s+\w+){0,3}\s+(\w*st)\b")

#: Und dieselbe Person in Umkehrung: "sollst du einlesen", "hörst du",
#: "musst du". Ohne sie fielen am 19.08.2026 die Auftraege durch, mit
#: denen der Benutzer fuenfmal hintereinander dasselbe verlangte
#: ("Genau dieses Dokument sollst du einlesen, bitte").
_DU_UMKEHR = re.compile(r"\b(\w*st)\s+du\b")

#: Wörter auf "-st", die keine Verbform der zweiten Person sind. Ohne
#: diese Liste würde "du ... das ist" fälschlich als Anrede gelten.
_KEIN_DU_VERB = frozenset((
    "ist", "erst", "fast", "selbst", "angst", "kunst", "dienst", "rest",
    "fest", "ernst", "durst", "gast", "post", "host", "lust", "frist",
    "list", "last", "most", "west", "ost", "test", "sonst", "meist",
    "zuerst", "obst", "brust", "wurst", "trost", "prost", "gerüst",
))


def _du_in_aussagestellung(klein: str) -> bool:
    """Ob im Text ein "du" mit zugehöriger Verbform der 2. Person steht."""

    for muster in (_DU_AUSSAGE, _DU_UMKEHR):
        for treffer in muster.finditer(klein):
            wort = treffer.group(1)
            if len(wort) >= 4 and wort not in _KEIN_DU_VERB:
                return True
    return False

#: Der Wunsch als verkleideter Auftrag. "Ich möchte vor allem Bilder zu
#: den Weltbränden" (Protokoll 18.08., 11:08) ist eine Anweisung, auch
#: wenn kein Imperativ und kein "du" darin steht. Geprüft wird wieder nur
#: der Anfang eines Teilsatzes - "er möchte" oder "sie hätte gern" fallen
#: damit heraus, denn dort geht es um jemand anderen.
_WUNSCHFORMEN = (
    "ich möchte", "ich moechte", "ich hätte gern", "ich haette gern",
    "ich hätte gerne", "ich haette gerne", "ich brauche", "ich bräuchte",
    "ich braeuchte", "ich wünsche", "ich wuensche",
    "ich würde gern", "ich wuerde gern", "ich suche", "ich warte",
    "mich interessiert", "mich würde interessieren", "zeig mir",
)

#: Zeichen dafür, dass jemand ANDERES gemeint ist.
_ANDERE_ADRESSATEN = (
    " ihr seid", " ihr habt", " ihr macht", " ihr könnt", " ihr koennt",
    " wir haben", " wir machen", " wir sind", " wir müssen", " wir muessen",
    " sie haben ", " sie sind ", " euch ", " euer ", " eure ",
    " schatz ", " mama", " papa", " liebling",
)

#: Reines Gesprächsfüllsel: höflich, aber ohne Auftrag und ohne Frage.
_FUELLSEL = frozenset((
    "vielen dank", "danke", "danke schön", "danke schoen", "ja genau",
    "genau", "ach so", "aha", "okay", "ok", "alles klar", "na gut",
    "gut", "ja", "nein", "mhm", "hm", "so", "also", "tschüss", "tschuess",
    "bis bald", "sehr gut", "schön", "schoen", "eben", "richtig",
    "stimmt", "klar", "verstehe", "sicher", "natürlich", "natuerlich",
))

#: Kurze Zustimmungen, die NUR als Antwort auf eine Rückfrage zählen.
_ANSCHLUSS = frozenset((
    "ja", "ja bitte", "ja gerne", "ja genau", "ja mach das", "mach das",
    "ja, mach das", "nein", "nein danke", "lieber nicht", "nicht jetzt",
    "später", "spaeter", "morgen", "okay", "ok", "einverstanden",
    "genau so", "bitte", "gerne", "ja klar", "auf jeden fall",
))

#: Ab dieser Länge gilt eine Äusserung als lange Rede - und der eigene
#: Name ganz am Schluss zählt dann nicht mehr als Anrede.
_LANGE_REDE = 20

#: So viele Wörter am Schluss gelten als "ganz am Ende".
_SCHWANZ = 3


@dataclass(slots=True)
class Richtung:
    """Das Urteil: an mich, Hintergrund, oder unklar."""

    art: str  # "an_mich" | "hintergrund" | "unklar"
    grund: str
    sicherheit: float = 0.0

    @property
    def antworten(self) -> bool:
        """Ob geantwortet werden soll. Nur bei klarer Anrede."""

        return self.art == "an_mich"

    def to_dict(self) -> dict[str, object]:
        return {
            "art": self.art,
            "grund": self.grund,
            "sicherheit": round(self.sicherheit, 2),
        }


def _ist_geplapper(text: str) -> bool:
    """Erkennt Whisper-Schleifen: dieselbe Wortgruppe immer wieder.

    "was wir haben, was wir haben, was wir haben" ist kein Satz, den
    jemand gesagt hat - es ist das bekannte Verhaken der Spracherkennung
    an einem undeutlichen Tonband. So etwas war nie an den Orb gerichtet.
    """

    worte = re.findall(r"\w+", text.lower())
    if len(worte) < 8:
        return False
    # Zwei- und Dreiwortgruppen zaehlen: Wiederholt sich eine davon mehr
    # als dreimal, ist es eine Schleife.
    for laenge in (2, 3):
        gruppen: dict[tuple[str, ...], int] = {}
        for i in range(len(worte) - laenge + 1):
            schluessel = tuple(worte[i:i + laenge])
            gruppen[schluessel] = gruppen.get(schluessel, 0) + 1
        if gruppen and max(gruppen.values()) >= 4:
            return True
    # Oder: sehr wenige verschiedene Woerter auf viel Text.
    return len(set(worte)) <= len(worte) / 3


def _teilsaetze(klein: str) -> list[list[str]]:
    """Zerlegt in Teilsätze und schneidet das Vorgeplänkel ab.

    Aus "Ja, und dann erklär mir bitte die Julikrise" werden die
    Teilsätze ["ja"] und ["und", "dann", "erklär", ...]; das Vorgeplänkel
    faellt weg, sodass "erklär" am Anfang steht. Genau darauf kommt es
    an: Ein Imperativ eroeffnet den Satz, ein Infinitiv steht hinten.
    """

    ergebnis: list[list[str]] = []
    for teil in re.split(r"[.!?;:,]+", klein):
        worte = teil.split()
        while worte and worte[0] in _VORLAUF:
            worte.pop(0)
        if worte:
            ergebnis.append(worte)
    return ergebnis


def _befehl_am_satzanfang(klein: str) -> str | None:
    """Sucht einen Imperativ oder Wunsch am Anfang eines Teilsatzes.

    Der Rueckgabewert ist das gefundene Wort - er steht im Protokoll und
    macht spaeter nachvollziehbar, woran der Orb den Auftrag erkannt hat.
    """

    for worte in _teilsaetze(klein):
        erstes = worte[0]

        # Der Wunsch als verkleideter Auftrag: "Ich möchte Bilder dazu".
        satzanfang = " ".join(worte[:3])
        if any(satzanfang.startswith(w) for w in _WUNSCHFORMEN):
            return satzanfang

        # Ein Steuerwort als ganzer Teilsatz: "Stopp", "Weiter", "Lauter".
        if erstes in _STEUERWORTE and len(worte) <= 2:
            return erstes

        # Mehrwortbefehle: "eigne dir", "arbeite dich", "trag ein".
        anfang = " ".join(worte[:2])
        if any(anfang.startswith(b) for b in _BEFEHLSANFAENGE):
            return anfang

        # Der Wir-Imperativ (Hortativ): "Erzählen wir etwas über den
        # neuen Realismus", "Machen wir weiter", "Fangen wir an". Das
        # Verb steht VOR dem "wir" - genau daran unterscheidet er sich
        # von der Aussage ("wir machen", "wir haben"), die weiter als
        # Zeichen fuer ein Gespraech unter Menschen gilt. Im Studium
        # ist diese Form die natuerlichste Auftragsform ueberhaupt.
        if len(worte) >= 2 and worte[1] == "wir" and erstes.endswith("n"):
            stamm = erstes[:-2] if erstes.endswith("en") else erstes[:-1]
            if stamm in _BEFEHLSSTAEMME:
                return f"{erstes} wir"

        # Der Stamm als Imperativ - mit und ohne das angehaengte "e".
        for endung in ("", "e"):
            if erstes.endswith(endung):
                stamm = erstes[: len(erstes) - len(endung)] if endung else erstes
                if stamm in _BEFEHLSSTAEMME:
                    return erstes
    return None


def _name_ist_anrede(knapp: str, klein: str, satzweise: str) -> bool:
    """Ob der eigene Name im Satz wirklich eine Anrede ist.

    Normalerweise ja: Wer "Orb" sagt, meint den Orb. Die eine Ausnahme
    steht im Protokoll vom 18.08.2026, 11:22:08 - fuenfzig Woerter
    fremder Rede, an deren Ende Whisper "Hallo Orb!" angehaengt hat. Die
    Spracherkennung tut das zuverlaessig, wenn der Ton am Schluss
    zerfaellt: Sie greift nach der vertrautesten Wendung, die sie kennt.
    Steht der Name ALLEIN ganz am Ende einer langen Rede, in der sonst
    kein Zeichen einer Anrede vorkommt, ist er ein Artefakt und keine
    Ansprache.
    """

    worte = klein.split()
    if len(worte) <= _LANGE_REDE:
        return True

    # Wo taucht der Name auf? Nur ganz hinten - oder auch vorher?
    vorne = " " + " ".join(worte[: max(0, len(worte) - _SCHWANZ)]) + " "
    if any(f" {name} " in vorne for name in _ANREDE):
        return True

    # Der Name steht nur im Schwanz. Gibt es sonst noch ein Zeichen?
    if knapp.rstrip().endswith("?"):
        return True
    if any(form in klein for form in _DU_FORMEN) or _du_in_aussagestellung(klein):
        return True
    if _befehl_am_satzanfang(satzweise):
        return True
    return False


def einschaetzen(
    text: str,
    *,
    sicherheit: float = 1.0,
    wurde_gefragt: bool = False,
    schwelle: float = 0.72,
) -> Richtung:
    """Beurteilt, ob eine Äusserung an den Orb gerichtet war.

    Args:
        text: Das Erkannte.
        sicherheit: Wie sicher die Spracherkennung war (0 bis 1).
        wurde_gefragt: Ob der Orb gerade selbst eine Rückfrage gestellt
            hat. Nur dann zählt ein blosses "ja" als Antwort an ihn.
        schwelle: Unter dieser Erkennungssicherheit gilt eine Äusserung
            ohne andere Anzeichen als aufgeschnappt.

    Returns:
        Das Urteil samt Begründung im Klartext - die steht im Protokoll
        und macht später nachvollziehbar, warum der Orb geschwiegen hat.
    """

    knapp = " ".join(str(text or "").split())
    if not knapp:
        return Richtung("hintergrund", "nichts verstanden")

    # Satzzeichen zu Leerzeichen: "Schatz, kommst du?" soll bei der Suche
    # nach " schatz " genauso treffen wie "mein Schatz kommt".
    klein = " " + re.sub(r"[,.!?;:]+", " ", knapp.lower()) + " "
    klein = re.sub(r"\s+", " ", klein)
    satzweise = knapp.lower()
    # Ohne Satzzeichen IM Innern: "Ja, bitte" und "ja bitte" sind
    # dieselbe Antwort - vorher scheiterte der Vergleich mit der
    # Anschlussliste am Komma, das Whisper mal setzt und mal nicht.
    schlicht = " ".join(
        re.sub(r"[,.!?;:]+", " ", knapp.lower()).split()
    )

    # "Tagebucheintrag" ist absichtlich ein vollstaendiger lokaler
    # Sprachbefehl. Er braucht weder eine Frageform noch das Weckwort; der
    # Orchestrator antwortet darauf mit der ausdruecklichen Diktierfreigabe.
    if schlicht in {
        "tagebucheintrag", "tagebuch eintrag", "tagebuchbild",
        "bild ins tagebuch", "bild in den tagebucheintrag",
        "bild zum tagebucheintrag",
    }:
        return Richtung("an_mich", "eindeutiger Tagebuchbefehl", 0.95)
    if (
        "tagebucheintrag" in schlicht
        and any(stamm in schlicht for stamm in (
            "erstell", "bestell", "starte", "beginne", "entfern", "lösch", "loesch",
        ))
    ):
        return Richtung("an_mich", "eindeutiger Tagebuchauftrag", 0.95)

    # 1. Der eigene Name schlaegt fast alles. Wer "Orb" sagt, meint den
    #    Orb - auch mitten im Satz und auch bei maessiger Erkennung. Die
    #    Ausnahme steht in _name_ist_anrede.
    if any(f" {name} " in klein or klein.startswith(f" {name}") for name in _ANREDE):
        if _name_ist_anrede(knapp, klein, satzweise):
            return Richtung("an_mich", "der eigene Name fiel", 1.0)
        return Richtung(
            "hintergrund",
            "der Name stand nur am Ende einer langen fremden Rede",
            0.85,
        )

    # 2. Zerfallene Sprache ist kein Gespraech mit jemandem.
    if _ist_geplapper(knapp):
        return Richtung("hintergrund", "Wortschleife ohne Inhalt", 0.9)

    # 3. Ein anderer Adressat schliesst den Orb aus.
    if any(zeichen in klein for zeichen in _ANDERE_ADRESSATEN):
        return Richtung("hintergrund", "an jemand anderen gerichtet", 0.85)

    # 4. Der Anschluss an eine eigene Rueckfrage - und sein Gegenteil.
    #
    # "Ja, mach das" ist beides: die Antwort auf eine Rueckfrage ODER
    # Zustimmung in einem Gespraech nebenan. Entscheidend ist allein, ob
    # der Orb eben gefragt hat. Diese Pruefung MUSS vor der Befehlsform
    # stehen - sonst faengt "mach" den Satz ab und der Orb antwortet auf
    # ein Gespraech, dem er nicht angehoerte.
    if schlicht in _ANSCHLUSS:
        if wurde_gefragt:
            return Richtung("an_mich", "Antwort auf die eigene Rückfrage", 0.9)
        return Richtung(
            "hintergrund",
            "kurze Zustimmung, aber es stand keine Rückfrage offen",
            0.8,
        )

    # 4b. Der Orb hat gerade SELBST gefragt - dann ist die nächste klar
    # verstandene Äusserung die Antwort, auch wenn sie länger ausfällt
    # als die Anschlussliste: "Ja, bitte, tu das", "Ja, wenn das reicht,
    # danke" (beide am 20.08. verworfen, beide waren Antworten). Wer
    # fragt, hat das Rederecht vergeben; das Schweigen auf die eigene
    # Frage zu erzwingen war der Fehler, nicht die Ausnahme. Die
    # Stimmprüfung davor stellt sicher, dass es die zugelassene Stimme
    # ist - und die Prüfungen 2 und 3 haben Wortschleifen und andere
    # Adressaten schon aussortiert.
    if wurde_gefragt and sicherheit >= schwelle:
        return Richtung("an_mich", "Antwort auf die eigene Frage", 0.8)

    # 5. Reines Fuellsel ohne Auftrag und ohne Frage.
    if schlicht in _FUELLSEL:
        return Richtung(
            "hintergrund",
            "Gesprächsfüllsel ohne Auftrag"
            + ("" if wurde_gefragt else " (es stand keine Rückfrage offen)"),
            0.8,
        )

    befehl = _befehl_am_satzanfang(satzweise)
    hat_du = any(form in klein for form in _DU_FORMEN) or _du_in_aussagestellung(klein)
    ist_frage = knapp.rstrip().endswith("?")

    # 6. Befehl oder Anrede in der zweiten Person: eindeutig gemeint.
    if befehl or hat_du:
        return Richtung(
            "an_mich",
            f"Auftrag am Satzanfang ({befehl})" if befehl
            else "Anrede in der zweiten Person",
            0.85,
        )

    # 7. Eine Frage ohne Anrede - im Zweifel gemeint, wenn sie klar
    #    verstanden wurde. Fragen stellt man einem Gegenueber.
    if ist_frage and sicherheit >= schwelle:
        return Richtung("an_mich", "Frage bei klarer Erkennung", 0.7)

    # 8. Alles Uebrige: Es fehlt jedes Zeichen einer Anrede.
    if sicherheit < schwelle:
        return Richtung(
            "hintergrund",
            f"kein Anzeichen einer Anrede, dazu unsicher erkannt ({sicherheit:.2f})",
            0.75,
        )
    return Richtung(
        "unklar",
        "klar verstanden, aber ohne Anrede, Frage oder Auftrag",
        0.5,
    )
