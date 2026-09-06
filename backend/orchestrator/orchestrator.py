"""Orchestrator – die Verteilungsschicht von AI-Orb.

Der Orchestrator analysiert jede Anfrage, bestimmt Intention und benötigte
Module und entscheidet insbesondere, **ob überhaupt ein Sprachmodell
benötigt wird**. Aufgaben wie "Datei öffnen", "Firefox starten" oder
"Terminal öffnen" werden vollständig lokal erledigt.

Der Orchestrator führt niemals selbst Systembefehle aus; sämtliche
Aktionen laufen über definierte Module (Sicherheitsvorgabe).

In AI-Orb v3 wird der Orchestrator vom Cognitive Core angesteuert und
arbeitet mit dem Agenten-Team zusammen; seine hier definierte Schnittstelle
bleibt dabei unverändert.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.ai.response_pipeline import is_valid_answer
from backend.config import get_config
from backend.events import event_types
from backend.events.event_bus import EventBus
from backend.evolution.live_development import parse_development_request
from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.conversation_manager import ConversationManager
from backend.orchestrator.verlaufsreparatur import (
    STANDARD_WECHSEL,
    antwort as reparatur_antwort,
    ist_reparaturbefehl,
)
from backend.orchestrator.intent_classifier import (
    CHAT,
    DOCUMENT,
    QUESTION,
    SMALL_TALK,
    IntentClassifier,
    IntentResult,
)
from backend.orchestrator.faehigkeiten import (
    Faehigkeitsentscheidung,
    entscheiden as faehigkeiten_entscheiden,
)
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import ProviderError
from backend.orchestrator.speech_stream import SpeechStream, remaining_after
from backend.orchestrator.task_router import RouteResult, TaskRouter
from backend.studium.vorlesungs_session import (
    ist_vorlesungssegment,
    lehrstoff_vervollstaendigen,
)
from backend.studium.vorlesungs_bilder import (
    bild_passt,
    bild_treffer_bewerten,
    bildsuchbegriffe,
    uebersichtsart,
    uebersichtskarten,
    vorlesungsfolie_titel,
    vorlesungsthema,
)
from backend.system.logging_setup import get_logger
from backend.system.performance_trace import (
    current_turn_trace,
    mark_stage,
    start_turn_trace,
)
from backend.system.terminal_control import parse_terminal_request

logger = get_logger(__name__)


@dataclass(frozen=True)
class TagebuchBefehl:
    """Ein ohne Sprachmodell eindeutig erkannter Tagebuchauftrag."""

    werkzeug: str
    argumente: dict[str, Any] = field(default_factory=dict)


_TAGEBUCH_EINTRAG = re.compile(
    r"^\s*(?:orb[,.]?\s*)?(?:"
    r"(?:neuer|neuen|einen)\s+tagebuch\s*eintrag|"
    r"tagebuch\s*eintrag|"
    r"schreib(?:e)?\s+(?:das\s+)?(?:in|ins)\s+(?:mein(?:em)?\s+)?tagebuch|"
    r"notier(?:e)?\s+(?:das\s+)?(?:in|im)\s+(?:mein(?:em)?\s+)?tagebuch"
    r")\s*[:,-]?\s*(?P<text>.+?)\s*$",
    re.IGNORECASE,
)

_TAGEBUCH_AUFNAHME_START = re.compile(
    r"^\s*(?:orb[,.]?\s*)?(?:(?:starte|beginne|mach(?:e)?|erstell(?:e)?)\s+(?:einen\s+)?"
    r"(?:neuen\s+)?tagebuch\s*eintrag|(?:neuer|neuen|ein)\s+"
    r"tagebuch\s*eintrag|tagebuch\s*eintrag)\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def _tagebuch_sprachform(text: str) -> str:
    """Vereinheitlicht haeufige Whisper-Formen von ``Tagebucheintrag``.

    In der realen Aufnahme vom 25.08. wurde daraus ``Tagebuchintrag``. Das
    fehlende ``e`` darf keinen mehrminuetigen freien Modellweg ausloesen:
    Gerade der Start eines Diktats muss lokal und deterministisch sein.
    """

    knapp = " ".join(str(text or "").lower().replace("-", " ").split())
    return re.sub(
        r"\btagebuch\s*(?:eintrag|intrag|eitrag|beitrag)\b",
        "tagebucheintrag",
        knapp,
        flags=re.IGNORECASE,
    )


def parse_tagebuch_befehl(text: str) -> TagebuchBefehl | None:
    """Erkennt Diktat und Buchbefehle lokal und bewahrt den Wortlaut.

    Ein Tagebucheintrag darf nicht davon abhaengen, ob ein Modell gerade
    erreichbar ist oder ein Werkzeugformat korrekt erzeugt. Nur der klar
    bezeichnete Vorspann wird entfernt; der eigentliche Text bleibt erhalten.
    """

    roh = str(text or "")
    # Interne Folgeauftraege einer Vorlesung koennen den letzten gesprochenen
    # Absatz enthalten. Stand dort zufaellig etwas ueber das Tagebuch, wurde
    # dieser technische Kontext bislang wie ein neuer Benutzerbefehl behandelt
    # und oeffnete das Tagebuch in einer Endlosschleife. Interne Regie ist nie
    # ein Tagebuchauftrag.
    if ist_vorlesungssegment(roh):
        return None
    start_knapp = _tagebuch_sprachform(roh)
    # Reale Whisper-Fehlform: "Hallo Orb, erstelle ..." wurde als
    # "Alle Orte bestellen ..." erkannt. Tagebucheintrag plus Startverb
    # und Artikel ist trotzdem eindeutig genug fuer den lokalen Weg.
    robuster_start = (
        "tagebucheintrag" in start_knapp
        and any(stamm in start_knapp for stamm in (
            "erstell", "bestell", "starte", "beginne", "mach einen", "mache einen",
        ))
        and any(w in start_knapp.split() for w in ("ein", "einen", "neuen", "neuer"))
        and not any(
            marker in start_knapp
            for marker in (
                "wie man", "wie erstelle ich", "erkläre mir", "erklaere mir",
                "beispiel für", "beispiel fuer", "was ist",
            )
        )
    )
    if _TAGEBUCH_AUFNAHME_START.match(roh) or robuster_start:
        return TagebuchBefehl("tagebuch_diktat_start")
    treffer = _TAGEBUCH_EINTRAG.match(roh)
    if treffer:
        eintrag = treffer.group("text").strip()
        # Gesprochene Absatzmarken werden in das bereits vom Tagebuch
        # verstandene, eindeutige Absatzzeichen uebersetzt.
        eintrag = re.sub(
            r"\s+(?:neuer|neue|naechster|nächster)\s+absatz\s+",
            " | ",
            eintrag,
            flags=re.IGNORECASE,
        )
        return TagebuchBefehl("tagebuch_schreiben", {"text": eintrag})

    knapp = " ".join(roh.lower().replace("-", " ").split())
    if "tagebuch" not in knapp:
        return None
    if any(w in knapp for w in ("öffne", "oeffne", "zeig", "zeige", "aufschlagen")):
        return TagebuchBefehl("tagebuch_zeigen", {})

    # Gezielte Aenderungen laufen ebenfalls lokal. Der eigentliche Wortlaut
    # darf nie zur Interpretation oder Umformulierung an ein Modell gehen.
    ersetzen = re.match(
        r"^\s*(?:orb[,.]?\s*)?ersetz(?:e)?\s+(?:im|in dem)\s+"
        r"(?:(?:letzten|jüngsten|juengsten)\s+)?tagebuch\s*eintrag\s+"
        r"(?P<alt>.+?)\s+(?:durch|mit)\s+(?P<neu>.+?)\s*[.!?]?\s*$",
        roh, flags=re.IGNORECASE,
    )
    if ersetzen:
        return TagebuchBefehl("tagebuch_aendern", {
            "modus": "ersetzen",
            "alt": ersetzen.group("alt").strip(" :,-"),
            "neu": ersetzen.group("neu").strip(" :,-"),
        })

    gesamt = re.match(
        r"^\s*(?:orb[,.]?\s*)?(?:ändere|aendere|ersetz(?:e)?)\s+"
        r"(?:den\s+)?"
        r"(?:(?P<lage>letzten|jüngsten|juengsten|ersten|ältesten|aeltesten)\s+)?"
        r"tagebuch\s*eintrag\s+(?:vollständig\s+|vollstaendig\s+)?"
        r"(?:zu|in|durch)\s*:?\s*(?P<text>.+?)\s*[.!?]?\s*$",
        roh, flags=re.IGNORECASE,
    )
    if gesamt:
        lage = (gesamt.group("lage") or "").lower()
        return TagebuchBefehl("tagebuch_aendern", {
            "modus": "ersetzen_gesamt",
            "text": gesamt.group("text").strip(" :,-"),
            "position": "erster" if lage in {"ersten", "ältesten", "aeltesten"} else "letzter",
        })

    anhaengen = re.match(
        r"^\s*(?:orb[,.]?\s*)?(?:ergänz(?:e)?|ergaenz(?:e)?|füg(?:e)?\s+hinzu)\s+"
        r"(?:(?:den|zum)\s+)?(?:(?:letzten|jüngsten|juengsten)\s+)?"
        r"tagebuch\s*eintrag(?:\s+um)?\s*:?\s*(?P<text>.+?)\s*[.!?]?\s*$",
        roh, flags=re.IGNORECASE,
    )
    if anhaengen:
        zusatz = anhaengen.group("text").strip(" .!?:,-")
        if zusatz:
            return TagebuchBefehl("tagebuch_aendern", {
                "modus": "anhaengen", "text": zusatz,
            })

    teil_entfernen = re.match(
        r"^\s*(?:orb[,.]?\s*)?(?:entfern(?:e)?|lösch(?:e)?|loesch(?:e)?)\s+"
        r"(?:bitte\s+)?(?:den\s+text\s+)?(?:aus|in)\s+(?:dem\s+)?"
        r"(?:(?:letzten|jüngsten|juengsten)\s+)?tagebuch\s*eintrag\s*:?\s*"
        r"(?P<text>.+?)\s*[.!?]?\s*$",
        roh, flags=re.IGNORECASE,
    )
    if teil_entfernen:
        return TagebuchBefehl("tagebuch_aendern", {
            "modus": "entfernen",
            "text": teil_entfernen.group("text").strip(" :,-"),
        })

    # Ohne genannten Aenderungstext beginnt ein gefuehrtes Diktat: Der Orb
    # sagt klar, welche Fassung jetzt gesprochen werden soll.
    aenderung_start = re.match(
        r"^\s*(?:orb[,.]?\s*)?(?P<art>ändere|aendere|bearbeite|"
        r"ergänze|ergaenze)\s+(?:bitte\s+)?(?:den\s+)?"
        r"(?:(?P<lage>ersten|ältesten|aeltesten|letzten|jüngsten|juengsten)\s+)?"
        r"tagebuch\s*eintrag\s*[.!?]?\s*$",
        roh, flags=re.IGNORECASE,
    )
    if aenderung_start:
        art = aenderung_start.group("art").lower()
        lage = (aenderung_start.group("lage") or "").lower()
        return TagebuchBefehl("tagebuch_aenderung_start", {
            "modus": "anhaengen" if art in {"ergänze", "ergaenze"} else "ersetzen_gesamt",
            "position": "erster" if lage in {"ersten", "ältesten", "aeltesten"} else "letzter",
        })

    if "letzten eintrag" in knapp and any(
        w in knapp for w in ("streich", "lösch", "loesch", "entfern")
    ):
        return TagebuchBefehl("tagebuch_streichen", {})
    entfernen = re.match(
        r"^\s*(?:orb[,.]?\s*)?(?:lösch(?:e)?|loesch(?:e)?|entfern(?:e)?)\s+"
        r"(?:bitte\s+)?(?:den\s+)?tagebuch\s*eintrag\s+"
        r"(?:über|ueber|mit|vom|von)\s+"
        r"(?:(?:den|dem|der|die|das|einen|einem|einer)\s+)?"
        r"(?P<suchtext>.+?)\s*[.!?]?\s*$",
        roh,
        flags=re.IGNORECASE,
    )
    if entfernen:
        suchtext = entfernen.group("suchtext").strip()
        uhrzeit = re.search(r"\b(\d{1,2})[.:](\d{2})\b", suchtext)
        if uhrzeit:
            suchtext = f"{uhrzeit.group(1)} {uhrzeit.group(2)}"
        return TagebuchBefehl(
            "tagebuch_streichen", {"suchtext": suchtext},
        )

    # Whisper erkennt "entferne" gelegentlich als "entfene". Datum und
    # Uhrzeit sind zur Auswahl sogar verlaesslicher als der Eintragstext.
    loeschauftrag = any(w in knapp for w in (
        "lösch", "loesch", "streich", "entfern", "entfen", "entfene",
    ))
    ganz = any(w in knapp for w in ("vollständig", "vollstaendig", "komplett", "ganzen eintrag"))
    if loeschauftrag and ("eintrag" in knapp or "tagebuch" in knapp) and (
        ganz or "aus dem" not in knapp
    ):
        if any(w in knapp for w in ("ersten", "ältesten", "aeltesten", "unteren")):
            return TagebuchBefehl("tagebuch_streichen", {"position": "erster"})
        uhrzeit = re.search(r"\b(\d{1,2})[.:](\d{2})\b", roh)
        if uhrzeit:
            return TagebuchBefehl(
                "tagebuch_streichen",
                {"suchtext": f"{uhrzeit.group(1)} {uhrzeit.group(2)}"},
            )
        if "heute" in knapp:
            return TagebuchBefehl("tagebuch_streichen", {"suchtext": "heute"})
        return TagebuchBefehl("tagebuch_streichen", {})
    return None


_ZAHLWORTE = {"eins": 1, "ein": 1, "erste": 1, "zwei": 2, "zweite": 2,
              "drei": 3, "dritte": 3, "vier": 4, "vierte": 4,
              "fünf": 5, "fuenf": 5, "fünfte": 5, "fuenfte": 5}


def parse_tagebuch_bild_befehl(text: str) -> TagebuchBefehl | None:
    """Erkennt Start und Auswahl des gefuehrten Tagebuch-Bilddialogs."""

    roh = str(text or "").strip()
    if ist_vorlesungssegment(roh):
        return None
    schlicht = " ".join(roh.lower().strip(" .!?").split())
    if schlicht in {
        "bild ins tagebuch", "bild in den tagebucheintrag",
        "bild zum tagebucheintrag", "tagebuchbild",
    }:
        return TagebuchBefehl("tagebuch_bild_suche_start")

    suche = re.match(
        r"^\s*(?:orb[,.]?\s*)?(?:such(?:e)?\s+(?:mir\s+)?|zeig(?:e)?\s+(?:mir\s+)?)?"
        r"(?:ein\s+)?bild\s+(?:von|vom|über|ueber|zu)\s+(?P<motiv>.+?)"
        r"(?:\s+(?:für|fuer|in)\s+(?:den\s+)?(?:tagebuch(?:eintrag)?|tagebucheintrag))?"
        r"\s*[.!?]?\s*$",
        roh, flags=re.IGNORECASE,
    )
    if suche and ("tagebuch" in schlicht or schlicht.startswith(("bild ", "suche ", "such "))):
        motiv = re.sub(
            r"\s+(?:für|fuer|in)\s+(?:den\s+)?(?:tagebuch(?:eintrag)?|tagebucheintrag)\s*$",
            "", suche.group("motiv"), flags=re.IGNORECASE,
        ).strip()
        return TagebuchBefehl("tagebuch_bild_suchen", {"begriff": motiv})

    auswahl = re.match(
        r"^\s*(?:nimm\s+|wähl(?:e)?\s+|waehl(?:e)?\s+)?(?:das\s+)?"
        r"(?:bild\s+(?:nummer\s+)?)?(?P<nummer>[1-5]|eins|ein|erste|zwei|zweite|"
        r"drei|dritte|vier|vierte|fünf|fuenf|fünfte|fuenfte)(?:\s*\.?)\s*$",
        roh, flags=re.IGNORECASE,
    )
    if auswahl:
        wert = auswahl.group("nummer").lower()
        return TagebuchBefehl(
            "tagebuch_bild_auswaehlen", {"nummer": int(wert) if wert.isdigit() else _ZAHLWORTE[wert]},
        )
    return None

#: Wörter, die eine Frage nach dem JETZT kennzeichnen.
#:
#: Eine Wortliste ist grob, und ich schreibe das hier hin, damit es
#: niemand für elegant hält: Sie wird Fälle übersehen und gelegentlich
#: einen zu viel fangen. Der Vergleich ist aber nicht "Wortliste gegen
#: perfekte Erkennung", sondern "Wortliste gegen ein Modell, das in der
#: Hälfte der Fälle nicht sucht". Ein überflüssiger Suchlauf kostet eine
#: Sekunde; eine ausgedachte Nachricht kostet das Vertrauen.
_JETZT_WOERTER: tuple[str, ...] = (
    "aktuell", "aktuelle", "aktuellen", "aktuelles", "neueste", "neuesten",
    "news", "nachricht", "nachrichten", "schlagzeile", "schlagzeilen",
    "heute", "gestern", "gerade", "momentan", "derzeit", "zurzeit",
    "inzwischen", "mittlerweile", "soeben", "eben erst", "diese woche",
    "letzte woche", "in den letzten", "stand der dinge", "wie steht es",
    "was ist los", "was gibt es neues", "was passiert", "letzter stand",
    "liveblog", "livestream", "wetter", "kurs", "preis", "börse", "boerse",
    "wechselkurs", "spielstand", "ergebnis von heute",
)

#: Wendungen, die ausdrücklich zur Suche auffordern.
_SUCHAUFTRAEGE: tuple[str, ...] = (
    "such", "suche", "recherchier", "schau nach", "sieh nach", "guck nach",
    "google", "im internet", "im netz", "nachschlagen", "nachsehen",
)

_PERSOENLICHE_JETZT_FRAGEN: tuple[str, ...] = (
    "wie geht es dir", "wie geht's dir", "wie gehts dir",
    "was machst du", "was tust du", "woran arbeitest du",
    "bist du gerade", "bist du heute",
)

#: "Finde heraus, warum die Suche nicht funktioniert" ist KEIN Suchauftrag.
#:
#: Am 19.08.2026 verlangte der Benutzer dreimal eine Fehlersuche im
#: eigenen Verhalten des Orb. Weil in jedem dieser Saetze das Wort
#: "Suche" oder "finde" stand, sprang die Vorabsuche an und legte dem
#: Modell Netzfunde vor::
#:
#:   10:10:42  "Führe eine Fehleranalyse durch und finde heraus, warum
#:              die Suche nicht funktioniert."
#:             -> gesucht, gefunden: "Numerische lineare Algebra"
#:
#: Das Modell bekam damit fremde Treffer zu einer Frage ueber sich selbst
#: - und antwortete entsprechend daneben. Wer nach dem eigenen Fehler
#: fragt, will kein Suchergebnis, sondern eine Pruefung.
_SELBSTDIAGNOSE: tuple[str, ...] = (
    "fehleranalyse", "selbstanalyse", "funktionstest", "selbsttest",
    "finde den fehler", "find den fehler", "such den fehler",
    "suche den fehler", "wo liegt der fehler", "was ist der fehler",
    "in deinem code", "deinen code", "dein code", "deinem quelltext",
    "warum du nicht", "warum du keine", "warum du kein",
    "warum die suche nicht", "warum deine", "warum dein ",
    "warum das nicht funktioniert", "warum es nicht funktioniert",
    "was bei dir nicht", "was bei dir schief",
    "prüfe deine", "pruefe deine", "prüf deine", "pruef deine",
    "analysiere deine", "analysier deine", "überprüfe deine",
    "ueberpruefe deine",
)


def ist_selbstdiagnose(text: str) -> bool:
    """Ob der Benutzer nach einem Fehler im Orb selbst fragt.

    Dann ist eine Internetsuche nicht bloss nutzlos, sondern schaedlich:
    Ihre Treffer verdraengen im Kontext genau das, was zur Antwort noetig
    waere - naemlich der eigene Zustand.
    """

    knapp = " " + " ".join((text or "").lower().split()) + " "
    return any(wendung in knapp for wendung in _SELBSTDIAGNOSE)


def provider_mode_command(text: str) -> str:
    """Erkennt einen ausdruecklichen Sprachbefehl zum Modellbetrieb.

    Die Erkennung bleibt absichtlich regelbasiert und lokal. Der Befehl,
    der die Cloud abschaltet, darf nicht erst an ein Cloud-Modell geschickt
    werden. Rueckgabe: ``offline``, ``auto``, ``status`` oder ``""``.
    """

    normalized = " ".join((text or "").lower().replace("-", " ").split())
    normalized = (
        normalized.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    wortliste = [word.strip(".,!?;:") for word in normalized.split()]
    words = set(wortliste)
    offline_target = any(
        marker in normalized
        for marker in (
            "offlinebetrieb", "offline betrieb", "offline modus", "offline mode",
            "of line betrieb", "lokales modell", "lokale modell", "lokaler ki",
            "lokale ki",
        )
    ) or "offline" in words
    online_target = any(
        marker in normalized
        for marker in (
            "onlinebetrieb", "online betrieb", "online modus", "online mode",
            "cloud modell", "automatische modellauswahl", "automatikbetrieb",
        )
    ) or "online" in words
    # Ein Zielwort irgendwo im Satz ist noch kein Befehl. Besonders in
    # Tagebuchtexten kommen Formulierungen wie "Im Offline-Modus läuft er"
    # und spaeter "aktuell verwende ich ..." vor. Die alte Suche fand darin
    # Ziel UND Verb und schaltete den Orb ungefragt um. Nur eine einleitende
    # Imperativform gilt als Aktion.
    befehlstext = re.sub(
        r"^(?:(?:hallo|hey|hi)\s+)?(?:orb|orp|org)[,.]?\s*", "", normalized
    )
    befehlstext = re.sub(r"^(?:bitte\s+)", "", befehlstext)
    aktions_treffer = re.match(
        r"^(?:du\s+sollst\s+)?(?:"
        r"schalt\w*|wechsel\w*|wechsle|aktivier\w*|deaktivier\w*|"
        r"beend\w*|verlass\w*|geh(?:e)?|"
        r"arbeite|nutz\w*|benutz\w*|verwend\w*|stell\w*"
        r")\b",
        befehlstext,
    )
    # Modusbefehle sind kurze, eigenstaendige Anweisungen. Diese Grenze ist
    # ein Sicherheitsgurt gegen Diktate, Zitate und Erklaerungen, in denen
    # am Anfang zufaellig ein Imperativ und viel spaeter das Wort "offline"
    # steht. Ein echter Umschaltbefehl braucht keine zwanzig Woerter.
    kurz_genug = len(befehlstext.split()) <= 16
    action = bool(aktions_treffer) and kurz_genug
    nach_aktion = (
        befehlstext[aktions_treffer.end():].strip()
        if aktions_treffer is not None
        else ""
    )
    # "Stell dir den Offlinebetrieb vor" und "Nutzen wir offline als
    # Beispiel" sind keine Systembefehle. Sie beginnen nur grammatisch wie
    # einer. Ebenso darf ein Auftrag, das WORT offline zu erklaeren oder zu
    # notieren, den Rechner nicht umschalten.
    if re.match(r"^(?:dir|wir|ich|man)\b", nach_aktion):
        action = False
    if any(
        marker in befehlstext
        for marker in (
            "als beispiel", "das wort offline", "wort offline",
            "erklaer", "beschreib", "zitier", "notier", "tagebuch",
        )
    ):
        action = False

    # Das Ziel muss NACH dem einleitenden Aktionswort stehen. Die alte
    # globale Suche konnte sonst zwei unabhaengige Satzteile miteinander
    # kombinieren: vorne "verwende", hinten "offline" - und schaltete um.
    target_after_action = False
    if action:
        tail_words = {
            word.strip(".,!?;:") for word in nach_aktion.split()
        }
        target_after_action = any(
            marker in nach_aktion
            for marker in (
                "offlinebetrieb", "offline betrieb", "offline modus",
                "offline mode", "of line betrieb", "lokales modell",
                "lokale modell", "lokaler ki", "lokale ki",
                "onlinebetrieb", "online betrieb", "online modus",
                "online mode", "cloud modell",
                "automatische modellauswahl", "automatikbetrieb",
            )
        ) or (
            bool(tail_words & {"offline", "online"})
            and bool(re.match(r"^(?:schalt\w*|wechsel\w*|wechsle|geh(?:e)?)\b", befehlstext))
        )
        action = target_after_action
    disable_offline = action and offline_target and any(
        marker in normalized
        for marker in (
            "ausschalt", "aus schalt", "deaktivier", "beende", "verlass",
            "zurueck online", "wieder online", "nicht mehr offline",
        )
    )
    disable_offline = disable_offline or (
        offline_target
        and action
        and (normalized.endswith(" aus") or " modus aus" in normalized)
    )
    if disable_offline or (online_target and action):
        return "auto"
    if offline_target and action:
        return "offline"
    if (
        (offline_target or online_target)
        and len(wortliste) <= 12
        and any(
        marker in normalized
        for marker in ("bist du", "sind wir", "ist der", "welcher modus", "status")
        )
    ):
        return "status"
    return ""


#: Wovon eine Frage handelt, die NIEMALS eine Internetsuche braucht.
#:
#: Das war die teuerste Fehlzündung im Protokoll des Benutzers. Die
#: Zeitwörter ("aktuell", "gerade", "zurzeit") stehen auch in Sätzen, die
#: mit der Welt nichts zu tun haben:
#:
#:   "Eine Darstellung ist AKTUELL sehr dunkel"              -> Orb-Animation
#:   "Befindest du dich ZURZEIT auf dem zweiten Bildschirm"  -> Fenster
#:   "lies das Dokument, das ich GERADE offen habe"          -> Datei
#:
#: Jeder dieser Sätze löste eine Suche bei sechs Nachrichtenhäusern aus,
#: und deren Schlagzeilen landeten im Kontext, bevor das Modell zu denken
#: anfing. Es sollte die Helligkeit des Orb erklären und bekam Nahost.
#: Nicht die Suche war kaputt - sie lief nur zur falschen Frage.
_EIGENES_UMFELD: tuple[str, ...] = (
    # Der Orb selbst
    "orb", "animation", "darstellung", "helligkeit", "leuchte",
    "dein fenster", "deine anzeige", "oberfläche", "oberflaeche",
    # Bildschirm und Fenster
    "bildschirm", "monitor", "fenster", "desktop", "taskleiste",
    # Lokales Material
    "dokument", "datei", "ordner", "verzeichnis", "pdf",
    # Der Orb als Programm
    "einstellung", "konfiguration", "config", "quelltext",
    "protokoll", "werkzeug", "gedächtnis", "gedaechtnis",
    # Der eigene Kalender.
    #
    # Mit fuehrendem Leerzeichen, und das ist hier wichtiger als sonst:
    # Ohne es faengt "termin" auch "Wahltermin" und "Liefertermin", und
    # dann unterbleibt bei einer Frage nach dem Wahltermin in den USA die
    # Suche - obwohl sie genau dort noetig waere.
    " termin", " kalender", " verabredung", " besprechung",
    "was steht an", "was habe ich vor", "was steht heute an",
    "was steht morgen an", "wann habe ich", "im kalender",
)


def betrifft_eigenes_umfeld(text: str) -> bool:
    """Ob es um den Orb, den Bildschirm oder lokales Material geht.

    Dann ist eine Internetsuche nicht bloss überflüssig, sondern schädlich:
    Ihre Treffer verdrängen im Kontext genau das, was zur Antwort nötig wäre.

    ACHTUNG, hier liegt eine Falle, in die ich schon getappt bin: „Betrifft
    den eigenen Rechner" heisst NICHT „braucht keine Werkzeuge" - es heisst
    fast immer das Gegenteil. Wer diese Funktion benutzt, um Werkzeuge
    abzuschalten, macht genau die Aufgaben unlösbar, für die der Orb da ist.
    Dafür gibt es ``braucht_werkzeuge``.
    """

    knapp = " " + " ".join(text.lower().split()) + " "
    return any(wort in knapp for wort in _EIGENES_UMFELD)


#: Tätigkeiten, die der Orb nur MIT einem Werkzeug ausführen kann.
#:
#: Diese Liste entstand aus einem Fehler, den ich selbst gebaut habe. Der
#: Ablauf schaltet für kurze Alltagsfragen auf das lokale Modell um und
#: nimmt ihm dabei die Werkzeuge weg - richtig für „erzähl mir einen Witz",
#: falsch für alles, was zu TUN ist. Ob eine Anfrage zum Tun gehört, wurde
#: an ``braucht_aktuelles`` abgelesen; als ich dort das Veto für Fragen
#: über den Orb einbaute, fiel dieser Satz des Benutzers durch:
#:
#:   „ich habe gerade ein Dokument geöffnet, erstelle ein Printscreen und
#:    lies das Dokument ein und merke es dir"
#:
#: Er landete beim lokalen Modell OHNE Werkzeuge - drei Aufträge, kein
#: Werkzeug, keine Lösung. Die Lehre: Ob gesucht werden muss und ob
#: gehandelt werden muss, sind zwei Fragen. Sie brauchen zwei Listen.
_WERKZEUG_TAETIGKEITEN: tuple[str, ...] = (
    # Sehen und aufnehmen
    "screenshot", "printscreen", "prinzscreen", "print screen", "bildschirmfoto",
    "schau", "sieh dir", "sieh mal", "guck", "zeig mir", "erkenn",
    # Lesen und einarbeiten
    "lies", "lies mir", "liest", "lesen", "einlesen", "vorlesen",
    "fasse zusammen", "zusammenfass", "durchles", "auswerten", "analysier",
    # Merken
    "merk dir", "merke dir", "merk es dir", "merke es dir", "speicher",
    "notier", "schreib auf", "behalte",
    # Dateien und Programme
    "öffne", "oeffne", "starte", "installier", "suche datei", "finde datei",
    "lege an", "erstelle", "erstell", "schreib", "lösche", "loesche",
    "verschiebe", "benenne",
    # Netz
    "such", "recherchier", "nachschlagen", "im internet", "webseite",
    # Mail
    "mail", "e-mail", "schreib eine mail", "sende",
    # Kalender. "Trag mir morgen 14 Uhr den Zahnarzt ein" enthaelt weder
    # das Wort Termin noch das Wort Kalender - und ohne diese Verben faellt
    # genau der Satz durch, mit dem man einen Termin eintraegt.
    "trag ein", "trag mir", "trag bitte", "eintrag", "eintragen",
    "vereinbar", "verschieb", "sag ab", "absagen", "erinner",
    "termin", "kalender",
)


def braucht_werkzeuge(text: str) -> bool:
    """Ob die Anfrage eine HANDLUNG verlangt und damit Werkzeuge braucht.

    Bewusst grosszügig: Ein Werkzeug zu viel im Systemprompt kostet ein
    paar hundert Zeichen Kontext. Ein Werkzeug zu wenig kostet die Aufgabe.
    """

    knapp = " " + " ".join(text.lower().split()) + " "
    if any(wort in knapp for wort in _WERKZEUG_TAETIGKEITEN):
        return True
    # Wer nach dem eigenen Fehler fragt, braucht Werkzeuge erst recht:
    # Dateien lesen, Protokolle durchsehen, den Selbsttest laufen lassen.
    # Ohne sie bleibt dem Modell nur die Behauptung - im Protokoll vom
    # 19.08.2026 stand woertlich "Ich hab den Code durchsucht und ...",
    # ohne dass eine einzige Datei geoeffnet worden waere.
    if ist_selbstdiagnose(text):
        return True
    # Ist von Bildschirm, Datei oder Dokument die Rede, geht es fast immer
    # um etwas, das auf diesem Rechner zu tun ist.
    return betrifft_eigenes_umfeld(text)


def will_pdf_erstellen(text: str) -> bool:
    """Ob der Benutzer jetzt eine PDF-Datei als Ergebnis verlangt."""

    knapp = " " + " ".join((text or "").lower().split()) + " "
    if "pdf" not in knapp:
        return False
    return any(
        marker in knapp
        for marker in (
            "erstell", "mach", "generier", "speicher", "exportier",
            "anleg", "druck", "als pdf", "pdf-datei",
        )
    )


def will_pdf_mit_grafik(text: str) -> bool:
    """Ob eine angeforderte PDF visuell erklaeren soll."""

    knapp = " " + " ".join((text or "").lower().split()) + " "
    return will_pdf_erstellen(text) and any(
        marker in knapp
        for marker in (
            " grafik", "infografik", "diagramm", "visuell", "anschaulich",
            "illustrier", " bebilder", " bild", " foto", " photo",
        )
    )


def will_pdf_mit_fotos(text: str) -> bool:
    """Ob ausdruecklich reale Fotos/Bilder statt nur Infografik gewuenscht sind."""

    knapp = " " + " ".join((text or "").lower().split()) + " "
    return will_pdf_erstellen(text) and any(
        marker in knapp
        for marker in (" foto", " photo", "bilder suchen", "echte bilder", "bebilder")
    )


def pdf_titel_aus(text: str) -> str:
    """Leitet fuer den deterministischen Rueckfall einen kurzen Titel ab."""

    cleaned = " ".join((text or "").strip().split())
    match = _re.search(
        r"(?:zum thema|zum|über|ueber|zu)\s+(.+?)(?:\s+und\s+(?:erstell|mach|speicher)|[.!?]?$)",
        cleaned,
        flags=_re.IGNORECASE,
    )
    candidate = match.group(1) if match else cleaned
    candidate = _re.sub(
        r"\b(?:erstelle?n?|mach(?:e)?|generiere?n?|pdf(?:-datei)?|mit|grafiken?|"
        r"infografiken?|diagrammen?|fotos?|photos?|bildern?|visuell|anschaulich)\b",
        " ",
        candidate,
        flags=_re.IGNORECASE,
    )
    candidate = " ".join(candidate.split()).strip(" -.,")
    return (candidate[:90].strip() or "AI-Orb Dokument")


def braucht_aktuelles(text: str) -> bool:
    """Ob eine Frage Wissen von JETZT verlangt.

    Zwei Wege führen zu ja: Der Benutzer fragt nach etwas Gegenwärtigem,
    oder er bittet ausdrücklich um eine Suche. Das zweite ist eine
    Anweisung und keine Gesprächsfloskel - ihr ist zu folgen.

    Ausdrücklich NICHT dabei ist die blosse Jahreszahl. "Was geschah
    1789?" braucht keine Suche, und eine Regel, die auf Jahreszahlen
    anspringt, würde bei einem Geschichtsprofessor bei jeder zweiten
    Frage suchen.
    """

    knapp = " " + " ".join(text.lower().split()) + " "
    # Zuerst das Veto, dann der Auftrag: "Finde heraus, warum die Suche
    # nicht funktioniert" enthaelt das Wort "Suche" und ist trotzdem
    # keine Bitte, im Netz zu suchen (siehe ist_selbstdiagnose).
    if ist_selbstdiagnose(text):
        return False
    if any(f" {wort}" in knapp for wort in _SUCHAUFTRAEGE):
        return True
    # "Wie geht es dir heute?" und "Was machst du gerade?" fragen nach
    # dem Orb, nicht nach dem Weltgeschehen. Zuvor starteten sie sechs
    # Nachrichtensuchen und lieferten anschließend fremde Webseiten.
    if any(wendung in knapp for wendung in _PERSOENLICHE_JETZT_FRAGEN):
        return False
    # Und dasselbe für alles, was den Orb, den Bildschirm oder eine Datei
    # betrifft: Dort ist ein Zeitwort eine Zeitangabe, keine Frage nach
    # der Welt (siehe betrifft_eigenes_umfeld).
    if betrifft_eigenes_umfeld(text):
        return False
    return any(wort in knapp for wort in _JETZT_WOERTER)


#: Ausdrueckliche Woerter fuer "mach ein Bild vom Bildschirm". Sie loesen
#: allein aus.
_BILDSCHIRM_DIREKT: tuple[str, ...] = (
    "screenshot", "screen shot", "printscreen", "print screen",
    "bildschirmfoto", "bildschirm-foto", "bildschirmaufnahme",
    # Wie die Spracherkennung "Printscreen" tatsaechlich schreibt.
    # Im Protokoll stand woertlich "erstelle ein Prinzscreen" - und weil
    # keine dieser Schreibungen hier stand, galt die klare Bitte nicht als
    # Bildschirmauftrag. Ein Verhoerer darf keine Faehigkeit kosten.
    "prinzscreen", "prinz screen", "printscream", "print scream",
    "prinzscream", "screenshoot", "screen-shot",
)

#: Das Wort fuer den Ort. Nur zusammen mit einem Seh-/Lesewort loest es aus -
#: sonst faenge man auch "mach den Bildschirm heller", was eine Einstellung
#: ist und kein Ansehen.
_BILDSCHIRM_ORT: tuple[str, ...] = (
    "bildschirm", "monitor", "auf dem schirm", "am schirm",
)

#: Die Absicht, hinzusehen oder zu lesen.
_BILDSCHIRM_SEHEN: tuple[str, ...] = (
    "schau", "sieh", "guck", "erkenn", "les", "lies", "beschreib",
    "analysier", "zeig mir was", "was siehst", "was ist", "was zeigt",
    "was laeuft", "was läuft", "zu sehen", "was steht", "welches",
    "was offen", "was gerade offen", "welches dokument", "was du siehst",
)


#: Woran ein WISSENSAUFTRAG zu erkennen ist: Der Benutzer will nicht eine
#: Antwort, sondern dass sich der Orb etwas dauerhaft erarbeitet.
#:
#: Belegt am 17.08.2026, 21:36: "Suche nach Markus Gabriel und eigne dir
#: sein Wissen an." Das Werkzeug dafuer existiert (wissen_aneignen), das
#: Modell nannte es - und rief es nicht. Auf "ja, mach das" behauptete es,
#: es habe nie einen Auftrag gegeben. Die bewaehrte Antwort auf dieses
#: Muster steht schon zweimal im Ablauf (Suche, Bildschirm): Wo die
#: Entscheidung feststeht, wird sie nicht delegiert.
_WISSENSAUFTRAG_ZEICHEN: tuple[str, ...] = (
    "eigne dir", "aneignen", "arbeite dich ein", "arbeite dich in",
    "einarbeiten", "lerne alles", "lern alles", "grundwissen",
    "vertiefe dein wissen", "vertief dein wissen", "dazulernen",
    "merke dir das wissen", "merk dir das wissen", "merke dir sein wissen",
    "merk dir sein wissen", "merke dir ihr wissen", "sein wissen an",
    "speichere das wissen", "speichere sein wissen", "studiere",
    "und merke dir sein", "und merk dir sein", "wissen aufbauen",
)


def will_wissensauftrag(text: str) -> bool:
    """Ob der Benutzer verlangt, dass sich der Orb Wissen ANEIGNET."""

    knapp = " " + " ".join((text or "").lower().split()) + " "
    return any(zeichen in knapp for zeichen in _WISSENSAUFTRAG_ZEICHEN)


def wissensthema_aus(text: str) -> str:
    """Zieht das Thema aus einem Wissensauftrag heraus.

    "Suche nach dem Philosophen Markus Gabriel und eigne dir sein Wissen
    an" -> "Philosophen Markus Gabriel". Erst wird das Stueck hinter
    ueber/zu/von/nach genommen und am Auftragsteil abgeschnitten; traegt
    das nichts, bleiben die Inhaltsworte des ganzen Satzes.
    """

    knapp = " ".join((text or "").split())
    treffer = _re.search(
        r"(?:^|\s)(?:ueber|über|zum thema|zur|zum|zu|von|nach|in die|in den|in das)\s+(.{3,80}?)"
        r"(?:\s+und\s+|\s*[.,!?;]|$)",
        knapp,
        _re.I,
    )
    kandidat = treffer.group(1).strip() if treffer else ""
    # Fuehrende Artikel abwerfen - "dem Philosophen" -> "Philosophen".
    kandidat = _re.sub(
        r"^(?:dem|der|die|das|den|des|einem|einer|dich in die|dich in|dich)\s+",
        "", kandidat, flags=_re.I,
    )
    # Das nachklappende Stueck des trennbaren Verbs ("eigne dir ... AN",
    # "arbeite dich ... EIN") ist kein Teil des Themas.
    kandidat = _re.sub(r"\s+(?:an|ein)$", "", kandidat, flags=_re.I)
    kandidat = _re.sub(r"^(?:dem|der|die|das|den|des)\s+", "", kandidat, flags=_re.I)
    # Ein Kandidat, der selbst nur Auftragsworte enthaelt, ist keiner.
    if kandidat and not will_wissensauftrag(kandidat):
        return kandidat

    from backend.research.offene_quellen import _inhaltsworte

    worte = [
        wort for wort in _inhaltsworte(knapp)
        if not any(zeichen.startswith(wort) for zeichen in _WISSENSAUFTRAG_ZEICHEN)
        and wort not in ("wissen", "eigne", "aneignen", "merke", "merk",
                         "speichere", "studiere", "lerne", "alles", "dich",
                         "einmal", "arbeite")
    ]
    return " ".join(worte[:6])


def will_bildschirm(text: str) -> bool:
    """Ob der Benutzer AUSDRUECKLICH auf den Bildschirm sehen lassen will.

    Bewusst eng gefasst: Ein Wort fuer den Ort (Bildschirm/Monitor) allein
    genuegt nicht - erst zusammen mit einer Seh- oder Leseabsicht. So faengt
    die Regel "schau auf den Bildschirm" und "was ist auf dem Bildschirm",
    aber nicht "mach den Bildschirm heller". Die klaren Fotobefehle
    (Screenshot, Printscreen) loesen fuer sich aus.
    """

    knapp = " " + " ".join(text.lower().split()) + " "
    if any(wort in knapp for wort in _BILDSCHIRM_DIREKT):
        return True
    if any(wort in knapp for wort in _BILDSCHIRM_ORT):
        if any(wort in knapp for wort in _BILDSCHIRM_SEHEN):
            return True
    return False


import re as _re

#: Eine Adresse im gesprochenen Text - mit oder ohne ``http``. ``www.x.de``
#: und ``spiegel.de/politik`` sollen genauso greifen wie eine volle URL.
_URL_MUSTER = _re.compile(
    r"\b((?:https?://)?(?:www\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/[^\s]*)?)",
    _re.IGNORECASE,
)

#: Endungen, die fast immer eine echte Netzadresse markieren. Ohne diese
#: Prüfung fischt das Muster auch "z.B." oder "u.a." heraus.
_URL_ENDUNGEN: tuple[str, ...] = (
    ".de", ".com", ".org", ".net", ".ch", ".at", ".eu", ".info", ".io",
    ".gov", ".edu", ".it", ".fr", ".uk", ".es", ".nl", ".pl", ".ru",
)

#: Die Absicht, eine bestimmte Seite zu LESEN (nicht im Browser zu klicken).
_LESE_ABSICHT: tuple[str, ...] = (
    "lies", "les", "vorles", "vorlesen", "lesen", "lese", "oeffne", "öffne",
    "ruf auf", "rufe auf", "geh auf", "geh zu", "zeig mir", "zeige mir",
    "zusammenfass", "fasse zusammen", "fasse", "zusammen", "worum geht",
    "was steht", "was schreibt", "schau dir", "sieh dir", "was sagt",
    "prüf", "pruef",
)

#: Wendungen, die einen echten Browser mit Klicken/Bedienen verlangen.
_BROWSER_WOERTER: tuple[str, ...] = (
    "browser", "im browser", "chrome", "firefox", "webseite bedien",
    "seite bedien", "steuere den browser", "browsersteuerung",
)

#: Die Absicht, im Browser etwas zu TUN (nicht bloss zu lesen).
_BROWSER_HANDLUNG: tuple[str, ...] = (
    "klick", "klicke", "tippe", "eingeb", "einloggen", "anmeld", "melde",
    "formular", "ausfüll", "ausfuell", "scroll", "navigier", "bediene",
    "drück", "drueck", "wähle", "waehle", "such auf", "buche", "bestell",
)


def _url_aus(text: str) -> str:
    """Zieht die erste echte Netzadresse aus dem Text - oder gibt "" zurück.

    Eng gefasst: Nur was auf eine bekannte Endung ausgeht, zählt. So wird
    "gegen 20.30 Uhr" nicht für eine Adresse gehalten, "spiegel.de/politik"
    aber schon.
    """

    for treffer in _URL_MUSTER.findall(text or ""):
        kandidat = treffer.strip().rstrip(".,;:!?)")
        # Erst das Schema abstreifen, sonst wäre "https:" der Wirt (die
        # Doppelschrägstriche zerlegten die Adresse an der falschen Stelle).
        ohne_schema = _re.sub(r"^https?://", "", kandidat, flags=_re.IGNORECASE)
        kern = ohne_schema.split("/")[0].lower()
        if any(kern.endswith(endung) for endung in _URL_ENDUNGEN):
            if not kandidat.lower().startswith(("http://", "https://")):
                kandidat = "https://" + kandidat
            return kandidat
    return ""


def will_webseite_lesen(text: str) -> str:
    """Die Adresse, die der Benutzer ausdrücklich LESEN lassen will - sonst "".

    Zwei Dinge müssen zusammenkommen: eine erkennbare Adresse UND eine
    Leseabsicht ("lies mir spiegel.de vor", "worum geht es auf …"). Eine
    Adresse allein genügt nicht - sie könnte auch nur erwähnt sein. Ist
    zugleich von einem Browser mit Klicken die Rede, gehört das nicht
    hierher, sondern in ``will_browser``.
    """

    url = _url_aus(text)
    if not url:
        return ""
    knapp = " " + " ".join(text.lower().split()) + " "
    if any(wort in knapp for wort in _BROWSER_HANDLUNG):
        return ""
    if any(wort in knapp for wort in _LESE_ABSICHT):
        return url
    return ""


#: Seiten, die Benutzer beim Sprechen NIE mit Endung nennen. "Öffne ein
#: Browserfenster mit Google" enthält keine einzige Adresse - und genau an
#: dieser Huerde ist der Befehl im Protokoll des Benutzers gescheitert.
_BEKANNTE_SEITEN: dict[str, str] = {
    "google": "https://www.google.de",
    "youtube": "https://www.youtube.com",
    "wikipedia": "https://de.wikipedia.org",
    "amazon": "https://www.amazon.de",
    "ebay": "https://www.ebay.de",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "tagesschau": "https://www.tagesschau.de",
}

#: Wendungen, die ein Browserfenster verlangen, auch ohne Ziel.
_BROWSER_OEFFNEN: tuple[str, ...] = (
    "browserfenster", "browser fenster", "browser oeffnen", "browser öffnen",
    "oeffne den browser", "öffne den browser", "oeffne einen browser",
    "öffne einen browser", "browser starten", "starte den browser",
    "browser auf",
)


def will_browser(text: str) -> str:
    """Die Adresse für eine ausdrückliche Browser-BEDIENUNG - sonst "".

    Anders als beim Lesen geht es hier ums Tun: klicken, tippen, sich
    anmelden, ein Formular ausfüllen - oder schlicht "öffne ein
    Browserfenster". Das Ziel darf eine Adresse sein, ein bekannter
    Seitenname ("mit Google") oder ganz fehlen - dann wird die Startseite
    der Suche geöffnet, denn ein leeres Browserfenster gibt es nicht.
    """

    knapp = " " + " ".join(text.lower().split()) + " "
    nennt_browser = any(wort in knapp for wort in _BROWSER_WOERTER)
    will_handeln = any(wort in knapp for wort in _BROWSER_HANDLUNG)
    will_fenster = any(wort in knapp for wort in _BROWSER_OEFFNEN)
    if not (nennt_browser or will_handeln or will_fenster):
        return ""

    url = _url_aus(text)
    if url:
        return url
    # Kein www und keine Endung? Dann die gesprochenen Seitennamen.
    for name, adresse in _BEKANNTE_SEITEN.items():
        if f" {name} " in knapp or f" {name}." in knapp or f" {name}," in knapp:
            return adresse
    # "Öffne ein Browserfenster" ohne Ziel: die Startseite der Suche.
    if will_fenster:
        return _BEKANNTE_SEITEN["google"]
    return ""


def ist_browser_befehl(text: str) -> bool:
    """Ob der Satz in erster Linie ein Browser-Befehl ist.

    Gebraucht als Schutz VOR der erzwungenen Vorabsuche: "Öffne ein
    Browserfenster bei Google und führe eine Suche durch" ist eine
    Handlungsanweisung - wer sie wörtlich als Suchbegriff ins Netz schickt,
    bekommt (belegt im Protokoll) null Treffer auf acht Kanälen und meldet
    dann "die Suche geht nicht".
    """

    knapp = " " + " ".join(text.lower().split()) + " "
    if any(wort in knapp for wort in _BROWSER_OEFFNEN):
        return True
    return bool(will_browser(text))


@dataclass
class OrchestrationResult:
    """Vollständiges Ergebnis einer orchestrierten Anfrage."""

    response: str
    intent: str
    used_llm: bool
    provider: str | None = None
    model: str | None = None
    module: str = ""
    duration_seconds: float = 0.0
    requires_confirmation: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "intent": self.intent,
            "used_llm": self.used_llm,
            "provider": self.provider,
            "model": self.model,
            "module": self.module,
            "duration_seconds": round(self.duration_seconds, 3),
            "requires_confirmation": self.requires_confirmation,
            "data": self.data,
        }


class Orchestrator:
    """Zentrale Verteilungsstelle für Benutzeranfragen."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        provider_manager: ProviderManager,
        event_bus: EventBus | None = None,
        classifier: IntentClassifier | None = None,
        router: TaskRouter | None = None,
    ) -> None:
        self._memory = memory
        self._providers = provider_manager
        self._event_bus = event_bus
        self._config = get_config()
        self.classifier = classifier or IntentClassifier()
        self.router = router or TaskRouter()
        self.conversations = ConversationManager(memory)
        self._last_decision: dict[str, Any] = {}
        #: Der zuletzt wirklich gesuchte Begriff. "Wiederhole die Suche"
        #: soll DEN wiederholen - nicht den Satz "wiederhole die Suche"
        #: wörtlich ins Netz schicken (belegt im Protokoll des Benutzers).
        self._letzter_suchbegriff: str = ""
        #: Beim Tagebuchdiktat gehoeren alle folgenden Aeusserungen
        #: wortgetreu in den Eintrag, bis "Tagebucheintrag beendet" faellt.
        self._tagebuch_diktat_ausstehend = False
        self._tagebuch_diktat_teile: list[str] = []
        self._tagebuch_bild_suchwort_ausstehend = False
        self._tagebuch_bild_kandidaten: list[dict[str, Any]] = []

        #: Wie viel Beigelegtes hoechstens in eine Anfrage darf.
        #:
        #: Nicht die Antwort wird hier begrenzt, sondern die FRAGE. Das ist
        #: der Unterschied, auf den es ankommt: Kuerzere Antworten waeren
        #: ein Verlust, ein kuerzerer Anlauf ist keiner - was hier
        #: wegfaellt, kann das Modell mit einem Werkzeug nachholen.
        self._kontext_hoechstens = max(
            2000, int(self._config.get("conversation.max_extra_context_chars", 12000))
        )
        #: Die Werkzeugschleife. Wird nach dem Aufbau angeschlossen (siehe
        #: attach_tool_engine) – zur Bauzeit des Orchestrators gibt es sie
        #: noch nicht.
        self._tool_engine: Any | None = None
        #: Die Ablaufmaschine. Wird nachgereicht wie die Werkzeugschleife –
        #: zur Bauzeit des Orchestrators gibt es sie noch nicht.
        self._workflows: Any | None = None
        #: Bildmaterial wird parallel zum gesprochenen Abschnitt beschafft.
        #: Die laufenden Tasks werden festgehalten, damit sie nicht vorzeitig
        #: eingesammelt werden; die Generation verhindert veraltete Anzeigen.
        self._vorlesungsbild_tasks: set[asyncio.Task[None]] = set()
        self._vorlesungsbild_generation = 0
        self._vorlesungsbild_cache: dict[str, dict[str, str]] = {}
        #: Der Schattenlauf. Wird beim ersten Zug gebaut, wenn er an ist -
        #: und genau einmal geprueft, wenn er aus ist.
        self._schatten: Any | None = None
        self._schatten_geprueft = False

    def attach_workflows(self, workflows: Any) -> None:
        """Schliesst die Ablaufmaschine an.

        Erst damit lassen sich Abläufe im Gespräch auslösen. Vorher gab es
        die Auslöser zwar, aber niemanden, der sie abfragte.
        """

        self._workflows = workflows

    def attach_tool_engine(self, tool_engine: Any) -> None:
        """Schließt die Werkzeugschleife an.

        Vorher konnte das Modell in Gesprächen keine Werkzeuge benutzen:
        Der Orchestrator fragte das Modell direkt, ohne ihm die Werkzeuge
        auch nur zu nennen. Auf „such das mal im Internet" blieb dem Modell
        nur die Auskunft, es könne das nicht – was klang wie ein
        Berechtigungsproblem, aber schlicht ein fehlender Anschluss war.
        """

        self._tool_engine = tool_engine

    def attach_lernstand(self, lernstand: Any) -> None:
        """Schliesst das Mitlesen an.

        Der Benutzer hat ausdruecklich verlangt, dass der Orb seinen
        Wissensstand aus dem GESPRAECH erkennt und nicht aus Tests. Das
        geht nur, wenn jede Aeusserung daraufhin angesehen wird - und
        zwar von selbst, ohne dass ein Werkzeug aufgerufen werden muss.
        Genau hier ist die Stelle: Jede Frage kommt hier vorbei.
        """

        self._lernstand = lernstand

    def _aus_dem_gespraech_lernen(self, text: str) -> str:
        """Liest an einer Aeusserung ab, wo der Benutzer steht.

        Gibt den Hinweis zurueck, der dem Sprachmodell beigelegt wird -
        oder eine leere Zeichenkette, wenn nichts zu erkennen war. Das
        Erkennen selbst steht in :mod:`backend.studium.mitlesen`; hier
        wird es nur eingeholt und festgehalten.

        Faellt irgendetwas davon aus, geht die Antwort trotzdem weiter:
        Eine Vermutung ueber den Lernenden darf nie eine Auskunft
        verhindern.
        """

        lernstand = getattr(self, "_lernstand", None)
        if lernstand is None or not text.strip():
            return ""
        try:
            lernstand.lernweg_beobachten(text)
            lernweg = lernstand.lernprofil_hinweis()
            from backend.studium.landkarte import thema_suchen
            from backend.studium.mitlesen import (
                einschaetzung_im_klartext,
                mitlesen,
            )

            treffer = thema_suchen(text)
            if treffer is None:
                return lernweg
            das_feld, das_thema = treffer
            beobachtung = mitlesen(text, das_thema)
            if not beobachtung.sagt_etwas:
                return ""
            lernstand.beobachten(das_feld.kennung, beobachtung)

            from backend.studium.antrieb import haltung_im_klartext

            teile = [
                lernweg,
                # Wozu der Orb das alles tut. Es steht hier und nicht im
                # allgemeinen Systemtext, weil es nur bei einer Fachfrage
                # etwas beitraegt - bei einer Wetterfrage waere es Ballast.
                haltung_im_klartext(),
                einschaetzung_im_klartext(beobachtung),
                lernstand.wechselurteil(
                    winkt_ab=beobachtung.interesse < 0
                ).als_hinweis(),
            ]
            return "\n\n".join(t for t in teile if t)
        except Exception:  # noqa: BLE001
            logger.exception("Das Mitlesen im Gespraech ist gescheitert.")
            return ""

    # --- Hauptablauf ------------------------------------------------------------

    #: Die Anweisung für gesprochene Antworten.
    #:
    #: Der Grund ist gemessen, nicht vermutet: Ohne sie schrieb das Modell
    #: auf eine gewöhnliche Frage rund 260 Wörter. Das Modell braucht dafür
    #: doppelt so lange, und vorgelesen sind es fast zwei Minuten – der
    #: Benutzer sitzt also zwei Minuten vor einem Vortrag, den er nicht
    #: erbeten hat. Mit dieser Anweisung sind es 60 Wörter und eine halbe
    #: Minute. Wer mehr will, fragt nach.
    SPOKEN_BREVITY = (
        "DEINE ANTWORT WIRD VORGELESEN. Deshalb:\n"
        "- Fasse dich auf zwei bis vier Sätze. Sag das Wichtigste zuerst.\n"
        "- Keine Aufzählungen, keine Überschriften, keine Klammerzusätze – "
        "das lässt sich nicht vorlesen.\n"
        "- Ist das Thema größer, sage das Wesentliche und biete in einem "
        "kurzen Satz an, mehr auszuführen. Halte keinen Vortrag, den "
        "niemand erbeten hat.\n"
        "- Wird ausdrücklich nach einer ausführlichen Darstellung gefragt, "
        "gilt diese Beschränkung nicht."
    )

    #: Was der Orb sagt, wenn am Ende doch nichts dasteht.
    LEERE_ANTWORT = (
        "Dabei ist mir nichts Brauchbares herausgekommen. Ich sage das "
        "lieber, als zu schweigen - frag gern noch einmal, auch anders "
        "formuliert."
    )

    #: Was der Orb sagt, wenn die Gesamtfrist gerissen ist.
    #:
    #: Nicht schoen, aber ehrlich - und vor allem: ueberhaupt etwas. Die
    #: Alternative war Stille von unbestimmter Dauer.
    ZEITUEBERSCHREITUNG = (
        "Das hat zu lange gedauert, ich habe abgebrochen - damit du nicht "
        "weiter vor einem stummen Orb sitzt. Frag noch einmal; beim "
        "naechsten Mal ist ein anderes Modell an der Reihe."
    )

    LOCAL_SPOKEN_SYSTEM = (
        "Diese Antwort wird vorgelesen. Antworte bei einer einfachen Frage "
        "in ein bis drei kurzen Saetzen und beginne unmittelbar mit der "
        "Sache. Keine Listen, Ueberschriften oder sichtbare Formatierung."
    )

    async def handle(
        self,
        text: str,
        *,
        project_id: str | None = None,
        extra_context: str | None = None,
        spoken: bool = False,
        on_speech: Callable[[str], Awaitable[bool]] | None = None,
    ) -> OrchestrationResult:
        """Der lebende Pfad - und daneben, danach, der Schatten.

        Diese Hülle tut selbst nichts an der Antwort. Sie reicht die
        Anfrage an ``_anfrage_bearbeiten`` weiter, gibt deren Ergebnis
        unverändert zurück und setzt erst danach den Schattenlauf ab.

        Warum eine Hülle und nicht ein Aufruf am Ende von
        ``_anfrage_bearbeiten``: Die Bearbeitung hat über zwanzig
        Rückgabestellen - Tagebuch, Betriebsartwechsel, Verlaufsreparatur,
        Abläufe, Werkzeugpfad. Ein Aufruf "am Ende" hätte die meisten davon
        verfehlt, und ein Schatten, der nur bei einem Teil der Züge läuft,
        misst die Verteilung der Züge, nicht das Modell.

        Der Schattenlauf kann die Antwort nicht anfassen: Er bekommt sie
        als Zeichenkette, gibt nichts zurück, und läuft in einer eigenen
        Aufgabe mit eigener Zeitgrenze. Fällt er aus, merkt der Benutzer
        nichts - was ausgefallen ist, steht im Zähler.
        """

        ergebnis = await self._anfrage_bearbeiten(
            text,
            project_id=project_id,
            extra_context=extra_context,
            spoken=spoken,
            on_speech=on_speech,
        )

        waechter = self._schattenwaechter()
        if waechter is not None:
            try:
                waechter.starten(
                    text=text,
                    live_antwort=ergebnis.response,
                    kategorie=str(ergebnis.data.get("faehigkeit", "") or ergebnis.intent),
                    werkzeuge_live=list(ergebnis.data.get("werkzeuge", []) or []),
                )
            except Exception:  # noqa: BLE001 - der Schatten darf den Zug nicht beruehren.
                logger.debug("Der Schattenlauf liess sich nicht absetzen.", exc_info=True)

        return ergebnis

    def _schattenwaechter(self) -> Any | None:
        """Baut den Wächter beim ersten Bedarf - und nur, wenn er an ist.

        Ist der Schattenlauf aus (Vorgabe), bleibt es bei einem einzigen
        Konfigurationszugriff und einem ``None``; es entsteht kein Objekt,
        keine Aufgabe, kein Zähler.
        """

        if self._schatten is not None:
            return self._schatten
        if self._schatten_geprueft:
            return None
        self._schatten_geprueft = True
        try:
            from backend.lernen.schattenpfad import Schattenwaechter

            waechter = Schattenwaechter(
                provider_manager=self._providers, event_bus=self._event_bus
            )
        except Exception:  # noqa: BLE001
            logger.debug("Der Schattenwaechter liess sich nicht bauen.", exc_info=True)
            return None
        if not waechter.aktiv:
            logger.debug("Der Schattenlauf ist abgeschaltet.")
            return None
        self._schatten = waechter
        logger.info("Der Schattenlauf ist aktiv: %s", waechter.status())
        return waechter

    async def _anfrage_bearbeiten(
        self,
        text: str,
        *,
        project_id: str | None = None,
        extra_context: str | None = None,
        spoken: bool = False,
        on_speech: Callable[[str], Awaitable[bool]] | None = None,
    ) -> OrchestrationResult:
        """Verarbeitet eine Benutzeranfrage vollständig.

        Ablauf: Intent-Klassifikation → Routing → gegebenenfalls
        Modellanfrage → Speicherung relevanter Informationen.

        Args:
            text: Die Benutzereingabe.
            project_id: Optionales aktives Projekt; sorgt dafür, dass
                Kontext und Erinnerungen projektbezogen bleiben.
            extra_context: Zusätzlicher Kontext, den übergeordnete
                Schichten (Cognitive Core, Agenten) beisteuern.

        Returns:
            Das Ergebnis inklusive Angabe, welcher Weg gewählt wurde.
        """

        started = time.perf_counter()
        mark_stage("orchestrator_received")
        # Jede Anfrage bekommt eine Korrelations-Kennung, auch die getippte.
        #
        # Die Sprachpipeline legt fuer gesprochene Zuege laengst eine an;
        # ueber die Oberflaeche kam bisher keine, und genau diese Zuege
        # liessen sich im Protokoll nicht verfolgen. Der Marker wird am
        # Ende dieses Zuges wieder zurueckgesetzt.
        if current_turn_trace() is None:
            # Kein Zuruecksetzen noetig: Jede Anfrage laeuft in einer
            # eigenen asyncio-Aufgabe, und die bekommt eine eigene Kopie
            # des Kontexts. Die Kennung endet also mit diesem Zug von
            # selbst. Die Sprachpipeline setzt ihre eigene ausdruecklich
            # zurueck, weil sie die Aufgabe wiederverwendet.
            start_turn_trace()
        self._providers.begin_conversation()
        interner_vorlesungsauftrag = ist_vorlesungssegment(text)

        if project_id is not None:
            self.conversations.set_project(project_id)

        # Der Wechsel in den Offlinebetrieb muss VOR Intent-Erkennung und
        # erst recht vor jeder Modellanfrage geschehen. So verlaesst selbst
        # der Umschaltbefehl den Rechner nicht und funktioniert auch dann,
        # wenn gerade kein Cloud-Provider erreichbar ist.
        # "Du hast eine falsche Stimme gehoert" muss wirken, und zwar
        # sofort und ohne Modell.
        #
        # Was eine fremde Stimme gesagt hat, steht sonst fuer immer im
        # Verlauf - und weil jede weitere Antwort den ganzen Verlauf
        # mitliest, faerbt der Unsinn auf alles Folgende ab. Genau so
        # entstand am 18.08.2026 der Eindruck, der Orb halluziniere und
        # hoere nicht mehr damit auf. Diese Pruefung steht deshalb ganz
        # vorn: Der Satz, mit dem man das zurueckholt, darf an keiner
        # Modellwahl und keiner Werkzeugwahl scheitern.
        if not interner_vorlesungsauftrag and ist_reparaturbefehl(text):
            entfernt = self.conversations.letzte_wechsel_verwerfen(STANDARD_WECHSEL)
            response = reparatur_antwort(entfernt)
            logger.info(
                "Verlauf auf Zuruf bereinigt: %d Wortwechsel entfernt.", entfernt
            )
            result = OrchestrationResult(
                response=response,
                intent="verlauf_reparatur",
                used_llm=False,
                module="conversation_manager",
                data={"success": True, "entfernt": entfernt},
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        # Tagebuchinhalt kann die Woerter "offline", "online", "nutze" oder
        # "verwende" enthalten, ohne eine Systemanweisung zu sein. Ein lokal
        # erkannter Tagebuchauftrag hat deshalb absoluten Vorrang vor der
        # Betriebsmodus-Erkennung.
        tagebuch_vorab = parse_tagebuch_befehl(text)
        mode_command = ""
        if (
            not interner_vorlesungsauftrag
            and not self._tagebuch_diktat_ausstehend
            and tagebuch_vorab is None
        ):
            mode_command = provider_mode_command(text)
        if mode_command:
            if mode_command == "status":
                provider_status = self._providers.status()
                mode = str(provider_status.get("mode", "auto"))
                active = str(provider_status.get("active") or "kein Modell")
                model = str(provider_status.get("active_model") or "")
                response = (
                    f"Der Offlinebetrieb ist {'aktiv' if mode == 'offline' else 'nicht aktiv'}. "
                    f"Aktuell verwende ich {active}{f' mit {model}' if model else ''}."
                )
                data = {"success": True, **provider_status}
            else:
                data = await self._providers.set_operating_mode(mode_command)
                response = str(data.get("message", "Der Betriebsmodus wurde geaendert."))

            self.conversations.add_user_message(text)
            self.conversations.add_assistant_message(response)
            result = OrchestrationResult(
                response=response,
                intent="provider_modus",
                used_llm=False,
                provider=str(data.get("provider") or self._providers.active_name or "") or None,
                model=str(data.get("model") or "") or None,
                module="provider_manager",
                data=data,
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        # Nach der Aufnahmeaufforderung sammeln wir beliebig viele
        # Sprachabschnitte. Erst der ausdrueckliche Schlusssatz beendet und
        # speichert das Diktat; normale Sprechpausen tun das gerade nicht.
        if self._tagebuch_diktat_ausstehend and not interner_vorlesungsauftrag:
            roh_diktat = str(text or "").strip()
            ende = re.search(
                r"(?:^|\s)(?:"
                r"tagebuch(?:eintrag|eitrag)\s+beendet|"
                r"ende\s+des\s+(?:tagebuch\s*)?eintrag(?:s|es)|"
                r"(?:tagebuch\s*)?eintrag\s+ende"
                r")[.!?]*\s*$",
                roh_diktat,
                flags=re.IGNORECASE,
            )
            abschnitt = roh_diktat[:ende.start()].strip() if ende else roh_diktat
            if abschnitt:
                self._tagebuch_diktat_teile.append(abschnitt)

            if not ende:
                response = (
                    "Der Abschnitt ist aufgenommen. Zum Abschluss sage: "
                    "Ende des Eintrages. Möchtest du weiter diktieren?"
                )
                self.conversations.add_user_message(text)
                self.conversations.add_assistant_message(response)
                result = OrchestrationResult(
                    response=response, intent="tagebuch", used_llm=False,
                    module="tagebuch",
                    data={"ok": True, "wartet_auf_diktat": True,
                          "abschnitte": len(self._tagebuch_diktat_teile)},
                    duration_seconds=time.perf_counter() - started,
                )
                await self._publish("ai.response", result.to_dict())
                return result

            if self._tool_engine is not None and self._tool_engine.enabled:
                if not self._tagebuch_diktat_teile:
                    response = (
                        "Es wurde noch kein Text aufgenommen. Diktiere deinen Text "
                        "und sage danach: Ende des Eintrages."
                    )
                    result = OrchestrationResult(
                        response=response, intent="tagebuch", used_llm=False,
                        module="tagebuch",
                        data={"ok": False, "wartet_auf_diktat": True},
                        duration_seconds=time.perf_counter() - started,
                    )
                    await self._publish("ai.response", result.to_dict())
                    return result
                self._tagebuch_diktat_ausstehend = False
                gesamtdiktat = " ".join(self._tagebuch_diktat_teile)
                self._tagebuch_diktat_teile = []
                diktat = re.sub(
                    r"\s+(?:neuer|neue|naechster|nächster)\s+absatz\s+",
                    " | ",
                    gesamtdiktat,
                    flags=re.IGNORECASE,
                )
                run = await self._tool_engine.direkt_ausfuehren(
                    "tagebuch_schreiben", {"text": diktat},
                    actor="tagebuch_sprachbefehl",
                )
                geoeffnet = False
                if run.result.ok:
                    auf = await self._tool_engine.direkt_ausfuehren(
                        "tagebuch_zeigen", {}, actor="tagebuch_sprachbefehl",
                    )
                    geoeffnet = bool(auf.result.ok)
                    response = (
                        "Der Tagebucheintrag ist fertig und gespeichert. "
                        + ("Ich habe ihn jetzt im Tagebuch geöffnet."
                           if geoeffnet else
                           "Das Tagebuch konnte ich diesmal nicht automatisch öffnen.")
                    )
                else:
                    response = run.result.error or "Der Tagebucheintrag konnte nicht gespeichert werden."
                self.conversations.add_user_message(text)
                self.conversations.add_assistant_message(response)
                result = OrchestrationResult(
                    response=response, intent="tagebuch", used_llm=False,
                    module="tagebuch",
                    data={"ok": run.result.ok, "geoeffnet": geoeffnet, **run.result.context},
                    duration_seconds=time.perf_counter() - started,
                )
                await self._publish("ai.response", result.to_dict())
                return result

        # Der Bilddialog ist ebenfalls lokal gesteuert: Motiv erfragen,
        # freie Bilder suchen und zeigen, danach die gesprochene Nummer in
        # den juengsten Eintrag uebernehmen und das Buch oeffnen.
        bild_befehl = parse_tagebuch_bild_befehl(text)
        if self._tagebuch_bild_suchwort_ausstehend and not interner_vorlesungsauftrag:
            self._tagebuch_bild_suchwort_ausstehend = False
            bild_befehl = TagebuchBefehl(
                "tagebuch_bild_suchen", {"begriff": str(text or "").strip()}
            )

        if bild_befehl is not None and bild_befehl.werkzeug == "tagebuch_bild_suche_start":
            self._tagebuch_bild_suchwort_ausstehend = True
            response = "Welches Bild soll ich für den Tagebucheintrag suchen?"
            result = OrchestrationResult(
                response=response, intent="tagebuch_bild", used_llm=False,
                module="tagebuch", data={"ok": True, "wartet_auf_bildmotiv": True},
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        if (
            bild_befehl is not None
            and bild_befehl.werkzeug == "tagebuch_bild_suchen"
            and self._tool_engine is not None and self._tool_engine.enabled
        ):
            suche = await self._tool_engine.direkt_ausfuehren(
                "bild_suchen", {"begriff": bild_befehl.argumente["begriff"], "anzahl": 5},
                actor="tagebuch_bilddialog",
            )
            if suche.result.ok:
                self._tagebuch_bild_kandidaten = list(
                    suche.result.context.get("bilder", []) or []
                )[:5]
                pfade = "\n".join(str(b.get("pfad", "")) for b in self._tagebuch_bild_kandidaten)
                zeigen = await self._tool_engine.direkt_ausfuehren(
                    "bild_zeigen",
                    {"pfade": pfade, "titel": f"Bilder: {bild_befehl.argumente['begriff']}"},
                    actor="tagebuch_bilddialog",
                )
                response = (
                    f"Ich zeige dir {len(self._tagebuch_bild_kandidaten)} Bilder. "
                    "Sage zum Beispiel: Bild zwei. Welches Bild soll ich einfügen?"
                    if zeigen.result.ok else
                    "Die Bilder wurden gefunden, konnten aber nicht geöffnet werden."
                )
            else:
                self._tagebuch_bild_kandidaten = []
                response = suche.result.error or "Ich habe dazu keine Bilder gefunden."
            result = OrchestrationResult(
                response=response, intent="tagebuch_bild", used_llm=False,
                module="tagebuch",
                data={"ok": suche.result.ok, "bilder": len(self._tagebuch_bild_kandidaten)},
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        if (
            bild_befehl is not None
            and bild_befehl.werkzeug == "tagebuch_bild_auswaehlen"
            and self._tagebuch_bild_kandidaten
            and self._tool_engine is not None and self._tool_engine.enabled
        ):
            nummer = int(bild_befehl.argumente["nummer"])
            if not 1 <= nummer <= len(self._tagebuch_bild_kandidaten):
                response = f"Bitte wähle eine Nummer von eins bis {len(self._tagebuch_bild_kandidaten)}."
                ok = False
            else:
                bild = self._tagebuch_bild_kandidaten[nummer - 1]
                einfuegen = await self._tool_engine.direkt_ausfuehren(
                    "tagebuch_bild_einfuegen",
                    {"pfad": str(bild.get("pfad", "")),
                     "nachweis": str(bild.get("nachweis", ""))},
                    actor="tagebuch_bilddialog",
                )
                ok = bool(einfuegen.result.ok)
                if ok:
                    self._tagebuch_bild_kandidaten = []
                    auf = await self._tool_engine.direkt_ausfuehren(
                        "tagebuch_zeigen", {}, actor="tagebuch_bilddialog",
                    )
                    response = (
                        "Das ausgewählte Bild ist eingefügt. Ich habe den Eintrag im Tagebuch geöffnet."
                        if auf.result.ok else
                        "Das ausgewählte Bild ist eingefügt, aber das Tagebuch konnte nicht geöffnet werden."
                    )
                else:
                    response = einfuegen.result.error or "Das Bild konnte nicht eingefügt werden."
            result = OrchestrationResult(
                response=response, intent="tagebuch_bild", used_llm=False,
                module="tagebuch", data={"ok": ok, "nummer": nummer},
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        # Ein diktiertes Tagebuch ist persoenlicher Originaltext. Deshalb
        # laeuft dieser klar erkennbare Auftrag direkt zum Tagebuchwerkzeug:
        # kein Cloud-Modell, keine Umformulierung und kein Risiko, dass ein
        # Providerausfall den Eintrag verschluckt. Oeffnen und das Streichen
        # des letzten Fehldiktats folgen demselben verlaesslichen Weg.
        tagebuch_befehl = tagebuch_vorab
        if tagebuch_befehl is not None and tagebuch_befehl.werkzeug == "tagebuch_diktat_start":
            self._tagebuch_diktat_ausstehend = True
            self._tagebuch_diktat_teile = []
            response = (
                "Beginne jetzt mit dem Diktieren. "
                "Beende mit dem Satz: Ende des Eintrages."
            )
            self.conversations.add_user_message(text)
            self.conversations.add_assistant_message(response)
            result = OrchestrationResult(
                response=response, intent="tagebuch", used_llm=False,
                module="tagebuch", data={"ok": True, "wartet_auf_diktat": True},
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result
        if (
            tagebuch_befehl is not None
            and self._tool_engine is not None
            and self._tool_engine.enabled
        ):
            run = await self._tool_engine.direkt_ausfuehren(
                tagebuch_befehl.werkzeug,
                tagebuch_befehl.argumente,
                actor="tagebuch_sprachbefehl",
            )
            response = run.result.output if run.result.ok else run.result.error
            geoeffnet = False
            if run.result.ok and tagebuch_befehl.werkzeug in {
                "tagebuch_schreiben", "tagebuch_streichen", "tagebuch_aendern",
            }:
                auf = await self._tool_engine.direkt_ausfuehren(
                    "tagebuch_zeigen", {}, actor="tagebuch_sprachbefehl",
                )
                geoeffnet = bool(auf.result.ok)
                if tagebuch_befehl.werkzeug == "tagebuch_schreiben":
                    aktion = "Der Tagebucheintrag ist vollständig gespeichert."
                elif tagebuch_befehl.werkzeug == "tagebuch_streichen":
                    aktion = "Der gewünschte Tagebucheintrag ist entfernt."
                else:
                    aktion = "Der Tagebucheintrag ist geändert und gespeichert."
                response = aktion + (
                    " Ich habe das Tagebuch jetzt geöffnet."
                    if geoeffnet else
                    " Das Tagebuch konnte ich diesmal nicht automatisch öffnen."
                )
            response = response or (
                "Der Tagebucheintrag ist festgehalten."
                if run.result.ok
                else "Der Tagebuchauftrag ist fehlgeschlagen."
            )
            self.conversations.add_user_message(text)
            self.conversations.add_assistant_message(response)
            result = OrchestrationResult(
                response=response,
                intent="tagebuch",
                used_llm=False,
                module="tagebuch",
                data={
                    "werkzeug": tagebuch_befehl.werkzeug,
                    "ok": run.result.ok,
                    "geoeffnet": geoeffnet,
                    **run.result.context,
                },
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        # Ein ausdruecklich genannter CMD-/PowerShell-Auftrag ist bereits
        # vollstaendig bestimmt. Das Modell soll weder den Befehl umschreiben
        # noch bloss behaupten, es habe ihn ausgefuehrt. Die Werkzeugmaschine
        # uebernimmt deterministisch; Validierung, Zustimmung und Protokoll
        # bleiben dabei identisch mit jedem modellgesteuerten Werkzeugaufruf.
        terminal_request = (
            None if interner_vorlesungsauftrag else parse_terminal_request(text)
        )
        if (
            terminal_request is not None
            and self._tool_engine is not None
            and self._tool_engine.enabled
        ):
            tool_name = (
                "terminal_befehl_ausfuehren"
                if terminal_request.command
                else "terminal_oeffnen"
            )
            arguments: dict[str, Any] = {"shell": terminal_request.shell}
            if terminal_request.command:
                arguments["befehl"] = terminal_request.command
            run = await self._tool_engine.direkt_ausfuehren(
                tool_name,
                arguments,
                actor="terminal_sprachbefehl",
            )
            response = run.result.output if run.result.ok else run.result.error
            response = response or (
                "Der Terminalauftrag wurde ausgefuehrt."
                if run.result.ok
                else "Der Terminalauftrag ist fehlgeschlagen."
            )
            self.conversations.add_user_message(text)
            self.conversations.add_assistant_message(response)
            result = OrchestrationResult(
                response=response,
                intent="terminal",
                used_llm=False,
                module="terminal",
                data={
                    "werkzeug": tool_name,
                    "shell": terminal_request.shell,
                    "befehl": terminal_request.command,
                    "ok": run.result.ok,
                },
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        # Ein klarer Entwicklungsauftrag wird nicht dem Zufall überlassen,
        # ob das Gesprächsmodell das richtige Werkzeug auswählt. Derselbe
        # Satz funktioniert dadurch im Chat und über die Sprachsteuerung.
        development_request = (
            None if interner_vorlesungsauftrag else parse_development_request(text)
        )
        if (
            development_request is not None
            and self._tool_engine is not None
            and self._tool_engine.enabled
        ):
            run = await self._tool_engine.direkt_ausfuehren(
                "entwicklungsauftrag_umsetzen",
                {"wunsch": development_request},
                actor="live_entwicklung",
            )
            response = run.result.output if run.result.ok else run.result.error
            response = response or (
                "Die Änderung wurde umgesetzt."
                if run.result.ok
                else "Der Entwicklungsauftrag konnte nicht umgesetzt werden."
            )
            self.conversations.add_user_message(text)
            self.conversations.add_assistant_message(response)
            result = OrchestrationResult(
                response=response,
                intent="live_entwicklung",
                used_llm=True,
                provider=self._providers.active_name,
                module="evolution",
                data={"ok": run.result.ok, **run.result.context},
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        vorlesungssegment = interner_vorlesungsauftrag
        if vorlesungssegment:
            # Zweite und entscheidende Schranke: Das Cognitive Core markiert
            # Vorlesungen bereits als Frage, doch ``handle`` klassifiziert
            # normalerweise selbst noch einmal. Dabei wurde die technische
            # Regie "beende nur diesen Abschnitt" als PROGRAMM_SCHLIESSEN
            # gelesen und lokal mit "welches Programm?" beantwortet.
            intent = IntentResult(
                intent=QUESTION,
                confidence="hoch",
                score=1.0,
                requires_llm=True,
                matched_keywords=["interner_vorlesungsabschnitt"],
            )
        else:
            intent = self.classifier.classify(text)
        mark_stage("intent_ready")
        await self._publish("ai.intent.classified", intent.to_dict())

        # Löst der Satz einen hinterlegten Ablauf aus?
        #
        # Das war der Sinn der Auslöser von Anfang an, nur fragte sie nie
        # jemand ab: Abläufe liessen sich ausschliesslich über ihre Kennung
        # starten – also über die Oberfläche, nie im Gespräch. Ein Ablauf,
        # den man nur mit seiner Nummer aufrufen kann, ist keine
        # Automatisierung, sondern ein Menüpunkt.
        ablauf = None if vorlesungssegment else await self._ablauf_versuchen(text)
        if ablauf is not None:
            ablauf.duration_seconds = time.perf_counter() - started
            await self._publish("ai.response", ablauf.to_dict())
            return ablauf

        route = await self.router.route(text, intent)
        mark_stage("route_ready")

        self._last_decision = {
            "text": text,
            "intent": intent.to_dict(),
            "route": route.to_dict(),
            "at": time.time(),
        }

        # ist_endgueltig statt handled_locally: Eine unsichere lokale
        # Zuordnung beendet den Zug nicht mehr (siehe RouteResult).
        if route.ist_endgueltig and not route.requires_llm:
            self.conversations.add_user_message(text)
            self.conversations.add_assistant_message(route.response)
            result = OrchestrationResult(
                response=route.response,
                intent=intent.intent,
                used_llm=False,
                module=route.module,
                requires_confirmation=route.requires_confirmation,
                data=route.data,
                duration_seconds=time.perf_counter() - started,
            )
            await self._publish("ai.response", result.to_dict())
            return result

        aufruf = self._answer_with_model(
            text,
            intent=intent,
            route=route,
            project_id=project_id,
            extra_context=extra_context,
            spoken=spoken,
            on_speech=on_speech,
        )
        frist = self._antwortfrist(text)
        try:
            if frist > 0:
                result = await asyncio.wait_for(aufruf, timeout=frist)
            else:
                result = await aufruf
        except asyncio.TimeoutError:
            # Der Zug ist abgebrochen; die unbeantwortete Frage darf nicht
            # im Verlauf stehenbleiben, sonst antwortet das Modell beim
            # naechsten Mal auf zwei Fragen gleichzeitig.
            self.conversations.discard_unanswered_user_message(text)
            logger.warning(
                "Gesamtfrist von %.0f s ueberschritten - der Zug wurde "
                "abgebrochen. Ohne diese Grenze waere die Wartezeit die "
                "Summe der Zeitlimits aller Anbieter.",
                frist,
            )
            result = OrchestrationResult(
                response=self.ZEITUEBERSCHREITUNG,
                intent=intent.intent,
                used_llm=False,
                module="orchestrator",
                data={"abbruch": "zeitueberschreitung", "frist_sekunden": frist},
            )
            result.duration_seconds = time.perf_counter() - started
            await self._publish("ai.response", result.to_dict())
            return result
        except asyncio.CancelledError:
            self.conversations.discard_unanswered_user_message(text)
            logger.info("Abgebrochenen Gespraechszug aus dem Kontext entfernt.")
            raise
        result = self._niemals_stumm(result)
        result.duration_seconds = time.perf_counter() - started
        await self._publish("ai.response", result.to_dict())
        return result

    def _niemals_stumm(self, result: OrchestrationResult) -> OrchestrationResult:
        """Das letzte Netz: Eine leere Antwort verlässt den Orchestrator nicht.

        Das Netz gab es längst. ``is_valid_answer`` in response_pipeline.py
        prüft genau das - leer, Platzhalter, nur Satzzeichen. Nur rief es
        niemand: Die ResponsePipeline wurde beim Start gebaut und danach nie
        benutzt. Ein Sicherheitsnetz, das keiner aufspannt, fängt nichts.

        Hier hängt es jetzt, an der einen Stelle, an der jede Antwort
        vorbeikommt.
        """

        gueltig, grund = is_valid_answer(result.response)
        if gueltig:
            return result

        logger.warning(
            "Eine leere oder unbrauchbare Antwort wurde abgefangen: %s", grund
        )
        result.response = self.LEERE_ANTWORT
        result.data = {**(result.data or {}), "leere_antwort": grund}
        return result

    async def _ablauf_versuchen(self, text: str) -> OrchestrationResult | None:
        """Startet einen Ablauf, wenn ein Auslöser im Satz steckt.

        Gibt ``None`` zurück, wenn keiner passt – dann geht es den
        gewöhnlichen Weg weiter. Ein Fehler hier darf nie eine Antwort
        verhindern: Im Zweifel antwortet der Orb lieber selbst, als wegen
        eines Ablaufs zu schweigen.
        """

        if self._workflows is None:
            return None

        try:
            ablauf = self._workflows.find_by_trigger(text)
            if ablauf is None:
                return None

            logger.info("Ablauf '%s' durch den Satz ausgelöst.", ablauf.name)
            bericht = await self._workflows.run(ablauf.id)
        except Exception:  # noqa: BLE001
            logger.exception("Der ausgelöste Ablauf ist gescheitert.")
            return None

        # Der Bericht ist ein Objekt, kein Wörterbuch – und was es genau
        # anbietet, hängt an der Ablaufmaschine. Deshalb vorsichtig lesen
        # und im Zweifel schlicht bestätigen.
        antwort = ""
        for feld in ("summary", "zusammenfassung"):
            wert = getattr(bericht, feld, None)
            if callable(wert):
                wert = wert()
            if isinstance(wert, str) and wert.strip():
                antwort = wert.strip()
                break
        if not antwort:
            antwort = f"Der Ablauf '{ablauf.name}' ist durchgelaufen."
        self.conversations.add_user_message(text)
        self.conversations.add_assistant_message(antwort)
        return OrchestrationResult(
            response=antwort,
            intent="ablauf",
            used_llm=False,
            module="workflows",
            data={
                "ablauf": ablauf.id,
                "bericht": bericht.to_dict() if hasattr(bericht, "to_dict") else {},
            },
        )

    @staticmethod
    def _kennung() -> str:
        """Die Korrelations-Kennung dieses Zuges.

        Es gibt sie laengst: ``TurnTrace.turn_id`` wird in der
        Sprachpipeline erzeugt und liegt als Kontextvariable an. Sie wurde
        nur nirgends mitgeschrieben - deshalb liess sich ein Zug im
        Protokoll nicht von Anfang bis Ende verfolgen. Hier wird sie
        gelesen, nicht neu erfunden.
        """

        trace = current_turn_trace()
        return getattr(trace, "turn_id", "-") if trace is not None else "-"

    def _faehigkeit_bestimmen(
        self,
        text: str,
        *,
        gesprochen: bool,
        vorlesungssegment: bool,
        werkzeuge_vorhanden: bool,
    ) -> Faehigkeitsentscheidung:
        """Fragt die zentrale Faehigkeitsentscheidung mit den eigenen Werten."""

        namen: list[str] = []
        if self._tool_engine is not None:
            with contextlib.suppress(Exception):
                namen = list(self._tool_engine.registry.names())

        return faehigkeiten_entscheiden(
            text,
            gesprochen=gesprochen,
            vorlesungssegment=vorlesungssegment,
            werkzeuge_vorhanden=werkzeuge_vorhanden,
            werkzeugnamen=namen,
            schwelle=float(
                self._config.get("routing.werkzeug_schwelle", 0.45) or 0.45
            ),
            im_zweifel_werkzeuge=bool(
                self._config.get("routing.werkzeuge_im_zweifel", True)
            ),
        )

    def _sprechgrenze(
        self, *, vorlesungssegment: bool, gesprochen: bool, mit_werkzeugen: bool
    ) -> int | None:
        """Wie lang eine gesprochene Antwort höchstens werden darf.

        Vorher hing das an den Werkzeugen: Ein gesprochener Zug MIT
        Werkzeugen bekam gar keine Grenze. Der Gedanke dahinter ist
        richtig - in vierzig Tokens passt kein Werkzeugaufruf. Seit die
        Fähigkeitsentscheidung im Zweifel Werkzeuge gibt, bekämen aber
        auch gewöhnliche Sprachzüge keine Grenze mehr, und der Orb
        hielte wieder Vorträge.

        Deshalb jetzt zwei Grenzen statt einer Grenze und keiner: eine
        knappe fürs blosse Sprechen, eine weitere, wenn ein Werkzeugaufruf
        hineinpassen muss.
        """

        if vorlesungssegment:
            return int(
                self._config.get("voice.vorlesung.abschnitt_max_tokens", 420)
            )
        if not gesprochen:
            return None
        if mit_werkzeugen:
            return int(
                self._config.get("voice.spoken_max_tokens_mit_werkzeugen", 320)
            )
        return int(self._config.get("voice.spoken_max_tokens", 96))

    def _antwortfrist(self, text: str) -> float:
        """Die Gesamtfrist fuer einen Zug in Sekunden. ``0`` hebt sie auf.

        Ohne diese Frist ist die Dauer einer Frage die SUMME der Zeitlimits
        aller Kandidaten: erst die Cloud, dann das lokale Modell, dann das
        kleine - in der jetzigen Konfiguration ueber drei Minuten, ohne dass
        irgendwo etwas abbricht. Der Providerwechsel hilft dagegen nicht, er
        ist der Grund.

        Ein Vorlesungsabschnitt bekommt mehr Zeit: Er erzeugt absichtlich
        viel Text. Die Frist ist eine Notbremse gegen Haenger und keine
        Laengenbegrenzung.
        """

        frist = float(self._config.get("ai.answer_timeout_seconds", 180) or 0)
        if frist <= 0:
            return 0.0
        if ist_vorlesungssegment(text):
            faktor = float(
                self._config.get("ai.answer_timeout_lecture_factor", 3.0) or 3.0
            )
            frist *= max(1.0, faktor)
        return max(10.0, frist)

    async def _answer_with_model(
        self,
        text: str,
        *,
        intent: IntentResult,
        route: RouteResult,
        project_id: str | None,
        extra_context: str | None,
        spoken: bool = False,
        on_speech: Callable[[str], Awaitable[bool]] | None = None,
    ) -> OrchestrationResult:
        """Beantwortet eine Anfrage mit Hilfe eines Sprachmodells."""

        vorlesungssegment = ist_vorlesungssegment(text)
        # Der vollstaendige Abschnittsauftrag gehoert in den temporaeren
        # Kontext, nicht 24-mal in den dauerhaften Gespraechsverlauf. Dort
        # reicht die semantische Benutzerhandlung. Das haelt Folgeabschnitte
        # schnell und verhindert, dass die Vorlesung ihren eigenen Kontext
        # mit wiederholten Regieanweisungen verdraengt.
        gespraechstext = (
            "Fahre mit dem naechsten Abschnitt der laufenden Vorlesung fort."
            if vorlesungssegment
            else text
        )
        self.conversations.add_user_message(gespraechstext)
        await self.conversations.maybe_compress()

        memory_context = self._memory.context_for(gespraechstext, project_id=project_id)
        if vorlesungssegment:
            extra_context = "\n\n".join(
                part for part in (extra_context, text) if part
            )
        context_block = self._format_context(memory_context, extra_context)

        # Am Gesagten ablesen, wo der Benutzer steht - und es dem Modell
        # beilegen. Kein Test, kein Werkzeugaufruf: einfach zuhoeren.
        anhaltspunkt = self._aus_dem_gespraech_lernen(text)
        if anhaltspunkt:
            context_block = "\n\n".join(
                part for part in (context_block, anhaltspunkt) if part
            )

        # Gesprochene Antworten kurz halten – gemessen der grösste Hebel
        # gegen lange Wartezeiten.
        if spoken and not vorlesungssegment:
            context_block = "\n\n".join(
                part for part in (context_block, self.SPOKEN_BREVITY) if part
            )

        # A short spoken conversation turn is deliberately routed to the
        # local model. Feeding all 46 tool descriptions into that same turn
        # added more than 11,000 characters before the actual question and
        # made an 8B model sit silently for 20+ seconds. Tool requests,
        # current information, browser, screen and academic work are already
        # excluded by this selector and retain the full tool-capable path.
        preferred_spoken = (
            self._preferred_spoken_provider(text, intent, extra_context)
            if on_speech is not None
            else None
        )

        # Bei einer Frage nach Aktuellem wird VORHER gesucht.
        #
        # Das ist der Unterschied zwischen festverdrahtet und überredet.
        # Bisher stand in der Anweisung, das Modell solle bei allem
        # Aktuellen suchen - und es tat es mal, und mal nicht. Im
        # Protokoll des Benutzers steht beides innerhalb weniger Minuten:
        # zweimal gesucht und gelesen, dreimal aus dem Gedächtnis
        # geantwortet. Eine Anweisung, die in der Hälfte der Fälle befolgt
        # wird, ist keine Lösung, sondern eine Hoffnung.
        #
        # Wo die Entscheidung ohnehin feststeht, muss man sie nicht
        # delegieren. Fragt jemand nach Nachrichten, dann IST zu suchen -
        # da gibt es nichts zu entscheiden. Also wird gesucht, und das
        # Ergebnis liegt dem Modell vor, wenn es zu denken anfängt.
        tools_available = self._tool_engine is not None and self._tool_engine.enabled
        # Eine einfache gesprochene Wissens- oder Gespraechsfrage braucht
        # keine Beschreibung aller (derzeit 59) Werkzeuge. Diese Liste
        # machte aus einem kurzen Zug 15.000 bis 22.000 Zeichen Kontext und
        # wurde trotzdem bei jedem Satz mitgeschickt. Handlungsauftraege
        # behalten den vollstaendigen Werkzeugweg; nur eindeutig werkzeuglose
        # Sprachzuege werden davon befreit.
        # Eine Entscheidung fuer den ganzen Zug, an einer Stelle getroffen.
        #
        # Hier stand ein Schluesselwort-Tor: Ein gesprochener Zug bekam nur
        # dann Werkzeuge, wenn im Satz eines von rund fuenfzig Verben
        # vorkam. "Gut, meine Vorlieben, es muss im ersten Stock sein …" -
        # die Fortsetzung eines Suchauftrags ohne eigenes Verb - fiel
        # durch, und der Orb konnte nicht suchen, ohne dass irgendwo stand
        # warum. Die Voreinstellung ist jetzt umgedreht: im Zweifel mit
        # Werkzeugen. Der Vorlesungsabschnitt behaelt sein Verhalten.
        faehigkeit = self._faehigkeit_bestimmen(
            text,
            gesprochen=spoken,
            vorlesungssegment=vorlesungssegment,
            werkzeuge_vorhanden=tools_available,
        )
        model_tools_available = faehigkeit.werkzeuge and preferred_spoken is None
        # Bereits deterministisch ausgefuehrte Werkzeuge merken. Das Modell
        # bekommt deren Ergebnis weiter unten als Kontext. Fordert es dasselbe
        # Werkzeug trotzdem noch einmal an, darf daraus kein zweiter, teurer
        # Lauf werden (bei der Bildanalyse waren das zuletzt weitere 25 s).
        vorab_ergebnisse: dict[str, str] = {}
        vorab_suchkontext = ""
        # Browser-Befehle sind KEINE Suchanfragen: "öffne ein Browserfenster
        # und führe eine Suche durch" löste vorher acht Suchläufe mit dem
        # wörtlichen Befehlssatz aus - alle leer, und für den Benutzer sah
        # das aus wie "die Suche ist kaputt".
        if tools_available and faehigkeit.aktualitaet and not ist_browser_befehl(text):
            frisch = await self._vorab_suchen(text)
            if frisch:
                vorab_suchkontext = frisch
                context_block = "\n\n".join(
                    part for part in (context_block, frisch) if part
                )
                # Das Ergebnis liegt dem Modell bereits vor. Fordert es die
                # identische Suche trotzdem an, wird die vorhandene Antwort
                # benutzt statt erneut mehrere Suchmaschinen zu belasten.
                vorab_ergebnisse["internet_suchen"] = frisch.split("\n\n", 1)[-1].strip()

        # Ein Wissensauftrag ("eigne dir X an") WIRD angenommen - nicht dem
        # Modell ueberlassen, das ihn am 17.08. erst zerredete und dann
        # abstritt. Die Einarbeitung startet im Hintergrund; das Modell
        # bekommt die Zusage als Kontext und bestaetigt sie ehrlich.
        if tools_available and will_wissensauftrag(text):
            zusage = await self._vorab_wissen(text)
            if zusage:
                context_block = "\n\n".join(
                    part for part in (context_block, zusage) if part
                )
                vorab_ergebnisse["wissen_aneignen"] = (
                    "Der Auftrag läuft bereits im Hintergrund - nicht erneut starten."
                )

        # Bittet jemand ausdruecklich, auf den Bildschirm zu sehen, dann WIRD
        # hingesehen - deterministisch, nicht auf gut Glueck.
        #
        # Genau hier lag die wiederkehrende Klage: Der Benutzer sagte "mach
        # einen Printscreen und nutze das Werkzeug", und das Modell nannte das
        # Werkzeug, ohne es zu rufen. Ein Schubser (das Nachhaken) hilft oft,
        # aber "oft" ist bei einer klaren Ansage zu wenig. Wo die Entscheidung
        # feststeht, gehoert sie in den Ablauf: Der Orb macht das Bild selbst
        # und legt die Beschreibung dem Modell vor, bevor es zu denken anfaengt.
        if tools_available and will_bildschirm(text):
            gesehen = await self._vorab_bildschirm(text)
            if gesehen:
                context_block = "\n\n".join(
                    part for part in (context_block, gesehen) if part
                )
                vorab_ergebnisse["bildschirm_ansehen"] = (
                    gesehen.split("\n\n", 1)[-1].strip()
                )

                # Die Bildauswertung IST bereits eine Modellantwort auf die
                # konkrete Frage. Im Sprachweg ging sie bisher trotzdem noch
                # einmal an das Gespraechsmodell und kostete damit nach den
                # gemessenen 14-28 s fuer das Bild weitere 12-14 s. Das
                # veraendert den Befund nicht, sondern formuliert ihn nur neu.
                # Direkt sprechen halbiert hier die Wartezeit und verhindert
                # zugleich einen zweiten Screenshot durch die Werkzeugrunde.
                if spoken:
                    answer_text = vorab_ergebnisse["bildschirm_ansehen"]
                    self.conversations.add_assistant_message(answer_text)
                    self._wortwechsel_merken(text, answer_text, project_id)
                    return OrchestrationResult(
                        response=answer_text,
                        intent=intent.intent,
                        used_llm=True,
                        provider=self._providers.active_name,
                        module="vision",
                        data={
                            "gesprochen": False,
                            "werkzeugaufrufe": 1,
                            "direkte_bildantwort": True,
                        },
                    )

        # Nennt der Benutzer eine Adresse und will sie gelesen haben, dann WIRD
        # sie gelesen - dasselbe Prinzip wie bei Suche und Bildschirm. Vorher
        # nannte das Modell "webseite_lesen" und rief es nicht; hier holt der
        # Orb die Seite selbst und legt den Text vor.
        if tools_available:
            zu_lesen = will_webseite_lesen(text)
            if zu_lesen:
                gelesen = await self._vorab_webseite(zu_lesen)
                if gelesen:
                    context_block = "\n\n".join(
                        part for part in (context_block, gelesen) if part
                    )

        # Verlangt der Benutzer, im Browser etwas zu TUN (klicken, anmelden,
        # ein Formular), öffnet der Orb das Fenster deterministisch und zeigt,
        # was anklickbar ist. Klicken/Tippen macht das Modell danach mit dem
        # Werkzeug - aber der erste, so oft verweigerte Schritt (überhaupt
        # öffnen) ist damit getan.
        if tools_available:
            browser_ziel = will_browser(text)
            if browser_ziel:
                geoeffnet = await self._vorab_browser(browser_ziel)
                if geoeffnet:
                    context_block = "\n\n".join(
                        part for part in (context_block, geoeffnet) if part
                    )

        # Und bei einer Fachfrage in den EIGENEN Quellen.
        #
        # Der Benutzer hat das unmissverständlich verlangt: "er soll aber
        # die Suchmaschinen die verlinkt sind auch wirklich nutzen …
        # sonst bringt die Funktion nichts."
        #
        # Er hat recht, und es ist derselbe Punkt wie oben. Die Anweisung,
        # die Favoriten zu befragen, steht seit Wochen im Systemprompt des
        # Professors - und in keinem einzigen Protokoll taucht ein Aufruf
        # auf. Was verlässlich geschehen soll, gehört nicht in eine Bitte
        # an das Sprachmodell, sondern in den Ablauf.
        # Eine Bildschirm-/Bildanalyse ist bereits eine vollstaendige,
        # ausdrueckliche Aufgabe. Im Professor-Modus zusaetzlich noch alle
        # Favoritenportale zu durchsuchen, bevor das Bild ueberhaupt
        # beschrieben wird, machte aus einem Zug mehrere unabhaengige
        # Langlaeufer. Quellen werden bei einer anschliessenden Sach- oder
        # Forschungsfrage weiterhin wie vorgesehen benutzt.
        if (
            tools_available
            and not vorlesungssegment
            and not will_bildschirm(text)
            and self._ist_fachfrage(text, extra_context)
        ):
            eigenes = await self._vorab_eigene_quellen(text)
            if eigenes:
                context_block = "\n\n".join(
                    part for part in (context_block, eigenes) if part
                )
        instructions = ""
        if model_tools_available:
            try:
                instructions = self._tool_engine.system_instructions(text=text)
            except TypeError:
                # Kompatibel mit Plugins und kleinen Test-Doubles, die noch
                # die fruehere parameterlose Signatur anbieten.
                instructions = self._tool_engine.system_instructions()

        # Das Netz unter dem Netz: eine Obergrenze fuer alles Beigelegte.
        #
        # Gemessen am 19.08.2026 ueber 81 Anfragen: Median 21'000 Zeichen
        # je Anfrage, Spitze 39'661 - und bei einer Nachrichtenfrage
        # steckten davon 27'000 allein in den Suchergebnissen, bei DREI
        # Nachrichten im Verlauf. Das Modell brauchte danach 6,4 Sekunden
        # bis zum ersten Wort. Diese Sekunden hoert der Benutzer als
        # Stille, und sie waren der halbe Grund fuer "keine fluessige
        # Konversation".
        #
        # Gekuerzt wird von hinten: Vorn stehen Gedaechtnis und
        # Benutzerangaben, hinten die Werkzeuganleitung und die Fundstuecke.
        # Was wegfaellt, kann das Modell mit einem Werkzeug nachholen -
        # was vorn steht, nicht.
        # Fuer die konkrete Werkzeuganleitung Platz RESERVIEREN. Vorher wurde
        # sie hinten angehaengt und danach der Gesamtblock von vorn gekappt;
        # bei langen Erinnerungen fiel damit ausgerechnet die Werkzeugliste
        # weg. Das erklaert, warum die Einzeltests fuer Bilder/PDF bestanden,
        # der Orb die Faehigkeiten im echten Gespraech aber nicht verband.
        grundgrenze = max(
            2500,
            self._kontext_hoechstens - len(instructions) - (2 if instructions else 0),
        )
        if context_block and len(context_block) > grundgrenze:
            gekuerzt = context_block[:grundgrenze].rsplit("\n", 1)[0]
            logger.info(
                "Kontext von %d auf %d Zeichen gekuerzt (Grenze %d).",
                len(context_block), len(gekuerzt), grundgrenze,
            )
            context_block = (
                gekuerzt
                + "\n\n[Gekürzt. Brauchst du mehr, hol es dir mit einem Werkzeug.]"
            )
        if instructions:
            context_block = "\n\n".join(
                part for part in (context_block, instructions) if part
            )

        spoken_system = None
        if preferred_spoken:
            # Der lokale Schnellweg darf den persoenlichen Grundprompt nicht
            # ersetzen. Genau das geschah zuvor: online Mentor, offline ein
            # austauschbarer Assistent. Der kurze Zusatz begrenzt nur die
            # Laenge der gesprochenen Antwort.
            base_system = str(self._config.get("conversation.system_prompt", "")).strip()
            spoken_system = "\n\n".join(
                part for part in (base_system, self.LOCAL_SPOKEN_SYSTEM) if part
            )

        messages = self.conversations.build_messages(
            extra_context=context_block,
            system_prompt=spoken_system,
            recent_limit=(2 if preferred_spoken else None),
        )
        logger.info(
            "[%s] Tor 6 Modellkontext: %d Nachrichten, %d Zeichen, "
            "Wunschprovider=%s, Werkzeuge=%s (%s, Konfidenz %.2f, Signale: %s).",
            self._kennung(),
            len(messages),
            sum(len(message.content) for message in messages),
            preferred_spoken or "standard",
            model_tools_available,
            faehigkeit.begruendung,
            faehigkeit.konfidenz,
            ", ".join(faehigkeit.signale) or "keine",
        )
        mark_stage("model_context_ready")

        strom: SpeechStream | None = None
        #: Ob wirklich etwas zu hören war – nicht bloss, ob Text an die
        #: Sprachausgabe gereicht wurde.
        #:
        #: Der Unterschied ist der ganze Fehler, der den Orb verstummen
        #: liess: Vorher galt eine Antwort als gesprochen, sobald der Satz
        #: weitergegeben war. Schlug die Sprachausgabe still fehl, meldete
        #: der Weg trotzdem „schon gesagt" – und die Sprachschicht
        #: verzichtete darauf, sie noch einmal zu sprechen. Der Orb dachte,
        #: antwortete, hielt es für erledigt und blieb stumm.
        wirklich_gesprochen = False
        bild_geplant = False

        try:
            if on_speech is not None:

                async def _sprich(satz: str) -> bool:
                    nonlocal wirklich_gesprochen, bild_geplant
                    gehoert = bool(await on_speech(satz))
                    wirklich_gesprochen = wirklich_gesprochen or gehoert
                    return gehoert

                response, strom = await self._stream_and_speak(
                    messages,
                    _sprich,
                    preferred=preferred_spoken,
                    max_tokens=self._sprechgrenze(
                        vorlesungssegment=vorlesungssegment,
                        gesprochen=spoken,
                        mit_werkzeugen=model_tools_available,
                    ),
                )
            else:
                response = await self._providers.chat(messages)
            mark_stage("model_completed")
        except ProviderError as error:
            logger.error("Keine Modellantwort möglich: %s", error)
            fallback = (
                "Ich kann gerade kein Sprachmodell erreichen. "
                "Prüfe bitte deine Internetverbindung oder ob Ollama lokal läuft. "
                "Lokale Aufgaben (Programme starten, Dateien suchen, Aufgaben verwalten) "
                "funktionieren weiterhin."
            )
            self.conversations.add_assistant_message(fallback)
            return OrchestrationResult(
                response=fallback,
                intent=intent.intent,
                used_llm=False,
                module="ai_provider",
                data={"error": str(error)},
            )

        answer_text = (
            lehrstoff_vervollstaendigen(response.text)
            if vorlesungssegment
            else response.text
        )
        if vorlesungssegment:
            # Genau eine Suche mit dem vollstaendigen Abschnitt. Der alte
            # Fruehstart wurde unmittelbar danach durch eine neue Generation
            # entwertet und lud Bilder doppelt, ohne sie sichtbar zu machen.
            # Da das Audio zu diesem Zeitpunkt noch laeuft, begleitet die
            # Lehrtafel den Vortrag trotzdem rechtzeitig.
            self._vorlesungsbild_planen(answer_text, text, infografik_erlaubt=True)
            bild_geplant = True
        tool_runs = 0
        #: Welche Werkzeuge wirklich liefen. Die blosse Anzahl genuegte
        #: der Anzeige, aber nicht dem Schattenlauf: Der vergleicht die
        #: WAHL des Werkzeugs, und dafuer braucht er Namen.
        werkzeugnamen: list[str] = []
        if model_tools_available:
            # Enthält die Antwort Werkzeugaufrufe, hier ausführen – mit
            # Sicherheitsprüfung und Prüfprotokoll, im selben Gespräch.
            answer_text, runs = await self._tool_engine.continue_with_tools(
                messages,
                response.text,
                actor="gespraech",
                preexecuted=vorab_ergebnisse,
            )
            tool_runs = len(runs)
            werkzeugnamen = [str(getattr(lauf, "tool", "")) for lauf in runs]

            # Letzte Zuverlaessigkeitsschicht fuer PDF-Auftraege: Manche
            # Modelle liefern nach Recherche bereits einen vollstaendigen,
            # gut gegliederten Inhalt, vergessen aber trotz Nachhaken den
            # eigentlichen Schreibaufruf. Dann wird genau dieser Inhalt
            # deterministisch gespeichert. Eine Ausrede oder ein kurzer
            # Platzhalter wird bewusst NICHT in eine nutzlose PDF gegossen.
            # Einige Integrationen/Test-Doubles liefern fuer einen Lauf nur
            # einen opaken Marker. Solche Eintraege sind kein PDF-Erfolg, duerfen
            # aber die normale Werkzeugantwort auch nicht abbrechen.
            pdf_runs = [
                run
                for run in runs
                if getattr(run, "tool", "") == "pdf_erstellen"
                and bool(getattr(getattr(run, "result", None), "ok", False))
            ]
            pdf_done = bool(pdf_runs)
            bildhinweise: list[str] = []

            # Hat das Modell die PDF bereits erzeugt, aber den ausdruecklich
            # verlangten Bildteil vergessen, wird genau dieses Dokument
            # nachgeruestet. Die Einzelwerkzeuge konnten Bilder schon laenger;
            # die fehlende garantierte Verkettung war der eigentliche Fehler.
            if will_pdf_mit_grafik(text) and pdf_runs:
                letzter_pdf_lauf = pdf_runs[-1]
                bildzahl = int(
                    getattr(getattr(letzter_pdf_lauf, "result", None), "context", {}).get(
                        "images", 0
                    )
                    or 0
                )
                if bildzahl < 1:
                    pdf_argumente = dict(getattr(letzter_pdf_lauf, "arguments", {}) or {})
                    pdf_inhalt = str(pdf_argumente.get("inhalt", "") or "")
                    pdf_quellen = str(pdf_argumente.get("quellen", "") or "")
                    bilder, bildhinweise = await self._pdf_bilder_beschaffen(
                        text, pdf_inhalt, pdf_quellen
                    )
                    if bilder:
                        vorhandene = pdf_argumente.get("bilder") or []
                        if not isinstance(vorhandene, list):
                            vorhandene = [vorhandene]
                        pdf_argumente["bilder"] = [*vorhandene, *bilder]
                        pdf_argumente["pfad"] = str(
                            getattr(letzter_pdf_lauf.result, "context", {}).get("path", "")
                            or pdf_argumente.get("pfad", "")
                        )
                        pdf_argumente["ueberschreiben"] = True
                        lauf = await self._tool_engine.direkt_ausfuehren(
                            "pdf_erstellen", pdf_argumente, actor="pdf-grafik-nachruestung"
                        )
                        runs.append(lauf)
                        tool_runs = len(runs)
                        werkzeugnamen = [str(getattr(r, "tool", "")) for r in runs]
                        if lauf.result.ok:
                            answer_text = str(lauf.result.output)
                            pdf_done = True
            lowered_answer = answer_text.lower()
            pdf_excuse = any(
                marker in lowered_answer
                for marker in (
                    "kann kein pdf", "keine pdf erstellen", "nicht als pdf",
                    "kein werkzeug", "kann ich nicht", "nicht möglich",
                    "nicht moeglich",
                )
            )
            if (
                will_pdf_erstellen(text)
                and not pdf_done
                and not pdf_excuse
                and len(answer_text.strip()) >= 120
            ):
                urls = _re.findall(r"https?://[^\s<>]+", vorab_suchkontext)
                quellen = "\n".join(dict.fromkeys(url.rstrip(".,)") for url in urls))
                bilder: list[dict[str, str]] = []
                if will_pdf_mit_grafik(text):
                    bilder, bildhinweise = await self._pdf_bilder_beschaffen(
                        text, answer_text, quellen
                    )
                lauf = await self._tool_engine.direkt_ausfuehren(
                    "pdf_erstellen",
                    {
                        "titel": pdf_titel_aus(text),
                        "inhalt": answer_text,
                        "quellen": quellen,
                        "bilder": bilder,
                    },
                    actor="pdf-auftrag",
                )
                runs.append(lauf)
                tool_runs = len(runs)
                werkzeugnamen = [str(getattr(r, "tool", "")) for r in runs]
                if lauf.result.ok:
                    answer_text = str(lauf.result.output)
                    if bildhinweise:
                        answer_text += " " + " ".join(bildhinweise)
                else:
                    answer_text = (
                        answer_text
                        + "\n\nDie PDF-Datei konnte nicht gespeichert werden: "
                        + str(lauf.result.error or "unbekannter Fehler")
                    )

            if pdf_done and bildhinweise and answer_text:
                fehlende_hinweise = [hinweis for hinweis in bildhinweise if hinweis not in answer_text]
                if fehlende_hinweise:
                    answer_text += " " + " ".join(fehlende_hinweise)

        # Was während des Denkens schon gesprochen wurde, darf nicht noch
        # einmal kommen. Nach einem Werkzeugaufruf steht meist eine ganz
        # neue Antwort da – dann wird sie vollständig gesprochen; ohne
        # Werkzeug bleibt höchstens der Schlusssatz übrig.
        if strom is not None:
            rest = remaining_after(strom.spoken, answer_text)
            if rest and on_speech is not None:
                if await on_speech(rest):
                    wirklich_gesprochen = True

        self.conversations.add_assistant_message(answer_text)
        lernstand = getattr(self, "_lernstand", None)
        if lernstand is not None:
            with contextlib.suppress(Exception):
                lernstand.lehrweg_notieren(answer_text)
        self._wortwechsel_merken(text, answer_text, project_id)

        return OrchestrationResult(
            response=answer_text,
            intent=intent.intent,
            used_llm=True,
            provider=response.provider,
            model=response.model,
            module=route.module or "ai_provider",
            data={
                "latency": round(response.latency_seconds, 3),
                "werkzeugaufrufe": tool_runs,
                "werkzeuge": werkzeugnamen,
                # Sagt der Sprachschicht: Diese Antwort war wirklich zu
                # hören. Ohne diesen Vermerk käme sie ein zweites Mal – mit
                # einem falschen gar nicht.
                "gesprochen": wirklich_gesprochen,
            },
        )

    def _vorlesungsbild_planen(
        self,
        abschnitt: str,
        auftrag: str,
        *,
        infografik_erlaubt: bool = True,
    ) -> None:
        """Startet eine Bildsuche, ohne Sprechen oder Folgezuege aufzuhalten."""

        if (
            not str(abschnitt or "").strip()
            or self._event_bus is None
            or self._tool_engine is None
            or not self._tool_engine.enabled
        ):
            return
        self._vorlesungsbild_generation += 1
        generation = self._vorlesungsbild_generation
        task = asyncio.create_task(
            self._vorlesungsbild_aktualisieren(
                abschnitt,
                auftrag,
                generation,
                infografik_erlaubt=infografik_erlaubt,
            ),
            name=f"vorlesungsbild-{generation}",
        )
        self._vorlesungsbild_tasks.add(task)
        task.add_done_callback(self._vorlesungsbild_tasks.discard)

    async def _vorlesungsbild_aktualisieren(
        self,
        abschnitt: str,
        auftrag: str,
        generation: int,
        *,
        infografik_erlaubt: bool = True,
    ) -> None:
        """Sucht ein passendes Bild und meldet es an die Desktop-Lehrtafel.

        Foto und Orientierung sind keine Alternativen mehr: Ein passendes
        reales Bild bleibt gross sichtbar, daneben stehen wenige responsive
        Orientierungskarten. Gibt es kein belastbares Foto, bleibt die
        Uebersicht allein sichtbar, statt ein schwer lesbares Rasterbild zu
        erzeugen.
        """

        try:
            begriffe = bildsuchbegriffe(abschnitt, auftrag)
            bild: dict[str, str] | None = None
            for begriff in begriffe:
                schluessel = begriff.casefold()
                bild = self._vorlesungsbild_cache.get(schluessel)
                if bild is None:
                    lauf = await self._tool_engine.direkt_ausfuehren(
                        "bild_suchen",
                        {"begriff": begriff, "anzahl": 3, "relevanz": begriff},
                        actor="vorlesung-bild",
                    )
                    if not lauf.result.ok:
                        continue
                    eintraege = list(lauf.result.context.get("bilder", []) or [])
                    if not eintraege:
                        continue
                    passende = [
                        treffer
                        for treffer in eintraege
                        if bild_passt(begriff, treffer)
                    ]
                    eintrag = (
                        max(
                            passende,
                            key=lambda treffer: bild_treffer_bewerten(begriff, treffer),
                        )
                        if passende
                        else None
                    )
                    if eintrag is None:
                        logger.info(
                            "Bildtreffer zu '%s' verworfen: Metadaten passen nicht.",
                            begriff,
                        )
                        continue
                    pfad = str(eintrag.get("pfad", "") or "").strip()
                    if not pfad:
                        continue
                    bild = {
                        "path": pfad,
                        "caption": str(
                            eintrag.get("nachweis", "Freies Bild") or "Freies Bild"
                        ),
                        "kind": "photo",
                    }
                    self._vorlesungsbild_cache[schluessel] = bild
                break

            # Ein langsamer alter Abruf darf die Tafel des inzwischen
            # begonnenen Folgeabschnitts nicht wieder ueberschreiben.
            if generation != self._vorlesungsbild_generation:
                return
            if not infografik_erlaubt:
                return
            karten = uebersichtskarten(abschnitt)
            titel = vorlesungsfolie_titel(abschnitt, auftrag)
            await self._publish(
                event_types.LECTURE_VISUAL_CHANGED,
                {
                    **(bild or {}),
                    "path": str((bild or {}).get("path", "")),
                    "caption": str((bild or {}).get("caption", "")),
                    "kind": "photo-overview" if bild else "overview",
                    "title": titel,
                    "topic": vorlesungsthema(auftrag),
                    "summary": karten,
                    "layout": uebersichtsart(abschnitt),
                    "generation": generation,
                },
            )
            logger.info(
                "Vorlesungstafel %d aktualisiert (%s, %d Orientierungskarten).",
                generation,
                "Foto" if bild else "ohne Foto",
                len(karten),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - Bildmaterial darf den Vortrag nie stoppen.
            logger.exception("Das Vorlesungsbild konnte nicht beschafft werden.")

    async def _pdf_bilder_beschaffen(
        self, text: str, inhalt: str, quellen: str = ""
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Erzeugt die fuer eine visuelle PDF verlangten Bilddateien.

        Eine lokale Infografik ist der verlaessliche Grundstock. Reale Fotos
        werden nur bei ausdruecklichem Wunsch gesucht und behalten ihren
        Lizenznachweis als Bildunterschrift. Ein ausgefallener Bilddienst
        verhindert die PDF nicht.
        """

        if self._tool_engine is None or not self._tool_engine.enabled:
            return [], ["Grafiken waren angefordert, die Werkzeuge sind aber deaktiviert."]

        titel = pdf_titel_aus(text)
        bilder: list[dict[str, str]] = []
        hinweise: list[str] = []
        quelle = next((zeile.strip() for zeile in quellen.splitlines() if zeile.strip()), "")

        infografik = await self._tool_engine.direkt_ausfuehren(
            "infografik_erstellen",
            {"titel": titel, "inhalt": inhalt, "quelle": quelle},
            actor="pdf-grafik",
        )
        if infografik.result.ok:
            pfad = str(infografik.result.context.get("pfad", "") or "")
            if pfad:
                bilder.append(
                    {
                        "pfad": pfad,
                        "beschriftung": str(
                            infografik.result.context.get("nachweis", "Infografik: AI-Orb")
                        ),
                    }
                )
        else:
            hinweise.append(
                "Die lokale Infografik konnte nicht erstellt werden: "
                + str(infografik.result.error or "unbekannter Fehler")
            )

        if will_pdf_mit_fotos(text):
            fotos = await self._tool_engine.direkt_ausfuehren(
                "bild_suchen", {"begriff": titel, "anzahl": 2}, actor="pdf-fotos"
            )
            if fotos.result.ok:
                for eintrag in list(fotos.result.context.get("bilder", []) or [])[:2]:
                    pfad = str(eintrag.get("pfad", "") or "")
                    if pfad:
                        bilder.append(
                            {
                                "pfad": pfad,
                                "beschriftung": str(
                                    eintrag.get("nachweis", "Freies Foto") or "Freies Foto"
                                ),
                            }
                        )
            else:
                hinweise.append(
                    "Freie Fotos waren angefordert, der Bilddienst lieferte aber keine: "
                    + str(fotos.result.error or "unbekannter Fehler")
                )

        return bilder, hinweise

    async def _stream_and_speak(
        self,
        messages: list[Any],
        on_speech: Callable[[str], Awaitable[bool]],
        *,
        preferred: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[Any, SpeechStream]:
        """Holt die Antwort stückweise und spricht jeden fertigen Satz sofort.

        Damit beginnt der Orb zu reden, während er den Rest noch denkt. Die
        gemessene Wartezeit ändert sich dadurch nicht – die empfundene
        halbiert sich, und die ist die einzige, die jemand erlebt.

        Werkzeugaufrufe stehen als eingezäunter Block mitten in der
        Antwort; :class:`SpeechStream` hält sie zurück, damit nie
        Maschinensprache vorgelesen wird.

        Scheitert der Fluss, bleibt der gewöhnliche Weg: lieber die ganze
        Antwort auf einmal als gar keine.
        """

        from backend.orchestrator.providers.base_provider import ProviderResponse

        strom = SpeechStream()
        stuecke: list[str] = []
        begonnen = time.perf_counter()

        try:
            async for stueck in self._providers.chat_stream(
                messages,
                preferred=preferred,
                max_tokens=(
                    max_tokens
                    if max_tokens is not None
                    else int(self._config.get("voice.spoken_max_tokens", 96))
                    if preferred
                    else None
                ),
            ):
                stuecke.append(stueck)
                for satz in strom.feed(stueck):
                    await on_speech(satz)
            for satz in strom.finish():
                await on_speech(satz)
        except ProviderError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Der Fluss ist gescheitert; die Antwort kommt am Stück.")
            if not stuecke:
                return await self._providers.chat(messages), SpeechStream()

        return (
            ProviderResponse(
                text="".join(stuecke),
                provider=self._providers.active_name or "",
                model="",
                latency_seconds=time.perf_counter() - begonnen,
                finish_reason="stop",
            ),
            strom,
        )

    def _preferred_spoken_provider(
        self,
        text: str,
        intent: IntentResult,
        extra_context: str | None,
    ) -> str | None:
        """Nimmt fuer kurze Alltagsfragen sofort das lokale Modell.

        Claude Code bleibt fuer Werkzeuge, Programmierung, Recherche und
        Facharbeit reserviert. Eine normale gesprochene Frage darf dagegen
        nicht erst dessen Prozessfrist abwarten, obwohl Ollama bereits laeuft.
        """

        # Im Offlinebetrieb darf das kleine Nebenmodell kurze, klar
        # werkzeuglose Sprachzuege uebernehmen. Der Provider-Manager gibt
        # diesen Namen nur bei bewusstem Offlinebetrieb oder nach einem
        # echten Netz-/Cloud-Ausfall heraus. Online bleibt Claude damit
        # unveraendert der Hauptprovider.
        local_selector = getattr(self._providers, "local_provider_for", None)
        offline_fast = local_selector("fast") if callable(local_selector) else None

        # Standardmaessig AUS - Claude bleibt der Hauptprovider.
        #
        # Der Benutzer hat das ausdruecklich verlangt: "der Wunschprovider
        # ist nicht ollama sondern Claude; er soll andere Modelle fuer
        # Sub-Agenten nutzen, um die Effizienz zu steigern." Genau so ist
        # es jetzt eingerichtet: Die HAUPTANTWORT kommt von Claude, und die
        # Ersparnis entsteht bei den Teilaufgaben (siehe agents.modelle in
        # der config.yaml - conversation/reasoning/history laufen ueber
        # OpenRouter, research/coding lokal).
        #
        # Die Umleitung der Hauptantwort auf das lokale Modell hatte zwei
        # Nachteile, die zusammen den Betrieb beschaedigten: Sie nahm der
        # Anfrage die WERKZEUGE (siehe model_tools_available), und das
        # kleine Modell brauchte im Protokoll 40 Sekunden fuer eine
        # Antwort, die Claude in vier lieferte. Wer sie dennoch will,
        # schaltet sie hier ein.
        if not offline_fast and not bool(
            self._config.get("ai.lokal_fuer_alltag", False)
        ):
            return None

        local = list(getattr(self._providers, "local_provider_names", []) or [])
        if not local or intent.intent not in {CHAT, DOCUMENT, QUESTION, SMALL_TALK}:
            return None

        stripped = text.strip()
        # The intent class already excludes program, file, browser and other
        # action commands. Requiring a question mark here rejected ordinary
        # speech such as "Nenne mir ein Tier" and attached all tool schemas.
        looks_conversational = True
        if not looks_conversational or len(stripped) > 220:
            return None
        if (
            braucht_aktuelles(stripped)
            # Der entscheidende Wächter: Alles, was zu TUN ist, bleibt beim
            # werkzeugfähigen Weg. Er stand vorher nicht hier, und die
            # Aufgabe "mach einen Printscreen, lies das Dokument, merk es
            # dir" landete beim lokalen Modell ohne Werkzeuge.
            or braucht_werkzeuge(stripped)
            or ist_browser_befehl(stripped)
            or will_bildschirm(stripped)
            or will_webseite_lesen(stripped)
            or will_browser(stripped)
            or self._ist_fachfrage(stripped, extra_context)
        ):
            return None
        return str(offline_fast or local[0])

    def _ist_fachfrage(self, text: str, extra_context: str | None) -> bool:
        """Ob in den eigenen Quellen des Benutzers zu suchen ist.

        Zwei Wege, und der zweite ist der wichtigere.

        Der erste ist die Wortliste des Professors (``looks_academic``).
        Sie fängt vieles, aber nicht alles: „Welche Ursachen hatte der
        Investiturstreit?" enthält kein einziges ihrer Merkmale, weil
        Eigennamen dort naturgemäss fehlen. Eine Liste, die auch
        „Investiturstreit", „Sattelzeit" und „Reichsdeputationshauptschluss"
        kennt, ist nicht zu schreiben.

        Der zweite Weg umgeht das: Ist der Professor für diesen Zug im
        Dienst, IST es eine Fachfrage - er hat das bereits entschieden,
        und zwar mit mehr Wissen als eine Wortliste (laufender Vorgang,
        ausdrücklich verlangter Modus, Lernprofil). Statt seine
        Entscheidung nachzubauen, wird sie gelesen.

        Ausgenommen bleiben Fragen nach Aktuellem. Wer nach den
        Nachrichten von heute fragt, ist mit den Nachrichtenhäusern besser
        bedient als mit einem Archivportal - und zehn Suchläufe für eine
        Frage sind ohnehin zu viele.
        """

        # Erst hier eingebunden und nicht oben: Der Professor haengt am
        # Agentenpaket, das seinerseits ueber den Cognitive Core wieder
        # hierher zeigt. Ein Import auf Modulebene waere ein Ring, und
        # Python bricht Ringe mit einer Fehlermeldung ab, die niemand mit
        # dieser Zeile in Verbindung bringt.
        from backend.agents.history_agent.bridge import looks_academic

        if braucht_aktuelles(text):
            return False
        # Ein laufender Professor-Modus macht nicht jede kurze
        # Gespraechsfortsetzung zu einem neuen Rechercheauftrag. Im
        # Betriebsprotokoll loesten Ein-Wort-Nachtraege wie
        # "Wissenschaftlich" dieselbe mehrfache Portalsuche aus wie eine
        # echte Fachfrage. Das blockiert den Dialog, ohne neue Information
        # zu liefern. Ausdrueckliche Such-/Quellenauftraege bleiben davon
        # unberuehrt.
        knapp = " ".join((text or "").strip().split())
        woerter = knapp.split()
        verlangt_quellen = any(
            marker in knapp.lower()
            for marker in (
                "such", "recherch", "quelle", "quellen", "beleg",
                "literatur", "forschungsstand", "nachschlagen",
            )
        )
        if len(woerter) < 4 and not verlangt_quellen:
            return False
        if looks_academic(text):
            return True
        # Der Professor baut den Systemprompt, wenn er übernimmt. Steht er
        # im Zusatzkontext, hat er sich für zuständig erklärt.
        if not (
            bool(extra_context)
            and any(
                marker in str(extra_context)
                for marker in ("Geschichtsprofessor", "Fachprofessor", "FACH:")
            )
        ):
            return False
        # Der Professor darf Eigennamen auffangen, die keine Wortliste kennen
        # kann. Dafuer muss es aber eine inhaltliche Frage oder ein
        # substanzieller Satz sein - kein Modusbefehl und keine Bestaetigung.
        fragewoerter = (
            "wer ", "was ", "wann ", "wo ", "wie ", "warum ",
            "weshalb ", "welche ", "welcher ", "welches ", "wodurch ",
        )
        ist_frage = "?" in knapp or knapp.lower().startswith(fragewoerter)
        # Laenge allein ist kein Fachsignal. Der Satz "Erklaere mir in einem
        # Satz, was ein Regenbogen ist" hatte neun Woerter und startete
        # deshalb Favoritenzugriff, Werkzeugprompt und Professor-Recherche.
        # Das kostete zehn Sekunden und lieferte trotzdem keine Antwort.
        # Eigennamenfragen faengt das Fragezeichen/Fragewort auf; ein bloss
        # langer Erklaerwunsch bleibt ein normaler Erklaerwunsch.
        return verlangt_quellen or ist_frage

    async def _vorab_eigene_quellen(self, text: str) -> str:
        """Sucht bei einer Fachfrage gezielt IN den Favoriten des Benutzers.

        Nicht in den Lesezeichen - in den Seiten, auf die sie zeigen. Das
        ist der Unterschied, wegen dem die Funktion vorher nichts brachte:
        Ein Archivportal in der Leiste war ein Link und keine Quelle.
        """

        einstellungen = self._config.get("recherche.favoriten", {}) or {}
        if not bool(einstellungen.get("nutzen", True)):
            return ""
        if self._tool_engine is None:
            return ""

        from backend.research.eigene_quellen import eigene_domaenen
        from backend.research.suchmasken import favoriten_suche
        from backend.tools.web_tools import (
            quellen_gegenueberstellen,
            suchbegriff_aus,
        )

        domaenen = await asyncio.to_thread(
            eigene_domaenen,
            ordner=str(einstellungen.get("ordner", "") or ""),
            hoechstens=int(einstellungen.get("max_domaenen", 4) or 4),
        )
        if not domaenen:
            logger.info(
                "Keine brauchbaren Favoriten gefunden - es bleibt bei der "
                "gewöhnlichen Suche."
            )
            return ""

        # Jetzt werden die Favoriten nicht mehr bloss mit ``site:`` von
        # aussen abgesucht, sondern - wo es geht - über ihre EIGENE
        # Suchmaske bedient (JSTOR, BASE, Semantic Scholar, Wikipedia …).
        # Für die übrigen bleibt es beim ``site:``-Weg. Wikipedia ist als
        # Auffangquelle immer dabei, damit eine Fachfrage nie ganz leer
        # ausgeht.
        gesammelt = await favoriten_suche(
            suchbegriff_aus(text),
            list(domaenen),
            je_quelle=int(einstellungen.get("treffer_je_domaene", 3) or 3),
        )
        if not gesammelt:
            logger.info("In den eigenen Quellen war zu %r nichts zu finden.", text[:60])
            return ""

        logger.info(
            "In eigenen Quellen gesucht, %d davon mit Treffern: %s",
            len(gesammelt),
            ", ".join(gesammelt),
        )
        return (
            "AUS DEN EIGENEN QUELLEN DES BENUTZERS (seine Favoriten - über "
            "Jahre gesammelte, geprüfte Anlaufstellen). Diese gehen einem "
            "beliebigen Suchtreffer vor und sind eher zitierfähig. Nenne, "
            "aus welcher seiner Quellen etwas stammt, und lies mit "
            "'webseite_lesen' nach, wenn die Trefferzeile nicht reicht:\n\n"
            + quellen_gegenueberstellen(gesammelt)
        )

    async def _vorab_suchen(self, text: str) -> str:
        """Sucht zu einer Frage nach Aktuellem und gibt das Ergebnis zurück.

        Scheitert die Suche, wird das ebenfalls mitgegeben - und zwar im
        Klartext. Das ist wichtiger, als es klingt: Ein Modell, das nicht
        weiss, dass die Suche versagt hat, erfindet an ihrer Stelle etwas
        Plausibles. Eines, dem man es sagt, kann es dem Benutzer sagen.
        """

        if self._tool_engine is None:
            return ""

        # Mehrere Häuser statt eines besten Treffers.
        #
        # Der Benutzer fragte, ob auch andere Berichterstattung einfliesst -
        # Al Jazeera etwa. Vorher nicht: Der Orb las, was oben stand, und
        # das ist bei deutschen Fragen fast immer tagesschau oder zdfheute.
        #
        # Wer wissen will, wie über einen Konflikt BERICHTET wird, braucht
        # nicht den besten Treffer, sondern mehrere Darstellungen
        # nebeneinander. Der beste Treffer leistet das nicht: Er ist eine
        # Sicht, die sich als die Sache ausgibt.
        from backend.tools.web_tools import suchbegriff_aus

        # "Wiederhole die Suche" wiederholt die LETZTE Suche - der Satz
        # selbst ist kein Suchbegriff. Ohne diesen Griff wurde er woertlich
        # gesucht (belegt im Protokoll: 'Wiederhole die Suche, sie muss
        # funktionieren.'), ergab nichts, und jede Wiederholung erst recht.
        knapp = " " + " ".join(text.lower().split()) + " "
        ist_wiederholung = any(w in knapp for w in (
            "wiederhol", "noch einmal such", "nochmal such", "nochmals such",
            "such nochmal", "such noch einmal", "erneut such", "such erneut",
        ))
        # "Ja, bitte suche gezielt danach" benennt kein Thema - es ZEIGT auf
        # eines, naemlich das der vorigen Frage. Am 17.08. wurde genau dieser
        # Satz woertlich gesucht: 'gezielt danach', fuenf beliebige
        # Wikipedia-Treffer, dem Modell als frische Ergebnisse vorgelegt -
        # und die Antwort darauf war erfunden. Ob ein Satz ein Thema
        # benennt, pruefen die Inhaltsworte; tut er es nicht, gilt er als
        # Fortsetzung der letzten Suche.
        from backend.research.offene_quellen import _inhaltsworte

        ohne_thema = not _inhaltsworte(text)
        if (ist_wiederholung or ohne_thema) and self._letzter_suchbegriff:
            begriff = self._letzter_suchbegriff
            such_text = begriff
            logger.info("Suche fortgesetzt mit dem letzten Begriff: %r", begriff)
        elif ohne_thema:
            # Kein Thema und keine letzte Suche: Eine woertliche Suche nach
            # Verweiswoertern liefert nur Zufallstreffer, die das Modell in
            # die Irre fuehren. Dann lieber gar keine Vorabsuche - das
            # Modell hat seine Werkzeuge und den Gespraechsverlauf.
            logger.info("Vorabsuche uebersprungen: %r benennt kein Thema.", text[:60])
            return ""
        else:
            begriff = suchbegriff_aus(text)
            self._letzter_suchbegriff = begriff
            such_text = text

        mehr = await self._vorab_mehrquellen(such_text)
        if mehr:
            return mehr

        try:
            lauf = await self._tool_engine.direkt_ausfuehren(
                "internet_suchen", {"suchbegriff": begriff, "max_treffer": 5}
            )
        except Exception:  # noqa: BLE001 - eine Vorabsuche darf nie die Antwort verhindern.
            logger.exception("Die Vorabsuche ist gescheitert.")
            return ""

        if lauf.result.ok and lauf.result.output:
            logger.info("Vorab gesucht zu %r (%.1f s).", text[:60], lauf.seconds)
            return (
                "FRISCH GESUCHT - diese Treffer sind von jetzt und gehen deinem "
                "eigenen Wissensstand vor. Stützte deine Antwort darauf und nenne, "
                "woher sie stammt. Reicht dir das nicht, lies mit 'webseite_lesen' "
                "nach:\n\n" + str(lauf.result.output)
            )

        logger.warning("Die Vorabsuche brachte nichts: %s", lauf.result.error)
        return (
            "HINWEIS: Ich habe für diese Frage zu suchen versucht, und es hat "
            "nicht geklappt: " + str(lauf.result.error or "kein Ergebnis") +
            " Sage dem Benutzer, dass die Suche gerade nicht geht, statt aus dem "
            "Gedächtnis zu antworten."
        )

    async def _vorab_wissen(self, text: str) -> str:
        """Startet einen Wissensauftrag - deterministisch, im Hintergrund.

        Das Gegenstueck zur erzwungenen Vorabsuche, fuers Aneignen. Belegt
        am 17.08.2026, 21:36: "Eigne dir sein Wissen an" - das Modell
        nannte das Werkzeug und rief es nicht; auf "ja, mach das" stritt es
        den Auftrag ab. Wo die Entscheidung feststeht, wird sie nicht
        delegiert: Der Orb startet die Einarbeitung selbst.

        Im HINTERGRUND, nicht davor: Das Einlesen mehrerer Quellen samt
        Destillat dauert eine halbe Minute und mehr. Der Benutzer bekommt
        sofort eine ehrliche Zusage; das Ergebnis landet im Themenwissen
        und ist ab dann abrufbar.
        """

        if self._tool_engine is None:
            return ""
        thema = wissensthema_aus(text)
        if not thema:
            return ""

        engine = self._tool_engine

        async def _lauf() -> None:
            try:
                lauf = await engine.direkt_ausfuehren(
                    "wissen_aneignen", {"thema": thema, "max_quellen": 3}
                )
                if lauf.result.ok:
                    logger.info("Wissensauftrag erledigt: %r.", thema)
                else:
                    logger.warning(
                        "Wissensauftrag %r fehlgeschlagen: %s",
                        thema, lauf.result.error,
                    )
            except Exception:  # noqa: BLE001 - Hintergrundarbeit stuerzt nie durch.
                logger.exception("Wissensauftrag %r abgebrochen.", thema)

        auftrag = asyncio.create_task(_lauf(), name=f"wissensauftrag:{thema[:30]}")
        # Verwahren, sonst raeumt der Speicherbereiniger die Aufgabe ab.
        laufende = getattr(self, "_wissensauftraege", None)
        if laufende is None:
            laufende = set()
            self._wissensauftraege = laufende
        laufende.add(auftrag)
        auftrag.add_done_callback(laufende.discard)

        logger.info("Wissensauftrag angenommen: %r.", thema)
        return (
            f"WISSENSAUFTRAG ANGENOMMEN. Die Einarbeitung in '{thema}' läuft "
            "bereits im Hintergrund: Es werden mehrere Quellen gelesen, "
            "belegte Aussagen destilliert und dauerhaft behalten. Sage dem "
            "Benutzer genau das kurz zu. Behaupte NICHT, es sei schon "
            "fertig, lehne den Auftrag NICHT ab, und rufe 'wissen_aneignen' "
            "NICHT noch einmal - es läuft schon."
        )

    async def _vorab_bildschirm(self, text: str) -> str:
        """Sieht auf den Bildschirm - deterministisch, ohne das Modell zu fragen.

        Das ist das Gegenstueck zur erzwungenen Vorabsuche, nur fuers Sehen.
        Bittet der Benutzer ausdruecklich darum ("mach einen Printscreen",
        "was ist auf dem Bildschirm"), nimmt der Orb das Bild selbst auf und
        wertet es aus, statt zu hoffen, dass das Modell von sich aus das
        Werkzeug ruft. Die Beschreibung liegt dem Modell dann vor, wenn es zu
        antworten beginnt.
        """

        if self._tool_engine is None:
            return ""

        try:
            lauf = await self._tool_engine.direkt_ausfuehren(
                "bildschirm_ansehen", {"frage": text[:200]}
            )
        except Exception:  # noqa: BLE001 - das Ansehen darf die Antwort nie verhindern.
            logger.exception("Das erzwungene Bildschirm-Ansehen ist gescheitert.")
            return ""

        if lauf.result.ok and lauf.result.output:
            logger.info("Bildschirm vorab angesehen (%.1f s).", lauf.seconds)
            return (
                "SO SIEHT DER BILDSCHIRM DES BENUTZERS GERADE AUS (soeben "
                "aufgenommen und ausgewertet) - stütze deine Antwort darauf und "
                "sag NICHT, du könntest den Bildschirm nicht sehen:\n\n"
                + str(lauf.result.output)
            )

        logger.warning("Das Bildschirm-Ansehen brachte nichts: %s", lauf.result.error)
        return (
            "HINWEIS: Ich habe versucht, den Bildschirm anzusehen, und es ging "
            "nicht: " + str(lauf.result.error or "kein Ergebnis") + " Sag das dem "
            "Benutzer geradeheraus."
        )

    async def _vorab_webseite(self, url: str) -> str:
        """Liest eine ausdrücklich genannte Seite - ohne das Modell zu fragen.

        Das Gegenstück zur erzwungenen Suche, nur für eine konkrete Adresse.
        Nennt der Benutzer eine Seite und will sie gelesen haben, holt der
        Orb sie selbst und legt den Text vor - statt zu hoffen, dass das
        Modell von sich aus 'webseite_lesen' ruft.
        """

        if self._tool_engine is None:
            return ""

        try:
            lauf = await self._tool_engine.direkt_ausfuehren(
                "webseite_lesen", {"url": url, "max_zeichen": 4000}
            )
        except Exception:  # noqa: BLE001 - das Lesen darf die Antwort nie verhindern.
            logger.exception("Das erzwungene Webseite-Lesen ist gescheitert.")
            return ""

        if lauf.result.ok and lauf.result.output:
            logger.info("Seite vorab gelesen: %s (%.1f s).", url, lauf.seconds)
            self._gelesenes_merken(str(lauf.result.output), quelle=url)
            return (
                "SO STEHT ES AUF DER SEITE, DIE DER BENUTZER GENANNT HAT "
                f"({url}, soeben geholt) - stütze deine Antwort darauf und sag "
                "NICHT, du könntest keine Webseiten öffnen:\n\n"
                + str(lauf.result.output)
            )

        logger.warning("Das Webseite-Lesen brachte nichts: %s", lauf.result.error)
        return (
            "HINWEIS: Ich habe versucht, " + url + " zu öffnen, und es ging "
            "nicht: " + str(lauf.result.error or "kein Ergebnis") + " Sag das "
            "dem Benutzer geradeheraus, statt etwas zu erfinden."
        )

    async def _vorab_browser(self, url: str) -> str:
        """Öffnet den Browser bei einer Adresse und zeigt, was anklickbar ist.

        Nur die beiden gefahrlosen Schritte werden vorweggenommen: das
        Fenster öffnen und die Elemente auflisten. Geklickt, getippt oder
        abgeschickt wird hier NICHTS - das bleibt dem Modell mit dem Werkzeug,
        weil es je nach Seite und Absicht anders ausfällt. Behoben ist damit
        die häufigste Klage: dass der Orb den Browser gar nicht erst öffnete.
        """

        if self._tool_engine is None:
            return ""

        try:
            auf = await self._tool_engine.direkt_ausfuehren(
                "browser_bedienen", {"aktion": "oeffnen", "ziel": url}
            )
        except Exception:  # noqa: BLE001 - das Öffnen darf die Antwort nie verhindern.
            logger.exception("Das erzwungene Browser-Öffnen ist gescheitert.")
            return ""

        if not (auf.result.ok and auf.result.output):
            logger.warning("Das Browser-Öffnen brachte nichts: %s", auf.result.error)
            return (
                "HINWEIS: Ich habe versucht, den Browser bei " + url + " zu "
                "öffnen, und es ging nicht: "
                + str(auf.result.error or "kein Ergebnis") + " Sag das dem "
                "Benutzer geradeheraus."
            )

        # Lief nur der Ausweichweg (Standardbrowser, weil die Steuerung
        # nicht eingerichtet ist)? Dann ist das Fenster offen, aber Klicken
        # und Tippen gehen nicht - das Modell soll das ehrlich sagen und
        # nicht so tun, als könnte es weitersteuern.
        if (getattr(auf.result, "context", {}) or {}).get("steuerung") is False:
            logger.info("Browser im Ausweichweg geöffnet: %s.", url)
            return (
                "DER BROWSER IST GEÖFFNET (bei " + url + ", im normalen "
                "Standardbrowser). Die STEUERUNG (klicken, tippen, mitlesen) "
                "ist noch nicht eingerichtet - dafür muss der Benutzer einmal "
                "'BROWSER-EINRICHTEN.bat' im AI-Orb-Ordner ausführen. Sag ihm "
                "genau das, kurz und freundlich."
            )

        teile = [str(auf.result.output)]
        # Die Elemente sind der zweite gefahrlose Schritt - mit ihnen kann das
        # Modell direkt weiter klicken/tippen, statt sie erst anzufordern.
        try:
            elemente = await self._tool_engine.direkt_ausfuehren(
                "browser_bedienen", {"aktion": "elemente"}
            )
            if elemente.result.ok and elemente.result.output:
                teile.append(str(elemente.result.output))
        except Exception:  # noqa: BLE001 - ohne die Liste geht es auch weiter.
            logger.info("Die Elemente ließen sich nach dem Öffnen nicht lesen.")

        logger.info("Browser vorab geöffnet: %s (%.1f s).", url, auf.seconds)
        return (
            "DER BROWSER IST BEREITS GEÖFFNET (bei " + url + ", vom Orb selbst). "
            "Sag NICHT, du könntest keinen Browser bedienen - du kannst es, das "
            "Fenster steht offen. Mach mit dem Werkzeug 'browser_bedienen' "
            "weiter: 'klicken'/'tippen' sprechen die Nummern unten an, "
            "'scrollen' blättert.\n\n" + "\n\n".join(teile)
        )

    #: Woran eine echte Frage nach NACHRICHTEN zu erkennen ist.
    #:
    #: Die Gegenüberstellung von sechs Nachrichtenhäusern ist das teuerste
    #: Werkzeug im Haus: sechs Suchläufe, und ihre Schlagzeilen füllen den
    #: Kontext. Das ist richtig bei "was ist heute in der Welt passiert" -
    #: und falsch bei jeder Frage, in der bloss ein Zeitwort vorkommt. Ein
    #: solches Wort genügt dafür nicht mehr; es muss um Berichterstattung
    #: gehen.
    _NACHRICHTEN_WOERTER: tuple[str, ...] = (
        "nachricht", "news", "schlagzeile", "meldung", "presse", "medien",
        "berichterstattung", "berichtet", "zeitung", "tagesschau",
        "weltlage", "krieg", "wahl", "konflikt", "politik", "was ist passiert",
        "was passiert in", "aus aller welt", "weltweit", "lage in",
    )

    def _will_nachrichten(self, text: str) -> bool:
        """Ob wirklich nach Nachrichten gefragt ist."""

        knapp = " " + " ".join(text.lower().split()) + " "
        return any(wort in knapp for wort in self._NACHRICHTEN_WOERTER)

    async def _vorab_mehrquellen(self, text: str) -> str:
        """Befragt mehrere Häuser parallel und stellt sie gegenüber."""

        if not bool(self._config.get("recherche.mehrquellen", True)):
            return ""
        # Nur bei einer echten Nachrichtenfrage. Sonst genügt die
        # gewöhnliche Suche - sie ist schneller und verstopft den Kontext
        # nicht mit Schlagzeilen, die zur Frage nicht gehören.
        if not self._will_nachrichten(text):
            return ""
        quellen = self._config.get("recherche.quellen", []) or []
        if not quellen:
            return ""

        from backend.tools.web_tools import (
            mehrquellensuche,
            quellen_gegenueberstellen,
        )

        from backend.tools.web_tools import suchbegriff_aus

        gesammelt = await mehrquellensuche(
            suchbegriff_aus(text),
            [dict(q) for q in quellen],
            je_quelle=int(self._config.get("recherche.treffer_je_quelle", 3) or 3),
            gleichzeitig=int(self._config.get("recherche.gleichzeitig", 4) or 4),
        )
        # Unter zwei Häusern gibt es nichts gegenüberzustellen - dann ist
        # die gewöhnliche Suche ehrlicher als eine "Gegenüberstellung"
        # mit einem einzigen Beteiligten.
        if len(gesammelt) < 2:
            return ""

        logger.info(
            "Mehrquellensuche zu %r: %s", text[:50], ", ".join(gesammelt)
        )
        return (
            "FRISCH GESUCHT, BEI MEHREREN HÄUSERN. Diese Treffer sind von "
            "jetzt und gehen deinem eigenen Wissensstand vor.\n\n"
            "Sie stehen absichtlich nach Herkunft getrennt. Sage in deiner "
            "Antwort, WORIN sich die Darstellungen unterscheiden - in der "
            "Wortwahl, in dem, was betont oder weggelassen wird, in den "
            "Zahlen. Wo alle dasselbe berichten, sag auch das: Es ist ein "
            "Befund und keine Selbstverständlichkeit. Nenne die Häuser "
            "beim Namen; ein 'Berichten zufolge' ist wertlos.\n\n"
            + quellen_gegenueberstellen(gesammelt)
        )

    # --- Kontextaufbereitung ---------------------------------------------------

    @staticmethod
    def _format_context(memory_context: dict[str, Any], extra: str | None) -> str:
        """Formt den Gedächtniskontext in einen kompakten Systemtext um.

        Unsichere Informationen bleiben dabei als solche gekennzeichnet
        (Reasoning-Context-Anforderung).
        """

        lines: list[str] = []

        memories = memory_context.get("memories") or []
        if memories:
            lines.append(
                "Bekanntes aus dem Gedächtnis (das hast DU in früheren "
                "Sitzungen mit dem Benutzer gelernt - deine eigene "
                "Erinnerung, sprich daraus):"
            )
            for entry in memories:
                marker = "" if entry.get("certainty") == "fakt" else f" [{entry.get('certainty')}]"
                lines.append(f"- {entry['content']}{marker}")

        facts = memory_context.get("user_facts") or []
        if facts:
            lines.append("Bekanntes über den Benutzer:")
            lines.extend(f"- {fact}" for fact in facts)

        tasks = memory_context.get("open_tasks") or []
        if tasks:
            lines.append("Offene Aufgaben:")
            lines.extend(f"- {task}" for task in tasks)

        conversations = memory_context.get("conversations") or []
        if conversations:
            lines.append("Frühere Gespräche (zusammengefasst):")
            lines.extend(f"- {entry['content']}" for entry in conversations)

        if extra:
            lines.append(extra)

        if not lines:
            return ""

        lines.append(
            "Nutze diese Angaben nur, wenn sie zur Frage passen. "
            "Erfinde nichts hinzu und kennzeichne Unsicherheiten."
        )
        return "\n".join(lines)

    async def _publish(self, event_name: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(event_name, payload)

    # --- Transparenz -------------------------------------------------------------

    def explain_last_decision(self) -> dict[str, Any]:
        """Erklärt die zuletzt getroffene Weiterleitungsentscheidung.

        Beantwortet die Transparenzfragen "Warum hast du so entschieden?"
        und "Welche Strategie hast du gewählt?" mit nachvollziehbaren Daten,
        ohne interne Gedankengänge offenzulegen.
        """

        if not self._last_decision:
            return {"available": False, "message": "Es liegt noch keine Entscheidung vor."}

        intent = self._last_decision["intent"]
        route = self._last_decision["route"]
        return {
            "available": True,
            "erkannte_absicht": intent["intent"],
            "sicherheit": intent["confidence"],
            "ausschlaggebende_begriffe": intent["matched_keywords"],
            "bearbeitet_durch": route["module"] or "Sprachmodell",
            "sprachmodell_genutzt": not route["handled_locally"] or route["requires_llm"],
            "aktiver_provider": self._providers.active_name,
        }

    #: So viel von einer Antwort wandert ins Gedaechtnis.
    #:
    #: Genug, damit die Aussage darin steht; kurz genug, dass hundert
    #: Wortwechsel das Gedaechtnis nicht zumauern. Wer mehr braucht,
    #: fragt noch einmal - dann sucht der Orb neu.
    _ANTWORT_IM_GEDAECHTNIS = 700

    def _wortwechsel_merken(
        self, frage: str, antwort: str, project_id: str | None
    ) -> None:
        """Legt Frage UND Antwort ins Gedächtnis - nicht nur die Frage.

        Hier stand bisher ``remember(text)``: gespeichert wurde allein,
        was der Benutzer GEFRAGT hat. Im Gedächtnis des Benutzers sah das
        am 19.08.2026 so aus::

            "du hast zuletzt ein dokument über fossilien und gestein
             eingelesen dabei gab es offene fragen was sind diese offenen
             fragen"

        Das ist die Frage. Die Antwort darauf - das, worum es ging - stand
        nirgends. Deshalb konnte der Orb sich an behandelte Themen nicht
        erinnern: Er hatte hundertdreissig alte Fragen gespeichert und
        keine einzige Auskunft.

        Gespeichert wird beides zusammen, denn getrennt taugt keines von
        beiden: Eine Antwort ohne ihre Frage ist beim Wiederfinden nicht
        einzuordnen, eine Frage ohne Antwort ist leer.
        """

        frage_knapp = " ".join(str(frage or "").split())
        antwort_knapp = " ".join(str(antwort or "").split())
        if not frage_knapp or not antwort_knapp:
            return

        if len(antwort_knapp) > self._ANTWORT_IM_GEDAECHTNIS:
            gekuerzt = antwort_knapp[: self._ANTWORT_IM_GEDAECHTNIS]
            # An der letzten Satzgrenze abschneiden, nicht mitten im Wort.
            schnitt = max(gekuerzt.rfind(". "), gekuerzt.rfind("! "), gekuerzt.rfind("? "))
            antwort_knapp = (
                gekuerzt[: schnitt + 1] if schnitt > 200 else gekuerzt.rstrip() + " …"
            )

        with contextlib.suppress(Exception):
            self._memory.remember(
                f"Gefragt: {frage_knapp}\nGeantwortet: {antwort_knapp}",
                kind="knowledge",
                project_id=project_id,
                source="gespräch",
            )

    #: So viel eines gelesenen Textes wandert ins Gedächtnis.
    _GELESENES_IM_GEDAECHTNIS = 1500

    def _gelesenes_merken(self, inhalt: str, *, quelle: str) -> None:
        """Behält, was gelesen wurde - mit Angabe, woher.

        „Er speichert eingelesene Dokumente nicht in seinem Gedächtnis ab":
        Das stimmte. Was ``webseite_lesen`` oder ``datei_lesen`` holte,
        ging in den Kontext DIESER einen Antwort und war danach weg. Beim
        nächsten Start wusste der Orb nichts mehr davon - und auf die
        Frage „was stand in dem Dokument" musste er raten.

        Gespeichert wird ein Auszug, nicht das ganze Dokument: Das
        Gedächtnis ist zum Wiederfinden da, nicht zum Archivieren. Steht
        die Quelle dabei, kann der Orb bei Bedarf noch einmal nachlesen -
        und das ist mehr wert als der vollständige Text von damals, denn
        Seiten ändern sich.
        """

        knapp = " ".join(str(inhalt or "").split())
        if len(knapp) < 200:
            return
        if len(knapp) > self._GELESENES_IM_GEDAECHTNIS:
            knapp = knapp[: self._GELESENES_IM_GEDAECHTNIS].rsplit(" ", 1)[0] + " …"

        with contextlib.suppress(Exception):
            self._memory.remember(
                f"Gelesen aus {quelle}:\n{knapp}",
                kind="knowledge",
                source=quelle,
                # force: Die Relevanzpruefung ist fuer Gespraechsfetzen
                # gedacht. Was der Benutzer ausdruecklich lesen liess, ist
                # per se relevant - er hat darum gebeten.
                force=True,
            )
            logger.info("Gelesenes im Gedächtnis abgelegt (Quelle: %s).", quelle)

    async def end_conversation(self) -> str | None:
        """Beendet die laufende Unterhaltung und sichert deren Zusammenfassung."""

        summary = await self.conversations.finish()
        await self._providers.end_conversation()
        return summary

    def status(self) -> dict[str, Any]:
        """Statusübersicht des Orchestrators."""

        uebersicht: dict[str, Any] = {
            "conversation": self.conversations.status(),
            "providers": self._providers.status(),
            "known_intents": self.classifier.intents,
        }
        # Der Beleg, dass live UND Schatten gelaufen sind, gehoert dorthin,
        # wo man ihn im Betrieb auch nachsieht.
        if self._schatten is not None:
            uebersicht["schattenlauf"] = self._schatten.status()
        return uebersicht
