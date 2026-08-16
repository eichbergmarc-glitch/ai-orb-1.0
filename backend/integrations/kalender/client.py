"""Der Kalender-Client.

Spricht die Google-Calendar-REST-API an: ansehen, suchen, anlegen, ändern,
löschen. Mit der stdlib (``urllib``) und ohne die Google-Bibliothek -
dieselbe Beschränkung wie im ganzen Projekt, und die Calendar-API ist
gewöhnliches REST über HTTPS.

## Der einschleusbare Transport

Alle Netzaufrufe laufen durch ``self._transport``. Im Betrieb ist das eine
dünne ``urllib``-Hülle, im Test eine Attrappe. Das ist hier nicht optional:
Ein Kalender-Client, den man nur am echten Kalender prüfen kann, wird beim
Prüfen des Löschens einen echten Termin löschen. Genau das darf kein Test
tun.

## Was bewusst nicht hier steht

Die Rückfrage vor dem Löschen. Sie gehört zur Sicherheitsschicht und zum
Werkzeug, nicht in den Client - zwei Schranken an zwei Stellen laufen mit
der Zeit auseinander, und dann glaubt jede, die andere prüfe schon.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from backend.integrations.gmail.oauth import GmailAuth, kalender_bereich_enthalten
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

_API_BASE = "https://www.googleapis.com/calendar/v3"

_NEU_ANMELDEN = (
    "Der Kalender ist noch nicht freigegeben. Das Google-Konto ist zwar "
    "angemeldet, aber die Anmeldung stammt aus der Zeit vor der "
    "Kalenderfunktion. Sag einmal „Melde mich bei Gmail an“ - danach gilt "
    "die Freigabe für Post und Kalender zusammen."
)


class KalenderFehler(RuntimeError):
    """Ein Fehler beim Kalenderzugriff."""


class Transport(Protocol):
    def request(
        self, method: str, url: str, *, token: str, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        ...


class UrllibTransport:
    """Der echte Transport über ``urllib``."""

    def request(
        self, method: str, url: str, *, token: str, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        import json
        import urllib.error
        import urllib.request

        daten = json.dumps(body).encode("utf-8") if body is not None else None
        kopfzeilen = {"Authorization": f"Bearer {token}"}
        if daten is not None:
            kopfzeilen["Content-Type"] = "application/json"

        anfrage = urllib.request.Request(url, data=daten, headers=kopfzeilen, method=method)
        try:
            with urllib.request.urlopen(anfrage, timeout=30) as antwort:
                roh = antwort.read().decode("utf-8")
                return json.loads(roh) if roh.strip() else {}
        except urllib.error.HTTPError as fehler:
            text = fehler.read().decode("utf-8", errors="replace")[:400]
            if fehler.code in (401, 403) and "calendar" not in text.lower():
                raise KalenderFehler(_NEU_ANMELDEN) from fehler
            if fehler.code == 403:
                raise KalenderFehler(f"Google verweigert den Zugriff: {text}") from fehler
            if fehler.code == 404:
                raise KalenderFehler("Diesen Termin gibt es nicht (mehr).") from fehler
            raise KalenderFehler(f"Der Kalender antwortete mit {fehler.code}: {text}") from fehler
        except (urllib.error.URLError, TimeoutError, OSError) as fehler:
            raise KalenderFehler(f"Der Kalender ist nicht erreichbar: {fehler}") from fehler


@dataclass(slots=True)
class Termin:
    """Ein Termin in der Form, die der Orb braucht."""

    id: str = ""
    titel: str = ""
    beginn: datetime | None = None
    ende: datetime | None = None
    ganztags: bool = False
    ort: str = ""
    beschreibung: str = ""
    teilnehmer: list[str] = field(default_factory=list)
    link: str = ""
    kalender: str = "primary"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "titel": self.titel,
            "beginn": self.beginn.isoformat() if self.beginn else "",
            "ende": self.ende.isoformat() if self.ende else "",
            "ganztags": self.ganztags,
            "ort": self.ort,
            "beschreibung": self.beschreibung,
            "teilnehmer": list(self.teilnehmer),
            "link": self.link,
        }

    def zum_vorlesen(self, *, jetzt: datetime | None = None) -> str:
        """Der Termin als ein Satz, den man hören kann.

        Kein Datumsformat mit Bindestrichen, keine Sekunden: Wer einen
        Termin vorgelesen bekommt, will "morgen um halb drei" hören und
        nicht "2026-09-15T14:30:00+02:00".
        """

        if self.beginn is None:
            return self.titel or "Ein Termin ohne Zeit"

        jetzt = (jetzt or datetime.now()).astimezone(self.beginn.tzinfo)
        tage = (self.beginn.date() - jetzt.date()).days
        if tage == 0:
            wann = "heute"
        elif tage == 1:
            wann = "morgen"
        elif tage == -1:
            wann = "gestern"
        elif 0 < tage <= 6:
            wann = f"am {_WOCHENTAG[self.beginn.weekday()]}"
        else:
            wann = f"am {self.beginn.day}. {_MONAT[self.beginn.month - 1]}"

        if self.ganztags:
            zeit = "den ganzen Tag"
        else:
            minute = self.beginn.minute
            zeit = f"um {self.beginn.hour} Uhr" + (f" {minute}" if minute else "")

        satz = f"{self.titel or 'Termin'} {wann} {zeit}"
        if self.ort:
            satz += f", {self.ort}"
        return satz + "."


_WOCHENTAG = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
_MONAT = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def _zeit_lesen(eintrag: dict[str, Any]) -> tuple[datetime | None, bool]:
    """Liest ``start``/``end`` aus der API-Antwort."""

    if not isinstance(eintrag, dict):
        return None, False
    if eintrag.get("dateTime"):
        try:
            return datetime.fromisoformat(str(eintrag["dateTime"]).replace("Z", "+00:00")), False
        except ValueError:
            return None, False
    if eintrag.get("date"):
        try:
            tag = datetime.fromisoformat(str(eintrag["date"]))
            return tag.astimezone() if tag.tzinfo else tag, True
        except ValueError:
            return None, True
    return None, False


def _termin_lesen(daten: dict[str, Any], kalender: str = "primary") -> Termin:
    beginn, ganztags = _zeit_lesen(daten.get("start", {}))
    ende, _ = _zeit_lesen(daten.get("end", {}))
    return Termin(
        id=str(daten.get("id", "")),
        titel=str(daten.get("summary", "") or "Ohne Titel"),
        beginn=beginn,
        ende=ende,
        ganztags=ganztags,
        ort=str(daten.get("location", "") or ""),
        beschreibung=str(daten.get("description", "") or ""),
        teilnehmer=[
            str(t.get("email", ""))
            for t in (daten.get("attendees") or [])
            if isinstance(t, dict) and t.get("email")
        ],
        link=str(daten.get("htmlLink", "") or ""),
        kalender=kalender,
    )


def _zeitfeld(wann: datetime, ganztags: bool) -> dict[str, str]:
    if ganztags:
        return {"date": wann.date().isoformat()}
    if wann.tzinfo is None:
        wann = wann.astimezone()
    return {"dateTime": wann.isoformat()}


class KalenderClient:
    """Liest und ändert Termine über die Google-Calendar-API."""

    def __init__(
        self,
        auth: GmailAuth,
        *,
        transport: Transport | None = None,
        kalender: str = "primary",
    ) -> None:
        self._auth = auth
        self._transport = transport or UrllibTransport()
        self._kalender = kalender or "primary"

    # --- Zustand --------------------------------------------------------------

    @property
    def ist_bereit(self) -> bool:
        """Ob angemeldet UND der Kalender freigegeben ist."""

        return self._auth.is_authenticated and kalender_bereich_enthalten(
            self._auth.granted_scopes()
        )

    def zustand(self) -> dict[str, Any]:
        angemeldet = self._auth.is_authenticated
        return {
            "eingerichtet": self._auth.config.is_configured,
            "angemeldet": angemeldet,
            "kalender_freigegeben": kalender_bereich_enthalten(self._auth.granted_scopes()),
            "kalender": self._kalender,
        }

    def _pruefen(self) -> None:
        if not self._auth.config.is_configured:
            raise KalenderFehler(
                "Der Google-Zugang ist nicht eingerichtet. Es fehlt "
                "GMAIL_CLIENT_ID in der .env - siehe docs/KALENDER.md."
            )
        if not self._auth.is_authenticated:
            raise KalenderFehler(
                "Es ist kein Google-Konto angemeldet. Sag „Melde mich bei "
                "Gmail an“, um die einmalige Anmeldung zu starten."
            )
        if not kalender_bereich_enthalten(self._auth.granted_scopes()):
            raise KalenderFehler(_NEU_ANMELDEN)

    def _rufen(
        self, methode: str, pfad: str, koerper: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._pruefen()
        token = self._auth.access_token()
        adresse = pfad if pfad.startswith("http") else f"{_API_BASE}{pfad}"
        return self._transport.request(methode, adresse, token=token, body=koerper)

    def _weg(self, rest: str = "") -> str:
        return f"/calendars/{urllib.parse.quote(self._kalender, safe='')}/events{rest}"

    # --- Ansehen --------------------------------------------------------------

    def termine(
        self,
        *,
        von: datetime | None = None,
        bis: datetime | None = None,
        suche: str = "",
        limit: int = 20,
    ) -> list[Termin]:
        """Listet Termine in einem Zeitraum, nach Beginn geordnet."""

        von = von or datetime.now().astimezone()
        bis = bis or (von + timedelta(days=7))
        parameter = {
            "timeMin": von.astimezone().isoformat(),
            "timeMax": bis.astimezone().isoformat(),
            # Wiederkehrende Termine als einzelne Vorkommen: Sonst kommt die
            # Serie als ein Eintrag zurueck, und "was steht morgen an" waere
            # bei jedem woechentlichen Termin falsch.
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(max(1, min(limit, 100))),
        }
        if suche.strip():
            parameter["q"] = suche.strip()

        antwort = self._rufen("GET", self._weg(f"?{urllib.parse.urlencode(parameter)}"))
        return [
            _termin_lesen(eintrag, self._kalender)
            for eintrag in (antwort.get("items") or [])
            if str(eintrag.get("status", "")) != "cancelled"
        ][:limit]

    def naechste(self, *, anzahl: int = 5, tage: int = 14) -> list[Termin]:
        jetzt = datetime.now().astimezone()
        return self.termine(von=jetzt, bis=jetzt + timedelta(days=tage), limit=anzahl)

    def holen(self, termin_id: str) -> Termin:
        pfad = self._weg(f"/{urllib.parse.quote(termin_id, safe='')}")
        return _termin_lesen(self._rufen("GET", pfad), self._kalender)

    # --- Ändern ---------------------------------------------------------------

    def anlegen(
        self,
        *,
        titel: str,
        beginn: datetime,
        ende: datetime | None = None,
        ganztags: bool = False,
        ort: str = "",
        beschreibung: str = "",
        teilnehmer: list[str] | None = None,
        erinnerung_minuten: int | None = None,
    ) -> Termin:
        """Legt einen Termin an."""

        if not titel.strip():
            raise KalenderFehler("Ein Termin ohne Titel ist keiner.")
        if ende is None:
            ende = beginn + timedelta(days=1) if ganztags else beginn + timedelta(hours=1)
        if ende <= beginn:
            raise KalenderFehler("Das Ende liegt vor dem Beginn.")

        koerper: dict[str, Any] = {
            "summary": titel.strip(),
            "start": _zeitfeld(beginn, ganztags),
            "end": _zeitfeld(ende, ganztags),
        }
        if ort.strip():
            koerper["location"] = ort.strip()
        if beschreibung.strip():
            koerper["description"] = beschreibung.strip()
        if teilnehmer:
            koerper["attendees"] = [{"email": t} for t in teilnehmer if "@" in t]
        if erinnerung_minuten is not None:
            koerper["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": max(0, int(erinnerung_minuten))}],
            }

        angelegt = _termin_lesen(self._rufen("POST", self._weg(), koerper), self._kalender)
        logger.info("Termin angelegt: %s (%s).", angelegt.titel, angelegt.id)
        return angelegt

    def aendern(
        self,
        termin_id: str,
        *,
        titel: str | None = None,
        beginn: datetime | None = None,
        ende: datetime | None = None,
        ganztags: bool | None = None,
        ort: str | None = None,
        beschreibung: str | None = None,
    ) -> Termin:
        """Ändert einzelne Felder eines Termins.

        Es wird PATCH benutzt und nicht PUT: Bei PUT müsste der ganze Termin
        mitgeschickt werden, und alles, was nicht mitkommt, wäre danach weg -
        Teilnehmer, Erinnerungen, Videokonferenz. Wer die Uhrzeit verschiebt,
        will nicht die Gäste verlieren.
        """

        if not termin_id.strip():
            raise KalenderFehler("Es fehlt die Kennung des Termins.")

        vorher = self.holen(termin_id)
        ganztags_neu = vorher.ganztags if ganztags is None else bool(ganztags)

        koerper: dict[str, Any] = {}
        if titel is not None:
            koerper["summary"] = titel.strip()
        if ort is not None:
            koerper["location"] = ort.strip()
        if beschreibung is not None:
            koerper["description"] = beschreibung.strip()

        if beginn is not None:
            koerper["start"] = _zeitfeld(beginn, ganztags_neu)
            if ende is None:
                # Die Dauer beibehalten: Wer "verschieb das auf 15 Uhr" sagt,
                # meint nicht "und mach eine Stunde daraus".
                dauer = timedelta(hours=1)
                if vorher.beginn and vorher.ende:
                    dauer = vorher.ende - vorher.beginn
                koerper["end"] = _zeitfeld(beginn + dauer, ganztags_neu)
        if ende is not None:
            koerper["end"] = _zeitfeld(ende, ganztags_neu)

        if not koerper:
            raise KalenderFehler("Es wurde nicht gesagt, was geändert werden soll.")

        pfad = self._weg(f"/{urllib.parse.quote(termin_id, safe='')}")
        geaendert = _termin_lesen(self._rufen("PATCH", pfad, koerper), self._kalender)
        logger.info("Termin geändert: %s (%s).", geaendert.titel, geaendert.id)
        return geaendert

    def loeschen(self, termin_id: str) -> None:
        """Löscht einen Termin.

        Ohne Rückfrage - die holt das Werkzeug ein. Hier steht sie nicht,
        damit es nur EINE Stelle gibt, an der über das Löschen entschieden
        wird.
        """

        if not termin_id.strip():
            raise KalenderFehler("Es fehlt die Kennung des Termins.")
        self._rufen("DELETE", self._weg(f"/{urllib.parse.quote(termin_id, safe='')}"))
        logger.info("Termin gelöscht: %s.", termin_id)
