"""Werkzeuge fuer Buchprojekte (23.11.2026): schreiben, notieren, zitieren, exportieren.

Die eigentliche Arbeit steckt in backend.knowledge.buchprojekt; hier stehen
nur die Werkzeuge, mit denen Synapse sie bedient.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

_SCHREIBWEISE = (
    "Schreibweise im Text: Leerzeile = neuer Absatz; '## Titel' = Unterkapitel; "
    "'- ' = Aufzaehlung; '> ' = Blockzitat; **fett**, *kursiv*; Quellenverweis "
    "[@schluessel] oder [@schluessel, S. 12]; Abbildung [BILD: nummer]."
)


def _bp():
    from backend.knowledge import buchprojekt

    return buchprojekt


class _BuchWerkzeug(Tool):
    permission = "write_files"

    async def _lauf(self, funktion, *args, **kwargs) -> ToolResult:
        bp = _bp()
        try:
            return ToolResult.success(await asyncio.to_thread(funktion, *args, **kwargs))
        except bp.BuchFehler as fehler:
            return ToolResult.failure(str(fehler))
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Buchwerkzeug %s gescheitert.", self.name)
            return ToolResult.failure(f"Das ging schief: {fehler}")


class BuchAnlegenTool(_BuchWerkzeug):
    name = "buch_anlegen"
    description = (
        "Legt ein Buchprojekt an (oder aktualisiert ein vorhandenes mit gleichem "
        "Titel: Autor, Untertitel, Gliederung). 'gliederung' = Kapitel mit "
        "Unterkapiteln in der Form 'Kapitel A: Unter 1; Unter 2 | Kapitel B: "
        "Unter 1; Unter 2'. Uebernimm dabei ALLE Kapitel und Unterkapitel, die "
        "Marc im Gespraech festgelegt hat - vollstaendig, in seinen Worten. "
        "Danach schreibst du Kapitel mit kapitel_schreiben."
    )
    parameters = (
        ToolParameter("titel", "string", "Titel des Buchs."),
        ToolParameter("gliederung", "string", "Kapitel: Unterkapitel; ... | naechstes Kapitel: ...",
                      required=False, default=""),
        ToolParameter("untertitel", "string", "Untertitel.", required=False, default=""),
        ToolParameter("autor", "string", "Autor.", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            titel = str(arguments.get("titel") or "")
            gliederung = str(arguments.get("gliederung") or arguments.get("kapitel") or "")
            try:
                daten = bp.anlegen(titel, untertitel=str(arguments.get("untertitel") or ""),
                                   autor=str(arguments.get("autor") or "Marc"))
                kopf = "Buchprojekt angelegt."
            except bp.BuchFehler:
                # 23.11.2026: Gibt es das Buch schon, wird es aktualisiert statt abgewiesen.
                daten = bp.laden(titel)
                kopf = "Das Buch gab es schon - aktualisiert."
            for feld in ("autor", "untertitel"):
                wert = str(arguments.get(feld) or "").strip()
                # "Marc" ueberschreibt nie den vollen Namen (am 23.11. wurde so
                # aus "Marc Eichberg" wieder "Marc").
                if wert and not (feld == "autor" and wert.lower() in daten.get("autor", "").lower()):
                    daten[feld] = wert
            bp.speichern(daten)
            ort = f"\nDas Dokument liegt in: {bp.ausgabe_ordner()}"
            if gliederung.strip():
                return kopf + "\n" + bp.gliederung_setzen(daten, gliederung) + ort
            return kopf + "\n" + bp.uebersicht(daten, mit_unterkapiteln=True) + ort

        return await self._lauf(tun)


class GliederungSetzenTool(_BuchWerkzeug):
    name = "gliederung_setzen"
    description = (
        "Setzt oder aendert die Gliederung (Inhaltsverzeichnis) des Buchs: alle "
        "Kapitel mit ihren Unterkapiteln, Form 'Kapitel A: Unter 1; Unter 2 | "
        "Kapitel B: ...'. Benutze das IMMER, wenn Marc Kapitel oder Unterkapitel "
        "festlegt oder aendert ('nimm das ins Inhaltsverzeichnis', 'uebernimm "
        "das'). Gib die vollstaendige Gliederung an; vorhandener Text bleibt "
        "erhalten. Sag nie, du haettest etwas ins Buch uebernommen, ohne dieses "
        "Werkzeug benutzt zu haben."
    )
    parameters = (
        ToolParameter("gliederung", "string", "Vollstaendige Gliederung."),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            daten = bp.laden(str(arguments.get("buch") or ""))
            return bp.gliederung_setzen(daten, str(arguments.get("gliederung") or "")) + f"\nDas Dokument liegt in: {bp.ausgabe_ordner()}"

        return await self._lauf(tun)


class BuchUebersichtTool(_BuchWerkzeug):
    name = "buch_uebersicht"
    description = (
        "Zeigt die Gliederung eines Buchprojekts (Kapitel, Wortzahl, Notizen, "
        "Quellen, Abbildungen) oder - ohne Angabe und wenn keines aktiv ist - "
        "alle Buchprojekte. 'buch' leer = das zuletzt bearbeitete."
    )
    permission = "read_files"
    parameters = (ToolParameter("buch", "string", "Titel des Buchs (optional).", required=False, default=""),)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            try:
                return bp.uebersicht(bp.laden(str(arguments.get("buch") or "")), mit_unterkapiteln=True)
            except bp.BuchFehler:
                alle = bp.alle_buecher()
                if not alle:
                    raise
                return "Buchprojekte: " + "; ".join(b["titel"] for b in alle)

        return await self._lauf(tun)


class KapitelSchreibenTool(_BuchWerkzeug):
    name = "kapitel_schreiben"
    description = (
        "Schreibt oder ueberarbeitet ein Kapitel im Buchprojekt. Du verfasst den "
        "Text selbst - ausgearbeitet, in Marcs Ton, sachlich korrekt. 'kapitel' = "
        "Nummer oder Titel; 'modus': 'anhaengen' (Standard), 'ersetzen' (ganzes "
        "Kapitel neu), 'neu' (neues Kapitel, 'kapitel' = sein Titel), "
        "'umbenennen' ('text' = neuer Titel). Zitiere nur aus Quellen, die mit "
        "quelle_hinzufuegen erfasst sind, und woertlich nur, was du wirklich "
        "gelesen hast; Seitenzahlen nie erfinden. Lies vor dem Ueberarbeiten "
        "mit kapitel_lesen. " + _SCHREIBWEISE
    )
    parameters = (
        ToolParameter("kapitel", "string", "Kapitelnummer oder -titel."),
        ToolParameter("text", "string", "Der Kapiteltext in der Schreibweise oben."),
        ToolParameter("modus", "string", "anhaengen, ersetzen, neu oder umbenennen.", required=False,
                      default="anhaengen", choices=("anhaengen", "ersetzen", "neu", "umbenennen")),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            daten = bp.laden(str(arguments.get("buch") or ""))
            return bp.kapitel_schreiben(daten, str(arguments.get("kapitel") or ""), str(arguments.get("text") or ""),
                                        modus=str(arguments.get("modus") or "anhaengen"))

        return await self._lauf(tun)


class KapitelLesenTool(_BuchWerkzeug):
    name = "kapitel_lesen"
    description = (
        "Liest ein Kapitel samt Notizen vor dem Ueberarbeiten oder Weiterschreiben "
        "- oder mit kapitel 'notizen' alle Notizen zum Buch, mit 'quellen' das "
        "Quellenverzeichnis mit den Schluesseln fuer [@...]."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("kapitel", "string", "Nummer, Titel, 'notizen' oder 'quellen'."),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            daten = bp.laden(str(arguments.get("buch") or ""))
            angabe = str(arguments.get("kapitel") or "").strip()
            if angabe.lower() == "quellen":
                if not daten["quellen"]:
                    return "Noch keine Quellen erfasst."
                return "\n".join(f"[@{k}] {bp.literatur_eintrag(q)}" for k, q in daten["quellen"].items())
            if angabe.lower() == "notizen":
                zeilen = [f"- ({n['datum']}) {n['text']}" for n in daten["notizen"]]
                for i, k in enumerate(daten["kapitel"], 1):
                    zeilen += [f"- Kap. {i} ({n['datum']}): {n['text']}" for n in k["notizen"]]
                return "\n".join(zeilen) or "Keine Notizen."
            i = bp.kapitel_finden(daten, angabe)
            k = daten["kapitel"][i]
            notizen = "\n".join(f"- {n['text']}" for n in k["notizen"])
            return (f"Kapitel {i + 1}: {k['titel']}\n\n{k['text'] or '(leer)'}"
                    + (f"\n\nNotizen dazu:\n{notizen}" if notizen else ""))[:12000]

        return await self._lauf(tun)


class BuchNotizTool(_BuchWerkzeug):
    name = "buch_notiz"
    description = (
        "Haelt eine Notiz, Idee oder einen Gedanken zum Buch fest - zu einem "
        "Kapitel oder allgemein. Benutze das bei 'notier dir', 'halt fest', "
        "'Idee fuers Buch'. Schreib Marcs Gedanken moeglichst in seinen Worten auf."
    )
    parameters = (
        ToolParameter("text", "string", "Die Notiz."),
        ToolParameter("kapitel", "string", "Kapitel (optional).", required=False, default=""),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            daten = bp.laden(str(arguments.get("buch") or ""))
            return bp.notiz(daten, str(arguments.get("text") or ""), str(arguments.get("kapitel") or ""))

        return await self._lauf(tun)


class QuelleHinzufuegenTool(_BuchWerkzeug):
    name = "quelle_hinzufuegen"
    description = (
        "Erfasst eine Quelle im Buchprojekt und gibt ihren Schluessel zurueck "
        "(z. B. 'gabriel2013'), den du im Text als [@gabriel2013, S. 12] "
        "verwendest. Nur echte, ueberpruefte Angaben eintragen - nichts "
        "erfinden. Autor als 'Nachname, Vorname; Nachname, Vorname'."
    )
    parameters = (
        ToolParameter("autor", "string", "Autor(en)."),
        ToolParameter("jahr", "string", "Erscheinungsjahr."),
        ToolParameter("titel", "string", "Titel."),
        ToolParameter("verlag", "string", "Verlag (Buch).", required=False, default=""),
        ToolParameter("ort", "string", "Verlagsort.", required=False, default=""),
        ToolParameter("zeitschrift", "string", "Zeitschrift (Artikel).", required=False, default=""),
        ToolParameter("seiten", "string", "Seiten (Artikel).", required=False, default=""),
        ToolParameter("doi", "string", "DOI.", required=False, default=""),
        ToolParameter("url", "string", "Webadresse.", required=False, default=""),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            daten = bp.laden(str(arguments.get("buch") or ""))
            felder = {k: str(arguments.get(k) or "") for k in
                      ("autor", "jahr", "titel", "verlag", "ort", "zeitschrift", "seiten", "doi", "url")}
            if felder["url"] and not felder["doi"]:
                import datetime as _dt

                felder["abgerufen"] = _dt.date.today().strftime("%d.%m.%Y")
            schluessel = bp.quelle_hinzufuegen(daten, **felder)
            return f"Quelle erfasst als [@{schluessel}]: {bp.literatur_eintrag(daten['quellen'][schluessel])}"

        return await self._lauf(tun)


class LiteraturSuchenTool(_BuchWerkzeug):
    name = "literatur_suchen"
    description = (
        "Recherchiert wissenschaftliche Literatur (OpenAlex: ueber 250 Millionen "
        "Buecher und Artikel, frei) mit vollstaendigen Angaben fuer das "
        "Literaturverzeichnis. Mit 'aufnehmen' = Nummern (z. B. '1,3') werden "
        "Treffer gleich als Quellen ins Buch uebernommen. Fuer den Inhalt einer "
        "Quelle lies sie mit webseite_lesen (url/doi), bevor du daraus zitierst."
    )
    permission = "network"
    parameters = (
        ToolParameter("thema", "string", "Suchbegriffe (englisch findet oft mehr)."),
        ToolParameter("anzahl", "integer", "Wie viele Treffer (bis 10).", required=False, default=6),
        ToolParameter("aufnehmen", "string", "Trefferpositionen, die als Quelle ins Buch sollen.", required=False, default=""),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            try:
                anzahl = int(arguments.get("anzahl") or 6)
            except (TypeError, ValueError):
                anzahl = 6
            treffer = bp.literatur_suchen(str(arguments.get("thema") or ""), anzahl=anzahl)
            if not treffer:
                return "Keine Literatur gefunden - versuch andere oder englische Begriffe."
            zeilen = [f"{i}. {bp.literatur_eintrag(t)} (zitiert {t.get('zitiert', 0)}x)"
                      + (f" Volltext: {t['url']}" if t.get("url") else "") for i, t in enumerate(treffer, 1)]
            wahl = [int(x) for x in str(arguments.get("aufnehmen") or "").replace(" ", "").split(",") if x.isdigit()]
            if wahl:
                daten = bp.laden(str(arguments.get("buch") or ""))
                aufgenommen = []
                for n in wahl:
                    if 1 <= n <= len(treffer):
                        felder = {k: v for k, v in treffer[n - 1].items() if k not in ("zitiert", "typ")}
                        aufgenommen.append(f"[@{bp.quelle_hinzufuegen(daten, **felder)}]")
                zeilen.append("Als Quellen aufgenommen: " + ", ".join(aufgenommen))
            return "\n".join(zeilen)

        return await self._lauf(tun)


class BuchBildTool(_BuchWerkzeug):
    name = "buch_bild"
    description = (
        "Fuegt eine Abbildung ins Buch ein. Die Bilddatei erzeugst du vorher mit "
        "bild_erzeugen (Illustration), diagramm_zeichnen (Zahlen), "
        "infografik_erstellen oder bild_suchen (freie Fotos) - deren Pfad gibst "
        "du hier an. Mit 'kapitel' haengt die Abbildung ans Kapitelende; sonst "
        "setzt du [BILD: nummer] selbst an die passende Stelle. Bei gefundenen "
        "Fotos immer die Quelle/Lizenz angeben."
    )
    parameters = (
        ToolParameter("datei", "string", "Pfad der Bilddatei."),
        ToolParameter("beschriftung", "string", "Bildunterschrift."),
        ToolParameter("kapitel", "string", "Kapitel, an dessen Ende sie kommt (optional).", required=False, default=""),
        ToolParameter("quelle", "string", "Bildquelle/Lizenz (z. B. 'Wikimedia Commons, CC BY-SA').",
                      required=False, default=""),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            daten = bp.laden(str(arguments.get("buch") or ""))
            nummer = bp.bild_hinzufuegen(daten, str(arguments.get("datei") or ""),
                                         str(arguments.get("beschriftung") or ""),
                                         kapitel=str(arguments.get("kapitel") or ""),
                                         quelle=str(arguments.get("quelle") or ""))
            ort = "am Kapitelende eingefuegt" if arguments.get("kapitel") else "bereit - setze [BILD: %d] in den Text" % nummer
            return f"Abbildung {nummer} {ort}."

        return await self._lauf(tun)


class BuchExportierenTool(_BuchWerkzeug):
    name = "buch_exportieren"
    description = (
        "Erstellt aus dem Buchprojekt ein OpenOffice-Dokument (.odt) mit "
        "Titelseite, Inhaltsverzeichnis, Kapiteln, Abbildungen, Quellenverweisen "
        "und Literaturverzeichnis, legt es in Dokumente/Synapse-Buecher ab und "
        "oeffnet es. Benutze das bei 'erstell das Dokument', 'zeig mir das Buch', "
        "'exportier'."
    )
    parameters = (
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
        ToolParameter("oeffnen", "boolean", "Danach in OpenOffice oeffnen.", required=False, default=True),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bp = _bp()

        def tun() -> str:
            daten = bp.laden(str(arguments.get("buch") or ""))
            pfad, hinweise = bp.exportieren(daten)
            if arguments.get("oeffnen", True) not in (False, "false", "False", 0) and sys.platform == "win32":
                try:
                    os.startfile(str(pfad))  # type: ignore[attr-defined]
                except OSError:
                    hinweise.append("Kein Programm fuer .odt gefunden - OpenOffice oder LibreOffice installieren")
            hinweis_offen = (" (Die bisherige Fassung war gerade in OpenOffice offen - darum unter neuem Namen.)"
                             if "(Stand " in pfad.name else "")
            text = (f"Dokument erstellt und gespeichert unter: {pfad}{hinweis_offen}\n{bp.uebersicht(daten, mit_unterkapiteln=True)}\n"
                    "Seitenzahlen im Inhaltsverzeichnis: in OpenOffice Extras -> Verzeichnisse -> Aktualisieren.")
            if hinweise:
                text += "\nHinweise: " + "; ".join(hinweise)
            return text

        return await self._lauf(tun)


class LiteraturRechercheTool(_BuchWerkzeug):
    name = "literatur_recherche"
    description = (
        "Macht die Literaturrecherche fuer das Buch: sucht zu JEDEM Unterkapitel "
        "(oder nur zu einem Kapitel) passende Fachliteratur (OpenAlex, deutsch und "
        "englisch, ab 2005), erfasst die Funde als Quellen im Buch, notiert sie "
        "beim Kapitel und schreibt ein eigenes Dokument 'Literaturrecherche - "
        "<Titel>.odt' in Dokumente/Synapse-Buecher, das sich danach oeffnet. "
        "Dauert ein bis drei Minuten und laeuft im Hintergrund. Benutze das bei "
        "'mach eine Literaturrecherche', 'such Quellen fuer Kapitel 2'."
    )
    permission = "network"
    parameters = (
        ToolParameter("kapitel", "string", "Nur dieses Kapitel (Nummer/Titel); leer = ganzes Buch.",
                      required=False, default=""),
        ToolParameter("je_unterkapitel", "integer", "Quellen pro Unterkapitel (1-6).", required=False, default=3),
        ToolParameter("buch", "string", "Titel des Buchs (leer = aktuelles).", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import threading

        bp = _bp()
        try:
            daten = bp.laden(str(arguments.get("buch") or ""))
            kapitel = str(arguments.get("kapitel") or "")
            if kapitel.strip():
                bp.kapitel_finden(daten, kapitel)   # frueh pruefen, damit der Fehler hier ankommt
        except bp.BuchFehler as fehler:
            return ToolResult.failure(str(fehler))
        try:
            je = max(1, min(6, int(arguments.get("je_unterkapitel") or 3)))
        except (TypeError, ValueError):
            je = 3

        def hintergrund() -> None:
            try:
                pfad, bericht = bp.recherche(daten, kapitel=kapitel, je_unterkapitel=je)
                logger.info("Literaturrecherche fertig: %s (%s)", pfad, bericht)
                if sys.platform == "win32":
                    os.startfile(str(pfad))  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                logger.exception("Literaturrecherche gescheitert.")

        threading.Thread(target=hintergrund, name="literaturrecherche", daemon=True).start()
        umfang = f"Kapitel {kapitel}" if kapitel.strip() else "alle Kapitel"
        return ToolResult.success(
            f"Literaturrecherche fuer {umfang} von „{daten['titel']}“ laeuft im Hintergrund "
            f"(ein bis drei Minuten). Danach oeffnet sich das Dokument 'Literaturrecherche - "
            f"{daten['titel']}.odt' in {bp.ausgabe_ordner()}, und die Quellen stehen im Buch. "
            "Sag Marc genau das - behaupte nicht, sie sei schon fertig."
        )


def build_buch_tools() -> list[Tool]:
    return [BuchAnlegenTool(), GliederungSetzenTool(), BuchUebersichtTool(), KapitelSchreibenTool(), KapitelLesenTool(),
            BuchNotizTool(), QuelleHinzufuegenTool(), LiteraturSuchenTool(), LiteraturRechercheTool(), BuchBildTool(),
            BuchExportierenTool()]
