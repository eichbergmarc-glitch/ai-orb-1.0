"""Die Werkzeuge für TIDAL.

Sieben Stück: anmelden, suchen, abspielen, steuern, Playlists ansehen,
Playlist erstellen, Playlist ergänzen.

## Warum Songs als Text und nicht als Kennungen

Wie beim Kalender: Kein Mensch sagt "Titel 77646123". Das Modell gibt die
Songs so an, wie der Benutzer sie nennt ("Bohemian Rhapsody von Queen"),
und das Werkzeug sucht selbst den passenden Titel. Was es nicht findet,
sagt es ausdrücklich - eine Playlist, in der stillschweigend die Hälfte
fehlt, ist schlimmer als eine Fehlermeldung.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from backend.integrations.tidal.client import TidalClient, TidalFehler, Titel
from backend.integrations.tidal.oauth import TidalAuthFehler
from backend.integrations.tidal.player import MEDIENTASTEN, in_app_oeffnen, taste_druecken
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

_PERMISSION = "music"

#: Höchstens so viele Songs pro Playlist-Auftrag - schützt vor endlosen
#: Suchschleifen, wenn das Modell eine riesige Liste erfindet.
_MAX_SONGS = 100


def _songs_lesen(text: str) -> list[str]:
    """Zerlegt "A; B; C" oder eine Liste mit Zeilen in einzelne Songs."""

    teile = re.split(r"[;\n]+", text or "")
    songs = []
    for teil in teile:
        sauber = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", teil).strip()
        if sauber:
            songs.append(sauber)
    return songs[:_MAX_SONGS]


def _suchbegriff(song: str) -> str:
    """'Hello von Adele' / 'Adele - Hello' -> 'Hello Adele' (besser für die Suche)."""

    return re.sub(r"\s+(?:von|by)\s+|\s+[-–]\s+", " ", song).strip()


#: Seiten der TIDAL-App, die ohne Entwickler-Anmeldung erreichbar sind:
#: Die App oeffnet tidal://<pfad> wie den gleichnamigen Pfad des Webplayers.
APP_SEITEN: dict[str, str] = {
    "lieblingssongs": "my-collection/tracks",
    "playlists": "my-collection/playlists",
    "alben": "my-collection/albums",
    "kuenstler": "my-collection/artists",
    "mixes": "my-collection/mixes",
    "startseite": "home",
}
APP_SEITEN_NAMEN: dict[str, str] = {
    "lieblingssongs": "deine gelikten Songs",
    "playlists": "deine Playlists",
    "alben": "deine Alben",
    "kuenstler": "deine Kuenstler",
    "mixes": "deine Mixes",
    "startseite": "die TIDAL-Startseite",
}


class _TidalWerkzeug(Tool):
    permission = _PERMISSION

    def __init__(self, dienst: TidalDienst) -> None:
        self._dienst = dienst

    @property
    def _client(self) -> TidalClient:
        return self._dienst.client

    def _fehler(self, fehler: Exception, *, app_seite: str = "") -> ToolResult:
        # 22.11.2026: Marc nutzt TIDAL als App und will keine Entwickler-
        # Anmeldung. Fehlt sie, oeffnet das Werkzeug die passende Seite
        # direkt in der TIDAL-App (dort ist Marc angemeldet).
        if app_seite and "nicht angemeldet" in str(fehler):
            wo = self._dienst.app_seite_oeffnen(app_seite)
            ort = "in der TIDAL-App" if wo == "app" else "im TIDAL-Webplayer"
            return ToolResult.success(
                f"Ich habe {APP_SEITEN_NAMEN.get(app_seite, 'die Seite')} {ort} geoeffnet "
                "und starte die Wiedergabe. (Eigene Playlists "
                "anlegen kann ich ohne TIDAL-Entwicklerzugang nicht - das geht in der App.)",
                wo=wo,
            )
        return ToolResult.failure(str(fehler))


class TidalAnmeldenTool(_TidalWerkzeug):
    name = "tidal_anmelden"
    description = (
        "Startet die einmalige Anmeldung bei TIDAL im Browser. Benutze das bei "
        "'melde mich bei TIDAL an' oder wenn ein TIDAL-Werkzeug meldet, dass "
        "keine Anmeldung besteht. Nötig für Playlists; Suchen und Abspielen "
        "gehen auch ohne."
    )
    parameters = ()

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        bericht = self._dienst.anmeldung_starten()
        if not bericht.get("ok"):
            return ToolResult.failure(str(bericht.get("fehler")))
        return ToolResult.success(
            "Ich habe die TIDAL-Anmeldung im Browser geöffnet. Melde dich dort "
            "an und erteile die Erlaubnis - danach kann ich Playlists anlegen.",
            url=bericht.get("url", ""),
        )


class MusikSuchenTool(_TidalWerkzeug):
    name = "musik_suchen"
    description = (
        "Sucht Songs bei TIDAL und listet die Treffer auf, ohne etwas "
        "abzuspielen. 'suche' ist Titel und/oder Künstler."
    )
    parameters = (
        ToolParameter("suche", "string", "Titel und/oder Künstler, z.B. 'Hello Adele'."),
        ToolParameter("anzahl", "integer", "Wie viele Treffer.", required=False, default=5),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            treffer = await asyncio.to_thread(
                self._client.suchen, arguments["suche"], anzahl=int(arguments.get("anzahl") or 5)
            )
        except (TidalFehler, TidalAuthFehler) as fehler:
            return self._fehler(fehler)
        if not treffer:
            return ToolResult.success(f"Zu '{arguments['suche']}' habe ich bei TIDAL nichts gefunden.")
        zeilen = [f"{i}. {t.zum_vorlesen()}" for i, t in enumerate(treffer, 1)]
        return ToolResult.success("\n".join(zeilen), titel=[t.id for t in treffer])


class MusikAbspielenTool(_TidalWerkzeug):
    name = "musik_abspielen"
    description = (
        "Spielt Musik über TIDAL ab: sucht einen Song (oder eine eigene "
        "Playlist) und startet ihn in der TIDAL-App. Benutze das bei 'spiel "
        "...', 'ich will ... hören', 'mach Musik an'. 'art' ist 'song' oder "
        "'playlist'."
    )
    parameters = (
        ToolParameter("suche", "string", "Songtitel und/oder Künstler bzw. Name der Playlist."),
        ToolParameter(
            "art", "string", "Was gespielt werden soll.",
            required=False, default="song", choices=("song", "playlist"),
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        suche = str(arguments.get("suche", "")).strip()
        art = str(arguments.get("art") or "song")
        try:
            if art == "playlist":
                playlist, kandidaten = await asyncio.to_thread(self._client.playlist_finden, suche)
                if playlist is None:
                    if kandidaten:
                        namen = ", ".join(p.name for p in kandidaten[:8])
                        return ToolResult.failure(f"Mehrere Playlists passen: {namen}. Welche meinst du?")
                    return ToolResult.failure(f"Eine Playlist '{suche}' habe ich in deiner Sammlung nicht gefunden.")
                wo = self._dienst.oeffnen(playlist.app_link, playlist.link)
                return ToolResult.success(f"Ich spiele deine Playlist „{playlist.name}“ ab.", wo=wo)

            treffer = await asyncio.to_thread(self._client.suchen, _suchbegriff(suche), anzahl=1)
        except (TidalFehler, TidalAuthFehler) as fehler:
            return self._fehler(fehler, app_seite="playlists" if art == "playlist" else "")
        if not treffer:
            return ToolResult.failure(f"Zu '{suche}' habe ich bei TIDAL nichts gefunden.")
        titel = treffer[0]
        wo = self._dienst.oeffnen(titel.app_link, titel.link)
        ort = "in der TIDAL-App" if wo == "app" else "im Browser"
        return ToolResult.success(f"Ich spiele {titel.zum_vorlesen()} {ort} ab.", titel=titel.id, wo=wo)


class MusikSteuernTool(_TidalWerkzeug):
    name = "musik_steuern"
    description = (
        "Steuert die laufende Musik über die Medientasten: pause, weiter, "
        "naechster, vorheriger, stopp, lauter, leiser, stumm. Benutze das bei "
        "'Pause', 'nächster Song', 'lauter' usw."
    )
    parameters = (
        ToolParameter(
            "aktion", "string", "Was getan werden soll.",
            choices=tuple(k for k in MEDIENTASTEN if k != "abspielen"),
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        aktion = str(arguments.get("aktion", ""))
        # Lautstärke in spürbaren Schritten - ein einzelner Tastendruck sind
        # unter Windows nur zwei Prozent.
        wiederholen = 5 if aktion in ("lauter", "leiser") else 1
        if not taste_druecken(aktion, wiederholen=wiederholen):
            return ToolResult.failure("Die Medientasten lassen sich nur unter Windows drücken.")
        return ToolResult.success("Erledigt.", aktion=aktion)


class PlaylistsAnsehenTool(_TidalWerkzeug):
    name = "playlists_ansehen"
    description = "Listet die eigenen TIDAL-Playlists des Benutzers auf."
    parameters = ()

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            playlists = await asyncio.to_thread(self._client.meine_playlists)
        except (TidalFehler, TidalAuthFehler) as fehler:
            return self._fehler(fehler, app_seite="playlists")
        if not playlists:
            return ToolResult.success("In deiner TIDAL-Sammlung sind noch keine Playlists.")
        zeilen = [
            f"{i}. {p.name}" + (f" ({p.anzahl} Titel)" if p.anzahl is not None else "")
            for i, p in enumerate(playlists, 1)
        ]
        return ToolResult.success("\n".join(zeilen))


class _PlaylistFuellen(_TidalWerkzeug):
    async def _titel_suchen(self, songs: list[str]) -> tuple[list[Titel], list[str]]:
        gefunden: list[Titel] = []
        fehlend: list[str] = []
        for song in songs:
            try:
                treffer = await asyncio.to_thread(self._client.suchen, _suchbegriff(song), anzahl=1)
            except TidalFehler as fehler:
                logger.warning("TIDAL-Suche nach %r fehlgeschlagen: %s", song, fehler)
                treffer = []
            if treffer:
                gefunden.append(treffer[0])
            else:
                fehlend.append(song)
        return gefunden, fehlend

    @staticmethod
    def _bericht(kopf: str, gefunden: list[Titel], fehlend: list[str]) -> str:
        text = kopf
        if gefunden:
            text += "\n" + "\n".join(f"- {t.zum_vorlesen()}" for t in gefunden)
        if fehlend:
            text += "\nNicht gefunden: " + "; ".join(fehlend)
        return text


class PlaylistErstellenTool(_PlaylistFuellen):
    name = "playlist_erstellen"
    description = (
        "Legt in TIDAL eine neue Playlist an und füllt sie mit Songs. 'songs' "
        "ist eine Liste, getrennt durch Semikolon, z.B. 'Hello von Adele; "
        "Yellow von Coldplay'. Wenn der Benutzer nur eine Stimmung oder ein "
        "Thema nennt, wähle selbst passende, real existierende Songs aus."
    )
    parameters = (
        ToolParameter("name", "string", "Name der Playlist."),
        ToolParameter("songs", "string", "Songs, getrennt durch ';' - jeweils Titel und Künstler."),
        ToolParameter("beschreibung", "string", "Optionale Beschreibung.", required=False, default=""),
        ToolParameter("abspielen", "boolean", "Danach gleich abspielen.", required=False, default=False),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        songs = _songs_lesen(str(arguments.get("songs", "")))
        if not name:
            return ToolResult.failure("Die Playlist braucht einen Namen.")
        try:
            # Zuerst prüfen, ob die Anmeldung steht - sonst sucht der Orb
            # zwanzig Songs, nur um dann am Anlegen zu scheitern.
            self._dienst.auth.user_token()
            gefunden, fehlend = await self._titel_suchen(songs)
            playlist = await asyncio.to_thread(
                self._client.playlist_anlegen, name, beschreibung=str(arguments.get("beschreibung") or "")
            )
            if gefunden:
                await asyncio.to_thread(self._client.titel_hinzufuegen, playlist.id, [t.id for t in gefunden])
        except (TidalFehler, TidalAuthFehler) as fehler:
            return self._fehler(fehler, app_seite="playlists")

        if arguments.get("abspielen"):
            self._dienst.oeffnen(playlist.app_link, playlist.link)
        kopf = f"Die Playlist „{playlist.name}“ ist angelegt, mit {len(gefunden)} Titeln."
        return ToolResult.success(self._bericht(kopf, gefunden, fehlend), playlist=playlist.id, link=playlist.link)


class PlaylistErgaenzenTool(_PlaylistFuellen):
    name = "playlist_ergaenzen"
    description = (
        "Fügt Songs zu einer bestehenden eigenen TIDAL-Playlist hinzu. "
        "'playlist' ist ihr Name, 'songs' durch Semikolon getrennt."
    )
    parameters = (
        ToolParameter("playlist", "string", "Name der Playlist."),
        ToolParameter("songs", "string", "Songs, getrennt durch ';'."),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        songs = _songs_lesen(str(arguments.get("songs", "")))
        try:
            playlist, kandidaten = await asyncio.to_thread(
                self._client.playlist_finden, str(arguments.get("playlist", ""))
            )
            if playlist is None:
                if kandidaten:
                    namen = ", ".join(p.name for p in kandidaten[:8])
                    return ToolResult.failure(f"Mehrere Playlists passen: {namen}. Welche meinst du?")
                return ToolResult.failure("Diese Playlist habe ich in deiner Sammlung nicht gefunden.")
            gefunden, fehlend = await self._titel_suchen(songs)
            if gefunden:
                await asyncio.to_thread(self._client.titel_hinzufuegen, playlist.id, [t.id for t in gefunden])
        except (TidalFehler, TidalAuthFehler) as fehler:
            return self._fehler(fehler, app_seite="playlists")
        kopf = f"Zu „{playlist.name}“ habe ich {len(gefunden)} Titel hinzugefügt."
        return ToolResult.success(self._bericht(kopf, gefunden, fehlend), playlist=playlist.id)


class TidalDienst:
    """Hält Anmeldung, Client und Abspieleinstellungen zusammen."""

    def __init__(self, client: TidalClient, *, danach_abspielen: bool = True, warte_sekunden: float = 4.0, oeffner: Any = None) -> None:
        self.client = client
        self.auth = client.auth
        self.danach_abspielen = danach_abspielen
        self.warte_sekunden = warte_sekunden
        self._oeffner = oeffner or in_app_oeffnen

    def app_seite_oeffnen(self, seite: str, *, abspielen: bool | None = None) -> str:
        if abspielen is None:
            abspielen = seite in ("lieblingssongs", "mixes")
        pfad = APP_SEITEN.get(seite, seite)
        return self._oeffner(f"tidal://{pfad}", f"https://listen.tidal.com/{pfad}",
                             danach_abspielen=abspielen, warte_sekunden=self.warte_sekunden)

    def oeffnen(self, app_link: str, web_link: str) -> str:
        return self._oeffner(
            app_link, web_link,
            danach_abspielen=self.danach_abspielen,
            warte_sekunden=self.warte_sekunden,
        )

    def anmeldung_starten(self) -> dict[str, Any]:
        if not self.auth.is_configured:
            return {
                "ok": False,
                "fehler": (
                    "TIDAL ist nicht eingerichtet: TIDAL_CLIENT_ID und "
                    "TIDAL_CLIENT_SECRET fehlen in der .env (siehe docs/TIDAL.md)."
                ),
            }
        url = self.auth.anmelde_url()
        try:
            import webbrowser

            webbrowser.open(url, new=2)
        except Exception:  # noqa: BLE001
            logger.info("Browser nicht zu öffnen; die URL steht im Ergebnis.")
        return {"ok": True, "url": url}

    def anmeldung_abschliessen(self, code: str, state: str = "") -> dict[str, Any]:
        if not code.strip():
            return {"ok": False, "fehler": "Es kam kein Anmeldecode an."}
        try:
            self.auth.anmeldung_abschliessen(code.strip(), state)
        except TidalAuthFehler as fehler:
            return {"ok": False, "fehler": str(fehler)}
        return {"ok": True}


class LieblingssongsTool(_TidalWerkzeug):
    """22.11.2026: "stell mir eine Playlist aus den Sachen zusammen, die ich geliked habe"."""

    name = "lieblingssongs"
    description = (
        "Holt die Songs, die Marc in TIDAL geliked (mit Herz markiert) hat. "
        "aktion 'zeigen' nennt sie; aktion 'playlist' legt daraus eine neue "
        "Playlist an (Name frei waehlbar) und kann sie gleich abspielen. "
        "Benutze das bei 'meine Lieblingssongs', 'was ich geliked habe', "
        "'meine Favoriten'."
    )
    parameters = (
        ToolParameter("aktion", "string", "'zeigen' oder 'playlist'.",
                      required=False, default="playlist", choices=("zeigen", "playlist")),
        ToolParameter("name", "string", "Name der neuen Playlist.",
                      required=False, default="Meine Lieblingssongs"),
        ToolParameter("anzahl", "integer", "Hoechstens so viele Songs (Standard 100).",
                      required=False, default=100),
        ToolParameter("abspielen", "boolean", "Danach gleich abspielen.",
                      required=False, default=True),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            anzahl = max(1, min(_MAX_SONGS, int(arguments.get("anzahl") or 100)))
        except (TypeError, ValueError):
            anzahl = 100
        try:
            titel = await asyncio.to_thread(self._client.lieblingstitel, anzahl=anzahl)
            if not titel:
                return ToolResult.failure("In deiner TIDAL-Sammlung sind keine gelikten Songs.")
            if str(arguments.get("aktion") or "playlist") == "zeigen":
                liste = "\n".join(f"- {t.zum_vorlesen()}" for t in titel[:30])
                return ToolResult.success(f"Deine gelikten Songs ({len(titel)}):\n{liste}")
            name = str(arguments.get("name") or "Meine Lieblingssongs").strip()
            playlist = await asyncio.to_thread(
                self._client.playlist_anlegen, name, beschreibung="Von Synapse aus deinen Likes"
            )
            await asyncio.to_thread(self._client.titel_hinzufuegen, playlist.id, [t.id for t in titel])
        except (TidalFehler, TidalAuthFehler) as fehler:
            return self._fehler(fehler, app_seite="lieblingssongs")
        if arguments.get("abspielen", True) not in (False, "false", "False", 0):
            self._dienst.oeffnen(playlist.app_link, playlist.link)
        return ToolResult.success(
            f"Die Playlist „{playlist.name}“ ist angelegt, mit {len(titel)} deiner gelikten Songs.",
            playlist=playlist.id, link=playlist.link,
        )


class TidalAppTool(_TidalWerkzeug):
    """22.11.2026: Marc nutzt TIDAL als App - Seiten direkt dort oeffnen."""

    name = "tidal_app"
    description = (
        "Oeffnet in der TIDAL-App eine Seite deiner Sammlung: 'lieblingssongs' "
        "(gelikte Songs), 'playlists', 'alben', 'kuenstler', 'mixes' (deine "
        "Mixes) oder 'startseite'. Benutze das bei 'oeffne TIDAL', 'spiel "
        "meine Lieblingssongs/Mixes', 'zeig meine Playlists'. Einzelne Songs "
        "spielst du mit musik_abspielen, steuern mit musik_steuern."
    )
    parameters = (
        ToolParameter("seite", "string", "Welche Seite.", required=False, default="startseite",
                      choices=tuple(APP_SEITEN)),
        ToolParameter("abspielen", "boolean", "Gleich abspielen (Standard: ja bei Lieblingssongs und Mixes).",
                      required=False),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        seite = str(arguments.get("seite") or "startseite")
        if seite not in APP_SEITEN:
            seite = "startseite"
        wunsch = arguments.get("abspielen")
        abspielen = None if wunsch in (None, "") else wunsch in (True, "true", "True", 1)
        wo = self._dienst.app_seite_oeffnen(seite, abspielen=abspielen)
        ort = "in der TIDAL-App" if wo == "app" else "im TIDAL-Webplayer"
        spielt = abspielen if abspielen is not None else seite in ("lieblingssongs", "mixes")
        zusatz = " und starte die Wiedergabe - beim ersten Mal startet die App dafuer kurz neu" if spielt else ""
        return ToolResult.success(f"Ich habe {APP_SEITEN_NAMEN[seite]} {ort} geoeffnet{zusatz}.", wo=wo)


def build_tidal_tools(dienst: TidalDienst) -> list[Tool]:
    return [
        TidalAppTool(dienst),
        TidalAnmeldenTool(dienst),
        LieblingssongsTool(dienst),
        MusikSuchenTool(dienst),
        MusikAbspielenTool(dienst),
        MusikSteuernTool(dienst),
        PlaylistsAnsehenTool(dienst),
        PlaylistErstellenTool(dienst),
        PlaylistErgaenzenTool(dienst),
    ]
