"""Das Verhörte wieder herausnehmen.

Der Anlass steht im Protokoll vom 18.08.2026. Eine fremde Stimme kam
zweimal durch die Erkennung, beide Sätze wurden beantwortet - und beide
blieben im Gesprächsverlauf stehen. Von da an las jede weitere Antwort
sie mit. Der Modellkontext wuchs von 17 auf 23 Nachrichten, die falschen
zwei waren in jeder einzelnen dabei.

Der Benutzer hat um 11:22:45 selbst gesagt, was zu tun wäre::

    "Du hast eine falsche Stimme gehört, Orb, du sollst nur auf mich
     hören."

Es geschah nichts. Diese Tests halten fest, dass dieser Satz jetzt wirkt -
ohne Sprachmodell, ohne Werkzeug, sofort.
"""

from __future__ import annotations

import pytest

from backend.orchestrator.verlaufsreparatur import (
    STANDARD_WECHSEL,
    antwort,
    ist_reparaturbefehl,
)


@pytest.mark.parametrize(
    "satz",
    [
        "Du hast eine falsche Stimme gehört, Orb, du sollst nur auf mich hören.",
        "Das war eine fremde Stimme, nicht ich.",
        "Das war nicht ich",
        "Das habe ich gar nicht gesagt",
        "Das war jemand anderes",
        "Das war der Fernseher",
        "Vergiss das letzte bitte",
        "Nimm das letzte zurück",
        "Hör nur auf mich",
    ],
)
def test_die_ruecknahme_wird_erkannt(satz):
    assert ist_reparaturbefehl(satz), satz


@pytest.mark.parametrize(
    "satz",
    [
        "Was hast du gerade gesagt?",
        "Erzähl mir mehr über die Stimme der Vernunft",
        "Ich habe das nicht verstanden",
        "Das war interessant",
        "",
    ],
)
def test_gewoehnliche_saetze_loeschen_nichts(satz):
    assert not ist_reparaturbefehl(satz), satz


def test_die_bestaetigung_nennt_die_zahl():
    assert "1" not in antwort(0)
    assert "letzten Wortwechsel" in antwort(1)
    assert "2" in antwort(2)


# --- Der Verlauf selbst ----------------------------------------------------


class _Speicher:
    """Ein Gedächtnis, das für diesen Test nichts können muss."""

    class summaries:  # noqa: N801
        @staticmethod
        async def summarize_conversation(_messages):
            return ""


def _manager():
    from backend.orchestrator.conversation_manager import ConversationManager

    return ConversationManager(_Speicher())


def test_zwei_wechsel_verschwinden_vollstaendig():
    manager = _manager()
    manager.add_user_message("Fasse mir die Nachrichten zusammen")
    manager.add_assistant_message("Gerne, hier sind sie.")
    manager.add_user_message("Nachwägung, Konkunft, Sekundism ...")
    manager.add_assistant_message("Ich verstehe das als Hinweis auf ...")
    manager.add_user_message("Das ist unverteidigbar ... Hallo Orb!")
    manager.add_assistant_message("Du sprichst offenbar über ...")

    entfernt = manager.letzte_wechsel_verwerfen(STANDARD_WECHSEL)

    assert entfernt == 2
    inhalte = [m["content"] for m in manager.active.messages]
    assert inhalte == ["Fasse mir die Nachrichten zusammen", "Gerne, hier sind sie."]


def test_eine_frage_ohne_antwort_wird_mit_entfernt():
    # Bliebe die Frage stehen, wuerde das Modell beim naechsten Mal
    # versuchen, sie nachzuholen - und der Unsinn waere wieder da.
    manager = _manager()
    manager.add_user_message("Zeig mir die Bilder")
    manager.add_assistant_message("Hier sind sie.")
    manager.add_user_message("wirres Zeug aus dem Raum")

    assert manager.letzte_wechsel_verwerfen(1) == 1
    assert [m["role"] for m in manager.active.messages] == ["user", "assistant"]


def test_ein_leerer_verlauf_bleibt_leer():
    manager = _manager()
    assert manager.letzte_wechsel_verwerfen(2) == 0
    assert manager.active.messages == []


def test_es_wird_nie_mehr_entfernt_als_da_ist():
    manager = _manager()
    manager.add_user_message("Hallo")
    manager.add_assistant_message("Hallo auch.")

    assert manager.letzte_wechsel_verwerfen(5) == 1
    assert manager.active.messages == []


def test_der_orchestrator_holt_die_ruecknahme_wirklich_ein():
    # Ein Urteil nuetzt nichts, wenn es niemand einholt - und diese
    # Pruefung muss vor jeder Modellwahl stehen, sonst scheitert die
    # Ruecknahme genau dann, wenn der Verlauf schon verdorben ist.
    from pathlib import Path

    quelle = Path("backend/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    assert "ist_reparaturbefehl" in quelle
    assert quelle.index("ist_reparaturbefehl(text)") < quelle.index(
        "mode_command = provider_mode_command(text)"
    )
