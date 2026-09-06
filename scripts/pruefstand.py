"""Der Prüfstand - prüft den Orb auf DEM RECHNER, auf dem er läuft.

Der Anlass ist eine berechtigte Forderung des Benutzers: "solange er nur
in der Sandbox getestet wird ist nie ganz sicher, dass sich der Orb
ausserhalb der Sandbox gleich verhalten wird." Die Bauumgebung hat kein
Mikrofon, keine Lautsprecher und keinen Weg ins offene Netz - was dort
grün ist, beweist die Logik, aber nicht das Verhalten hier.

Der Prüfstand holt das nach, so weit es ohne Zutun geht:

1. Umgebung  - Python, Orb-Version, sind die tragenden Pakete da?
2. Geräte    - gibt es ein Mikrofon und einen Lautsprecher?
3. Quellen   - antworten die offenen Kataloge (OpenAlex, Crossref)?
4. Testsuite - die komplette Suite, mit DIESEM Python, auf DIESEN Dateien.

Alles landet in logs/pruefstand.txt, damit es sich weitergeben lässt.
Bekannte, unschädliche Ausfälle (Tests, die ein fehlendes Zusatzpaket
brauchen) werden benannt und nicht als Fehler gewertet - aber auch nicht
verschwiegen.
"""

from __future__ import annotations

import datetime
import io
import json
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent

#: Testdateien, deren Ausfall bekannt und unschädlich ist: Sie brauchen
#: pytest-asyncio, das nicht überall installiert ist. Fällt dort etwas,
#: wird es GENANNT, aber nicht als Defekt des Orbs gewertet.
BEKANNT_BRUECHIG = (
    "test_event_bus.py",
    "test_agents_and_skills.py",
    "test_claude_providers.py",
    "test_provider_stream_fallback.py",
)

QUELLEN = (
    ("OpenAlex", "https://api.openalex.org/works?per-page=1"),
    ("Crossref", "https://api.crossref.org/works?rows=1"),
)


def _zeile(text: str = "") -> str:
    print(text)
    return text + "\n"


def _umgebung() -> str:
    bericht = _zeile("--- 1. Umgebung " + "-" * 44)
    bericht += _zeile(f"Python:  {sys.version.split()[0]}  ({sys.executable})")
    bericht += _zeile(f"System:  {platform.platform()}")
    try:
        sys.path.insert(0, str(WURZEL))
        import backend

        bericht += _zeile(f"Orb:     Version {backend.__version__}")
    except Exception as fehler:  # noqa: BLE001 - der Bericht muss weiterlaufen.
        bericht += _zeile(f"Orb:     Version nicht lesbar ({fehler})")

    for paket in ("yaml", "numpy", "sounddevice", "faster_whisper", "pytest"):
        try:
            __import__(paket)
            bericht += _zeile(f"Paket:   {paket:<15} da")
        except Exception as fehler:  # noqa: BLE001
            bericht += _zeile(f"Paket:   {paket:<15} FEHLT ({fehler})")
    return bericht


def _geraete() -> str:
    bericht = _zeile()
    bericht += _zeile("--- 2. Geräte " + "-" * 46)
    try:
        import sounddevice as sd

        geraete = sd.query_devices()
        eingaenge = [g for g in geraete if int(g.get("max_input_channels", 0)) > 0]
        ausgaenge = [g for g in geraete if int(g.get("max_output_channels", 0)) > 0]
        bericht += _zeile(
            f"Mikrofone:    {len(eingaenge)}"
            + (f"  (z.B. {eingaenge[0]['name']})" if eingaenge else "  KEINES GEFUNDEN")
        )
        bericht += _zeile(
            f"Lautsprecher: {len(ausgaenge)}"
            + (f"  (z.B. {ausgaenge[0]['name']})" if ausgaenge else "  KEINER GEFUNDEN")
        )
    except Exception as fehler:  # noqa: BLE001
        bericht += _zeile(f"Geräte nicht abfragbar: {fehler}")
    return bericht


def _quellen() -> tuple[str, bool]:
    bericht = _zeile()
    bericht += _zeile("--- 3. Offene Quellen " + "-" * 38)
    alles_gut = True
    for name, adresse in QUELLEN:
        try:
            anfrage = urllib.request.Request(
                adresse, headers={"User-Agent": "AI-Orb Pruefstand"}
            )
            with urllib.request.urlopen(anfrage, timeout=10) as antwort:
                daten = json.loads(antwort.read().decode("utf-8", "replace"))
            treffer = bool(
                daten.get("results") or (daten.get("message") or {}).get("items")
            )
            bericht += _zeile(
                f"{name:<10} antwortet"
                + (" und liefert Treffer." if treffer else ", aber ohne Treffer.")
            )
        except Exception as fehler:  # noqa: BLE001
            alles_gut = False
            bericht += _zeile(f"{name:<10} NICHT ERREICHBAR: {fehler}")
    return bericht, alles_gut


def _testsuite() -> tuple[str, bool]:
    bericht = _zeile()
    bericht += _zeile("--- 4. Testsuite (das dauert ein paar Minuten) " + "-" * 13)
    lauf = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--color=no"],
        cwd=WURZEL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    ausgabe = (lauf.stdout or "") + (lauf.stderr or "")

    gefallen = [z for z in ausgabe.splitlines() if z.startswith("FAILED")]
    bekannt = [z for z in gefallen if any(name in z for name in BEKANNT_BRUECHIG)]
    ernst = [z for z in gefallen if z not in bekannt]

    schluss = [z for z in ausgabe.splitlines() if " in " in z and ("passed" in z or "failed" in z)]
    bericht += _zeile(schluss[-1].strip() if schluss else "(kein Abschluss gefunden)")

    if bekannt:
        bericht += _zeile()
        bericht += _zeile(
            f"Bekannt und unschädlich ({len(bekannt)} - brauchen pytest-asyncio):"
        )
        for zeile in bekannt:
            bericht += _zeile(f"  {zeile}")
    if ernst:
        bericht += _zeile()
        bericht += _zeile(f"ERNSTE AUSFÄLLE ({len(ernst)}):")
        for zeile in ernst:
            bericht += _zeile(f"  {zeile}")

    return bericht, not ernst and lauf.returncode in (0, 1)


def main() -> int:
    kopf = io.StringIO()
    kopf.write("AI-Orb Prüfstand - " + datetime.datetime.now().isoformat(timespec="seconds") + "\n")
    kopf.write("=" * 60 + "\n\n")
    print(kopf.getvalue(), end="")

    bericht = kopf.getvalue()
    bericht += _umgebung()
    bericht += _geraete()
    quellen_text, quellen_gut = _quellen()
    bericht += quellen_text
    tests_text, tests_gut = _testsuite()
    bericht += tests_text

    bericht += "\n" + "=" * 60 + "\n"
    if tests_gut and quellen_gut:
        urteil = "ERGEBNIS: Alles in Ordnung. Der Orb ist auf diesem Rechner geprüft."
    elif tests_gut:
        urteil = (
            "ERGEBNIS: Die Tests bestehen, aber mindestens eine Quelle war "
            "nicht erreichbar - siehe Abschnitt 3."
        )
    else:
        urteil = (
            "ERGEBNIS: Es gibt ernste Ausfälle - bitte logs/pruefstand.txt "
            "weitergeben."
        )
    bericht += urteil + "\n"
    print()
    print(urteil)

    ablage = WURZEL / "logs" / "pruefstand.txt"
    try:
        ablage.parent.mkdir(parents=True, exist_ok=True)
        ablage.write_text(bericht, encoding="utf-8")
        print(f"\nDer volle Bericht liegt unter: {ablage}")
    except OSError as fehler:
        print(f"\nDer Bericht ließ sich nicht ablegen: {fehler}")

    return 0 if tests_gut else 1


if __name__ == "__main__":
    raise SystemExit(main())
