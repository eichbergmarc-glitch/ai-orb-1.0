"""Tests von Wissensbasis, Knowledge Graph und Lernen (Phasen 7, 11, 12, 18)."""

from __future__ import annotations

import time

from backend.graph.knowledge_graph import EdgeType, KnowledgeGraph, NodeType
from backend.knowledge.knowledge_base import KnowledgeBase, cosine, term_vector, tokenize
from backend.learning.flashcards import Card, FlashcardDeck, Grade
from backend.learning.preference_learner import PreferenceLearner
from backend.learning.study_plan import StudyPlanner
from backend.research.research_engine import ResearchEngine
from backend.research.source_criticism import SourceCriticism, SourceKind


# --- Wissensbasis ------------------------------------------------------------


def _fresh_knowledge() -> KnowledgeBase:
    base = KnowledgeBase(store_filename=f"knowledge/test-{int(time.time() * 1000)}.json")
    base.clear()
    return base


def test_tokenize_removes_stopwords() -> None:
    tokens = tokenize("Der Kaiser und die Reichsgründung von 1871")
    assert "der" not in tokens
    assert "und" not in tokens
    assert "von" not in tokens
    assert tokens, "Es muss etwas übrig bleiben"


def test_tokenize_matches_across_word_forms() -> None:
    """Einzahl und Mehrzahl müssen sich treffen, sonst findet die Suche nichts."""

    singular = set(tokenize("Die Reichsgründung"))
    plural = set(tokenize("Mehrere Reichsgründungen"))
    assert singular & plural


def test_tokenize_splits_compounds() -> None:
    """Deutsch bildet lange Zusammensetzungen – „Sonderweg" steckt in
    „Sonderwegsthese" und muss dort gefunden werden."""

    query = set(tokenize("Sonderweg"))
    text = set(tokenize("Die Sonderwegsthese ist umstritten"))
    assert query & text


def test_term_vector_is_normalized() -> None:
    """Ohne Normierung läge ein langer Abschnitt bei jeder Suche vorn."""

    short = term_vector(tokenize("Kaiser Reichsgründung"))
    long = term_vector(tokenize("Kaiser Reichsgründung " * 20))

    assert abs(sum(value * value for value in short.values()) - 1.0) < 0.001
    assert abs(sum(value * value for value in long.values()) - 1.0) < 0.001


def test_cosine_similarity_bounds() -> None:
    vector = term_vector(tokenize("Kaiser Reichsgründung Bismarck"))
    assert cosine(vector, vector) > 0.99
    assert cosine(vector, {}) == 0.0
    assert cosine(vector, term_vector(tokenize("Kochrezept Nudeln"))) == 0.0


def test_knowledge_add_and_search() -> None:
    base = _fresh_knowledge()
    text = (
        "Die Reichsgründung von 1871 vollzog sich im Spiegelsaal von Versailles.\n\n"
        "Bismarck hatte den Norddeutschen Bund zuvor als Vorstufe geschaffen.\n\n"
        "Die Sonderwegsthese behauptet ein Abweichen Deutschlands vom westlichen Weg."
    )
    ok, message = base.add_text(text, title="Kaiserreich", citation="Skript S. 12")
    assert ok, message

    findings = base.search("Sonderweg")
    assert findings
    assert "Sonderwegsthese" in findings[0].text
    assert "Skript" in findings[0].reference()

    base.clear()


def test_knowledge_rejects_duplicate_and_short_text() -> None:
    base = _fresh_knowledge()
    text = "Ein hinreichend langer Text ueber die Reichsgruendung von 1871. " * 3

    assert base.add_text(text, title="A")[0]
    assert not base.add_text(text, title="A")[0]
    assert not base.add_text("zu kurz", title="B")[0]

    base.clear()


def test_knowledge_context_carries_citation() -> None:
    """Der Beleg muss die Fundstelle mitbringen, sonst ist er wertlos."""

    base = _fresh_knowledge()
    base.add_text(
        "Die Sonderwegsthese wurde von Wehler vertreten und von Nipperdey bestritten. " * 3,
        title="Debatte",
        citation="Wehler 1973, S. 45",
    )

    context = base.context_for("Sonderweg")
    assert "Wehler 1973" in context
    assert "Fundstelle" in context

    base.clear()


# --- Knowledge Graph -----------------------------------------------------------


def _fresh_graph() -> KnowledgeGraph:
    graph = KnowledgeGraph(store_filename=f"graph/test-{int(time.time() * 1000)}.json")
    graph.clear()
    return graph


def test_graph_connects_and_finds_neighbors() -> None:
    graph = _fresh_graph()
    edge, message = graph.connect(
        "Wehler", "widerspricht", "Nipperdey", source_type="person", target_type="person"
    )
    assert edge is not None, message

    node = graph.find_node("Wehler")
    assert node is not None
    neighbors = graph.neighbors(node.node_id)
    assert len(neighbors) == 1
    assert neighbors[0]["node"]["label"] == "Nipperdey"

    graph.clear()


def test_graph_finds_incoming_edges() -> None:
    """Von der Quelle aus muss man die zitierenden Arbeiten finden."""

    graph = _fresh_graph()
    graph.connect("Aufsatz", "zitiert", "Grundlagenwerk", source_type="artikel", target_type="buch")

    target = graph.find_node("Grundlagenwerk")
    assert target is not None
    neighbors = graph.neighbors(target.node_id)
    assert neighbors[0]["direction"] == "eingehend"
    assert "zitiert von" in neighbors[0]["relation"]

    graph.clear()


def test_graph_merges_duplicate_nodes() -> None:
    """Zweimal dieselbe Person ergibt einen Knoten, nicht zwei."""

    graph = _fresh_graph()
    graph.add_node("Bismarck", NodeType.PERSON)
    graph.add_node("bismarck", NodeType.PERSON)
    assert len(graph) == 1

    graph.clear()


def test_graph_rejects_unknown_types() -> None:
    graph = _fresh_graph()
    node, message = graph.add_node("Etwas", "kaese")
    assert node is None
    assert "Knotenart" in message

    edge, message = graph.connect("Alpha", "verzaubert", "Beta")
    assert edge is None
    assert "Beziehung" in message

    graph.clear()


def test_graph_lists_contradictions() -> None:
    graph = _fresh_graph()
    graph.connect("These A", "widerspricht", "These B", evidence="Kapitel 3")
    graph.connect("These A", "unterstuetzt", "These C")

    contradictions = graph.contradictions()
    assert len(contradictions) == 1
    assert contradictions[0]["evidence"] == "Kapitel 3"

    graph.clear()


def test_graph_traverses_in_breadth() -> None:
    """Nahes kommt vor Fernem."""

    graph = _fresh_graph()
    graph.connect("Kapitel", "gehoert_zu", "Teil")
    graph.connect("Teil", "gehoert_zu", "Buch")
    graph.connect("Buch", "gehoert_zu", "Reihe")

    related = graph.related("Kapitel", depth=3)
    distances = [item["distance"] for item in related]
    assert distances == sorted(distances)

    graph.clear()


def test_graph_removes_node_with_edges() -> None:
    graph = _fresh_graph()
    graph.connect("Aufsatz", "zitiert", "Buch")
    node = graph.find_node("Aufsatz")
    assert node is not None

    ok, _ = graph.remove_node(node.node_id)
    assert ok
    assert len(graph.edges()) == 0

    graph.clear()


def test_graph_exports(tmp_path) -> None:
    graph = _fresh_graph()
    graph.connect("Aufsatz", "zitiert", "Buch")

    target = graph.export(tmp_path / "export.json")
    assert target.exists()
    assert "zitiert" in target.read_text(encoding="utf-8")

    graph.clear()


def test_edge_type_parsing() -> None:
    assert EdgeType.parse("widerspricht") is EdgeType.CONTRADICTS
    assert EdgeType.parse("gehört zu") is EdgeType.BELONGS_TO
    assert EdgeType.parse("unsinn") is None


# --- Karteikarten -------------------------------------------------------------------


def _fresh_deck() -> FlashcardDeck:
    deck = FlashcardDeck(store_filename=f"learning/test-cards-{int(time.time() * 1000)}.json")
    deck.clear()
    return deck


def test_flashcard_interval_grows_when_known() -> None:
    """Was sitzt, wird seltener abgefragt."""

    deck = _fresh_deck()
    card, _ = deck.add("Reichsgründung?", "1871")
    assert card is not None

    intervals = []
    for _ in range(4):
        updated, _ = deck.review(card.card_id, Grade.GOOD)
        assert updated is not None
        intervals.append(updated.interval_days)

    assert intervals == sorted(intervals)
    assert intervals[-1] > intervals[0]

    deck.clear()


def test_flashcard_lapse_resets_streak() -> None:
    """Ein Fehler bringt die Karte am nächsten Tag zurück."""

    deck = _fresh_deck()
    card, _ = deck.add("Frage", "Antwort")
    assert card is not None

    deck.review(card.card_id, Grade.GOOD)
    deck.review(card.card_id, Grade.GOOD)
    updated, _ = deck.review(card.card_id, Grade.AGAIN)

    assert updated is not None
    assert updated.streak == 0
    assert updated.interval_days == 1.0
    assert updated.lapses == 1

    deck.clear()


def test_flashcard_ease_stays_above_minimum() -> None:
    """Auch nach vielen Fehlern bleibt die Karte handhabbar."""

    deck = _fresh_deck()
    card, _ = deck.add("Schwer", "Sehr schwer")
    assert card is not None

    for _ in range(20):
        deck.review(card.card_id, Grade.AGAIN)

    # Nach einem Fehler ist die Karte erst morgen wieder faellig, steht aber
    # weiterhin im Stapel.
    updated = deck.cards()[0]
    assert updated["ease"] >= 1.3

    deck.clear()


def test_flashcard_rejects_duplicates() -> None:
    deck = _fresh_deck()
    assert deck.add("Eine Frage", "A", deck="x")[0] is not None
    assert deck.add("eine frage", "B", deck="x")[0] is None
    # In einem anderen Stapel ist dieselbe Frage erlaubt.
    assert deck.add("Eine Frage", "C", deck="y")[0] is not None

    deck.clear()


def test_flashcard_due_order_prefers_repetitions() -> None:
    """Erst wiederholen, dann Neues aufnehmen."""

    deck = _fresh_deck()
    old, _ = deck.add("Alte Frage", "Antwort A")
    assert old is not None
    deck.add("Neue Frage", "Antwort B")

    # Die alte Karte wurde schon einmal abgefragt und ist ueberfaellig.
    deck.review(old.card_id, Grade.AGAIN)
    stored = deck._cards[old.card_id]  # noqa: SLF001
    stored.due_at = time.time() - 3600.0

    due = deck.due_cards()
    assert due[0].front == "Alte Frage"

    deck.clear()


def test_flashcard_forecast_covers_days() -> None:
    deck = _fresh_deck()
    deck.add("Eine Frage", "Eine Antwort")
    forecast = deck.forecast(days=5)
    assert len(forecast) == 5
    assert forecast[0]["count"] >= 1

    deck.clear()


def test_grade_parsing() -> None:
    assert Grade.parse("nochmal") is Grade.AGAIN
    assert Grade.parse("3") is Grade.EASY
    assert Grade.parse("unsinn") is Grade.GOOD


# --- Lernplan ----------------------------------------------------------------------


def test_study_plan_schedules_hardest_first() -> None:
    planner = StudyPlanner(store_filename=f"learning/test-plans-{int(time.time() * 1000)}.json")

    plan, message = planner.create(
        "Klausur",
        exam_date="31.12.2026",
        hours_per_day=4,
        topics=[
            {"title": "Leicht", "difficulty": 1, "hours": 1},
            {"title": "Schwer", "difficulty": 5, "hours": 2},
        ],
    )
    assert plan is not None, message

    today = planner.today(plan.plan_id)
    assert today[0]["title"] == "Schwer"

    planner.remove(plan.plan_id)


def test_study_plan_detects_impossible_schedule() -> None:
    """Wenn die Zeit nicht reicht, wird das gesagt statt beschönigt."""

    planner = StudyPlanner(store_filename=f"learning/test-tight-{int(time.time() * 1000)}.json")

    plan, _ = planner.create(
        "Zu wenig Zeit",
        exam_date=time.strftime("%d.%m.%Y", time.localtime(time.time() + 2 * 86400)),
        hours_per_day=1,
        topics=[{"title": f"Thema {index}", "hours": 5} for index in range(10)],
    )
    assert plan is not None

    progress = plan.progress()
    assert not progress["feasible"]
    assert "fehlen" in progress["note"]

    planner.remove(plan.plan_id)


def test_study_plan_rejects_past_date() -> None:
    planner = StudyPlanner(store_filename=f"learning/test-past-{int(time.time() * 1000)}.json")
    plan, message = planner.create("Vorbei", exam_date="01.01.2020")
    assert plan is None
    assert "Vergangenheit" in message


def test_study_plan_rejects_bad_date() -> None:
    planner = StudyPlanner(store_filename=f"learning/test-bad-{int(time.time() * 1000)}.json")
    plan, message = planner.create("Unklar", exam_date="irgendwann")
    assert plan is None
    assert "Datum" in message


# --- Vorlieben ------------------------------------------------------------------------


def test_preferences_need_enough_evidence() -> None:
    """Aus einer einzigen Beobachtung folgt nichts."""

    learner = PreferenceLearner(
        store_filename=f"learning/test-prefs-{int(time.time() * 1000)}.json"
    )
    learner.forget()

    learner.observe_interaction(question="Hi", answer="Hallo", via_voice=True)
    assert learner.preferences() == []
    assert learner.guidance() == ""

    for _ in range(15):
        learner.observe_interaction(question="Kurz?", answer="Ja.", via_voice=True)

    preferences = {item.key for item in learner.preferences()}
    assert "eingabeweg" in preferences
    assert "Sprache" in learner.guidance() or "vorgelesen" in learner.guidance()

    learner.forget()


def test_preference_confidence_is_capped() -> None:
    """Auch viele Beobachtungen ergeben keine Gewissheit über einen Menschen."""

    learner = PreferenceLearner(
        store_filename=f"learning/test-cap-{int(time.time() * 1000)}.json"
    )
    learner.forget()

    for _ in range(500):
        learner.observe_interaction(question="Kurz?", answer="Ja.", via_voice=True)

    for preference in learner.preferences():
        assert preference.confidence <= 0.85

    learner.forget()


# --- Forschung --------------------------------------------------------------------------


def test_yes_no_question_is_rejected() -> None:
    result = ResearchEngine().sharpen_question("War Bismarck erfolgreich?")
    assert not result["usable"]
    assert any("Ja oder Nein" in problem for problem in result["problems"])


def test_good_question_passes() -> None:
    result = ResearchEngine().sharpen_question(
        "Inwiefern veränderte die Reichsgründung 1871 die Rolle Preußens in Deutschland?"
    )
    assert result["usable"], result["problems"]


def test_thesis_review_flags_generalisation() -> None:
    review = ResearchEngine().review_thesis(
        "Alle Deutschen unterstützten 1914 den Krieg, weil die Propaganda wirkte."
    )
    assert any("Verallgemeinerungen" in weakness for weakness in review.weaknesses)
    assert review.falsification


def test_argument_check_finds_missing_counterposition() -> None:
    result = ResearchEngine().check_argument(
        "Die Reichsgründung war ein Erfolg. Sie einte die Staaten. Sie schuf einen Markt. "
        "Sie stärkte die Wirtschaft. Sie festigte Preußen. Sie brachte Stabilität. "
        "Sie wirkte lange nach. Sie prägte Europa. Sie veränderte alles."
    )
    assert any("Gegenposition" in note for note in result["notes"])


def test_source_criticism_identifies_primary_source() -> None:
    assessment = SourceCriticism().assess("Ein Feldpostbrief eines Soldaten", year="1916")
    assert assessment.kind is SourceKind.PRIMARY
    assert any("Kriegs" in caveat for caveat in assessment.caveats)


def test_source_criticism_warns_about_encyclopedia() -> None:
    assessment = SourceCriticism().assess("Ein Artikel aus einem Lexikon")
    assert assessment.kind is SourceKind.TERTIARY
    assert any("Beleg" in caveat for caveat in assessment.caveats)


def test_source_criticism_lists_missing_metadata() -> None:
    assessment = SourceCriticism().assess("Irgendein Text")
    assert "Verfasser" in assessment.missing_metadata
    assert assessment.open_questions
