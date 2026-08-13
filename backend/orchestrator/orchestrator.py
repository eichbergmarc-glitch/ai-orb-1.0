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
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.events.event_bus import EventBus
from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.conversation_manager import ConversationManager
from backend.orchestrator.intent_classifier import IntentClassifier, IntentResult
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import ProviderError
from backend.orchestrator.speech_stream import SpeechStream, remaining_after
from backend.orchestrator.task_router import RouteResult, TaskRouter
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

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
    words = {word.strip(".,!?;:") for word in normalized.split()}
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
    action = any(
        marker in normalized
        for marker in (
            "schalt", "wechsel", "wechsle", "aktivier", "geh ", "gehe ",
            "arbeite", "nutze", "benutze", "verwende", "stell ", "stelle ",
        )
    )
    disable_offline = offline_target and any(
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
    if (offline_target or online_target) and any(
        marker in normalized
        for marker in ("bist du", "sind wir", "ist der", "welcher modus", "status")
    ):
        return "status"
    return ""


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
    if any(f" {wort}" in knapp for wort in _SUCHAUFTRAEGE):
        return True
    # "Wie geht es dir heute?" und "Was machst du gerade?" fragen nach
    # dem Orb, nicht nach dem Weltgeschehen. Zuvor starteten sie sechs
    # Nachrichtensuchen und lieferten anschließend fremde Webseiten.
    if any(wendung in knapp for wendung in _PERSOENLICHE_JETZT_FRAGEN):
        return False
    return any(wort in knapp for wort in _JETZT_WOERTER)


#: Ausdrueckliche Woerter fuer "mach ein Bild vom Bildschirm". Sie loesen
#: allein aus.
_BILDSCHIRM_DIREKT: tuple[str, ...] = (
    "screenshot", "screen shot", "printscreen", "print screen",
    "bildschirmfoto", "bildschirm-foto", "bildschirmaufnahme",
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
        #: Die Werkzeugschleife. Wird nach dem Aufbau angeschlossen (siehe
        #: attach_tool_engine) – zur Bauzeit des Orchestrators gibt es sie
        #: noch nicht.
        self._tool_engine: Any | None = None
        #: Die Ablaufmaschine. Wird nachgereicht wie die Werkzeugschleife –
        #: zur Bauzeit des Orchestrators gibt es sie noch nicht.
        self._workflows: Any | None = None

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

    async def handle(
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
        self._providers.begin_conversation()

        if project_id is not None:
            self.conversations.set_project(project_id)

        # Der Wechsel in den Offlinebetrieb muss VOR Intent-Erkennung und
        # erst recht vor jeder Modellanfrage geschehen. So verlaesst selbst
        # der Umschaltbefehl den Rechner nicht und funktioniert auch dann,
        # wenn gerade kein Cloud-Provider erreichbar ist.
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

        intent = self.classifier.classify(text)
        await self._publish("ai.intent.classified", intent.to_dict())

        # Löst der Satz einen hinterlegten Ablauf aus?
        #
        # Das war der Sinn der Auslöser von Anfang an, nur fragte sie nie
        # jemand ab: Abläufe liessen sich ausschliesslich über ihre Kennung
        # starten – also über die Oberfläche, nie im Gespräch. Ein Ablauf,
        # den man nur mit seiner Nummer aufrufen kann, ist keine
        # Automatisierung, sondern ein Menüpunkt.
        ablauf = await self._ablauf_versuchen(text)
        if ablauf is not None:
            ablauf.duration_seconds = time.perf_counter() - started
            await self._publish("ai.response", ablauf.to_dict())
            return ablauf

        route = await self.router.route(text, intent)

        self._last_decision = {
            "text": text,
            "intent": intent.to_dict(),
            "route": route.to_dict(),
            "at": time.time(),
        }

        if route.handled_locally and not route.requires_llm:
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

        result = await self._answer_with_model(
            text,
            intent=intent,
            route=route,
            project_id=project_id,
            extra_context=extra_context,
            spoken=spoken,
            on_speech=on_speech,
        )
        result.duration_seconds = time.perf_counter() - started
        await self._publish("ai.response", result.to_dict())
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

        self.conversations.add_user_message(text)
        await self.conversations.maybe_compress()

        memory_context = self._memory.context_for(text, project_id=project_id)
        context_block = self._format_context(memory_context, extra_context)

        # Gesprochene Antworten kurz halten – gemessen der grösste Hebel
        # gegen lange Wartezeiten.
        if spoken:
            context_block = "\n\n".join(
                part for part in (context_block, self.SPOKEN_BREVITY) if part
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
        # Browser-Befehle sind KEINE Suchanfragen: "öffne ein Browserfenster
        # und führe eine Suche durch" löste vorher acht Suchläufe mit dem
        # wörtlichen Befehlssatz aus - alle leer, und für den Benutzer sah
        # das aus wie "die Suche ist kaputt".
        if tools_available and braucht_aktuelles(text) and not ist_browser_befehl(text):
            frisch = await self._vorab_suchen(text)
            if frisch:
                context_block = "\n\n".join(
                    part for part in (context_block, frisch) if part
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
        if tools_available and self._ist_fachfrage(text, extra_context):
            eigenes = await self._vorab_eigene_quellen(text)
            if eigenes:
                context_block = "\n\n".join(
                    part for part in (context_block, eigenes) if part
                )
        if tools_available:
            instructions = self._tool_engine.system_instructions()
            context_block = "\n\n".join(
                part for part in (context_block, instructions) if part
            )

        messages = self.conversations.build_messages(extra_context=context_block)

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

        try:
            if on_speech is not None:

                async def _sprich(satz: str) -> bool:
                    nonlocal wirklich_gesprochen
                    gehoert = bool(await on_speech(satz))
                    wirklich_gesprochen = wirklich_gesprochen or gehoert
                    return gehoert

                response, strom = await self._stream_and_speak(messages, _sprich)
            else:
                response = await self._providers.chat(messages)
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

        answer_text = response.text
        tool_runs = 0
        if tools_available:
            # Enthält die Antwort Werkzeugaufrufe, hier ausführen – mit
            # Sicherheitsprüfung und Prüfprotokoll, im selben Gespräch.
            answer_text, runs = await self._tool_engine.continue_with_tools(
                messages, response.text, actor="gespraech"
            )
            tool_runs = len(runs)

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

        # Relevante Informationen aus der Benutzereingabe merken.
        self._memory.remember(
            text,
            kind="knowledge",
            project_id=project_id,
            source="gespräch",
        )

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
                # Sagt der Sprachschicht: Diese Antwort war wirklich zu
                # hören. Ohne diesen Vermerk käme sie ein zweites Mal – mit
                # einem falschen gar nicht.
                "gesprochen": wirklich_gesprochen,
            },
        )

    async def _stream_and_speak(
        self,
        messages: list[Any],
        on_speech: Callable[[str], Awaitable[bool]],
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
            async for stueck in self._providers.chat_stream(messages):
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
        if looks_academic(text):
            return True
        # Der Professor baut den Systemprompt, wenn er übernimmt. Steht er
        # im Zusatzkontext, hat er sich für zuständig erklärt.
        return bool(extra_context) and "Geschichtsprofessor" in str(extra_context)

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
        if ist_wiederholung and self._letzter_suchbegriff:
            begriff = self._letzter_suchbegriff
            such_text = begriff
            logger.info("Suche wiederholt mit dem letzten Begriff: %r", begriff)
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

    async def _vorab_mehrquellen(self, text: str) -> str:
        """Befragt mehrere Häuser parallel und stellt sie gegenüber."""

        if not bool(self._config.get("recherche.mehrquellen", True)):
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

    async def end_conversation(self) -> str | None:
        """Beendet die laufende Unterhaltung und sichert deren Zusammenfassung."""

        summary = await self.conversations.finish()
        await self._providers.end_conversation()
        return summary

    def status(self) -> dict[str, Any]:
        """Statusübersicht des Orchestrators."""

        return {
            "conversation": self.conversations.status(),
            "providers": self._providers.status(),
            "known_intents": self.classifier.intents,
        }
