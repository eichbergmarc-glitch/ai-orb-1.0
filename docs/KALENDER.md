# Der Google-Kalender im Orb

Der Orb kann Termine ansehen, eintragen, verschieben und löschen - und von
sich aus Bescheid sagen, bevor etwas ansteht.

---

## Einrichten

Es ist **dieselbe Anmeldung wie bei Gmail**: dieselbe Client-ID, dasselbe
Token, eine Zustimmungsseite für beides.

### Wenn Gmail schon läuft

Dann fehlt nur eine Kleinigkeit. Sag dem Orb einmal:

> **„Melde mich bei Gmail an."**

Auf der Google-Seite steht jetzt zusätzlich der Kalender. Zustimmen, fertig.
Der Umweg ist nötig, weil das alte Token nur die Post kannte - Google trägt
die erteilten Rechte im Token selbst ein, und ein bereits erteiltes lässt
sich nachträglich nicht erweitern.

Solange das nicht geschehen ist, sagt der Orb genau das, statt eine
Fehlermeldung von Google vorzulesen.

### Wenn Google noch gar nicht eingerichtet ist

1. In der [Google Cloud Console](https://console.cloud.google.com/) ein
   Projekt anlegen.
2. Unter **APIs & Dienste → Bibliothek** die **Google Calendar API** und die
   **Gmail API** aktivieren.
3. Unter **Anmeldedaten → OAuth-Client-ID erstellen** den Typ
   **Desktop-App** wählen.
4. Als Weiterleitungsziel eintragen:
   `http://127.0.0.1:8756/gmail/callback`
5. Die beiden Werte in die Datei `.env` im AI-Orb-Ordner schreiben:

   ```
   GMAIL_CLIENT_ID=...
   GMAIL_CLIENT_SECRET=...
   ```

   **Nur dorthin.** Nie in die `config.yaml`, nie nach GitHub - dort steht
   ausschließlich der NAME der Variablen, nie ihr Wert.

6. Den Orb neu starten und sagen: „Melde mich bei Gmail an."

Empfohlen ist zusätzlich ein `AI_ORB_ENCRYPTION_KEY` in der `.env`. Ohne ihn
liegt das Token im Klartext auf der Platte, und der Orb sagt das auch.

---

## Was man sagen kann

| Gesagt | Was passiert |
|---|---|
| „Was steht heute an?" | Die Termine von heute |
| „Was habe ich morgen für Termine?" | Die Termine von morgen |
| „Zeig mir meinen Kalender diese Woche" | Die nächsten sieben Tage |
| „Trag mir morgen um 14 Uhr den Zahnarzt ein" | Legt den Termin an, eine Stunde lang |
| „Trag Zahnarzt am 15.9. um halb elf ein, 90 Minuten" | Mit Datum und Dauer |
| „Verschieb den Zahnarzt auf 16 Uhr" | Verschiebt ihn, **die Dauer bleibt** |
| „Sag den Termin am Freitag ab" | Löscht ihn |

Zeitangaben dürfen so klingen, wie man sie sagt: *morgen um zwei*,
*nächsten Dienstag*, *halb drei*, *viertel vor acht*, *in zwei Stunden*,
*15.09.2026 09:30*. Ist etwas nicht eindeutig, fragt der Orb nach, statt zu
raten - eine geratene Zeit im Kalender ist schlimmer als eine Rückfrage.

### Beim Ändern und Löschen wird nicht geraten

Termine werden über ein Stichwort gesucht. Passen mehrere, liest der Orb die
Liste vor und fragt, welcher gemeint ist. Er nimmt nie den erstbesten.

---

## Die Erinnerungen

Voreingestellt erinnert der Orb **eine Stunde** und **zehn Minuten** vor
einem Termin. Zu ändern in der `config.yaml`:

```yaml
kalender:
  erinnerung:
    enabled: true
    vorlaufzeiten: [60, 10]   # Minuten vorher
    takt_sekunden: 180        # wie oft nachgesehen wird
```

Ein paar Festlegungen dahinter:

* **Ganztägige Termine lösen keine Vorlauferinnerung aus.** Bei ihnen gibt
  es keine Uhrzeit, auf die sich ein Vorlauf beziehen könnte.
* **Jede Erinnerung kommt genau einmal.** Es wird alle drei Minuten
  nachgesehen, aber nicht alle drei Minuten dasselbe gesagt.
* **Nichts wird nachgeholt.** Wer den Orb zehn Minuten vor einem Termin
  startet, hört die Stunde-vorher-Erinnerung nicht mehr.
* **„Sei mal still" gilt auch hier.** Hat man um Ruhe gebeten, schweigt der
  Orb auch bei Terminen.

Ganz abschalten: `enabled: false`.

---

## Wenn etwas nicht geht

| Was der Orb sagt | Was zu tun ist |
|---|---|
| „Sag einmal: Melde mich bei Gmail an" | Genau das - die Freigabe fehlt noch |
| „Es fehlt GMAIL_CLIENT_ID in der .env" | Siehe Einrichten, oben |
| „Der Kalender ist nicht erreichbar" | Kein Netz; er versucht es von selbst wieder |

Im Zweifel steht der Grund im Klartext in
`logs/backend_integrations_kalender_client.log`.

---

## Was der Orb *nicht* darf

Die Freigabe umfasst **nur Termine** (`calendar.events`), nicht die
Verwaltung ganzer Kalender. Der Orb kann also keinen Kalender anlegen,
umbenennen oder löschen - nur die Termine darin. Das ist Absicht: Weniger
Rechte zu erteilen, als man erteilen könnte, ist die billigste
Sicherheitsmaßnahme, die es gibt.
