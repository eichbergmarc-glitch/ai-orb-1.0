"""Robuste Antwortpipeline (Phase 17).

Die Vorgabe ist unmissverständlich: *„Der Orb darf niemals einfach
‚undefined', leer oder stumm zurückgeben."* Dieses Modul setzt das durch.

Jede Anfrage bekommt eine Kennung, ein Zeitlimit und eine Prüfung ihres
Ergebnisses. Fällt eine Stufe aus, greift die nächste – und wenn alle
ausfallen, kommt trotzdem ein verständlicher Satz zurück statt eines
leeren Feldes.

Was als **ungültige Antwort** gilt, ist dabei weiter gefasst, als man
zunächst denkt. Nicht nur eine leere Zeichenkette: Auch „undefined", „null",
eine reine Fehlermeldung des Anbieters oder ein Text, der nur aus
Sonderzeichen besteht, wird abgewiesen und der Rückfall angestoßen. Solche
Antworten kommen in der Praxis häufiger vor als echte Netzwerkfehler, und
sie sind unangenehmer, weil sie wie eine Antwort aussehen.

Die Kennung jeder Anfrage steht in jeder Protokollzeile dazu. Wer einen
Fehler nachvollziehen will, findet damit alle zusammengehörigen Zeilen –
auch wenn parallel mehrere Anfragen laufen.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.config import get_config
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Antworten, die wie eine Antwort aussehen, aber keine sind.
INVALID_ANSWERS: frozenset[str] = frozenset(
    {
        "",
        "undefined",
        "null",
        "none",
        "nan",
        "n/a",
        "[object object]",
        "{}",
        "[]",
        "error",
        "fehler",
    }
)

#: Ein Text, der nur hieraus besteht, ist keine Antwort.
_ONLY_PUNCTUATION = re.compile(r"^[\s\W_]+$", re.UNICODE)


@dataclass
class Attempt:
    """Ein einzelner Versuch."""

    stage: str
    ok: bool
    seconds: float
    error: str = ""
    characters: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "ok": self.ok,
            "seconds": round(self.seconds, 3),
            "error": self.error,
            "characters": self.characters,
        }


@dataclass
class PipelineResult:
    """Das Ergebnis einer Anfrage durch die Pipeline."""

    request_id: str
    answer: str
    #: Welche Stufe geantwortet hat.
    stage: str = ""
    ok: bool = True
    attempts: list[Attempt] = field(default_factory=list)
    seconds: float = 0.0
    #: Warum es nicht die erste Stufe war.
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "answer": self.answer,
            "stage": self.stage,
            "ok": self.ok,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "seconds": round(self.seconds, 3),
            "fallback_reason": self.fallback_reason,
        }


def is_valid_answer(text: Any, *, minimum_characters: int = 1) -> tuple[bool, str]:
    """Prüft, ob etwas als Antwort durchgeht.

    Returns:
        Die Entscheidung und, bei Ablehnung, der Grund im Klartext.
    """

    if text is None:
        return False, "Die Antwort war leer."

    if not isinstance(text, str):
        return False, f"Die Antwort war kein Text, sondern {type(text).__name__}."

    stripped = text.strip()

    if not stripped:
        return False, "Die Antwort war leer."

    if stripped.lower() in INVALID_ANSWERS:
        return False, f"Die Antwort war ein Platzhalter: '{stripped[:40]}'."

    if _ONLY_PUNCTUATION.match(stripped):
        return False, "Die Antwort enthielt keinen lesbaren Text."

    if len(stripped) < minimum_characters:
        return False, (
            f"Die Antwort war mit {len(stripped)} Zeichen zu kurz "
            f"(mindestens {minimum_characters})."
        )

    return True, ""


class ResponsePipeline:
    """Führt eine Anfrage über mehrere Stufen und gibt immer etwas zurück."""

    def __init__(self) -> None:
        config = get_config()

        self._timeout = float(config.get("pipeline.timeout_seconds", 180))
        self._minimum_characters = int(config.get("pipeline.minimum_answer_characters", 1))
        self._retries = int(config.get("pipeline.retries_per_stage", 1))
        self._last_resort = str(
            config.get(
                "pipeline.last_resort_message",
                "Ich kann gerade nicht antworten. Das Sprachmodell ist nicht "
                "erreichbar – prüfe die Internetverbindung oder starte AI-Orb neu. "
                "Die Einzelheiten stehen im Protokoll.",
            )
        )

        self._total = 0
        self._failed = 0
        self._fallbacks = 0

    async def run(
        self,
        stages: list[tuple[str, Callable[[], Awaitable[Any]]]],
        *,
        request_id: str = "",
        timeout: float = 0.0,
    ) -> PipelineResult:
        """Führt die Stufen der Reihe nach aus, bis eine gültig antwortet.

        Args:
            stages: Paare aus Stufenname und der auszuführenden Funktion.
                Die Reihenfolge ist die Rückfallreihenfolge.
            request_id: Eine Kennung; wird sonst erzeugt.
            timeout: Zeitlimit je Stufe. 0 nimmt die Konfiguration.

        Returns:
            Immer ein Ergebnis. Bei vollständigem Ausfall enthält es die
            Erklärung aus der Konfiguration – niemals nichts.
        """

        identifier = request_id or uuid.uuid4().hex[:10]
        limit = timeout or self._timeout
        started = time.perf_counter()

        result = PipelineResult(request_id=identifier, answer="", ok=False)
        self._total += 1

        for index, (name, action) in enumerate(stages):
            for attempt_number in range(1, max(1, self._retries) + 1):
                attempt_started = time.perf_counter()

                try:
                    raw = await asyncio.wait_for(action(), timeout=limit)
                except asyncio.TimeoutError:
                    elapsed = time.perf_counter() - attempt_started
                    message = f"Zeitlimit von {limit:.0f} Sekunden überschritten."
                    result.attempts.append(Attempt(name, False, elapsed, message))
                    logger.warning("[%s] Stufe '%s': %s", identifier, name, message)
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 - kein unbehandelter Fehler.
                    elapsed = time.perf_counter() - attempt_started
                    message = f"{type(error).__name__}: {error}"
                    result.attempts.append(Attempt(name, False, elapsed, message))
                    logger.warning("[%s] Stufe '%s' fehlgeschlagen: %s", identifier, name, message)
                    continue

                text = self._extract(raw)
                valid, reason = is_valid_answer(text, minimum_characters=self._minimum_characters)
                elapsed = time.perf_counter() - attempt_started

                if valid:
                    result.attempts.append(Attempt(name, True, elapsed, characters=len(text)))
                    result.answer = text.strip()
                    result.stage = name
                    result.ok = True
                    result.seconds = time.perf_counter() - started

                    if index > 0:
                        self._fallbacks += 1
                        result.fallback_reason = self._describe_fallback(result.attempts)
                        logger.info(
                            "[%s] Über Rückfallstufe '%s' beantwortet. %s",
                            identifier,
                            name,
                            result.fallback_reason,
                        )
                    else:
                        logger.debug(
                            "[%s] Beantwortet über '%s' in %.2f s.", identifier, name, elapsed
                        )

                    return result

                result.attempts.append(Attempt(name, False, elapsed, reason, len(str(text))))
                logger.warning("[%s] Stufe '%s': %s", identifier, name, reason)

                if attempt_number < self._retries:
                    # Kurz warten, statt sofort erneut zu drücken – bei einer
                    # Überlastung hilft ein zweiter Versuch in derselben
                    # Millisekunde nicht.
                    await asyncio.sleep(0.5 * attempt_number)

        # Alle Stufen ausgefallen.
        #
        # Der vorformulierte Satz nennt die Internetverbindung als mögliche
        # Ursache. Das ist eine Vermutung, keine Messung – und sie führt in
        # die Irre, wenn das Internet in Ordnung ist und etwas anderes
        # klemmt. Deshalb kommt der tatsächlich aufgetretene Fehler mit
        # dazu, sofern es einen gibt.
        self._failed += 1
        result.answer = self._compose_failure_message(result.attempts)
        result.stage = "notfall"
        result.ok = False
        result.seconds = time.perf_counter() - started
        result.fallback_reason = self._describe_fallback(result.attempts)

        logger.error(
            "[%s] Alle %d Stufen ausgefallen. %s",
            identifier,
            len(stages),
            result.fallback_reason,
        )
        return result

    def _compose_failure_message(self, attempts: list[Attempt]) -> str:
        """Setzt die Meldung für den Fall zusammen, dass nichts geklappt hat.

        Der Benutzer soll nicht raten müssen. „Prüfe die
        Internetverbindung" ist ein Rat ins Blaue; die Meldung des letzten
        Versuchs ist eine Auskunft.
        """

        failures = [attempt for attempt in attempts if not attempt.ok and attempt.error]
        if not failures:
            return self._last_resort

        last = failures[-1]
        detail = last.error.strip()

        # Sehr lange Ausgaben abschneiden. Eine Antwort, die den halben
        # Bildschirm füllt, wird nicht gelesen.
        if len(detail) > 300:
            detail = detail[:297] + "..."

        return (
            "Ich kann gerade nicht antworten. Der letzte Versuch über "
            f"'{last.stage}' scheiterte:\n\n{detail}\n\n"
            "Mehr steht im Protokoll."
        )

    @staticmethod
    def _extract(raw: Any) -> str:
        """Holt den Text aus dem, was eine Stufe zurückgibt.

        Die Stufen liefern je nach Herkunft Text, ein Objekt mit ``text``
        oder ein Verzeichnis. Das hier zu vereinheitlichen erspart jeder
        aufrufenden Stelle dieselbe Fallunterscheidung.
        """

        if isinstance(raw, str):
            return raw

        for attribute in ("response", "text", "content", "answer"):
            value = getattr(raw, attribute, None)
            if isinstance(value, str):
                return value

        if isinstance(raw, dict):
            for key in ("response", "text", "content", "answer"):
                value = raw.get(key)
                if isinstance(value, str):
                    return value

        return "" if raw is None else str(raw)

    @staticmethod
    def _describe_fallback(attempts: list[Attempt]) -> str:
        """Fasst zusammen, woran die vorherigen Stufen scheiterten."""

        failures = [attempt for attempt in attempts if not attempt.ok]
        if not failures:
            return ""
        return "Zuvor gescheitert: " + "; ".join(
            f"{attempt.stage} ({attempt.error})" for attempt in failures[:4]
        )

    def new_request_id(self) -> str:
        """Erzeugt eine Anfragekennung."""

        return uuid.uuid4().hex[:10]

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "total_requests": self._total,
            "failed_completely": self._failed,
            "answered_via_fallback": self._fallbacks,
            "success_rate": (
                round((self._total - self._failed) / self._total, 3) if self._total else 1.0
            ),
            "timeout_seconds": self._timeout,
            "retries_per_stage": self._retries,
        }
