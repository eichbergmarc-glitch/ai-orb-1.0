"""Werkzeuge, mit denen Synapse ihre Wissensbibliothek selbst erweitert (22.11.2026)."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


class WissenErweiternTool(Tool):
    name = "wissen_erweitern"
    description = (
        "Erweitert deine Wissensbibliothek dauerhaft: nimmt einen offenen "
        "Datensatz, eine Webseite oder eine Datei auf, damit du das Wissen "
        "spaeter nachschlagen kannst (online und offline). 'quelle' ist "
        "(a) ein Hugging-Face-Datensatz als 'hf:besitzer/name' oder dessen "
        "Adresse huggingface.co/datasets/..., z. B. 'hf:rajpurkar/squad' "
        "(Wissensfragen), 'hf:fancyzhx/dbpedia_14' (Lexikon-Kurztexte); "
        "(b) eine Webseiten-Adresse; (c) ein Dateipfad (.txt .md .csv .json "
        ".jsonl). 'anzahl' = hoechstens so viele Zeilen (Standard 1000, "
        "hoechstens 20000), 'ab' = ab welcher Zeile weitermachen. Benutze das "
        "bei 'lerne ...', 'nimm ... in dein Wissen auf', 'erweitere deine "
        "Wissensdatenbank', 'lade den Datensatz ...'."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("quelle", "string", "Datensatz (hf:besitzer/name), Webadresse oder Dateipfad."),
        ToolParameter("anzahl", "integer", "Hoechstens so viele Zeilen.", required=False, default=1000),
        ToolParameter("ab", "integer", "Ab dieser Zeile (zum Fortsetzen).", required=False, default=0),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.knowledge.wissen_import import ImportFehler, aufnehmen

        try:
            anzahl = int(arguments.get("anzahl") or 1000)
            ab = int(arguments.get("ab") or 0)
        except (TypeError, ValueError):
            anzahl, ab = 1000, 0
        try:
            bericht = await asyncio.to_thread(
                aufnehmen, str(arguments.get("quelle", "")), anzahl=anzahl, ab=ab
            )
        except ImportFehler as fehler:
            return ToolResult.failure(f"Das liess sich nicht aufnehmen: {fehler}")
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Wissensimport fehlgeschlagen.")
            return ToolResult.failure(f"Beim Aufnehmen ging etwas schief: {fehler}")
        text = f"Aufgenommen: {bericht['eingetragen']} Wissenseintraege aus {bericht['name']}."
        if bericht.get("gesamt"):
            text += (
                f" Gelesen wurden {bericht['gelesen']} von {bericht['gesamt']} Zeilen; "
                f"weitermachen ginge mit ab={bericht['weiter_ab']}."
            )
        return ToolResult.success(text, **{k: v for k, v in bericht.items() if k != "name"})


class WissenBestandTool(Tool):
    name = "wissen_bestand"
    description = (
        "Zeigt, was in deiner Wissensbibliothek steckt (Wikipedia, eigene "
        "Eintraege nach Herkunft) und schlaegt offene Datensaetze vor. Mit "
        "'vergessen' = Herkunft (z. B. 'datensatz:squad') entfernst du einen "
        "aufgenommenen Datensatz wieder."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("vergessen", "string", "Herkunft, die entfernt werden soll.", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.knowledge.wissen_import import VORSCHLAEGE, bestand, vergessen
        from backend.knowledge.wissensbibliothek import bibliothek

        weg = str(arguments.get("vergessen") or "").strip()
        if weg:
            anzahl = await asyncio.to_thread(vergessen, weg)
            return ToolResult.success(f"{anzahl} Eintraege mit der Herkunft '{weg}' entfernt.")
        status = await asyncio.to_thread(bibliothek().status)
        teile = await asyncio.to_thread(bestand)
        wiki = status.get("wikipedia")
        zeilen = [
            f"Wikipedia: {wiki.get('artikel')} Artikel (Stand {wiki.get('stand')})" if wiki
            else "Wikipedia: noch nicht eingerichtet",
            f"Eigenes Wissen: {status.get('eigenes_wissen') or 0} Eintraege",
        ]
        zeilen += [f"  - {art}: {n}" for art, n in teile[:15]]
        zeilen.append("Offene Datensaetze zum Aufnehmen:")
        zeilen += [f"  - {k}: {v}" for k, v in VORSCHLAEGE.items()]
        return ToolResult.success("\n".join(zeilen))


class SelbstLernenTool(Tool):
    """23.11.2026: Synapse lernt selbst dazu - Bericht, sofortiger Lernlauf, Thema vormerken."""

    name = "selbst_lernen"
    description = (
        "Dein eigenes Dazulernen. Du merkst dir Fragen, zu denen deine "
        "Bibliothek nichts wusste, und lernst sie alle zwei Stunden aus der "
        "aktuellen Wikipedia nach. aktion 'bericht' = was du heute gelernt "
        "hast und was noch offen ist; 'jetzt' = sofort einen Lernlauf machen; "
        "'thema' = ein Thema (in 'thema') sofort lernen. Benutze das bei 'was "
        "hast du heute gelernt', 'lern etwas ueber ...', 'bild dich weiter'."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("aktion", "string", "'bericht', 'jetzt' oder 'thema'.",
                      required=False, default="bericht", choices=("bericht", "jetzt", "thema")),
        ToolParameter("thema", "string", "Thema zum Lernen (bei aktion 'thema').", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.knowledge import selbstlernen as sl

        aktion = str(arguments.get("aktion") or "bericht")
        try:
            if aktion == "thema":
                thema = str(arguments.get("thema") or "").strip()
                if not thema:
                    return ToolResult.failure("Welches Thema soll ich lernen?")
                titel = await asyncio.to_thread(sl.wikipedia_lernen, thema, artikel=2)
                if not titel:
                    await asyncio.to_thread(sl.thema_vormerken, thema)
                    return ToolResult.success(f"Zu '{thema}' fand ich gerade keinen Artikel; ich habe es vorgemerkt.")
                return ToolResult.success(f"Gelernt und in die Bibliothek aufgenommen: {', '.join(titel)}.")
            if aktion == "jetzt":
                bericht = await asyncio.to_thread(sl.lernlauf)
                if not bericht["gelernt"]:
                    return ToolResult.success(f"Lernlauf fertig - nichts Neues ({bericht['offen']} offene Fragen).")
                return ToolResult.success("Gelernt:\n" + "\n".join(f"- {g}" for g in bericht["gelernt"]))
            heute = await asyncio.to_thread(sl.heute_gelernt)
            offen = [e["frage"] for e in await asyncio.to_thread(sl._luecken) if e.get("stand") == "offen"]
            text = ("Heute gelernt:\n" + "\n".join(f"- {g}" for g in heute)) if heute else "Heute noch nichts Neues gelernt."
            if offen:
                text += f"\nNoch offen ({len(offen)}): " + "; ".join(o[:60] for o in offen[-5:])
            return ToolResult.success(text)
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Das Lernen klappte gerade nicht: {fehler}")


def build_wissen_tools() -> list[Tool]:
    try:
        from backend.knowledge.selbstlernen import hintergrund_starten

        hintergrund_starten()
    except Exception:  # noqa: BLE001
        logger.info("Selbstlernen nicht gestartet.", exc_info=True)
    return [WissenErweiternTool(), WissenBestandTool(), SelbstLernenTool()]
