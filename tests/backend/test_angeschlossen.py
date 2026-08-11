"""Tests der neu angeschlossenen Faehigkeiten.

Eine Durchsicht des Programms hat mehrere Faehigkeiten zutage gefoerdert,
die fertig gebaut, getestet - und von keiner Stelle erreichbar waren. Der
Gmail-Agent war die groesste: Anmeldung, Postfach, Entwurf, Bestaetigung,
Senden, alles da, und der Orb konnte trotzdem keine einzige Mail lesen.

Diese Tests halten den Anschluss fest. Sie pruefen nicht, ob Gmail
funktioniert - das taten die bestehenden Tests schon -, sondern ob es
ERREICHBAR ist und ob die eine Regel gilt, auf die es ankommt: dass nichts
ohne ausdrueckliche Zustimmung das Postfach verlaesst.
"""

from __future__ import annotations

import asyncio

from backend.tools.gmail_tools import (
    DraftMailTool,
    ReadMailTool,
    SearchMailTool,
    SendMailTool,
    build_gmail_tools,
)


def _fuehre_aus(werkzeug, **argumente):
    return asyncio.run(werkzeug.execute(argumente))


class _Mail:
    def __init__(self, kennung: str, von: str, betreff: str):
        self.id = kennung
        self.sender = von
        self.subject = betreff

    def for_reading_aloud(self) -> str:
        return f"Von {self.sender}, Betreff {self.subject}."


class _Agent:
    """Ein Gmail-Agent ohne Netz."""

    def __init__(self, bereit: bool = True):
        self.is_ready = bereit
        self.gesendet = 0
        self.entwuerfe: list[dict] = []
        self.mails = [_Mail("1", "anna@example.org", "Termin")]

    def status(self):
        return {"hinweis": "Gmail ist nicht verbunden."}

    async def read_unread(self, *, limit=5):
        return self.mails[:limit]

    async def search(self, text, *, limit=10):
        return [m for m in self.mails if text.lower() in m.subject.lower()][:limit]

    async def prepare_draft(self, *, to, subject, body, reply_to_id="", thread_id=""):
        self.entwuerfe.append({"an": to, "betreff": subject, "text": body})
        return {
            "ok": True,
            "entwurf_id": "e1",
            "vorschau": {"an": to, "betreff": subject, "text": body},
        }

    async def confirm_and_send(self):
        if not self.entwuerfe:
            return {"ok": False, "hinweis": "Es wartet kein Entwurf."}
        self.entwuerfe.pop()
        self.gesendet += 1
        return {"ok": True, "hinweis": "Die Mail ist unterwegs."}

    async def discard_draft(self):
        if not self.entwuerfe:
            return {"ok": False, "hinweis": "Es wartet kein Entwurf."}
        self.entwuerfe.pop()
        return {"ok": True, "hinweis": "Der Entwurf ist verworfen."}

    def begin_login(self):
        return {"hinweis": "Oeffne die Seite und melde dich an."}


# --- Gmail ist erreichbar ------------------------------------------------------


def test_alle_mail_werkzeuge_entstehen():
    werkzeuge = build_gmail_tools(_Agent())
    namen = {w.name for w in werkzeuge}

    assert namen == {
        "mails_lesen",
        "mails_suchen",
        "mail_entwerfen",
        "mail_senden",
        "entwurf_verwerfen",
        "gmail_anmelden",
    }


def test_mails_werden_vorlesbar_geliefert():
    ergebnis = _fuehre_aus(ReadMailTool(_Agent()), anzahl=5)

    assert ergebnis.ok, ergebnis.error
    assert "anna@example.org" in ergebnis.output
    assert "Termin" in ergebnis.output


def test_ohne_anmeldung_kommt_eine_verstaendliche_auskunft():
    ergebnis = _fuehre_aus(ReadMailTool(_Agent(bereit=False)), anzahl=5)

    assert not ergebnis.ok
    assert "nicht verbunden" in ergebnis.error


def test_suche_findet_und_meldet_leere_treffer():
    agent = _Agent()
    assert "Termin" in _fuehre_aus(SearchMailTool(agent), suche="termin").output

    leer = _fuehre_aus(SearchMailTool(agent), suche="gibtsnicht")
    assert leer.ok
    assert "nichts im Postfach" in leer.output


# --- Und die Regel, auf die es ankommt -----------------------------------------


def test_ein_entwurf_wird_nicht_gesendet():
    """Der wichtigste Test: Zwischen Schreiben und Senden gehoert ein Halt.

    Eine Mail laesst sich nicht zurueckholen. Es darf deshalb kein Werkzeug
    geben, das in einem Zug schreibt und abschickt.
    """

    agent = _Agent()
    ergebnis = _fuehre_aus(
        DraftMailTool(agent), an="anna@example.org", betreff="Hallo", text="Kurz."
    )

    assert ergebnis.ok, ergebnis.error
    assert agent.gesendet == 0, "der Entwurf wurde gesendet"
    assert "NICHT gesendet" in ergebnis.output
    assert "frage" in ergebnis.output.lower(), "es wird nicht zum Nachfragen angehalten"


def test_gesendet_wird_erst_nach_dem_entwurf():
    agent = _Agent()

    ohne = _fuehre_aus(SendMailTool(agent))
    assert not ohne.ok
    assert agent.gesendet == 0

    _fuehre_aus(DraftMailTool(agent), an="a@b.de", betreff="X", text="Y")
    mit = _fuehre_aus(SendMailTool(agent))

    assert mit.ok, mit.error
    assert agent.gesendet == 1


def test_zweimal_senden_schickt_nicht_zweimal():
    """Ein spaeteres 'ja' darf nichts erneut verschicken."""

    agent = _Agent()
    _fuehre_aus(DraftMailTool(agent), an="a@b.de", betreff="X", text="Y")
    _fuehre_aus(SendMailTool(agent))
    nochmal = _fuehre_aus(SendMailTool(agent))

    assert not nochmal.ok
    assert agent.gesendet == 1


def test_das_senden_verlangt_die_hoechste_berechtigung():
    """Es ist die einzige Stelle, die etwas aus dem Haus schickt."""

    assert SendMailTool(_Agent()).permission == "send_email"
    assert DraftMailTool(_Agent()).permission == "read_email"


def test_unsinnige_adresse_wird_abgewiesen():
    agent = _Agent()
    ergebnis = _fuehre_aus(DraftMailTool(agent), an="Anna", betreff="X", text="Y")

    assert not ergebnis.ok
    assert agent.entwuerfe == []


# --- Ablaeufe lassen sich per Satz ausloesen -----------------------------------


class _Ablauf:
    def __init__(self):
        self.id = "a1"
        self.name = "Morgenroutine"


class _Ablaufmaschine:
    def __init__(self, treffer: bool = True):
        self.treffer = treffer
        self.gestartet: list[str] = []

    def find_by_trigger(self, text):
        return _Ablauf() if self.treffer else None

    async def run(self, kennung, **kw):
        self.gestartet.append(kennung)

        class _Bericht:
            summary = "Drei Schritte erledigt."

            def to_dict(self):
                return {"ok": True}

        return _Bericht()


def _orchestrator(maschine=None):
    from backend.memory.memory_engine import MemoryEngine
    from backend.orchestrator.orchestrator import Orchestrator

    class _Anbieter:
        active_name = "test"

        def begin_conversation(self):
            pass

        gefragt = 0

        async def chat(self, messages, **kw):
            from backend.orchestrator.providers.base_provider import ProviderResponse

            type(self).gefragt += 1
            return ProviderResponse(
                text="Eine gewoehnliche Antwort.",
                provider="test",
                model="test",
                latency_seconds=0.0,
            )

    orch = Orchestrator(memory=MemoryEngine(), provider_manager=_Anbieter())
    if maschine is not None:
        orch.attach_workflows(maschine)
    return orch


def test_ein_satz_loest_den_ablauf_aus():
    """Ein Ablauf, den man nur mit seiner Nummer aufrufen kann, ist keine
    Automatisierung, sondern ein Menuepunkt."""

    maschine = _Ablaufmaschine(treffer=True)
    orch = _orchestrator(maschine)

    ergebnis = asyncio.run(orch.handle("Starte meine Morgenroutine"))

    assert maschine.gestartet == ["a1"]
    assert ergebnis.module == "workflows"
    assert "Drei Schritte" in ergebnis.response
    assert ergebnis.used_llm is False


def test_ohne_passenden_ablauf_geht_es_gewoehnlich_weiter():
    maschine = _Ablaufmaschine(treffer=False)
    orch = _orchestrator(maschine)

    ergebnis = asyncio.run(orch.handle("Erzähl mir etwas über Bern."))

    assert maschine.gestartet == []
    assert ergebnis.module != "workflows"


def test_ein_kaputter_ablauf_verhindert_keine_antwort():
    """Im Zweifel antwortet der Orb lieber selbst, als zu schweigen."""

    class _Kaputt:
        def find_by_trigger(self, text):
            raise RuntimeError("Ablaufdatei weg")

    orch = _orchestrator(_Kaputt())
    ergebnis = asyncio.run(orch.handle("Erzähl mir etwas über Bern."))

    assert ergebnis.module != "workflows"
    assert ergebnis.response
