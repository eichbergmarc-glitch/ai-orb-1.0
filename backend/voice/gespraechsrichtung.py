"""Bin ich gemeint? - die Unterscheidung von Anrede und Hintergrundgespräch.

## Das Problem

Nach einer Antwort hört der Orb 45 Sekunden weiter zu, ohne dass man ihn
erneut wecken muss. Das ist bequem und richtig - aber in diesem Fenster
gilt bisher ALLES als Anweisung, was die Stimme des Benutzers hat. Im
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

## Warum im Zweifel geschwiegen wird

Ein übersehener Auftrag kostet eine Wiederholung. Eine Antwort auf ein
Gespräch, das dem Orb nicht galt, kostet Vertrauen - und in einem Raum
mit anderen Menschen ist sie peinlich. Deshalb: Bei ``unklar`` wird
zugehört und geschwiegen, nicht geraten. Ein ausdrücklich benannter
Zweifel ("Sag noch mal, ich war nicht sicher, ob du mich meinst") wäre
schlimmer als Stille - er unterbricht das Gespräch, das gerade nicht ihm
galt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Der eigene Name in allen Formen, in denen Whisper ihn liefert.
_ANREDE = (
    "orb", "orbi", "hallo orb", "hey orb", "orb,", "ork", "orp",
)

#: Befehlsformen. Ein Imperativ richtet sich an ein Gegenüber - und im
#: Raum steht nur eines, das Befehle entgegennimmt.
_BEFEHLE = (
    "such", "recherchier", "find", "zeig", "lies", "vorles", "erklär",
    "erklar", "erzähl", "erzahl", "sag mir", "sag mal", "nenn", "fass",
    "zusammenfass", "öffne", "oeffne", "starte", "schliess", "mach",
    "erstell", "schreib", "trag ein", "trag mir", "merk", "merke",
    "speicher", "lösche", "loesche", "verschieb", "rechne", "übersetz",
    "uebersetz", "vergleich", "prüf", "pruef", "hilf", "wiederhol",
    "eigne dir", "arbeite dich", "lerne", "lern", "stopp", "stop", "halt",
    "warte", "weiter", "genauer", "ausführlicher", "ausfuehrlicher",
)

#: Anreden in der zweiten Person Singular - die Anrede selbst.
_DU_FORMEN = (
    "kannst du", "weisst du", "weißt du", "hast du", "bist du",
    "willst du", "kennst du", "siehst du", "verstehst du", "machst du",
    "denkst du", "meinst du", "findest du", "könntest du", "koenntest du",
    "würdest du", "wuerdest du", "sag du", "du kannst", "du weisst",
    "dir bekannt", "deine meinung", "deiner meinung",
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
    schlicht = knapp.lower().strip(" .,!?;:")

    # 1. Der eigene Name schlaegt alles. Wer "Orb" sagt, meint den Orb -
    #    auch mitten im Satz und auch bei maessiger Erkennung.
    if any(f" {name} " in klein or klein.startswith(f" {name}") for name in _ANREDE):
        return Richtung("an_mich", "der eigene Name fiel", 1.0)

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

    # 5. Reines Fuellsel ohne Auftrag und ohne Frage.
    if schlicht in _FUELLSEL:
        return Richtung(
            "hintergrund",
            "Gesprächsfüllsel ohne Auftrag"
            + ("" if wurde_gefragt else " (es stand keine Rückfrage offen)"),
            0.8,
        )

    hat_befehl = any(f" {wort}" in klein for wort in _BEFEHLE)
    hat_du = any(form in klein for form in _DU_FORMEN)
    ist_frage = knapp.rstrip().endswith("?")

    # 6. Befehl oder Anrede in der zweiten Person: eindeutig gemeint.
    if hat_befehl or hat_du:
        return Richtung(
            "an_mich",
            "Befehlsform" if hat_befehl else "Anrede in der zweiten Person",
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
