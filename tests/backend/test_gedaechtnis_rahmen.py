"""Der Orb muss wissen, dass er ein sitzungsuebergreifendes Gedaechtnis hat.

Der ganze Gedaechtnis-Weg funktioniert (Speichern, Laden, Suchen, Einspeisen
sind an anderer Stelle geprueft). Der Benutzer erlebte trotzdem "der Orb
erinnert sich nicht" - weil das Modell das eingespeiste Wissen nicht als
SEINE Erinnerung behandelte und reflexhaft sagte, es habe keinen Zugriff auf
fruehere Sitzungen. Diese Tests sichern die beiden Stellen, die das
klarstellen: der Systemprompt und die Ueberschrift des Gedaechtnisblocks.
"""

from __future__ import annotations

import yaml

from backend.orchestrator.orchestrator import Orchestrator
from backend.utils.paths import get_project_root


def _system_prompt() -> str:
    d = yaml.safe_load((get_project_root() / "config.yaml").read_text(encoding="utf-8"))
    return d["conversation"]["system_prompt"]


def test_systemprompt_sagt_dass_es_ein_gedaechtnis_gibt():
    sp = _system_prompt().lower()
    assert "gedaechtnis" in sp or "gedächtnis" in sp
    # Es muss dem reflexhaften "ich kann mich nicht sitzunguebergreifend
    # erinnern" ausdruecklich widersprechen.
    assert "keinen zugriff auf fruehere" in sp or "nicht erinnern" in sp


def test_kontextblock_kennzeichnet_erinnerung_als_eigene():
    ctx = {
        "memories": [
            {"content": "Der Benutzer arbeitet an einer Arbeit zur Antike.",
             "kind": "knowledge", "certainty": "fakt", "relevance": 0.9}
        ],
        "conversations": [], "user_facts": [], "open_tasks": [],
    }
    block = Orchestrator._format_context(ctx, None)
    assert "Antike" in block
    # Die Ueberschrift muss klarstellen: das ist die eigene Erinnerung.
    assert "Gedächtnis" in block
    assert "früheren" in block or "gelernt" in block


def test_leerer_kontext_bleibt_leer():
    leer = {"memories": [], "conversations": [], "user_facts": [], "open_tasks": []}
    assert Orchestrator._format_context(leer, None) == ""
