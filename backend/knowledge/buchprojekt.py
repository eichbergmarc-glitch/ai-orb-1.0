"""Buchprojekte: Synapse hilft Marc beim Schreiben (23.11.2026).

Ein Buch ist eine kleine JSON-Datei mit Kapiteln, Notizen, Quellen und
Bildern (``<daten>/buecher/<kurzname>/buch.json``). Daraus entsteht auf
Knopfdruck ein OpenDocument-Text (.odt) fuer OpenOffice/LibreOffice: mit
Titelseite, Inhaltsverzeichnis, Kapiteln, Abbildungen mit Beschriftung,
Zitaten im Text und Literaturverzeichnis.

## Schreibweise im Kapiteltext

Bewusst schlicht, damit das Sprachmodell sie sicher trifft:

* Leerzeile = neuer Absatz
* ``## Abschnitt`` = Unterkapitel, ``### ...`` = Unter-Unterkapitel
* ``- Punkt`` = Aufzaehlung
* ``> Text`` = eingeruecktes Zitat (Blockzitat)
* ``**fett**`` und ``*kursiv*``
* ``[@gabriel2013]`` oder ``[@gabriel2013, S. 12]`` = Quellenverweis.
  Im Dokument wird daraus "(Gabriel 2013, S. 12)", und die Quelle
  erscheint im Literaturverzeichnis.
* ``[BILD: 3]`` = Abbildung Nummer 3 an dieser Stelle

Das .odt wird ohne Zusatzbibliothek geschrieben (ein ZIP mit XML-Dateien).
Das Inhaltsverzeichnis ist ein echtes Verzeichnis: Es steht fertig im
Dokument und laesst sich in OpenOffice jederzeit aktualisieren
(Rechtsklick -> Verzeichnis aktualisieren).
"""

from __future__ import annotations

import datetime as _dt
import html
import json
import re
import shutil
import threading
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

_SPERRE = threading.RLock()


class BuchFehler(RuntimeError):
    """Meldung fuer Marc - der Text ist fuer ihn bestimmt."""


# --- Ablage -------------------------------------------------------------------

def _wurzel() -> Path:
    from backend.utils.paths import get_data_dir

    ordner = get_data_dir() / "buecher"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def kurzname(titel: str) -> str:
    roh = unicodedata.normalize("NFKD", str(titel or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", roh.lower()).strip("-")[:40] or "buch"


def ausgabe_ordner() -> Path:
    """Wo die fertigen Dokumente landen: Dokumente/Synapse-Buecher."""

    home = Path.home()
    for kandidat in (home / "OneDrive" / "Dokumente", home / "OneDrive" / "Documents",
                     home / "Documents", home / "Dokumente"):
        if kandidat.is_dir():
            ziel = kandidat / "Synapse-Buecher"
            ziel.mkdir(parents=True, exist_ok=True)
            return ziel
    ziel = _wurzel() / "export"
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def _pfad(name: str) -> Path:
    return _wurzel() / name / "buch.json"


def alle_buecher() -> list[dict[str, Any]]:
    ergebnis = []
    for datei in sorted(_wurzel().glob("*/buch.json")):
        try:
            ergebnis.append(json.loads(datei.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return ergebnis


def aktuelles() -> str:
    datei = _wurzel() / "aktuell.txt"
    return datei.read_text(encoding="utf-8").strip() if datei.exists() else ""


def laden(buch: str = "") -> dict[str, Any]:
    """Laedt ein Buch nach Titel, Kurzname oder Teil davon - leer = das aktuelle."""

    gesucht = str(buch or "").strip()
    with _SPERRE:
        if not gesucht:
            gesucht = aktuelles()
            if not gesucht:
                raise BuchFehler("Es gibt noch kein Buchprojekt. Lege zuerst eines mit buch_anlegen an.")
        k = kurzname(gesucht)
        if _pfad(k).exists():
            daten = json.loads(_pfad(k).read_text(encoding="utf-8"))
        else:
            passende = [b for b in alle_buecher()
                        if k in b["kurzname"] or gesucht.lower() in b["titel"].lower()]
            if len(passende) != 1:
                namen = ", ".join(b["titel"] for b in alle_buecher()) or "keine"
                raise BuchFehler(f"Buch '{gesucht}' nicht eindeutig gefunden. Vorhanden: {namen}.")
            daten = passende[0]
        (_wurzel() / "aktuell.txt").write_text(daten["kurzname"], encoding="utf-8")
        return daten


def speichern(daten: dict[str, Any]) -> None:
    with _SPERRE:
        pfad = _pfad(daten["kurzname"])
        pfad.parent.mkdir(parents=True, exist_ok=True)
        daten["geaendert"] = _dt.datetime.now().isoformat(timespec="seconds")
        zwischen = pfad.with_suffix(".tmp")
        zwischen.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
        if pfad.exists():
            shutil.copy(pfad, pfad.with_suffix(".bak"))   # eine Sicherung der letzten Fassung
        zwischen.replace(pfad)
        (_wurzel() / "aktuell.txt").write_text(daten["kurzname"], encoding="utf-8")
    # 23.11.2026: Nach jeder Aenderung liegt das Dokument sofort aktuell in
    # Dokumente/Synapse-Buecher. Vorher entstand es nur, wenn das Modell
    # ausdruecklich buch_exportieren aufrief - und das tat es oft nicht
    # ("Ich speichere es jetzt ... einen Moment"), sodass Marc vor einem
    # leeren Ordner stand.
    try:
        exportieren(daten)
    except Exception as fehler:  # noqa: BLE001 - z. B. Datei gerade in OpenOffice offen
        import logging

        logging.getLogger(__name__).info("Dokument nicht automatisch erneuert: %s", fehler)


# --- Bearbeiten ---------------------------------------------------------------

def anlegen(titel: str, *, untertitel: str = "", autor: str = "Marc", kapitel: list[str] | None = None) -> dict[str, Any]:
    titel = " ".join(str(titel or "").split())
    if not titel:
        raise BuchFehler("Das Buch braucht einen Titel.")
    k = kurzname(titel)
    if _pfad(k).exists():
        raise BuchFehler(f"Ein Buch '{titel}' gibt es schon - ich arbeite damit weiter.")
    daten = {
        "titel": titel, "untertitel": untertitel.strip(), "autor": autor.strip() or "Marc",
        "kurzname": k, "angelegt": _dt.date.today().isoformat(),
        "kapitel": [{"titel": t.strip(), "text": "", "notizen": []} for t in (kapitel or []) if t.strip()],
        "notizen": [], "quellen": {}, "bilder": [],
    }
    speichern(daten)
    return daten


def gliederung_lesen(text: str) -> list[tuple[str, list[str]]]:
    """'Kapitel A: Unter 1; Unter 2 | Kapitel B: ...' (oder je Kapitel eine Zeile)."""

    ergebnis = []
    for teil in re.split(r"\s*(?:\||\n)\s*", str(text or "")):
        teil = re.sub(r"^\s*(?:kapitel\s*)?\d+[.):]?\s+", "", teil.strip(), flags=re.I)
        if not teil:
            continue
        titel, _, rest = teil.partition(":")
        unter = [re.sub(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[-*•])\s*", "", u).strip() for u in re.split(r"\s*;\s*", rest)]
        ergebnis.append((titel.strip(), [u for u in unter if u]))
    return ergebnis


def gliederung_setzen(daten: dict[str, Any], gliederung: str) -> str:
    """Setzt Kapitel und Unterkapitel. Vorhandener Text bleibt erhalten:
    Ein Kapitel mit gleichem Titel wird nur um fehlende Unterkapitel ergaenzt."""

    eintraege = gliederung_lesen(gliederung)
    if not eintraege:
        raise BuchFehler("Die Gliederung ist leer. Form: 'Kapitel: Unterkapitel; Unterkapitel | naechstes Kapitel: ...'")
    alt = {k["titel"].lower(): k for k in daten["kapitel"]}
    neu = []
    for titel, unter in eintraege:
        k = alt.pop(titel.lower(), None) or {"titel": titel, "text": "", "notizen": []}
        vorhanden = {m.lower() for m in re.findall(r"^##\s+(.+)$", k["text"], re.M)}
        fehlend = [u for u in unter if u.lower() not in vorhanden]
        if fehlend:
            k["text"] = (k["text"].rstrip() + "\n\n" + "\n\n".join(f"## {u}" for u in fehlend)).strip()
        neu.append(k)
    # Kapitel, die in der neuen Gliederung fehlen, aber schon Text haben, gehen nicht verloren
    neu += [k for k in alt.values() if k["text"].strip() and not re.fullmatch(r"(\s*##[^\n]*\s*)*", k["text"])]
    daten["kapitel"] = neu
    speichern(daten)
    return "Gliederung gespeichert.\n" + uebersicht(daten, mit_unterkapiteln=True)


def kapitel_finden(daten: dict[str, Any], angabe: str | int) -> int:
    """'3', 3, 'Kapitel 3' oder ein Teil des Titels -> Index."""

    text = str(angabe or "").strip()
    nummer = re.fullmatch(r"(?:kapitel\s*)?(\d{1,3})\.?", text, re.I)
    if nummer:
        i = int(nummer.group(1)) - 1
        if 0 <= i < len(daten["kapitel"]):
            return i
        raise BuchFehler(f"Kapitel {i + 1} gibt es nicht - das Buch hat {len(daten['kapitel'])} Kapitel.")
    passende = [i for i, k in enumerate(daten["kapitel"]) if text.lower() in k["titel"].lower()]
    if len(passende) == 1:
        return passende[0]
    namen = "; ".join(f"{i + 1}. {k['titel']}" for i, k in enumerate(daten["kapitel"]))
    raise BuchFehler(f"Welches Kapitel? Vorhanden: {namen or 'noch keine'}.")


def kapitel_schreiben(daten: dict[str, Any], kapitel: str, text: str, *, modus: str = "anhaengen",
                      position: int | None = None) -> str:
    text = str(text or "").strip()
    if modus == "neu" or (not daten["kapitel"] and kapitel):
        eintrag = {"titel": kapitel.strip() or f"Kapitel {len(daten['kapitel']) + 1}", "text": text, "notizen": []}
        if position and 1 <= position <= len(daten["kapitel"]) + 1:
            daten["kapitel"].insert(position - 1, eintrag)
        else:
            daten["kapitel"].append(eintrag)
        speichern(daten)
        return f"Neues Kapitel „{eintrag['titel']}“ angelegt ({len(text.split())} Wörter)."
    i = kapitel_finden(daten, kapitel)
    k = daten["kapitel"][i]
    if modus == "ersetzen":
        k["text"] = text
    elif modus == "umbenennen":
        k["titel"] = text
    else:
        k["text"] = (k["text"].rstrip() + "\n\n" + text).strip()
    speichern(daten)
    return f"Kapitel {i + 1} „{k['titel']}“: jetzt {len(k['text'].split())} Wörter."


def notiz(daten: dict[str, Any], text: str, kapitel: str = "") -> str:
    eintrag = {"text": str(text).strip(), "datum": _dt.datetime.now().strftime("%d.%m.%Y %H:%M")}
    if not eintrag["text"]:
        raise BuchFehler("Die Notiz ist leer.")
    if str(kapitel or "").strip():
        i = kapitel_finden(daten, kapitel)
        daten["kapitel"][i]["notizen"].append(eintrag)
        ort = f"zu Kapitel {i + 1} „{daten['kapitel'][i]['titel']}“"
    else:
        daten["notizen"].append(eintrag)
        ort = "zum Buch"
    speichern(daten)
    return f"Notiz {ort} festgehalten."


def quellen_schluessel(daten: dict[str, Any], autor: str, jahr: str) -> str:
    nachname = re.split(r"[,;&]| und | and ", str(autor or "anonym"))[0].strip().split()[-1:] or ["anonym"]
    basis = kurzname(nachname[0]).replace("-", "") + re.sub(r"\D", "", str(jahr))[:4]
    schluessel, n = basis or "quelle", 1
    while schluessel in daten["quellen"]:
        n += 1
        schluessel = f"{basis}{chr(96 + n)}"
    return schluessel


def quelle_hinzufuegen(daten: dict[str, Any], **felder: str) -> str:
    autor = str(felder.get("autor") or "").strip()
    titel = str(felder.get("titel") or "").strip()
    if not titel:
        raise BuchFehler("Die Quelle braucht mindestens einen Titel.")
    # Doppelte vermeiden (gleiche DOI oder gleicher Titel)
    for schluessel, q in daten["quellen"].items():
        if (felder.get("doi") and q.get("doi") == felder.get("doi")) or q.get("titel", "").lower() == titel.lower():
            return schluessel
    schluessel = quellen_schluessel(daten, autor, str(felder.get("jahr") or "o.J."))
    daten["quellen"][schluessel] = {k: str(v).strip() for k, v in felder.items() if str(v or "").strip()}
    speichern(daten)
    return schluessel


def bild_hinzufuegen(daten: dict[str, Any], datei: str, beschriftung: str, *, kapitel: str = "",
                     quelle: str = "") -> int:
    pfad = Path(str(datei or "").strip().strip('"'))
    if not pfad.is_file():
        raise BuchFehler(f"Die Bilddatei {pfad} gibt es nicht.")
    if pfad.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
        raise BuchFehler("Nur Bilder (png, jpg, gif) lassen sich einfügen.")
    nummer = len(daten["bilder"]) + 1
    ziel_ordner = _pfad(daten["kurzname"]).parent / "bilder"
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    ziel = ziel_ordner / f"bild{nummer}{pfad.suffix.lower()}"
    shutil.copy(pfad, ziel)
    daten["bilder"].append({"nummer": nummer, "datei": str(ziel), "beschriftung": beschriftung.strip(),
                            "quelle": quelle.strip()})
    if str(kapitel or "").strip():
        i = kapitel_finden(daten, kapitel)
        daten["kapitel"][i]["text"] = (daten["kapitel"][i]["text"].rstrip() + f"\n\n[BILD: {nummer}]").strip()
    speichern(daten)
    return nummer


def uebersicht(daten: dict[str, Any], *, mit_unterkapiteln: bool = False) -> str:
    zeilen = [f"„{daten['titel']}“" + (f" – {daten['untertitel']}" if daten.get("untertitel") else "")
              + f" von {daten.get('autor', 'Marc')}"]
    gesamt = 0
    for i, k in enumerate(daten["kapitel"], 1):
        woerter = len(re.sub(r"^##+\s+.*$", "", k["text"], flags=re.M).split())
        gesamt += woerter
        zeilen.append(f"{i}. {k['titel']} – {woerter} Wörter" + (f", {len(k['notizen'])} Notizen" if k["notizen"] else ""))
        if mit_unterkapiteln:
            zeilen += [f"   {i}.{j} {u}" for j, u in enumerate(re.findall(r"^##\s+(.+)$", k["text"], re.M), 1)]
    zeilen.append(f"Insgesamt {gesamt} Wörter, {len(daten['quellen'])} Quellen, {len(daten['bilder'])} Abbildungen, "
                  f"{len(daten['notizen'])} Notizen zum Buch.")
    return "\n".join(zeilen)


# --- Zitieren -----------------------------------------------------------------

def _autor_kurz(autor: str) -> str:
    personen = [p.strip() for p in re.split(r";| und | and |&", autor or "") if p.strip()]
    if not personen:
        return "o. A."
    nachnamen = []
    for p in personen:
        nachnamen.append(p.split(",")[0].strip() if "," in p else p.split()[-1])
    if len(nachnamen) == 1:
        return nachnamen[0]
    if len(nachnamen) == 2:
        return f"{nachnamen[0]} & {nachnamen[1]}"
    return f"{nachnamen[0]} et al."


def verweis_text(q: dict[str, Any], zusatz: str = "") -> str:
    return f"{_autor_kurz(q.get('autor', ''))} {q.get('jahr', 'o. J.')}" + (f", {zusatz}" if zusatz else "")


def literatur_eintrag(q: dict[str, Any]) -> str:
    """Eintrag im Literaturverzeichnis, angelehnt an APA (deutsche Fassung)."""

    teile = [f"{q.get('autor', 'o. A.')} ({q.get('jahr', 'o. J.')}). {q.get('titel', '')}."]
    if q.get("zeitschrift"):
        teile.append(f"{q['zeitschrift']}" + (f", {q['band']}" if q.get("band") else "")
                     + (f", {q['seiten']}" if q.get("seiten") else "") + ".")
    if q.get("verlag") or q.get("ort"):
        teile.append(", ".join(x for x in (q.get("ort", ""), q.get("verlag", "")) if x) + ".")
    if q.get("doi"):
        doi = q["doi"].replace("https://doi.org/", "")
        teile.append(f"https://doi.org/{doi}")
    elif q.get("url"):
        teile.append(q["url"] + (f" (abgerufen am {q['abgerufen']})" if q.get("abgerufen") else ""))
    return " ".join(teile)


# --- OpenDocument schreiben ---------------------------------------------------

def _x(text: str) -> str:
    return html.escape(str(text), quote=False)


_VERWEIS = re.compile(r"\[@([A-Za-z0-9_\-]+)(?:\s*,\s*([^\]]+))?\]")


class _Schreiber:
    def __init__(self, daten: dict[str, Any]) -> None:
        self.d = daten
        self.zitiert: list[str] = []
        self.bilder: dict[int, dict[str, Any]] = {b["nummer"]: b for b in daten["bilder"]}
        self.bild_dateien: list[tuple[str, Path]] = []
        self.ueberschriften: list[tuple[int, str]] = []
        self.fehlende: set[str] = set()

    # Inline: fett, kursiv, Verweise
    def inline(self, text: str) -> str:
        teile: list[str] = []
        pos = 0
        for m in _VERWEIS.finditer(text):
            teile.append(self._formatiert(text[pos:m.start()]))
            schluessel, zusatz = m.group(1), (m.group(2) or "").strip()
            q = self.d["quellen"].get(schluessel)
            if q is None:
                self.fehlende.add(schluessel)
                teile.append(_x(f"[Quelle {schluessel} fehlt]"))
            else:
                if schluessel not in self.zitiert:
                    self.zitiert.append(schluessel)
                teile.append(_x(f"({verweis_text(q, zusatz)})"))
            pos = m.end()
        teile.append(self._formatiert(text[pos:]))
        return "".join(teile)

    @staticmethod
    def _formatiert(text: str) -> str:
        t = _x(text)
        t = re.sub(r"\*\*(.+?)\*\*", r'<text:span text:style-name="Fett">\1</text:span>', t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r'<text:span text:style-name="Kursiv">\1</text:span>', t)
        return t

    def ueberschrift(self, ebene: int, text: str, *, nummer: str = "") -> str:
        anzeige = f"{nummer} {text}".strip()
        self.ueberschriften.append((ebene, anzeige))
        return (f'<text:h text:style-name="Heading_20_{ebene}" text:outline-level="{ebene}">'
                f"{_x(anzeige)}</text:h>")

    def bild(self, nummer: int) -> str:
        b = self.bilder.get(nummer)
        if b is None or not Path(b["datei"]).is_file():
            return f'<text:p text:style-name="Standard">{_x(f"[Abbildung {nummer} fehlt]")}</text:p>'
        pfad = Path(b["datei"])
        name = f"Pictures/bild{nummer}{pfad.suffix.lower()}"
        self.bild_dateien.append((name, pfad))
        breite_cm, hoehe_cm = 15.0, 10.0
        try:
            from PIL import Image

            with Image.open(pfad) as img:
                w, h = img.size
            breite_cm = min(15.0, 15.0)
            hoehe_cm = breite_cm * h / max(w, 1)
            if hoehe_cm > 18:
                breite_cm, hoehe_cm = breite_cm * 18 / hoehe_cm, 18.0
        except Exception:  # noqa: BLE001 - ohne PIL ein festes Format
            pass
        unterschrift = f"Abbildung {nummer}: {b.get('beschriftung', '')}"
        if b.get("quelle"):
            unterschrift += f" (Quelle: {b['quelle']})"
        return (f'<text:p text:style-name="Bildabsatz"><draw:frame draw:style-name="Bildrahmen" '
                f'draw:name="Abbildung{nummer}" text:anchor-type="as-char" svg:width="{breite_cm:.2f}cm" '
                f'svg:height="{hoehe_cm:.2f}cm" draw:z-index="0"><draw:image xlink:href="{name}" '
                f'xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/></draw:frame></text:p>'
                f'<text:p text:style-name="Bildunterschrift">{self.inline(unterschrift)}</text:p>')

    def block(self, text: str, kapitel_nr: int) -> str:
        aus: list[str] = []
        liste: list[str] = []
        unter = 0

        def liste_schliessen() -> None:
            if liste:
                aus.append('<text:list text:style-name="Aufzaehlung">' + "".join(
                    f'<text:list-item><text:p text:style-name="Listenabsatz">{p}</text:p></text:list-item>'
                    for p in liste) + "</text:list>")
                liste.clear()

        for absatz in re.split(r"\n\s*\n", str(text or "").strip()):
            zeilen = [z.rstrip() for z in absatz.strip().splitlines() if z.strip()]
            if not zeilen:
                continue
            if all(re.match(r"^\s*[-*•]\s+", z) for z in zeilen):
                liste.extend(self.inline(re.sub(r"^\s*[-*•]\s+", "", z)) for z in zeilen)
                continue
            liste_schliessen()
            erste = zeilen[0].strip()
            bild = re.fullmatch(r"\[BILD:\s*(\d+)\]", erste, re.I)
            if bild and len(zeilen) == 1:
                aus.append(self.bild(int(bild.group(1))))
                continue
            kopf = re.match(r"^(#{2,3})\s+(.+)$", erste)
            if kopf:
                ebene = len(kopf.group(1))
                if ebene == 2:
                    unter += 1
                    aus.append(self.ueberschrift(2, kopf.group(2).strip(), nummer=f"{kapitel_nr}.{unter}"))
                else:
                    aus.append(self.ueberschrift(3, kopf.group(2).strip()))
                zeilen = zeilen[1:]
                if not zeilen:
                    continue
            if all(z.lstrip().startswith(">") for z in zeilen):
                inhalt = " ".join(z.lstrip()[1:].strip() for z in zeilen)
                aus.append(f'<text:p text:style-name="Zitat">{self.inline(inhalt)}</text:p>')
                continue
            aus.append(f'<text:p text:style-name="Text_20_body">{self.inline(" ".join(z.strip() for z in zeilen))}</text:p>')
        liste_schliessen()
        return "".join(aus)

    def inhalt(self) -> str:
        d = self.d
        titel = (f'<text:p text:style-name="Title">{_x(d["titel"])}</text:p>'
                 + (f'<text:p text:style-name="Subtitle">{_x(d["untertitel"])}</text:p>' if d.get("untertitel") else "")
                 + f'<text:p text:style-name="Autor">{_x(d.get("autor", ""))}</text:p>'
                 + f'<text:p text:style-name="Autor">{_x(_dt.date.today().strftime("%d.%m.%Y"))}</text:p>')
        kapitel_xml = []
        for i, k in enumerate(d["kapitel"], 1):
            kapitel_xml.append(self.ueberschrift(1, k["titel"], nummer=f"{i}"))
            kapitel_xml.append(self.block(k["text"], i) or
                               '<text:p text:style-name="Text_20_body">(Dieses Kapitel ist noch leer.)</text:p>')
        if self.zitiert:
            kapitel_xml.append(self.ueberschrift(1, "Literaturverzeichnis"))
            eintraege = sorted((literatur_eintrag(d["quellen"][s]) for s in self.zitiert), key=str.lower)
            kapitel_xml += [f'<text:p text:style-name="Literatur">{_x(e)}</text:p>' for e in eintraege]
        if self.bilder and any(b.get("quelle") for b in self.bilder.values()):
            pass
        # Das Verzeichnis zuletzt: erst jetzt kennen wir alle Ueberschriften.
        verzeichnis = self._verzeichnis()
        return titel + verzeichnis + "".join(kapitel_xml)

    def _verzeichnis(self) -> str:
        eintraege = "".join(
            f'<text:p text:style-name="Contents_20_{ebene}">{_x(text)}<text:tab/></text:p>'
            for ebene, text in self.ueberschriften if ebene <= 2)
        return ('<text:table-of-content text:style-name="Verzeichnis" text:protected="true" text:name="Inhaltsverzeichnis">'
                '<text:table-of-content-source text:outline-level="2">'
                '<text:index-title-template text:style-name="Contents_20_Heading">Inhaltsverzeichnis</text:index-title-template>'
                + "".join(
                    f'<text:table-of-content-entry-template text:outline-level="{e}" text:style-name="Contents_20_{e}">'
                    '<text:index-entry-chapter/><text:index-entry-text/><text:index-entry-tab-stop style:type="right" '
                    'style:leader-char="."/><text:index-entry-page-number/></text:table-of-content-entry-template>'
                    for e in (1, 2))
                + '</text:table-of-content-source><text:index-body>'
                '<text:index-title text:style-name="Verzeichnis" text:name="Inhaltsverzeichnis_Kopf">'
                '<text:p text:style-name="Contents_20_Heading">Inhaltsverzeichnis</text:p></text:index-title>'
                + eintraege + '</text:index-body></text:table-of-content>')


_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
       'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
       'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
       'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
       'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
       'xmlns:xlink="http://www.w3.org/1999/xlink" '
       'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
       'xmlns:dc="http://purl.org/dc/elements/1.1/" '
       'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
       'office:version="1.2"')

_STILE = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {_NS}>
<office:font-face-decls xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>
<office:styles>
 <style:default-style style:family="paragraph"><style:paragraph-properties fo:hyphenation-ladder-count="no-limit"/>
  <style:text-properties style:font-name="Liberation Serif" fo:font-family="'Liberation Serif', 'Times New Roman', serif" fo:font-size="12pt" fo:language="de" fo:country="CH" fo:hyphenate="true"/></style:default-style>
 <style:style style:name="Standard" style:family="paragraph" style:class="text"/>
 <style:style style:name="Text_20_body" style:display-name="Text body" style:family="paragraph" style:parent-style-name="Standard" style:class="text">
  <style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="0.25cm" fo:line-height="140%" fo:text-align="justify"/></style:style>
 <style:style style:name="Heading" style:family="paragraph" style:parent-style-name="Standard" style:next-style-name="Text_20_body" style:class="text">
  <style:paragraph-properties fo:margin-top="0.6cm" fo:margin-bottom="0.3cm" fo:keep-with-next="always"/>
  <style:text-properties style:font-name="Liberation Sans" fo:font-family="'Liberation Sans', Arial, sans-serif" fo:font-weight="bold"/></style:style>
 <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph" style:parent-style-name="Heading" style:default-outline-level="1" style:class="text">
  <style:paragraph-properties fo:break-before="page" fo:margin-top="0.4cm" fo:margin-bottom="0.5cm"/><style:text-properties fo:font-size="20pt"/></style:style>
 <style:style style:name="Heading_20_2" style:display-name="Heading 2" style:family="paragraph" style:parent-style-name="Heading" style:default-outline-level="2" style:class="text">
  <style:text-properties fo:font-size="15pt"/></style:style>
 <style:style style:name="Heading_20_3" style:display-name="Heading 3" style:family="paragraph" style:parent-style-name="Heading" style:default-outline-level="3" style:class="text">
  <style:text-properties fo:font-size="13pt" fo:font-style="italic"/></style:style>
 <style:style style:name="Title" style:family="paragraph" style:parent-style-name="Standard" style:class="chapter">
  <style:paragraph-properties fo:margin-top="6cm" fo:margin-bottom="0.6cm" fo:text-align="center"/>
  <style:text-properties style:font-name="Liberation Sans" fo:font-family="'Liberation Sans', Arial, sans-serif" fo:font-size="28pt" fo:font-weight="bold"/></style:style>
 <style:style style:name="Subtitle" style:family="paragraph" style:parent-style-name="Standard" style:class="chapter">
  <style:paragraph-properties fo:margin-bottom="2cm" fo:text-align="center"/><style:text-properties fo:font-size="16pt" fo:font-style="italic"/></style:style>
 <style:style style:name="Autor" style:family="paragraph" style:parent-style-name="Standard">
  <style:paragraph-properties fo:text-align="center" fo:margin-bottom="0.2cm"/><style:text-properties fo:font-size="13pt"/></style:style>
 <style:style style:name="Zitat" style:family="paragraph" style:parent-style-name="Text_20_body">
  <style:paragraph-properties fo:margin-left="1cm" fo:margin-right="1cm" fo:text-align="justify"/><style:text-properties fo:font-size="11pt" fo:font-style="italic"/></style:style>
 <style:style style:name="Listenabsatz" style:family="paragraph" style:parent-style-name="Text_20_body"/>
 <style:style style:name="Literatur" style:family="paragraph" style:parent-style-name="Standard">
  <style:paragraph-properties fo:margin-left="1cm" fo:text-indent="-1cm" fo:margin-bottom="0.2cm" fo:text-align="start"/><style:text-properties fo:font-size="11pt"/></style:style>
 <style:style style:name="Bildabsatz" style:family="paragraph" style:parent-style-name="Standard">
  <style:paragraph-properties fo:text-align="center" fo:margin-top="0.3cm" fo:keep-with-next="always"/></style:style>
 <style:style style:name="Bildunterschrift" style:family="paragraph" style:parent-style-name="Standard" style:class="extra">
  <style:paragraph-properties fo:text-align="center" fo:margin-bottom="0.4cm"/><style:text-properties fo:font-size="10pt" fo:font-style="italic"/></style:style>
 <style:style style:name="Contents_20_Heading" style:display-name="Contents Heading" style:family="paragraph" style:parent-style-name="Heading" style:class="index">
  <style:paragraph-properties fo:break-before="page"/><style:text-properties fo:font-size="18pt"/></style:style>
 <style:style style:name="Contents_20_1" style:display-name="Contents 1" style:family="paragraph" style:parent-style-name="Standard" style:class="index">
  <style:paragraph-properties fo:margin-top="0.2cm"><style:tab-stops><style:tab-stop style:position="16cm" style:type="right" style:leader-style="dotted" style:leader-text="."/></style:tab-stops></style:paragraph-properties>
  <style:text-properties fo:font-weight="bold"/></style:style>
 <style:style style:name="Contents_20_2" style:display-name="Contents 2" style:family="paragraph" style:parent-style-name="Standard" style:class="index">
  <style:paragraph-properties fo:margin-left="0.6cm"><style:tab-stops><style:tab-stop style:position="15.4cm" style:type="right" style:leader-style="dotted" style:leader-text="."/></style:tab-stops></style:paragraph-properties></style:style>
 <style:style style:name="Fett" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>
 <style:style style:name="Kursiv" style:family="text"><style:text-properties fo:font-style="italic"/></style:style>
 <text:list-style style:name="Aufzaehlung">
  <text:list-level-style-bullet text:level="1" text:bullet-char="•"><style:list-level-properties text:list-level-position-and-space-mode="label-alignment">
   <style:list-level-label-alignment text:label-followed-by="listtab" text:list-tab-stop-position="1cm" fo:text-indent="-0.5cm" fo:margin-left="1cm"/></style:list-level-properties></text:list-level-style-bullet>
 </text:list-style>
</office:styles>
<office:automatic-styles>
 <style:page-layout style:name="Seite"><style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" fo:margin-top="2.5cm" fo:margin-bottom="2cm" fo:margin-left="2.5cm" fo:margin-right="2.5cm"/>
  <style:footer-style><style:header-footer-properties fo:min-height="0.6cm" fo:margin-top="0.4cm"/></style:footer-style></style:page-layout>
 <style:style style:name="Fusszeile" style:family="paragraph"><style:paragraph-properties fo:text-align="center"/><style:text-properties fo:font-size="10pt"/></style:style>
</office:automatic-styles>
<office:master-styles>
 <style:master-page style:name="Standard" style:page-layout-name="Seite">
  <style:footer><text:p text:style-name="Fusszeile"><text:page-number text:select-page="current">1</text:page-number></text:p></style:footer>
 </style:master-page>
</office:master-styles>
</office:document-styles>"""

_AUTO = """<office:automatic-styles>
 <style:style style:name="Bildrahmen" style:family="graphic"><style:graphic-properties style:wrap="none" style:vertical-pos="top" style:vertical-rel="baseline" style:horizontal-pos="center" style:horizontal-rel="paragraph"/></style:style>
 <style:style style:name="Verzeichnis" style:family="section"><style:section-properties style:editable="false"/></style:style>
</office:automatic-styles>"""


def exportieren(daten: dict[str, Any], *, ziel: Path | None = None) -> tuple[Path, list[str]]:
    """Schreibt das Buch als .odt. Gibt Pfad und Hinweise (fehlende Quellen ...) zurueck."""

    s = _Schreiber(daten)
    koerper = s.inhalt()
    inhalt = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {_NS}>'
              f"{_AUTO}<office:body><office:text>{koerper}</office:text></office:body></office:document-content>")
    meta = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-meta {_NS}><office:meta>'
            f"<dc:title>{_x(daten['titel'])}</dc:title><meta:initial-creator>{_x(daten.get('autor', ''))}</meta:initial-creator>"
            f"<meta:generator>AI-Orb Synapse</meta:generator><dc:language>de-CH</dc:language>"
            f"</office:meta></office:document-meta>")
    bilder_manifest = "".join(
        f'<manifest:file-entry manifest:full-path="{n}" manifest:media-type="image/{"jpeg" if n.endswith((".jpg", ".jpeg")) else n.rsplit(".", 1)[-1]}"/>'
        for n, _ in s.bild_dateien)
    manifest = ('<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest '
                'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
                '<manifest:file-entry manifest:full-path="/" manifest:version="1.2" '
                'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
                '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
                f"{bilder_manifest}</manifest:manifest>")
    if ziel is None:
        # 23.11.2026: Nur den DATEINAMEN saeubern. Vorher fiel auch der
        # Doppelpunkt in "C:" weg - aus C:\Users\... wurde ein relativer
        # Pfad, und das Speichern scheiterte ("No such file or directory").
        dateiname = re.sub(r'[<>:"/\\|?*]', "", daten["titel"][:60]).strip() or "Buch"
        ziel = ausgabe_ordner() / f"{dateiname}.odt"
    zwischen = ziel.with_suffix(".odt.tmp")
    with zipfile.ZipFile(zwischen, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", inhalt, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("styles.xml", _STILE, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("meta.xml", meta, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/manifest.xml", manifest, compress_type=zipfile.ZIP_DEFLATED)
        for name, pfad in s.bild_dateien:
            z.write(pfad, name, compress_type=zipfile.ZIP_STORED)
    import time as _zeit

    for versuch in range(4):
        try:
            zwischen.replace(ziel)
            break
        except PermissionError:
            # 23.11.2026: Ist das Dokument in OpenOffice offen (oder haelt
            # OneDrive es kurz fest), laesst Windows es nicht ersetzen. Statt
            # abzubrechen - Marc bekam dann gar kein Dokument - kurz warten
            # und notfalls unter einem neuen Namen mit Uhrzeit speichern.
            if versuch < 2:
                _zeit.sleep(0.7)
                continue
            ziel = ziel.with_name(f"{ziel.stem} (Stand {_dt.datetime.now():%d.%m. %H-%M}){ziel.suffix}")
            zwischen.replace(ziel)
            break
    hinweise = [f"Quelle [@{k}] ist nicht erfasst" for k in sorted(s.fehlende)]
    return ziel, hinweise


# --- Literatur suchen (OpenAlex, frei und ohne Konto) -------------------------

def _json_holen(adresse: str, *, zeitlimit: int = 25) -> dict[str, Any]:
    import urllib.request

    anfrage = urllib.request.Request(adresse, headers={"User-Agent": "AI-Orb-Synapse/1.0"})
    with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:  # noqa: S310 - feste Quellen
        return json.loads(antwort.read().decode("utf-8"))


def ins_englische(text: str) -> str:
    """Kurze Suchbegriffe ins Englische (MyMemory, frei). Bei Ausfall: Original.

    Die meiste Fachliteratur ist englisch; eine deutsche Suche nach
    "Klimapolitik und internationale Abkommen" findet nur einen Bruchteil.
    """

    import urllib.parse

    try:
        daten = _json_holen("https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
            {"q": text[:200], "langpair": "de|en"}), zeitlimit=10)
        uebersetzt = str((daten.get("responseData") or {}).get("translatedText") or "").strip()
        if uebersetzt and "MYMEMORY WARNING" not in uebersetzt.upper() and uebersetzt.lower() != text.lower():
            return uebersetzt
    except Exception:  # noqa: BLE001
        pass
    return text


def _kurzfassung(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    woerter: dict[int, str] = {}
    for wort, stellen in index.items():
        for s in stellen:
            woerter[s] = wort
    return " ".join(woerter[i] for i in sorted(woerter))[:700]


def _openalex(suche: str, *, anzahl: int, ab_jahr: int = 0) -> list[dict[str, Any]]:
    import urllib.parse

    filter_teile = ["type:article|book|book-chapter|review", "has_abstract:true"]
    if ab_jahr:
        filter_teile.append(f"from_publication_date:{ab_jahr}-01-01")
    daten = _json_holen("https://api.openalex.org/works?" + urllib.parse.urlencode(
        {"search": suche, "per-page": str(max(1, min(anzahl * 3, 25))), "filter": ",".join(filter_teile),
         "mailto": "synapse@ai-orb.invalid"}))
    return list(daten.get("results") or [])


def _eintrag_aus(w: dict[str, Any]) -> dict[str, str]:
    def umdrehen(name: str) -> str:   # "Jan Voosholz" -> "Voosholz, Jan" (wie im Literaturverzeichnis ueblich)
        teile = name.split()
        return f"{teile[-1]}, {' '.join(teile[:-1])}" if len(teile) > 1 and "," not in name else name

    autoren = "; ".join(
        umdrehen(str((a.get("author") or {}).get("display_name") or "")) for a in (w.get("authorships") or [])[:6])
    ort = w.get("primary_location") or {}
    quelle = ort.get("source") or {}
    oa = (w.get("open_access") or {}).get("oa_url") or ""
    biblio = w.get("biblio") or {}
    seiten = "-".join(x for x in (biblio.get("first_page"), biblio.get("last_page")) if x)
    typ = str(w.get("type") or "")
    eintrag = {
        "autor": autoren, "jahr": str(w.get("publication_year") or ""),
        "titel": str(w.get("display_name") or ""), "doi": str(w.get("doi") or "").replace("https://doi.org/", ""),
        "url": oa or str(ort.get("landing_page_url") or ""),
        "zitiert": str(w.get("cited_by_count") or 0), "typ": typ,
        "kurzfassung": _kurzfassung(w.get("abstract_inverted_index")),
    }
    if typ in ("book", "book-chapter"):
        eintrag["verlag"] = str(quelle.get("host_organization_name") or quelle.get("display_name") or "")
    else:
        eintrag["zeitschrift"] = str(quelle.get("display_name") or "")
        if biblio.get("volume"):
            eintrag["band"] = str(biblio["volume"])
        if seiten:
            eintrag["seiten"] = seiten
    return {k: v for k, v in eintrag.items() if v}


def literatur_suchen(thema: str, *, anzahl: int = 5, ab_jahr: int = 0, englisch: bool = True) -> list[dict[str, str]]:
    """Sucht deutsch UND englisch, wirft Unbrauchbares weg, ordnet nach Relevanz und Zitierungen."""

    import math

    thema = " ".join(str(thema or "").split())
    if not thema:
        return []
    anfragen = [thema]
    if englisch:
        en = ins_englische(thema)
        if en.lower() != thema.lower():
            anfragen.insert(0, en)
    gesehen: set[str] = set()
    kandidaten: list[tuple[float, dict[str, str]]] = []
    for rang_basis, suche in enumerate(anfragen):
        try:
            werke = _openalex(suche, anzahl=anzahl, ab_jahr=ab_jahr)
        except Exception:  # noqa: BLE001
            continue
        for pos, w in enumerate(werke):
            e = _eintrag_aus(w)
            schluessel = (e.get("doi") or e.get("titel", "")).lower()
            if not e.get("titel") or not e.get("autor") or schluessel in gesehen:
                continue
            if re.search(r"(^|\b)(erratum|corrigendum|retraction|front matter|table of contents|index)\b", e["titel"], re.I):
                continue
            gesehen.add(schluessel)
            relevanz = float(w.get("relevance_score") or 0) or (30 - pos)
            wert = relevanz * (1 + 0.15 * math.log1p(int(e.get("zitiert", "0")))) / (1 + 0.3 * rang_basis)
            kandidaten.append((wert, e))
    kandidaten.sort(key=lambda x: -x[0])
    return [e for _, e in kandidaten[:anzahl]]


# --- Literaturrecherche fuer ein ganzes Buch oder Kapitel ---------------------

def recherche(daten: dict[str, Any], *, kapitel: str = "", je_unterkapitel: int = 3,
              ab_jahr: int = 2005) -> tuple[Path, dict[str, int]]:
    """Sucht zu jedem Unterkapitel passende Literatur, erfasst sie als Quellen
    und schreibt ein eigenes Dokument 'Literaturrecherche - <Titel>.odt'."""

    if str(kapitel or "").strip():
        auswahl = [kapitel_finden(daten, kapitel)]
    else:
        auswahl = list(range(len(daten["kapitel"])))
    if not auswahl:
        raise BuchFehler("Das Buch hat noch keine Kapitel - zuerst die Gliederung festlegen.")
    bericht = {"themen": 0, "funde": 0, "neu": 0}
    rechercheteile = []
    for i in auswahl:
        k = daten["kapitel"][i]
        unter = [u for u in re.findall(r"^##\s+(.+)$", k["text"], re.M)
                 if not re.match(r"^\s*einleitung\b", u, re.I)] or [k["titel"]]
        abschnitte = []
        for u in unter:
            thema = u if len(u.split()) >= 3 else f"{u} {k['titel']}"
            thema = re.sub(r"\s*[–-]\s*", " ", thema)
            funde = literatur_suchen(thema, anzahl=je_unterkapitel, ab_jahr=ab_jahr)
            bericht["themen"] += 1
            bericht["funde"] += len(funde)
            zeilen, schluessel = [f"## {u}"], []
            for f in funde:
                vorher = len(daten["quellen"])
                s = quelle_hinzufuegen(daten, **{x: y for x, y in f.items() if x not in ("zitiert", "typ", "kurzfassung")})
                bericht["neu"] += len(daten["quellen"]) - vorher
                schluessel.append(f"[@{s}]")
                zeilen.append(f"- {literatur_eintrag(daten['quellen'][s])}"
                              + (f" – {f['zitiert']}-mal zitiert" if f.get("zitiert") else "")
                              + f" – im Buch: [@{s}]".replace("[@", "Schlüssel ").replace("]", ""))
                if f.get("kurzfassung"):
                    zeilen.append(f"> {f['kurzfassung'][:450]}…")
            if not funde:
                zeilen.append("Keine passende Fachliteratur gefunden – anderer Suchbegriff nötig.")
            abschnitte.append("\n\n".join(zeilen))
            if schluessel:
                k["notizen"].append({"text": f"Literatur zu «{u}»: " + ", ".join(schluessel),
                                     "datum": _dt.datetime.now().strftime("%d.%m.%Y %H:%M")})
        rechercheteile.append({"titel": k["titel"], "text": "\n\n".join(abschnitte), "notizen": []})
    speichern(daten)
    liste = {"titel": f"Literaturrecherche – {daten['titel']}", "untertitel": "Quellen nach Kapiteln (OpenAlex)",
             "autor": daten.get("autor", ""), "kurzname": daten["kurzname"] + "-recherche",
             "kapitel": rechercheteile, "notizen": [], "quellen": daten["quellen"], "bilder": []}
    dateiname = re.sub(r'[<>:"/\\|?*]', "", f"Literaturrecherche - {daten['titel'][:50]}").strip()
    pfad, _ = exportieren(liste, ziel=ausgabe_ordner() / f"{dateiname}.odt")
    return pfad, bericht
