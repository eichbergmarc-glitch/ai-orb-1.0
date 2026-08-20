"""Der Orb muss sich an Besprochenes erinnern.

Der Befund vom 19.08.2026, gemessen an ``data/memory.json`` des Benutzers:

* **222 Einträge** im Gedächtnis - davon **null**
  Gesprächszusammenfassungen. Geschrieben wurden sie nur beim sauberen
  Herunterfahren (``end_conversation``), und ein Sprachassistent auf
  einem Arbeitsrechner wird nicht sauber heruntergefahren. Er wird
  geschlossen.
* Von den 222 stammten **130 aus "gespräch"** - und zwar ausschliesslich
  die FRAGEN des Benutzers. Wörtlich gespeichert war etwa::

      "du hast zuletzt ein dokument über fossilien und gestein eingelesen
       dabei gab es offene fragen was sind diese offenen fragen"

  Die Auskunft darauf stand nirgends.
* Eine neue Unterhaltung begann bei null, auch zehn Minuten nach der
  letzten.

Daraus die drei Klagen des Benutzers: keine flüssige Konversation, keine
Erinnerung an behandelte Themen, eingelesene Dokumente nicht gespeichert.
"""

from __future__ import annotations

import time
import uuid

import pytest

from backend.memory.conversation_memory import ConversationMemory
from backend.memory.memory_store import MemoryStore
from backend.utils.paths import get_data_dir


def _frischer_speicher():
    """Ein eigener Speicher je Test.

    ``MemoryStore`` schreibt in eine Datei unter ``data/``. Ohne eigenen
    Namen greifen alle Tests auf dasselbe Gedaechtnis zu - und auf das
    ECHTE, wenn der Test im Projektordner laeuft.
    """

    return MemoryStore(filename=f"test-gedaechtnis-{uuid.uuid4().hex}.json")


@pytest.fixture(autouse=True)
def _aufraeumen():
    yield
    for datei in get_data_dir().glob("test-gedaechtnis-*.json"):
        datei.unlink(missing_ok=True)


@pytest.fixture
def gedaechtnis():
    return ConversationMemory(_frischer_speicher())


# --- Der Stand einer laufenden Sitzung -------------------------------------


def test_eine_laufende_sitzung_wird_festgehalten(gedaechtnis):
    eintrag = gedaechtnis.sitzung_festhalten(
        "Es ging um Fossilien im Schweizer Jura.",
        session_id="abc",
        message_count=12,
    )
    assert eintrag is not None
    assert gedaechtnis.recent(limit=5)


def test_ein_neuer_stand_ersetzt_den_alten_derselben_sitzung(gedaechtnis):
    # Sonst entstuende bei jedem Verdichten ein weiterer halber Rueckblick,
    # und nach zwei Stunden Gespraech stuenden zwanzig davon im Gedaechtnis.
    gedaechtnis.sitzung_festhalten("Erster Stand", session_id="abc")
    gedaechtnis.sitzung_festhalten("Zweiter, vollständigerer Stand", session_id="abc")

    eintraege = gedaechtnis.recent(limit=10)
    assert len(eintraege) == 1
    assert eintraege[0].content == "Zweiter, vollständigerer Stand"


def test_verschiedene_sitzungen_bleiben_getrennt(gedaechtnis):
    gedaechtnis.sitzung_festhalten("Gespräch über Geologie", session_id="abc")
    gedaechtnis.sitzung_festhalten("Gespräch über Markus Gabriel", session_id="xyz")
    assert len(gedaechtnis.recent(limit=10)) == 2


def test_leeres_wird_nicht_abgelegt(gedaechtnis):
    assert gedaechtnis.sitzung_festhalten("", session_id="abc") is None
    assert gedaechtnis.sitzung_festhalten("   ", session_id="abc") is None
    assert gedaechtnis.recent(limit=5) == []


# --- Der Faden in die neue Sitzung -----------------------------------------


class _Gedaechtnis:
    """Ein Gedächtnis mit echtem Speicher, aber ohne Modellanbindung."""

    def __init__(self):
        self.conversations = ConversationMemory(_frischer_speicher())

    class summaries:  # noqa: N801
        @staticmethod
        async def summarize_conversation(_messages):
            return "verdichtet"


def _manager(gedaechtnis):
    from backend.orchestrator.conversation_manager import ConversationManager

    return ConversationManager(gedaechtnis)


def test_eine_neue_unterhaltung_kennt_die_letzte():
    g = _Gedaechtnis()
    g.conversations.sitzung_festhalten(
        "Wir haben das Dokument über Fossilien durchgesprochen.",
        session_id="gestern",
    )

    unterhaltung = _manager(g).start()

    assert "Fossilien" in unterhaltung.summary
    assert "Frueher besprochen" in unterhaltung.summary


def test_ohne_vorgeschichte_bleibt_die_unterhaltung_leer():
    unterhaltung = _manager(_Gedaechtnis()).start()
    assert unterhaltung.summary == ""


def test_der_rueckblick_landet_auch_im_systemtext():
    # Er nuetzt nichts, wenn er nicht in die Modellanfrage kommt.
    g = _Gedaechtnis()
    g.conversations.sitzung_festhalten("Thema war die Julikrise.", session_id="gestern")

    manager = _manager(g)
    manager.start()
    nachrichten = manager.build_messages()

    assert any("Julikrise" in str(n.content) for n in nachrichten)


@pytest.mark.parametrize("stunden", [1, 30])
def test_das_alter_wird_genannt(stunden):
    # "Frueher besprochen" ohne Zeitangabe waere irrefuehrend: Das Modell
    # kann sonst nicht unterscheiden, ob etwas von eben oder von vorletzter
    # Woche stammt.
    g = _Gedaechtnis()
    eintrag = g.conversations.sitzung_festhalten("Thema X", session_id="alt")
    # Direkt zurueckdatieren: ``update()`` setzt updated_at immer auf jetzt,
    # und genau dieses Feld soll hier geprueft werden.
    eintrag.updated_at = time.time() - stunden * 3600

    unterhaltung = _manager(g).start()
    assert f"vor {stunden} h" in unterhaltung.summary, unterhaltung.summary


# --- Dass die Verdichtung wirklich ins Gedächtnis schreibt -----------------


def test_die_verdichtung_schreibt_ins_gedaechtnis():
    from pathlib import Path

    quelle = Path("backend/orchestrator/conversation_manager.py").read_text(
        encoding="utf-8"
    )
    anfang = quelle.index("async def maybe_compress")
    ausschnitt = quelle[anfang:anfang + 3000]
    assert "sitzung_festhalten" in ausschnitt


# --- Und dass Frage UND Antwort gemerkt werden -----------------------------


def test_der_wortwechsel_enthaelt_beides():
    from pathlib import Path

    quelle = Path("backend/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    anfang = quelle.index("def _wortwechsel_merken")
    ausschnitt = quelle[anfang:anfang + 2500]
    assert "Gefragt:" in ausschnitt
    assert "Geantwortet:" in ausschnitt
    # Und der alte Weg - nur die Frage - darf nicht daneben stehenbleiben.
    assert 'remember(\n                text,' not in quelle


def test_gelesenes_wird_behalten():
    from pathlib import Path

    quelle = Path("backend/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    assert "def _gelesenes_merken" in quelle
    werkzeuge = Path("backend/tools/tool_engine.py").read_text(encoding="utf-8")
    assert "gelesenes_behalten" in werkzeuge
    assert "_LESENDE_WERKZEUGE" in werkzeuge
    laufzeit = Path("backend/runtime.py").read_text(encoding="utf-8")
    assert "gelesenes_behalten" in laufzeit
