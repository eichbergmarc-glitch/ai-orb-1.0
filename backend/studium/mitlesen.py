"""Am Gesagten erkennen, wo jemand steht.

## Warum nicht abfragen

Der Benutzer hat es unmissverständlich gesagt::

    "Der Orb soll auch nicht einfach plump irgendwelche Tests mit mir
     machen um sich meinen Wissensstand zu merken, er soll dies durch das
     Gespräch mit mir feststellen."

Er hat damit recht, und zwar aus einem Grund, der über den Geschmack
hinausgeht: Eine Prüfung misst, was jemand unter Prüfungsbedingungen
abrufen kann. Ein Gespräch zeigt, wie jemand über eine Sache denkt - und
das ist es, was ein Lehrender braucht. Ein guter Dozent merkt nach drei
Sätzen, mit wem er es zu tun hat, und stellt dafür keine einzige
Testfrage.

## Woran man es tatsächlich merkt

Vier Dinge, alle im Gesagten selbst, alle ohne Rückfrage zu haben:

1. **Die Art der Frage.** „Was heisst Morphem?" und „Warum scheitert der
   Morphembegriff beim Ablaut?" kommen von zwei verschiedenen Orten. Die
   erste fragt nach dem Namen einer Sache, die zweite setzt die Sache
   voraus und fragt nach ihrer Grenze.
2. **Die benutzten Begriffe.** Wer von sich aus „Allophon" sagt, hat das
   Wort irgendwo her. Das ist kein Beweis für Verstehen - aber ein
   Hinweis, den man nicht wegwerfen sollte.
3. **Die Selbstauskunft.** „Das kenne ich schon", „davon habe ich noch
   nie gehört", „ich verstehe nicht, wieso" - Menschen sagen erstaunlich
   oft geradeheraus, wo sie stehen. Man muss nur zuhören.
4. **Das Interesse.** „Erzähl mehr davon", „das ist spannend", „das
   interessiert mich weniger" - das steuert, wohin es weitergeht, und
   darum ging es dem Benutzer ausdrücklich.

## Was diese Datei NICHT kann, und warum das gesagt gehört

Sie liest Zeichen, sie versteht nicht. „Was ist ein Morphem?" kann von
einem Anfänger kommen oder von einem Professor, der prüft, ob der Orb es
weiss. Deshalb wiegt eine einzelne Beobachtung wenig, und deshalb ist
Widerspruch vorgesehen: Wer sich fortgeschritten zeigt und danach eine
Grundfrage stellt, verliert nicht seinen Stand - es kommt eine
Beobachtung hinzu, mehr nicht. Der Stand ist eine Vermutung, die sich
über viele Gespräche verdichtet, und sie soll sich auch wieder
verflüchtigen können.

Das Sprachmodell kann diese Einschätzung jederzeit übergehen: Es hört
dasselbe Gespräch, nur besser. Diese Datei liefert ihm einen Anhaltspunkt
und keine Vorschrift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.studium.landkarte import TIEFEN, Thema

# ---------------------------------------------------------------------------
#  Woran man die Art der Frage erkennt
# ---------------------------------------------------------------------------

#: „Was ist ...?" - gefragt wird nach dem Namen oder der Zugehörigkeit
#: einer Sache. Wer so fragt, hat die Sache noch nicht.
_FRAGT_NACH_DEM_WAS: tuple[str, ...] = (
    "was ist", "was heisst", "was heißt", "was bedeutet", "was versteht man",
    "was sind", "wer war", "wer ist", "wie nennt man", "wie heisst",
    "wie heißt", "erklär mir", "erkläre mir", "erklär mal", "was macht",
    "wofür steht", "wofuer steht", "kannst du mir sagen was",
)

#: „Wie macht man das?" - die Sache ist bekannt, gefragt ist ihr Gebrauch.
_FRAGT_NACH_DEM_WIE: tuple[str, ...] = (
    "wie analysier", "wie bestimm", "wie zerleg", "wie erkenne ich",
    "wie unterscheide ich", "wie wende ich", "zeig mir an einem beispiel",
    "gib mir ein beispiel", "an einem beispiel", "wie gehe ich vor",
    "wie würde man", "wie wuerde man", "kannst du das an", "üben",
    "ueben", "aufgabe dazu", "selbst probieren",
)

#: „Warum gilt das nicht?" - die Sache ist durchschaut, gefragt ist ihre
#: Grenze. Das ist die Frage, an der man einen Fortgeschrittenen erkennt.
_FRAGT_NACH_DER_GRENZE: tuple[str, ...] = (
    "warum gilt", "warum nicht", "wo stösst", "wo stoesst", "wo scheitert",
    "warum scheitert", "scheitert", "stösst an", "stoesst an",
    "an seine grenzen", "grenzen des", "grenzen der", "problem mit",
    "warum funktioniert", "reicht nicht aus", "was ist daran",
    "wo liegt die grenze", "was spricht dagegen", "gegenbeispiel",
    "widerspricht", "wie verhält sich das zu", "wie verhaelt sich das zu",
    "wie passt das zu", "welche position", "wer vertritt", "kontrovers",
    "streit", "forschungsstand", "kritik an", "problematisch an",
    "schwäche", "schwaeche", "einwand",
)

# ---------------------------------------------------------------------------
#  Woran man die Selbstauskunft erkennt
# ---------------------------------------------------------------------------

_SAGT_ER_KENNT_ES: tuple[str, ...] = (
    "das kenne ich", "das weiss ich", "das weiß ich", "kenn ich",
    "ist mir bekannt", "hatte ich schon", "weiss ich schon",
    "weiß ich schon", "das ist mir klar", "verstehe ich", "ist klar",
    "hab ich verstanden", "habe ich verstanden", "logisch",
)

_SAGT_ER_KENNT_ES_NICHT: tuple[str, ...] = (
    "nie gehört", "nie gehoert", "kenne ich nicht", "keine ahnung",
    "verstehe ich nicht", "versteh ich nicht", "ist mir nicht klar",
    "verstehe das nicht", "versteh das nicht", "verstehe ich nicht ganz",
    "nicht verstanden", "nicht ganz klar", "steig ich nicht durch",
    "kapier ich nicht", "sagt mir nichts", "noch nie", "was soll das sein",
    "bin ich überfragt", "bin ich ueberfragt", "verwirrt mich",
    "zu schnell", "nochmal langsam", "noch einmal langsam",
)

_ZEIGT_INTERESSE: tuple[str, ...] = (
    "das interessiert mich", "spannend", "erzähl mehr", "erzaehl mehr",
    "mehr davon", "weiter damit", "faszinierend", "das will ich verstehen",
    "darüber mehr", "darueber mehr", "genauer bitte", "vertiefen",
)

_ZEIGT_DESINTERESSE: tuple[str, ...] = (
    "interessiert mich nicht", "weniger interessant", "lass das",
    "anderes thema", "genug davon", "langweilig", "brauch ich nicht",
    "später mal", "spaeter mal",
)


@dataclass(slots=True)
class Beobachtung:
    """Was eine einzelne Äusserung über den Sprechenden verrät.

    Bewusst ohne Note. ``tiefe`` sagt, worüber gerade gesprochen wird,
    ``gewicht`` wie stark der Hinweis ist - eine beiläufige Bemerkung
    wiegt weniger als eine ausdrückliche Auskunft.
    """

    thema: str = ""
    tiefe: str = ""
    gewicht: float = 0.0
    #: Begriffe des Themas, die der Sprechende selbst benutzt hat.
    eigene_begriffe: tuple[str, ...] = ()
    #: Was er ausdrücklich über sich gesagt hat.
    selbstauskunft: str = ""
    interesse: int = 0  # +1 / 0 / -1
    gruende: list[str] = field(default_factory=list)

    @property
    def sagt_etwas(self) -> bool:
        """Ob überhaupt etwas zu lernen war."""

        return bool(
            self.tiefe or self.eigene_begriffe or self.selbstauskunft or self.interesse
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "thema": self.thema,
            "tiefe": self.tiefe,
            "gewicht": round(self.gewicht, 2),
            "eigene_begriffe": list(self.eigene_begriffe),
            "selbstauskunft": self.selbstauskunft,
            "interesse": self.interesse,
            "gruende": list(self.gruende),
        }


def _enthaelt(knapp: str, wendungen: tuple[str, ...]) -> str:
    for w in wendungen:
        if w in knapp:
            return w
    return ""


def _eigene_begriffe(knapp: str, thema: Thema | None) -> tuple[str, ...]:
    """Welche Fachbegriffe des Themas der Sprechende selbst benutzt hat.

    Nur Begriffe ab fünf Zeichen: „Wert" oder „Phon" fallen auch in
    gewöhnlicher Rede und wären kein Hinweis, sondern ein Zufall.
    """

    if thema is None:
        return ()
    gefunden: list[str] = []
    for begriff in thema.begriffe:
        b = begriff.lower()
        if len(b) < 5:
            continue
        # Als Wortanfang, nicht nur als ganzes Wort: Im Deutschen steckt
        # der Fachbegriff meist in einer Zusammensetzung - "Morphembegriff",
        # "Flexionsendung", "Kasusrektion". Wer so redet, hat den Begriff.
        if re.search(rf"(?:^|\W){re.escape(b)}\w*", knapp):
            gefunden.append(begriff)
    return tuple(gefunden)


def mitlesen(text: str, thema: Thema | None = None) -> Beobachtung:
    """Liest aus einer Äusserung, was sie über den Sprechenden verrät.

    Args:
        text: Was der Benutzer gesagt hat.
        thema: Das Thema, um das es geht - wenn bekannt. Ohne Thema
            lassen sich Fragetyp, Selbstauskunft und Interesse trotzdem
            ablesen, nur die Begriffe nicht.
    """

    knapp = " " + " ".join(str(text or "").lower().split()) + " "
    beobachtung = Beobachtung(thema=thema.kennung if thema else "")
    if len(knapp.strip()) < 3:
        return beobachtung

    # 1. Die Art der Frage. Von hinten nach vorn geprüft: Die Grenzfrage
    #    ist die aussagekräftigste, und wer sie stellt, hat meist auch
    #    eine Was-Wendung im Satz.
    if (treffer := _enthaelt(knapp, _FRAGT_NACH_DER_GRENZE)):
        beobachtung.tiefe, beobachtung.gewicht = "beurteilen", 0.7
        beobachtung.gruende.append(f"fragt nach der Grenze ({treffer!r})")
    elif (treffer := _enthaelt(knapp, _FRAGT_NACH_DEM_WIE)):
        beobachtung.tiefe, beobachtung.gewicht = "anwenden", 0.6
        beobachtung.gruende.append(f"fragt nach dem Gebrauch ({treffer!r})")
    elif (treffer := _enthaelt(knapp, _FRAGT_NACH_DEM_WAS)):
        beobachtung.tiefe, beobachtung.gewicht = "kennen", 0.6
        beobachtung.gruende.append(f"fragt nach dem Was ({treffer!r})")

    # 2. Die eigenen Begriffe. Sie heben die Einschätzung, ersetzen sie
    #    aber nicht: Ein Wort zu benutzen heisst nicht, es zu verstehen.
    beobachtung.eigene_begriffe = _eigene_begriffe(knapp, thema)
    if len(beobachtung.eigene_begriffe) >= 2:
        beobachtung.gewicht += 0.3
        beobachtung.gruende.append(
            "benutzt selbst " + ", ".join(beobachtung.eigene_begriffe[:3])
        )
        if beobachtung.tiefe == "kennen":
            # Wer die Begriffe hat und trotzdem nach dem Was fragt, fragt
            # nach einem EINZELNEN und nicht nach dem Gebiet.
            beobachtung.tiefe = "anwenden"
            beobachtung.gruende.append("kennt das Umfeld bereits")
    elif beobachtung.eigene_begriffe:
        beobachtung.gewicht += 0.15
        beobachtung.gruende.append(f"benutzt selbst {beobachtung.eigene_begriffe[0]}")

    # 3. Die Selbstauskunft schlägt alles. Wer sagt, dass er etwas nicht
    #    versteht, hat damit mehr gesagt als jede Frageform verrät.
    if (treffer := _enthaelt(knapp, _SAGT_ER_KENNT_ES_NICHT)):
        beobachtung.selbstauskunft = "kennt es nicht"
        beobachtung.tiefe, beobachtung.gewicht = "kennen", 1.0
        beobachtung.gruende.append(f"sagt es selbst ({treffer!r})")
    elif (treffer := _enthaelt(knapp, _SAGT_ER_KENNT_ES)):
        beobachtung.selbstauskunft = "kennt es"
        beobachtung.gewicht = max(beobachtung.gewicht, 0.8)
        if beobachtung.tiefe in ("", "kennen"):
            beobachtung.tiefe = "anwenden"
        beobachtung.gruende.append(f"sagt es selbst ({treffer!r})")

    # 4. Das Interesse steuert die Richtung, nicht die Tiefe.
    if _enthaelt(knapp, _ZEIGT_INTERESSE):
        beobachtung.interesse = 1
        beobachtung.gruende.append("zeigt Interesse")
    elif _enthaelt(knapp, _ZEIGT_DESINTERESSE):
        beobachtung.interesse = -1
        beobachtung.gruende.append("winkt ab")

    beobachtung.gewicht = round(min(1.0, beobachtung.gewicht), 2)
    return beobachtung


def einschaetzung_im_klartext(beobachtung: Beobachtung) -> str:
    """Was der Orb daraus mitbekommt - als Satz für den Systemtext.

    Klartext und keine Zahl: Das Sprachmodell soll den Anhaltspunkt
    abwägen können, und dafür muss es den Grund sehen. Eine Zahl ohne
    Begründung würde es entweder blind befolgen oder ganz übergehen.
    """

    if not beobachtung.sagt_etwas:
        return ""
    teile: list[str] = []
    if beobachtung.tiefe:
        teile.append(
            {
                "kennen": "Er scheint hier neu zu sein",
                "anwenden": "Er kennt die Grundbegriffe und will damit arbeiten",
                "beurteilen": "Er ist im Thema und fragt nach Grenzen",
            }[beobachtung.tiefe]
        )
    if beobachtung.selbstauskunft:
        teile.append(f"er sagt selbst: {beobachtung.selbstauskunft}")
    if beobachtung.interesse > 0:
        teile.append("das Thema interessiert ihn – dabeibleiben lohnt sich")
    elif beobachtung.interesse < 0:
        teile.append("er winkt ab – nicht darauf beharren")
    if not teile:
        return ""
    grund = "; ".join(beobachtung.gruende[:3])
    return (
        "ANHALTSPUNKT ZUM GEGENÜBER (aus dem Gesagten gelesen, keine "
        f"Gewissheit): {'. '.join(teile)}. Woran: {grund}. Wenn dein "
        "eigener Eindruck dagegen spricht, folge deinem Eindruck."
    )


def naechste_tiefe(bisher: str, beobachtung: Beobachtung) -> str:
    """Wie tief das Gespräch als Nächstes gehen sollte.

    Nicht eine Stufe höher, sondern dort, wo der andere gerade ist. Das
    ist der Unterschied zu einer Leiter: Wer eine Grundfrage stellt,
    bekommt eine Grundantwort - auch wenn er gestern über Forschung
    gesprochen hat.
    """

    if beobachtung.tiefe:
        return beobachtung.tiefe
    return bisher if bisher in TIEFEN else TIEFEN[0]
