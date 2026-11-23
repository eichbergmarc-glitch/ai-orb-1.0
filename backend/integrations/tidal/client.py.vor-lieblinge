"""Der TIDAL-Client.

Spricht die offizielle TIDAL-API (``https://openapi.tidal.com/v2``) an. Sie
folgt dem JSON:API-Format: Antworten haben ``data`` (die Treffer als
``{id, type}``) und ``included`` (die eigentlichen Angaben zu Titeln und
Künstlern). Wie beim Kalender nur mit der stdlib und einem einschleusbaren
Transport, damit kein Test echte Playlists anlegt.

## Abspielen

Die öffentliche API liefert keine Musik aus - abgespielt wird in der
TIDAL-App. Der Orb sucht den Titel über die API und öffnet ihn dann mit
einem ``tidal://``-Link in der App (ersatzweise im Browser auf tidal.com).
Gesteuert (Pause, weiter, lauter) wird über die Medientasten von Windows,
auf die die TIDAL-App hört.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.integrations.tidal.oauth import TidalAuth, TidalAuthFehler
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

API_BASE = "https://openapi.tidal.com/v2"
_JSONAPI = "application/vnd.api+json"

#: Wie viele Titel TIDAL pro Anfrage zu einer Playlist hinzufügen lässt.
_HINZUFUEGEN_PRO_ANFRAGE = 20


class TidalFehler(RuntimeError):
    """Ein Fehler beim Zugriff auf TIDAL."""


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
        daten = json.dumps(body).encode("utf-8") if body is not None else None
        kopf = {"Authorization": f"Bearer {token}", "Accept": _JSONAPI}
        if daten is not None:
            kopf["Content-Type"] = _JSONAPI
        anfrage = urllib.request.Request(url, data=daten, headers=kopf, method=method)
        try:
            with urllib.request.urlopen(anfrage, timeout=30) as antwort:
                roh = antwort.read().decode("utf-8")
                return json.loads(roh) if roh.strip() else {}
        except urllib.error.HTTPError as fehler:
            text = fehler.read().decode("utf-8", errors="replace")[:400]
            if fehler.code == 401:
                raise TidalFehler(
                    "TIDAL hat die Anmeldung nicht akzeptiert. Sag „Melde mich "
                    f"bei TIDAL an“. ({text})"
                ) from fehler
            if fehler.code == 403:
                raise TidalFehler(
                    "TIDAL verweigert das. Meist fehlt in der Anwendung im "
                    "Entwicklerportal ein Bereich (Scope) oder die Anmeldung "
                    f"stammt von vor der Änderung. ({text})"
                ) from fehler
            if fehler.code == 404:
                raise TidalFehler("Das gibt es bei TIDAL nicht (mehr).") from fehler
            if fehler.code == 429:
                raise TidalFehler("TIDAL bremst gerade - zu viele Anfragen. Gleich noch einmal.") from fehler
            raise TidalFehler(f"TIDAL antwortete mit {fehler.code}: {text}") from fehler
        except (urllib.error.URLError, TimeoutError, OSError) as fehler:
            raise TidalFehler(f"TIDAL ist nicht erreichbar: {fehler}") from fehler


@dataclass(slots=True)
class Titel:
    id: str
    name: str = ""
    kuenstler: list[str] = field(default_factory=list)
    dauer: str = ""

    def zum_vorlesen(self) -> str:
        if self.kuenstler:
            return f"„{self.name}“ von {', '.join(self.kuenstler)}"
        return f"„{self.name}“"

    @property
    def link(self) -> str:
        return f"https://tidal.com/browse/track/{self.id}"

    @property
    def app_link(self) -> str:
        return f"tidal://track/{self.id}"


@dataclass(slots=True)
class Playlist:
    id: str
    name: str = ""
    anzahl: int | None = None

    @property
    def link(self) -> str:
        return f"https://tidal.com/browse/playlist/{self.id}"

    @property
    def app_link(self) -> str:
        return f"tidal://playlist/{self.id}"


def _dauer_lesen(iso: str) -> str:
    """``PT3M25S`` -> ``3:25``."""

    import re

    treffer = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not treffer:
        return ""
    h, m, s = (int(x or 0) for x in treffer.groups())
    m += h * 60
    return f"{m}:{s:02d}"


class TidalClient:
    """Suchen, Playlists anlegen und füllen."""

    def __init__(
        self,
        auth: TidalAuth,
        *,
        land: str = "CH",
        transport: Transport | None = None,
    ) -> None:
        self.auth = auth
        self.land = (land or "CH").upper()
        self._transport = transport or UrllibTransport()

    # --- intern ----------------------------------------------------------------

    def _url(self, pfad: str, params: dict[str, Any] | None = None) -> str:
        alle = {"countryCode": self.land, **(params or {})}
        return f"{API_BASE}{pfad}?{urllib.parse.urlencode(alle, safe=',[]')}"

    def _anfrage(
        self,
        method: str,
        pfad: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        benutzer: bool = False,
    ) -> dict[str, Any]:
        try:
            token = self.auth.user_token() if benutzer else self.auth.bester_token()
        except TidalAuthFehler as fehler:
            raise TidalFehler(str(fehler)) from fehler
        return self._transport.request(method, self._url(pfad, params), token=token, body=body)

    @staticmethod
    def _titel_aus(dokument: dict[str, Any], reihenfolge: list[str]) -> list[Titel]:
        """Setzt Titel und Künstlernamen aus ``data`` und ``included`` zusammen."""

        eintraege = list(dokument.get("included") or [])
        daten = dokument.get("data")
        if isinstance(daten, list):
            eintraege += [d for d in daten if d.get("attributes")]
        elif isinstance(daten, dict) and daten.get("attributes"):
            eintraege.append(daten)

        kuenstler = {
            e["id"]: str(e.get("attributes", {}).get("name", ""))
            for e in eintraege
            if e.get("type") == "artists"
        }
        titel: dict[str, Titel] = {}
        for e in eintraege:
            if e.get("type") != "tracks":
                continue
            attr = e.get("attributes") or {}
            name = str(attr.get("title", ""))
            if attr.get("version"):
                name += f" ({attr['version']})"
            namen = [
                kuenstler[r["id"]]
                for r in ((e.get("relationships") or {}).get("artists") or {}).get("data") or []
                if r.get("id") in kuenstler and kuenstler[r["id"]]
            ]
            titel[str(e["id"])] = Titel(
                id=str(e["id"]),
                name=name,
                kuenstler=namen,
                dauer=_dauer_lesen(str(attr.get("duration", ""))),
            )
        return [titel[i] for i in reihenfolge if i in titel]

    # --- Suche -----------------------------------------------------------------

    def suchen(self, text: str, *, anzahl: int = 5) -> list[Titel]:
        """Sucht Titel im Katalog."""

        begriff = (text or "").strip()
        if not begriff:
            return []
        antwort = self._anfrage(
            "GET",
            f"/searchResults/{urllib.parse.quote(begriff, safe='')}/relationships/tracks",
            params={"include": "tracks"},
        )
        ids = [str(d.get("id")) for d in (antwort.get("data") or []) if d.get("type") == "tracks"]
        ids = ids[: max(1, anzahl)]
        if not ids:
            return []
        return self.titel_holen(ids)

    def titel_holen(self, ids: list[str]) -> list[Titel]:
        """Holt Titel samt Künstlernamen."""

        if not ids:
            return []
        antwort = self._anfrage(
            "GET",
            "/tracks",
            params={"filter[id]": ",".join(ids), "include": "artists"},
        )
        titel = self._titel_aus(antwort, ids)
        # Wenn TIDAL Künstler nicht mitliefert, sind die Titel trotzdem brauchbar.
        bekannt = {t.id for t in titel}
        return titel + [Titel(id=i) for i in ids if i not in bekannt]

    # --- Playlists -------------------------------------------------------------

    def playlist_anlegen(self, name: str, *, beschreibung: str = "", oeffentlich: bool = False) -> Playlist:
        antwort = self._anfrage(
            "POST",
            "/playlists",
            body={
                "data": {
                    "type": "playlists",
                    "attributes": {
                        "name": name,
                        "description": beschreibung,
                        "accessType": "PUBLIC" if oeffentlich else "UNLISTED",
                    },
                }
            },
            benutzer=True,
        )
        daten = antwort.get("data") or {}
        if not daten.get("id"):
            raise TidalFehler("TIDAL hat die Playlist nicht bestätigt.")
        return Playlist(id=str(daten["id"]), name=str((daten.get("attributes") or {}).get("name", name)), anzahl=0)

    def titel_hinzufuegen(self, playlist_id: str, titel_ids: list[str]) -> int:
        """Hängt Titel an eine Playlist an. Gibt die Anzahl zurück."""

        ids = [str(i) for i in titel_ids if str(i).strip()]
        for start in range(0, len(ids), _HINZUFUEGEN_PRO_ANFRAGE):
            stueck = ids[start : start + _HINZUFUEGEN_PRO_ANFRAGE]
            self._anfrage(
                "POST",
                f"/playlists/{urllib.parse.quote(playlist_id, safe='')}/relationships/items",
                body={"data": [{"id": i, "type": "tracks"} for i in stueck]},
                benutzer=True,
            )
        return len(ids)

    def meine_playlists(self, *, anzahl: int = 50) -> list[Playlist]:
        """Die Playlists in der Sammlung des Benutzers."""

        antwort = self._anfrage(
            "GET",
            "/userCollectionPlaylists/me/relationships/items",
            params={"include": "items"},
            benutzer=True,
        )
        details = {
            str(e.get("id")): e
            for e in (antwort.get("included") or [])
            if e.get("type") == "playlists"
        }
        ergebnis: list[Playlist] = []
        for d in antwort.get("data") or []:
            if d.get("type") != "playlists":
                continue
            attr = (details.get(str(d.get("id"))) or {}).get("attributes") or {}
            ergebnis.append(
                Playlist(
                    id=str(d.get("id")),
                    name=str(attr.get("name", "")),
                    anzahl=attr.get("numberOfItems"),
                )
            )
        return ergebnis[:anzahl]

    def playlist_finden(self, name: str) -> tuple[Playlist | None, list[Playlist]]:
        """Sucht eine eigene Playlist nach Namen. Mehrdeutig -> ``None`` + Liste."""

        klein = (name or "").strip().lower()
        alle = self.meine_playlists(anzahl=200)
        genau = [p for p in alle if p.name.lower() == klein]
        if len(genau) == 1:
            return genau[0], genau
        teil = [p for p in alle if klein and klein in p.name.lower()]
        if len(teil) == 1:
            return teil[0], teil
        return None, (genau or teil)
