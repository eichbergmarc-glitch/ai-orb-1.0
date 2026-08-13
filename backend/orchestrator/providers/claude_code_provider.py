"""Claude-Provider über die lokal installierte Claude-Code-Befehlszeile.

Dieser Provider nutzt **dein Claude-Abonnement** (Pro oder Max) statt eines
kostenpflichtigen API-Schlüssels. Möglich ist das, weil die Claude-Code-
Befehlszeile sich mit deinem Konto anmeldet und im sogenannten
Print-Modus (``claude -p``) einzelne Anfragen beantworten kann, ohne dass
eine interaktive Sitzung nötig wäre.

Voraussetzungen:

1. Claude Code ist auf dem Rechner installiert.
2. Du hast dich einmalig mit ``claude`` angemeldet (Abo-Anmeldung, nicht
   API-Schlüssel).

AI-Orb ruft die Befehlszeile asynchron in einem eigenen Prozess auf; die
Oberfläche wird dadurch nie blockiert. Es werden keine Daten an andere
Dienste übertragen als an Anthropic – und das nur für die eigentliche
Anfrage.

Zur Antwortzeit: Die Befehlszeile wird nicht mehr für jede Frage neu
gestartet. Ein Prozess steht schon vor der ersten Frage bereit und trägt
das ganze Gespräch; geschickt wird nur, was neu hinzugekommen ist. Das
spart zweierlei – den Start (unter Windows mehrere Sekunden, und zwar
jedes Mal) und das erneute Durchdenken des bisherigen Verlaufs. Gemessen
kam das erste Wort danach nach etwa einer Sekunde statt nach zehn.

Alle dafür nötigen Schalter werden vorher gegen ``claude --help``
geprüft. Auf einer älteren Fassung fehlt schlicht die Beschleunigung –
sie darf nie dazu führen, dass gar keine Antwort mehr kommt.

Hinweis zu den Grenzen: Ein Abonnement besitzt Nutzungsgrenzen. Ist die
Grenze erreicht, meldet der Provider dies verständlich, und der Provider
Manager wechselt automatisch auf das lokale Modell.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

#: Meldungen, die auf eine erschöpfte Abo-Nutzungsgrenze hindeuten.
#:
#: „session limit" stand hier NICHT, und das war der ganze Ausfall: Die
#: Befehlszeile meldet im Protokoll des Benutzers wörtlich
#:
#:     You've hit your session limit · resets 2:20pm (Etc/GMT-1)
#:
#: Kein einziger der bisherigen Marker passt darauf. Die Abkühlpause griff
#: deshalb nie, der Orb hielt Claude weiter für verfügbar und lief bei
#: JEDER Frage erneut in dieselbe Wand - bis zu 75 Sekunden Zeitlimit, dann
#: ein neuer Prozess, wieder dieselbe Meldung. Für den Benutzer sah das aus,
#: als sei der Orb tot.
#:
#: Die Liste ist bewusst großzügig: Ein zu früh erkanntes Limit kostet eine
#: halbe Stunde lokales Modell, ein nicht erkanntes kostet den Betrieb.
_LIMIT_MARKERS: tuple[str, ...] = (
    "usage limit",
    "rate limit",
    "session limit",
    "limit reached",
    "hit your limit",
    "hit your session",
    "credit balance",
    "insufficient credit",
    "out of credit",
    "too many requests",
    "nutzungsgrenze",
    "kontingent",
    "quota",
)

#: Die Identitaet, die Claude Code auf SYSTEM-Ebene mitbekommt.
#:
#: Der Grund steht im Protokoll des Benutzers: Das Modell beharrte, es sei
#: "Claude Code im Repository claude_workspace" - und benutzte deshalb die
#: Orb-Werkzeuge nicht. Der Systemprompt des Orb reiste bisher nur als
#: gewoehnlicher Text im '-p'-Prompt mit und war damit schwaecher als die
#: eingebaute Selbstauskunft von Claude Code. Ueber '--append-system-prompt'
#: steht die Orb-Identitaet dort, wo sie hingehoert: im Systemprompt selbst.
_IDENTITAET = (
    "Du bist AI-Orb, ein eigenstaendiger, lokaler Sprachassistent auf dem "
    "Rechner des Benutzers. Du bist NICHT Claude Code und NICHT eine "
    "Entwicklungsumgebung, auch wenn du technisch ueber Claude in einem "
    "Arbeitsordner laeufst - das spielt keine Rolle. Fragt jemand, wer oder "
    "was du bist, bist du AI-Orb (kurz: Orb). Sag NIE, du seiest Claude, "
    "Claude Code oder in einem Repository. Du hast Werkzeuge (Suche, "
    "Bildschirm ansehen, Webseiten lesen, Browser bedienen u.a.); benutze "
    "das passende, statt zu sagen, du koennest etwas nicht."
)

#: Meldungen, die auf eine fehlende Anmeldung hindeuten.
_AUTH_MARKERS: tuple[str, ...] = (
    "not logged in",
    "please log in",
    "authentication",
    "unauthorized",
    "/login",
)

#: Aufrufe, mit denen die Befehlszeile im Strom-Modus arbeitet.
#:
#: Damit bleibt ein Prozess offen und wartet auf die Frage, statt für jede
#: Frage neu zu starten – und die Antwort kommt Stück für Stück, statt erst
#: am Ende in einem Schwall.
_STREAM_ARGS: tuple[str, ...] = (
    "-p",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--include-partial-messages",
)

#: Ein leerer MCP-Satz. Als Zeichenkette, weil die Befehlszeile beides nimmt.
_NO_MCP = '{"mcpServers":{}}'

#: Findet die Schalternamen in der Hilfeausgabe ("--strict-mcp-config").
_FLAG_PATTERN = re.compile(r"--[a-zA-Z][a-zA-Z0-9-]*")

#: Die Schalter, die die Antwortzeit ausmachen. Fehlt einer, wird es
#: langsamer – aber nichts geht kaputt.
_SPEED_FLAGS: frozenset[str] = frozenset(
    {
        "--include-partial-messages",
        "--strict-mcp-config",
        "--setting-sources",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--tools",
        "--effort",
    }
)

#: Zeilen aus der Befehlszeile können lang werden – eine ganze Antwort passt
#: in eine einzige. Die Vorgabe von asyncio (64 KB) reicht dafür nicht.
_LINE_LIMIT = 16 * 1024 * 1024


class ClaudeCodeProvider(BaseProvider):
    """Spricht Claude über die lokal angemeldete Claude-Code-Befehlszeile an."""

    name = "claude_code"

    #: Diese Fassung liest Dateien selbst von der Platte.
    #:
    #: Wichtig für Bilder: Claude Code bekommt kein Bild als Anhang, wohl
    #: aber einen Dateipfad – und öffnet die Datei dann eigenständig. Für
    #: Bildschirmfotos ist das der richtige Weg und obendrein der sparsame:
    #: Das Bild muss nicht als base64 durch den Prompt geschleust werden.
    reads_local_files = True

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        # Modell-Kurznamen ("sonnet", "opus", "haiku") sind stabil und
        # überstehen Modellwechsel – daher die Voreinstellung.
        self._model = str(settings.get("model", "sonnet"))
        self._executable = str(settings.get("executable", "")).strip()
        self._extra_args = [str(argument) for argument in (settings.get("extra_args", []) or [])]
        self._timeout = float(settings.get("timeout", 180))

        # Sperrfrist nach erreichter Nutzungsgrenze.
        #
        # Ist das Abo-Kontingent erschoepft, meldet die Befehlszeile das mit
        # einer Nutzungsgrenzen-Meldung. Der Rueckfall auf das lokale Modell
        # greift ohnehin pro Anfrage - aber ohne diese Sperre wuerde JEDE
        # weitere Frage zuerst wieder in Claudes Limit laufen (und ein paar
        # Sekunden verschenken), bevor sie zu Ollama faellt. Darum wird Claude
        # nach einer Grenzmeldung fuer eine Weile als "nicht verfuegbar"
        # gefuehrt: Der Orb bleibt in dieser Zeit ohne Umweg beim lokalen
        # Modell und probiert Claude erst nach Ablauf wieder.
        self._limit_cooldown = max(0.0, float(settings.get("limit_cooldown_minutes", 30))) * 60.0
        self._limit_until = 0.0

        # Eigenes, leeres Arbeitsverzeichnis: So durchsucht Claude Code nicht
        # versehentlich deine Projektdateien, sondern beantwortet
        # ausschließlich die gestellte Frage.
        self._workdir: Path = get_data_dir() / "claude_workspace"
        self._workdir.mkdir(parents=True, exist_ok=True)

        # Der Ordner, in dem die Bildschirmaufnahmen liegen. Er wird der
        # CLI ausdruecklich freigegeben (siehe _tempo_flags) - sonst darf
        # sie die Aufnahme nicht oeffnen, die ihr genannt wird.
        self._bildordner: Path = get_data_dir() / "vision"
        with contextlib.suppress(OSError):
            self._bildordner.mkdir(parents=True, exist_ok=True)

        self._resolved_executable: str | None = None

        # --- Der vorgewärmte Prozess ------------------------------------------
        #
        # Das Starten der Befehlszeile kostet auf einem Windows-Rechner
        # mehrere Sekunden – und zwar JEDES Mal, bei jeder einzelnen Frage.
        # Das war der größte Teil der Wartezeit, und es war reine
        # Anlaufzeit: Zum Zeitpunkt der Frage war noch kein einziges Wort
        # gedacht.
        #
        # Deshalb steht ab jetzt schon vor der ersten Frage ein Prozess
        # bereit – und er bleibt über das Gespräch hinweg bestehen. Beides
        # zählt: Der Start entfällt, und der Prozess kennt den bisherigen
        # Verlauf bereits, muss ihn also nicht erneut durchdenken. Gemessen
        # kam das erste Wort danach nach anderthalb statt nach vier Sekunden.
        #
        # Geschickt wird deshalb nur noch das Neue. Der Verlauf, den AI-Orb
        # selbst führt, dient als Abgleich: Steht er unverändert vorn, redet
        # der Prozess weiter; wurde er verdichtet oder geleert, beginnt ein
        # frischer – sonst spräche der Orb aus einer Vergangenheit, die es
        # nicht mehr gibt.
        self._use_warm = bool(settings.get("warm_process", True))
        self._lean = bool(settings.get("lean_start", True))
        # Nur „Read": Das braucht der Blick auf den Bildschirm, um ein
        # Bildschirmfoto selbst zu öffnen. Alles Weitere würde die
        # Befehlszeile bloß dazu verleiten, auf eigene Faust zu suchen –
        # AI-Orb hat für Werkzeuge sein eigenes System.
        self._tools = str(settings.get("tools", "Read"))
        # Wie lange das Modell vor dem Antworten nachdenkt.
        #
        # Gemessen an einer gesprochenen Frage: Bei der Vorgabe kam das erste
        # Wort nach drei Sekunden, mit „low" nach knapp einer – bei derselben
        # Modellgüte. Für ein Gespräch ist das der Unterschied zwischen
        # Antworten und Warten. Wer lieber gründlicher gedacht haben möchte,
        # stellt hier "medium" oder "high" ein.
        self._effort = str(settings.get("effort", "low")).strip()
        self._warm: asyncio.subprocess.Process | None = None
        self._warm_stderr: asyncio.Task[Any] | None = None
        self._warm_task: asyncio.Task[Any] | None = None
        self._warm_lock: asyncio.Lock | None = None
        self._warm_broken = False
        #: Welche Benutzernachrichten der laufende Prozess schon kennt.
        self._sent_users: list[str] = []
        #: Wie viele Runden er schon getragen hat.
        self._turns = 0
        #: Nach so vielen Runden wird er abgeloest. Der Prozess fuehrt seinen
        #: eigenen Verlauf mit; irgendwann waere der laenger als noetig und
        #: das Antworten wieder langsamer. Ein frischer Start kostet einmal
        #: Anlaufzeit und faellt in die Sprechpause.
        self._max_turns = int(settings.get("max_turns", 20))
        #: Welche Schalter die vorgefundene Befehlszeile kennt (einmal ermittelt).
        self._flags: frozenset[str] | None = None
        #: Wie lange auf ein Lebenszeichen des wartenden Prozesses gewartet
        #: wird, bevor er als hängend gilt.
        self._warm_timeout = float(settings.get("warm_timeout", 75))

        # --- Der Wachhund ueber dem Warmstart -----------------------------------
        #
        # Der vorgewaermte Prozess war schon einmal die Ursache dafuer, dass
        # der Orb auf jede Frage drei Minuten lang schwieg. Das Sicherheitsnetz
        # dagegen - kurze Frist, Rueckfall auf einen frischen Prozess - faengt
        # jede EINZELNE Frage ab. Es faengt aber nicht den Fall ab, dass der
        # Warmstart dauerhaft kaputt ist: Dann zahlt jede Frage erst die
        # vergebliche Frist und danach den vollen Neustart, und der Warmstart
        # macht den Orb langsamer statt schneller.
        #
        # Deshalb zaehlt der Orb mit (siehe _warm_gescheitert).
        self._warm_fehler = 0

    # --- Auffinden der Befehlszeile ------------------------------------------

    def _find_executable(self) -> str | None:
        """Sucht die Claude-Code-Befehlszeile auf diesem System."""

        if self._resolved_executable is not None:
            return self._resolved_executable

        candidates: list[str] = []
        if self._executable:
            candidates.append(self._executable)
        # Unter Windows liegt der Einstiegspunkt häufig als .cmd vor.
        candidates.extend(["claude", "claude.cmd", "claude.exe"])

        for candidate in candidates:
            found = shutil.which(candidate)
            if found is not None:
                self._resolved_executable = found
                return found

        # Übliche Installationsorte prüfen, falls PATH nicht gesetzt ist.
        home = Path.home()
        for fallback in (
            home / "AppData" / "Roaming" / "npm" / "claude.cmd",
            home / ".local" / "bin" / "claude",
            home / ".claude" / "local" / "claude",
        ):
            if fallback.exists():
                self._resolved_executable = str(fallback)
                return self._resolved_executable

        return None

    @staticmethod
    def _process_command(executable: str, *arguments: str) -> list[str]:
        """Baut einen unter Windows wirklich startbaren Prozessaufruf.

        ``asyncio.create_subprocess_exec`` startet auf Windows nur echte
        Programme direkt. Claude Code wird dort jedoch meistens als
        ``claude.cmd`` installiert; Test- und Hilfsprogramme liegen oft als
        ``.py`` vor. Beide endeten bisher mit WinError 193. Die Shell wird
        nur fuer eine bereits gefundene cmd/bat-Datei verwendet, niemals
        fuer Benutzereingaben oder einen zusammengesetzten Befehlsstring.
        """

        suffix = Path(executable).suffix.lower()
        if suffix == ".py":
            return [sys.executable, executable, *arguments]
        if os.name == "nt" and suffix in {".cmd", ".bat"}:
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            return [comspec, "/d", "/s", "/c", executable, *arguments]
        return [executable, *arguments]

    # --- Verfügbarkeit ---------------------------------------------------------

    async def is_available(self) -> bool:
        """Prüft, ob Claude Code installiert und angemeldet ist."""

        # Steckt Claude gerade in der Sperrfrist nach einer erreichten
        # Nutzungsgrenze, gilt es als nicht verfuegbar - dann haelt der
        # Gesundheitswaechter das lokale Modell aktiv, statt bei jeder
        # Anfrage erneut in Claudes Limit zu laufen. Nach Ablauf faellt die
        # Sperre von selbst, und der naechste Versuch entscheidet neu.
        if self._now() < self._limit_until:
            logger.debug(
                "Claude Code ist wegen erreichter Nutzungsgrenze noch ~%.0f min "
                "gesperrt - es bleibt beim lokalen Modell.",
                (self._limit_until - self._now()) / 60.0,
            )
            return False

        # Die Meldungen hier stehen bewusst auf "warning" und nicht auf
        # "debug".
        #
        # Ist dieser Provider nicht erreichbar und Ollama nicht
        # installiert, sagt der Orb "Ich kann kein Sprachmodell
        # erreichen" – und das ist alles, was der Benutzer erfährt. Der
        # Grund lag auf "debug", die Anzeige auf "info"; er war also
        # ermittelt, aufgeschrieben und trotzdem unsichtbar. Eine
        # Auskunft, die niemand liest, ist keine.
        executable = self._find_executable()
        if executable is None:
            logger.warning(
                "Claude Code wurde nicht gefunden. Gesucht wurde im Suchpfad "
                "nach 'claude', 'claude.cmd' und 'claude.exe' sowie an den "
                "ueblichen Installationsorten."
            )
            return False

        # Das Arbeitsverzeichnis muss existieren, sonst schlaegt schon der
        # Start des Prozesses fehl - und zwar mit einer Meldung, die nach
        # einem Problem mit Claude Code aussieht statt nach einem
        # fehlenden Ordner.
        try:
            self._workdir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            logger.warning("Arbeitsverzeichnis nicht anlegbar (%s): %s", self._workdir, error)
            return False

        try:
            process = await asyncio.create_subprocess_exec(
                *self._process_command(executable, "--version"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workdir),
                env=self._build_environment(),
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20.0)
        except NotImplementedError as error:
            # Unter Windows lassen sich Unterprozesse nicht aus jeder
            # Ereignisschleife heraus starten. Das ist keine Eigenheit von
            # Claude Code, sondern eine von asyncio - und es lohnt, das zu
            # unterscheiden.
            logger.warning(
                "Unterprozesse sind in dieser Ereignisschleife nicht moeglich: %s", error
            )
            return False
        except (OSError, asyncio.TimeoutError) as error:
            logger.warning("Claude Code (%s) antwortet nicht: %s", executable, error)
            return False

        if process.returncode != 0:
            logger.warning(
                "Claude Code meldet einen Fehler (Code %s): %s",
                process.returncode,
                (stderr or b"").decode("utf-8", errors="replace").strip()[:300]
                or "keine Ausgabe",
            )
            return False

        version = (stdout or b"").decode("utf-8", errors="replace").strip()
        logger.info("Claude Code erreichbar: %s (%s)", version or "ohne Fassungsangabe", executable)
        return True

    # --- Anfragen ---------------------------------------------------------------

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Stellt eine Anfrage über die Claude-Code-Befehlszeile.

        Der Gesprächsverlauf wird von AI-Orb selbst verwaltet
        (:class:`~backend.orchestrator.conversation_manager.ConversationManager`)
        und hier zu einem einzelnen Prompt zusammengesetzt. Claude Code
        startet dadurch für jede Anfrage ohne eigenen Verlauf – der Kontext
        kommt vollständig von AI-Orb.
        """

        if self._use_warm and not self._warm_broken:
            started = self._now()
            try:
                text = ""
                async with self._lock():
                    prompt, weiter = await self._prepare_turn(messages)
                    if weiter:
                        try:
                            async for art, inhalt in self._stream_from_warm(prompt):
                                if art == "ende":
                                    text = inhalt
                        except BaseException:
                            await self._retire_warm()
                            raise
                self._maybe_replace()
                if text:
                    self._warm_gelungen()
                    dauer = self._now() - started
                    # Die Dauer stand bisher nur im Rueckgabewert und
                    # nirgends im Protokoll. Damit liess sich nach einer
                    # Aenderung nicht sagen, ob sie etwas gebracht hat -
                    # und was man nicht misst, verbessert man nicht,
                    # sondern glaubt es nur.
                    logger.info(
                        "Antwort in %.1f s (vorgewaermt, %d Zeichen).",
                        dauer,
                        len(text),
                    )
                    return ProviderResponse(
                        text=text,
                        provider=self.name,
                        model=self._model,
                        latency_seconds=dauer,
                        finish_reason="stop",
                        raw={"warm": True},
                    )
            except Exception as fehler:  # noqa: BLE001
                # Der vorgewärmte Weg ist eine Beschleunigung, keine
                # Bedingung. Geht er schief, wird wie früher gestartet –
                # langsamer, aber der Benutzer bekommt seine Antwort.
                #
                # Vorher stand hier für ProviderError ein blosses `raise`,
                # und das war der schlimmstmögliche Fall: Blieb der
                # wartende Prozess hängen oder starb er still, scheiterte
                # damit JEDE Anfrage – und zwar erst nach dem Zeitlimit.
                # Der Orb schwieg minutenlang und antwortete dann gar
                # nicht. Ein Beschleuniger, der beim Versagen alles
                # mitreisst, ist keiner.
                self._warm_gescheitert(str(fehler))
                with contextlib.suppress(Exception):
                    await self._retire_warm()

        return await self._chat_einzeln(self._compose_prompt(messages))

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Liefert die Antwort Stück für Stück, während sie entsteht.

        Damit fängt der Orb an zu sprechen, sobald der erste Satz fertig
        gedacht ist – statt zu schweigen, bis der letzte steht. Das ist der
        Unterschied zwischen „er antwortet nach drei Sekunden" und „er
        antwortet nach zwölf", obwohl beides gleich lange dauert.
        """

        if not self._use_warm or self._warm_broken:
            response = await self.chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
            if response.text:
                yield response.text
            return

        etwas_gesagt = False

        async with self._lock():
            prompt, weiter = await self._prepare_turn(messages)
            if not weiter:
                self._warm_broken = True
                antwort = await self._chat_einzeln(self._compose_prompt(messages))
                if antwort.text:
                    yield antwort.text
                return
            try:
                async for art, inhalt in self._stream_from_warm(prompt):
                    if art == "text":
                        etwas_gesagt = True
                        yield inhalt
                    elif art == "ende" and not etwas_gesagt and inhalt:
                        # Kam nichts stückweise an, wenigstens das Ganze.
                        yield inhalt
                # Auch hier melden. Wuerde der Wachhund nur im gewoehnlichen
                # Weg mitzaehlen, bliebe der haeufigste Weg - der
                # gesprochene - fuer ihn unsichtbar.
                self._warm_gelungen()
            except Exception as fehler:  # noqa: BLE001
                self._warm_gescheitert(str(fehler))
                await self._retire_warm()
                if etwas_gesagt:
                    # Mittendrin abgerissen. Noch einmal von vorn zu
                    # beginnen hiesse, den halben Satz ein zweites Mal zu
                    # sprechen – dann lieber hier enden.
                    logger.warning("Der Strom riss ab: %s", fehler)
                    return
                logger.warning(
                    "Der Strom kam nicht zustande (%s); es wird neu gestartet.",
                    fehler,
                )
                antwort = await self._chat_einzeln(self._compose_prompt(messages))
                if antwort.text:
                    yield antwort.text
                return
            except BaseException:
                await self._retire_warm()
                raise
        self._maybe_replace()

    async def _chat_einzeln(self, prompt: str) -> ProviderResponse:
        """Der alte Weg: für diese eine Frage einen Prozess starten.

        Bleibt als Rückfallebene bestehen – etwa wenn sich in dieser
        Ereignisschleife keine wartenden Prozesse halten lassen.
        """

        executable = self._find_executable()
        if executable is None:
            raise ProviderError(
                "claude_code: Claude Code wurde nicht gefunden. Installiere es und "
                "melde dich einmalig mit deinem Abo an ('claude' im Terminal)."
            )

        arguments = self._process_command(
            executable,
            "-p",
            prompt,
            "--output-format",
            "json",
        )
        if self._model:
            arguments.extend(["--model", self._model])
        # Auch hier nur, was diese Fassung kennt – sonst startet der Aufruf
        # gar nicht erst.
        await self._supported_flags(executable)
        arguments.extend(self._tempo_flags())
        arguments.extend(self._extra_args)

        started = self._now()
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workdir),
                env=self._build_environment(),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError as error:
            raise ProviderError(
                f"claude_code: Zeitlimit von {self._timeout:.0f} s überschritten."
            ) from error
        except OSError as error:
            raise ProviderError(f"claude_code: Aufruf fehlgeschlagen – {error}") from error

        latency = self._now() - started
        stdout = (stdout_bytes or b"").decode("utf-8", errors="replace").strip()
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()

        if process.returncode != 0:
            raise ProviderError(self._explain_failure(stderr or stdout))

        text = self._extract_text(stdout)
        if not text:
            raise ProviderError(self._explain_failure(stderr or stdout or "leere Antwort"))

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self._model,
            latency_seconds=latency,
            finish_reason="stop",
            raw={"stdout_length": len(stdout)},
        )

    # --- Der vorgewärmte Prozess -------------------------------------------------

    def _lock(self) -> asyncio.Lock:
        """Die Sperre erst anlegen, wenn eine Ereignisschleife läuft."""

        if self._warm_lock is None:
            self._warm_lock = asyncio.Lock()
        return self._warm_lock

    async def _supported_flags(self, executable: str) -> frozenset[str]:
        """Ermittelt einmalig, welche Schalter diese Befehlszeile kennt.

        Der Grund ist Vorsicht, nicht Neugier: Die Beschleunigungsschalter
        gibt es erst ab neueren Fassungen von Claude Code. Auf einer älteren
        würde ein unbekannter Schalter nicht etwa übergangen, sondern den
        Start verweigern – und dann bekäme der Benutzer auf JEDE Frage einen
        Fehler statt einer Antwort. Ein langsamer Orb ist ärgerlich, ein
        stummer unbrauchbar.

        Wird nichts ermittelt, gilt nichts als bekannt: Dann läuft alles wie
        vor dieser Änderung.
        """

        if self._flags is not None:
            return self._flags

        self._flags = frozenset()
        try:
            process = await asyncio.create_subprocess_exec(
                *self._process_command(executable, "--help"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workdir),
                env=self._build_environment(),
                limit=_LINE_LIMIT,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30.0)
        except (OSError, NotImplementedError, ValueError, asyncio.TimeoutError) as error:
            logger.warning(
                "Die Schalter der Befehlszeile liessen sich nicht ermitteln (%s) – "
                "es wird ohne die Beschleunigungen gearbeitet.",
                error,
            )
            return self._flags

        hilfe = (stdout or b"").decode("utf-8", errors="replace")
        self._flags = frozenset(_FLAG_PATTERN.findall(hilfe))
        fehlend = sorted(_SPEED_FLAGS - self._flags)
        if fehlend:
            logger.info(
                "Diese Fassung von Claude Code kennt %s nicht – die Antworten "
                "kommen deshalb langsamer. Ein 'npm update -g @anthropic-ai/claude-code' "
                "hilft.",
                ", ".join(fehlend),
            )
        return self._flags

    def _stream_arguments(self, executable: str) -> list[str]:
        """Baut den Aufruf für einen wartenden Prozess."""

        arguments = self._process_command(executable)
        arguments.extend(self._filter_flags(_STREAM_ARGS))
        if self._model:
            arguments.extend(["--model", self._model])
        arguments.extend(self._tempo_flags())
        arguments.extend(self._extra_args)
        return arguments

    def _tempo_flags(self) -> list[str]:
        """Die Schalter, die die Antwortzeit ausmachen – soweit bekannt.

        Was diese Fassung von Claude Code nicht kennt, bleibt weg. Das ist
        der Unterschied zwischen "langsamer als möglich" und "startet gar
        nicht": Ein unbekannter Schalter verweigert den Start, und dann gäbe
        es auf jede Frage einen Fehler statt einer Antwort.
        """

        bekannt = self._flags or frozenset()
        argumente: list[str] = []

        # Die Orb-Identitaet auf System-Ebene - stark genug, um Claude Codes
        # eingebaute Selbstauskunft zu ueberschreiben. Kennt die Fassung den
        # Schalter nicht, bleibt es beim (verstaerkten) Systemprompt im Text.
        if "--append-system-prompt" in bekannt:
            argumente.extend(["--append-system-prompt", _IDENTITAET])

        # Werkzeuge ausdrücklich benennen – und die benannten auch gleich
        # erlauben, sonst bliebe eine Rückfrage offen, die niemand sieht.
        if "--tools" in bekannt:
            argumente.extend(["--tools", self._tools])
            if self._tools and "--allowedTools" in bekannt:
                argumente.extend(["--allowedTools", self._tools])
        if self._effort and "--effort" in bekannt:
            argumente.extend(["--effort", self._effort])

        # Der Ordner mit den Bildschirmaufnahmen wird ausdruecklich
        # freigegeben.
        #
        # Ohne das kann die Bildauswertung nicht funktionieren, und zwar
        # aus einem Grund, den man dem Fehlerbild nicht ansieht: Claude
        # Code liest nur innerhalb seines Arbeitsverzeichnisses, und das
        # ist hier bewusst ein leerer eigener Ordner - damit es nicht
        # versehentlich in fremden Dateien sucht. Die Aufnahme liegt aber
        # daneben, in `vision`. Der Pfad wurde also genannt, die Datei
        # existierte, und die CLI durfte trotzdem nicht hinsehen.
        #
        # Freigegeben wird genau dieser eine Ordner und nicht der
        # Datenordner darueber: Dort liegen auch die Konfiguration und das
        # Stimmprofil, und die gehen einer Bildbeschreibung nichts an.
        if "--add-dir" in bekannt:
            argumente.extend(["--add-dir", str(self._bildordner)])
        if self._lean:
            # Alles abschalten, was beim Start Zeit kostet und für eine
            # gesprochene Antwort nichts beiträgt: fremde MCP-Server,
            # Einstellungsdateien, Skills, das Ablegen der Sitzung.
            if "--strict-mcp-config" in bekannt and "--mcp-config" in bekannt:
                argumente.extend(["--strict-mcp-config", "--mcp-config", _NO_MCP])
            if "--setting-sources" in bekannt:
                argumente.extend(["--setting-sources", ""])
            if "--disable-slash-commands" in bekannt:
                argumente.append("--disable-slash-commands")
            if "--no-session-persistence" in bekannt:
                argumente.append("--no-session-persistence")
        return argumente

    def _filter_flags(self, argumente: tuple[str, ...]) -> list[str]:
        """Laesst unbekannte Schalter aus einer festen Liste weg."""

        bekannt = self._flags or frozenset()
        heraus: list[str] = []
        for eintrag in argumente:
            if eintrag.startswith("--") and eintrag not in bekannt:
                continue
            heraus.append(eintrag)
        return heraus

    async def prewarm(self) -> bool:
        """Startet im Voraus einen Prozess, damit die erste Frage nicht wartet.

        Wird beim Hochfahren aufgerufen – zusammen mit dem Vorladen von
        Spracherkennung und Stimme. Schlägt es fehl, ist das kein Fehler:
        Dann wird eben wie früher für jede Frage neu gestartet.
        """

        if not self._use_warm or self._warm_broken:
            return False
        async with self._lock():
            return await self._ensure_warm()

    async def shutdown(self) -> None:
        """Beendet einen wartenden Prozess beim Herunterfahren.

        Sonst bliebe er als verwaister Prozess zurück – und beim nächsten
        Start stünden zwei davon herum.
        """

        # Zuerst abschalten, dann aufräumen. Andersherum könnte ein bereits
        # angestoßenes Nachlegen noch einen Prozess starten, den danach
        # niemand mehr beendet – und der bliebe als Waise zurück.
        self._use_warm = False

        task, self._warm_task = self._warm_task, None
        if task is not None and not task.done():
            task.cancel()
            # CancelledError ist kein Exception mehr, sondern BaseException –
            # ohne die ausdrückliche Nennung käme sie hier wieder heraus.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        with contextlib.suppress(Exception):
            await self._retire_warm()

    async def _prepare_turn(self, messages: list[ChatMessage]) -> tuple[str, bool]:
        """Entscheidet, ob der laufende Prozess weiterreden darf.

        Der wartende Prozess hält den Gesprächsfaden: Wer ihn behält, spart
        nicht nur den Start, sondern auch das erneute Durchdenken des
        bisherigen Verlaufs. Gemessen war das der Unterschied zwischen
        „erstes Wort nach vier Sekunden" und „nach anderthalb".

        Weitergeredet wird nur, wenn der bisherige Verlauf unverändert vorn
        steht. Wurde er verdichtet, geleert oder sonstwie umgeschrieben,
        beginnt ein frischer Prozess – sonst spräche der Orb aus einer
        Vergangenheit, die es nicht mehr gibt.

        Returns:
            Den zu sendenden Text und ob ein Prozess bereitsteht.
        """

        verlauf = [
            self._fingerabdruck(nachricht)
            for nachricht in messages
            if nachricht.role == "user"
        ]
        system = [nachricht for nachricht in messages if nachricht.role == "system"]

        passt = (
            self._warm is not None
            and self._warm.returncode is None
            and self._turns < self._max_turns
            and len(verlauf) > len(self._sent_users)
            and verlauf[: len(self._sent_users)] == self._sent_users
        )

        if passt:
            # Nur das Neue schicken. Den Systemteil dennoch jedes Mal – er
            # trägt die Uhrzeit, den Gedächtniskontext und die Werkzeugliste,
            # und die sind jetzt gültig, nicht von vorhin.
            neu = [
                nachricht
                for nachricht in messages
                if nachricht.role == "user"
            ][len(self._sent_users) :]
            self._sent_users = verlauf
            self._turns += 1
            return self._compose_prompt([*system, *neu]), True

        await self._retire_warm()
        if not await self._ensure_warm():
            return "", False
        self._sent_users = verlauf
        self._turns = 1
        return self._compose_prompt(messages), True

    @staticmethod
    def _fingerabdruck(nachricht: ChatMessage) -> str:
        """Ein kurzer, stabiler Abdruck einer Nachricht."""

        return hashlib.sha1(nachricht.content.encode("utf-8")).hexdigest()

    async def _ensure_warm(self) -> bool:
        """Sorgt dafür, dass ein wartender Prozess bereitsteht."""

        if self._warm is not None and self._warm.returncode is None:
            return True
        self._warm = None

        executable = self._find_executable()
        if executable is None:
            return False

        bekannt = await self._supported_flags(executable)
        if "--input-format" not in bekannt or "--output-format" not in bekannt:
            # Ohne diese beiden gibt es keinen wartenden Prozess. Das ist
            # kein Fehler, nur eine ältere Fassung.
            self._warm_broken = True
            return False

        try:
            process = await asyncio.create_subprocess_exec(
                *self._stream_arguments(executable),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workdir),
                env=self._build_environment(),
                limit=_LINE_LIMIT,
            )
        except (OSError, NotImplementedError, ValueError) as error:
            # NotImplementedError trifft Ereignisschleifen, die unter Windows
            # keine Unterprozesse können. Dann bleibt es beim alten Weg.
            logger.warning(
                "Kein vorgewaermter Claude-Prozess moeglich (%s) – es wird "
                "wie bisher fuer jede Frage neu gestartet.",
                error,
            )
            self._warm_broken = True
            return False

        self._warm = process
        # Die Fehlerausgabe muss jemand mitlesen, sonst läuft die Leitung
        # voll und der Prozess bleibt irgendwann stehen.
        self._warm_stderr = asyncio.ensure_future(self._drain_stderr(process))
        logger.info("Ein Claude-Code-Prozess steht bereit und wartet auf die naechste Frage.")
        return True

    @staticmethod
    async def _drain_stderr(process: asyncio.subprocess.Process) -> None:
        """Liest die Fehlerausgabe mit, damit die Leitung nicht verstopft."""

        stream = process.stderr
        if stream is None:
            return
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("claude_code: %s", text)
        except (asyncio.CancelledError, ValueError, OSError):
            return

    async def _retire_warm(self) -> None:
        """Verabschiedet den benutzten Prozess und stellt einen frischen bereit."""

        process, self._warm = self._warm, None
        task, self._warm_stderr = self._warm_stderr, None
        # Mit dem Prozess geht auch sein Gedächtnis. Bliebe der Abgleich
        # stehen, hielte der nächste Prozess einen Verlauf für bekannt, den
        # er nie gehört hat – und die Antwort verlöre ihren Bezug.
        self._sent_users = []
        self._turns = 0

        if task is not None:
            task.cancel()
        if process is not None:
            with contextlib.suppress(Exception):
                if process.stdin is not None and not process.stdin.is_closing():
                    process.stdin.close()
            with contextlib.suppress(Exception):
                process.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=5.0)

    def _schedule_warm(self) -> None:
        """Löst einen erschöpften Prozess im Hintergrund ab.

        Ausdrücklich ohne Warten: Der Anlauf soll in die Zeit fallen, in der
        der Orb gerade spricht – dann merkt ihn niemand. Geschähe die
        Ablösung erst bei der nächsten Frage, zahlte ausgerechnet die den
        Start, und alle paar Runden wäre eine Antwort ohne Grund langsam.
        """

        if not self._use_warm or self._warm_broken:
            return
        if self._warm_task is not None and not self._warm_task.done():
            return

        async def _abloesen() -> None:
            with contextlib.suppress(Exception):
                async with self._lock():
                    # Zwischen dem Anstoßen und dem Zug kann das Herunter-
                    # fahren dazwischengekommen sein. Dann darf hier nichts
                    # mehr starten, was niemand mehr beendet.
                    if not self._use_warm or self._warm_broken:
                        return
                    await self._retire_warm()
                    await self._ensure_warm()

        with contextlib.suppress(RuntimeError):
            self._warm_task = asyncio.ensure_future(_abloesen())

    def _maybe_replace(self) -> None:
        """Prüft nach einer Runde, ob der Prozess abgelöst gehört."""

        if self._turns >= self._max_turns:
            logger.info(
                "Der Claude-Prozess hat %d Runden getragen und wird im "
                "Hintergrund abgeloest.",
                self._turns,
            )
            self._schedule_warm()

    def _warm_gescheitert(self, grund: str) -> None:
        """Meldet dem Wachhund einen Fehlschlag des Warmstarts.

        Den Notschalter ``_warm_broken`` gab es schon, und er wurde an
        mehreren Stellen gesetzt - nur nicht an der wichtigsten. In
        :meth:`chat` wurde ein gescheiterter Warmstart bloss weggeraeumt
        und die Frage neu gestellt. Das ist fuer einen Ausrutscher richtig
        und fuer einen dauerhaften Defekt das Schlechteste, was man tun
        kann: Jede Frage zahlt dann erst die vergebliche Frist und danach
        den vollen Neustart obendrauf. Der Warmstart macht den Orb in dem
        Fall LANGSAMER, und niemand merkt, warum.

        Zwei Fehlschlaege hintereinander, und der Warmstart bleibt fuer
        diese Sitzung aus. Zwei und nicht einer: Ein einzelner kann eine
        ueberlange Frage sein oder ein Netzhaenger, und eine Faehigkeit
        wegen eines Ausrutschers aufzugeben waere voreilig.
        """

        self._warm_fehler += 1
        if self._warm_fehler < 2:
            logger.warning(
                "Der vorgewaermte Prozess hat nicht geliefert (%s). Diese "
                "Frage laeuft ueber einen frischen Prozess weiter.",
                grund,
            )
            return

        self._warm_broken = True
        logger.warning(
            "Der vorgewaermte Prozess ist zweimal hintereinander gescheitert "
            "(%s). Er bleibt fuer diese Sitzung abgeschaltet - der Orb "
            "antwortet weiter, nur ohne den Zeitvorteil. Nach einem Neustart "
            "wird er wieder versucht.",
            grund,
        )

    def _warm_gelungen(self) -> None:
        """Setzt den Wachhund zurueck.

        Ein Fehler von vor einer Stunde soll nicht mit einem von jetzt
        zusammenzaehlen - sonst legte der Wachhund den Warmstart
        irgendwann wegen zweier voellig unabhaengiger Ausrutscher still.
        """

        self._warm_fehler = 0

    async def _stream_from_warm(self, prompt: str) -> AsyncIterator[tuple[str, str]]:
        """Schickt die Frage an den wartenden Prozess und liefert die Stücke.

        Ergibt Paare aus Art und Inhalt: ``("text", …)`` für ein Stück der
        Antwort und ``("ende", …)`` für den vollständigen Text am Schluss.

        Raises:
            ProviderError: Wenn kein Prozess bereitsteht oder er abbricht.
        """

        process = self._warm
        if process is None or process.returncode is not None:
            raise ProviderError("claude_code: kein bereitstehender Prozess.")
        if process.stdin is None or process.stdout is None:
            raise ProviderError("claude_code: der Prozess hat keine Leitungen.")

        nachricht = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
        }
        try:
            process.stdin.write((json.dumps(nachricht) + "\n").encode("utf-8"))
            await process.stdin.drain()
        except (OSError, BrokenPipeError) as error:
            raise ProviderError(f"claude_code: Frage nicht zustellbar – {error}") from error

        gesammelt: list[str] = []
        # Kürzer als das grosse Zeitlimit, und mit Absicht.
        #
        # Das grosse (drei Minuten) ist für einen frisch gestarteten Prozess
        # gedacht, der noch lädt. Ein wartender Prozess, der nach einer
        # Minute kein Zeichen von sich gegeben hat, lädt nicht – er hängt.
        # Drei Minuten zu warten hiesse, den Benutzer für einen Fehler
        # büssen zu lassen, der nach sechzig Sekunden feststand.
        frist = min(self._timeout, self._warm_timeout)

        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=frist)
            except asyncio.TimeoutError as error:
                raise ProviderError(
                    f"claude_code: Zeitlimit von {frist:.0f} s überschritten."
                ) from error
            except (ValueError, OSError) as error:
                raise ProviderError(f"claude_code: Antwort nicht lesbar – {error}") from error

            if not line:
                raise ProviderError("claude_code: der Prozess hat sich beendet.")

            try:
                daten = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if not isinstance(daten, dict):
                continue

            art = daten.get("type")

            if art == "stream_event":
                ereignis = daten.get("event") or {}
                if ereignis.get("type") == "content_block_delta":
                    stueck = str((ereignis.get("delta") or {}).get("text", ""))
                    if stueck:
                        gesammelt.append(stueck)
                        yield ("text", stueck)
                continue

            if art == "result":
                if daten.get("is_error"):
                    raise ProviderError(
                        self._explain_failure(str(daten.get("result") or "unbekannter Fehler"))
                    )
                ganz = str(daten.get("result") or "").strip()
                yield ("ende", ganz or "".join(gesammelt).strip())
                return

    # --- Hilfsfunktionen ---------------------------------------------------------

    @staticmethod
    def _compose_prompt(messages: list[ChatMessage]) -> str:
        """Setzt den Verlauf zu einem einzelnen Prompt zusammen.

        Systemnachrichten stehen voran, danach folgt der Verlauf mit klar
        gekennzeichneten Sprechern, damit Claude den Zusammenhang erkennt.
        """

        system_parts = [
            message.content.strip()
            for message in messages
            if message.role == "system" and message.content.strip()
        ]
        dialogue = [message for message in messages if message.role != "system"]

        blocks: list[str] = []
        if system_parts:
            blocks.append("\n\n".join(system_parts))

        if len(dialogue) == 1 and dialogue[0].role == "user":
            # Einzelanfrage: kein künstliches Verlaufsgerüst nötig.
            blocks.append(dialogue[0].content.strip())
        else:
            history: list[str] = []
            for message in dialogue:
                speaker = "Benutzer" if message.role == "user" else "Assistent"
                history.append(f"{speaker}: {message.content.strip()}")
            if history:
                blocks.append(
                    "Bisheriger Gesprächsverlauf:\n"
                    + "\n\n".join(history[:-1])
                    + "\n\nAktuelle Nachricht des Benutzers:\n"
                    + dialogue[-1].content.strip()
                    if len(history) > 1
                    else history[0]
                )

        return "\n\n".join(part for part in blocks if part).strip()

    @staticmethod
    def _extract_text(stdout: str) -> str:
        """Liest den Antworttext aus der Ausgabe der Befehlszeile.

        Bevorzugt wird die JSON-Ausgabe; ist sie nicht auswertbar, wird die
        Rohausgabe verwendet, damit eine Antwort nicht verloren geht.
        """

        if not stdout:
            return ""

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            # Manche Fassungen geben mehrere JSON-Zeilen aus.
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    parsed = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            else:
                return stdout

        if isinstance(parsed, list):
            parsed = parsed[-1] if parsed else {}

        if isinstance(parsed, dict):
            if parsed.get("is_error"):
                return ""
            for key in ("result", "text", "content", "message"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    texts = [
                        str(block.get("text", ""))
                        for block in value
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    joined = "\n".join(text for text in texts if text).strip()
                    if joined:
                        return joined

        return ""

    def _explain_failure(self, output: str) -> str:
        """Übersetzt eine Fehlermeldung der Befehlszeile in Klartext.

        Nebenbei wird hier die Nutzungsgrenze erkannt und die Sperrfrist
        gesetzt: Dies ist der eine Punkt, durch den ALLE Fehlermeldungen der
        Befehlszeile laufen, ganz gleich ob aus dem vorgewärmten Prozess,
        dem Einzelaufruf oder dem Strom. Wer die Grenze nur an einer Stelle
        abfinge, uebersaehe sie an den anderen.
        """

        lowered = output.lower()

        if any(marker in lowered for marker in _AUTH_MARKERS):
            return (
                "claude_code: Du bist in Claude Code nicht angemeldet. Öffne ein "
                "Terminal, gib 'claude' ein und melde dich mit deinem Abo an."
            )
        if any(marker in lowered for marker in _LIMIT_MARKERS):
            if self._limit_cooldown > 0:
                self._limit_until = self._now() + self._limit_cooldown
                logger.warning(
                    "Claude-Nutzungsgrenze erreicht. Ich fuehre Claude Code fuer "
                    "%.0f Minuten als nicht verfuegbar und arbeite solange mit dem "
                    "lokalen Modell weiter.",
                    self._limit_cooldown / 60.0,
                )
            return (
                "claude_code: Die Nutzungsgrenze deines Abonnements ist derzeit "
                "erreicht. Ich wechsle auf das lokale Modell, bis sie sich "
                "zurücksetzt."
            )
        return f"claude_code: {output[:400]}" if output else "claude_code: unbekannter Fehler"

    def _build_environment(self) -> dict[str, str]:
        """Erzeugt die Umgebung für den Unterprozess.

        Ein gesetzter ``ANTHROPIC_API_KEY`` wird bewusst entfernt: Sonst
        würde Claude Code über den API-Schlüssel abrechnen statt über dein
        Abonnement.
        """

        environment = dict(os.environ)
        environment.pop("ANTHROPIC_API_KEY", None)
        environment.pop("ANTHROPIC_AUTH_TOKEN", None)
        return environment
