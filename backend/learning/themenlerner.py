"""Der Themenlerner – aus gelesenem Text werden belegte Aussagen.

Dies ist die Stelle, an der aus Text Wissen wird, und sie hat genau eine
Aufgabe: **destillieren, nicht zusammenfassen.**

Der Unterschied ist entscheidend. Eine Zusammenfassung ist ein Fliesstext,
der nur als Ganzes Sinn ergibt; sie lässt sich später weder einzeln
wiederfinden noch mit einer Quelle belegen noch mit etwas Neuem
zusammenführen. Was hier entsteht, sind einzelne Feststellungen, jede für
sich verständlich und jede mit ihrer Herkunft. Erst daraus lässt sich beim
nächsten Mal etwas holen.

## Warum das Modell das machen muss und nicht eine Regel

Man könnte Sätze mechanisch trennen und die längsten nehmen. Das wäre
schneller und wertlos: Was in einem Artikel zählt und was Beiwerk ist,
entscheidet sich am Inhalt und nicht an der Satzlänge. Also fragt diese
Stelle das Sprachmodell – und zwar mit einer Anweisung, die drei Dinge
ausdrücklich verlangt:

  1. **Jede Aussage muss allein verständlich sein.** „Er trat daraufhin
     zurück" ist ohne den Umgebungstext wertlos, und den gibt es später
     nicht mehr.

  2. **Nichts hinzuerfinden.** Was in keiner Quelle stand, darf nicht
     erscheinen – auch dann nicht, wenn es stimmt. Ein Wissensspeicher,
     dem man nicht trauen kann, ist schlimmer als keiner.

  3. **Offene Fragen benennen.** Das ist der Teil, den man am ehesten
     weglässt und am dringendsten braucht: Aus ihnen speist sich das
     Vertiefen und das selbstständige Weiterarbeiten.

## Zum Format

Verlangt wird JSON, und die Antwort wird streng gelesen. Kommt Unsinn
zurück, wird lieber nichts gespeichert als etwas Halbes – ein Thema mit
Bruchstücken darin sieht gefüllt aus und ist wertlos.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.learning.themenwissen import (
    MAX_AUSSAGEN,
    MAX_FRAGEN,
    ZEICHEN_JE_QUELLE,
    Aussage,
    Thema,
    Themenspeicher,
)
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


_ANWEISUNG = (
    "Du arbeitest einem wissenschaftlich arbeitenden Menschen zu. Aus den "
    "vorgelegten Quellen destillierst du Wissen - du fasst NICHT zusammen.\n\n"
    "Regeln, an die du dich halten musst:\n"
    "1. Jede Aussage muss FUER SICH verstaendlich sein. Keine Verweise wie "
    "'er', 'dort', 'daraufhin' - nenne Namen, Orte, Jahre.\n"
    "2. Erfinde NICHTS. Was nicht in den Quellen steht, kommt nicht vor - "
    "auch dann nicht, wenn du es weisst.\n"
    "3. Gib zu jeder Aussage die Quelle an, aus der sie stammt.\n"
    "4. Ist etwas in den Quellen umstritten, kennzeichne es als strittig, "
    "statt dich fuer eine Seite zu entscheiden.\n"
    "5. Benenne, was offen bleibt: Fragen, die die Quellen aufwerfen, aber "
    "nicht beantworten.\n\n"
    "Antworte AUSSCHLIESSLICH mit JSON in genau dieser Form, ohne "
    "Vorrede und ohne Nachwort:\n"
    '{"aussagen": [{"text": "...", "quelle": "...", '
    '"sicherheit": "fakt|wahrscheinlich|strittig"}], '
    '"offene_fragen": ["...", "..."]}'
)


@dataclass
class Lernergebnis:
    """Was ein Durchgang erbracht hat."""

    ok: bool = False
    thema: str = ""
    neue_aussagen: int = 0
    neue_fragen: int = 0
    quellen: list[str] = None  # type: ignore[assignment]
    hinweis: str = ""

    def __post_init__(self) -> None:
        if self.quellen is None:
            self.quellen = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "thema": self.thema,
            "neue_aussagen": self.neue_aussagen,
            "neue_fragen": self.neue_fragen,
            "quellen": list(self.quellen),
            "hinweis": self.hinweis,
        }


def _json_aus(text: str) -> dict[str, Any] | None:
    """Holt das JSON-Objekt aus einer Modellantwort.

    Modelle stellen gern eine Zeile davor („Hier ist das Ergebnis:") oder
    packen alles in einen Codeblock. Beides ist kein Fehler des Modells,
    sondern etwas, worauf man sich einstellt: Gesucht wird die äusserste
    geschweifte Klammer.
    """

    if not text:
        return None
    anfang = text.find("{")
    ende = text.rfind("}")
    if anfang < 0 or ende <= anfang:
        return None
    try:
        daten = json.loads(text[anfang : ende + 1])
    except ValueError:
        return None
    return daten if isinstance(daten, dict) else None


class Themenlerner:
    """Arbeitet ein Thema ein und hält das Ergebnis fest."""

    def __init__(
        self,
        *,
        speicher: Themenspeicher,
        provider_manager: Any,
        memory: Any | None = None,
    ) -> None:
        """
        Args:
            speicher: Wohin die Themen geschrieben werden.
            provider_manager: Fürs Destillieren.
            memory: Das Langzeitgedächtnis. Jede Aussage wird zusätzlich
                dort abgelegt, damit die bestehende Erinnerungssuche sie
                findet – ohne das wäre das Themenwissen eine zweite,
                abgeschottete Ablage, und der Orb wüsste etwas, käme aber
                im Gespräch nicht darauf.
        """

        self._speicher = speicher
        self._providers = provider_manager
        self._memory = memory

    # --- Aus dem Internet ----------------------------------------------------------

    async def aus_dem_netz(
        self, thema_name: str, *, quellen: int = 3, frage: str = ""
    ) -> Lernergebnis:
        """Sucht, liest und arbeitet ein.

        Args:
            thema_name: Das Gebiet.
            quellen: Wie viele Fundstellen gelesen werden.
            frage: Wonach genau gesucht wird. Leer heisst: nach dem Thema
                selbst. Beim Vertiefen steht hier eine offene Frage – so
                landet der Orb nicht wieder auf denselben Übersichtsseiten.
        """

        from backend.tools.web_tools import search_web

        thema = self._speicher.laden(thema_name)
        suche = frage.strip() or thema_name

        try:
            treffer = await asyncio.to_thread(search_web, suche, limit=max(1, quellen) + 3)
        except Exception as fehler:  # noqa: BLE001
            return Lernergebnis(
                thema=thema_name, hinweis=f"Die Suche ist gescheitert: {fehler}"
            )

        if not treffer:
            return Lernergebnis(
                thema=thema_name, hinweis=f"Zu '{suche}' war nichts zu finden."
            )

        # Schon Gelesenes überspringen. Ohne das läse der Orb beim
        # Vertiefen wieder dieselben drei Seiten und käme nie weiter.
        frisch = [t for t in treffer if t.get("url") and t["url"] not in thema.gelesen]
        if not frisch:
            return Lernergebnis(
                thema=thema_name,
                hinweis=(
                    "Alle gefundenen Quellen kenne ich schon. Gib mir eine "
                    "genauere Frage, dann suche ich gezielter."
                ),
            )

        gelesen = await self._quellen_lesen(frisch[:quellen])
        if not gelesen:
            return Lernergebnis(
                thema=thema_name, hinweis="Keine der Quellen ließ sich lesen."
            )

        ergebnis = await self._einarbeiten(thema, gelesen, frage=frage)
        return ergebnis

    async def _quellen_lesen(self, treffer: list[dict[str, str]]) -> list[tuple[str, str]]:
        """Holt den Text der Fundstellen. Gibt Paare aus URL und Text."""

        from backend.tools.web_tools import _TextExtractor, _decode, _fetch

        gelesen: list[tuple[str, str]] = []
        for eintrag in treffer:
            url = eintrag.get("url", "")
            if not url:
                continue

            def _lesen(ziel: str = url) -> str:
                extractor = _TextExtractor()
                extractor.feed(_decode(_fetch(ziel)))
                return extractor.text()

            try:
                text = await asyncio.to_thread(_lesen)
            except Exception:  # noqa: BLE001 - eine tote Seite ist kein Abbruch.
                logger.debug("Quelle %s ließ sich nicht lesen.", url, exc_info=True)
                continue
            if text and len(text.strip()) > 200:
                gelesen.append((url, text[:ZEICHEN_JE_QUELLE]))
        return gelesen

    # --- Aus einer Datei -----------------------------------------------------------

    async def aus_datei(self, thema_name: str, pfad: Path) -> Lernergebnis:
        """Arbeitet eine Datei ein – ein PDF, ein Dokument, einen Text."""

        try:
            text = await asyncio.to_thread(self._datei_lesen, pfad)
        except Exception as fehler:  # noqa: BLE001
            return Lernergebnis(
                thema=thema_name, hinweis=f"Die Datei ließ sich nicht lesen: {fehler}"
            )

        if not text or len(text.strip()) < 200:
            return Lernergebnis(
                thema=thema_name,
                hinweis="In der Datei stand zu wenig Text, um daraus zu lernen.",
            )

        thema = self._speicher.laden(thema_name)
        return await self._einarbeiten(thema, [(str(pfad), text[:ZEICHEN_JE_QUELLE * 2])])

    @staticmethod
    def _datei_lesen(pfad: Path) -> str:
        """Liest Text aus einer Datei – auch aus einem PDF, wenn es geht."""

        endung = pfad.suffix.lower()

        if endung == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore[import-not-found]
            except ImportError:
                try:
                    from PyPDF2 import PdfReader  # type: ignore[import-not-found,no-redef]
                except ImportError as fehler:
                    raise RuntimeError(
                        "Für PDFs fehlt das Paket 'pypdf'. Sag mir "
                        "'Rüste dir das Paket pypdf nach', dann hole ich es."
                    ) from fehler
            leser = PdfReader(str(pfad))
            return "\n".join((seite.extract_text() or "") for seite in leser.pages)

        if endung == ".docx":
            try:
                import docx  # type: ignore[import-not-found]
            except ImportError as fehler:
                raise RuntimeError(
                    "Für Word-Dateien fehlt das Paket 'python-docx'. Sag mir "
                    "'Rüste dir das Paket python-docx nach', dann hole ich es."
                ) from fehler
            dokument = docx.Document(str(pfad))
            return "\n".join(absatz.text for absatz in dokument.paragraphs)

        return pfad.read_text(encoding="utf-8", errors="replace")

    # --- Aus dem Gespräch ----------------------------------------------------------

    def aus_gespraech(self, thema_name: str, aussage: str) -> Lernergebnis:
        """Übernimmt, was der Benutzer selbst erklärt hat.

        Ohne Modell und ohne Prüfung: Was der Benutzer sagt, wird
        aufgeschrieben, wie er es gesagt hat. Es umzuformulieren hiesse,
        seine Genauigkeit gegen die eigene einzutauschen – und er weiss
        über sein Fach mehr als der Orb.
        """

        text = aussage.strip()
        if len(text) < 8:
            return Lernergebnis(thema=thema_name, hinweis="Die Aussage ist zu kurz.")

        thema = self._speicher.laden(thema_name)
        if any(a.text.strip().lower() == text.lower() for a in thema.aussagen):
            return Lernergebnis(
                ok=True, thema=thema_name, hinweis="Das wusste ich schon von dir."
            )

        thema.aussagen.append(
            Aussage(text=text, quelle="Vom Benutzer erklärt", sicherheit="fakt")
        )
        thema.durchgaenge += 1
        self._speicher.speichern(thema)
        self._ins_gedaechtnis(thema.name, [thema.aussagen[-1]])

        return Lernergebnis(
            ok=True,
            thema=thema_name,
            neue_aussagen=1,
            quellen=["Vom Benutzer erklärt"],
            hinweis="Ich habe es mir gemerkt – mit dir als Quelle.",
        )

    # --- Der gemeinsame Kern -------------------------------------------------------

    async def _einarbeiten(
        self, thema: Thema, gelesen: list[tuple[str, str]], *, frage: str = ""
    ) -> Lernergebnis:
        """Destilliert die gelesenen Texte und legt das Ergebnis ab."""

        teile = [f"Thema: {thema.name}"]
        if frage:
            teile.append(f"Besonders interessiert: {frage}")
        if thema.aussagen:
            # Was schon bekannt ist, mitgeben – sonst destilliert das
            # Modell beim Vertiefen dieselben Grundlagen noch einmal, und
            # der Orb tritt auf der Stelle.
            teile.append("\nDas ist bereits bekannt und braucht NICHT wiederholt zu werden:")
            for aussage in thema.aussagen[-12:]:
                teile.append(f"- {aussage.text}")

        teile.append("\nQuellen:")
        for url, text in gelesen:
            teile.append(f"\n--- {url} ---\n{text}")

        try:
            antwort = await self._providers.complete(
                "\n".join(teile), system_prompt=_ANWEISUNG
            )
        except Exception as fehler:  # noqa: BLE001
            return Lernergebnis(
                thema=thema.name, hinweis=f"Das Einarbeiten ist gescheitert: {fehler}"
            )

        daten = _json_aus(antwort)
        if daten is None:
            return Lernergebnis(
                thema=thema.name,
                hinweis=(
                    "Ich habe die Quellen gelesen, konnte daraus aber nichts "
                    "Verwertbares destillieren. Ich habe lieber nichts "
                    "gespeichert als etwas Halbes."
                ),
            )

        neue = self._aussagen_uebernehmen(thema, daten.get("aussagen", []))
        fragen = self._fragen_uebernehmen(thema, daten.get("offene_fragen", []), frage)

        for url, _ in gelesen:
            if url not in thema.gelesen:
                thema.gelesen.append(url)

        thema.durchgaenge += 1
        self._speicher.speichern(thema)
        self._ins_gedaechtnis(thema.name, neue)

        return Lernergebnis(
            ok=True,
            thema=thema.name,
            neue_aussagen=len(neue),
            neue_fragen=fragen,
            quellen=[u for u, _ in gelesen],
            hinweis="",
        )

    def _aussagen_uebernehmen(self, thema: Thema, roh: Any) -> list[Aussage]:
        """Prüft, was das Modell geliefert hat, und übernimmt das Brauchbare."""

        if not isinstance(roh, list):
            return []

        bekannt = {a.text.strip().lower() for a in thema.aussagen}
        neue: list[Aussage] = []

        for eintrag in roh[:MAX_AUSSAGEN]:
            if not isinstance(eintrag, dict):
                continue
            text = str(eintrag.get("text", "")).strip()

            # Zu kurze Aussagen sind fast immer Bruchstücke - „1945" oder
            # „siehe oben". Sie später wieder herauszusuchen kostet mehr,
            # als sie einbringen.
            if len(text) < 20:
                continue
            if text.lower() in bekannt:
                continue

            sicherheit = str(eintrag.get("sicherheit", "wahrscheinlich")).strip().lower()
            if sicherheit not in ("fakt", "wahrscheinlich", "strittig"):
                sicherheit = "wahrscheinlich"

            aussage = Aussage(
                text=text,
                quelle=str(eintrag.get("quelle", "")).strip(),
                sicherheit=sicherheit,
            )
            thema.aussagen.append(aussage)
            neue.append(aussage)
            bekannt.add(text.lower())

        return neue

    @staticmethod
    def _fragen_uebernehmen(thema: Thema, roh: Any, beantwortet: str) -> int:
        """Übernimmt neue offene Fragen und streicht die abgearbeitete."""

        # Die Frage, mit der dieser Durchgang lief, gilt als bearbeitet -
        # ganz gleich, ob sie erschöpfend beantwortet wurde. Bliebe sie
        # stehen, arbeitete der Orb sie immer wieder ab und käme nie zur
        # nächsten.
        if beantwortet:
            thema.offene_fragen = [
                f for f in thema.offene_fragen if f.strip() != beantwortet.strip()
            ]

        if not isinstance(roh, list):
            return 0

        bekannt = {f.strip().lower() for f in thema.offene_fragen}
        gezaehlt = 0
        for eintrag in roh:
            frage = str(eintrag).strip()
            if len(frage) < 10 or frage.lower() in bekannt:
                continue
            thema.offene_fragen.append(frage)
            bekannt.add(frage.lower())
            gezaehlt += 1
            if len(thema.offene_fragen) >= MAX_FRAGEN * 3:
                break

        # Nicht unbegrenzt sammeln: Eine Liste mit hundert offenen Fragen
        # ist keine Arbeitsliste mehr, sondern ein Vorwurf. Die ältesten
        # fallen weg.
        if len(thema.offene_fragen) > MAX_FRAGEN * 3:
            thema.offene_fragen = thema.offene_fragen[-MAX_FRAGEN * 3 :]
        return gezaehlt

    def _ins_gedaechtnis(self, thema: str, aussagen: list[Aussage]) -> None:
        """Legt jede Aussage zusätzlich im Langzeitgedächtnis ab.

        Ohne das wäre das Themenwissen eine zweite, abgeschottete Ablage:
        Der Orb wüsste etwas, käme aber im Gespräch nicht darauf, weil die
        Erinnerungssuche nur das Gedächtnis durchsucht. Gelernt zu haben
        und nichts damit zu tun sieht von aussen wie Gleichgültigkeit aus.
        """

        if self._memory is None:
            return
        for aussage in aussagen:
            try:
                self._memory.remember(
                    f"{thema}: {aussage.text}",
                    kind="knowledge",
                    tags=[thema.lower()],
                    source=aussage.quelle or None,
                    certainty="fakt" if aussage.sicherheit == "fakt" else "wahrscheinlich",
                )
            except Exception:  # noqa: BLE001
                logger.debug("Eine Aussage ließ sich nicht merken.", exc_info=True)

    # --- Auskunft ------------------------------------------------------------------

    def naechste_luecke(self) -> tuple[str, str] | None:
        """Sucht das Thema mit der ältesten offenen Frage.

        Das ist die Grundlage des selbstständigen Weiterarbeitens: Der Orb
        braucht eine Antwort auf „woran arbeite ich als Nächstes", die er
        ohne den Benutzer beantworten kann.

        Genommen wird das am längsten nicht bearbeitete Thema, nicht das
        neueste. Sonst bliebe alles Ältere für immer liegen, sobald ein
        neues Thema hinzukommt.

        Returns:
            Thema und Frage – oder ``None``, wenn nichts offen ist.
        """

        kandidaten = [t for t in self._speicher.alle() if t.offene_fragen]
        if not kandidaten:
            return None
        kandidaten.sort(key=lambda t: t.zuletzt)
        thema = kandidaten[0]
        return thema.name, thema.offene_fragen[0]
