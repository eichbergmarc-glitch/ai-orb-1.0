"""Die Fähigkeitsentscheidung: Braucht dieser Zug Werkzeuge?

Vorher war das ein einzelnes Schlüsselwort-Tor. In ``_answer_with_model``
stand sinngemäss: Ein gesprochener Zug bekommt nur dann Werkzeuge, wenn im
Satz eines von rund fünfzig Verben vorkommt. Fehlte das Verb, bekam das
Modell keine Werkzeuge - und antwortete, ohne handeln zu können, ohne dass
irgendwo stand, warum.

Im Protokoll vom 31.08.2026 ist das nachlesbar: „Gut, meine Vorlieben, es
muss entweder im ersten Stock sein oder im Parterre …" - eine Fortsetzung
des Auftrags, eine Wohnung zu suchen, ohne eigenes Verb. Ergebnis:
``Werkzeuge=False``. Der Orb konnte gar nicht suchen.

Was sich hier ändert, ist die Beweislast. Die Schlüsselwörter bleiben, aber
nur noch als **Signale**, die auf eine Entscheidung einzahlen. Und die
Voreinstellung dreht sich um: Ein gesprochener Zug bekommt Werkzeuge,
**ausser** er ist erkennbar reine Konversation. Der Grund steht schon in
der alten Fassung von ``braucht_werkzeuge``: „Ein Werkzeug zu viel im
Systemprompt kostet ein paar hundert Zeichen Kontext. Ein Werkzeug zu wenig
kostet die Aufgabe."

Dieselbe Entscheidung beantwortet drei Fragen an drei verschiedenen Toren,
damit sie nicht dreimal verschieden ausfallen:

* Tor 4 (Router): Ist das ein Handlungsauftrag? Dann darf ihn keine lokale
  Auskunft abfangen.
* Tor 5 (Professor): Ist das ein fachfremder Handlungsauftrag? Dann endet
  der Fachmodus.
* Tor 6 (Orchestrator): Bekommt das Modell Werkzeuge?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Faehigkeitsentscheidung:
    """Was dieser Zug darf und warum."""

    #: Ob dem Modell die Werkzeuge mitgegeben werden.
    werkzeuge: bool
    #: Ob nach etwas Aktuellem gefragt wird (vorab gesucht wird).
    aktualitaet: bool
    #: Ob der Satz den Orb zu einer Handlung auffordert.
    handlungsauftrag: bool
    #: 0.0 bis 1.0 - wie deutlich die Signale sind.
    konfidenz: float
    #: Im Klartext, geeignet fürs Protokoll.
    begruendung: str
    #: Welche Signale angeschlagen haben.
    signale: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "werkzeuge": self.werkzeuge,
            "aktualitaet": self.aktualitaet,
            "handlungsauftrag": self.handlungsauftrag,
            "konfidenz": round(self.konfidenz, 2),
            "begruendung": self.begruendung,
            "signale": list(self.signale),
        }


#: Wendungen, mit denen ein Mensch einen Auftrag einleitet, ohne selbst ein
#: Tätigkeitswort zu benutzen ("Kannst du mir …", "Ich hätte gern …").
_AUFTRAGSWENDUNGEN: tuple[str, ...] = (
    "kannst du", "koenntest du", "könntest du", "kannst du mir", "würdest du",
    "wuerdest du", "bitte ", "ich moechte", "ich möchte", "ich haette gern",
    "ich hätte gern", "ich brauche", "ich will", "du sollst", "soll ich dir",
    "mach mir", "mach mal", "tu mir", "hilf mir", "wiederhole die aufgabe",
    "die aufgabe lautet", "der auftrag", "fuehre aus", "führe aus",
)

#: Wendungen, an denen eine reine Wissens- oder Plauderfrage zu erkennen ist.
#: Sie zahlen NEGATIV ein - sie sprechen gegen Werkzeuge.
_KONVERSATIONSWENDUNGEN: tuple[str, ...] = (
    "was ist", "was sind", "was bedeutet", "wer war", "wer ist", "warum",
    "wieso", "weshalb", "erklaer mir", "erklär mir", "erklaere", "erkläre",
    "wie geht es dir", "wie heisst du", "wie heißt du", "was denkst du",
    "was haeltst du", "was hältst du", "erzaehl mir etwas", "erzähl mir etwas",
)

#: Wie stark ein Signal zählt. Absichtlich grob: Es geht um "deutlich" oder
#: "nicht deutlich", nicht um eine Nachkommastelle.
_GEWICHTE: dict[str, float] = {
    "handlungsverb": 0.5,
    "auftragswendung": 0.25,
    "eigenes_umfeld": 0.35,
    "aktualitaet": 0.4,
    "browserbefehl": 0.5,
    "selbstdiagnose": 0.5,
    "werkzeugname": 0.6,
    "konversationswendung": -0.3,
}


_quellen_zwischenspeicher: dict[str, Callable[..., Any]] | None = None


def _quellen() -> dict[str, Callable[..., Any]]:
    """Die vorhandenen Erkenner aus dem Orchestrator.

    Der Import steht in der Funktion und nicht oben: Der Orchestrator nutzt
    dieses Modul, ein Import auf Modulebene liefe im Kreis. Python legt das
    Ergebnis ohnehin ab, der Zugriff kostet also nur beim ersten Mal.
    """

    global _quellen_zwischenspeicher
    if _quellen_zwischenspeicher is None:
        from backend.orchestrator import orchestrator as _o

        _quellen_zwischenspeicher = {
            "braucht_werkzeuge": _o.braucht_werkzeuge,
            "braucht_aktuelles": _o.braucht_aktuelles,
            "betrifft_eigenes_umfeld": _o.betrifft_eigenes_umfeld,
            "ist_selbstdiagnose": _o.ist_selbstdiagnose,
            "ist_browser_befehl": _o.ist_browser_befehl,
        }
    return _quellen_zwischenspeicher


def _knapp(text: str) -> str:
    return " " + " ".join(str(text or "").lower().split()) + " "


def entscheiden(
    text: str,
    *,
    gesprochen: bool = False,
    vorlesungssegment: bool = False,
    werkzeuge_vorhanden: bool = True,
    werkzeugnamen: list[str] | tuple[str, ...] | None = None,
    schwelle: float = 0.45,
    im_zweifel_werkzeuge: bool = True,
) -> Faehigkeitsentscheidung:
    """Entscheidet einmal für den ganzen Zug, was er darf.

    Args:
        text: Was der Benutzer gesagt hat.
        gesprochen: Ob die Antwort vorgelesen wird. Nur dort wurde bisher
            überhaupt eingeschränkt.
        vorlesungssegment: Ein interner Vorlesungsabschnitt behält sein
            bisheriges Verhalten - dort sind Werkzeuge nicht gemeint.
        werkzeuge_vorhanden: Ob überhaupt Werkzeuge angemeldet sind.
        werkzeugnamen: Die angemeldeten Namen. Kommt einer davon im Satz
            vor, ist das das stärkste Signal überhaupt.
        schwelle: Ab welcher Konfidenz ein Handlungsauftrag gilt.
        im_zweifel_werkzeuge: Die umgedrehte Voreinstellung. ``False``
            stellt das alte Verhalten wieder her.
    """

    quellen = _quellen()
    knapp = _knapp(text)
    signale: list[str] = []
    punkte = 0.0

    def zaehle(name: str, trifft: bool) -> None:
        nonlocal punkte
        if trifft:
            signale.append(name)
            punkte += _GEWICHTE.get(name, 0.0)

    zaehle("handlungsverb", bool(quellen["braucht_werkzeuge"](text)))
    zaehle(
        "auftragswendung",
        any(wendung in knapp for wendung in _AUFTRAGSWENDUNGEN),
    )
    zaehle("eigenes_umfeld", bool(quellen["betrifft_eigenes_umfeld"](text)))
    aktualitaet = bool(quellen["braucht_aktuelles"](text))
    zaehle("aktualitaet", aktualitaet)
    zaehle("browserbefehl", bool(quellen["ist_browser_befehl"](text)))
    zaehle("selbstdiagnose", bool(quellen["ist_selbstdiagnose"](text)))
    zaehle(
        "werkzeugname",
        any(f" {name} " in knapp for name in (werkzeugnamen or ())),
    )
    reine_konversation = any(
        knapp.strip().startswith(wendung) for wendung in _KONVERSATIONSWENDUNGEN
    )
    zaehle("konversationswendung", reine_konversation)

    konfidenz = max(0.0, min(1.0, punkte))
    handlungsauftrag = konfidenz >= schwelle

    if not werkzeuge_vorhanden:
        return Faehigkeitsentscheidung(
            werkzeuge=False,
            aktualitaet=aktualitaet,
            handlungsauftrag=handlungsauftrag,
            konfidenz=konfidenz,
            begruendung="es sind keine Werkzeuge angemeldet",
            signale=tuple(signale),
        )

    if vorlesungssegment:
        # Unverändert: In einem Vorlesungsabschnitt sind Werkzeuge nicht
        # gemeint, und der Abschnitt soll ohne Umwege gesprochen werden.
        return Faehigkeitsentscheidung(
            werkzeuge=False,
            aktualitaet=aktualitaet,
            handlungsauftrag=False,
            konfidenz=konfidenz,
            begruendung="Vorlesungsabschnitt - unverändertes Verhalten",
            signale=tuple(signale),
        )

    if not gesprochen:
        return Faehigkeitsentscheidung(
            werkzeuge=True,
            aktualitaet=aktualitaet,
            handlungsauftrag=handlungsauftrag,
            konfidenz=konfidenz,
            begruendung="geschriebener Zug - Werkzeuge waren nie eingeschränkt",
            signale=tuple(signale),
        )

    if handlungsauftrag or aktualitaet:
        return Faehigkeitsentscheidung(
            werkzeuge=True,
            aktualitaet=aktualitaet,
            handlungsauftrag=handlungsauftrag,
            konfidenz=konfidenz,
            begruendung="deutlicher Auftrag: " + ", ".join(signale),
            signale=tuple(signale),
        )

    if reine_konversation and konfidenz <= 0.0:
        return Faehigkeitsentscheidung(
            werkzeuge=False,
            aktualitaet=False,
            handlungsauftrag=False,
            konfidenz=konfidenz,
            begruendung="erkennbar reine Wissens- oder Plauderfrage",
            signale=tuple(signale),
        )

    if im_zweifel_werkzeuge:
        # Der Zweifelsfall - und genau hier lag der Fehler.
        #
        # Ein Satz ohne eigenes Tätigkeitswort ("Gut, meine Vorlieben, es
        # muss im ersten Stock sein …") ist meistens die Fortsetzung eines
        # Auftrags. Ihn ohne Werkzeuge zu beantworten heisst, ihn nicht zu
        # beantworten.
        return Faehigkeitsentscheidung(
            werkzeuge=True,
            aktualitaet=aktualitaet,
            handlungsauftrag=False,
            konfidenz=konfidenz,
            begruendung="unklar - im Zweifel mit Werkzeugen",
            signale=tuple(signale),
        )

    return Faehigkeitsentscheidung(
        werkzeuge=False,
        aktualitaet=aktualitaet,
        handlungsauftrag=False,
        konfidenz=konfidenz,
        begruendung="kein Auftragssignal und Zweifelsregel abgeschaltet",
        signale=tuple(signale),
    )


__all__ = ["Faehigkeitsentscheidung", "entscheiden"]
