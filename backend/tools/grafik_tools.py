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
from backend.grafik.infografik import infografik_zeichnen
from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

_ARTEN = ("balken", "linie", "torte", "punkte")

# Vorkompilierte Regex für bessere Performance
_NUMBER_PATTERN = re.compile(r"[-+]?\d[\d.\s]*(?:,\d+)?|[-+]?\d*\.\d+")
_SPLIT_PATTERN = re.compile(r"[;,]\s*(?=[-+]?\d)|\s{2,}")
_NAME_CLEANUP_PATTERN = re.compile(r"[^a-z0-9äöüß]+")


def _ablage(unterordner: str) -> Path:
    """Wohin erzeugte Bilder kommen: in die Anwendungsdaten, nicht ins Projekt."""

    ordner = get_data_dir() / "grafiken" / unterordner
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _dateiname(text: str, endung: str) -> str:
    schlicht = _NAME_CLEANUP_PATTERN.sub("-", (text or "").lower()).strip("-")[:48]
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
        return [float(werte)]
    
    if isinstance(werte, str):
        werte = _SPLIT_PATTERN.split(werte.strip())
    else:
        werte = list(werte or [])

    ergebnis: list[float] = []
    for eintrag in werte:
        if isinstance(eintrag, (int, float)):
            ergebnis.append(float(eintrag))
            continue
            
        text = str(eintrag).strip()
        treffer = _NUMBER_PATTERN.search(text)
        if not treffer:
            ergebnis.append(0.0)
            continue
            
        roh = treffer.group(0).replace(" ", "")
        # Normalisiere deutsche Zahlenformate
        if "," in roh:
            roh = roh.replace(".", "").replace(",", ".")
        elif roh.count(".") > 1:
            roh = roh.replace(".", "")
        
        try:
            ergebnis.append(float(roh))
        except ValueError:
            ergebnis.append(0.0)
    return ergebnis


def _texte(werte: Any) -> list[str]:
    if isinstance(werte, str):
        return [t.strip() for t in re.split(r"[;,]", werte) if t.strip()]
    return [str(t).strip() for t in (werte or []) if str(t).strip()]


def _reihen_lesen(argumente: dict[str, Any], anzahl_kategorien: int) -> list[Reihe]:
    """Liest die Datenreihen - egal in welcher der ueblichen Formen sie kommen."""

    roh = argumente.get("reihen")
    reihen: list[Reihe] = []

    if isinstance(roh, dict):
        roh = [{"name": name, "werte": werte} for name, werte in roh.items()]

    for eintrag in (roh or []):
        if isinstance(eintrag, dict):
            name = (
                str(eintrag.get("name") or eintrag.get("titel") or eintrag.get("label") or "")
                .strip()
            )
            werte = _zahlen(
                eintrag.get("werte") or eintrag.get("values") or eintrag.get("daten")
            )
            if werte:
                reihen.append(
                    Reihe(name=name or f"Reihe {len(reihen) + 1}", werte=werte)
                )
        elif isinstance(eintrag, (list, tuple)):
            reihen.append(Reihe(name=f"Reihe {len(reihen) + 1}", werte=_zahlen(eintrag)))

    if reihen:
        return reihen

    # Der haeufige einfache Fall: eine einzelne Werteliste.
    werte = _zahlen(argumente.get("werte") or argumente.get("daten"))
    if werte:
        name = str(
            argumente.get("reihenname") or argumente.get("einheit") or "Wert"
        ).strip()
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


class ErzeugeInfografikTool(Tool):
    """Baut aus Erklaertext eine lokale, hochwertige Uebersichtsgrafik."""

    name = "infografik_erstellen"
    description = (
        "Erstellt aus einem Titel und gegliedertem Erklaertext eine moderne "
        "hochaufgeloeste Infografik als PNG. Benutze sie fuer konzeptionelle, "
        "historische oder wissenschaftliche Erklaerungen und fuer grafisch "
        "hochwertige PDFs; sie arbeitet lokal und braucht keinen Bilddienst."
    )
    permission = "write_files"
    parameters = (
        ToolParameter("titel", "string", "Titel der Infografik."),
        ToolParameter(
            "inhalt", "string",
            "Gegliederter Inhalt; Markdown-Ueberschriften werden zu Karten.",
        ),
        ToolParameter(
            "quelle", "string", "Optionale Quellenzeile.",
            required=False, default="",
        ),
        ToolParameter(
            "layout", "string",
            "Darstellung: 'karten' oder 'konzept' mit zentralem Zusammenhang.",
            required=False, default="karten",
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
        inhalt = str(arguments.get("inhalt", "") or "").strip()
        if not titel:
            return ToolResult.failure("Der Titel der Infografik fehlt.")
        if len(inhalt) < 40:
            return ToolResult.failure("Der Inhalt ist zu kurz fuer eine Infografik.")

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
            ziel = _ablage("infografiken") / _dateiname(titel, ".png")

        try:
            pfad = await asyncio.to_thread(
                infografik_zeichnen,
                titel=titel,
                inhalt=inhalt,
                ziel=ziel,
                quelle=str(arguments.get("quelle", "") or ""),
                layout=str(arguments.get("layout", "karten") or "karten"),
            )
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Infografik konnte nicht gezeichnet werden.")
            return ToolResult.failure(f"Die Infografik liess sich nicht zeichnen: {fehler}")

        return ToolResult.success(
            f"Die Infografik wurde erstellt: {pfad}. Fuer eine PDF diesen "
            "Pfad bei 'pdf_erstellen' unter 'bilder' angeben.",
            pfad=str(pfad),
            nachweis="Infografik: AI-Orb",
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
        ToolParameter(
            "relevanz", "string",
            "Optionaler fachlicher Begriff, der in Titel oder Nachweis vorkommen muss.",
            required=False, default="",
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

        relevanz = str(arguments.get("relevanz", "") or "").strip()
        akzeptieren = None
        if relevanz:
            from backend.studium.vorlesungs_bilder import bild_passt

            akzeptieren = lambda eintrag: bild_passt(relevanz, eintrag.to_dict())
        treffer = await asyncio.to_thread(
            bildquellen.bilder_suchen,
            begriff,
            anzahl=anzahl,
            akzeptieren=akzeptieren,
        )
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
            + "\n\nWill der Benutzer die Bilder SEHEN, rufe jetzt 'bild_zeigen' "
              "mit diesen Pfaden auf. Fuer Dokumente kannst du die Pfade bei "
              "'pdf_erstellen' unter 'bilder' angeben oder als [BILD: pfad] in "
              "den Inhalt schreiben. Den Nachweis bitte als Bildunterschrift "
              "uebernehmen.",
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
            f"Will der Benutzer es SEHEN, rufe jetzt 'bild_zeigen' mit diesem "
            f"Pfad auf. Fuer Dokumente kannst du den Pfad bei 'pdf_erstellen' "
            f"unter 'bilder' angeben oder als [BILD: {pfad}] in den Inhalt "
            f"schreiben.",
            pfad=str(pfad),
            nachweis=nachweis,
            beschreibung=beschreibung,
        )


class ZeigeBilderTool(Tool):
    """Zeigt Bilddateien gross auf dem Bildschirm an.

    Der Anlass steht im Protokoll vom 19.08.2026, 15:14 Uhr: Der Orb hatte
    zwei Golderz-Fotos heruntergeladen und sagte dann - "Die Bilder kann
    ich dir nicht direkt oeffnen lassen, weil ich keine Anzeige fuer
    Bilddateien implementiert habe." Er hatte recht: bild_suchen und
    bild_erzeugen legten Dateien ab, aber KEIN Werkzeug zeigte sie. Der
    Benutzer bekam Pfade vorgelesen statt Bilder gezeigt - und meldete es
    zu Recht als seit langem ungeloest.

    Angezeigt wird ueber die vorhandene Bildschirmpraesentation: eine
    Folie je Bild, eingebettet in eine einzige HTML-Datei, geoeffnet im
    Standardbrowser. Bewusst OHNE Playwright - das fehlt auf dem Rechner,
    und eine Anzeige, die daran scheitert, waere wieder keine.
    """

    name = "bild_zeigen"
    description = (
        "Zeigt ein oder mehrere Bilder vom Rechner GROSS auf dem Bildschirm "
        "(im Browser, mit Pfeiltasten blaetterbar). Benutze das IMMER, wenn "
        "der Benutzer ein Bild sehen will - nach 'bild_suchen', "
        "'bild_erzeugen' oder 'diagramm_zeichnen' mit deren Pfaden, oder "
        "mit jeder Bilddatei, deren Pfad du kennst. Pfade NIE nur vorlesen: "
        "Wer ein Bild will, will es sehen."
    )
    parameters = (
        ToolParameter(
            "pfade", "string",
            "Ein Bildpfad oder mehrere, getrennt durch Zeilenumbruch, "
            "Semikolon oder Komma.",
        ),
        ToolParameter(
            "titel", "string", "Ueberschrift der Bilderschau.",
            required=False, default="",
        ),
        ToolParameter(
            "unterschrift", "string",
            "Bildunterschrift bzw. Nachweis (gilt fuer alle gezeigten Bilder).",
            required=False, default="",
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        angabe = str(arguments.get("pfade", "") or "").strip()
        if not angabe:
            return ToolResult.failure("Es fehlt der Pfad des Bildes.")

        pfade = [
            Path(teil.strip().strip("'\""))
            for teil in re.split(r"[\n;,|]+", angabe)
            if teil.strip()
        ]
        vorhanden = [p for p in pfade if p.is_file()]
        fehlend = [p for p in pfade if not p.is_file()]
        if not vorhanden:
            return ToolResult.failure(
                "Keine der Dateien liegt an ihrem Pfad: "
                + "; ".join(str(p) for p in fehlend)
                + ". Erst mit 'bild_suchen' oder 'bild_erzeugen' beschaffen "
                "- oder den Pfad pruefen."
            )

        from backend.studium.praesentation import Folie, Praesentation

        titel = str(arguments.get("titel", "") or "").strip() or "Bilder"
        nachweis = str(arguments.get("unterschrift", "") or "").strip()
        schau = Praesentation(titel=titel)
        for pfad in vorhanden:
            schau.hinzufuegen(
                Folie(
                    art="bild",
                    titel=pfad.stem.replace("-", " ").replace("_", " "),
                    bild=str(pfad),
                    bildnachweis=nachweis,
                )
            )

        ziel = _ablage("bilderschau") / _dateiname(titel, ".html")
        try:
            await asyncio.to_thread(schau.speichern, ziel)
        except Exception as fehler:  # noqa: BLE001 - dem Modell sagen, nicht wuergen.
            return ToolResult.failure(f"Die Bilderschau liess sich nicht bauen: {fehler}")

        geoeffnet = await asyncio.to_thread(_im_browser_oeffnen, ziel)
        if not geoeffnet:
            return ToolResult.failure(
                f"Die Bilderschau liegt unter {ziel}, aber der Browser liess "
                "sich nicht oeffnen. Sag dem Benutzer den Pfad."
            )

        hinweis = ""
        if fehlend:
            hinweis = (
                " Nicht gefunden und deshalb nicht dabei: "
                + "; ".join(str(p) for p in fehlend)
            )
        return ToolResult.success(
            f"{len(vorhanden)} Bild(er) werden jetzt im Browser gezeigt "
            f"({titel}). Mit den Pfeiltasten laesst sich blaettern."
            + hinweis,
            pfad=str(ziel),
            gezeigt=[str(p) for p in vorhanden],
        )


def _im_browser_oeffnen(pfad: Path) -> bool:
    """Oeffnet eine Datei im Standardbrowser - ohne Playwright."""

    import webbrowser

    try:
        return webbrowser.open(f"file:///{str(pfad).lstrip('/')}", new=2)
    except Exception:  # noqa: BLE001
        logger.exception("Die Bilderschau liess sich nicht oeffnen.")
        return False


def build_grafik_tools(security: SecurityEngine) -> list[Tool]:
    return [
        ZeichneDiagrammTool(security),
        ErzeugeInfografikTool(security),
        SucheBildTool(),
        ErzeugeBildTool(),
        ZeigeBilderTool(),
    ]
