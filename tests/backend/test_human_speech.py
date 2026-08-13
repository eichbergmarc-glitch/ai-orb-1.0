from __future__ import annotations

import json

from backend.voice.human_speech import HumanSpeechPolicy
from backend.voice.speaker_id import Stimmprofil


def test_denklaut_ist_sparsam_und_hat_abkuehlzeit():
    policy = HumanSpeechPolicy(cooldown_seconds=30, minimum_words=6)
    text = (
        "Warum ist dieser Ansatz langfristig besser und welche technischen, "
        "finanziellen und praktischen Nachteile muss ich bei der Entscheidung berücksichtigen?"
    )

    assert policy.thinking_cue(text, now=100) in {"Hmm.", "Hmm, lass mich kurz überlegen."}
    assert policy.thinking_cue(text, now=110) == ""
    assert policy.thinking_cue(text, now=131) != ""


def test_kurze_antworten_bekommen_keinen_kuenstlichen_fuelllaut():
    policy = HumanSpeechPolicy(minimum_words=8)
    assert policy.thinking_cue("Wie spät ist es?", now=100) == ""


def test_stimmprofil_speichert_nur_nicht_rekonstruierbaren_rhythmus():
    profil = Stimmprofil(sprechtempo=0.94, pause_ms=245)
    data = profil.to_dict()

    assert data["sprechstil"] == {"tempo": 0.94, "pause_ms": 245}
    assert "audio" not in json.dumps(data).lower()
    restored = Stimmprofil.from_dict(data)
    assert restored.sprechtempo == 0.94
    assert restored.pause_ms == 245


def test_altes_stimmprofil_bleibt_kompatibel():
    restored = Stimmprofil.from_dict(
        {"abdruecke": [[0.1, 0.2]], "schwelle": 0.62, "aufnahmen": 3}
    )
    assert restored.gelernt
    assert restored.sprechtempo == 1.0
    assert restored.pause_ms == 180
