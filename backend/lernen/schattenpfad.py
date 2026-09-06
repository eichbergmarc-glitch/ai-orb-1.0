"""Der Schattenlauf im echten Betrieb - mitrechnen, ohne mitzureden.

Bis hierher war der Schattenlauf ein Buch ohne Schreiber: ``Schattenbuch``
konnte Lehren aufnehmen, aber niemand erzeugte welche, weil der lebende
Pfad ihn nie aufrief. Diese Datei schliesst ihn an - und zwar so, dass er
die Antwort des Benutzers unter keinen Umständen berühren kann.

Wie die Trennung erzwungen wird

* **Danach, nicht dazwischen.** Der Wächter wird erst gerufen, wenn die
  Antwort fertig ist. Er bekommt sie als Text; er kann sie nicht ändern,
  weil er sie nicht zurückgibt.
* **Eigene Aufgabe.** Der Lauf ist eine abgesetzte asyncio-Aufgabe. Der
  Zug des Benutzers wartet nicht auf ihn und endet unabhängig davon.
* **Zeitgrenze.** Wer zu lange rechnet, wird abgebrochen. Ein langsames
  lokales Modell darf keine Aufgaben anhäufen.
* **Nichts dringt nach aussen.** Der ganze Lauf steht in einem
  ``try``-Block, der alles ausser dem Abbruch schluckt. Ein Fehler im
  Schatten ist ein Zählerstand, kein Vorfall.
* **Aus, wenn nicht ausdrücklich an.** ``lernen.schattenlauf_aktiv`` ist
  standardmässig ``false``, dazu eine Obergrenze je Stunde.

Was gespeichert wird, entscheidet ``schattenlauf.Schattenbuch``: eine
Fehlerklasse, die Werkzeugentscheidung, ein Aufgabenmuster. Der Wortlaut
der Anfrage wird hier gar nicht erst weitergereicht - ``aufgabenmuster``
beschreibt die Anfrage nur der Form nach (Länge, Wortzahl, Satzart) und
enthält kein einziges Wort daraus.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from backend.config import get_config
from backend.lernen.schattenlauf import Lehre, Schattenbuch, fehlerklasse_bestimmen
from backend.system.logging_setup import get_logger
from backend.system.performance_trace import current_turn_trace

logger = get_logger(__name__)


def aufgabenmuster_bilden(text: str) -> str:
    """Beschreibt eine Anfrage der Form nach - ohne ein Wort daraus.

    Ein Muster wie ``"frage, 9 woerter, 54 zeichen"`` genügt, um Fälle zu
    gruppieren, und verrät nichts. Der Wortlaut bleibt im Gespräch, wo er
    hingehört.
    """

    schlank = " ".join(str(text or "").split())
    if not schlank:
        return "leer"
    woerter = len(schlank.split())
    art = "frage" if schlank.rstrip().endswith("?") else "aussage"
    return f"{art}, {woerter} woerter, {len(schlank)} zeichen"


class Schattenwaechter:
    """Lässt den Schüler dieselbe Anfrage rechnen - im Hintergrund.

    Der Wächter ist bewusst dumm gehalten: Er kennt weder Rubriken noch
    Bewerter. Was er vergleichen kann, ist die Werkzeugentscheidung - und
    genau die ist die häufigste Bruchstelle des lokalen Modells. Alles
    Weitere gehört in den Messlauf, wo es Prüfstücke mit Erwartungen gibt.
    """

    def __init__(
        self,
        *,
        provider_manager: Any,
        buch: Schattenbuch | None = None,
        event_bus: Any | None = None,
    ) -> None:
        konfig = get_config()
        self._providers = provider_manager
        self._buch = buch or Schattenbuch()
        self._event_bus = event_bus
        self._modell = str(konfig.get("lernen.schattenlauf_modell", "") or "")
        self._zeitgrenze = float(
            konfig.get("lernen.schattenlauf_zeitgrenze_sekunden", 20.0) or 20.0
        )
        #: Die laufenden Aufgaben festhalten, damit sie nicht vorzeitig
        #: eingesammelt werden - sonst verschwindet ein Lauf spurlos.
        self._laufend: set[asyncio.Task[None]] = set()
        self._zaehler: dict[str, int] = {
            "gestartet": 0,
            "abgelehnt": 0,
            "fertig": 0,
            "abgelaufen": 0,
            "gescheitert": 0,
            "eingetragen": 0,
        }

    @property
    def aktiv(self) -> bool:
        return self._buch.aktiv

    def zaehler(self) -> dict[str, int]:
        """Die Betriebszahlen - Beleg dafür, dass beides lief."""

        return dict(self._zaehler)

    def status(self) -> dict[str, Any]:
        return {
            "aktiv": self.aktiv,
            "modell": self._modell or "voreingestellt",
            "zeitgrenze_sekunden": self._zeitgrenze,
            "laufend": len(self._laufend),
            **self._zaehler,
        }

    # --- Der Anschluss an den lebenden Pfad --------------------------------

    def starten(
        self,
        *,
        text: str,
        live_antwort: str,
        kategorie: str = "",
        werkzeuge_live: list[str] | None = None,
    ) -> asyncio.Task[None] | None:
        """Setzt einen Schattenlauf ab. Gibt sofort zurück.

        Returns:
            Die abgesetzte Aufgabe, oder ``None``, wenn nicht gelaufen
            wird (aus, Grenze erreicht, keine Schleife). Der Aufrufer
            braucht den Rückgabewert nicht - er ist für Tests da.
        """

        if not str(text or "").strip() or not str(live_antwort or "").strip():
            return None
        if not self._buch.darf_laufen():
            self._zaehler["abgelehnt"] += 1
            return None

        spur = current_turn_trace()
        kennung = getattr(spur, "turn_id", "") if spur else ""

        try:
            aufgabe = asyncio.get_running_loop().create_task(
                self._laufen(
                    text=text,
                    live_antwort=live_antwort,
                    kategorie=kategorie,
                    werkzeuge_live=list(werkzeuge_live or []),
                    kennung=str(kennung or ""),
                )
            )
        except RuntimeError:
            # Kein laufender Loop: dann eben kein Schattenlauf. Das ist
            # kein Fehler des Benutzerzuges.
            self._zaehler["abgelehnt"] += 1
            return None

        self._zaehler["gestartet"] += 1
        self._laufend.add(aufgabe)
        aufgabe.add_done_callback(self._laufend.discard)
        return aufgabe

    async def _laufen(
        self,
        *,
        text: str,
        live_antwort: str,
        kategorie: str,
        werkzeuge_live: list[str],
        kennung: str,
    ) -> None:
        """Der eigentliche Lauf - eingehegt gegen alles ausser Abbruch."""

        begonnen = time.perf_counter()
        try:
            antwort, werkzeuge = await asyncio.wait_for(
                self._schueler_fragen(text), timeout=self._zeitgrenze
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            self._zaehler["abgelaufen"] += 1
            logger.info(
                "Schattenlauf abgebrochen nach %.1f s (Zug %s).",
                self._zeitgrenze,
                kennung or "ohne Kennung",
            )
            return
        except Exception as fehler:  # noqa: BLE001 - der Schatten darf nichts reissen.
            self._zaehler["gescheitert"] += 1
            logger.info(
                "Schattenlauf gescheitert (%s: %s, Zug %s).",
                type(fehler).__name__,
                fehler,
                kennung or "ohne Kennung",
            )
            return

        self._zaehler["fertig"] += 1
        dauer = time.perf_counter() - begonnen

        klasse = fehlerklasse_bestimmen(
            verlangte_werkzeuge=werkzeuge_live,
            schueler_werkzeuge=werkzeuge,
            schueler_aufruf_ungueltig=False,
            # Ohne Pruefstueck gibt es keine Punkte. Der Vergleich beschraenkt
            # sich hier ehrlich auf die Werkzeugentscheidung; alles Fachliche
            # gehoert in den Messlauf.
            schueler_punkte=0.0,
            lehrer_punkte=0.0,
            schueler_halluzination=False,
        )

        try:
            self._buch.eintragen(
                Lehre(
                    kategorie=kategorie or "unbestimmt",
                    fehlerklasse=klasse,
                    werkzeugentscheidung=(
                        f"live: {', '.join(werkzeuge_live) or 'keine'}; "
                        f"schatten: {', '.join(werkzeuge) or 'keine'}"
                    ),
                    verbesserungsvorschlag=_vorschlag(klasse),
                    aufgabenmuster=aufgabenmuster_bilden(text),
                )
            )
        except Exception:  # noqa: BLE001
            self._zaehler["gescheitert"] += 1
            logger.debug("Eine Lehre liess sich nicht ablegen.", exc_info=True)
            return

        self._zaehler["eingetragen"] += 1
        logger.info(
            "Schattenlauf zu Zug %s: %s in %.1f s (live %d Zeichen, Schatten %d).",
            kennung or "ohne Kennung",
            klasse,
            dauer,
            len(live_antwort),
            len(antwort),
        )

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    "lernen.schattenlauf",
                    {
                        "zug": kennung,
                        "kategorie": kategorie or "unbestimmt",
                        "fehlerklasse": klasse,
                        "sekunden": round(dauer, 3),
                    },
                )
            except Exception:  # noqa: BLE001
                logger.debug("Die Schattenmeldung ging nicht raus.", exc_info=True)

    async def _schueler_fragen(self, text: str) -> tuple[str, list[str]]:
        """Fragt das lokale Modell - ohne Werkzeuge, ohne Nebenwirkung.

        Bewusst ohne Werkzeugschleife: Ein Schattenlauf, der Dateien
        anlegt, Termine schreibt oder im Netz sucht, wäre kein Schatten
        mehr. Gemessen wird deshalb, ob der Schüler ein Werkzeug
        VERLANGEN würde - der Aufruf selbst bleibt aus.
        """

        from backend.orchestrator.providers.base_provider import ChatMessage

        ergebnis = await self._providers.chat(
            [ChatMessage(role="user", content=text)],
            preferred=self._modell or None,
        )
        antwort = str(getattr(ergebnis, "text", "") or "")
        werkzeuge = _werkzeugwuensche(antwort)
        return antwort, werkzeuge


def _werkzeugwuensche(antwort: str) -> list[str]:
    """Liest aus einer Antwort, welche Werkzeuge sie aufrufen wollte."""

    try:
        from backend.tools.tool_engine import parse_tool_calls

        return [str(aufruf.tool) for aufruf in parse_tool_calls(antwort)]
    except Exception:  # noqa: BLE001 - eine unlesbare Antwort ist kein Vorfall.
        return []


def _vorschlag(klasse: str) -> str:
    """Ein Satz je Fehlerklasse - abstrakt, ohne Bezug zum Einzelfall."""

    return {
        "werkzeug_nicht_aufgerufen": (
            "Dem Schueler fehlt der Anlass, ein Werkzeug zu verlangen; "
            "Werkzeugbeschreibungen schaerfen."
        ),
        "falsches_werkzeug": (
            "Der Schueler waehlt ein anderes Werkzeug als der Lehrer; "
            "Abgrenzung der Werkzeuge in der Beschreibung praezisieren."
        ),
        "werkzeugaufruf_ungueltig": (
            "Der Schueler ruft formal falsch auf; Beispielaufruf im "
            "Systemtext ergaenzen."
        ),
        "kein_unterschied": "Keine Abweichung in der Werkzeugentscheidung.",
    }.get(klasse, "Abweichung vermerkt; Einordnung braucht einen Messlauf.")


__all__ = ["Schattenwaechter", "aufgabenmuster_bilden"]
