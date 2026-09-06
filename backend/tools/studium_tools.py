"""Die Werkzeuge des Professors - der Weg von der Stimme zum Wissen.

## Warum das die wichtigste Datei dieses Umbaus ist

Der Orb hatte schon einen Professor-Apparat: 3.500 Zeilen unter
``backend/agents/history_agent``, mit Sokratik, Prüfungsmaschine und
Lernprofil. Er hat seit dem 9. August dreimal gefeuert. Die
Prüfungsmaschine wurde nie erreicht, das Lernprofil nie gefüttert.

Der Grund war nicht schlechter Code. Der Grund war, dass es keinen Weg
von einer gesprochenen Äusserung dorthin gab - kein Werkzeug, das das
Sprachmodell hätte aufrufen können. Was ein Modell nicht aufrufen kann,
gibt es für den Benutzer nicht.

## Was hier bewusst FEHLT

Ein Werkzeug zum Abfragen. Es gab eines, und der Benutzer hat es
zurückgewiesen: „Der Orb soll auch nicht einfach plump irgendwelche Tests
mit mir machen." Den Stand liest der Orb jetzt aus dem Gespräch mit -
das geschieht im Orchestrator bei jeder Äusserung und braucht keinen
Werkzeugaufruf. Hier steht nur noch, was das Modell aus eigenem Antrieb
tun können muss: nachsehen, notieren, zeigen.
"""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from typing import Any

from backend.studium.landkarte import (
    TIEFEN,
    TIEFEN_KLARTEXT,
    feld as feld_holen,
    feld_suchen,
    felder,
    thema_suchen,
)
from backend.studium.lernstand import Lernstand
from backend.studium.praesentation import Folie, Praesentation
from backend.studium.vorlesungs_bilder import (
    bild_passt,
    bild_treffer_bewerten,
    bildsuchbegriffe,
    folienpunkte_bereinigen,
)
from backend.studium.zeigen import lohnt_sich
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


def _feld_finden(angabe: str, text: str = ""):
    if angabe:
        gefunden = feld_holen(angabe.strip().lower()) or feld_suchen(angabe)
        if gefunden is not None:
            return gefunden
    return feld_suchen(text) if text else None


class Nachsehen(Tool):
    """Was zu einem Thema gehört und was daran hängt."""

    name = "wissen_nachsehen"
    description = (
        "Sieht in der Wissenslandkarte nach: worum es bei einem Thema geht, "
        "was man dafür braucht, wohin es weiterführt, welche Fachbegriffe "
        "dazugehören und was der Benutzer davon schon berührt hat. Nimm es, "
        "BEVOR du ein Fachthema erklärst - dann weisst du, woran du "
        "anknüpfen kannst und was du noch nicht voraussetzen darfst. Ohne "
        "Angabe eines Themas nennt es die Felder, die der Orb überblickt."
    )
    parameters = (
        ToolParameter("thema", "string", "Thema oder Stichwort.", required=False),
        ToolParameter("feld", "string", "Fachgebiet, falls nicht eindeutig.",
                      required=False),
    )

    def __init__(self, lernstand: Lernstand, aktualisierung: Any = None) -> None:
        self._lernstand = lernstand
        self._aktualisierung = aktualisierung

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        angabe = str(arguments.get("thema", "") or "").strip()
        if not angabe:
            return ToolResult.success(self._felder_nennen())

        treffer = thema_suchen(angabe)
        if treffer is None:
            das_feld = _feld_finden(str(arguments.get("feld", "") or ""), angabe)
            if das_feld is None:
                return ToolResult.success(
                    f"Zu {angabe!r} habe ich nichts in der Landkarte. Das heisst "
                    "NICHT, dass du nichts dazu sagen kannst - erklär es aus "
                    "deinem eigenen Wissen. Es heisst nur, dass ich dir hier "
                    "keine Anknüpfungspunkte liefern kann.\n\n"
                    + self._felder_nennen()
                )
            return ToolResult.success(self._feld_zeigen(das_feld))

        das_feld, das_thema = treffer
        beruehrt = self._lernstand.beruehrt(das_feld.kennung)
        fehlt = das_feld.was_fehlt(das_thema.kennung, beruehrt)
        umfeld = das_feld.nachbarschaft(das_thema.kennung)
        stand = self._lernstand.stand(das_feld.kennung, das_thema.kennung)

        zeilen = [
            f"THEMA: {das_thema.titel} ({das_feld.titel})",
            "",
            das_thema.abriss,
            "",
            "Worum es geht:",
            *(f"- {z}" for z in das_thema.worum_es_geht),
            "",
            "Fachbegriffe: " + ", ".join(das_thema.begriffe),
        ]
        if das_thema.literatur:
            zeilen += ["Literatur: " + "; ".join(das_thema.literatur)]

        zeilen += ["", "IN DER LANDKARTE:"]
        zeilen.append(
            "  Setzt voraus: "
            + (", ".join(self._titel(das_feld, k) for k in umfeld.get("baut_auf", ()))
               or "nichts")
        )
        zeilen.append(
            "  Führt weiter zu: "
            + (", ".join(self._titel(das_feld, k) for k in umfeld.get("fuehrt_zu", ()))
               or "–")
        )
        if fehlt:
            zeilen.append(
                "  NOCH NICHT BERÜHRT, wird aber gebraucht: "
                + ", ".join(self._titel(das_feld, k) for k in fehlt)
                + "\n  Sag das nicht als Verbot. Biete an, es kurz mitzunehmen, "
                "oder erklär es beiläufig mit."
            )

        zeilen += ["", "WAS ICH ÜBER DEN BENUTZER VERMUTE:"]
        if stand is None:
            zeilen.append(
                "  Nichts – über dieses Thema wurde noch nie gesprochen. "
                "Fang eher niedrig an und merke am Gespräch, ob er weiter ist."
            )
        else:
            zeilen.append(
                f"  Bisher {stand.beruehrungen} mal berührt, Schwerpunkt "
                f"'{stand.schwerpunkt()}' ({TIEFEN_KLARTEXT[stand.schwerpunkt()]})."
            )
            if stand.eigene_begriffe:
                zeilen.append(
                    "  Diese Begriffe hat er selbst benutzt: "
                    + ", ".join(stand.eigene_begriffe[:10])
                )
            if stand.auskuenfte:
                zeilen.append(f"  Zuletzt gesagt: {stand.auskuenfte[-1]}")
            if stand.interesse > 0:
                zeilen.append("  Er hat hier Interesse gezeigt.")
            elif stand.interesse < 0:
                zeilen.append("  Er hat hier eher abgewinkt.")

        # Und die Frage, ob sich Zeigen lohnt.
        zeilen += ["", lohnt_sich(das_thema.abriss, das_thema).als_hinweis()]

        # Was die Forschung seit dem letzten Blick hervorgebracht hat -
        # vom Aktuellhalten im Hintergrund gesammelt. Das ist der Punkt,
        # an dem die stille Pflege im Gespraech ankommt.
        if self._aktualisierung is not None:
            frisch = self._aktualisierung.hinweis(
                das_feld.kennung, das_thema.kennung
            )
            if frisch:
                zeilen += ["", frisch]

        anlaesse = das_thema.anlaesse_der_tiefe(
            stand.schwerpunkt() if stand else TIEFEN[0]
        ) or das_thema.anlaesse
        if anlaesse:
            zeilen += [
                "",
                "FRAGEN, DIE DAS GESPRÄCH WEITERBRINGEN (keine Prüfung – stell "
                "höchstens eine, und nur wenn sie sich ergibt):",
                *(f"  - {a.frage}" for a in anlaesse[:3]),
            ]
        return ToolResult.success("\n".join(zeilen))

    @staticmethod
    def _titel(das_feld: Any, kennung: str) -> str:
        thema = das_feld.thema(kennung)
        return thema.titel if thema is not None else kennung

    @staticmethod
    def _felder_nennen() -> str:
        liste = "\n".join(
            f"- {f.titel} ({f.kennung}): {f.gegenstand}" for f in felder()
        )
        return "Felder, zu denen ich eine Landkarte habe:\n" + (liste or "– noch keine –")

    def _feld_zeigen(self, das_feld: Any) -> str:
        beruehrt = self._lernstand.beruehrt(das_feld.kennung)
        zeilen = [
            f"FELD: {das_feld.titel}",
            "",
            f"Gegenstand: {das_feld.gegenstand}",
            f"Methode: {das_feld.methode}",
            "",
            "Aufgaben des Fachs:",
            *(f"- {a}" for a in das_feld.aufgaben),
            "",
            "Abgrenzung zu den Nachbarn:",
            *(f"- {n}" for n in das_feld.nachbarn),
            "",
            "Die Landkarte:",
        ]
        for gebiet in das_feld.gebiete:
            marken = ", ".join(
                f"{t.titel}{' ✓' if t.kennung in beruehrt else ''}"
                for t in gebiet.themen
            )
            zeilen.append(f"  {gebiet.titel}: {marken}")
        zeilen += [
            "",
            "Es gibt hier KEINE vorgeschriebene Reihenfolge. Was mit ✓ "
            "markiert ist, wurde schon berührt. Frag den Benutzer, was ihn "
            "interessiert, statt ihm einen Weg vorzugeben.",
        ]
        return "\n".join(zeilen)


class WoranWeiter(Tool):
    """Ein Vorschlag, woran es weitergehen könnte."""

    name = "woran_weiter"
    description = (
        "Schlägt vor, woran der Benutzer in einem Feld weitermachen könnte - "
        "zuerst nach seinen gezeigten Interessen, dann nach dem, wo er selbst "
        "gesagt hat, dass es hakt, erst danach nach der Landkarte. Nimm es, "
        "wenn er fragt, was er als Nächstes anschauen soll, oder wenn ein "
        "Gespräch zu Ende geht und ein Anschluss guttäte."
    )
    parameters = (
        ToolParameter("feld", "string", "Kennung oder Name des Felds."),
    )

    def __init__(self, lernstand: Lernstand) -> None:
        self._lernstand = lernstand

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        das_feld = _feld_finden(str(arguments.get("feld", "") or ""))
        if das_feld is None:
            return ToolResult.failure(
                "Dieses Feld kenne ich nicht. Ich habe: "
                + ", ".join(f.kennung for f in felder()) + "."
            )
        vorschlag = self._lernstand.woran_weiter(das_feld.kennung)
        kennung = str(vorschlag.get("thema", ""))
        thema = das_feld.thema(kennung) if kennung else None
        uebersicht = self._lernstand.uebersicht().get(das_feld.kennung, {})

        zeilen = [
            f"Feld: {das_feld.titel}",
            f"Vorschlag: {thema.titel if thema else vorschlag.get('grund')}",
            f"Warum: {vorschlag.get('grund', '')}",
            f"Wie tief: {vorschlag.get('tiefe', 'kennen')}",
        ]
        if uebersicht.get("interessen"):
            zeilen.append(
                "Interesse gezeigt bei: "
                + ", ".join(self._titel(das_feld, k) for k in uebersicht["interessen"])
            )
        if uebersicht.get("haken"):
            zeilen.append(
                "Selbst gesagt, dass es hakt: "
                + ", ".join(self._titel(das_feld, k) for k in uebersicht["haken"])
            )
        zeilen.append(
            "\nBiete es an, verordne es nicht. Wenn er etwas anderes will, "
            "ist das anderes richtig."
        )
        return ToolResult.success("\n".join(zeilen))

    @staticmethod
    def _titel(das_feld: Any, kennung: str) -> str:
        thema = das_feld.thema(kennung)
        return thema.titel if thema is not None else kennung


class Notieren(Tool):
    """Was der Orb selbst am Gespräch bemerkt hat."""

    name = "lernstand_notieren"
    description = (
        "Hält fest, was du im Gespräch über den Benutzer bemerkt hast - dass "
        "er ein Thema sicher beherrscht, dass er etwas verwechselt, dass ihn "
        "etwas besonders interessiert. Nimm es sparsam und nur bei etwas, das "
        "dir wirklich aufgefallen ist. Es ersetzt keine Prüfung, sondern die "
        "Notiz, die ein Dozent nach einem Gespräch im Kopf behält."
    )
    parameters = (
        ToolParameter("thema", "string", "Kennung oder Titel des Themas."),
        ToolParameter("bemerkung", "string",
                      "Was dir aufgefallen ist, in einem Satz."),
        ToolParameter("tiefe", "string",
                      "Auf welcher Höhe er sich zeigte.", required=False,
                      choices=TIEFEN),
        ToolParameter("interesse", "string",
                      "ja, nein oder leer.", required=False),
    )

    def __init__(self, lernstand: Lernstand) -> None:
        self._lernstand = lernstand

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from backend.studium.mitlesen import Beobachtung

        angabe = str(arguments.get("thema", "") or "").strip()
        treffer = thema_suchen(angabe)
        if treffer is None:
            return ToolResult.failure(
                f"Zu {angabe!r} finde ich kein Thema in der Landkarte."
            )
        das_feld, das_thema = treffer

        interesse = str(arguments.get("interesse", "") or "").strip().lower()
        tiefe = str(arguments.get("tiefe", "") or "").strip().lower()
        beobachtung = Beobachtung(
            thema=das_thema.kennung,
            tiefe=tiefe if tiefe in TIEFEN else "",
            # Was der Orb selbst bemerkt, wiegt schwerer als eine
            # Worterkennung - er hat das ganze Gespraech gehoert.
            gewicht=1.0 if tiefe in TIEFEN else 0.0,
            selbstauskunft=str(arguments.get("bemerkung", "") or "")[:160],
            interesse=1 if interesse.startswith("ja") else (
                -1 if interesse.startswith("nein") else 0
            ),
            gruende=["vom Orb im Gespräch bemerkt"],
        )
        self._lernstand.beobachten(das_feld.kennung, beobachtung)
        return ToolResult.success(
            f"Notiert zu {das_thema.titel}: {beobachtung.selbstauskunft}"
        )


class FolienZeigen(Tool):
    """Baut Folien aus dem, was DU zeigen willst - und öffnet sie."""

    name = "folien_zeigen"
    description = (
        "Baut eine Bildschirmpräsentation aus Folien, die DU bestimmst, und "
        "öffnet sie. Nimm es NUR, wenn es etwas zu SEHEN gibt: eine Karte, "
        "eine Tabelle, ein Paradigma, einen Zeitverlauf, ein Bild des "
        "Gegenstands. Ein Gedankengang oder eine Begründung gehört NICHT auf "
        "eine Folie - dort erklärst du im Gespräch. Auf die Folie kommt nur, "
        "was man sehen muss, nie das, was du ohnehin sagst."
    )
    parameters = (
        ToolParameter("titel", "string", "Überschrift der Präsentation."),
        ToolParameter(
            "folien", "array",
            "Die Folien, je eine als Objekt mit 'titel' und 'punkte' (Liste "
            "kurzer Stichworte, keine Sätze). Zusätzlich möglich: 'bild' "
            "(Suchbegriff für ein Bild aus dem Netz), 'zitat' und 'quelle'. "
            "Drei bis acht Folien sind genug.",
        ),
        ToolParameter("thema", "string",
                      "Thema der Landkarte, falls es dazu gehört.",
                      required=False),
    )

    def __init__(self, lernstand: Lernstand) -> None:
        self._lernstand = lernstand

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        roh = arguments.get("folien") or []
        if not isinstance(roh, list) or not roh:
            return ToolResult.failure(
                "Ohne Folien kann ich nichts zeigen. Gib mindestens eine an."
            )

        titel = str(arguments.get("titel", "") or "Vortrag").strip()
        p = Praesentation(titel=titel)
        p.hinzufuegen(Folie(art="titel", titel=titel))

        gesucht = 0
        for eintrag in roh[:12]:
            if not isinstance(eintrag, dict):
                continue
            folientitel = str(eintrag.get("titel", "") or "").strip()
            punkte = folienpunkte_bereinigen(
                folientitel,
                eintrag.get("punkte") or [],
            )
            bildpfad, nachweis = "", ""
            begriff = str(eintrag.get("bild", "") or "").strip()
            if begriff and gesucht < 4:
                kontext = f"{folientitel}. {' '.join(punkte)}"
                bildpfad, nachweis = await asyncio.to_thread(
                    _bild_besorgen,
                    begriff,
                    gesucht,
                    kontext,
                )
                gesucht += 1
            zitat = str(eintrag.get("zitat", "") or "").strip()
            p.hinzufuegen(Folie(
                art="zitat" if zitat else ("bild" if bildpfad and not punkte else "inhalt"),
                titel=folientitel,
                punkte=punkte,
                bild=bildpfad,
                bildnachweis=nachweis,
                zitat=zitat,
                quelle=str(eintrag.get("quelle", "") or "").strip(),
            ))

        ziel = _speicherort(titel)
        p.speichern(ziel)
        geoeffnet = _oeffnen(ziel)

        thema_angabe = str(arguments.get("thema", "") or "").strip()
        if thema_angabe:
            treffer = thema_suchen(thema_angabe)
            if treffer is not None:
                self._lernstand.erklaert(treffer[0].kennung, treffer[1].kennung)

        hinweis = (
            "Die Präsentation ist auf dem Bildschirm offen."
            if geoeffnet
            else f"Sie liegt unter {ziel}, liess sich aber nicht selbst öffnen – "
                 "sag das dem Benutzer."
        )
        return ToolResult.success(
            f"{hinweis} {len(p.folien)} Folien, {gesucht} Bilder gesucht.\n\n"
            "Sprich jetzt frei dazu. Lies die Folien NICHT vor - der Benutzer "
            "sieht sie. Sag, was daran zu sehen ist und was es bedeutet. "
            "Blättern kann er mit der Leertaste."
        )


def _bild_besorgen(
    begriff: str,
    nummer: int,
    kontext: str = "",
) -> tuple[str, str]:
    """Holt den fachlich passendsten freien Bildtreffer.

    Eine konkrete Folie wie ``Die vier Ursachen`` darf nicht mit dem ersten
    beliebigen Aristoteles-Portraet enden. Deshalb werden aus Folientitel
    und Punkten spezifische Suchbegriffe gebildet und mehrere Treffer nach
    Fachbezug, Aufloesung und Proportion bewertet.
    """

    try:
        from backend.grafik.bildquellen import bild_holen, bilder_suchen
        from backend.utils.paths import get_data_dir

        ordner = get_data_dir() / "vortraege" / "bilder"
        ordner.mkdir(parents=True, exist_ok=True)
        suchfragen = bildsuchbegriffe(kontext, f"Thema: {begriff}")
        if begriff not in suchfragen:
            suchfragen.append(begriff)
        gesehen: set[str] = set()
        for suchfrage in suchfragen[:4]:
            if suchfrage.casefold() in gesehen:
                continue
            gesehen.add(suchfrage.casefold())
            treffer = bilder_suchen(
                suchfrage,
                anzahl=3,
                akzeptieren=lambda kandidat, q=suchfrage: bild_passt(
                    q,
                    kandidat.to_dict(),
                ),
            )
            for kandidat in sorted(
                treffer,
                key=lambda eintrag, q=suchfrage: bild_treffer_bewerten(
                    q,
                    eintrag.to_dict(),
                ),
                reverse=True,
            ):
                ziel = ordner / f"folie-{nummer}.jpg"
                pfad = bild_holen(kandidat, ziel)
                if pfad:
                    return str(pfad), kandidat.nachweis()
    except Exception:  # noqa: BLE001 - ein fehlendes Bild ist kein Fehler.
        logger.info("Kein Bild zu %r – die Folie entsteht ohne.", begriff)
    return "", ""


def _speicherort(titel: str) -> Path:
    import re

    from backend.utils.paths import get_data_dir

    sauber = re.sub(r"[^0-9a-zA-ZäöüÄÖÜß-]+", "-", titel).strip("-").lower()
    return get_data_dir() / "vortraege" / f"{sauber or 'vortrag'}.html"


def _oeffnen(pfad: Path) -> bool:
    """Öffnet im Standardbrowser.

    Bewusst ``webbrowser`` und nicht die Browsersteuerung des Orb: Die
    hängt an Playwright, und Playwright fehlt auf dem Rechner des
    Benutzers. Ein Vortrag, der daran scheitert, wäre keiner.
    """

    try:
        return webbrowser.open(f"file:///{str(pfad).lstrip('/')}", new=2)
    except Exception:  # noqa: BLE001
        logger.exception("Die Präsentation liess sich nicht öffnen.")
        return False


class ForschungNachsehen(Tool):
    """Holt auf Zuruf, was zu einem Thema neu erschienen ist."""

    name = "forschung_aktuell"
    description = (
        "Fragt OpenAlex und Crossref nach Publikationen, die zu einem Thema "
        "der Landkarte NEU erschienen sind, und legt die Funde ab. Nimm es, "
        "wenn der Benutzer nach dem Forschungsstand, nach Neuem oder nach "
        "aktuellen Publikationen zu einem Thema fragt - oder wenn du selbst "
        "wissen willst, ob dein Wissen noch dem Stand entspricht. Die Funde "
        "sind ungeprüfte Hinweise: nenne sie mit Quelle, gib sie nie als "
        "eigenes Wissen aus."
    )
    parameters = (
        ToolParameter("thema", "string", "Thema oder Stichwort."),
    )

    def __init__(self, lernstand: Lernstand, aktualisierung: Any) -> None:
        self._lernstand = lernstand
        self._aktualisierung = aktualisierung

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import asyncio

        angabe = str(arguments.get("thema", "") or "").strip()
        treffer = thema_suchen(angabe)
        if treffer is None:
            return ToolResult.failure(
                f"Zu {angabe!r} habe ich kein Thema in der Landkarte. Für "
                "freie Fragen nach Neuem nimm 'internet_suchen'."
            )
        das_feld, das_thema = treffer
        lauf = await asyncio.to_thread(
            self._aktualisierung.auffrischen, das_feld.kennung, das_thema.kennung
        )
        hinweis = self._aktualisierung.hinweis(das_feld.kennung, das_thema.kennung)
        if lauf.fehler and not hinweis:
            return ToolResult.failure(
                f"Die Quellen waren nicht erreichbar ({lauf.fehler}). Sag das "
                "dem Benutzer geradeheraus."
            )
        if not hinweis:
            return ToolResult.success(
                f"Zu {das_thema.titel} ist seit dem letzten Blick nichts "
                "Neues erschienen - auch das ist eine Auskunft."
            )
        neu_text = f"{len(lauf.neue)} neue Funde. " if lauf.neue else ""
        return ToolResult.success(neu_text + hinweis)


def build_studium_tools(
    lernstand: Lernstand, aktualisierung: Any = None
) -> list[Tool]:
    """Alle Werkzeuge des Studiums."""

    werkzeuge: list[Tool] = [
        Nachsehen(lernstand, aktualisierung),
        WoranWeiter(lernstand),
        Notieren(lernstand),
        FolienZeigen(lernstand),
    ]
    if aktualisierung is not None:
        werkzeuge.append(ForschungNachsehen(lernstand, aktualisierung))
    return werkzeuge
