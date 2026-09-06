"""
patchschmied.py - Macht aus einer Idee eine konkrete Codeaenderung.
================================================================================

Warum es diese Datei gibt
-------------------------
Der erste Nachtlauf hat es gezeigt: Alle elf Ideen des Ideengenerators waren
Beschreibungen, keine Aenderungen. "Wartbarkeit der Architektur verbessern"
nennt nicht einmal eine Datei. Zwischen "ich sehe ein Problem" und "ich kann
es beheben" klafft eine Luecke, und hier wird sie geschlossen.

Der Grundsatz: EINE Funktion auf einmal
---------------------------------------
Das Sprachmodell bekommt nie eine ganze Datei zu sehen und schreibt nie eine
ganze Datei. Es bekommt genau eine Funktion, das Problem dazu, und liefert
genau diese Funktion zurueck. Ersetzt wird ueber den Syntaxbaum.

Das ist keine Bequemlichkeit, sondern die eigentliche Absicherung. Ein
Modell dieser Groesse schreibt zuverlaessig Unsinn, sobald es viel auf
einmal soll. Auf eine Funktion begrenzt, laesst sich jede Antwort streng
pruefen: Ist es syntaktisch gueltig? Heisst sie noch so? Hat sie dieselben
Parameter? Ist ausserhalb nichts angeruehrt? Ist die Datei danach noch
uebersetzbar? Faellt eine dieser Fragen negativ aus, wird verworfen - und
das ist der Normalfall, nicht die Ausnahme.

Was hier NICHT passiert
-----------------------
Es wird nichts geschrieben. Diese Datei liefert den neuen Dateiinhalt als
Text zurueck; was damit geschieht, entscheidet die Evolution Engine mit
ihrer Arbeitskopie, ihren Tests und ihrem Review. Der Patchschmied ist der
Vorschlagende, nicht der Entscheidende.
"""

from __future__ import annotations

import ast
import json
import os
import re
import textwrap
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

#: Ordner, die nur GANZ OBEN im Projekt uebergangen werden.
#:
#: Die Unterscheidung ist keine Feinheit. Eine einzige Liste, die in jeder
#: Tiefe greift, hat den haeufigsten Fehler ueberhaupt verschluckt: Der
#: Mikrofonfehler steckt in ``backend/audio/audio_capture.py``, und
#: ``audio`` stand in der Liste - gemeint war der Ordner mit den
#: Klangproben oben im Projekt. Vierzehn Vorfaelle, lautlos uebergangen.
TABU_OBEN = {
    "runtime", "node_modules", "build", "dist", "logs", "data", "tmp",
    "models", "audio", "ipad", "werkzeug", "tests", "AI-Orb-iPad",
}

#: Ordner, die in jeder Tiefe uebergangen werden - dazu alles, was mit
#: einem Punkt beginnt (.git, .venv, .pytest_cache, .godot, .tools).
TABU_UEBERALL = {"__pycache__", "node_modules"}


def _uebergangen(rel: Path) -> bool:
    """Sagt, ob ein Weg unterhalb des Projekts uebersprungen wird."""

    teile = rel.parts
    if not teile:
        return True
    if teile[0] in TABU_OBEN:
        return True
    return any(t in TABU_UEBERALL or t.startswith(".") for t in teile[:-1])

#: Ab wie vielen Zeilen eine Funktion als zu lang gilt.
ZU_LANG = 80

#: Wie stark eine Funktion hoechstens wachsen darf. Eine Antwort, die das
#: Dreifache umfasst, hat das Thema verfehlt.
WACHSTUM = 3.0


@dataclass
class Ziel:
    """Eine Stelle, an der sich etwas beheben laesst."""

    art: str                      # "fehler", "dokumentation", "laenge"
    datei: Path
    funktion: str
    problem: str
    auftrag: str
    gewicht: int = 1
    zeile: int = 0

    def titel(self) -> str:
        kurz = self.datei.name
        return f"{self.art}: {kurz}::{self.funktion} - {self.problem[:60]}"


# ===================================================== Ziele aus den Protokollen
_RAHMEN = re.compile(r'File "([^"]+)", line (\d+), in (\w+)')
_FEHLERZEILE = re.compile(r"^(\w*(?:Error|Exception|Warning))\b:?\s*(.*)$")


def ziele_aus_protokollen(wurzel: Path, hoechstens: int = 5) -> list[Ziel]:
    """Sucht wiederkehrende Ausnahmen und findet die Stelle im Quelltext.

    Nur was mit Rueckverfolgung im Protokoll steht, ist verwertbar: Erst der
    letzte Rahmen INNERHALB des Projekts sagt, welche Funktion es angeht.
    Eine Meldung ohne Rueckverfolgung nennt kein Ziel und wird uebergangen -
    lieber nichts vorschlagen als ins Blaue.
    """

    ordner = wurzel / "logs"
    if not ordner.is_dir():
        return []

    zaehler: Counter[tuple[str, str, str]] = Counter()
    beispiele: dict[tuple[str, str, str], tuple[int, str]] = {}

    # Nach Aenderungsdatum, nicht nach Namen: Gesucht sind die
    # juengsten Protokolle, nicht die alphabetisch letzten.
    juengste = sorted(ordner.glob("*.log"),
                      key=lambda d: d.stat().st_mtime)[-6:]
    for protokoll in juengste:
        try:
            text = protokoll.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for block in text.split("Traceback (most recent call last)"):
            rahmen = _RAHMEN.findall(block)
            if not rahmen:
                continue
            eigene = [
                (d, int(z), f) for d, z, f in rahmen
                if _gehoert_dazu(Path(d), wurzel)
            ]
            if not eigene:
                continue
            datei, zeile, funktion = eigene[-1]
            meldung = ""
            for zeile_text in block.splitlines():
                treffer = _FEHLERZEILE.match(zeile_text.strip())
                if treffer:
                    meldung = f"{treffer.group(1)}: {treffer.group(2)}"[:200]
            schluessel = (datei, funktion, meldung.split(":")[0])
            zaehler[schluessel] += 1
            beispiele.setdefault(schluessel, (zeile, meldung))

    ziele: list[Ziel] = []
    for (datei, funktion, _art), anzahl in zaehler.most_common(hoechstens):
        rel = _teilpfad(datei, wurzel)
        if rel is None:
            continue
        pfad = wurzel / rel
        if not pfad.is_file():
            continue
        zeile, meldung = beispiele[(datei, funktion, _art)]
        ziele.append(Ziel(
            art="fehler", datei=pfad, funktion=funktion, zeile=zeile,
            problem=meldung or "wiederkehrende Ausnahme",
            gewicht=anzahl,
            auftrag=(
                f"In dieser Funktion tritt im Betrieb wiederholt folgender "
                f"Fehler auf (Zeile {zeile}):\n{meldung}\n\n"
                "Behebe die Ursache. Fange den Fehler nicht nur ab, wenn sich "
                "die Ursache beheben laesst. Aendere nichts, was mit diesem "
                "Fehler nichts zu tun hat."
            ),
        ))
    return ziele


def _teilpfad(gemeldet: str, wurzel: Path) -> Path | None:
    """Macht aus einem protokollierten Pfad den Weg innerhalb des Projekts.

    Zwei Dinge sind hier zu beachten, und beide haben schon Ziele
    verschluckt. Erstens steht in den Protokollen die Windows-Schreibweise
    mit Rueckstrichen; wer sie mit ``Path`` einliest, bekommt anderswo einen
    einzigen langen Dateinamen statt eines Weges. Deshalb wird von Hand
    getrennt, an beiden Strichen.

    Zweitens ist der protokollierte Pfad absolut - und zeigt damit auf den
    Ordner, in dem der Fehler EINMAL aufgetreten ist. Zurueckgegeben wird
    darum nur der Weg unterhalb des Projektordners; wohin der zeigt,
    entscheidet der Aufrufer mit seiner eigenen Wurzel.
    """

    teile = [t for t in gemeldet.replace("\\", "/").split("/") if t and t != "."]
    if not teile:
        return None

    name = wurzel.resolve().name.lower()
    # Von hinten suchen: Liegt eine Kopie des Projekts im Projekt, gilt der
    # innerste Treffer.
    for stelle in range(len(teile) - 1, -1, -1):
        if teile[stelle].lower() == name:
            rest = teile[stelle + 1:]
            return Path(*rest) if rest else None

    # Ein relativer Pfad ohne Wurzelnamen - z.B. "backend\\api\\server.py".
    # Der zaehlt nur mit, wenn er im Projekt auch wirklich existiert.
    versuch = Path(*teile)
    return versuch if (wurzel / versuch).is_file() else None


def _gehoert_dazu(pfad: Path, wurzel: Path) -> bool:
    rel = _teilpfad(str(pfad), wurzel)
    return rel is not None and not _uebergangen(rel)


# ========================================================== Ziele aus dem Code
def python_dateien(wurzel: Path):
    """Liefert die eigenen Python-Dateien des Projekts.

    Abgeschnitten wird beim Gehen, nicht hinterher. Das ist der ganze
    Unterschied zwischen zwei Sekunden und Minuten: Unter ``runtime`` liegt
    ein vollstaendiger Python-Unterbau, daneben ``node_modules`` - zusammen
    Zehntausende Dateien, die niemanden interessieren. Wer sie erst
    einsammelt und dann wegwirft, hat sie trotzdem alle angefasst.
    """

    for ordner, unterordner, dateien in os.walk(wurzel):
        oben = Path(ordner) == Path(wurzel)
        # Aendert die Liste an Ort und Stelle - nur so laesst os.walk die
        # betroffenen Ordner wirklich aus. Versteckte Ordner sind nie
        # eigener Quelltext: .git, .venv, .pytest_cache - und Beigepacktes
        # wie games/nullprotokoll/.tools, ein ganzer Godot-Unterbau mit
        # fast neuntausend Dateien.
        unterordner[:] = sorted(
            u for u in unterordner
            if not u.startswith(".")
            and u not in TABU_UEBERALL
            and not (oben and u in TABU_OBEN)
        )
        for name in sorted(dateien):
            if name.endswith(".py"):
                yield Path(ordner) / name


def ziele_aus_code(wurzel: Path, hoechstens: int = 5) -> list[Ziel]:
    """Findet Funktionen ohne Dokumentation und zu lange Funktionen.

    Bewusst selbst gesucht statt aus dem Ideengenerator uebernommen: Der
    liefert Sammelbefunde ("159 ueberlange Funktionen"), und eine Sammlung
    laesst sich nicht patchen. Gebraucht wird EINE Funktion mit Namen.
    """

    ohne_doku: list[Ziel] = []
    zu_lang: list[Ziel] = []

    for pfad in python_dateien(wurzel):
        try:
            quelle = pfad.read_text(encoding="utf-8")
            baum = ast.parse(quelle)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            # Eine Datei, die sich nicht lesen oder nicht uebersetzen
            # laesst, ist kein Ziel - aber auch kein Grund, den ganzen
            # Durchlauf abzubrechen.
            continue
        for knoten in ast.walk(baum):
            if not isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if knoten.name.startswith("__"):
                continue
            laenge = (knoten.end_lineno or knoten.lineno) - knoten.lineno
            if ast.get_docstring(knoten) is None and 6 <= laenge <= 60:
                ohne_doku.append(Ziel(
                    art="dokumentation", datei=pfad, funktion=knoten.name,
                    zeile=knoten.lineno, problem="ohne Dokumentation",
                    gewicht=laenge,
                    auftrag=(
                        "Diese Funktion hat keinen Dokumentationstext. Ergaenze "
                        "einen deutschen Docstring im Stil des Projekts: Was tut "
                        "sie, und warum ist sie so gebaut? Aendere am Code selbst "
                        "NICHTS - kein Zeichen ausser dem eingefuegten Docstring."
                    ),
                ))
            elif laenge > ZU_LANG:
                zu_lang.append(Ziel(
                    art="laenge", datei=pfad, funktion=knoten.name,
                    zeile=knoten.lineno, problem=f"{laenge} Zeilen lang",
                    gewicht=laenge,
                    auftrag=(
                        f"Diese Funktion ist {laenge} Zeilen lang und tut zu viel. "
                        "Gliedere sie. Das Verhalten muss exakt gleich bleiben, "
                        "Name und Parameter unveraendert. Hilfsfunktionen darfst "
                        "du INNERHALB dieser Funktion anlegen."
                    ),
                ))

    ohne_doku.sort(key=lambda z: -z.gewicht)
    zu_lang.sort(key=lambda z: -z.gewicht)
    return (_je_datei_eins(ohne_doku)[:hoechstens]
            + _je_datei_eins(zu_lang)[: max(0, hoechstens // 2)])


def _je_datei_eins(ziele: list[Ziel]) -> list[Ziel]:
    """Laesst je Datei nur das staerkste Ziel stehen.

    Drei Nachtpatches, alle drei in ``grafik_tools.py``, weil dort drei
    Klassen je eine Methode ``execute`` haben - das waere ein vertaner
    Lauf. Und es waere heikel: Bei gleichnamigen Funktionen in einer Datei
    muss die Ersetzung die richtige treffen, und jeder Versuch weniger ist
    ein Risiko weniger.
    """

    gesehen: set[Path] = set()
    behalten: list[Ziel] = []
    for ziel in ziele:
        if ziel.datei in gesehen:
            continue
        gesehen.add(ziel.datei)
        behalten.append(ziel)
    return behalten


# ================================================================ Das Modell
class Modell:
    """Das lokale Sprachmodell ueber Ollama."""

    def __init__(self, adresse: str, name: str) -> None:
        self.adresse = adresse.rstrip("/")
        self.name = name

    def fragen(self, auftrag: str, *, zeit: float = 300.0) -> str:
        anfrage = urllib.request.Request(
            f"{self.adresse}/api/generate",
            data=json.dumps({
                "model": self.name,
                "prompt": auftrag,
                "stream": False,
                "keep_alive": "30m",
                # Wenig Zufall: Es soll Code schreiben, nicht dichten.
                "options": {"temperature": 0.15, "top_p": 0.9, "num_predict": 1600},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(anfrage, timeout=zeit) as antwort:
            daten = json.loads(antwort.read().decode("utf-8", "replace"))
        return str(daten.get("response", ""))


VORLAGE = """Du bist ein sorgfaeltiger Python-Entwickler und arbeitest an einem \
deutschsprachigen Projekt. Kommentare und Dokumentation sind auf Deutsch.

Hier ist eine Funktion aus der Datei {datei}:

```python
{quelle}
```

Aufgabe:
{auftrag}

Regeln, die du einhalten MUSST:
- Antworte mit GENAU EINER Funktion in einem einzigen ```python-Block.
- Der Name der Funktion bleibt {funktion}.
- Die Parameter bleiben unveraendert.
- Kein Text vor oder nach dem Block. Keine Erklaerung.
- Keine neuen Importe auf Dateiebene. Brauchst du einen, importiere ihn
  innerhalb der Funktion.
- Aendere nichts, was mit der Aufgabe nichts zu tun hat.
"""


# =============================================================== Auspacken
_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


def auspacken(antwort: str) -> str | None:
    """Holt den Quelltext aus der Antwort des Modells."""

    treffer = _BLOCK.findall(antwort or "")
    if treffer:
        return textwrap.dedent(treffer[0]).strip("\n")
    # Manche Modelle vergessen den Block. Dann gilt: Faengt es mit def an,
    # nehmen wir es; sonst nicht.
    knapp = textwrap.dedent(antwort or "").strip("\n")
    if knapp.startswith(("def ", "async def ", "@")):
        return knapp
    return None


# ================================================================== Pruefen
@dataclass
class Urteil:
    ok: bool
    grund: str = ""
    inhalt: str = ""


def unterschrift(knoten) -> tuple:
    """Name und Parameter einer Funktion - das, was gleich bleiben muss."""

    a = knoten.args
    return (
        knoten.name,
        tuple(p.arg for p in a.posonlyargs),
        tuple(p.arg for p in a.args),
        a.vararg.arg if a.vararg else None,
        tuple(p.arg for p in a.kwonlyargs),
        a.kwarg.arg if a.kwarg else None,
        len(a.defaults),
        len(a.kw_defaults),
    )


def pruefen(datei: Path, alt: ast.AST, neu_quelle: str, quelle: str) -> Urteil:
    """Prueft die Antwort des Modells und baut den neuen Dateiinhalt.

    Jede einzelne Pruefung hier hat ihren Grund in dem, was Modelle dieser
    Groesse tatsaechlich tun: Sie benennen Funktionen um, erfinden Parameter,
    haengen Erklaerungen an, ziehen Importe nach oben und schreiben aus
    Versehen die halbe Datei neu.
    """

    try:
        neuer_baum = ast.parse(neu_quelle)
    except SyntaxError as fehler:
        return Urteil(False, f"nicht uebersetzbar ({fehler.msg}, Zeile {fehler.lineno})")

    koerper = [k for k in neuer_baum.body
               if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(neuer_baum.body) != len(koerper) or len(koerper) != 1:
        return Urteil(False, "die Antwort enthaelt nicht genau eine Funktion")

    neu = koerper[0]
    if unterschrift(neu) != unterschrift(alt):
        return Urteil(False, "Name oder Parameter wurden veraendert")

    alt_zeilen = (alt.end_lineno or alt.lineno) - alt.lineno + 1
    neu_zeilen = len(neu_quelle.splitlines())
    if neu_zeilen > alt_zeilen * WACHSTUM + 20:
        return Urteil(False, f"aus {alt_zeilen} Zeilen wurden {neu_zeilen}")

    # Der Austausch: exakt die Zeilen der alten Funktion, mit ihrer
    # Einrueckung. Ueber den Syntaxbaum, nicht ueber Textsuche - eine
    # gleichnamige Funktion in einer anderen Klasse bleibt unberuehrt.
    zeilen = quelle.splitlines(keepends=True)
    anfang = alt.lineno - 1
    if alt.decorator_list:
        anfang = min(d.lineno for d in alt.decorator_list) - 1
    ende = alt.end_lineno
    einzug = re.match(r"[ \t]*", zeilen[alt.lineno - 1]).group(0)
    eingerueckt = textwrap.indent(neu_quelle.rstrip("\n") + "\n", einzug)
    neuer_inhalt = "".join(zeilen[:anfang]) + eingerueckt + "".join(zeilen[ende:])

    try:
        compile(neuer_inhalt, str(datei), "exec")
    except SyntaxError as fehler:
        return Urteil(False, f"die Datei waere danach fehlerhaft ({fehler.msg})")

    # Es darf sich ausserhalb dieser einen Funktion nichts geaendert haben.
    if not _nur_diese_funktion(quelle, neuer_inhalt, alt.name):
        return Urteil(False, "es wurde ausserhalb der Funktion etwas veraendert")

    if neuer_inhalt == quelle:
        return Urteil(False, "keine Aenderung")
    return Urteil(True, inhalt=neuer_inhalt)


def _nur_diese_funktion(alt: str, neu: str, name: str) -> bool:
    """Vergleicht beide Fassungen ohne die betroffene Funktion.

    Ausgeblendet werden ALLE Funktionen dieses Namens, nicht nur die erste.
    Sonst scheitert der Vergleich, sobald derselbe Name zweimal vorkommt -
    etwa als Methode einer Klasse und als Funktion daneben: Ausgeblendet
    wuerde dann die eine, geaendert war die andere, und ein voellig
    einwandfreier Patch fiele durch.

    Dass wirklich nur eine davon angeruehrt wurde, ist ohnehin gesichert -
    ersetzt wird ueber den Syntaxbaum an genau einer Stelle.
    """

    def rest(quelle: str) -> str:
        baum = ast.parse(quelle)
        zeilen = quelle.splitlines(keepends=True)
        weg: list[tuple[int, int]] = []
        for knoten in ast.walk(baum):
            if (isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and knoten.name == name):
                anfang = knoten.lineno - 1
                if knoten.decorator_list:
                    anfang = min(d.lineno for d in knoten.decorator_list) - 1
                weg.append((anfang, knoten.end_lineno or knoten.lineno))
        behalten = [
            zeile for nummer, zeile in enumerate(zeilen)
            if not any(a <= nummer < e for a, e in weg)
        ]
        return "".join(behalten)

    try:
        return rest(alt) == rest(neu)
    except SyntaxError:
        return False


# ================================================================= Schmieden
@dataclass
class Ergebnis:
    ziel: Ziel
    gelungen: bool
    grund: str = ""
    aenderungen: dict[str, str] = field(default_factory=dict)


def funktion_finden(baum: ast.AST, name: str, zeile: int = 0):
    """Die passende Funktion - bei Namensgleichheit die naechste an der Zeile."""

    treffer = [k for k in ast.walk(baum)
               if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
               and k.name == name]
    if not treffer:
        return None
    if zeile and len(treffer) > 1:
        return min(treffer, key=lambda k: abs(k.lineno - zeile))
    return treffer[0]


def schmieden(ziel: Ziel, modell: Modell, *, versuche: int = 2) -> Ergebnis:
    """Laesst das Modell eine Funktion neu schreiben und prueft das Ergebnis."""

    try:
        quelle = ziel.datei.read_text(encoding="utf-8")
        baum = ast.parse(quelle)
    except (OSError, SyntaxError) as fehler:
        return Ergebnis(ziel, False, f"Datei nicht lesbar ({fehler})")

    knoten = funktion_finden(baum, ziel.funktion, ziel.zeile)
    if knoten is None:
        return Ergebnis(ziel, False, f"Funktion '{ziel.funktion}' nicht gefunden")

    zeilen = quelle.splitlines(keepends=True)
    anfang = knoten.lineno - 1
    if knoten.decorator_list:
        anfang = min(d.lineno for d in knoten.decorator_list) - 1
    ausschnitt = textwrap.dedent("".join(zeilen[anfang:knoten.end_lineno]))

    auftrag = VORLAGE.format(
        datei=ziel.datei.name, quelle=ausschnitt.rstrip(),
        auftrag=ziel.auftrag, funktion=ziel.funktion,
    )

    letzter = ""
    for _ in range(max(1, versuche)):
        try:
            antwort = modell.fragen(auftrag)
        except Exception as fehler:  # noqa: BLE001
            return Ergebnis(ziel, False, f"Modell nicht erreichbar ({str(fehler)[:60]})")
        neu = auspacken(antwort)
        if neu is None:
            letzter = "keine verwertbare Antwort"
            continue
        urteil = pruefen(ziel.datei, knoten, neu, quelle)
        if urteil.ok:
            return Ergebnis(ziel, True, aenderungen={str(ziel.datei): urteil.inhalt})
        letzter = urteil.grund
    return Ergebnis(ziel, False, letzter or "unbekannt")
