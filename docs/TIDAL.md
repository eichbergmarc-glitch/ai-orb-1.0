# TIDAL im AI-Orb

Der Orb kann mit TIDAL:

- **Musik abspielen**: „Spiel Yellow von Coldplay“, „Spiel meine Playlist Sport“
- **Steuern**: „Pause“, „Nächster Song“, „Lauter“ (über die Medientasten von Windows)
- **Suchen**: „Such mir Songs von Adele“
- **Playlists anlegen**: „Mach mir eine Playlist ‚Waldrunde‘ mit ruhigen Indie-Songs“
- **Playlists ergänzen**: „Füg ‚Hello‘ von Adele zu meiner Playlist Waldrunde hinzu“
- **Playlists ansehen**: „Welche Playlists habe ich?“

Abgespielt wird in der **TIDAL-Desktop-App**. Die öffentliche TIDAL-API
liefert selbst keine Musik aus. Der Orb sucht den Titel und öffnet ihn per
`tidal://`-Link in der App. Ist keine App installiert, öffnet er ihn im
Browser auf tidal.com.

## Einrichtung (einmalig)

1. **Zugangsdaten in die `.env`** im Projektordner (nie in `config.yaml`,
   die Datei liegt auf GitHub):

   ```
   TIDAL_CLIENT_ID=deine-client-id
   TIDAL_CLIENT_SECRET=dein-client-secret
   ```

2. **Redirect-URI im Entwicklerportal eintragen**: Unter
   https://developer.tidal.com → Dashboard → deine App → *Redirect URIs*
   folgende Adresse genau so hinzufügen:

   ```
   http://127.0.0.1:8756/tidal/callback
   ```

   Akzeptiert TIDAL `127.0.0.1` nicht, nimm `http://localhost:8756/tidal/callback`
   und stelle in `config.yaml` unter `tidal.redirect_uri` dasselbe ein.

3. **Bereiche (Scopes)** der App im Portal aktivieren: `user.read`,
   `search.read`, `playlists.read`, `playlists.write`, `collection.read`,
   `collection.write`.

4. **TIDAL-Desktop-App** installieren und darin anmelden.

5. Orb neu starten und einmal sagen: **„Melde mich bei TIDAL an“**. Im
   Browser bei TIDAL anmelden und zustimmen. Danach kann der Orb
   Playlists anlegen. Suchen und Abspielen funktionieren auch ohne diesen
   Schritt.

## Einstellungen (`config.yaml` → `tidal`)

| Schlüssel | Bedeutung |
|---|---|
| `enabled` | TIDAL ein/aus |
| `land` | Katalogland (z. B. `CH`, `DE`) |
| `nach_oeffnen_abspielen` | Nach dem Öffnen die Wiedergabetaste drücken. Auf `false` stellen, wenn die App selbst losspielt und der Orb sonst pausiert. |
| `warte_sekunden` | Wie lange der Orb auf die App wartet, bevor er „Play“ drückt |
| `redirect_uri` | Rückweg der Anmeldung (muss im Portal stehen) |
| `scope` | Eigene Bereiche, leer = Voreinstellung |

## Wo was liegt

- `backend/integrations/tidal/oauth.py`: Anmeldung (Client Credentials + PKCE)
- `backend/integrations/tidal/client.py`: API-Aufrufe (Suche, Playlists)
- `backend/integrations/tidal/player.py`: App öffnen, Medientasten
- `backend/tools/tidal_tools.py`: die sieben Werkzeuge
- Token: Benutzerdaten `tidal/token.json`, verschleiert, wenn `AI_ORB_ENCRYPTION_KEY` gesetzt ist
