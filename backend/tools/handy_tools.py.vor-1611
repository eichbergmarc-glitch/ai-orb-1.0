"""Das Handy bedienen: anrufen, Nachrichten, Kurzbefehle, Apps, Dokumente.

Seit 12.11.2026. Marc spricht ueber das iPhone mit Synapse und wollte, dass
sie dort anruft, SMS und WhatsApp schreibt, Apps bedient und erstellte
Dokumente direkt aufs Handy bringt.

Synapse laeuft auf dem PC; auf dem Handy ist sie eine Webseite. Eine
Webseite darf auf dem iPhone nicht selbst waehlen oder senden. Sie darf
aber Verweise anbieten, die das iPhone versteht:

* ``tel:+41...``                  -> Anruf (iPhone fragt "Anrufen?")
* ``sms:+41...&body=...``         -> Nachrichten-App mit fertigem Text
* ``https://wa.me/41...?text=...`` -> WhatsApp mit fertigem Text
* ``shortcuts://run-shortcut?...`` -> ein Kurzbefehl (steuert fast jede App)
* ``maps://?daddr=...`` usw.      -> Apps direkt oeffnen

Die Werkzeuge hier bereiten so einen Verweis vor ("Aktion"). Die Laufzeit
holt die Aktionen nach der Antwort ab und gibt sie an das Handy weiter;
dort erscheint ein grosser Knopf ("Peter anrufen"), ein Tipp genuegt.

Telefonnummern kommen aus den Google-Kontakten - ueber dieselbe Anmeldung
wie Gmail und Kalender.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

# --- Aktionen fuer das Handy ----------------------------------------------------

_aktionen: list[dict[str, str]] = []
_geraet_aktiv = False
_dokumente: dict[str, Path] = {}


def geraet_aktiv(an: bool) -> None:
    """Die Laufzeit meldet: Die laufende Frage kommt vom Handy."""

    global _geraet_aktiv
    _geraet_aktiv = bool(an)
    if an:
        _aktionen.clear()


def ist_geraet_aktiv() -> bool:
    return _geraet_aktiv


def aktion_vormerken(art: str, url: str, titel: str) -> None:
    _aktionen.append({"art": art, "url": url, "titel": titel})


def aktionen_abholen() -> list[dict[str, str]]:
    fertig = list(_aktionen)
    _aktionen.clear()
    return fertig


def dokument_freigeben(pfad: Path, titel: str = "") -> str:
    """Macht eine erzeugte Datei fuer das Handy abrufbar und merkt die Aktion vor.

    Freigegeben wird nur, was Synapse selbst erzeugt hat - ueber eine
    zufaellige Kennung, nie ueber einen Pfad.
    """

    kennung = secrets.token_urlsafe(12)
    _dokumente[kennung] = Path(pfad)
    if len(_dokumente) > 50:
        _dokumente.pop(next(iter(_dokumente)))
    aktion_vormerken(
        "dokument",
        "/dokument?id=" + kennung,
        (titel or Path(pfad).stem) + " öffnen",
    )
    return kennung


def dokument_pfad(kennung: str) -> Path | None:
    pfad = _dokumente.get(str(kennung or ""))
    return pfad if pfad is not None and pfad.is_file() else None


# --- Telefonnummern -------------------------------------------------------------


def nummer_normalisieren(nummer: str, *, land: str = "41") -> str:
    """'079 123 45 67' -> '+41791234567'. Leer, wenn es keine Nummer ist."""

    roh = re.sub(r"[^\d+]", "", str(nummer or ""))
    if roh.startswith("00"):
        roh = "+" + roh[2:]
    elif roh.startswith("0"):
        roh = f"+{land}" + roh[1:]
    elif roh and not roh.startswith("+") and len(roh) >= 10:
        roh = "+" + roh
    ziffern = re.sub(r"\D", "", roh)
    return roh if len(ziffern) >= 6 else ""


def _falten(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(z for z in text if not unicodedata.combining(z)).strip()


class KontaktFehler(RuntimeError):
    pass


class Kontaktbuch:
    """Liest die Google-Kontakte (nur lesen) und findet Nummern zu Namen."""

    _URL = (
        "https://people.googleapis.com/v1/people/me/connections"
        "?personFields=names,nicknames,phoneNumbers&pageSize=1000&sortOrder=LAST_MODIFIED_DESCENDING"
    )

    def __init__(
        self,
        auth: Any = None,
        *,
        abrufen: Callable[[str, str], dict[str, Any]] | None = None,
        haltbar_sekunden: float = 600.0,
    ) -> None:
        self._auth = auth
        self._abrufen = abrufen or self._http
        self._haltbar = haltbar_sekunden
        self._liste: list[dict[str, Any]] = []
        self._stand = 0.0

    @staticmethod
    def _http(url: str, token: str) -> dict[str, Any]:
        anfrage = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(anfrage, timeout=20) as antwort:
                return json.loads(antwort.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as fehler:
            text = fehler.read().decode("utf-8", errors="replace")[:300]
            if fehler.code == 403 and "SERVICE_DISABLED" in text:
                raise KontaktFehler(
                    "Die Google People API ist im Google-Cloud-Projekt noch nicht "
                    "eingeschaltet (console.cloud.google.com -> APIs -> 'People API' "
                    "aktivieren)."
                ) from fehler
            if fehler.code in (401, 403):
                raise KontaktFehler(
                    "Synapse darf die Kontakte noch nicht lesen. Sag: 'Melde mich bei "
                    "Gmail an' und erlaube dabei den Zugriff auf die Kontakte."
                ) from fehler
            raise KontaktFehler(f"Google-Kontakte antworteten mit {fehler.code}: {text}") from fehler
        except (urllib.error.URLError, TimeoutError, OSError) as fehler:
            raise KontaktFehler(f"Google-Kontakte nicht erreichbar: {fehler}") from fehler

    def _laden(self) -> list[dict[str, Any]]:
        if self._liste and time.monotonic() - self._stand < self._haltbar:
            return self._liste
        if self._auth is None:
            raise KontaktFehler("Google ist nicht eingerichtet.")
        try:
            token = self._auth.access_token()
        except Exception as fehler:  # noqa: BLE001
            raise KontaktFehler(
                "Synapse ist nicht bei Google angemeldet. Sag: 'Melde mich bei Gmail an'."
            ) from fehler
        liste: list[dict[str, Any]] = []
        url = self._URL
        for _ in range(10):
            daten = self._abrufen(url, token)
            for person in daten.get("connections") or []:
                namen = [n.get("displayName", "") for n in person.get("names") or []]
                namen += [n.get("value", "") for n in person.get("nicknames") or []]
                nummern = [
                    {"nummer": t.get("value", ""), "typ": t.get("formattedType") or t.get("type", "")}
                    for t in person.get("phoneNumbers") or []
                    if t.get("value")
                ]
                if namen and nummern:
                    liste.append({"name": namen[0], "namen": namen, "nummern": nummern})
            weiter = daten.get("nextPageToken")
            if not weiter:
                break
            url = self._URL + "&pageToken=" + urllib.parse.quote(weiter)
        self._liste, self._stand = liste, time.monotonic()
        logger.info("%d Kontakte mit Telefonnummer geladen.", len(liste))
        return liste

    def finden(self, wer: str) -> list[dict[str, Any]]:
        """Alle Kontakte, deren Name zu ``wer`` passt - der beste zuerst."""

        gesucht = _falten(wer)
        if not gesucht:
            return []
        woerter = gesucht.split()
        treffer: list[tuple[int, dict[str, Any]]] = []
        for kontakt in self._laden():
            beste = 0
            for name in kontakt["namen"]:
                n = _falten(name)
                if n == gesucht:
                    beste = max(beste, 3)
                elif all(re.search(r"\b" + re.escape(w), n) for w in woerter):
                    beste = max(beste, 2)
                elif gesucht in n:
                    beste = max(beste, 1)
            if beste:
                treffer.append((beste, kontakt))
        treffer.sort(key=lambda t: -t[0])
        if treffer and treffer[0][0] == 3:
            return [k for p, k in treffer if p == 3]
        return [k for _, k in treffer]


def _nummer_waehlen(kontakt: dict[str, Any], *, mobil: bool) -> str:
    nummern = kontakt["nummern"]
    if mobil:
        for eintrag in nummern:
            if re.search(r"mobil|mobile|handy|cell", str(eintrag.get("typ", "")), re.I):
                return eintrag["nummer"]
        for eintrag in nummern:
            if re.match(r"\s*(\+41|0041|0)\s*7[5-9]", eintrag["nummer"]):
                return eintrag["nummer"]
    return nummern[0]["nummer"]


def empfaenger_aufloesen(
    kontakte: Kontaktbuch | None, wer: str, *, mobil: bool = False
) -> tuple[str, str]:
    """Liefert (Name, Nummer im Format +41...) oder wirft KontaktFehler."""

    direkt = nummer_normalisieren(wer)
    if direkt and not re.search(r"[a-zA-ZäöüÄÖÜ]", wer):
        return wer.strip(), direkt
    if kontakte is None:
        raise KontaktFehler("Es ist kein Adressbuch verbunden. Nenne die Nummer direkt.")
    gefunden = kontakte.finden(wer)
    if not gefunden:
        raise KontaktFehler(f"Ich finde '{wer}' nicht in deinen Google-Kontakten.")
    if len(gefunden) > 1 and _falten(gefunden[0]["name"]) != _falten(gefunden[1]["name"]):
        namen = ", ".join(k["name"] for k in gefunden[:4])
        if not any(_falten(k["name"]) == _falten(wer) for k in gefunden):
            raise KontaktFehler(f"Mehrere passen: {namen}. Welchen meinst du?")
    kontakt = gefunden[0]
    nummer = nummer_normalisieren(_nummer_waehlen(kontakt, mobil=mobil))
    if not nummer:
        raise KontaktFehler(f"Bei {kontakt['name']} steht keine brauchbare Nummer.")
    return kontakt["name"], nummer


def _nur_handy() -> ToolResult | None:
    if _geraet_aktiv:
        return None
    return ToolResult.failure(
        "Das geht nur, wenn Marc gerade ueber das Handy mit dir spricht - dort "
        "erscheint dann der Knopf dafuer."
    )


# --- Werkzeuge ------------------------------------------------------------------


class AnrufenTool(Tool):
    name = "anrufen"
    description = (
        "Ruft jemanden ueber Marcs Handy an: Name aus den Google-Kontakten oder "
        "eine Nummer. Auf dem Handy erscheint ein Knopf 'Anrufen', Marc tippt "
        "einmal darauf. Benutze das bei 'ruf ... an'."
    )
    permission = "network"
    parameters = (ToolParameter("wen", "string", "Name des Kontakts oder Telefonnummer."),)

    def __init__(self, kontakte: Kontaktbuch | None = None) -> None:
        super().__init__()
        self._kontakte = kontakte

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sperre = _nur_handy()
        if sperre:
            return sperre
        try:
            name, nummer = empfaenger_aufloesen(self._kontakte, str(arguments.get("wen", "")))
        except KontaktFehler as fehler:
            return ToolResult.failure(str(fehler))
        aktion_vormerken("anruf", "tel:" + nummer, f"{name} anrufen")
        return ToolResult.success(
            f"Anruf an {name} ({nummer}) ist auf dem Handy bereit. Sag kurz: "
            "'Tipp auf Anrufen.'"
        )


class NachrichtSendenTool(Tool):
    name = "nachricht_senden"
    description = (
        "Schreibt eine SMS oder WhatsApp-Nachricht ueber Marcs Handy an einen "
        "Kontakt (Name aus den Google-Kontakten) oder eine Nummer. Der Text "
        "steht danach fertig im Nachrichtenfeld; Marc tippt auf Senden. Lies "
        "ihm den Text vorher kurz vor."
    )
    permission = "network"
    parameters = (
        ToolParameter("wen", "string", "Name des Kontakts oder Telefonnummer."),
        ToolParameter("text", "string", "Der Nachrichtentext."),
        ToolParameter(
            "kanal", "string", "whatsapp oder sms.", required=False,
            choices=("whatsapp", "sms"), default="whatsapp",
        ),
    )

    def __init__(self, kontakte: Kontaktbuch | None = None) -> None:
        super().__init__()
        self._kontakte = kontakte

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sperre = _nur_handy()
        if sperre:
            return sperre
        text = str(arguments.get("text", "") or "").strip()
        if not text:
            return ToolResult.failure("Der Nachrichtentext fehlt.")
        kanal = str(arguments.get("kanal", "whatsapp") or "whatsapp").lower()
        try:
            name, nummer = empfaenger_aufloesen(
                self._kontakte, str(arguments.get("wen", "")), mobil=True
            )
        except KontaktFehler as fehler:
            return ToolResult.failure(str(fehler))
        if kanal == "sms":
            url = f"sms:{nummer}&body=" + urllib.parse.quote(text)
            titel = f"SMS an {name} senden"
        else:
            url = f"https://wa.me/{nummer.lstrip('+')}?text=" + urllib.parse.quote(text)
            titel = f"WhatsApp an {name} senden"
        aktion_vormerken("nachricht", url, titel)
        return ToolResult.success(
            f"{titel.split(' senden')[0]} ist vorbereitet ({nummer}): \"{text}\". "
            "Marc tippt auf den Knopf und dann auf Senden."
        )


#: Apps, die das iPhone ueber eine Adresse oeffnet.
_APPS: dict[str, str] = {
    "whatsapp": "whatsapp://",
    "telefon": "tel:",
    "nachrichten": "sms:",
    "karten": "maps://",
    "apple maps": "maps://",
    "google maps": "comgooglemaps://",
    "mail": "message://",
    "kalender": "calshow://",
    "musik": "music://",
    "spotify": "spotify://",
    "youtube": "youtube://",
    "podcasts": "podcasts://",
    "kurzbefehle": "shortcuts://",
    "fotos": "photos-redirect://",
    "uhr": "clock-alarm://",
    "wecker": "clock-alarm://",
    "notizen": "mobilenotes://",
    "erinnerungen": "x-apple-reminderkit://",
    "sbb": "https://www.sbb.ch/de",
    "safari": "https://www.google.ch",
}


class AppOeffnenTool(Tool):
    name = "app_oeffnen"
    description = (
        "Oeffnet eine App auf Marcs iPhone (WhatsApp, Karten, Musik, Spotify, "
        "YouTube, Kalender, Notizen, Wecker, Kurzbefehle ...) oder startet in "
        "Karten die Navigation zu einem Ziel (app='karten', ziel='...')."
    )
    permission = "network"
    parameters = (
        ToolParameter("app", "string", "Name der App."),
        ToolParameter(
            "ziel", "string", "Optional: Navigationsziel oder Suchbegriff.",
            required=False, default="",
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sperre = _nur_handy()
        if sperre:
            return sperre
        app = _falten(arguments.get("app", ""))
        ziel = str(arguments.get("ziel", "") or "").strip()
        if ziel and app in ("karten", "apple maps", "maps", "navigation"):
            url = "maps://?daddr=" + urllib.parse.quote(ziel)
            titel = f"Route nach {ziel}"
        elif ziel and app == "google maps":
            url = "comgooglemaps://?daddr=" + urllib.parse.quote(ziel) + "&directionsmode=driving"
            titel = f"Route nach {ziel}"
        elif ziel and app == "youtube":
            url = "youtube://results?search_query=" + urllib.parse.quote(ziel)
            titel = f"YouTube: {ziel}"
        elif ziel and app == "spotify":
            url = "spotify:search:" + urllib.parse.quote(ziel)
            titel = f"Spotify: {ziel}"
        else:
            url = next((u for name, u in _APPS.items() if name == app), "")
            if not url:
                url = next((u for name, u in _APPS.items() if app and (app in name or name in app)), "")
            if not url:
                return ToolResult.failure(
                    f"Fuer '{arguments.get('app')}' kenne ich keinen direkten Weg. Marc kann "
                    "auf dem iPhone einen Kurzbefehl anlegen, der die App oeffnet - den "
                    "starte ich dann mit kurzbefehl_starten."
                )
            titel = f"{str(arguments.get('app')).strip().title()} öffnen"
        aktion_vormerken("app", url, titel)
        return ToolResult.success(f"'{titel}' ist auf dem Handy bereit - ein Tipp genuegt.")


class KurzbefehlStartenTool(Tool):
    name = "kurzbefehl_starten"
    description = (
        "Startet einen iPhone-Kurzbefehl (App 'Kurzbefehle') mit Namen, optional "
        "mit Text als Eingabe. Damit lassen sich fast alle Apps und das Smart "
        "Home steuern, z. B. 'Fokus an', 'Licht aus', 'Wecker 6 Uhr'."
    )
    permission = "network"
    parameters = (
        ToolParameter("name", "string", "Exakter Name des Kurzbefehls."),
        ToolParameter("eingabe", "string", "Optionaler Text als Eingabe.", required=False, default=""),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sperre = _nur_handy()
        if sperre:
            return sperre
        name = str(arguments.get("name", "") or "").strip()
        if not name:
            return ToolResult.failure("Der Name des Kurzbefehls fehlt.")
        url = "shortcuts://run-shortcut?name=" + urllib.parse.quote(name)
        eingabe = str(arguments.get("eingabe", "") or "").strip()
        if eingabe:
            url += "&input=text&text=" + urllib.parse.quote(eingabe)
        aktion_vormerken("kurzbefehl", url, f"Kurzbefehl '{name}' starten")
        return ToolResult.success(f"Kurzbefehl '{name}' ist auf dem Handy bereit.")


def build_handy_tools(kontakte: Kontaktbuch | None) -> list[Tool]:
    return [
        AnrufenTool(kontakte),
        NachrichtSendenTool(kontakte),
        AppOeffnenTool(),
        KurzbefehlStartenTool(),
    ]
