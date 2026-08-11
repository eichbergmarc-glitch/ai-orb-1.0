"""OAuth2 für Gmail (Master-Prompt Abschnitte 35, 67).

Google verlangt für den Zugriff auf Gmail eine Anmeldung über OAuth2 – ein
API-Schlüssel genügt nicht, und das ist gut so: Ein Schlüssel wäre ein
Dauerzugang, ein OAuth-Token lässt sich einzeln widerrufen und ist auf
genau die Rechte beschränkt, die man erteilt hat.

## Der gewählte Weg: Loopback

Für Anwendungen ohne eigenen Server empfiehlt Google den
Loopback-Fluss. Er läuft so:

1. AI-Orb öffnet die Google-Zustimmungsseite im Browser.
2. Der Benutzer meldet sich bei Google an und erteilt die Erlaubnis –
   nicht gegenüber AI-Orb, sondern gegenüber Google.
3. Google schickt einen einmaligen Code an einen kurzlebigen lokalen
   Server, den AI-Orb nur für diesen Moment öffnet.
4. AI-Orb tauscht den Code gegen ein Zugriffs- und ein Erneuerungstoken.

Der Benutzer gibt sein Passwort also nur bei Google ein, nie bei AI-Orb.

## Wo die Geheimnisse liegen

Client-ID und Client-Secret der Anwendung kommen aus Umgebungsvariablen,
nie aus dem Code (Abschnitt 11). Das erteilte Token liegt in den
Benutzerdaten, außerhalb des Programmordners und außerhalb von Git – und,
wenn ein Schlüssel gesetzt ist, verschlüsselt. Ein Token ist ein
Zugang zum Postfach; es im Klartext neben den Programmcode zu legen wäre
fahrlässig.

## Zum Umfang der Rechte

Voreingestellt ist der Bereich ``gmail.modify`` – lesen, Entwürfe anlegen,
senden. Bewusst NICHT ``mail.google.com`` (Vollzugriff inkl. endgültigem
Löschen): Least Privilege (Abschnitt 46). Wer nur lesen will, setzt den
Bereich enger.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_user_dir

logger = get_logger(__name__)

#: Endpunkte von Google. Diese sind öffentlich und keine Geheimnisse.
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: Der voreingestellte Rechteumfang. Lesen, Entwürfe, Senden – nicht mehr.
DEFAULT_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


@dataclass(slots=True)
class OAuthConfig:
    """Die Anmeldedaten der Anwendung – aus der Umgebung, nie aus dem Code."""

    client_id: str = ""
    client_secret: str = ""
    scope: str = DEFAULT_SCOPE
    #: Port des kurzlebigen lokalen Servers. 0 heißt: ein freier wird gewählt.
    redirect_port: int = 0

    @classmethod
    def from_env(cls) -> OAuthConfig:
        """Liest die Anmeldedaten aus den Umgebungsvariablen.

        Die Namen sind fest, die Werte stehen in der ``.env``. Fehlt die
        ID, ist Gmail schlicht nicht eingerichtet – das ist kein Fehler,
        sondern ein Zustand, den der Agent verständlich meldet.
        """

        return cls(
            client_id=os.environ.get("GMAIL_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("GMAIL_CLIENT_SECRET", "").strip(),
            scope=os.environ.get("GMAIL_SCOPE", DEFAULT_SCOPE).strip() or DEFAULT_SCOPE,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id)


@dataclass(slots=True)
class Token:
    """Ein erteiltes Zugriffstoken samt Erneuerung."""

    access_token: str = ""
    refresh_token: str = ""
    #: Ablaufzeitpunkt als Unix-Zeit.
    expires_at: float = 0.0
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        # Eine Minute Puffer: Ein Token, das in dieser Sekunde noch gilt,
        # kann während der Anfrage ablaufen.
        return time.time() >= self.expires_at - 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Token:
        return cls(
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data.get("refresh_token", "")),
            expires_at=float(data.get("expires_at", 0.0)),
            scope=str(data.get("scope", "")),
        )


def _obfuscate(text: str, key: str) -> bytes:
    """Verschleiert das Token mit einem aus dem Schlüssel abgeleiteten Strom.

    Das ist bewusst kein Anspruch auf echte Kryptografie – dafür fehlt in
    der stdlib-only-Umgebung eine geprüfte Bibliothek, und eine selbst
    gebaute wäre schlechter als ehrlich benannte Verschleierung. Sie
    verhindert das eine, worauf es hier ankommt: dass ein Token im
    Klartext auf der Platte liegt und beim Blick in die Datei sofort
    lesbar ist. Wer keinen Schlüssel setzt, bekommt Klartext und eine
    Warnung – das ist eine bewusste Wahl, keine Falle.
    """

    stream = b""
    seed = key.encode("utf-8")
    while len(stream) < len(text.encode("utf-8")):
        seed = hashlib.sha256(seed).digest()
        stream += seed
    raw = text.encode("utf-8")
    return bytes(a ^ b for a, b in zip(raw, stream))


def _deobfuscate(data: bytes, key: str) -> str:
    stream = b""
    seed = key.encode("utf-8")
    while len(stream) < len(data):
        seed = hashlib.sha256(seed).digest()
        stream += seed
    return bytes(a ^ b for a, b in zip(data, stream)).decode("utf-8", errors="replace")


class GmailAuth:
    """Verwaltet Anmeldung, Token und dessen Erneuerung."""

    def __init__(
        self,
        config: OAuthConfig | None = None,
        *,
        token_path: Path | None = None,
    ) -> None:
        self.config = config or OAuthConfig.from_env()
        self.token_path = token_path or (get_user_dir() / "gmail" / "token.json")
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token: Token | None = None
        self._encryption_key = os.environ.get("AI_ORB_ENCRYPTION_KEY", "").strip()

    # --- Zustand --------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        """Ob ein brauchbares Token vorliegt."""

        token = self._load_token()
        return token is not None and bool(token.refresh_token)

    # --- Token laden und sichern ----------------------------------------------

    def _load_token(self) -> Token | None:
        if self._token is not None:
            return self._token
        if not self.token_path.is_file():
            return None

        try:
            raw = self.token_path.read_bytes()
        except OSError as error:
            logger.warning("Gmail-Token nicht lesbar: %s", error)
            return None

        try:
            if self._encryption_key and raw[:5] == b"ENC1:":
                text = _deobfuscate(base64.b64decode(raw[5:]), self._encryption_key)
            else:
                text = raw.decode("utf-8")
            self._token = Token.from_dict(json.loads(text))
            return self._token
        except (ValueError, json.JSONDecodeError) as error:
            logger.warning("Gmail-Token beschädigt: %s", error)
            return None

    def _save_token(self, token: Token) -> None:
        self._token = token
        payload = json.dumps(token.to_dict(), ensure_ascii=False)

        try:
            if self._encryption_key:
                blob = b"ENC1:" + base64.b64encode(
                    _obfuscate(payload, self._encryption_key)
                )
                self.token_path.write_bytes(blob)
            else:
                logger.warning(
                    "Gmail-Token wird im Klartext gespeichert. Setze "
                    "AI_ORB_ENCRYPTION_KEY in der .env, um es zu schützen."
                )
                self.token_path.write_text(payload, encoding="utf-8")

            # Nur der Benutzer darf lesen – soweit das Dateisystem es hergibt.
            try:
                os.chmod(self.token_path, 0o600)
            except OSError:
                pass
        except OSError as error:
            logger.error("Gmail-Token nicht speicherbar: %s", error)

    def forget(self) -> bool:
        """Löscht das Token – der Widerruf auf dieser Seite."""

        self._token = None
        try:
            if self.token_path.is_file():
                self.token_path.unlink()
            return True
        except OSError as error:
            logger.error("Gmail-Token nicht löschbar: %s", error)
            return False

    # --- Zugriffstoken beschaffen ---------------------------------------------

    def access_token(self) -> str:
        """Liefert ein gültiges Zugriffstoken und erneuert es bei Bedarf.

        Raises:
            GmailAuthError: Wenn keine Anmeldung vorliegt oder die
                Erneuerung scheitert.
        """

        token = self._load_token()
        if token is None or not token.refresh_token:
            raise GmailAuthError(
                "Gmail ist nicht angemeldet. Sage „Melde mich bei Gmail an“, "
                "um die einmalige Anmeldung zu starten."
            )

        if token.is_expired:
            token = self._refresh(token)

        return token.access_token

    def _refresh(self, token: Token) -> Token:
        """Erneuert das Zugriffstoken über das Erneuerungstoken."""

        data = urllib.parse.urlencode(
            {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "refresh_token": token.refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")

        try:
            response = self._post(_TOKEN_ENDPOINT, data)
        except OSError as error:
            raise GmailAuthError(f"Token-Erneuerung fehlgeschlagen: {error}") from error

        token.access_token = str(response.get("access_token", ""))
        token.expires_at = time.time() + float(response.get("expires_in", 3600))
        # Google schickt das Erneuerungstoken nicht jedes Mal mit; das alte
        # gilt weiter.
        if response.get("refresh_token"):
            token.refresh_token = str(response["refresh_token"])

        self._save_token(token)
        return token

    def exchange_code(self, code: str, redirect_uri: str, verifier: str) -> Token:
        """Tauscht den einmaligen Code gegen ein Token (Schritt 4 des Flusses)."""

        data = urllib.parse.urlencode(
            {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        ).encode("utf-8")

        response = self._post(_TOKEN_ENDPOINT, data)

        token = Token(
            access_token=str(response.get("access_token", "")),
            refresh_token=str(response.get("refresh_token", "")),
            expires_at=time.time() + float(response.get("expires_in", 3600)),
            scope=str(response.get("scope", self.config.scope)),
        )
        self._save_token(token)
        logger.info("Gmail-Anmeldung erfolgreich.")
        return token

    def build_authorization_url(self, redirect_uri: str) -> tuple[str, str]:
        """Baut die Zustimmungs-URL samt PKCE-Prüfwert.

        PKCE (der ``code_verifier``/``code_challenge``-Mechanismus) sichert
        den Fluss auch ohne vertrauliches Client-Secret ab – wichtig, weil
        eine Desktop-Anwendung ihr Secret nie wirklich geheim halten kann.

        Returns:
            Die URL und den ``code_verifier``, der später beim Tausch
            gebraucht wird.
        """

        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )

        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.config.scope,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            # Erzwingt das Erneuerungstoken auch bei wiederholter Anmeldung.
            "prompt": "consent",
        }
        return f"{_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}", verifier

    # --- HTTP ------------------------------------------------------------------

    def _post(self, url: str, data: bytes) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))


class GmailAuthError(RuntimeError):
    """Ein Problem bei Anmeldung oder Token."""
