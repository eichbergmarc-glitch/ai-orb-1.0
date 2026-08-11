"""Gmail-Anbindung (Master-Prompt Abschnitte 35, 36, 67).

Der Benutzer kann Mails lesen, suchen, zusammenfassen, vorlesen lassen,
beantworten, Entwuerfe erstellen und senden.

Die eine Regel, die alles ueberstimmt, steht in Abschnitt 36:

    Der Orb darf niemals ungefragt eine Mail senden.

Sie ist hier nicht als Bitte ans Sprachmodell umgesetzt, sondern als
Ablauf, an dem kein Modell vorbeikommt: Senden geht ausschliesslich ueber
einen zuvor angelegten Entwurf, der ausdruecklich bestaetigt wurde.
"""

from backend.integrations.gmail.client import GmailClient, GmailMessage
from backend.integrations.gmail.oauth import GmailAuth, OAuthConfig

__all__ = ["GmailAuth", "GmailClient", "GmailMessage", "OAuthConfig"]
