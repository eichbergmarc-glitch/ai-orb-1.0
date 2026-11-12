"""Anmeldung bei TIDAL.

TIDAL kennt zwei Wege, und der Orb braucht beide:

1. **Client Credentials** - nur mit Client-ID und Client-Secret, ohne
   Benutzer. Damit darf man den Katalog durchsuchen (Titel, Alben,
   Künstler). Das funktioniert sofort, ganz ohne Anmeldung im Browser.
2. **Authorization Code mit PKCE** - der Benutzer meldet sich einmal im
   Browser bei TIDAL an. Erst damit darf der Orb in SEINEM Konto etwas tun:
   Playlists anlegen, Titel hinzufügen, eigene Playlists ansehen.

Der Ablauf von Weg 2 ist derselbe Loopback-Fluss wie bei Gmail: Browser
auf, Anmeldung bei TIDAL, TIDAL schickt den Einmalcode an
``/tidal/callback`` des lokalen Servers, der Code wird gegen ein Token
getauscht. Das Passwort sieht der Orb nie.

## Wo die Geheimnisse liegen

Client-ID und Client-Secret stehen in der ``.env`` (``TIDAL_CLIENT_ID``,
``TIDAL_CLIENT_SECRET``), nie im Code und nie in ``config.yaml`` - das
Projekt liegt auf GitHub. Das Benutzertoken liegt in den Benutzerdaten
(``tidal/token.json``), verschleiert wie das Gmail-Token, wenn
``AI_ORB_ENCRYPTION_KEY`` gesetzt ist.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.integrations.gmail.oauth import Token, _deobfuscate, _obfuscate
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_user_dir

logger = get_logger(__name__)

#: Öffentliche Endpunkte von TIDAL - keine Geheimnisse.
AUTH_ENDPOINT = "https://login.tidal.com/authorize"
TOKEN_ENDPOINT = "https://auth.tidal.com/v1/oauth2/token"

#: Was der Orb im Konto darf: lesen, suchen, Playlists und Sammlung pflegen.
#: Lässt sich mit ``TIDAL_SCOPE`` in der .env oder ``tidal.scope`` in der
#: config.yaml ändern, falls TIDAL die Namen der Bereiche ändert.
DEFAULT_SCOPE = (
    "user.read search.read playlists.read playlists.write "
    "collection.read collection.write"
)

#: Der Rückweg nach der Anmeldung. Muss im TIDAL-Entwicklerportal GENAU so
#: als Redirect-URI eingetragen sein.
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8756/tidal/callback"


class TidalAuthFehler(RuntimeError):
    """Ein Problem bei Anmeldung oder Token."""


@dataclass(slots=True)
class TidalOAuthConfig:
    """Die Anmeldedaten der Anwendung."""

    client_id: str = ""
    client_secret: str = ""
    scope: str = DEFAULT_SCOPE
    redirect_uri: str = DEFAULT_REDIRECT_URI

    @classmethod
    def from_env(
        cls, *, scope: str = "", redirect_uri: str = ""
    ) -> TidalOAuthConfig:
        return cls(
            client_id=os.environ.get("TIDAL_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("TIDAL_CLIENT_SECRET", "").strip(),
            scope=(os.environ.get("TIDAL_SCOPE", "").strip() or scope or DEFAULT_SCOPE),
            redirect_uri=redirect_uri or DEFAULT_REDIRECT_URI,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def _post_formular(url: str, felder: dict[str, str], *, basic: tuple[str, str] | None = None) -> dict[str, Any]:
    """Schickt ein Formular an den Token-Endpunkt und liest die JSON-Antwort."""

    kopf = {"Content-Type": "application/x-www-form-urlencoded"}
    if basic is not None:
        roh = f"{basic[0]}:{basic[1]}".encode("utf-8")
        kopf["Authorization"] = "Basic " + base64.b64encode(roh).decode("ascii")

    anfrage = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(felder).encode("utf-8"),
        headers=kopf,
        method="POST",
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:
            return json.loads(antwort.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as fehler:
        text = fehler.read().decode("utf-8", errors="replace")[:400]
        raise TidalAuthFehler(f"TIDAL lehnt die Anmeldung ab ({fehler.code}): {text}") from fehler
    except (urllib.error.URLError, TimeoutError, OSError) as fehler:
        raise TidalAuthFehler(f"TIDAL ist nicht erreichbar: {fehler}") from fehler


class TidalAuth:
    """Verwaltet beide Token: das der Anwendung und das des Benutzers."""

    def __init__(
        self,
        config: TidalOAuthConfig | None = None,
        *,
        token_path: Path | None = None,
        post: Any = None,
    ) -> None:
        self.config = config or TidalOAuthConfig.from_env()
        self.token_path = token_path or (get_user_dir() / "tidal" / "token.json")
        self._token: Token | None = None
        self._app_token: Token | None = None
        self._key = os.environ.get("AI_ORB_ENCRYPTION_KEY", "").strip()
        #: Einschleusbar für Tests - kein Test soll echt bei TIDAL anklopfen.
        self._post = post or _post_formular
        #: Der PKCE-Prüfwert und der state der laufenden Anmeldung.
        self._ausstehend: tuple[str, str] | None = None

    # --- Zustand --------------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    @property
    def is_authenticated(self) -> bool:
        token = self._load_token()
        return token is not None and bool(token.refresh_token or not token.is_expired)

    # --- Anwendungstoken (nur Katalog) ---------------------------------------

    def app_token(self) -> str:
        """Ein Token ohne Benutzer - reicht zum Suchen im Katalog."""

        if not self.is_configured:
            raise TidalAuthFehler(
                "TIDAL ist nicht eingerichtet: TIDAL_CLIENT_ID und "
                "TIDAL_CLIENT_SECRET fehlen in der .env."
            )
        if self._app_token is not None and not self._app_token.is_expired:
            return self._app_token.access_token

        antwort = self._post(
            TOKEN_ENDPOINT,
            {"grant_type": "client_credentials"},
            basic=(self.config.client_id, self.config.client_secret),
        )
        self._app_token = Token(
            access_token=str(antwort.get("access_token", "")),
            expires_at=time.time() + float(antwort.get("expires_in", 3600)),
            scope=str(antwort.get("scope", "")),
        )
        if not self._app_token.access_token:
            raise TidalAuthFehler("TIDAL hat kein Zugriffstoken geschickt.")
        return self._app_token.access_token

    # --- Benutzertoken ---------------------------------------------------------

    def user_token(self) -> str:
        """Ein Token im Namen des Benutzers - nötig für Playlists."""

        token = self._load_token()
        if token is None:
            raise TidalAuthFehler(
                "Du bist bei TIDAL noch nicht angemeldet. Sag „Melde mich bei "
                "TIDAL an“ - das ist einmalig."
            )
        if token.is_expired:
            if not token.refresh_token:
                raise TidalAuthFehler(
                    "Die TIDAL-Anmeldung ist abgelaufen. Sag „Melde mich bei "
                    "TIDAL an“, um sie zu erneuern."
                )
            token = self._erneuern(token)
        return token.access_token

    def bester_token(self) -> str:
        """Benutzertoken, wenn vorhanden - sonst das Anwendungstoken."""

        try:
            return self.user_token()
        except TidalAuthFehler:
            return self.app_token()

    def _erneuern(self, token: Token) -> Token:
        antwort = self._post(
            TOKEN_ENDPOINT,
            {
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "client_id": self.config.client_id,
            },
        )
        token.access_token = str(antwort.get("access_token", ""))
        token.expires_at = time.time() + float(antwort.get("expires_in", 3600))
        if antwort.get("refresh_token"):
            token.refresh_token = str(antwort["refresh_token"])
        self._save_token(token)
        return token

    # --- Anmeldung im Browser --------------------------------------------------

    def anmelde_url(self) -> str:
        """Baut die Anmelde-URL und merkt sich Prüfwert und state."""

        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        state = secrets.token_urlsafe(16)
        self._ausstehend = (verifier, state)

        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": self.config.scope,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
        return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    def anmeldung_abschliessen(self, code: str, state: str = "") -> Token:
        """Tauscht den Einmalcode gegen das Benutzertoken."""

        if self._ausstehend is None:
            raise TidalAuthFehler(
                "Es läuft gerade keine TIDAL-Anmeldung. Sag zuerst „Melde mich "
                "bei TIDAL an“."
            )
        verifier, erwartet = self._ausstehend
        # Der state schützt davor, dass eine fremde Seite dem Orb einen Code
        # unterschiebt. Fehlt er ganz, lassen wir es durchgehen (manche
        # Weiterleitungen verlieren ihn), ein FALSCHER state aber nicht.
        if state and state != erwartet:
            raise TidalAuthFehler("Der Rückweg passt nicht zur gestarteten Anmeldung.")

        antwort = self._post(
            TOKEN_ENDPOINT,
            {
                "grant_type": "authorization_code",
                "client_id": self.config.client_id,
                "code": code,
                "redirect_uri": self.config.redirect_uri,
                "code_verifier": verifier,
            },
        )
        token = Token(
            access_token=str(antwort.get("access_token", "")),
            refresh_token=str(antwort.get("refresh_token", "")),
            expires_at=time.time() + float(antwort.get("expires_in", 3600)),
            scope=str(antwort.get("scope", self.config.scope)),
        )
        if not token.access_token:
            raise TidalAuthFehler("TIDAL hat kein Zugriffstoken geschickt.")
        self._save_token(token)
        self._ausstehend = None
        logger.info("TIDAL-Anmeldung erfolgreich.")
        return token

    def forget(self) -> bool:
        self._token = None
        try:
            if self.token_path.is_file():
                self.token_path.unlink()
            return True
        except OSError as fehler:
            logger.error("TIDAL-Token nicht löschbar: %s", fehler)
            return False

    # --- Speichern -------------------------------------------------------------

    def _load_token(self) -> Token | None:
        if self._token is not None:
            return self._token
        if not self.token_path.is_file():
            return None
        try:
            roh = self.token_path.read_bytes()
            if self._key and roh[:5] == b"ENC1:":
                text = _deobfuscate(base64.b64decode(roh[5:]), self._key)
            else:
                text = roh.decode("utf-8")
            self._token = Token.from_dict(json.loads(text))
            return self._token
        except (OSError, ValueError) as fehler:
            logger.warning("TIDAL-Token nicht lesbar: %s", fehler)
            return None

    def _save_token(self, token: Token) -> None:
        self._token = token
        inhalt = json.dumps(token.to_dict(), ensure_ascii=False)
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            if self._key:
                self.token_path.write_bytes(
                    b"ENC1:" + base64.b64encode(_obfuscate(inhalt, self._key))
                )
            else:
                logger.warning(
                    "TIDAL-Token wird im Klartext gespeichert. Setze "
                    "AI_ORB_ENCRYPTION_KEY in der .env, um es zu schützen."
                )
                self.token_path.write_text(inhalt, encoding="utf-8")
            try:
                os.chmod(self.token_path, 0o600)
            except OSError:
                pass
        except OSError as fehler:
            logger.error("TIDAL-Token nicht speicherbar: %s", fehler)
