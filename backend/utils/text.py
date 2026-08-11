"""Textverarbeitung ohne externe Abhängigkeiten.

AI-Orb soll auch vollständig offline und ohne installierte
Embedding-Modelle nutzbar sein. Dieses Modul stellt daher eine leichte,
rein lokale Grundlage für Ähnlichkeitssuche bereit: Tokenisierung mit
deutscher und englischer Stoppwortliste, Wortstamm-Näherung und
Kosinus-Ähnlichkeit über TF-Gewichte.

Die Memory Engine (:mod:`backend.memory.memory_search`) nutzt diese
Funktionen als Standardverfahren. Sind später echte lokale Embeddings
verfügbar, kann die Suche dort ergänzt werden, ohne dieses Modul zu ändern.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

_TOKEN_PATTERN = re.compile(r"[a-zäöüß0-9]+", re.IGNORECASE)

# Bewusst kompakte Stoppwortliste (Deutsch + Englisch). Sie filtert die
# häufigsten Funktionswörter heraus, ohne inhaltstragende Begriffe zu
# entfernen.
_STOPWORDS: frozenset[str] = frozenset(
    """
    der die das den dem des ein eine einer eines einem einen und oder aber
    doch denn weil dass ob wenn als wie wo wer was warum wieso ich du er sie
    es wir ihr mich dich sich uns euch mein dein sein ihr unser euer nicht
    kein keine nur auch schon noch mal sehr mehr viel wenig hier dort da
    ist sind war waren bin bist sein hat haben hatte hatten wird werden
    wurde wurden kann können konnte könnte soll sollen muss müssen darf
    dürfen mag mögen für von mit bei nach aus vor über unter zwischen durch
    gegen ohne um an auf in im am zum zur ins beim vom des dessen deren
    the a an and or but if then than that this these those is are was were
    be been being have has had do does did will would can could should may
    might must of to in on at for with from by about as into over under
    it its he she they we you i me my your his her their our not no yes
    """.split()
)

# Sehr einfache Suffix-Reduktion für deutsche und englische Wortformen.
# Kein vollwertiger Stemmer, aber ausreichend, damit "Projekte" und
# "Projekt" oder "Quellen" und "Quelle" als verwandt erkannt werden.
_SUFFIXES: tuple[str, ...] = (
    "ungen",
    "lich",
    "isch",
    "heit",
    "keit",
    "ende",
    "ung",
    "ern",
    "est",
    "end",
    "ing",
    "ies",
    "em",
    "en",
    "er",
    "es",
    "et",
    "st",
    "ns",
    "n",
    "s",
    "e",
)


def normalize(text: str) -> str:
    """Normalisiert Text: Kleinschreibung und einheitliche Unicode-Form."""

    return unicodedata.normalize("NFC", text).strip().lower()


def stem(word: str) -> str:
    """Reduziert ein Wort näherungsweise auf seinen Stamm.

    Es wird höchstens ein Suffix entfernt und niemals unter eine Restlänge
    von vier Zeichen gekürzt, damit kurze Fachbegriffe erhalten bleiben.
    """

    for suffix in _SUFFIXES:
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokenize(text: str, *, remove_stopwords: bool = True, apply_stemming: bool = True) -> list[str]:
    """Zerlegt Text in normalisierte Tokens.

    Args:
        text: Eingabetext.
        remove_stopwords: Entfernt häufige Funktionswörter.
        apply_stemming: Wendet die Suffix-Reduktion aus :func:`stem` an.

    Returns:
        Liste der Tokens in Vorkommensreihenfolge.
    """

    tokens = [match.group(0).lower() for match in _TOKEN_PATTERN.finditer(normalize(text))]
    if remove_stopwords:
        tokens = [token for token in tokens if token not in _STOPWORDS]
    if apply_stemming:
        tokens = [stem(token) for token in tokens]
    return [token for token in tokens if len(token) > 1]


def term_frequencies(text: str) -> Counter[str]:
    """Berechnet die Termhäufigkeiten eines Texts."""

    return Counter(tokenize(text))


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Berechnet die Kosinus-Ähnlichkeit zweier Texte (0.0 bis 1.0).

    Grundlage sind die Termhäufigkeiten der tokenisierten Texte. Leere
    Texte ergeben 0.0.
    """

    vec_a = term_frequencies(text_a)
    vec_b = term_frequencies(text_b)
    if not vec_a or not vec_b:
        return 0.0

    shared = set(vec_a) & set(vec_b)
    if not shared:
        return 0.0

    dot = sum(vec_a[token] * vec_b[token] for token in shared)
    norm_a = math.sqrt(sum(value * value for value in vec_a.values()))
    norm_b = math.sqrt(sum(value * value for value in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def keyword_overlap(text: str, keywords: list[str]) -> float:
    """Anteil der Schlüsselwörter, die im Text vorkommen (0.0 bis 1.0)."""

    if not keywords:
        return 0.0
    tokens = set(tokenize(text))
    hits = sum(1 for keyword in keywords if stem(keyword.lower()) in tokens)
    return hits / len(keywords)


def summarize(text: str, max_sentences: int = 3) -> str:
    """Erzeugt eine extraktive Kurzfassung ohne Sprachmodell.

    Es werden die Sätze mit der höchsten Termgewichtung ausgewählt und in
    ihrer ursprünglichen Reihenfolge zusammengesetzt. Das Verfahren ist
    bewusst deterministisch und offline nutzbar; die Memory Engine setzt es
    ein, wenn kein Sprachmodell für eine Zusammenfassung verfügbar ist.
    """

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if len(sentences) <= max_sentences:
        return text.strip()

    frequencies = term_frequencies(text)
    scored: list[tuple[int, float]] = []
    for index, sentence in enumerate(sentences):
        tokens = tokenize(sentence)
        if not tokens:
            scored.append((index, 0.0))
            continue
        score = sum(frequencies[token] for token in tokens) / math.sqrt(len(tokens))
        scored.append((index, score))

    best_indices = sorted(
        sorted(scored, key=lambda item: item[1], reverse=True)[:max_sentences],
        key=lambda item: item[0],
    )
    return " ".join(sentences[index] for index, _ in best_indices)


def truncate(text: str, max_chars: int) -> str:
    """Kürzt Text auf ``max_chars`` Zeichen und ergänzt eine Ellipse."""

    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"
