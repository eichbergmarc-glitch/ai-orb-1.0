"""Der Vorlesungsmodus muss technisch fortsetzen, nicht nur davon reden."""

from __future__ import annotations

import json
import asyncio

from backend.studium.vorlesungs_session import (
    VORLESUNGS_MARKER,
    VorlesungsSession,
    ist_vorlesungssegment,
    lehrstoff_vervollstaendigen,
)
from backend.cognitive.orchestrator import CognitiveOrchestrator
from backend.cognitive.cognitive_core import kognitiver_prueftext
from backend.orchestrator.intent_classifier import IntentClassifier, IntentResult, QUESTION
from backend.orchestrator.intent_classifier import APP_CLOSE
from backend.orchestrator.task_router import TaskRouter
from backend.reasoning.task_analyzer import TaskAnalyzer
from backend.voice.voice_pipeline import VoicePipeline


def test_vorlesung_startet_als_persistente_sitzung(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)

    assert session.befehl("Halte mir eine Vorlesung über Mesopotamien") == "start"
    auftrag = session.starten("Halte mir eine Vorlesung über Mesopotamien")

    assert session.aktiv
    assert ist_vorlesungssegment(auftrag)
    assert auftrag.startswith(VORLESUNGS_MARKER)
    assert "Abschnitt 1 von hoechstens 5" in auftrag
    assert "Frage NICHT" in auftrag
    assert "alle Punkte vollstaendig" in auftrag


def test_abgeschnittene_vier_ursachen_werden_vollstaendig_abgeschlossen():
    antwort = (
        "Aristoteles unterscheidet vier Ursachen. Die Materialursache ist der "
        "Stoff. Die Formursache ist die Gestalt. Die Wirkursache ist der "
        "Bildhauer."
    )

    vollstaendig = lehrstoff_vervollstaendigen(antwort)

    assert vollstaendig.startswith(antwort)
    assert "Zweck- oder Zielursache" in vollstaendig
    assert "Telos" in vollstaendig


def test_vollstaendige_vier_ursachen_werden_nicht_doppelt_ergaenzt():
    antwort = (
        "Die vier Ursachen sind Materialursache, Formursache, Wirkursache "
        "und Zweckursache."
    )

    assert lehrstoff_vervollstaendigen(antwort) == antwort


def test_whisper_varianten_starten_die_vorlesung(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)

    assert session.befehl(
        "Halte mir eine Einführungsvorlässung über Geschichtswissenschaft"
    ) == "start"
    assert session.befehl(
        "Ich möchte, dass die Vorleistung selbstständig gestaltet ist"
    ) == "start"


def test_erwaehnte_faehigkeit_startet_keine_vorlesung(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)

    assert session.befehl(
        "Der Orb kann mittlerweile ganze Vorlesungen abhalten und Bilder zeigen."
    ) == ""


def test_fortsetzen_mit_neuem_explizitem_thema_startet_neue_vorlesung(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    session.starten("Halte eine Vorlesung über Wirtschaftsgeschichte")
    session.pausieren()

    befehl = "Fahre fort mit der Einführungsvorlesung in Philosophie."

    assert session.befehl(befehl) == "start"
    auftrag = session.starten(befehl)
    assert session.stand.thema == "philosophie"
    assert "Abschnitt 1" in auftrag


def test_erfolgreicher_abschnitt_plant_den_naechsten(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    session.starten("Halte eine Vorlesung zur frühen Menschheitsgeschichte")

    session.abschnitt_beendet("Die ersten Siedlungen entstanden schrittweise.")
    folge = session.naechster_auftrag()

    assert session.aktiv
    assert "Abschnitt 2 von hoechstens 5" in folge
    assert "ersten Siedlungen" in folge


def test_interner_abschnitt_wird_nicht_in_desktop_teilaufgaben_zerlegt(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    auftrag = session.starten("Halte eine Vorlesung über Sprachwissenschaft")
    verteiler = CognitiveOrchestrator(IntentClassifier())
    intent = IntentResult(QUESTION, "hoch", 1.0, True)

    verteilung = verteiler.distribute(auftrag, intent)

    assert verteilung.engines == ["conversation"]
    assert len(verteilung.subtasks) == 1
    assert verteilung.subtasks[0].text == auftrag


def test_interner_abschnitt_gelangt_nicht_als_riskante_aktion_in_die_pruefung(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    auftrag = session.starten("Halte eine Vorlesung über Geschichtswissenschaft")

    prueftext = kognitiver_prueftext(auftrag)

    assert prueftext == "Inhaltliche Fortsetzung einer laufenden gesprochenen Vorlesung."
    assert "beende" not in prueftext.casefold()
    assert "ausfuehren" not in prueftext.casefold()
    profil = TaskAnalyzer().analyze(
        prueftext, IntentResult(QUESTION, "hoch", 1.0, True)
    )
    assert profil.risk == "gering"
    assert "desktop" not in profil.required_modules


def test_task_router_fuehrt_markierte_vorlesung_nie_als_programmaktion_aus(tmp_path):
    async def _lauf():
        session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
        auftrag = session.starten("Halte eine Vorlesung über Geschichtswissenschaft")
        # Genau die Fehlklassifikation aus dem Laufzeitprotokoll simulieren.
        falsches_intent = IntentResult(APP_CLOSE, "hoch", 1.0, False)
        return await TaskRouter().route(auftrag, falsches_intent)

    route = asyncio.run(_lauf())

    assert not route.handled_locally
    assert route.requires_llm
    assert route.module == "ai_provider"
    assert "Programm" not in route.response


def test_vorlesungsweg_schliesst_modellwerkzeugschleife_explizit_aus() -> None:
    quelle = __import__(
        "backend.orchestrator.orchestrator", fromlist=["Orchestrator"]
    )
    text = __import__("inspect").getsource(quelle.Orchestrator._answer_with_model)

    assert "and not vorlesungssegment" in text


def test_sicherheitsrueckfrage_stoppt_automatische_vorlesung(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    session.starten("Halte eine Vorlesung über Sprachwissenschaft")

    session.abschnitt_beendet(
        "Diese Aktion kann nicht rückgängig gemacht werden. "
        "Soll ich sie wirklich ausführen?"
    )

    assert not session.aktiv
    assert session.stand.pausiert
    assert session.stand.naechster_abschnitt == 1


def test_programm_router_antwort_wird_nicht_als_lehrstoff_gespeichert(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    session.starten("Halte eine Vorlesung über Geschichtswissenschaft")

    session.abschnitt_beendet(
        "Ich habe nicht erkannt, welches Programm beendet werden soll."
    )

    assert not session.aktiv
    assert session.stand.naechster_abschnitt == 1
    assert session.stand.letzter_auszug == ""


def test_tagebuchwerkzeug_antwort_wird_nicht_als_lehrstoff_gespeichert(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    session.starten("Halte eine Vorlesung über Geschichtswissenschaft")

    session.abschnitt_beendet("Das Tagebuch ist aufgeschlagen (2 Eintraege).")

    assert not session.aktiv
    assert session.stand.naechster_abschnitt == 1
    assert session.stand.letzter_auszug == ""


def test_alter_beschaedigter_vorlesungsstand_wird_beim_laden_repariert(tmp_path):
    path = tmp_path / "vorlesung.json"
    path.write_text(
        json.dumps(
            {
                "auftrag": "Vorlesung Geschichtswissenschaft",
                "thema": "Geschichtswissenschaft",
                "naechster_abschnitt": 2,
                "aktiv": True,
                "pausiert": False,
                "letzter_auszug": (
                    "Ich habe nicht erkannt, welches Programm beendet werden soll."
                ),
            }
        ),
        encoding="utf-8",
    )

    session = VorlesungsSession(path, max_abschnitte=5)

    assert not session.aktiv
    assert session.stand.pausiert
    assert session.stand.naechster_abschnitt == 1
    assert session.stand.letzter_auszug == ""
    repariert = json.loads(path.read_text(encoding="utf-8"))
    assert repariert["naechster_abschnitt"] == 1
    assert repariert["letzter_auszug"] == ""


def test_alter_tagebuch_auszug_wird_beim_laden_repariert(tmp_path):
    path = tmp_path / "vorlesung.json"
    path.write_text(
        json.dumps(
            {
                "auftrag": "Vorlesung Geschichtswissenschaft",
                "thema": "Geschichtswissenschaft",
                "naechster_abschnitt": 3,
                "aktiv": False,
                "pausiert": True,
                "letzter_auszug": "Das Tagebuch ist aufgeschlagen (2 Eintraege).",
            }
        ),
        encoding="utf-8",
    )

    session = VorlesungsSession(path, max_abschnitte=5)

    assert session.stand.naechster_abschnitt == 2
    assert session.stand.letzter_auszug == ""


def test_stop_pausiert_und_fahre_fort_setzt_am_selben_stand_fort(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    session.starten("Halte eine Vorlesung über die Antike")
    session.abschnitt_beendet("Der erste Teil ist beendet.")

    assert session.befehl("Stopp") == "pausieren"
    session.pausieren()
    assert not session.aktiv
    assert session.befehl("Fahre mit der Vorlesung fort") == "fortsetzen"

    folge = session.fortsetzen()
    assert session.aktiv
    assert "Abschnitt 2 von hoechstens 5" in folge


def test_freie_fortsetzungsform_und_zwischenfrage_lassen_sitzung_aktiv(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=5)
    session.starten("Halte eine Vorlesung über die Antike")

    assert session.befehl("Fahre von hier aus fort mit der Jungsteinzeit") == "fortsetzen"
    session.benutzer_unterbricht()

    assert session.aktiv


def test_neustart_redet_nicht_ungefragt_weiter_kennt_aber_den_stand(tmp_path):
    path = tmp_path / "vorlesung.json"
    erste = VorlesungsSession(path, max_abschnitte=5)
    erste.starten("Halte eine Vorlesung über Rom")
    erste.abschnitt_beendet("Rom entwickelte sich von einer Siedlung zur Stadt.")

    zweite = VorlesungsSession(path, max_abschnitte=5)
    assert not zweite.aktiv
    assert zweite.stand.pausiert
    assert zweite.stand.naechster_abschnitt == 2
    assert "Rom entwickelte" in zweite.fortsetzen()


def test_letzter_abschnitt_schliesst_die_sitzung(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=2)
    session.starten("Halte eine Vorlesung über Quellenkritik")
    session.abschnitt_beendet("Erster Teil.")
    assert "letzte geplante Abschnitt" in session.naechster_auftrag()

    session.abschnitt_beendet("Damit ist diese Vorlesung abgeschlossen.")
    assert not session.aktiv
    assert session.stand.abgeschlossen

    gespeichert = json.loads(session.path.read_text(encoding="utf-8"))
    assert gespeichert["abgeschlossen"] is True


def _pipeline_fuer_timer(session):
    pipeline = VoicePipeline.__new__(VoicePipeline)
    pipeline._vorlesung = session
    pipeline._vorlesung_pause = 0.01
    pipeline._vorlesung_task = None
    pipeline._processing = False
    pipeline._turn_claimed = False
    pipeline._antwort_task = None
    pipeline._state = type("State", (), {})()  # weder thinking noch speaking
    pipeline._loop = None
    pipeline._neue_rede = lambda: None
    return pipeline


def test_timer_ruft_den_naechsten_abschnitt_tatsaechlich_auf(tmp_path):
    async def _lauf():
        session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=3)
        session.starten("Halte eine Vorlesung über die Antike")
        pipeline = _pipeline_fuer_timer(session)
        pipeline._loop = asyncio.get_running_loop()
        aufgerufen = []

        async def _antwort(text, turn, *, vorlesungszug=False):
            aufgerufen.append((text, vorlesungszug))

        pipeline._respond = _antwort
        pipeline._vorlesung_fortsetzung_planen()
        await asyncio.sleep(0.04)
        return aufgerufen

    aufgerufen = asyncio.run(_lauf())
    assert len(aufgerufen) == 1
    assert ist_vorlesungssegment(aufgerufen[0][0])
    assert aufgerufen[0][1] is True


def test_beschaeftigter_orb_verliert_die_geplante_fortsetzung_nicht(tmp_path):
    async def _lauf():
        session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=3)
        session.starten("Halte eine Vorlesung über die Antike")
        pipeline = _pipeline_fuer_timer(session)
        pipeline._loop = asyncio.get_running_loop()
        pipeline._processing = True
        aufgerufen = []

        async def _antwort(text, turn, *, vorlesungszug=False):
            aufgerufen.append((text, vorlesungszug))

        pipeline._respond = _antwort
        pipeline._vorlesung_fortsetzung_planen()
        await asyncio.sleep(0.04)
        pipeline._processing = False
        await asyncio.sleep(0.40)
        return aufgerufen

    aufgerufen = asyncio.run(_lauf())
    assert len(aufgerufen) == 1
    assert ist_vorlesungssegment(aufgerufen[0][0])


def test_wortmeldung_verwirft_den_geplanten_folgeabschnitt(tmp_path):
    async def _lauf():
        session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=3)
        session.starten("Halte eine Vorlesung über die Antike")
        pipeline = _pipeline_fuer_timer(session)
        pipeline._loop = asyncio.get_running_loop()
        pipeline._vorlesung_pause = 0.05
        aufgerufen = []

        async def _antwort(text, turn, *, vorlesungszug=False):
            aufgerufen.append(text)

        pipeline._respond = _antwort
        pipeline._vorlesung_fortsetzung_planen()
        pipeline._vorlesung_timer_abbrechen()
        await asyncio.sleep(0.08)
        return aufgerufen

    assert asyncio.run(_lauf()) == []


# ---------------------------------------------------------------------------
# Philosophie und Geschichte wurden verwechselt (26.08.2026)
# ---------------------------------------------------------------------------
#
# Es gab genau EINEN Stand in EINER Datei. Auf dem Rechner des Benutzers
# stand darin eine Philosophie-Vorlesung bei Abschnitt 18. Wer daneben eine
# Vorlesung ueber Geschichte begann, ueberschrieb sie lautlos - und ein
# spaeteres "Fahre fort" setzte die zuletzt gestartete fort, gleich welche
# gemeint war.


def test_eine_zweite_vorlesung_loescht_die_erste_nicht(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=40)
    session.starten("Halte eine Einführungsvorlesung in Philosophie")
    session.abschnitt_beendet("Platon lehrte die Ideenlehre.")
    session.abschnitt_beendet("Aristoteles widersprach ihm.")

    session.starten("Halte eine Vorlesung über Geschichte")

    assert set(session.faecher) == {"philosophie", "geschichte"}
    assert session._alle["philosophie"].naechster_abschnitt == 3
    assert session._alle["geschichte"].naechster_abschnitt == 1


def test_fortsetzen_mit_genanntem_fach_wechselt_statt_zu_loeschen(tmp_path):
    """Der eigentliche Fehler: Ein genanntes anderes Fach hiess "start"."""

    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=40)
    session.starten("Halte eine Einführungsvorlesung in Philosophie")
    session.abschnitt_beendet("Die Ideenlehre bei Platon.")
    session.starten("Halte eine Vorlesung über Geschichte")

    assert session.befehl("Fahre fort mit der Vorlesung über Philosophie") == "fortsetzen"
    session.fortsetzen()
    assert session.stand.thema.lower() == "philosophie"
    assert session.stand.naechster_abschnitt == 2


def test_ein_unbekanntes_fach_beginnt_weiterhin_neu(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=40)
    session.starten("Halte eine Einführungsvorlesung in Philosophie")

    assert session.befehl("Fahre fort mit der Vorlesung über Astronomie") == "start"


def test_der_alte_dateiaufbau_wird_uebernommen(tmp_path):
    """Die begonnene Philosophie-Vorlesung darf beim Umbau nicht verlorengehen."""

    import json

    pfad = tmp_path / "vorlesung.json"
    pfad.write_text(
        json.dumps(
            {
                "auftrag": "Halte eine Einführungsvorlesung in Philosophie",
                "thema": "Philosophie",
                "naechster_abschnitt": 18,
                "aktiv": True,
                "pausiert": False,
                "abgeschlossen": False,
                "letzter_auszug": "Aristoteles bricht mit Platon.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    session = VorlesungsSession(pfad, max_abschnitte=40)
    assert session.faecher == ["philosophie"]
    assert session.stand.naechster_abschnitt == 18
    # Nach einem Programmstart wird nie ungefragt weitergeredet.
    assert session.stand.pausiert is True


def test_beide_vorlesungen_ueberleben_einen_neustart(tmp_path):
    pfad = tmp_path / "vorlesung.json"
    erste = VorlesungsSession(pfad, max_abschnitte=40)
    erste.starten("Halte eine Einführungsvorlesung in Philosophie")
    erste.abschnitt_beendet("Platon und die Ideen.")
    erste.starten("Halte eine Vorlesung über Geschichte")
    erste.abschnitt_beendet("Die Antike beginnt.")

    zweite = VorlesungsSession(pfad, max_abschnitte=40)
    assert set(zweite.faecher) == {"philosophie", "geschichte"}
    assert zweite._alle["philosophie"].naechster_abschnitt == 2
    assert zweite._alle["geschichte"].naechster_abschnitt == 2


def test_ein_titel_muss_nicht_wortgleich_wiederholt_werden(tmp_path):
    session = VorlesungsSession(tmp_path / "vorlesung.json", max_abschnitte=40)
    session.starten("Halte eine Vorlesung über die Geschichte der Antike")
    session.abschnitt_beendet("Mesopotamien und Ägypten.")
    session.starten("Halte eine Einführungsvorlesung in Philosophie")

    assert session.befehl("Fahre fort mit der Vorlesung über Geschichte") == "fortsetzen"
    session.fortsetzen()
    assert "geschichte" in session.stand.thema.lower()
    assert session.stand.naechster_abschnitt == 2
