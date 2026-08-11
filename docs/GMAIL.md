# Gmail einrichten

AI-Orb kann deine Mails lesen, durchsuchen, zusammenfassen, vorlesen und –
nach ausdrücklicher Bestätigung – beantworten und senden. Damit das sicher
geht, meldet sich AI-Orb über OAuth2 bei Google an: Du gibst dein Passwort
nur bei Google ein, nie bei AI-Orb, und kannst den Zugang jederzeit einzeln
widerrufen.

Das Einrichten dauert einmalig etwa zehn Minuten.

## Warum das nicht einfacher geht

Google lässt keinen Zugriff auf ein Postfach über einen simplen Schlüssel
zu – aus gutem Grund. Nötig ist ein OAuth-Zugang, den du in der Google
Cloud Console anlegst. Das klingt aufwendiger, als es ist, und es hat einen
handfesten Vorteil: Der Zugang gehört dir, ist auf die erteilten Rechte
beschränkt und mit einem Klick widerrufbar.

## Schritt für Schritt

1. Öffne die **Google Cloud Console** (`console.cloud.google.com`) und lege
   ein neues Projekt an – der Name ist gleichgültig, etwa „AI-Orb".

2. Suche oben nach **Gmail API** und aktiviere sie für dein Projekt.

3. Unter **APIs & Dienste → OAuth-Zustimmungsbildschirm**: Wähle „Extern",
   trage einen Namen und deine E-Mail ein. Füge dich selbst unter
   „Testnutzer" hinzu – solange die App nicht veröffentlicht ist, dürfen
   nur Testnutzer sie verwenden, und das genügt für den Eigengebrauch.

4. Unter **APIs & Dienste → Anmeldedaten → Anmeldedaten erstellen →
   OAuth-Client-ID**: Als Anwendungstyp **Desktop-App** wählen. Trage als
   autorisierten Weiterleitungs-URI ein:

       http://127.0.0.1:8756/gmail/callback

5. Google zeigt dir jetzt **Client-ID** und **Client-Secret**. Trage beide
   in deine `.env` ein:

       GMAIL_CLIENT_ID=...
       GMAIL_CLIENT_SECRET=...

6. Empfohlen: Setze in der `.env` außerdem einen
   `AI_ORB_ENCRYPTION_KEY` (eine beliebige lange Zeichenfolge). Damit wird
   das Zugriffstoken verschlüsselt gespeichert statt im Klartext.

7. Starte AI-Orb neu und sage: **„Melde mich bei Gmail an."** Der Browser
   öffnet die Google-Anmeldung; nach deiner Zustimmung ist die Einrichtung
   abgeschlossen.

## Was AI-Orb darf – und was nicht

Voreingestellt ist der Rechteumfang `gmail.modify`: lesen, Entwürfe
anlegen, senden. **Nicht** enthalten ist der endgültige, unwiderrufliche
Zugriff (`mail.google.com`) – das ist Absicht (Least Privilege). Wer nur
lesen möchte, setzt `GMAIL_SCOPE` auf `.../auth/gmail.readonly`.

## Die Sendesperre

AI-Orb sendet **niemals** ungefragt. Der Ablauf ist fest verdrahtet und
lässt sich nicht umgehen:

    Entwurf  →  AI-Orb liest ihn dir vor  →  du bestätigst  →  senden

Sagst du nach dem Vorlesen nicht ausdrücklich „ja, sende", bleibt der
Entwurf liegen und nichts verlässt dein Postfach. Das Senden ist als
kritische Aktion eingestuft und wird jedes Mal einzeln gefragt – es lässt
sich nicht auf „immer erlauben" stellen.

## Widerrufen

Sage „Melde mich von Gmail ab", um das Token zu löschen. Zusätzlich kannst
du den Zugang jederzeit vollständig in deinem Google-Konto entziehen:
`myaccount.google.com/permissions`.
