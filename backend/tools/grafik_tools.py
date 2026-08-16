"""Die Werkzeuge fuer Bilder: zeichnen, suchen, erzeugen lassen.

Drei Werkzeuge, die alle dasselbe liefern: den Pfad einer fertigen
Bilddatei. Genau das braucht ``pdf_erstellen`` - damit lassen sich die drei
frei mischen, ohne dass eines vom anderen weiss.

Die Arbeitsteilung dahinter ist bewusst:

* ``diagramm_zeichnen`` rechnet und zeichnet auf dem Rechner. Es kann nicht
  ausfallen und liefert immer dasselbe Bild zu denselben Zahlen.
* ``bild_suchen`` holt ein echtes Foto samt Urheber und Lizenz.
* ``bild_erzeugen`` laesst ein Bild erfinden - nur fuer das, wovon es kein
  Foto geben kann.

Alle drei melden einen Ausfall als sauberes Ergebnis mit Begruendung.
Ein fehlendes Bild darf nie das Dokument verhindern, an dem es haengt.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.grafik import bildquellen
from backend.grafik.diagramm import DiagrammFehler, Reihe, diagramm_zeichnen
from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

_ARTEN = ("balken", "linie", "torte", "punkte")


def _ablage(unterordner: str) -> Path:
    """Wohin erzeugte Bilder kommen: in die Anwendungsdaten, nicht ins Projekt."""

    ordner = get_data_dir() / "grafiken" / unterordner
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _dateiname(text: str, endung: str) -> str:
    schlicht = re.sub(r"[^a-z0-9äöüß]+", "-", (text or "").lower()).strip("-")[:48]
    stempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{schlicht or 'bild'}-{stempel}{endung}"


def _zahlen(werte: Any) -> list[float]:
    """Macht aus dem, was ein Sprachmodell schickt, eine Zahlenreihe.

    Modelle liefern Zahlen mal als Zahl, mal als Zeichenkette, mal mit
    Einheit ("42 %") oder deutschem Komma ("3,5"). All das hier abzufangen
    ist keine Nachsicht, sondern der Unterschied zwischen einem Diagramm und
    einer Fehlermeldung.
    """

    if isinstance(werte, (int, float)):
        werte = [werte]
    if isinstance(werte, str):
        werte = re.split(r"[;,]\s*(?=[-+]?\d)|\s{2,}", werte.strip())

    ergebnis: list[float] = []
    for eintrag in list(werte or []):
        if isinstance(eintrag, (int, float)):
            ergebnis.append(float(eintrag))
            continue
        text = str(eintrag).strip()
        treffer = re.search(r"[-+]?\d[\d.\s]*(?:,\d+)?|[-+]?\d*\.\d+", text)
        if not treffer:
            ergebnis.append(0.0)
            continue
        roh = treffer.group(0).replace(" ", "")
        if "," in roh:
            # Deutsch: Punkt trennt Tausender, Komma die Dezimale.
            roh = roh.replace(".", "").replace(",", ".")
        elif roh.count(".") > 1:
            # "1.234.567" kann nur eine Tausendergliederung sein.
            roh = roh.replace(".", "")
        # Ein einzelner Punkt bleibt ein Dezimalpunkt. "1.234" ist zwar auch
        # als deutsche Tausendergliederung lesbar, aber Sprachmodelle
        # schreiben Zahlen in der englischen Form - und 3.142 als
        # dreitausend zu lesen waere der schlimmere Fehler.
        try:
            ergebnis.append(float(roh))
        except ValueError:
            ergebnis.append(0.0)
    return ergebnis


def _texte(werte: Any) -> list[str]:
    if isinstance(werte, str):
        return [t.strip() for t in re.split(r"[;,]", werte) if t.strip()]
    return [str(t).strip() for t in list(werte or []) if str(t).strip()]


def _reihen_lesen(argumente: dict[str, Any], anzahl_kategorien: int) -> list[Reihe]:
    """Liest die Datenreihen - egal in welcher der ueblichen Formen sie kommen."""

    roh = argumente.get("reihen")
    reihen: list[Reihe] = []

    if isinstance(roh, dict):
        roh = [{"name": name, "werte": werte} for name, werte in roh.items()]

    for eintrag in list(roh or []):
        if isinstance(eintrag, dict):
            name = str(
                eintrag.get("name") or eintrag.get("titel") or eintrag.get("label") or ""
            ).strip()
            werte = _zahlen(eintrag.get("werte") or eintrag.get("values") or eintrag.get("daten"))
            if werte:
                reihen.append(Reihe(name=name or f"Reihe {len(reihen) + 1}", werte=werte))
        elif isinstance(eintrag, (list, tuple)):
            reihen.append(Reihe(name=f"Reihe {len(reihen) + 1}", werte=_zahlen(eintrag)))

    if reihen:
        return reihen

    # Der haeufige einfache Fall: eine einzelne Werteliste.
    werte = _zahlen(argumente.get("werte") or argumente.get("daten"))
    if werte:
        name = str(argumente.get("reihenname") or argumente.get("einheit") or "Wert").strip()
        return [Reihe(name=name or "Wert", werte=werte[:anzahl_kategorien] or werte)]
    return []


class ZeichneDiagrammTool(Tool):
    """Zeichnet ein Diagramm aus Zahlen und legt es als PNG ab."""

    name = "diagramm_zeichnen"
    description = (
        "Zeichnet aus Zahlen ein Diagramm (Balken, Linie, Torte oder Punkte) und "
        "speichert es als Bilddatei. Benutze dieses Werkzeug immer, wenn Zahlen "
        "anschaulich werden sollen - besonders bevor du eine PDF erstellst: Den "
        "zurueckgegebenen Pfad gibst du dann bei 'pdf_erstellen' unter 'bilder' an "
        "oder schreibst ihn als [BILD: pfad] an die passende Stelle im Inhalt. "
        "Laeuft ohne Internet und ohne Konto. 'kategorien' sind die Beschriftungen "
        "(z.B. Monate), 'werte' die Zahlen dazu. Fuer mehrere Datenreihen "
        "stattdessen 'reihen' angeben."
    )
    permission = "write_files"
    parameters = (
        ToolParameter(
            "art", "string", "Diagrammart.",
            required=False, default="balken", choices=_ARTEN,
        ),
        ToolParameter("titel", "string", "Ueberschrift des Diagramms."),
        ToolParameter(
            "kategorien", "array",
            "Beschriftungen der waagerechten Achse, z.B. ['Jan','Feb','Mrz'].",
        ),
        ToolParameter(
            "werte", "array",
            "Die Zahlen zu den Kategorien, bei einer einzelnen Datenreihe.",
            required=False, default=[],
        ),
        ToolParameter(
            "reihen", "array",
            "Mehrere Datenreihen als [{'name': 'Berlin', 'werte': [1,2,3]}, ...].",
            required=False, default=[],
        ),
        ToolParameter(
            "einheit", "string", "Einheit hinter den Achsenzahlen, z.B. '%' oder 'EUR'.",
            required=False, default="",
        ),
        ToolParameter(
            "achse_x", "string", "Beschriftung der waagerechten Achse.",
            required=False, default="",
        ),
        ToolParameter(
            "achse_y", "string", "Beschriftung der Werteachse.",
            required=False, default="",
        ),
        ToolParameter(
            "quelle", "string", "Woher die Zahlen stammen. Steht als Fussnote im Bild.",
            required=False, default="",
        ),
        ToolParameter(
            "pfad", "string", "Optionaler Zielpfad mit .png-Endung.",
            required=False, default="",
        ),
    )

    def __init__(self, security: SecurityEngine) -> None:
        self._security = security

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        titel = str(arguments.get("titel", "") or "").strip()
        kategorien = _texte(arguments.get("kategorien"))
        if not kategorien:
            return ToolResult.failure(
                "Es fehlen die Kategorien - also die Beschriftungen der Achse."
            )

        reihen = _reihen_lesen(arguments, len(kategorien))
        if not reihen:
            return ToolResult.failure(
                "Es fehlen die Zahlen. Gib 'werte' an, oder 'reihen' fuer mehrere Reihen."
            )

        gewuenscht = str(arguments.get("pfad", "") or "").strip()
        if gewuenscht:
            ziel = Path(gewuenscht)
            if ziel.suffix.lower() != ".png":
                ziel = ziel.with_suffix(".png")
            entscheidung = self._security.paths.check_write(ziel)
            if not entscheidung.allowed:
                return ToolResult.failure(entscheidung.reason)
            ziel = entscheidung.path
        else:
            ziel = _ablage("diagramme") / _dateiname(titel, ".png")

        try:
            pfad = await asyncio.to_thread(
                diagramm_zeichnen,
                art=str(arguments.get("art", "balken") or "balken"),
                titel=titel,
                kategorien=kategorien,
                reihen=reihen,
                ziel=ziel,
                achse_x=str(arguments.get("achse_x", "") or ""),
                achse_y=str(arguments.get("achse_y", "") or ""),
                einheit=str(arguments.get("einheit", "") or ""),
                quelle=str(arguments.get("quelle", "") or ""),
            )
        except DiagrammFehler as fehler:
            return ToolResult.failure(str(fehler))
        except RuntimeError as fehler:
            return ToolResult.failure(str(fehler))
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Diagramm konnte nicht gezeichnet werden.")
            return ToolResult.failure(f"Das Diagramm liess sich nicht zeichnen: {fehler}")

        return ToolResult.success(
            f"Das Diagramm wurde gezeichnet: {pfad}. Diesen Pfad kannst du bei "
            f"'pdf_erstellen' unter 'bilder' angeben oder als [BILD: {pfad}] in "
            f"den Inhalt schreiben.",
            pfad=str(pfad),
            art=str(arguments.get("art", "balken") or "balken"),
            reihen=len(reihen),
            kategorien=len(kategorien),
        )


class SucheBildTool(Tool):
    """Sucht freie Fotos und laedt sie herunter."""

    name = "bild_suchen"
    description = (
        "Sucht echte, frei verwendbare Fotos zu einem Begriff (Wikimedia Commons "
        "und Openverse) und laedt sie herunter. Gibt die lokalen Pfade und je "
        "einen Nachweis mit Urheber und Lizenz zurueck. Benutze das fuer Bilder "
        "von Dingen, die es wirklich gibt - Orte, Bauwerke, Personen der "
        "Zeitgeschichte, Tiere, Pflanzen. Den Nachweis immer als Bildunterschrift "
        "mitgeben. Braucht kein Konto und keinen Schluessel."
    )
    permission = "network"
    parameters = (
        ToolParameter("begriff", "string", "Wonach gesucht wird, z.B. 'Brandenburger Tor'."),
        ToolParameter(
            "anzahl", "integer", "Wie viele Bilder hoechstens (1 bis 5).",
            required=False, default=2,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        begriff = str(arguments.get("begriff", "") or "").strip()
        if not begriff:
            return ToolResult.failure("Es fehlt der Suchbegriff.")
        try:
            anzahl = max(1, min(int(arguments.get("anzahl", 2) or 2), 5))
        except (TypeError, ValueError):
            anzahl = 2

        treffer = await asyncio.to_thread(bildquellen.bilder_suchen, begriff, anzahl=anzahl)
        if not treffer:
            return ToolResult.failure(
                f"Zu '{begriff}' waren keine freien Bilder zu finden. Moeglich ist "
                f"auch, dass die Bilddienste gerade nicht antworten. Mit einem "
                f"anderen Begriff nochmal versuchen - oder ohne Bild weitermachen."
            )

        ordner = _ablage("fotos")
        gefunden: list[dict[str, Any]] = []
        for stelle, eintrag in enumerate(treffer, start=1):
            ziel = ordner / _dateiname(f"{begriff}-{stelle}", ".jpg")
            pfad = await asyncio.to_thread(bildquellen.bild_holen, eintrag, ziel)
            if pfad is None:
                continue
            datensatz = eintrag.to_dict()
            datensatz["pfad"] = str(pfad)
            gefunden.append(datensatz)

        if not gefunden:
            return ToolResult.failure(
                f"Zu '{begriff}' gab es Treffer, aber keiner liess sich "
                f"herunterladen. Ohne Bild weitermachen."
            )

        zeilen = [
            f"{i}. {eintrag['pfad']}\n   Bildunterschrift: {eintrag['nachweis']}"
            for i, eintrag in enumerate(gefunden, start=1)
        ]
        return ToolResult.success(
            f"{len(gefunden)} Bild(er) zu '{begriff}' geladen:\n" + "\n".join(zeilen)
            + "\n\nDie Pfade kannst du bei 'pdf_erstellen' unter 'bilder' angeben "
              "oder als [BILD: pfad] in den Inhalt schreiben. Den Nachweis bitte "
              "als Bildunterschrift uebernehmen.",
            bilder=gefunden,
            pfad=gefunden[0]["pfad"],
        )


class ErzeugeBildTool(Tool):
    """Laesst aus einer Beschreibung ein Bild erzeugen."""

    name = "bild_erzeugen"
    description = (
        "Laesst aus einer Beschreibung ein Bild erzeugen (Illustration, Titelbild, "
        "Sinnbild) und speichert es. Benutze das NUR, wenn es kein echtes Foto "
        "geben kann - fuer alles Wirkliche ist 'bild_suchen' richtig, und fuer "
        "Zahlen 'diagramm_zeichnen'. Die Beschreibung ausfuehrlich auf Englisch "
        "formulieren, das ergibt bessere Bilder. Der Dienst ist kostenfrei und "
        "antwortet nicht immer; faellt er aus, kommt eine Meldung und du machst "
        "ohne Bild weiter."
    )
    permission = "network"
    parameters = (
        ToolParameter(
            "beschreibung", "string",
            "Was auf dem Bild zu sehen sein soll, ausfuehrlich und moeglichst englisch.",
        ),
        ToolParameter(
            "stil", "string",
            "Optionaler Stil, z.B. 'watercolor illustration' oder 'technical diagram'.",
            required=False, default="",
        ),
        ToolParameter(
            "breite", "integer", "Bildbreite in Bildpunkten.",
            required=False, default=1024,
        ),
        ToolParameter(
            "hoehe", "integer", "Bildhoehe in Bildpunkten.",
            required=False, default=640,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        beschreibung = str(arguments.get("beschreibung", "") or "").strip()
        if not beschreibung:
            return ToolResult.failure("Es fehlt die Beschreibung des Bildes.")

        def _ganzzahl(name: str, standard: int) -> int:
            try:
                return int(arguments.get(name, standard) or standard)
            except (TypeError, ValueError):
                return standard

        ziel = _ablage("erzeugt") / _dateiname(beschreibung, ".jpg")
        pfad = await asyncio.to_thread(
            bildquellen.bild_erzeugen,
            beschreibung,
            ziel,
            breite=_ganzzahl("breite", 1024),
            hoehe=_ganzzahl("hoehe", 640),
            stil=str(arguments.get("stil", "") or ""),
        )
        if pfad is None:
            return ToolResult.failure(
                "Der Bilddienst hat nicht geantwortet. Das kommt bei dem "
                "kostenfreien Dienst vor. Entweder gleich nochmal versuchen oder "
                "ohne Bild weitermachen - das Dokument soll daran nicht haengen."
            )

        nachweis = "Erzeugtes Bild (kein Foto)"
        return ToolResult.success(
            f"Das Bild wurde erzeugt: {pfad}. Bildunterschrift: {nachweis}. "
            f"Den Pfad kannst du bei 'pdf_erstellen' unter 'bilder' angeben oder "
            f"als [BILD: {pfad}] in den Inhalt schreiben.",
            pfad=str(pfad),
            nachweis=nachweis,
            beschreibung=beschreibung,
        )


def build_grafik_tools(security: SecurityEngine) -> list[Tool]:
    return [ZeichneDiagrammTool(security), SucheBildTool(), ErzeugeBildTool()]
