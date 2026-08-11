"""Tests der Historical Professor & Mentor Engine.

Geprueft wird nicht, ob der Professor gut klingt - das kann kein Test.
Geprueft wird, was ihn von einer Antwortmaschine unterscheidet und was
deshalb nicht still kaputtgehen darf:

  - Er verraet die Loesung nicht, wenn eigenes Denken moeglich ist.
  - Er tut es doch, wenn Nachfragen zur Schikane wuerde.
  - Er erinnert sich zwischen zwei Sitzungen.
  - Er passt die Schwierigkeit an.
  - Er erkennt formale Maengel an einer Forschungsfrage gleichbleibend.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.agents.base_agent import AgentTask
from backend.agents.history_agent import professor_engine, research_question_engine
from backend.agents.history_agent import socratic_engine
from backend.agents.history_agent.learning_profile import LearningProfile
from backend.agents.history_agent.mentor_engine import MentorEngine


# ---------------------------------------------------------------------------
#  Die wichtigste Regel: nicht die Loesung liefern
# ---------------------------------------------------------------------------


def test_denkfrage_wird_nicht_beantwortet(tmp_path):
    profil = LearningProfile(tmp_path / "lp.json")
    entscheidung = socratic_engine.decide(
        "Warum begann die Französische Revolution?", profil
    )
    assert entscheidung.ask, "Eine Warum-Frage wurde nicht zurückgespielt."
    assert entscheidung.questions, "Es wurde keine Gegenfrage angeboten."
    assert entscheidung.dimension == "kausalitaet"


def test_faktenfrage_wird_beantwortet(tmp_path):
    """Wer ein Datum nicht weiss, findet es nicht durch Nachdenken."""

    profil = LearningProfile(tmp_path / "lp.json")
    assert not socratic_engine.decide("Wann starb Karl der Große?", profil).ask


def test_nach_zwei_versuchen_wird_geholfen(tmp_path):
    profil = LearningProfile(tmp_path / "lp.json")
    entscheidung = socratic_engine.decide(
        "Warum begann die Französische Revolution?", profil, attempts=2
    )
    assert not entscheidung.ask
    assert "versuch" in entscheidung.reason.lower()


def test_ausdrueckliche_bitte_wird_respektiert(tmp_path):
    profil = LearningProfile(tmp_path / "lp.json")
    assert not socratic_engine.decide("Sag mir einfach die Antwort", profil).ask
    assert not socratic_engine.decide("Ich verstehe es nicht", profil).ask


def test_niveau_bestimmt_die_frage(tmp_path):
    """Eine Frage nach der impliziten Annahme ist fuer Einsteiger eine Mauer."""

    anfaenger = LearningProfile(tmp_path / "a.json")
    fortgeschritten = LearningProfile(tmp_path / "b.json")
    for schluessel in fortgeschritten.competences:
        for _ in range(8):
            fortgeschritten.record_competence(schluessel, 0.95)

    einfach = socratic_engine.pick_questions("argumentation", anfaenger.level)
    schwer = socratic_engine.pick_questions("argumentation", fortgeschritten.level)
    assert einfach != schwer, "Das Niveau wirkt sich nicht auf die Fragen aus."


# ---------------------------------------------------------------------------
#  Gedaechtnis
# ---------------------------------------------------------------------------


def test_profil_ueberlebt_neustart(tmp_path):
    pfad = tmp_path / "lp.json"
    erste = LearningProfile(pfad)
    for _ in range(3):
        erste.record_error("Kausalfehler", "Revolution", "Auslöser mit Ursache verwechselt")
    erste.record_topic("Reformation", 0.4)
    assert erste.save()

    zweite = LearningProfile(pfad)
    assert not zweite.is_new()
    assert zweite.recurring_errors(), "Der wiederkehrende Fehler ging verloren."
    assert "reformation" in zweite.topics


def test_unberuehrte_bereiche_gelten_nicht_als_schwaeche(tmp_path):
    """Ein Vorwurf fuer etwas, das nie verlangt wurde, waere unfair."""

    profil = LearningProfile(tmp_path / "lp.json")
    for _ in range(4):
        profil.record_competence("kausalitaet", 0.2)

    schwaechen = dict(profil.weaknesses())
    assert "kausalitaet" in schwaechen
    assert "historiographie" not in schwaechen, (
        "Ein nie geprüfter Bereich wurde als Schwäche gemeldet."
    )


def test_gut_beherrschtes_wird_seltener_wiederholt(tmp_path):
    profil = LearningProfile(tmp_path / "lp.json")
    schwach = profil.record_topic("Schwierig", 0.0)
    for _ in range(8):
        stark = profil.record_topic("Sitzt", 1.0)

    assert stark.due_at > schwach.due_at, (
        "Sicher Beherrschtes wird nicht seltener wiederholt."
    )


# ---------------------------------------------------------------------------
#  Pruefung
# ---------------------------------------------------------------------------


def test_zu_breite_frage_wird_erkannt():
    urteil = research_question_engine.assess("Warum war die Französische Revolution wichtig?")
    assert not urteil.is_usable
    arten = {mangel.kind for mangel in urteil.flaws}
    assert "unbestimmter Wertbegriff" in arten
    assert "fehlende zeitliche Eingrenzung" in arten


def test_gute_frage_besteht():
    urteil = research_question_engine.assess(
        "Wie veränderte die Französische Revolution die politische Partizipation "
        "in Frankreich zwischen 1789 und 1799?"
    )
    assert urteil.is_usable, [m.kind for m in urteil.flaws]


def test_deskriptive_frage_faellt_durch():
    assert not research_question_engine.assess("Was geschah 1789 in Frankreich?").is_usable


def test_werkstatt_geht_der_reihe_nach():
    gesammelt: dict[str, str] = {}
    schritt = research_question_engine.next_workshop_step(gesammelt)
    assert schritt is not None and schritt[0] == "thema"

    gesammelt["thema"] = "Reformation"
    schritt = research_question_engine.next_workshop_step(gesammelt)
    assert schritt is not None and schritt[0] == "interesse"


# ---------------------------------------------------------------------------
#  Modi und Rollen
# ---------------------------------------------------------------------------


def test_modi_werden_erkannt(tmp_path):
    profil = LearningProfile(tmp_path / "lp.json")
    erwartet = {
        "Ich möchte meine Forschungsfrage verbessern": "forschungsfrage",
        "Analysiere diese Quelle mit mir": "quellenkritik",
        "Schau dir meine Seminararbeit an": "arbeitsbetreuung",
        "Widersprich mir: die Wirtschaft war entscheidend": "debatte",
        "Was soll ich als nächstes lernen?": "lernplan",
    }
    for text, modus in erwartet.items():
        assert professor_engine.build_prompt(text, profile=profil).mode == modus, text


def test_laufender_vorgang_wird_nicht_unterbrochen(tmp_path):
    """Ein Modus, der bei jedem Satz umspringt, ist keiner."""

    profil = LearningProfile(tmp_path / "lp.json")
    modus, _ = professor_engine.detect_mode(
        "Und was war mit den Bauern?", current="quellenkritik"
    )
    assert modus == "quellenkritik"


def test_redlichkeitsregel_steht_immer_im_prompt(tmp_path):
    """Erfundene Archivsignaturen zerstoeren eine wissenschaftliche Arbeit."""

    profil = LearningProfile(tmp_path / "lp.json")
    for text in ("Erklär mir den Wiener Kongress", "Analysiere diese Quelle", "Widersprich mir"):
        prompt = professor_engine.build_prompt(text, profile=profil).system_prompt
        assert "Erfinde niemals" in prompt, text


def test_einsteiger_bekommt_den_tutor(tmp_path):
    profil = LearningProfile(tmp_path / "lp.json")
    assert professor_engine.detect_role("socratic", profil) == "tutor"


# ---------------------------------------------------------------------------
#  Betreuung
# ---------------------------------------------------------------------------


def test_projekt_ueberlebt_neustart(tmp_path):
    mentor = MentorEngine(tmp_path)
    projekt = mentor.create("Seminararbeit Reformation")
    projekt.set("forschungsfrage", "Wie veränderte sich die Frömmigkeit?")
    mentor.save(projekt)

    wieder = MentorEngine(tmp_path).load("Seminararbeit Reformation")
    assert wieder is not None
    assert wieder.fields["forschungsfrage"].startswith("Wie veränderte")


def test_haeufiger_wechsel_der_frage_wird_bemerkt(tmp_path):
    """Dass eine Fragestellung dreimal wechselt, ist selbst ein Befund."""

    mentor = MentorEngine(tmp_path)
    projekt = mentor.create("Arbeit")
    for frage in ("Erste", "Zweite", "Dritte"):
        projekt.set("forschungsfrage", frage)

    assert "geändert" in mentor.context(projekt)


# ---------------------------------------------------------------------------
#  Der Agent als Ganzes
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Ein Sprachmodell, das nur mitschreibt, was man ihm sagt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def chat(self, messages):
        self.prompts.append(messages[0].content)

        class _Antwort:
            text = "Eine Antwort des Professors."
            provider = "fake"
            model = "fake"

        return _Antwort()


def test_agent_reicht_die_sokratische_anweisung_durch(tmp_path, monkeypatch):
    import backend.agents.history_agent.agent as modul

    monkeypatch.setattr(modul, "LearningProfile", lambda: LearningProfile(tmp_path / "lp.json"))
    monkeypatch.setattr(modul, "MentorEngine", lambda: MentorEngine(tmp_path / "projekte"))

    provider = _FakeProvider()
    agent = modul.HistoryProfessorAgent(provider)

    # Ausdruecklich verlangt, nicht bloss gefragt.
    #
    # Frueher genuegte jede Frage ueber 25 Zeichen, um in den sokratischen
    # Modus zu geraten - und weil fast jede ernst gemeinte Frage laenger
    # ist, stellte der Orb dem Benutzer staendig Gegenfragen, statt ihm
    # etwas beizubringen. Sokratisches Lehren ist eine grossartige Methode
    # und ein schlechter Standard: Wer etwas wissen will, will es erklaert
    # bekommen; wer geprueft werden will, sagt das.
    ergebnis = asyncio.run(
        agent.handle(AgentTask(text="Frag mich ab: Warum begann die Französische Revolution?"))
    )

    assert ergebnis.success
    assert provider.prompts, "Es wurde kein Prompt gebaut."
    assert "Lösung NICHT preis" in provider.prompts[0], (
        "Die sokratische Anweisung fehlt im Systemprompt."
    )


def test_agent_haelt_den_laufenden_modus(tmp_path, monkeypatch):
    """Ein Modus, der bei jeder Zwischenfrage umspringt, ist keiner."""

    import backend.agents.history_agent.agent as modul

    monkeypatch.setattr(modul, "LearningProfile", lambda: LearningProfile(tmp_path / "lp.json"))
    monkeypatch.setattr(modul, "MentorEngine", lambda: MentorEngine(tmp_path / "projekte"))

    agent = modul.HistoryProfessorAgent(_FakeProvider())
    asyncio.run(agent.handle(AgentTask(text="Analysiere diese Quelle aus dem Jahr 1789.")))
    assert agent._mode == "quellenkritik"

    asyncio.run(agent.handle(AgentTask(text="Die Bauern waren unzufrieden.")))
    assert agent._mode == "quellenkritik", "Der Vorgang wurde durch eine Antwort beendet."

