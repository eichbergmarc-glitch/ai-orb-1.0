"""Die Verbindung zu iPad und Handy - eingerichtet beim Start des Orb.

Der Orb soll auf dem iPad erreichbar sein, ohne dass jemand vorher eine
Datei anklickt. Dieses Modul kümmert sich beim Start darum: Es sucht
Tailscale, prüft die verschlüsselte Weiterleitung, richtet sie ein, wenn
sie fehlt, und schreibt die fertige Adresse auf.

Es ist die *einzige* Stelle im Programm, die weiß, wo Tailscale liegt und
wie man es anspricht. ``scripts/fernzugang.py`` benutzt dieselben
Funktionen. Zwei Kopien dieses Wissens wären zwei Kopien, die
auseinanderlaufen, sobald Tailscale sich das nächste Mal ändert - und
dann funktioniert der Fernzugang je nachdem, wer ihn eingerichtet hat.

Nichts hier darf den Start des Orb aufhalten oder beenden. Ein iPad ist
schön, aber der Orb läuft auch ohne. Deshalb hat jeder Aufruf nach außen
eine Frist, und jeder Fehler endet in einer Protokollzeile statt in einer
Ausnahme.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Wie lange auf Tailscale gewartet wird. Es antwortet in Sekundenbruch-
#: teilen; wartet man länger, ist etwas kaputt und Warten hilft nicht.
FRIST = 15.0

#: Feste Orte, falls der Suchpfad nichts hergibt.
BEKANNTE_ORTE = (
    Path(r"C:\Program Files\Tailscale\tailscale.exe"),
    Path(r"C:\Program Files (x86)\Tailscale\tailscale.exe"),
    Path("/usr/bin/tailscale"),
    Path("/usr/local/bin/tailscale"),
    Path("/opt/homebrew/bin/tailscale"),
)


def _aus_der_registry():
    """Sucht Tailscale dort, wo Windows jede Installation einträgt.

    Der Suchpfad ist unzuverlässig: Ein frisch installiertes Programm
    steht zwar darin, aber nur für Prozesse, die *danach* gestartet
    wurden. Der Orb läuft womöglich seit dem Anmelden und hat die alte
    Umgebung geerbt. Genau deshalb heißt es nach einer Neuinstallation so
    oft „nicht gefunden", obwohl das Programm dort liegt.

    Die Deinstallations-Einträge kennen diesen Zeitverzug nicht.
    """

    if os.name != "nt":
        return

    import winreg

    zweige = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )

    for wurzel, pfad in zweige:
        try:
            schluessel = winreg.OpenKey(wurzel, pfad)
            anzahl = winreg.QueryInfoKey(schluessel)[0]
        except OSError:
            continue

        for nummer in range(anzahl):
            try:
                unter = winreg.OpenKey(schluessel, winreg.EnumKey(schluessel, nummer))
                anzeige = str(winreg.QueryValueEx(unter, "DisplayName")[0])
                if "tailscale" not in anzeige.lower():
                    continue
                ort = str(winreg.QueryValueEx(unter, "InstallLocation")[0]).strip()
            except OSError:
                continue
            if not ort:
                continue
            kandidat = Path(ort) / "tailscale.exe"
            if kandidat.is_file():
                yield kandidat


def _store_orte():
    """Der Ordner, in dem Windows Store-Programme ablegt."""

    lokal = os.environ.get("LOCALAPPDATA", "")
    if lokal:
        yield Path(lokal) / "Microsoft" / "WindowsApps" / "tailscale.exe"
    try:
        yield from Path("C:/Program Files/WindowsApps").glob("*Tailscale*/tailscale.exe")
    except OSError:
        return


def tailscale_finden() -> str | None:
    """Sucht das Tailscale-Programm auf allen bekannten Wegen."""

    gefunden = shutil.which("tailscale")
    if gefunden:
        return gefunden

    for kandidat in _aus_der_registry():
        return str(kandidat)

    for kandidat in (*BEKANNTE_ORTE, *_store_orte()):
        try:
            if kandidat.is_file():
                return str(kandidat)
        except OSError:
            continue
    return None


def fragen(programm: str, *argumente: str) -> tuple[int, str]:
    """Ruft Tailscale auf und fängt alles ab, was schiefgehen kann."""

    try:
        ergebnis = subprocess.run(
            [programm, *argumente],
            capture_output=True,
            text=True,
            timeout=FRIST,
            check=False,
            # Ohne dieses Fenster-Flag blitzt bei jedem Aufruf ein
            # schwarzes Fenster auf dem Schreibtisch auf. Der Orb soll
            # ruhig starten, nicht flackern.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as fehler:
        return 1, str(fehler)
    return ergebnis.returncode, (ergebnis.stdout + ergebnis.stderr).strip()


def geraetename(programm: str) -> str | None:
    """Der Name, unter dem dieser Rechner im eigenen Netz steht."""

    code, ausgabe = fragen(programm, "status", "--json")
    if code != 0:
        return None
    try:
        daten = json.loads(ausgabe)
    except json.JSONDecodeError:
        return None
    name = str((daten.get("Self") or {}).get("DNSName", "")).rstrip(".")
    return name or None


def zertifikate_moeglich(programm: str) -> bool | None:
    """Ob das eigene Netz HTTPS-Zertifikate ausstellen darf.

    Das ist ein Schalter in der Tailscale-Verwaltung, und er ist
    anfangs aus. Ist er aus, laesst sich die Weiterleitung zwar
    einrichten - aber der Browser bekommt beim Verbinden kein
    Zertifikat und **haengt**, ohne Fehlermeldung. Von aussen sieht das
    genauso aus wie ein abgestuerzter Server.

    ``None`` heisst: Es war nicht zu ermitteln.
    """

    code, ausgabe = fragen(programm, "status", "--json")
    if code != 0:
        return None
    try:
        daten = json.loads(ausgabe)
    except json.JSONDecodeError:
        return None
    if "CertDomains" not in daten:
        return None
    return bool(daten.get("CertDomains"))


def weiterleitung_steht(programm: str, port: int) -> bool:
    """Ob die Weiterleitung auf diesen Port bereits eingerichtet ist.

    ``tailscale serve --bg`` bleibt über Neustarts bestehen. Es jedes Mal
    neu zu setzen wäre unnötige Arbeit und würde bei jedem Start nach
    Administratorrechten fragen können.
    """

    for form in (("serve", "status"), ("serve", "status", "--json")):
        code, ausgabe = fragen(programm, *form)
        if code == 0 and str(port) in ausgabe:
            return True
    return False


#: Tailscale hat die Schreibweise dieses Befehls zwischen den Versionen
#: geändert. Statt eine zu erraten, werden sie der Reihe nach versucht.
SCHREIBWEISEN = (
    ("serve", "--bg", "--https=443", "http://127.0.0.1:{port}"),
    ("serve", "--bg", "http://127.0.0.1:{port}"),
    ("serve", "https:443", "/", "http://127.0.0.1:{port}"),
    ("serve", "https", "/", "http://127.0.0.1:{port}"),
)


def weiterleitung_einrichten(programm: str, port: int) -> tuple[bool, str]:
    """Richtet die verschlüsselte Weiterleitung ein."""

    letzte = ""
    for form in SCHREIBWEISEN:
        argumente = [teil.format(port=port) for teil in form]
        code, ausgabe = fragen(programm, *argumente)
        if code == 0:
            return True, "tailscale " + " ".join(argumente)
        letzte = ausgabe
    return False, letzte


def einrichten(port: int) -> dict[str, str]:
    """Stellt die Erreichbarkeit vom iPad her und sagt, was daraus wurde."""

    programm = tailscale_finden()
    if programm is None:
        return {"zustand": "kein_tailscale", "adresse": "", "hinweis": (
            "Tailscale ist nicht installiert. Ohne es bleibt der Orb auf "
            "das eigene WLAN beschränkt - und ohne verschlüsselte "
            "Verbindung gibt ein iPad das Mikrofon nicht frei."
        )}

    name = geraetename(programm)
    if name is None:
        return {"zustand": "nicht_angemeldet", "adresse": "", "hinweis": (
            "Tailscale ist da, aber nicht angemeldet. Einmal über das "
            "Symbol in der Taskleiste anmelden."
        )}

    adresse = f"https://{name}"

    if zertifikate_moeglich(programm) is False:
        return {"zustand": "kein_zertifikat", "adresse": adresse, "hinweis": (
            "Das eigene Tailscale-Netz darf keine HTTPS-Zertifikate "
            "ausstellen. Ohne sie haengt der Browser beim Verbinden, ohne "
            "Fehlermeldung. Einmalig einschalten unter "
            "login.tailscale.com/admin/dns bei 'HTTPS Certificates'."
        )}

    if weiterleitung_steht(programm, port):
        return {"zustand": "stand_schon", "adresse": adresse, "hinweis": ""}

    geklappt, meldung = weiterleitung_einrichten(programm, port)
    if geklappt:
        return {"zustand": "eingerichtet", "adresse": adresse, "hinweis": meldung}

    return {"zustand": "fehlgeschlagen", "adresse": adresse, "hinweis": (
        "Die Weiterleitung ließ sich nicht setzen. Meist fehlen dafür "
        "Administratorrechte - dann einmal FERNZUGANG.bat ausführen; "
        f"danach bleibt sie bestehen. Tailscale meldet: {meldung[:200]}"
    )}


def adresse_ablegen(port: int, bericht: dict[str, str], netzadresse: str = "") -> None:
    """Schreibt auf, wie das iPad hereinkommt."""

    from backend.utils.paths import get_project_root

    zeilen = ["So kommt das iPad an den Orb:", ""]

    if bericht.get("adresse") and bericht.get("zustand") in ("stand_schon", "eingerichtet"):
        zeilen += [
            f"    {bericht['adresse']}",
            "",
            "Diese Adresse in Safari eintippen. Sie ist verschlüsselt -",
            "nur damit gibt das iPad das Mikrofon frei, und nur damit",
            "lässt sich der Orb zum Startbildschirm hinzufügen.",
            "Sie gilt auch unterwegs, nicht nur zu Hause.",
        ]
    else:
        zeilen += [
            f"    (noch keine verschlüsselte Adresse: {bericht.get('zustand', 'unbekannt')})",
            "",
            bericht.get("hinweis", ""),
        ]

    if netzadresse:
        zeilen += [
            "",
            "Im eigenen WLAN geht auch, aber ohne Mikrofon:",
            f"    {netzadresse}:{port}",
        ]

    zeilen += [
        "",
        "Das Losungswort steht in der Datei .env unter AI_ORB_WEB_TOKEN.",
    ]

    try:
        ziel = get_project_root() / "logs" / "ipad-adresse.txt"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    except OSError as fehler:
        logger.debug("Adressdatei nicht geschrieben: %s", fehler)


def im_hintergrund_einrichten(port: int, netzadresse: str = "") -> None:
    """Richtet die Verbindung ein, ohne den Start aufzuhalten.

    Tailscale zu befragen dauert Sekundenbruchteile - aber eben nur, wenn
    alles in Ordnung ist. Ein hängender Aufruf darf den Orb nicht am
    Starten hindern, deshalb läuft das hier neben dem Start her.
    """

    try:
        from backend.config import get_config

        erlaubt = bool(get_config().section("backend").get("ipad_automatisch", True))
    except Exception:  # noqa: BLE001 - eine fehlende Einstellung ist kein Grund zu schweigen.
        erlaubt = True

    if not erlaubt:
        logger.info("Die iPad-Verbindung wird laut Konfiguration nicht selbst hergestellt.")
        return

    def arbeiten() -> None:
        try:
            bericht = einrichten(port)
        except Exception:  # noqa: BLE001 - der Start darf hieran nicht scheitern.
            logger.exception("Die iPad-Verbindung ließ sich nicht einrichten.")
            return

        zustand = bericht.get("zustand", "")
        if zustand == "stand_schon":
            logger.info("Vom iPad erreichbar unter %s", bericht["adresse"])
            logger.info(
                "Die Adresse muss mit https:// aufgerufen werden - ohne das "
                "landet Safari auf Port 80, wo nichts antwortet."
            )
        elif zustand == "eingerichtet":
            logger.info(
                "Verbindung zum iPad eingerichtet: %s (%s)",
                bericht["adresse"],
                bericht.get("hinweis", ""),
            )
        else:
            logger.warning("Keine iPad-Verbindung: %s", bericht.get("hinweis", zustand))

        adresse_ablegen(port, bericht, netzadresse)

    threading.Thread(target=arbeiten, name="ai-orb-ipad", daemon=True).start()
