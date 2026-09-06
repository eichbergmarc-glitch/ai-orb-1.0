"""Wann etwas zu ZEIGEN ist - und wann Reden genügt.

## Die Korrektur, aus der diese Datei entstand

Zuerst baute jede Vorlesung dieselben acht Folien: Titel, Frage,
Gegenstand, Begriffe, Streit, Zusammenfassung, Literatur. Der Benutzer
hat das zurückgewiesen::

    "Also sind fertige Präsentationen auch nicht hilfreich. Der Orb muss
     je nach Thema entscheiden, ob es sinnvoll wäre eine bestimmte
     Thematik mit Folien und/oder Bildern zu untermauern."

Er hat recht, und es ist mehr als eine Geschmacksfrage. Eine Folie, die
nichts zeigt, was die Sprache nicht auch sagen könnte, ist schlimmer als
keine: Sie zieht den Blick weg vom Zuhören auf das Lesen von Text, den
man auch hätte hören können. Wer zu jedem Thema Folien macht, macht sie
zu Tapete.

## Woran man erkennt, dass ein Bild etwas beiträgt

Die Frage ist nicht „ist das Thema wichtig?", sondern: **Gibt es hier
etwas, das man SEHEN kann und das in Worten mühsam wäre?** Fünf Fälle,
in denen die Antwort ja lautet:

* **Raum.** Grenzen, Verbreitung, Wege, Karten. Die Benrather Linie in
  Worten zu beschreiben, dauert eine Minute; auf einer Karte ist sie
  sofort da.
* **Zeit.** Abfolgen, Gleichzeitigkeit, Dauer. Was parallel lief, hört
  man nicht - man sieht es.
* **Form.** Paradigmen, Bäume, Gliederungen, Formeln. Ein Satz in Felder
  zerlegt ist eine Tabelle und keine Erzählung.
* **Zahl.** Verläufe, Anteile, Vergleiche. Dafür gibt es Diagramme.
* **Der Gegenstand selbst.** Eine Handschrift, ein Gemälde, ein Ort, ein
  Gesicht. Wer über die Lascaux-Malereien spricht, ohne sie zu zeigen,
  redet über etwas, das der Hörer nie gesehen hat.

Und der Gegenfall, der ausdrücklich dazugehört: **Ein Argument sieht man
nicht.** Warum Arbitrarität nicht Beliebigkeit heisst, warum eine
Implikatur streichbar ist, warum Sprachwandel kein Verfall ist - das sind
Gedankengänge. Sie brauchen ein Gegenüber, das nachfragt, keine Folie.

## Wer entscheidet

Das Sprachmodell. Diese Datei liefert ihm die Frage, an der es sich
entscheidet, und einen Anhaltspunkt aus dem, was in der Landkarte über
das Thema vermerkt ist (``zeigenswert``). Sie entscheidet nicht selbst -
sie kennt den Gesprächsverlauf nicht, und der gibt am Ende den Ausschlag.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.studium.landkarte import Thema

#: Die fünf Gründe, aus denen sich Zeigen lohnt - und woran man sie im
#: Text erkennt. Die Stichworte sind Anhaltspunkte für das Modell, keine
#: Entscheidung: Sie stehen im Hinweistext, nicht in einem Schalter.
ANLAESSE_ZUM_ZEIGEN: dict[str, tuple[str, ...]] = {
    "Raum": (
        "Karte", "Grenze", "Verbreitung", "Gebiet", "Linie", "Region",
        "Wanderung", "Lage", "wo", "Atlas",
    ),
    "Zeit": (
        "Abfolge", "Chronologie", "Jahrhundert", "Epoche", "Phase",
        "Entwicklung", "vorher", "nachher", "gleichzeitig", "Zeitstrahl",
    ),
    "Form": (
        "Paradigma", "Tabelle", "Baum", "Struktur", "Gliederung", "Schema",
        "Modell", "zerlegen", "Aufbau", "Formel", "Muster",
    ),
    "Zahl": (
        "Anteil", "Verlauf", "Häufigkeit", "Frequenz", "Statistik",
        "Vergleich", "Prozent", "Kurve", "gestiegen", "gesunken",
    ),
    "Der Gegenstand selbst": (
        "Handschrift", "Gemälde", "Bauwerk", "Fundstück", "Porträt",
        "Inschrift", "Foto", "Abbildung", "Original", "Ansicht",
    ),
}

#: Wo Zeigen wenig beiträgt: Ein Gedankengang hat kein Aussehen.
NICHT_ZU_ZEIGEN: tuple[str, ...] = (
    "Begründung", "Argument", "Einwand", "Schluss", "Definition",
    "Unterscheidung", "Position", "Kontroverse", "Deutung",
)


@dataclass(slots=True)
class Urteil:
    """Ob und wozu sich hier etwas zeigen lässt."""

    lohnt_sich: bool
    gruende: tuple[str, ...] = ()
    vorschlaege: tuple[str, ...] = ()

    def als_hinweis(self) -> str:
        """Der Text, den das Sprachmodell zu sehen bekommt."""

        if not self.lohnt_sich:
            return (
                "ZUM ZEIGEN: Hier gibt es nichts Sehenswertes – das ist ein "
                "Gedankengang, kein Gegenstand. Erklär es im Gespräch und "
                "mach KEINE Folien. Eine Folie, die nur wiederholt, was du "
                "ohnehin sagst, zieht den Blick vom Zuhören weg."
            )
        was = ", ".join(self.vorschlaege) if self.vorschlaege else "eine Abbildung"
        return (
            "ZUM ZEIGEN: Hier lässt sich etwas sehen, und das lohnt sich – "
            f"{'; '.join(self.gruende)}. Vorschlag: {was}. Benutze "
            "'folien_zeigen', wenn du meinst, dass es der Sache dient. Auf "
            "die Folien gehört NUR, was man sehen muss – nicht das, was du "
            "ohnehin sagst."
        )


def lohnt_sich(text: str, thema: Thema | None = None) -> Urteil:
    """Beurteilt, ob Zeigen hier etwas beiträgt.

    Args:
        text: Worum es gerade geht - die Frage des Benutzers oder der
            Abriss des Themas.
        thema: Das Thema aus der Landkarte, wenn bekannt. Sein Feld
            ``zeigenswert`` wiegt am schwersten: Dort hat jemand
            nachgedacht, statt Stichworte zu zählen.
    """

    # Was in der Landkarte steht, schlaegt jede Worterkennung.
    if thema is not None and thema.zeigenswert:
        return Urteil(
            lohnt_sich=True,
            gruende=("das Thema hat einen sichtbaren Gegenstand",),
            vorschlaege=tuple(thema.zeigenswert),
        )

    knapp = " ".join(str(text or "").lower().split())
    if thema is not None:
        knapp += " " + thema.abriss.lower() + " " + " ".join(thema.begriffe).lower()
    if not knapp.strip():
        return Urteil(lohnt_sich=False)

    gefunden: list[str] = []
    for anlass, stichworte in ANLAESSE_ZUM_ZEIGEN.items():
        if any(w.lower() in knapp for w in stichworte):
            gefunden.append(anlass)

    if not gefunden:
        return Urteil(lohnt_sich=False)

    # Ein einzelner Treffer neben lauter Argumentwoertern ist zu wenig.
    argumentativ = sum(1 for w in NICHT_ZU_ZEIGEN if w.lower() in knapp)
    if len(gefunden) == 1 and argumentativ >= 2:
        return Urteil(
            lohnt_sich=False,
            gruende=("überwiegend Argument, kaum Anschauliches",),
        )

    return Urteil(
        lohnt_sich=True,
        gruende=tuple(f"hier geht es um {g}" for g in gefunden),
        vorschlaege=_vorschlaege(gefunden),
    )


def _vorschlaege(anlaesse: list[str]) -> tuple[str, ...]:
    """Was man bei diesen Anlässen konkret zeigen würde."""

    mittel = {
        "Raum": "eine Karte",
        "Zeit": "ein Zeitstrahl oder eine Gegenüberstellung",
        "Form": "eine Tabelle oder ein Baumdiagramm",
        "Zahl": "ein Diagramm",
        "Der Gegenstand selbst": "eine Abbildung des Gegenstands",
    }
    return tuple(mittel[a] for a in anlaesse if a in mittel)
