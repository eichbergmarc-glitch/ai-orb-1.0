"""Eine Probe: Antwortet der Blindbewerter, und wie lange braucht er?

Vor einer Messserie mit ueber hundert Urteilen lohnt eine Minute
Vorpruefung. Gefragt wird genau so, wie im Ernstfall gefragt wird - mit
der Urteilsanweisung und zwei kurzen Antworten -, und gemessen wird, ob
ein lesbares Urteil herauskommt.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
if str(WURZEL) not in sys.path:
    sys.path.insert(0, str(WURZEL))

from backend.lernen.blindbewertung import (  # noqa: E402
    URTEILSANWEISUNG,
    Kandidat,
    _urteil_lesen,
    vorlage_bauen,
)


async def _probe(bewerter: str) -> dict:
    from backend.orchestrator.provider_manager import ProviderManager
    from backend.orchestrator.providers.base_provider import ChatMessage

    manager = ProviderManager()
    await manager.start()
    bericht: dict = {"bewerter": bewerter, "durchgaenge": []}
    try:
        for lage in ("normal", "getauscht"):
            vorlage = vorlage_bauen(
                kennung="probe-01",
                aufgabe="Wie viele Sekunden hat ein Tag?",
                erster=Kandidat("lehrer", "Ein Tag hat 86.400 Sekunden.", ()),
                zweiter=Kandidat("schueler", "Das sind 86400 Sekunden, also 24 mal 3600.", ()),
                lage=lage,
            )
            begonnen = time.perf_counter()
            try:
                antwort = await manager.chat(
                    [ChatMessage(role="user", content=f"{URTEILSANWEISUNG}\n\n{vorlage.sicht()}")],
                    preferred=bewerter,
                )
                roh = str(getattr(antwort, "text", "") or "")
                modell = str(getattr(antwort, "model", "") or "")
            except Exception as fehler:  # noqa: BLE001
                roh, modell = "", ""
                bericht.setdefault("fehler", []).append(f"{type(fehler).__name__}: {fehler}")
            etikett, grund = _urteil_lesen(roh)
            bericht["durchgaenge"].append(
                {
                    "lage": lage,
                    "sekunden": round(time.perf_counter() - begonnen, 1),
                    "modell": modell,
                    "etikett": etikett,
                    "grund": grund[:200],
                    "lesbar": etikett.strip().upper().rstrip(".:!") in {"A", "B"}
                    or "GLEICH" in etikett.upper(),
                    "rohlaenge": len(roh),
                }
            )
    finally:
        await manager.stop()
    return bericht


if __name__ == "__main__":  # pragma: no cover
    name = sys.argv[1] if len(sys.argv) > 1 else "ollama_richter"
    from backend.lernen.messen import _protokoll_auf_fehlerkanal

    _protokoll_auf_fehlerkanal()
    print(json.dumps(asyncio.run(_probe(name)), ensure_ascii=False, indent=2))
