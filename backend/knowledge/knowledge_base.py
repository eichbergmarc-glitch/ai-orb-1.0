"""Wissensbasis mit Quellenangabe (v2 Phase 20).

Eine Ablage für Dokumente, die AI-Orb beim Antworten heranziehen darf –
Vorlesungsskripte, Fachartikel, Normen, eigene Notizen. Der Unterschied zum
Gedächtnis: Hier steht, **woher** etwas stammt.

Das ist der eigentliche Zweck. Die Systemvorgabe verlangt, Fakten von
Annahmen zu trennen und niemals Quellen zu erfinden. Ein Sprachmodell kann
das nicht von sich aus – es weiß nicht, ob ein Satz aus einem Lehrbuch oder
aus seiner eigenen Erfindung stammt. Wenn ein Textabschnitt aber mit einer
Fundstelle geliefert wird, lässt sich die Behauptung nachprüfen.

Die Suche läuft ohne Einbettungsmodell: Ein Dokument wird in Abschnitte
zerlegt, jeder Abschnitt zu einer Worttabelle verdichtet und über die
Kosinusähnlichkeit verglichen. Das ist weniger fein als eine semantische
Suche, dafür sofort einsatzbereit, nachvollziehbar und ohne Download.

Alles liegt lokal. Es wird nichts hochgeladen.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir
from backend.utils.store import JsonStore
from backend.utils.text import stem

logger = get_logger(__name__)

#: Wortgrenzen für die Zerlegung.
_WORD = re.compile(r"[\wäöüßÄÖÜ]{2,}", re.UNICODE)

#: Sehr häufige Wörter, die nichts unterscheiden.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
        "eines", "und", "oder", "aber", "auch", "nicht", "ist", "sind", "war",
        "waren", "sein", "wird", "werden", "wurde", "hat", "haben", "hatte",
        "für", "von", "mit", "auf", "aus", "bei", "nach", "über", "unter", "durch",
        "zum", "zur", "als", "wie", "wenn", "dass", "sich", "man", "kann", "muss",
        "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    }
)

#: Dateitypen, die eingelesen werden können.
#:
#: PDF und Word standen hier lange nicht. Das war kein kleiner Mangel: Die
#: Wissensbasis ist die EINZIGE Ablage mit Quellenangabe - was hier nicht
#: hineinkommt, lässt sich später nicht belegen. Fachliteratur liegt aber
#: praktisch immer als PDF vor. Der Orb konnte also alles zitieren ausser
#: dem, worauf es ankommt.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset(
    {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".pdf", ".docx"}
)


class DokumentFehler(RuntimeError):
    """Der Text einer Datei liess sich nicht herausholen."""


def text_aus_datei(path: Path) -> str:
    """Holt den Text aus einer Datei - auch aus einem PDF oder einem Word-Dokument.

    Die Pakete werden erst hier importiert und nicht oben: Wer nie ein PDF
    einliest, soll ``pypdf`` nicht installieren müssen. Fehlt das Paket,
    steht im Klartext, was zu tun ist - der Orb kann es sich auf Zuruf
    selbst nachrüsten.

    Raises:
        DokumentFehler: Wenn das nötige Paket fehlt oder die Datei sich
            nicht auswerten lässt.
    """

    endung = path.suffix.lower()

    if endung == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore[import-not-found,no-redef]
            except ImportError as fehler:
                raise DokumentFehler(
                    "Für PDFs fehlt das Paket 'pypdf'. Sag mir "
                    "'Rüste dir das Paket pypdf nach', dann hole ich es."
                ) from fehler
        try:
            leser = PdfReader(str(path))
            return "\n\n".join((seite.extract_text() or "") for seite in leser.pages)
        except Exception as fehler:  # noqa: BLE001 - ein kaputtes PDF ist kein Absturz.
            raise DokumentFehler(
                f"Das PDF liess sich nicht auswerten: {fehler}"
            ) from fehler

    if endung == ".docx":
        try:
            import docx  # type: ignore[import-not-found]
        except ImportError as fehler:
            raise DokumentFehler(
                "Für Word-Dateien fehlt das Paket 'python-docx'. Sag mir "
                "'Rüste dir das Paket python-docx nach', dann hole ich es."
            ) from fehler
        try:
            dokument = docx.Document(str(path))
            return "\n\n".join(absatz.text for absatz in dokument.paragraphs)
        except Exception as fehler:  # noqa: BLE001
            raise DokumentFehler(
                f"Das Word-Dokument liess sich nicht auswerten: {fehler}"
            ) from fehler

    return path.read_text(encoding="utf-8", errors="replace")


@dataclass
class Passage:
    """Ein Abschnitt eines Dokuments."""

    document_id: str
    index: int
    text: str
    #: Worthäufigkeiten, für den Vergleich.
    terms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"document_id": self.document_id, "index": self.index, "text": self.text}


@dataclass
class Document:
    """Ein Dokument in der Wissensbasis."""

    document_id: str
    title: str
    source: str
    added_at: float = field(default_factory=time.time)
    passage_count: int = 0
    character_count: int = 0
    #: Freie Angaben: Autor, Jahr, Fundstelle.
    citation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source": self.source,
            "citation": self.citation,
            "added_at": self.added_at,
            "passage_count": self.passage_count,
            "character_count": self.character_count,
        }


@dataclass
class Finding:
    """Ein Fund mit Fundstelle."""

    text: str
    score: float
    title: str
    citation: str
    source: str
    passage_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "score": round(self.score, 4),
            "title": self.title,
            "citation": self.citation,
            "source": self.source,
            "passage_index": self.passage_index,
        }

    def reference(self) -> str:
        """Die Fundstelle als Text, wie sie zitiert wird."""

        if self.citation:
            return f"{self.citation} (Abschnitt {self.passage_index + 1})"
        return f"{self.title}, Abschnitt {self.passage_index + 1}"


def tokenize(text: str) -> list[str]:
    """Zerlegt Text in vergleichbare Wörter.

    Zwei Schritte über das reine Zerlegen hinaus sind nötig, damit die Suche
    im Deutschen überhaupt trifft.

    Erstens die **Stammform**: Wer „Reichsgründung" sucht, meint auch
    „Reichsgründungen". Ohne Suffixreduktion wären das zwei verschiedene
    Wörter.

    Zweitens die **Zerlegung von Zusammensetzungen**: Deutsch bildet lange
    Komposita, und „Sonderweg" steckt in „Sonderwegsthese", ohne dass ein
    Wortvergleich das je fände. Deshalb wird ein langes Wort zusätzlich in
    seine Anfangsstücke zerlegt. Das ist grob – eine richtige
    Kompositazerlegung bräuchte ein Wörterbuch –, holt aber genau die
    Treffer, die sonst fehlen.
    """

    tokens: list[str] = []

    for match in _WORD.finditer(text):
        word = match.group(0).lower()
        if word in _STOPWORDS:
            continue

        stemmed = stem(word)
        tokens.append(stemmed)

        # Zusammensetzungen: Anfangsstücke ab sechs Zeichen mitaufnehmen,
        # damit "Sonderwegsthese" auch unter "Sonderweg" gefunden wird.
        if len(word) >= 11:
            for cut in (len(word) - 4, len(word) - 5, len(word) - 6):
                if cut >= 6:
                    prefix = word[:cut].rstrip("s")
                    if len(prefix) >= 6 and prefix not in tokens:
                        tokens.append(prefix)

    return tokens


def term_vector(tokens: list[str]) -> dict[str, float]:
    """Baut eine auf die Länge normierte Worttabelle.

    Die Normierung ist wichtig: Ohne sie hätte ein langer Abschnitt allein
    durch seine Länge höhere Werte und würde bei jeder Suche vorn liegen.
    """

    if not tokens:
        return {}

    counts: dict[str, float] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0.0) + 1.0

    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0.0:
        return {}
    return {term: value / norm for term, value in counts.items()}


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    """Ähnlichkeit zweier Worttabellen zwischen 0.0 und 1.0."""

    if not left or not right:
        return 0.0
    # Über die kürzere Tabelle laufen – das spart bei großen Dokumenten Zeit.
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


class KnowledgeBase:
    """Verwaltet Dokumente und durchsucht sie mit Quellenangabe."""

    def __init__(self, *, store_filename: str = "knowledge/index.json") -> None:
        config = get_config()

        self._enabled = bool(config.get("knowledge.enabled", True))
        self._passage_characters = int(config.get("knowledge.passage_characters", 900))
        self._max_document_mb = float(config.get("knowledge.max_document_mb", 10.0))
        self._minimum_score = float(config.get("knowledge.minimum_score", 0.06))

        self._directory = get_data_dir() / "knowledge"
        self._directory.mkdir(parents=True, exist_ok=True)

        self._store = JsonStore(store_filename, default={"documents": {}, "passages": []})
        self._documents: dict[str, Document] = {}
        self._passages: list[Passage] = []
        self._load()

    # --- Laden und Speichern -------------------------------------------------------

    def _load(self) -> None:
        """Liest den Index von der Festplatte."""

        for raw in (self._store.get("documents", {}) or {}).values():
            document = Document(
                document_id=str(raw.get("document_id", "")),
                title=str(raw.get("title", "")),
                source=str(raw.get("source", "")),
                citation=str(raw.get("citation", "")),
                added_at=float(raw.get("added_at", 0.0)),
                passage_count=int(raw.get("passage_count", 0)),
                character_count=int(raw.get("character_count", 0)),
            )
            if document.document_id:
                self._documents[document.document_id] = document

        for raw in self._store.get("passages", []) or []:
            text = str(raw.get("text", ""))
            self._passages.append(
                Passage(
                    document_id=str(raw.get("document_id", "")),
                    index=int(raw.get("index", 0)),
                    text=text,
                    terms=term_vector(tokenize(text)),
                )
            )

        if self._documents:
            logger.info(
                "Wissensbasis geladen: %d Dokumente, %d Abschnitte.",
                len(self._documents),
                len(self._passages),
            )

    def _save(self) -> None:
        """Schreibt den Index auf die Festplatte.

        Die Worttabellen werden nicht mitgespeichert – sie lassen sich beim
        Laden in Millisekunden neu berechnen und würden die Datei um ein
        Vielfaches aufblähen.
        """

        self._store.update(
            {
                "documents": {
                    document_id: document.to_dict()
                    for document_id, document in self._documents.items()
                },
                "passages": [passage.to_dict() for passage in self._passages],
            }
        )

    # --- Aufnehmen ------------------------------------------------------------------

    def add_text(
        self,
        text: str,
        *,
        title: str,
        source: str = "",
        citation: str = "",
    ) -> tuple[bool, str]:
        """Nimmt einen Text in die Wissensbasis auf.

        Args:
            text: Der Inhalt.
            title: Wie das Dokument heißt.
            source: Woher es stammt – Pfad oder Adresse.
            citation: Die Fundstelle, wie sie zitiert werden soll.

        Returns:
            Erfolg und eine Meldung im Klartext.
        """

        if not self._enabled:
            return False, "Die Wissensbasis ist in config.yaml ausgeschaltet."

        cleaned = text.strip()
        if len(cleaned) < 50:
            return False, "Der Text ist zu kurz, um daraus etwas nachschlagen zu können."

        document_id = hashlib.sha256((title + source + cleaned[:500]).encode("utf-8")).hexdigest()[:16]

        if document_id in self._documents:
            return False, f"'{title}' ist bereits in der Wissensbasis."

        passages = self._split(cleaned)
        if not passages:
            return False, "Aus dem Text ließen sich keine Abschnitte bilden."

        document = Document(
            document_id=document_id,
            title=title.strip() or "Ohne Titel",
            source=source.strip(),
            citation=citation.strip() or title.strip(),
            passage_count=len(passages),
            character_count=len(cleaned),
        )

        self._documents[document_id] = document
        for index, passage_text in enumerate(passages):
            self._passages.append(
                Passage(
                    document_id=document_id,
                    index=index,
                    text=passage_text,
                    terms=term_vector(tokenize(passage_text)),
                )
            )

        self._save()
        logger.info("Aufgenommen: '%s' (%d Abschnitte).", document.title, len(passages))
        return True, f"'{document.title}' aufgenommen, {len(passages)} Abschnitte."

    def add_file(self, path: Path, *, citation: str = "") -> tuple[bool, str]:
        """Nimmt eine Textdatei auf.

        Die Prüfung, ob der Pfad freigegeben ist, geschieht **vorher** durch
        die aufrufende Stelle. Dieses Modul kennt die Sicherheitsschicht
        nicht – es soll auch unabhängig davon prüfbar sein.
        """

        if not path.is_file():
            return False, f"Die Datei gibt es nicht: {path}"

        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return False, (
                f"Dateien vom Typ '{path.suffix}' können nicht eingelesen werden. "
                "Möglich sind: " + ", ".join(sorted(SUPPORTED_SUFFIXES))
            )

        try:
            size_mb = path.stat().st_size / 1024 / 1024
            if size_mb > self._max_document_mb:
                return False, (
                    f"Die Datei ist mit {size_mb:.1f} MB größer als die erlaubten "
                    f"{self._max_document_mb:.0f} MB."
                )
            text = text_aus_datei(path)
        except DokumentFehler as fehler:
            return False, str(fehler)
        except OSError as error:
            return False, f"Die Datei ließ sich nicht lesen: {error}"

        # Ein PDF, aus dem nichts herauskommt, ist fast immer ein
        # eingescanntes: Bilder statt Text. Das ist kein Fehler des Orb,
        # aber der Benutzer soll erfahren, woran es liegt.
        if not text.strip():
            return False, (
                f"Aus '{path.name}' liess sich kein Text herausholen. Bei "
                "einem PDF heisst das meistens: Es ist eingescannt und "
                "enthält Bilder statt Text."
            )

        return self.add_text(
            text, title=path.stem, source=str(path), citation=citation or path.name
        )

    def _split(self, text: str) -> list[str]:
        """Zerlegt einen Text in Abschnitte.

        Zerlegt wird an Absätzen, nicht an einer festen Zeichenzahl. Ein
        Abschnitt, der mitten im Satz endet, wäre als Beleg unbrauchbar.
        """

        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        passages: list[str] = []
        current = ""

        for paragraph in paragraphs:
            if len(paragraph) > self._passage_characters:
                if current:
                    passages.append(current)
                    current = ""
                # Ein sehr langer Absatz wird an Satzgrenzen geteilt.
                sentence_buffer = ""
                for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
                    if len(sentence_buffer) + len(sentence) + 1 <= self._passage_characters:
                        sentence_buffer = f"{sentence_buffer} {sentence}".strip()
                    else:
                        if sentence_buffer:
                            passages.append(sentence_buffer)
                        sentence_buffer = sentence[: self._passage_characters]
                if sentence_buffer:
                    passages.append(sentence_buffer)
                continue

            if len(current) + len(paragraph) + 2 <= self._passage_characters:
                current = f"{current}\n\n{paragraph}".strip()
            else:
                if current:
                    passages.append(current)
                current = paragraph

        if current:
            passages.append(current)
        return passages

    # --- Suchen --------------------------------------------------------------------------

    def search(self, query: str, *, limit: int = 5) -> list[Finding]:
        """Sucht Abschnitte zu einer Frage.

        Returns:
            Die Funde mit Fundstelle, nach Güte sortiert.
        """

        if not self._enabled or not self._passages:
            return []

        query_terms = term_vector(tokenize(query))
        if not query_terms:
            return []

        scored: list[tuple[float, Passage]] = []
        for passage in self._passages:
            score = cosine(query_terms, passage.terms)
            if score >= self._minimum_score:
                scored.append((score, passage))

        scored.sort(key=lambda item: item[0], reverse=True)

        findings: list[Finding] = []
        for score, passage in scored[:limit]:
            document = self._documents.get(passage.document_id)
            findings.append(
                Finding(
                    text=passage.text,
                    score=score,
                    title=document.title if document else "Unbekannt",
                    citation=document.citation if document else "",
                    source=document.source if document else "",
                    passage_index=passage.index,
                )
            )
        return findings

    def context_for(self, query: str, *, limit: int = 3, max_characters: int = 3000) -> str:
        """Stellt Belegtext für eine Modellanfrage zusammen.

        Der Text ist so aufgebaut, dass das Modell die Fundstelle mitgeben
        kann – und dass ersichtlich bleibt, was Beleg ist und was nicht.
        """

        findings = self.search(query, limit=limit)
        if not findings:
            return ""

        parts: list[str] = [
            "Belege aus der Wissensbasis. Stütze deine Antwort darauf und nenne "
            "die Fundstelle. Was hier nicht steht, ist kein Beleg – sage es "
            "ausdrücklich, wenn du darüber hinausgehst.",
            "",
        ]

        used = 0
        for finding in findings:
            text = finding.text
            if used + len(text) > max_characters:
                text = text[: max(200, max_characters - used)] + " …"
            parts.append(f"[{finding.reference()}]\n{text}")
            used += len(text)
            if used >= max_characters:
                break

        return "\n\n".join(parts)

    # --- Verwalten ---------------------------------------------------------------------------

    def documents(self) -> list[dict[str, Any]]:
        """Alle Dokumente."""

        return [
            document.to_dict()
            for document in sorted(
                self._documents.values(), key=lambda item: item.added_at, reverse=True
            )
        ]

    def remove(self, document_id: str) -> tuple[bool, str]:
        """Entfernt ein Dokument samt seiner Abschnitte."""

        document = self._documents.pop(document_id, None)
        if document is None:
            return False, f"Ein Dokument mit der Kennung '{document_id}' gibt es nicht."

        before = len(self._passages)
        self._passages = [
            passage for passage in self._passages if passage.document_id != document_id
        ]
        self._save()

        return True, (
            f"'{document.title}' entfernt ({before - len(self._passages)} Abschnitte)."
        )

    def clear(self) -> int:
        """Leert die Wissensbasis vollständig."""

        count = len(self._documents)
        self._documents.clear()
        self._passages.clear()
        self._save()
        logger.info("Die Wissensbasis wurde geleert (%d Dokumente).", count)
        return count

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "enabled": self._enabled,
            "documents": len(self._documents),
            "passages": len(self._passages),
            "characters": sum(item.character_count for item in self._documents.values()),
            "directory": str(self._directory),
            "supported_types": sorted(SUPPORTED_SUFFIXES),
        }
