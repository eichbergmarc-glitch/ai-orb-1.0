"""Richtet den Zugang zum Orb von anderen Geraeten ein.

Das Skript nimmt drei Dinge in die Hand, die man sonst von Hand
zusammensuchen muesste:

1. Es legt ein Losungswort an (und schreibt es in ``.env``), damit von
   aussen nur hereinkommt, wer es kennt.
2. Es sucht Tailscale und richtet die verschluesselte Weiterleitung ein.
   Ohne echtes HTTPS gibt es auf einem iPad weder Mikrofon noch ein
   Symbol auf dem Startbildschirm - Apple erlaubt beides nur auf
   gesicherten Seiten.
3. Es sagt am Ende genau eine Adresse, die auf dem iPad einzutippen ist.

Es aendert nichts am laufenden Orb. Wer es zweimal aufruft, bekommt
dasselbe Losungswort - sonst muesste man jedes Geraet neu anmelden.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
ENV_DATEI = WURZEL / ".env"
SCHLUESSEL = "AI_ORB_WEB_TOKEN"

# Wo Tailscale unter Windows liegt, wenn es nicht im Suchpfad steht.
TAILSCALE_ORTE = [
    Path(r"C:\Program Files\Tailscale\tailscale.exe"),
    Path(r"C:\Program Files (x86)\Tailscale\tailscale.exe"),
    Path("/usr/bin/tailscale"),
    Path("/usr/local/bin/tailscale"),
]


#: Wohin die Mitschrift am Ende geschrieben wird (hoechstens ein Ziel).
_MITSCHRIFT: list[Path] = []

#: Jede Zeile, die gesagt wurde.
_ZEILEN: list[str] = []


def sagen(text: str = "") -> None:
    """Sagt etwas - auf dem Bildschirm und fuer die Mitschrift."""

    _ZEILEN.append(text)
    print(text, flush=True)


def _mitschrift_schreiben(ziel: Path) -> None:
    """Legt alles Gesagte als Datei ab."""

    try:
        ziel.write_text("\n".join(_ZEILEN) + "\n", encoding="utf-8")
    except OSError:
        pass


#: Zeichen fuer das Losungswort. Ohne 0/O und 1/l/I - auf einem iPad-
#: Bildschirm sind die nicht auseinanderzuhalten, und ein falsch
#: abgetipptes Zeichen sieht aus wie ein kaputter Zugang.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _ist_abtippbar(wort: str) -> bool:
    """Ob ein Losungswort die kurze, gegliederte Form hat."""

    teile = wort.split("-")
    return len(teile) == 3 and all(len(teil) == 4 for teil in teile)


def neues_losungswort() -> str:
    """Wuerfelt ein kurzes, abtippbares Losungswort.

    Zwoelf Zeichen aus einunddreissig ergeben rund sechzig Bit - raten ist
    aussichtslos, abtippen dauert zehn Sekunden. Die Bindestriche stehen
    mit im Wort und werden mitgetippt; sie sind kein Schmuck, sondern die
    Stelle, an der das Auge beim Abtippen wieder findet.
    """

    zeichen = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{zeichen[0:4]}-{zeichen[4:8]}-{zeichen[8:12]}"


def losungswort_holen(erneuern: bool = False) -> str:
    """Liest das vorhandene Losungswort - oder legt eines an.

    Ohne ``erneuern`` bleibt ein vorhandenes Wort stehen. Ein neues Wort
    sperrt jedes bereits angemeldete Geraet aus, und das darf nicht als
    Nebenwirkung eines zweiten Aufrufs passieren.
    """

    zeilen: list[str] = []
    if ENV_DATEI.exists():
        zeilen = ENV_DATEI.read_text(encoding="utf-8").splitlines()
        if not erneuern:
            for zeile in zeilen:
                name, gleich, wert = zeile.partition("=")
                if gleich and name.strip() == SCHLUESSEL and wert.strip():
                    vorhanden = wert.strip().strip("\"'")
                    if _ist_abtippbar(vorhanden):
                        return vorhanden
                    # Ein Wort aus der ersten Fassung: 32 Zeichen ohne
                    # Trennung. Auf einem iPad abzutippen ist das eine
                    # Zumutung, und niemand ist damit bisher angemeldet.
                    sagen("Das bisherige Losungswort war zu lang zum Abtippen.")
                    sagen("Es wird durch ein kuerzeres ersetzt. Ein Geraet, das")
                    sagen("sich damit schon angemeldet hatte, meldet sich neu an.")
                    break

    wort = neues_losungswort()

    zeilen = [z for z in zeilen if not z.startswith(f"{SCHLUESSEL}=")]
    while zeilen and not zeilen[-1].strip():
        zeilen.pop()
    if zeilen:
        zeilen.append("")
    zeilen.append("# Losungswort fuer den Zugang von anderen Geraeten (iPad, Handy).")
    zeilen.append("# Wer es kennt, kommt an den Orb. Nicht weitergeben.")
    zeilen.append(f"{SCHLUESSEL}={wort}")
    ENV_DATEI.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    sagen(f"Neues Losungswort angelegt und in {ENV_DATEI.name} gespeichert.")
    return wort


def firewall_oeffnen(port: int) -> bool:
    """Laesst Windows Anfragen aus dem eigenen Netz auf diesen Port durch.

    Ohne diese Regel verwirft Windows die Anfrage des iPad stillschweigend
    - der Orb sieht sie nie, und auf dem iPad steht nur, die Seite sei
    nicht erreichbar. Die alte Regel wird vorher entfernt, damit ein
    zweiter Aufruf nicht eine zweite Regel gleichen Namens anlegt.
    """

    if os.name != "nt":
        sagen("Firewall-Regel uebersprungen (kein Windows).")
        return True

    name = "AI-Orb"
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    ergebnis = subprocess.run(
        [
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={name}",
            "dir=in", "action=allow", "protocol=TCP",
            f"localport={port}",
            "profile=private",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if ergebnis.returncode == 0:
        sagen(f"Firewall geoeffnet fuer Port {port} (nur im privaten Netz).")
        return True

    sagen("Die Firewall-Regel konnte nicht angelegt werden.")
    sagen("Meist fehlen dafuer Administratorrechte.")
    ausgabe = (ergebnis.stdout + ergebnis.stderr).strip()
    if ausgabe:
        sagen(f"  {ausgabe.splitlines()[0]}")
    return False


def tailscale_finden() -> str | None:
    """Sucht das Tailscale-Programm."""

    gefunden = shutil.which("tailscale")
    if gefunden:
        return gefunden
    for ort in TAILSCALE_ORTE:
        if ort.exists():
            return str(ort)
    return None


def tailscale_fragen(programm: str, *argumente: str) -> tuple[int, str]:
    """Ruft Tailscale auf und faengt alles ab, was schiefgehen kann."""

    try:
        ergebnis = subprocess.run(
            [programm, *argumente],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as fehler:
        return 1, str(fehler)
    return ergebnis.returncode, (ergebnis.stdout + ergebnis.stderr).strip()


def geraetename(programm: str) -> str | None:
    """Liest den Namen, unter dem dieser Rechner im eigenen Netz steht."""

    code, ausgabe = tailscale_fragen(programm, "status", "--json")
    if code != 0:
        return None
    import json

    try:
        daten = json.loads(ausgabe)
    except json.JSONDecodeError:
        return None
    selbst = daten.get("Self") or {}
    name = str(selbst.get("DNSName", "")).rstrip(".")
    return name or None


def port_lesen() -> int:
    """Holt den Port aus der Konfiguration, ohne den Orb zu starten."""

    sys.path.insert(0, str(WURZEL))
    try:
        from backend.config import get_config

        return int(get_config().section("backend").get("port", 8756))
    except Exception:
        return 8756


def eigene_netzadresse() -> str | None:
    """Findet die Adresse dieses Rechners im eigenen WLAN.

    Der Trick: Man tut so, als wollte man ins Internet telefonieren. Das
    Betriebssystem waehlt dabei die Netzwerkkarte aus, ueber die es
    hinausginge - und verraet damit deren Adresse. Gesendet wird nichts.
    """

    import socket

    verbindung = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        verbindung.connect(("192.0.2.1", 9))
        return str(verbindung.getsockname()[0])
    except OSError:
        return None
    finally:
        verbindung.close()


#: Die Zeile, die den Server auf das eigene Netz umstellt - genau so, wie
#: sie in der mitgelieferten config.yaml steht.
HOST_ALT = (
    'backend:\n'
    '  # Host, auf dem der lokale REST-/WebSocket-Server lauscht.\n'
    '  host: "127.0.0.1"'
)

HOST_NEU = (
    'backend:\n'
    '  # Host, auf dem der lokale REST-/WebSocket-Server lauscht.\n'
    '  #\n'
    '  # "127.0.0.1" heisst: nur dieser Rechner. "0.0.0.0" heisst: auch\n'
    '  # andere Geraete im selben Netz - noetig fuer iPad und Handy im\n'
    '  # Heim-WLAN. Hereingelassen wird trotzdem nur, wer das Losungswort\n'
    '  # aus der .env kennt (AI_ORB_WEB_TOKEN).\n'
    '  host: "0.0.0.0"'
)


def auf_das_netz_hoeren() -> bool:
    """Stellt den Server in der config.yaml auf das eigene Netz um.

    Geaendert wird genau eine Zeile, und nur die im Abschnitt `backend`.
    Eine Sicherung liegt daneben, damit der Rueckweg eine Umbenennung ist.
    """

    datei = WURZEL / "config.yaml"
    if not datei.exists():
        sagen("config.yaml wurde nicht gefunden.")
        return False

    text = datei.read_text(encoding="utf-8")
    if 'host: "0.0.0.0"' in text:
        sagen("Der Server hoert bereits auf das ganze Netz.")
        return True

    if HOST_ALT not in text:
        sagen("Die Zeile mit host konnte nicht sicher gefunden werden.")
        sagen('Bitte in der config.yaml unter "backend:" von Hand setzen:')
        sagen('  host: "0.0.0.0"')
        return False

    (WURZEL / "config.yaml.vor-fernzugang").write_text(text, encoding="utf-8")
    datei.write_text(text.replace(HOST_ALT, HOST_NEU, 1), encoding="utf-8")
    sagen("config.yaml umgestellt (Sicherung: config.yaml.vor-fernzugang).")
    return True


def wlan_weg(wort: str, port: int) -> int:
    """Der kurze Weg: iPad und Rechner im selben WLAN, ohne Tailscale."""

    if not auf_das_netz_hoeren():
        return 1

    firewall_ok = firewall_oeffnen(port)

    adresse = eigene_netzadresse()
    if adresse is None:
        sagen("Die eigene Netzadresse liess sich nicht ermitteln.")
        sagen("Sie steht in Windows unter Einstellungen > Netzwerk > WLAN.")
        adresse = "<Adresse-dieses-Rechners>"

    sagen()
    sagen("=" * 62)
    sagen("  Fertig eingerichtet. Noch zwei Handgriffe:")
    sagen("=" * 62)
    sagen()
    sagen("  1. Den Orb einmal beenden und neu starten (ORB-STARTEN.bat).")
    sagen("     Erst dann hoert er auf das Netz statt nur auf sich selbst.")
    sagen()
    sagen("  2. Auf dem iPad Safari oeffnen und eintippen:")
    sagen()
    sagen(f"        {adresse}:{port}")
    sagen()
    sagen("     Es kommt eine Seite, die nach dem Losungswort fragt:")
    sagen()
    sagen(f"        {wort}")
    sagen()
    sagen("     Danach merkt das iPad es sich - ein Jahr lang.")
    sagen()
    sagen("=" * 62)

    if not firewall_ok:
        sagen()
        sagen("ACHTUNG: Die Firewall-Regel fehlt noch. Ohne sie verwirft")
        sagen("Windows die Anfrage des iPad, ohne dass jemand etwas merkt.")
        sagen("Diese Datei bitte mit Rechtsklick > Als Administrator")
        sagen("ausfuehren noch einmal starten.")
        return 1

    sagen()
    sagen("Das gilt im eigenen WLAN. Unterwegs ist der Orb damit noch")
    sagen("nicht erreichbar, und weil die Verbindung unverschluesselt")
    sagen("ist, erlaubt Apple weder Mikrofon noch ein Symbol auf dem")
    sagen("Startbildschirm. Beides bringt der Weg ueber Tailscale.")
    return 0


def main() -> int:
    # Alles, was hier gesagt wird, landet zusaetzlich in einer Datei.
    # Ein Konsolenfenster schliesst sich irgendwann; die Datei bleibt und
    # kann bei Fragen einfach weitergegeben werden.
    protokoll = WURZEL / "logs" / "ipad-einrichtung.txt"
    try:
        protokoll.parent.mkdir(parents=True, exist_ok=True)
        _MITSCHRIFT.append(protokoll)
    except OSError:
        pass

    sagen("=" * 62)
    sagen("  Der Orb von anderen Geraeten aus")
    sagen("=" * 62)
    sagen()

    wort = losungswort_holen("--neu" in sys.argv)
    port = port_lesen()

    ergebnis = 1
    try:
        if "--wlan" in sys.argv:
            ergebnis = wlan_weg(wort, port)
            return ergebnis

        programm = tailscale_finden()
        if programm is None:
            sagen("Tailscale ist auf diesem Rechner nicht gefunden worden.")
            sagen()
            sagen("So geht es weiter:")
            sagen("  1. tailscale.com/download - Tailscale hier installieren")
            sagen("     und mit dem eigenen Konto anmelden.")
            sagen("  2. Dieselbe Anmeldung in der Tailscale-App auf dem iPad.")
            sagen("  3. Dieses Skript noch einmal aufrufen.")
            sagen()
            sagen("Ohne Tailscale bleibt nur das eigene WLAN. Dafuer muesste in")
            sagen('der config.yaml unter "backend:" der Wert host auf "0.0.0.0"')
            sagen("stehen - dann ist der Orb im Heimnetz erreichbar, aber ohne")
            sagen("HTTPS und damit ohne Mikrofon und ohne Symbol am iPad.")
            sagen()
            sagen(f"Das Losungswort lautet: {wort}")
            return 1

        name = geraetename(programm)
        if name is None:
            sagen("Tailscale ist da, aber noch nicht angemeldet.")
            sagen(f"Bitte einmal ausfuehren:  {programm} up")
            sagen("und danach dieses Skript erneut aufrufen.")
            sagen()
            sagen(f"Das Losungswort lautet: {wort}")
            return 1

        sagen(f"Dieser Rechner heisst im eigenen Netz: {name}")
        sagen("Richte die verschluesselte Weiterleitung ein ...")

        code, ausgabe = tailscale_fragen(
            programm, "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"
        )
        if code != 0:
            sagen()
            sagen("Das hat nicht geklappt. Tailscale meldet:")
            sagen(f"  {ausgabe or 'keine Ausgabe'}")
            sagen()
            sagen("Meist fehlt HTTPS im eigenen Netz. Es wird einmalig in der")
            sagen("Tailscale-Verwaltung eingeschaltet:")
            sagen("  login.tailscale.com/admin/dns  ->  HTTPS Certificates")
            sagen()
            sagen(f"Das Losungswort lautet: {wort}")
            return 1

        adresse = f"https://{name}/?token={wort}"

        sagen()
        sagen("=" * 62)
        sagen("  Fertig. Auf dem iPad in Safari eingeben:")
        sagen()
        sagen(f"  {adresse}")
        sagen()
        sagen("=" * 62)
        sagen()
        sagen("Das Losungswort merkt sich der Browser danach von selbst -")
        sagen("es muss nur dieses eine Mal in der Adresse stehen.")
        sagen()
        sagen("Voraussetzungen, damit die Adresse antwortet:")
        sagen("  - Dieser Rechner laeuft und der Orb ist gestartet.")
        sagen("  - Auf dem iPad ist Tailscale installiert, angemeldet und an.")
        return 0
    finally:
        if protokoll.exists() or _MITSCHRIFT:
            _mitschrift_schreiben(protokoll)


if __name__ == "__main__":
    raise SystemExit(main())
