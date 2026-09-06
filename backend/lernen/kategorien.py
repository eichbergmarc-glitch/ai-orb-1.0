"""Zu welcher Aufgabenkategorie gehört diese Anfrage?

Die Übergabe geschieht kategorienweise, also muss jede Anfrage einer
Kategorie zugeordnet werden. Die Zuordnung ist bewusst grob und
nachvollziehbar: Sie entscheidet nur, welche Messreihe gilt und ob das
lokale Modell diese Art Aufgabe schon übernehmen darf. Ein Fehlgriff kostet
eine Anfrage am falschen Modell, nicht die Sicherheit.

Vorhandene Erkenner werden wiederverwendet, statt eine neue Wortliste neben
die bestehenden zu stellen: die Fähigkeitsentscheidung für Handlungen, der
Fachblick des Professors, die Aktualitätserkennung.
"""

from __future__ import annotations

from typing import Any

#: Wenn nichts passt. Alltagsdialog ist die haeufigste und harmloseste
#: Kategorie - im Zweifel dorthin.
STANDARD = "alltagsdialog"

_WORTFELDER: dict[str, tuple[str, ...]] = {
    "programmierung": (
        "code", "python", "funktion", "fehler im code", "stacktrace",
        "programmier", "debug", "exception", "kompilier", "syntaxfehler",
    ),
    "recherche": (
        "recherch", "quelle", "quellen", "studie", "belege", "literatur",
        "ist das wahr", "stimmt es", "faktencheck",
    ),
    "geschichte_philosophie": (
        "geschicht", "philosoph", "antike", "mittelalter", "kant", "hegel",
        "platon", "aristoteles", "ethik", "erkenntnistheorie", "historisch",
        "jahrhundert", "krieg", "revolution",
    ),
    "rechnerbedienung": (
        "datei", "ordner", "programm", "browser", "mail", "e-mail", "termin",
        "kalender", "fenster", "bildschirm", "starte", "oeffne", "öffne",
    ),
    "gedaechtnis": (
        "merk dir", "merke dir", "karteikarte", "lernstand", "erinnere",
        "erinnerung", "vergiss", "was weisst du ueber mich", "meine vorlieben",
    ),
    "darstellung": (
        "fasse ", "zusammenfass", "argumentier", "erklaere ausfuehrlich",
        "erklär ausführlich", "schreib einen text", "aufsatz", "essay",
        "in fuenf saetzen", "in fünf sätzen", "kurz zusammen",
    ),
}


def kategorie_fuer(text: str, *, intent: Any | None = None) -> str:
    """Ordnet eine Anfrage einer der acht Kategorien zu.

    Die Reihenfolge der Prüfung ist die Reihenfolge der Spezifität: Ein
    Satz über eine Datei ist Rechnerbedienung, auch wenn er nebenbei nach
    Geschichte klingt.
    """

    knapp = " " + " ".join(str(text or "").lower().split()) + " "

    # Werkzeugauswahl zuerst: Wo ein deutlicher Handlungsauftrag steht,
    # entscheidet nicht das Thema, sondern die Ausfuehrung.
    try:
        from backend.orchestrator.faehigkeiten import entscheiden

        entscheidung = entscheiden(text, gesprochen=False, werkzeuge_vorhanden=True)
    except Exception:  # noqa: BLE001 - die Zuordnung darf nie etwas reissen.
        entscheidung = None

    for kategorie in (
        "programmierung",
        "gedaechtnis",
        "rechnerbedienung",
        "recherche",
        "geschichte_philosophie",
        "darstellung",
    ):
        if any(wort in knapp for wort in _WORTFELDER[kategorie]):
            return kategorie

    # Fragen, die nur ueber ein Werkzeug ehrlich zu beantworten sind.
    if any(
        wort in knapp
        for wort in (" wie spaet", " wie spät", " welcher tag", " datum ", " uhrzeit")
    ):
        return "werkzeugwahl"

    if entscheidung is not None and entscheidung.handlungsauftrag:
        return "werkzeugwahl"

    return STANDARD


__all__ = ["STANDARD", "kategorie_fuer"]
