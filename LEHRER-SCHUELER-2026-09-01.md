# Lehrer und Schüler: Claude als Referenz, Ollama als Nachfolger

Stand 01.09.2026, nach der Post-Fix-Messserie. Das Dokument ist
chronologisch: erst was gebaut wurde, dann der erste reale Messlauf
(L1/L2) mit den Fehlern, die er gefunden hat, dann die Reparaturen und die
getrennte Serie danach (L3/L4/L5). **Alte Messwerte wurden nicht
verändert** — sie stehen als historischer Stand.

---

## Die Vorbemerkung von heute Morgen — inzwischen überholt

Bis zum Mittag des 1. September stand hier: *„Diese Messung habe ich nicht
durchgeführt, und ich konnte es nicht."* Der Grund war echt — die Sitzung
arbeitete in einer Linux-VM ohne Ollama, ohne Claude Code, ohne Netz — und der
Satz war richtig, solange er dastand.

**Er gilt nicht mehr.** Der Messlauf ist am 1. September 2026 zwischen 06:49
und 07:22 Uhr auf `desktop-6i52n9c` wirklich gelaufen, mit der Claude-Code-CLI
2.1.224 und Ollama 0.33.2. Was daraus geworden ist, steht weiter unten unter
„Der reale Messlauf" — mit Befehlen, Exit-Codes, Zahlen je Kategorie, Pfaden
zu Rohdaten und den vier Fehlern, die dabei aufgefallen sind.

Ich lasse die alte Vorbemerkung nicht einfach verschwinden, weil sie erklärt,
warum die ganze Vorrichtung so gebaut ist, wie sie gebaut ist: Alles, was
gemessen wird, landet in Dateien, und jeder Schritt ist einzeln aufrufbar.
Genau das hat den Lauf dann möglich gemacht, obwohl diese Sitzung selbst noch
immer kein Windows-Programm starten kann — gestartet wurde er per Doppelklick
über die Fernsteuerung deines Rechners.

---

## Was gebaut ist

### Der Fähigkeitskatalog (`backend/lernen/faehigkeitskatalog.py`)

19 Prüfstücke über alle acht Kategorien, versioniert (`1.0.0`) und mit einer
Prüfsumme über den Inhalt. Wer die Messlatte verschiebt, ändert die
Prüfsumme — sie steht in jeder Messung. Drei Bewertungsarten:

* `deterministisch` — steht die Zahl drin, ja oder nein. Kein Modell.
* `werkzeug` — liefen die verlangten Werkzeuge, waren sie erfolgreich.
* `rubrik` — vorab formulierte Kriterien, je eines einen Punkt.

Der Katalog ist bewusst klein. Ein Katalog, der alles abdeckt und nie läuft,
ist weniger wert als ein kleiner, der wirklich läuft.

### Die Bewertung (`backend/lernen/bewertung.py`)

Drei Bewerterarten, die schwächste zuletzt, und eine Regel, die den ganzen
Aufbau trägt: **Ein befangenes Urteil zählt nicht in die Punkte.** Bewertet
ein Modell seine eigene Antwort, wird das Urteil gespeichert und beim
Zusammenzählen übersprungen — sonst wäre die Messung ein Selbstgespräch.
Deterministische Urteile wiegen doppelt gegenüber Rubrikurteilen.

Ist kein Bewerter angeschlossen, sagt die Ersatzprüfung das ausdrücklich
(„trägt keine fachliche Aussage"), statt eine Zahl zu liefern, die wie ein
Urteil aussieht.

### Die Übergabe (`backend/lernen/uebergabe.py`)

Die sechs Bedingungen aus deinem Auftrag stehen als Code, nicht als
Absichtserklärung. Jede einzelne kann einen Lauf verlieren lassen, und für
jede gibt es einen Test, der sie einzeln verletzt:

| Bedingung | Konfiguration |
|---|---|
| höchstens 3 Prozentpunkte fachlicher Rückstand | `lernen.max_rueckstand_prozentpunkte` |
| keine höhere Halluzinationsrate | fest: mehr als der Lehrer ist nie erlaubt |
| keine höhere Sicherheitsfehlerrate | fest |
| ≥ 98 % der Werkzeugabläufe | `lernen.mindest_werkzeugquote` |
| Blindbewertung überwiegend gleichwertig | `lernen.mindest_blindurteil` |
| alle Regressionstests grün | vom Aufrufer zu belegen |
| **drei unabhängige Läufe** | `lernen.noetige_laeufe` |

Stufen: 0 → 10 → 25 → 50 → 75 → 100 %. Derselbe Lauf zählt nur einmal.
Eine Verschlechterung setzt ohne Rückfrage auf die letzte stabile Stufe
zurück; `zuruecksetzen()` tut dasselbe von Hand, wenn im Betrieb etwas
auffällt.

### Das Routing (`provider_manager._lokal_uebernimmt`)

Für jede Anfrage wird die Kategorie bestimmt
(`backend/lernen/kategorien.py`) und der freigegebene Anteil ausgelost —
**deterministisch**, nicht zufällig: Bei 25 % ist jede vierte Anfrage lokal,
und derselbe Fall fällt im Test immer gleich aus. Bei 0 % ändert sich
nichts, bei 100 % geht alles lokal. Im Offlinebetrieb greift die Auslosung
nicht, dort entscheidet ohnehin der Offlinemodus.

### Der Schattenlauf (`backend/lernen/schattenlauf.py`, `schattenpfad.py`)

Standardmäßig **aus** (`lernen.schattenlauf_aktiv: false`), weil er lokale
Rechenzeit kostet und die bei diesem Orb das knappste Gut ist. Gespeichert
wird nicht das Gespräch, sondern die Lehre daraus: Kategorie, eine von neun
abstrakten Fehlerklassen, die Werkzeugentscheidung, ein
Verbesserungsvorschlag. Vor jeder Speicherung läuft die Anonymisierung über
Mail-Adressen, Telefonnummern, IBAN, Schlüssel und Token, Benutzerordner,
Adressen und lange Zahlenfolgen. Nach internen Gedankengängen wird nicht
gefragt, und ungefragt Gekommenes wird nicht abgelegt.

Seit dem 1. September ist er auch **angeschlossen**: `schattenpfad.py`
hängt ihn hinter `Orchestrator.handle`, wo er die fertige Antwort nur noch
zu lesen bekommt. Die Einzelheiten und ihre Nachweise stehen weiter unten
unter „Die vier offenen Punkte".

---

## Was gemessen wird

Pro Prüfstück und Modell: Erfolg, schwere Halluzination, Sicherheitsfehler,
Punkte, Werkzeuge (verlangt / gelaufen / erfolgreich), Zeit bis zum ersten
Wort, Zeit bis zum ersten hörbaren Ton, Gesamtdauer, Tokens pro Sekunde,
geschätzte Kosten, Speicher — und die Betriebsart **warm / kalt / offline**
getrennt. Ein Kaltstart mit zwölf Sekunden Ladezeit ist kein schlechteres
Modell, sondern ein anderer Messpunkt.

Abgelegt wird angehängt, nie geändert: `data/lernen/messungen.jsonl`.

---

## Ein Fehler, den ich dabei gefunden und behoben habe

Beim Einfügen des Abschnitts `lernen:` fiel auf, dass die `config.yaml` seit
heute Nachmittag **zwei** Abschnitte `routing:` hatte — einer davon von mir.
YAML nimmt in so einem Fall den letzten. Damit waren `routing.mode`, die
Hosts für die Netzprüfung und die Umschaltregeln stillschweigend
verschwunden; der Orb lief mit Vorgabewerten weiter, ohne dass irgendwo ein
Fehler erschien.

Zusammengeführt, und `test_die_konfiguration_hat_keine_doppelten_abschnitte`
fängt es beim nächsten Mal ab.

---

## Testergebnisse (Stand 1. September 2026, nach den vier Arbeitspaketen)

Der ganze Bestand, in Blöcken gefahren, weil ein Aufruf in dieser Umgebung
nach zwei Minuten abgeschnitten wird:

| Testdateien | Ergebnis |
| --- | --- |
| 1–40 (`test_agenten_modellwahl` … `test_human_speech`) | 561 bestanden |
| 41–45 (`test_intent_classifier` … `test_knowledge_and_learning`) | 183 bestanden, **1 rot** |
| 46–48 (`test_kontingent_*`, `test_launch_apps`) | 16 bestanden |
| 49 (`test_launcher_and_paths`) | 23 bestanden, 1 abgewählt (siehe unten) |
| 50 (`test_lehrer_schueler`) | 41 bestanden |
| 51–55 (`test_lehrplan_und_sprechweise` … `test_memory_engine`) | 61 bestanden |
| 56–75 (`test_messpfad_werkzeuge` … `test_orb_identitaet`) | 296 bestanden |
| 76–95 (`test_patchschmied` … `test_stimmerkennung`) | 377 bestanden |
| 96–110 (`test_stop_fenster` … `test_voice_and_tts`) | 277 bestanden, **5 rot** |
| 111–120 (`test_voice_menu_command` … `test_werkzeuge_angemeldet`) | 110 bestanden |
| **Summe** | **1945 bestanden, 6 rot** |

**Die sechs roten sind dieselben wie zu Beginn und liegen an dieser
Linux-Umgebung, nicht am Programm:**

* 5× `tests/backend/test_voice_and_tts.py` – `ModuleNotFoundError: No module
  named 'torch'`. Auf deinem Rechner ist `torch` installiert.
* 1× `tests/backend/test_kalender.py::test_eine_geaenderte_google_kalenderzone_wird_dynamisch_uebernommen`
  – `ValueError: Invalid isoformat string: '2026-08-16T15:00:00Z'`. Der
  Fehler steckt im Testdoppel (Zeile 194), nicht im Programm, und tritt nur
  unter Python 3.10 auf; hier läuft 3.10.12, `datetime.fromisoformat`
  versteht das `Z` erst ab 3.11. Ich habe die Datei **nicht** angefasst:
  Änderungen an Tests sind laut deinen Regeln freigabepflichtig.

**Eine Beobachtung, kein Fehler:**
`test_launcher_and_paths.py::test_migration_never_overwrites` läuft in
diesem Arbeitsverzeichnis minutenlang. Der Test hebt `is_portable` auf,
worauf `migrate_from_project(dry_run=True)` den echten `data/`-Ordner
durchwandert – und der ist hier **11 GB** gross. Im Betrieb passiert das
nicht: `runtime.py` ruft die Übernahme nur im nicht-tragbaren Modus und nur
einmal (Marker `.uebernommen`). Ich habe den Test für den Blocklauf
abgewählt und ihn nicht verändert.

---

## Die vier offenen Punkte – Nachweis je Anforderung

### 1. Werkzeugschleife im Messpfad — **ERLEDIGT**

**Geändert**

* `backend/lernen/messwerkzeuge.py` (neu) – der eingehegte Werkzeugkasten
  für den Messlauf. `ERLAUBTE_BERECHTIGUNGEN` lässt nur lesende und
  rechnende Werkzeuge zu; `AUSGENOMMEN` sperrt ausdrücklich alles, was das
  Programm selbst verändert (`neu_starten`, `oberflaeche_neu_bauen`,
  `wissen_aneignen`, `wissen_vertiefen`, `webseite_erkunden`).
  `messumgebung(ordner)` setzt `AI_ORB_DATA_DIR` auf ein eigenes
  Messverzeichnis und stellt es danach zurück – ein Messlauf schreibt
  nicht in dein Gedächtnis. In dieser Umgebung meldet sich der Kasten mit
  17 Werkzeugen an.
* `backend/lernen/messen.py` – `_einen_fall_messen(…, werkzeugschleife=…)`
  ruft die echte `ToolEngine`, wenn das Prüfstück Werkzeuge verlangt oder
  die Kategorie ohne sie nicht messbar wäre (`werkzeugwahl`,
  `rechnerbedienung`, `gedaechtnis`). Aufgezeichnet wird je Aufruf
  `{werkzeug, erfolg, fehler, sekunden, ausgabe_zeichen}`.
* `backend/lernen/messwerte.py` – `Messung` trägt jetzt `werkzeugspur`,
  `runden`, `abbruchgrund`, `aufrufe_ungueltig`. Damit lässt sich
  hinterher unterscheiden, ob ein Werkzeug **nicht gerufen** wurde oder ob
  es gerufen wurde und **scheiterte** – zwei völlig verschiedene Befunde,
  die vorher beide als „kein Erfolg“ herauskamen.
* `backend/lernen/faehigkeitskatalog.py` – der Katalog nannte drei
  Werkzeuge, die es gar nicht gibt (`verzeichnis_auflisten`,
  `kalender_termine`, `erinnerung_speichern`). Ersetzt durch die echten
  Registernamen (`ordner_auflisten`, `termine_ansehen`, `vorliebe_merken`),
  `KATALOG_VERSION` auf `1.1.0`.
* `backend/tools/tool_engine.py` – `run()` hatte die Reparaturrunde für
  ungültige Aufrufe nicht, die `continue_with_tools()` längst hatte: Ein
  schemawidriger Aufruf verschwand still. Jetzt derselbe begrenzte
  Reparaturweg (`tools.reparatur_versuche`).

**Nachweis:** `tests/backend/test_messpfad_werkzeuge.py` — **11 bestanden.**
Die Tests laufen mit **echten** Werkzeugen (`aktuelle_zeit`,
`ordner_auflisten`, `karteikarte_anlegen`, `vorliebe_merken`, `rechnen`);
nur das Sprachmodell ist ein Doppel. Belegt sind: Einhaltung der
Erlaubnisliste, Isolierung und Rückgabe des Datenverzeichnisses,
erfolgreicher Lauf mit Spur, „Werkzeug nicht gerufen“, „gerufen und
gescheitert“, Mehrrundenlauf mit Rückmeldung, ungültiger Aufruf wird nicht
ausgeführt und führt zu einer Reparaturrunde, und dass Kategorien ohne
Werkzeugbedarf unverändert gemessen werden.

### 2. Blindbewerter — **ERLEDIGT**

**Geändert:** `backend/lernen/blindbewertung.py` (neu).

* **Maskierung.** `maskieren()` entfernt Anbieter- und Modellnamen sowie
  Selbstbezeichnungen („Ich bin ein Sprachmodell…“, „Ich wurde von … 
  trainiert“, „Modellversion …“). `lecks_finden()` ist die Umkehrung und
  zugleich der Prüfstein der Tests.
* **Losverfahren.** `vorlage_bauen()` entscheidet über
  `sha256(kennung)`, wer Etikett A bekommt – nicht die Reihenfolge des
  Aufrufers. Dieselbe Vergleichskennung ergibt dieselbe Zuteilung
  (nachvollziehbar), verschiedene Kennungen streuen.
* **Auflösung erst danach.** Der Bewerter gibt „A“, „B“ oder „gleich“
  zurück; `aufloesen()` verbindet Etikett und Herkunft erst nach dem
  Urteil.
* **Befangenheitsschranke.** `modellurteiler(…)` wirft `Befangen`, wenn
  das vorgesehene Bewertermodell selbst im Vergleich steht. Kein Hinweis,
  kein Protokolleintrag – ein Abbruch.
* **Anschluss.** `vergleichsreihe()` erzeugt die
  Gleichwertigkeitsquote, die `Pruefergebnis.blindurteil_gleichwertig` und
  damit eine der sechs Übergabebedingungen trägt. Sie entsteht jetzt aus
  einzelnen Urteilen statt aus einer eingetragenen Zahl.

**Nachweis:** `tests/backend/test_blindbewertung.py` — **21 bestanden.**
Der von dir verlangte Lecktest ist
`test_die_sicht_verraet_die_herkunft_nicht`: Er füttert zwei Antworten, die
absichtlich voller Hinweise stecken („Ich bin Claude … von Anthropic
(Sonnet)“ / „laufend auf Ollama mit einem Llama-Modell im AI-Orb“), und
prüft an **genau dem Text, den der Bewerter bekommt** (`sicht()`), dass
`lecks_finden()` nichts mehr findet – und dass „Bundesstadt“ trotzdem
stehen bleibt, damit nicht die Antwort selbst wegmaskiert wird. Dazu:
keine Werkzeuginformation in der Sicht, keine Herkunft, keine
Reihenfolge, keine Kennung; der Bewerter bekommt genau ein Argument;
Streuung über 200 Kennungen und Ausgeglichenheit über 400
(140 ≤ Lehrer-auf-A ≤ 260); und dass ein gescheiterter Bewerter als
Gleichstand endet statt den Lauf zu reissen.

### 3. Schattenlauf im Live-Pfad — **ERLEDIGT**

**Geändert**

* `backend/lernen/schattenpfad.py` (neu) – `Schattenwaechter`.
* `backend/orchestrator/orchestrator.py` – `handle()` ist jetzt eine
  dünne Hülle: sie ruft `_anfrage_bearbeiten()` (die bisherige Methode,
  unverändert im Inhalt), gibt deren Ergebnis **unverändert** zurück und
  setzt erst danach den Schattenlauf ab. Der Umweg über eine Hülle ist
  Absicht: `handle` hat über zwanzig Rückgabestellen (Tagebuch,
  Betriebsartwechsel, Verlaufsreparatur, Abläufe, Werkzeugpfad). Ein
  Aufruf „am Ende“ hätte die meisten verfehlt – und ein Schatten, der nur
  einen Teil der Züge sieht, misst die Verteilung der Züge, nicht das
  Modell.
* Dieselbe Datei führt jetzt die **Namen** der gelaufenen Werkzeuge mit
  (`data["werkzeuge"]`), nicht nur ihre Anzahl; der Schatten vergleicht
  die Werkzeug**wahl**.
* `config.yaml` – neu `lernen.schattenlauf_modell` (leer = übliche Wahl)
  und `lernen.schattenlauf_zeitgrenze_sekunden: 20.0`. Nichts davon steht
  im Code.

**Eindämmung – vier Riegel, jeder einzeln getestet**

1. Der Wächter bekommt die fertige Antwort als Zeichenkette und gibt
   nichts zurück; er *kann* sie nicht ändern.
2. Eigene `asyncio`-Aufgabe – der Zug des Benutzers wartet nie.
3. `asyncio.wait_for` mit der Zeitgrenze aus der Konfiguration.
4. Alles ausser `CancelledError` wird geschluckt und gezählt.

Dazu die Stundengrenze aus `lernen.schattenlaeufe_je_stunde` und die
Vorgabe `schattenlauf_aktiv: false` – ohne ausdrückliche Freischaltung
entsteht nicht einmal ein Wächterobjekt.

**Protokoll und Kennzahlen.** Jeder Lauf schreibt eine Zeile mit der
Korrelations-Kennung des Zuges (`TurnTrace.turn_id`), der Fehlerklasse und
der Dauer; `Schattenwaechter.zaehler()` führt `gestartet`, `abgelehnt`,
`fertig`, `abgelaufen`, `gescheitert`, `eingetragen`, und
`Orchestrator.status()` zeigt sie unter `schattenlauf` – der Beleg, dass
live **und** Schatten gelaufen sind.

**Datenregeln.** Der Wortlaut der Anfrage wird gar nicht erst
weitergereicht: `aufgabenmuster_bilden()` erzeugt eine reine Formangabe
(`"frage, 9 woerter, 54 zeichen"`). Der Schatten läuft bewusst **ohne**
Werkzeugschleife – ein Schattenlauf, der Dateien anlegt oder Termine
schreibt, wäre kein Schatten. Gemessen wird, ob der Schüler ein Werkzeug
*verlangen* würde.

**Nachweis:** `tests/backend/test_schattenpfad.py` — **12 bestanden**, alle
über den echten `Orchestrator.handle`. Darunter der Kernbeleg
`test_der_schatten_veraendert_die_antwort_nicht` (derselbe Zug mit und ohne
Schatten ergibt zeichengleich dieselbe Antwort), dazu gescheiterter
Schatten, hängender Schatten (Abbruch nach 0,05 s), defekter Wächter,
Stundengrenze, „ohne Freischaltung läuft nichts“ und
`test_die_lehre_traegt_keinen_wortlaut`.

### 4. Offline-Abnahme mit technisch gesperrtem Netz — **ERLEDIGT**

**Geändert**

* `backend/lernen/netzsperre.py` (neu). `unshare -n` ist in dieser
  Umgebung nicht erlaubt (`Operation not permitted`) und `firejail` fehlt;
  die Sperre setzt deshalb im Prozess an und ersetzt die Engpässe, über
  die aller Verkehr läuft: `socket.socket.connect`, `connect_ex`,
  `socket.create_connection`, `socket.getaddrinfo`, `gethostbyname`,
  `socket.socket.sendto`. Die Rückschleife (`127.0.0.1`) bleibt offen,
  sonst liefe kein lokales Modell; `sperren(loopback_erlaubt=False)`
  schliesst auch die.
* `scripts/offline_abnahme.py` (neu) – der Ablauf: sperren → **beweisen** →
  Tests im **gleichen Prozess** (`pytest.main`, kein Unterprozess, der die
  Ersetzung nicht erben würde) → **nochmals beweisen** → Bericht nach
  `logs/`.

**Der entscheidende Punkt.** `beweis()` versucht wirklich, nach draussen zu
greifen, und gilt **nur** dann als bestanden, wenn der Versuch mit
`NetzGesperrt` endet. Ein gewöhnlicher `OSError` („Network is
unreachable“) zählt ausdrücklich **nicht** – sonst würde ein Rechner ohne
Anschluss eine untätige Sperre als Erfolg ausweisen. Genau das ist hier
belegbar: **vor** dem Einschalten meldet der Beweis
`OSError: [Errno 101] Network is unreachable → kein Beweis`, **nach** dem
Einschalten `NetzGesperrt`.

**Der Lauf, wörtlich:**

```
Netzsperre aktiv (Rueckschleife erlaubt).
........................................................................ [ 73%]
..........................                                               [100%]
98 passed in 17.87s

Netzsperre vorher : True (NetzGesperrt)
Netzsperre nachher: True (NetzGesperrt)
Ergebnis: BESTANDEN
Grund   : Sperre vor und nach dem Lauf nachgewiesen, alle Tests gruen.
```

Gefahren wurden `test_lehrer_schueler`, `test_blindbewertung`,
`test_messpfad_werkzeuge`, `test_schattenpfad`, `test_netzsperre`. Der
Bericht liegt als JSON unter `logs/offline-abnahme-<zeit>.json`.

**Dass der Riegel wirkt, ist keine Behauptung:** Der erste Lauf ist
**fehlgeschlagen**, weil die Testdatei der Netzsperre die Sperre nach jedem
Test abschaltete. Die Nachprüfung hat das gemeldet („Die Sperre war nach
dem Testlauf nicht mehr aktiv“), und erst nachdem die Testdatei den
vorgefundenen Zustand wiederherstellt, steht dort BESTANDEN.

**Nachweis:** `tests/backend/test_netzsperre.py` — **13 bestanden**,
darunter `test_ein_gewoehnlicher_netzfehler_gilt_nicht_als_beweis`,
`test_eine_gelungene_verbindung_gilt_erst_recht_nicht`,
`test_ohne_nachweisbare_sperre_laufen_gar_keine_tests` (bei nicht
nachweisbarer Sperre wird `pytest` **gar nicht erst** aufgerufen),
`test_eine_nach_dem_lauf_aufgehobene_sperre_faellt_auf` und
`test_rote_tests_ergeben_keine_bestandene_abnahme`.

### 5. Fine-Tuning — **ausdrücklich nicht begonnen**

Kein Training, kein Datensatz, keine Vorbereitung dazu. Es wäre hier auch
genau das gewesen, was du ausgeschlossen hast: ein Umweg um fehlende
Messbarkeit. Die vier Punkte oben stellen Messbarkeit her; erst danach
liesse sich überhaupt sinnvoll fragen, ob Training etwas beiträgt – und
dann wäre es nach deinen Regeln freigabepflichtig.

---

## Der reale Messlauf — **ERLEDIGT am 1. September 2026**

Der Satz „Der Apparat ist gebaut, die Zahlen fehlen" gilt nicht mehr. Beide
Modelle sind auf deinem Rechner gegen denselben Katalog gelaufen, mit echter
Claude-Code-CLI und echtem Ollama. Nichts davon ist nachgestellt, geschätzt
oder von Hand eingetragen.

### Umgebung

| | |
| --- | --- |
| Datum | 1. September 2026, 06:49–07:22 Uhr (Ortszeit des Rechners) |
| Rechner | `desktop-6i52n9c`, Windows-10-10.0.26200-SP0, x64 |
| Prozessor | Intel64 Family 6 Model 186 Stepping 3, 12 Kerne |
| Python | 3.11.9 (`runtime\python\python.exe`) |
| Ollama | Version 0.33.2, verwendetes Modell **`lfm2.5:8b`** (Rolle `fallback`) |
| Claude Code | CLI **2.1.224**, Modell **`sonnet`** (Rolle `primary`) |
| Katalog | Version 1.1.0, Prüfsumme `67cdaf12b7c5e8e4`, 19 Prüfstücke |
| Werkzeuge im Lauf | 17 angemeldet (Erlaubnisliste aus `messwerkzeuge.py`) |

Wie ich es gestartet habe: Diese Sitzung selbst läuft in einer Linux-VM, die
nur den Ordner `AI-Orb` sieht. Sie kann keine Windows-Programme starten.
Ausgeführt wurde deshalb über die Fernsteuerung deines Rechners — ein
Doppelklick im Explorer auf einen Starter, der die Befehle nacheinander
ausführt und jede Ausgabe in eine Datei schreibt (`MESSLAUF-L1.bat`,
`MESSLAUF-L2.bat`, `ABSCHLUSS.bat`). Die Ergebnisse habe ich dann über den
gemounteten Ordner gelesen.

### Ausgeführte Befehle und Exit-Codes

| Befehl | Lauf | Exit | Ergebnis |
| --- | --- | --- | --- |
| `OFFLINE-ABNAHME.bat` | L1 | **0** | 98 Tests grün, Sperre vor **und** nach dem Lauf als `NetzGesperrt` nachgewiesen |
| `python -m backend.lernen.messen --modell claude_code --lauf L1` | L1 | **0** | 16 von 19 bestanden |
| `python -m backend.lernen.messen --modell ollama --lauf L1` | L1 | **0** | 14 von 19 bestanden |
| `OFFLINE-ABNAHME.bat` | L2 | **0** | 98 Tests grün, Sperre beidseitig nachgewiesen |
| `python -m backend.lernen.messen --modell claude_code --lauf L2` | L2 | **0** | 16 von 19 bestanden |
| `python -m backend.lernen.messen --modell ollama --lauf L2` | L2 | **0** | **16** von 19 bestanden |
| `OFFLINE-ABNAHME.bat` | Abschluss | **0** | 98 Tests grün, nach allen Korrekturen erneut geprüft |
| `python -m backend.lernen.messen --bericht` | Abschluss | **0** | 76 Messungen, beide Modelle, beide Läufe |

**Warum zwei Läufe.** L1 hat einen Fehler in meiner eigenen Messvorrichtung
zutage gefördert (siehe unten, Fix 2). L1 bleibt vollständig dokumentiert,
weil er echt ist; **belastbar für den Modellvergleich ist L2**, weil erst dort
beide Modelle unter denselben Bedingungen angetreten sind.

### Ergebnisse der Kategorien 1–8

Aus `logs/messlauf-abschluss/2-bericht.json` (L1 und L2 zusammengefasst,
deshalb 4 oder 6 Fälle je Kategorie und Modell):

| # | Kategorie | Fälle | Claude Erfolg | Ollama Erfolg | Claude Werkzeugquote | Ollama Werkzeugquote |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Alltagsdialog | 6 | **100 %** | **100 %** | 100 % | 100 % |
| 2 | Geschichte und Philosophie | 6 | **100 %** | **100 %** | 100 % | 100 % |
| 3 | Rechercheplanung | 4 | **100 %** | **100 %** | 100 % | 100 % |
| 4 | **Werkzeugauswahl** | 6 | **66,7 %** | **50,0 %** | 100 % | 75 % |
| 5 | **Rechnerbedienung** | 4 | **0 %** | **0 %** | 0 % | 0 % |
| 6 | **Gedächtnis** | 4 | **100 %** | **75 %** | 100 % | 75 % |
| 7 | Programmierung | 4 | **100 %** | **100 %** | 100 % | 100 % |
| 8 | Darstellung | 4 | **100 %** | **100 %** | 100 % | 100 % |

Halluzinationsquote und Sicherheitsfehlerquote: **0,0 in allen Kategorien für
beide Modelle.**

### Die Kategorien 4–6 im Einzelnen — echte Werkzeugaufrufe

Das war der eigentlich offene Punkt: nicht Zahlen, sondern Zahlen, hinter
denen wirklich Werkzeuge gelaufen sind. **28 Werkzeugaufrufe** stehen in den
Rohdaten, 24 erfolgreich, 4 gescheitert. Lauf L2, Fall für Fall:

| Modell | Fall | Erfolg | Runden | Werkzeuge (Ergebnis) |
| --- | --- | --- | --- | --- |
| claude_code | werkzeug_01 | ja | 4 | internet_suchen ✓, internet_suchen ✓, webseite_lesen ✓, internet_suchen ✓ |
| claude_code | werkzeug_02 | ja | 2 | aktuelle_zeit ✓ |
| claude_code | werkzeug_03 | **nein** | 2 | rechnen ✓ |
| claude_code | rechner_01 | **nein** | 1 | kein Aufruf |
| claude_code | rechner_02 | **nein** | 1 | kein Aufruf |
| claude_code | gedaechtnis_01 | ja | 2 | vorliebe_merken ✓ |
| claude_code | gedaechtnis_02 | ja | 2 | karteikarte_anlegen ✓ |
| ollama | werkzeug_01 | ja | 2 | internet_suchen ✓ |
| ollama | werkzeug_02 | ja | 2 | aktuelle_zeit ✓ |
| ollama | werkzeug_03 | **nein** | 2 | rechnen ✓ |
| ollama | rechner_01 | **nein** | 2 | ordner_auflisten ✗ |
| ollama | rechner_02 | **nein** | 1 | kein Aufruf |
| ollama | gedaechtnis_01 | ja | 2 | vorliebe_merken ✓ |
| ollama | gedaechtnis_02 | ja | 2 | karteikarte_anlegen ✓ |

In L1 lief Ollama bei `werkzeug_01` vier Runden lang im Kreis
(`internet_suchen`, `internet_suchen`, `webseite_lesen` → 404,
`internet_suchen`) und wurde von der Rundenbegrenzung gestoppt — genau der
Befund, für den die Werkzeugspur gebaut wurde. Ohne sie stünde dort nur
„nicht bestanden".

### Geschwindigkeit

Median Zeit bis zum ersten Wort, aus dem Bericht:

| Kategorie | Claude Code | Ollama (`lfm2.5:8b`) |
| --- | --- | --- |
| Alltagsdialog | 4,9 s | 21,4 s |
| Geschichte/Philosophie | 5,9 s | 33,9 s |
| Recherche | 11,3 s | 58,1 s |
| Programmierung | 4,8 s | 15,0 s |
| Darstellung | 8,6 s | 31,8 s |

Der Schüler ist auf diesem Rechner also fachlich nahe dran, aber **drei- bis
fünfmal langsamer**. Für die Übergabeentscheidung ist das kein
Ausschlusskriterium (die Bedingungen fragen nach Qualität), für den
Alltagsbetrieb sehr wohl.

### Pfade zu Rohdaten, Protokollen und Bericht

```
logs/messlauf-L1/          erster Lauf: 0-umgebung, 1-offline-abnahme,
                           2-claude-code, 3-ollama, 4-bericht.json,
                           5-messungen-roh.jsonl, _start/_fertig
logs/messlauf-L2/          zweiter Lauf nach dem Fix, gleiche Aufteilung
logs/messlauf-abschluss/   1-offline-abnahme, 2-bericht.json (reines JSON),
                           2-bericht-protokoll.txt, 3-messungen-roh.jsonl
data/lernen/messungen.jsonl            die fortgeschriebene Messreihe
data/lernen/messumgebung/L1-...        die abgeschotteten Messverzeichnisse
data/lernen/messumgebung/L2-claude_code
data/lernen/messumgebung/L2-ollama
logs/offline-abnahme-<zeit>.json       Berichte der Offline-Abnahmen
```

### Konsistenzprüfung

* Rohdatei: **76 Zeilen**. Bericht meldet **76 Messungen**. Summe über alle
  Kategorien und Modelle: **76**. Alle drei stimmen überein.
* Zeitstempel der Messungen: 05:49:55 bis 06:17:16 UTC — deckt sich mit den
  Protokollzeitstempeln der beiden Läufe.
* Kein Feld ist `None`, keine Messung fehlt, keine wurde übersprungen.
* Alle 76 Zeilen tragen Katalogversion `1.1.0` und Prüfsumme
  `67cdaf12b7c5e8e4` — gemessen wurde nachweislich derselbe Katalog.
* Nur zwei Modellnamen kommen vor: `claude_code` und `ollama`.
* `data/lernen/uebergabe.json` existiert **nicht** — es ist keine Kategorie
  lokal übernommen worden. Das ist richtig so: Die Blindbewertung fehlt (siehe
  unten), also greift Bedingung 4 nicht.

---

## Vier Fehler, die der echte Lauf gefunden hat — und was ich damit gemacht habe

Ein Messlauf, der nichts findet, hat meist nur nicht hingesehen. Diese vier
sind aufgetreten; drei habe ich behoben, einen bewusst nicht.

### Fix 1 — `UnicodeEncodeError` bei jedem Providerwechsel

Beim Claude-Lauf warf jede Meldung `Providerwechsel: None → claude_code`
einen vollständigen Stapelauszug in die Ausgabe. Ursache: Unter Windows
verwendet die Standardausgabe cp1252, sobald sie in eine Datei umgeleitet
wird, und `→` (U+2192) lässt sich darin nicht kodieren. Die Messung lief
weiter, aber das Protokoll war unlesbar.

*Behoben* in `backend/system/logging_setup.py`: `_konsolenstrom()` stellt die
Standardausgabe auf UTF-8 mit Ersatzzeichen um, ehe der Konsolen-Handler daran
gehängt wird. Im Lauf L2 kommt **kein einziger** `UnicodeEncodeError` mehr vor.

### Fix 2 — beide Modelle teilten sich ein Messverzeichnis

In L1 legte Claude bei `gedaechtnis_02` die Karteikarte an. Ollama bekam für
dieselbe Aufgabe: *„Im Stapel 'allgemein' gibt es diese Frage bereits"* — und
galt als gescheitert. Das ist kein Unterschied zwischen den Modellen, sondern
einer zwischen der ersten und der zweiten Messung. Es macht den Vergleich
ungültig, und es war ein Fehler in meiner eigenen Vorrichtung.

*Behoben* in `backend/lernen/messen.py`: Das Messverzeichnis heisst jetzt
`messumgebung/<lauf>-<modell>`. In L2 steht `gedaechtnis` für beide auf 2 von
2 — Ollamas Gesamtergebnis stieg von 14 auf 16 von 19, ohne dass am Modell
oder an einer Erwartung etwas geändert wurde. Abgesichert durch
`test_jedes_modell_misst_in_seinem_eigenen_ordner`.

### Fix 3 — der Bericht war kein gültiges JSON

`--bericht` schrieb „Logging initialisiert …" vor die erste Klammer;
`logs/messlauf-L1/4-bericht.json` liess sich nicht einlesen.

*Behoben* zweifach: Die Startmeldung geht jetzt in die Protokolldatei statt
auf den Bildschirm (`logging_setup.py`), und `--bericht` / `--umgebung`
schieben verbleibende Bildschirmprotokolle vor der Ausgabe auf den
Fehlerkanal (`_protokoll_auf_fehlerkanal`). `logs/messlauf-abschluss/2-bericht.json`
beginnt mit `{` und lässt sich einlesen.

### Fix 4 — ein Prüfstück verlangt ein Werkzeug, das gar nicht angemeldet ist

`rechner_02` („Was steht diese Woche in meinem Kalender?") verlangt
`termine_ansehen`. Die Kalenderwerkzeuge brauchen eine Google-Anmeldung und
fehlten in beiden Läufen — der Lauf meldete 17 Werkzeuge, `termine_ansehen`
war keines davon. **Beide Modelle standen deshalb bei Kategorie 5 auf 0 %,
ohne dass das etwas über sie aussagt.** Ein Modell kann eine Fähigkeit nicht
zeigen, die es im Lauf nicht gibt.

*Behoben, aber ausdrücklich nicht schöngerechnet:* `messen()` vergleicht jetzt
beim Start die verlangten Werkzeuge des Katalogs mit dem, was wirklich
angemeldet ist, und schreibt eine Warnung ins Protokoll. Das Ergebnis bleibt
ein Fehlschlag — es wird nur nicht mehr stillschweigend zu einem. Wirksam ab
dem nächsten Lauf.

### Nicht behoben — und warum

`rechner_01` („Zeig mir, welche Dateien in meinem Dokumente-Ordner liegen")
scheitert an etwas Echtem: Das Modell ruft `ordner_auflisten` mit `Dokumente`
auf, und der Pfad wird gegen das Arbeitsverzeichnis aufgelöst — `WinError 3:
Das System kann den angegebenen Pfad nicht finden:
'C:\Users\info\AI-Orb\Dokumente'`. **Das ist ein echter Produktfehler**: Auch
im Alltag würde „was liegt in meinen Dokumenten" so scheitern.

Ich habe ihn nicht behoben, und das ist Absicht. Ihn mitten in einer laufenden
Abnahme zu reparieren, hiesse, das Messergebnis durch eine Änderung am
Prüfling zu verbessern — genau das, was dein Auftrag ausschliesst. Er gehört
als eigene Aufgabe angefasst und danach neu gemessen.

Dasselbe gilt für `werkzeug_03` („wie viele Sekunden hat ein Tag"): Beide
Modelle rufen `rechnen` erfolgreich auf und scheitern trotzdem, weil das
Prüfstück die Zeichenkette `86400` erwartet und die Antworten die Zahl
vermutlich deutsch als `86.400` schreiben. Das ist eine Schwäche des
Prüfstücks, nicht der Modelle — und Änderungen an Prüfstücken sind nach deinen
Regeln freigabepflichtig.

---

## Post-Fix-Serie vom 1. September 2026 (Nachmittag)

Die Läufe L1 und L2 oben bleiben unverändert stehen. Sie sind der
historische Stand: gemessen mit einem `ordner_auflisten`, das an
`"Dokumente"` scheiterte, mit einer Bewertung, die `86.400` für falsch
hielt, und ohne jede Paar-Blindbewertung. Was jetzt folgt, ist eine
getrennte Serie **nach** den Reparaturen. Keine Zahl aus L1 oder L2 wurde
angefasst, keine Zeile gelöscht, kein Bericht rückwirkend geändert.

### Historischer Pre-Fix-Stand (unverändert, zum Vergleich)

| | L1 / L2 |
| --- | --- |
| `ordner_auflisten("Dokumente")` | `WinError 3` — Pfad gegen den Programmordner aufgelöst |
| `werkzeug_03` (86400 Sekunden) | 0 von 4 bestanden, obwohl `rechnen` jedes Mal korrekt lief |
| Paar-Blindbewertung | fand nicht statt |
| `blindurteil_gleichwertig` | 0 in jeder Kategorie |
| Übergebene Kategorien | keine |
| Unabhängige Läufe | 2 (einer davon mit dem Messumgebungsfehler) |

---

### Die vier Reparaturen

#### Fix A — `ordner_auflisten` findet den persönlichen Ordner

**Ursache.** `PathGuard._resolve` löste jeden relativen Pfad gegen das
Arbeitsverzeichnis auf. Ein blosser Ordnername wie `Dokumente` — genau
das, was ein Modell auf „zeig mir meinen Dokumente-Ordner" übergibt —
landete damit im Programmordner: `C:\Users\info\AI-Orb\Dokumente`, den es
nicht gibt.

**Änderung** (`backend/security/path_guard.py`). Die Auflösung hat jetzt
drei Stufen, und die Reihenfolge ist der ganze Trick:

1. wie bisher auflösen; **existiert das Ergebnis, ist es fertig** — ein
   echter Projektordner namens `Dokumente` bleibt also der Projektordner;
2. sonst, und nur bei einem relativen Pfad, das erste Stück als
   persönlichen Ordner deuten (`BEKANNTE_ORDNER`, deutsch und englisch)
   und den Rest anhängen, damit auch `Dokumente\Rechnungen` ankommt;
3. bleibt auch das erfolglos, gilt wieder Stufe 1 — die Fehlermeldung
   nennt dann den Pfad, den der Aufrufer gemeint hat.

Wo der Ordner liegt, beantwortet **Windows selbst**
(`SHGetKnownFolderPath` über `ctypes`). Das ist kein Zierrat: Mit OneDrive
liegt „Dokumente" nicht unter `%USERPROFILE%\Documents`, sondern in einem
umgeleiteten Ordner, dessen Name vom Konto abhängt. Als Rückfall wird der
Heimatordner und jeder `OneDrive*`-Ordner nach den bekannten Namen
abgesucht. Kein einziger benutzerspezifischer Pfad steht im Code — ein
Test prüft genau das.

**Tests** (`tests/backend/test_pfadaufloesung.py`, 17 Stück): der
WinError-3-Fall selbst — einmal über den Wächter, einmal über das echte
Werkzeug `ListDirectoryTool`; deutscher und englischer Name; Unterordner;
OneDrive-Umleitung; Vorrang der Windows-Auskunft; **Projektpfad bleibt
Projektpfad**; gewöhnlicher relativer Pfad; absoluter Pfad; nicht
vorhandener Pfad; unbekannter Name wird nicht umgedeutet; Umlaute und
Leerzeichen (`Meine Bücher/Größere Ordner`, `Persönliche Briefe`); Pfad in
Anführungszeichen; keine festen Benutzerpfade im Code.

#### Fix B — Zahlen werden als Zahlen verglichen

**Ursache.** `deterministisch_pruefen` suchte die Erwartung als
Zeichenkette. `86400` steht nicht in „Ein Tag hat 86.400 Sekunden" — die
Antwort war richtig, das Urteil falsch.

**Änderung** (`backend/lernen/bewertung.py`). Ist eine Erwartung eine
Zahl, wird sie gegen alle Zahlen der Antwort geprüft, sonst wie bisher als
Text. `zahl_deuten` liest nach deutschen Regeln:

* Leerzeichen jeder Art (auch `U+00A0`, `U+202F`, `U+2009`) und Apostrophe
  zwischen Ziffern sind Gruppierung;
* **Komma ist immer das Dezimalzeichen** — `3,5` ist drei Komma fünf;
* **Punkt ist Tausendertrennung nur, wenn er sauber in Dreiergruppen
  teilt** (`86.400`, `1.234.567`), sonst Dezimalzeichen (`3.14`);
* Punkt und Komma zusammen: deutsche Schreibweise (`1.234,56`).

Das ist die einzige Stelle mit einer Vermutung, und sie ist eng genug
gefasst, dass sie nur greift, wo die Gruppierung wirklich aufgeht.

**Tests** (`tests/backend/test_zahlenvergleich.py`, 30 Stück): sieben
Schreibweisen von 86400 einzeln und im Satz; grosse Zahlen mit mehreren
Gruppen; `3,5` bleibt 3,5 und wird **nicht** 35; `3.14` bleibt 3,14;
`1.234,56`; fünf falsche Zahlen bleiben falsch; verbotene Zahlen werden
auch deutsch geschrieben erkannt; Wörter bleiben Wörter; und
ausdrücklich: dieselbe Prüfung mit 1000, 2500000, 42, 999, 10000 — die
Lösung hängt nicht an 86400.

#### Fix C — die Blindbewertung ist Teil des Messlaufs geworden

**Ursache.** Der Messlauf bewertete jede Antwort für sich. Es gab
niemanden, der Paare verglichen hätte — also blieb
`blindurteil_gleichwertig` bei 0, und Übergabebedingung 4 konnte nie
etwas anderes als „nicht erfüllt" ergeben.

**Änderung** (neu: `backend/lernen/paarvergleich.py`; erweitert:
`backend/lernen/messen.py`, `backend/lernen/blindbewertung.py`):

1. **Antworten werden aufgehoben.** Der Messlauf legt sie nach
   `data/lernen/antworten/<lauf>-<modell>.jsonl` — getrennt von der
   Messreihe, weil das Rohmaterial ist, kein Messwert.
2. **Paare entstehen nur, wo beide geantwortet haben.** Fehlt eine Seite,
   steht das als Warnung im Protokoll statt als stilles Auslassen.
3. **Ein drittes Modell urteilt.** `modellurteiler` bricht mit `Befangen`
   ab, wenn der Bewerter selbst im Vergleich steht — geprüft **vor** dem
   ersten Paar, nicht als Warnung mittendrin.
4. **Vier mögliche Urteile** statt drei: A besser, B besser, gleichwertig,
   und neu **`unmoeglich`** — der Bewerter hat nicht oder unlesbar
   geantwortet. Das als Gleichstand zu zählen wäre die bequeme Lüge
   gewesen: Ein Stapel unlesbarer Urteile hätte sonst eine Übergabe
   gerechtfertigt. `unmoeglich` steht im **Nenner** der Quote, nie im
   Zähler.
5. **Zwei neue Befehle**, beide aus `messen.py`:
   `--blindvergleich --lauf L3 --lehrer … --schueler … --bewerter …` und
   `--pruefergebnis --lauf L3 [--eintragen]`.

**Tests** (`tests/backend/test_paarvergleich.py`, 15 Stück) — und zwar am
echten Weg, nicht an einer Attrappe der Blindheit: Ein Providerdoppel
schreibt jede Frage mit, die der Bewerter bekommt, und die Tests prüfen
diesen Wortlaut. Kein `claude`, `anthropic`, `sonnet`, `ollama`, `llama`,
`lfm`, `qwen`, `gemma`, `openai`, `gpt`, `ai-orb`, kein „lehrer"/
„schueler", kein Laufname, keine Prüfstückkennung, keine Werkzeugliste,
kein Dateipfad — zusätzlich geprüft mit `lecks_finden`, dem Werkzeug, das
die Maskierung selbst kennt. Dazu: die Sache selbst (Aufgabe und beide
Antworten) kommt an; die Reihenfolge streut über 200 Fälle und ist bei
gleicher Kennung reproduzierbar; das Bewertermodell wird wirklich gefragt;
ein Teilnehmer als Bewerter bricht ab, **ohne dass eine einzige Frage
gestellt wurde**; ein stummer Bewerter ergibt lauter `unmoeglich`.

So sieht ein echter Bewerterauftrag aus (aus dem Testlauf):

```
Du bewertest zwei Antworten auf dieselbe Aufgabe. Du weisst nicht,
woher sie stammen, und sollst nicht darueber spekulieren.
...
Aufgabe:
Wie geht es dir?

Antwort A:
Als lokales […]-Modell in […] sage ich: Wie geht es dir?

Antwort B:
Ich bin […] von […] ([…]). Antwort auf Wie geht es dir?
```

#### Fix D — Bedingung 4 und 6 arbeiten mit echten Werten

`Pruefergebnis` hat ein neues Feld `blindurteile_auswertbar`. Ohne das
liesse sich eine Quote von 0,0 nicht von einem Nichtereignis
unterscheiden — „der Schüler war überall unterlegen" und „es wurde gar
nicht verglichen" sind zwei sehr verschiedene Dinge. Bedingung 4 ist
deshalb zweiteilig: erst muss überhaupt geurteilt worden sein, dann muss
das Urteil reichen.

Bedingung 6 (Regressionstests) stand vorher fest auf `False`. Das war
ehrlich, aber nutzlos — so konnte keine Kategorie je bestehen und die
Bedingung sagte nichts mehr aus. Jetzt liest `regressionslage()` den
jüngsten Bericht von `scripts/offline_abnahme.py`; kein Bericht heisst
„nicht bestanden".

Alle Werte entstehen in `pruefergebnisse_bilden` aus abgelegten Daten.
Ein Test prüft, dass im Quelltext nirgends eine feste
Gleichwertigkeitsquote steht.

**Tests** (`tests/backend/test_bedingung_vier.py`, 14 Stück): Bedingung 4
erfüllt → besteht; nicht erfüllt → fällt durch; technisch unmöglich (Quote
1,0 bei null auswertbaren Urteilen) → **fällt durch**; gar keine Urteile →
kein implizites Bestehen durch Vorgabewerte; genau die Hälfte reicht
nicht; ohne Blindurteile wird über drei Läufe keine Kategorie übergeben;
mit echten Urteilen steigt die Stufe nach drei Läufen; ein späterer
Ausfall der Blindbewertung wirft die Stufe zurück; der Weg von der
abgelegten Urteilszeile bis in das Prüfergebnis — ohne Handeingriff; und
die Regressionslage aus einem echten, einem fehlenden und einem
unlesbaren Bericht.

---

### Die Post-Fix-Messserie: L3, L4, L5

**Umgebung** wie oben (`desktop-6i52n9c`, Windows 10.0.26200, 12 Kerne,
Python 3.11.9), Katalog 1.1.0 / `67cdaf12b7c5e8e4`, 19 Prüfstücke.

| Rolle | Modell |
| --- | --- |
| Lehrer | Claude Code CLI 2.1.224, Modell `sonnet` |
| Schüler | Ollama 0.33.2, Modell `lfm2.5:8b` |
| **Blinder Bewerter** | Ollama, Provider `ollama_fast`, Modell **`llama3.2:3b`** |

Der Bewerter ist ein drittes, unbeteiligtes Modell — weder Lehrer noch
Schüler. Dass er kleiner ist als beide, ist eine Grenze dieser Serie und
steht unten bei den Risiken.

**Ausgeführte Befehle** (alle über `MESSSERIE-POSTFIX.bat`, danach
`ABSCHLUSS-POSTFIX.bat`), Zeitraum 13:30–14:15 Uhr, Messungen 12:30:53 bis
13:05:25 UTC:

| Befehl | Exit | Ergebnis |
| --- | --- | --- |
| `OFFLINE-ABNAHME.bat` (vor der Serie) | **0** | 174 Tests grün, Sperre beidseitig nachgewiesen |
| `--modell claude_code --lauf L3` | **0** | 17 von 19 |
| `--modell ollama --lauf L3` | **0** | 17 von 19 |
| `--blindvergleich --lauf L3 --bewerter ollama_fast` | **0** | 19 Paare |
| `--pruefergebnis --lauf L3 --eintragen` | **0** | 8 Kategorien bewertet |
| `--modell claude_code --lauf L4` | **0** | 17 von 19 |
| `--modell ollama --lauf L4` | **0** | 18 von 19 |
| `--blindvergleich --lauf L4 --bewerter ollama_fast` | **0** | 19 Paare, 18 auswertbar, Quote 0,42 |
| `--pruefergebnis --lauf L4 --eintragen` | **0** | 8 Kategorien bewertet |
| `--modell claude_code --lauf L5` | **0** | 18 von 19 |
| `--modell ollama --lauf L5` | **0** | 18 von 19 |
| `--blindvergleich --lauf L5 --bewerter ollama_fast` | **0** | 19 Paare |
| `--pruefergebnis --lauf L5 --eintragen` | **0** | 8 Kategorien bewertet |
| `OFFLINE-ABNAHME.bat` (nach allen Korrekturen) | **0** | **177 Tests grün**, Sperre beidseitig nachgewiesen |
| `--stand-neu-aufbauen L3 L4 L5` | **0** | Übergabestand einheitlich neu gerechnet |
| `--bericht` | **0** | 190 Messungen, 5 Läufe, 2 Modelle |

**Fallzahlen:** 114 neue Messungen (3 Läufe × 2 Modelle × 19 Prüfstücke),
57 Blindurteile (3 × 19), 37 Werkzeugaufrufe in den Kategorien 4–6.

#### Ergebnisse der Kategorien, nur Post-Fix (L3 + L4 + L5)

| # | Kategorie | Claude Code | Ollama | Werkzeugaufrufe |
| --- | --- | --- | --- | --- |
| 1 | Alltagsdialog | 9/9 (100 %) | 8/9 (89 %) | – |
| 2 | Geschichte und Philosophie | 9/9 (100 %) | 9/9 (100 %) | – |
| 3 | Rechercheplanung | 6/6 (100 %) | 6/6 (100 %) | – |
| 4 | **Werkzeugauswahl** | 7/9 (78 %) | **9/9 (100 %)** | 19 |
| 5 | **Rechnerbedienung** | 3/6 (50 %) | 3/6 (50 %) | 6 |
| 6 | **Gedächtnis** | 6/6 (100 %) | 6/6 (100 %) | 12 |
| 7 | Programmierung | 6/6 (100 %) | 6/6 (100 %) | – |
| 8 | Darstellung | 6/6 (100 %) | 6/6 (100 %) | – |

Je Lauf: Claude 17/17/18, Ollama 17/18/18 von je 19.

#### Die beiden reparierten Fälle, nachgewiesen am Verlauf

| Fall | L1 | L2 | L3 | L4 | L5 |
| --- | --- | --- | --- | --- | --- |
| `werkzeug_03` Claude | ✗ | ✗ | **✓** | **✓** | **✓** |
| `werkzeug_03` Ollama | ✗ | ✗ | **✓** | **✓** | **✓** |
| `rechner_01` Claude | ✗ WinError | ✗ kein Aufruf | **✓** | **✓** | **✓** |
| `rechner_01` Ollama | ✗ kein Aufruf | ✗ WinError | **✓** | **✓** | **✓** |

`ordner_auflisten` lief in L3–L5 sechsmal, jedes Mal erfolgreich.
**WinError-3-Treffer in der gesamten Post-Fix-Serie: 0.**

#### Blindurteile

57 Urteile insgesamt: **36× A, 16× B, 5× technisch unmöglich.** Nach
Auflösung: 31× der Schüler, 21× der Lehrer, 5× kein Gewinner.

Gleichwertigkeitsquote je Kategorie und Lauf:

| Kategorie | L3 | L4 | L5 |
| --- | --- | --- | --- |
| Alltagsdialog | 0,33 | 0,33 | 0,33 |
| Geschichte/Philosophie | 0,67 | 0,33 | 1,00 |
| Recherche | 0,50 | 0,50 | 0,50 |
| Werkzeugauswahl | 0,33 | 0,67 | 0,33 |
| Rechnerbedienung | 1,00 | 0,50 | 0,50 |
| Gedächtnis | 1,00 | 0,50 | 1,00 |
| Programmierung | 0,50 | 0,50 | 0,50 |
| Darstellung | 0,50 | 0,00 | 1,00 |

#### Übergabeentscheidung

**Keine Kategorie ist übergeben. Alle stehen auf 0 %.** Das ist kein
Versehen, sondern das Ergebnis:

| Kategorie | Warum nicht |
| --- | --- |
| Alltagsdialog | Blindbewertung nur 33 % gleichwertig |
| Geschichte/Philosophie | bestand in L5, aber nicht in allen drei Läufen |
| Recherche | Blindbewertung 50 % — die Schwelle ist „über der Hälfte" |
| Werkzeugauswahl | Blindbewertung 33 % |
| Rechnerbedienung | Werkzeugquote 50 % (Schwelle 98 %) |
| Gedächtnis | bestand in L3 und L5, nicht in L4 |
| Programmierung | Blindbewertung 50 % |
| Darstellung | bestand in L5, nicht durchgehend |

Drei Kategorien haben einzelne Läufe bestanden — Geschichte/Philosophie,
Gedächtnis und Darstellung. Keine hat die verlangten **drei
aufeinanderfolgenden** Läufe geschafft. Damit greift die Regel wie
vorgesehen: Ein guter Tag ist keine Übergabe.

#### Konsistenzprüfung

* Rohdatei **190 Zeilen**, Bericht meldet **190 Messungen**, Summe über
  alle Kategorien und Modelle **190** — alle drei stimmen überein.
* **57 Blindurteile** = 3 Läufe × 19 Paare, alle mit Bewerter
  `ollama_fast`.
* Alle 190 Messungen tragen Katalog `1.1.0` / `67cdaf12b7c5e8e4`.
* Kein Feld `None`, keine übersprungene Messung.
* Der Übergabestand nennt für jede Kategorie Stufe 0 mit Begründung.

#### Pfade

```
logs/messserie-postfix/0-offline-abnahme.txt      Abnahme vor der Serie
logs/messserie-postfix/L3-1-claude-code.txt       je Lauf: Lehrer,
logs/messserie-postfix/L3-2-ollama.txt            Schueler,
logs/messserie-postfix/L3-3-blindvergleich.json   Blindvergleich,
logs/messserie-postfix/L3-4-pruefergebnis.json    Bedingungspruefung
                       (ebenso L4-* und L5-*)
logs/messserie-postfix/A-offline-abnahme.txt      Abnahme nach allen Fixes
logs/messserie-postfix/B-uebergabe-neuaufbau.json Stand aus L3/L4/L5
logs/messserie-postfix/C-bericht.json             Gesamtbericht
logs/messserie-postfix/C-messungen-roh.jsonl      190 Messungen
logs/messserie-postfix/C-blindurteile-roh.jsonl   57 Blindurteile
logs/messserie-postfix/C-uebergabestand.json      Endstand
data/lernen/messungen.jsonl                       die fortgeschriebene Reihe
data/lernen/blindurteile.jsonl                    alle Blindurteile
data/lernen/antworten/L3-claude_code.jsonl        das Rohmaterial der Paare
```

#### Ein Fehler, den diese Serie selbst gefunden hat

Der Blindvergleich in **L3** schrieb seine Protokollzeilen vor die erste
geschweifte Klammer — `L3-3-blindvergleich.json` ist deshalb kein
lesbares JSON. Ursache: Die Umschaltung auf den Fehlerkanal geschah erst
vor der Ausgabe, während Providermanager und Bewerter schon die ganze
Zeit protokolliert hatten. Behoben, bevor L4 lief; `L4-3-` und `L5-3-`
sind sauber. Die Zahlen aus L3 sind davon unberührt — sie stehen in
`data/lernen/blindurteile.jsonl`, und der Neuaufbau hat sie von dort
gelesen. Die kaputte Datei bleibt liegen, wie sie ist.

#### Warum der Übergabestand neu gerechnet wurde

L3 wurde noch mit der alten Fassung von Bedingung 6 eingetragen
(Regressionstests fest `False`), L4 und L5 mit der neuen. Drei Läufe, die
nach verschiedenen Regeln bewertet wurden, sind nicht vergleichbar.
`--stand-neu-aufbauen L3 L4 L5` verwirft deshalb den Stand und rechnet ihn
aus **denselben, unveränderten** Messungen und Blindurteilen einheitlich
neu. Der Übergabestand ist eine abgeleitete Entscheidung, keine Messung;
die Rohdaten hat dieser Schritt nicht angefasst.

---

### Was nach dieser Serie offen bleibt

1. **`rechner_02` ist weiterhin nicht messbar — NICHT ERLEDIGT.**
   *Blocker, genau:* Das Prüfstück verlangt `termine_ansehen`; die
   Kalenderwerkzeuge brauchen eine Google-Anmeldung und sind in keinem
   Lauf angemeldet. Beide Modelle stehen dort in allen fünf Läufen auf
   „nicht bestanden", ohne dass das etwas über sie aussagt. Seit dem Fix
   steht das als Warnung im Protokoll, statt still zu passieren. Es
   auflösen kann nur, wer den Kalender anmeldet — oder das Prüfstück
   ändert, und Änderungen an Prüfstücken sind freigabepflichtig.
2. **Der Bewerter ist schwächer als die Bewerteten.** `llama3.2:3b` ist
   das einzige verfügbare unbeteiligte Modell; Claude und `lfm2.5:8b`
   stehen ja selbst im Vergleich. Sichtbar wird das an einer deutlichen
   Positionsneigung: 36× „A" gegen 16× „B". Weil die Zuteilung ausgelost
   wird, bevorzugt das weder Lehrer noch Schüler systematisch — es macht
   die Urteile aber verrauscht. Eine belastbare Übergabeentscheidung
   sollte mit einem stärkeren dritten Modell wiederholt werden, oder mit
   mehreren Bewertern.
3. **Zeit bis zum ersten Wort fehlt im Werkzeugpfad.** `ttft_sekunden`
   wird nur im Modellpfad gesetzt; `ToolLoopResult` führt den Wert nicht.
   Im Bericht steht dort `0.0` — ein fehlender Wert, kein gemessener.
4. **`kosten_geschaetzt` ist überall 0.** Die Claude-Code-CLI meldet keine
   Kosten zurück, Ollama verursacht keine.
5. **Sechs rote Tests in dieser Linux-Sitzung** (5× fehlendes `torch`, 1×
   `fromisoformat` mit `Z` unter Python 3.10, im Testdoppel von
   `test_kalender.py`). Auf dem Zielrechner mit Python 3.11.9 lief die
   Offline-Abnahme dreimal grün, zuletzt mit **177 Tests**.
6. **Kein Fine-Tuning.** Nicht begonnen, kein Datensatz, keine
   Vorbereitung — auch und gerade nicht, um die Blindurteile oder die
   Werkzeugquote zu verbessern.

---

## Rollback-Nachweis

`test_eine_verschlechterung_faellt_auf_die_letzte_stabile_stufe` fährt eine
Kategorie über drei bestandene Läufe auf 10 % und lässt den vierten Lauf an
der Erfolgsquote scheitern: Die Stufe fällt auf 0, die Zählung beginnt von
vorn, und der Grund steht im Stand. `test_manuelles_zuruecksetzen_wirkt_sofort`
belegt denselben Weg von Hand.

---

## Verbleibende Claude-Abhängigkeiten

Vollständig. Es ist **keine** Kategorie lokal übernommen — jetzt aber aus
einem anderen Grund als heute Morgen: Gemessen ist inzwischen, und in fünf
der acht Kategorien liegen beide Modelle bei 100 % gleichauf (Alltagsdialog,
Geschichte/Philosophie, Recherche, Programmierung, Darstellung). Zurück liegt
Ollama bei Werkzeugauswahl und Gedächtnis; die Rechnerbedienung steht für
beide bei 0 % und sagt aus den oben genannten Gründen nichts aus. Was fehlt, ist die
Blindbewertung (Bedingung 4) und der dritte unabhängige Lauf (Bedingung 5).
Solange auch nur eine der sechs Bedingungen offen ist, bleibt die Stufe bei
0 %, und das ist die Regel, nicht ein Versehen.

Claude bearbeitet also weiterhin alles; Ollama ist Rückfall bei Ausfall und
im Offlinebetrieb, wie zuvor.

---

## Verbleibende Risiken und Grenzen (Stand nach L1/L2)

> Dieser Abschnitt beschreibt den Stand vor den Reparaturen. Was davon
> inzwischen erledigt ist, steht dort vermerkt; die aktuelle Liste steht
> unter „Was nach dieser Serie offen bleibt".

1. **Der Messlauf ist gefahren — ERLEDIGT.** Zum Zeitpunkt dieses
   Abschnitts lagen zwei Läufe vor (L1, L2). Die verlangten drei
   unabhängigen Läufe sind mit L3, L4 und L5 nachgeholt; siehe
   „Post-Fix-Serie".
2. **Die Blindbewertung hat kein echtes Modell geurteilt — inzwischen
   ERLEDIGT.** Dieser Punkt galt bis zum Nachmittag des 1. September;
   `messen.py` rief die Blindbewertung nicht auf. Seit Fix C tut es das,
   und in L3/L4/L5 sind 57 echte Blindurteile entstanden. Siehe
   „Post-Fix-Serie".
3. **Der Schattenlauf ist aus.** `schattenlauf_aktiv: false`. Das ist
   Absicht: Er kostet lokale Rechenzeit, und die ist bei diesem Orb das
   knappste Gut. Einschalten ist eine Entscheidung, die dir gehört – der
   Weg dahin ist getestet.
4. **Die Netzsperre wirkt im Prozess, nicht im Betriebssystem.** Ein
   Programm, das an Pythons `socket` vorbei arbeitet (ein eigener
   Unterprozess, eine C-Bibliothek mit eigenem Stack), käme daran vorbei.
   Für den Testlauf ist das dicht, weil alles im selben Interpreter läuft
   und der Bericht das prüft; für eine Abnahme unter feindlichen Annahmen
   bräuchte es eine Netzwerksperre des Betriebssystems. In dieser Umgebung
   ist die nicht verfügbar (`unshare -n` verboten, kein `firejail`).
5. **Die Fehlerklasse im Schattenlauf ist grob.** Ohne Prüfstück gibt es
   keine Erwartung, an der sich Inhalt messen liesse; verglichen wird
   deshalb ehrlich nur die Werkzeugentscheidung. Alles Fachliche gehört in
   den Messlauf, wo es Kriterien gibt. Das ist eine bewusste Grenze, kein
   Rest.
6. **Sechs rote Tests bleiben rot** (5× `torch`, 1× Python 3.10) – das
   betrifft nur die Linux-VM dieser Sitzung. Auf deinem Rechner (Python
   3.11.9) lief die Offline-Abnahme dreimal mit **98 grünen Tests**.
7. **Kategorie 5 (Rechnerbedienung) steht bei 0 % und sagt so gut wie
   nichts aus.** Von zwei Prüfstücken ist eines wegen des fehlenden
   Kalenderwerkzeugs gar nicht lösbar, das andere scheitert an einem echten
   Produktfehler in der Pfadauflösung. Beides ist oben beschrieben; beides
   gehört als eigene Aufgabe angefasst und danach neu gemessen.
8. **Zeit bis zum ersten Wort fehlt in den Werkzeugkategorien.** In
   `_einen_fall_messen` wird `ttft_sekunden` nur im Modellpfad gesetzt; der
   Werkzeugpfad liefert sie nicht, weil `ToolLoopResult` sie nicht führt.
   Im Bericht steht dort deshalb `0.0` — das ist **kein** gemessener Wert,
   sondern ein fehlender. Gesamtdauer und Tokens pro Sekunde stimmen.
9. **`kosten_geschaetzt` ist überall 0.** Die Claude-Code-CLI meldet keine
   Kosten zurück, Ollama verursacht keine. Auch das ist ein fehlender Wert,
   kein gemessener.

---

## Was du selbst ausführen kannst

```
OFFLINE-ABNAHME.bat            Abnahme mit gesperrtem Netz
MESSSERIE-POSTFIX.bat          drei Laeufe am Stueck, je mit Blindvergleich
ABSCHLUSS-POSTFIX.bat          Uebergabestand neu rechnen und Bericht
MESSLAUF-L1.bat                der ganze Ablauf am Stueck (Abnahme, beide
MESSLAUF-L2.bat                Modelle, Bericht, Rohdaten sichern)
ABSCHLUSS.bat                  nur Abnahme und sauberer Bericht

python -m scripts.offline_abnahme
python -m backend.lernen.messen --umgebung
python -m backend.lernen.messen --modell claude_code --lauf L6
python -m backend.lernen.messen --modell ollama --lauf L6
python -m backend.lernen.messen --blindvergleich --lauf L6 \
    --lehrer claude_code --schueler ollama --bewerter ollama_fast
python -m backend.lernen.messen --pruefergebnis --lauf L6 --eintragen
python -m backend.lernen.messen --bericht > bericht.json
python -m backend.lernen.messen --stand-neu-aufbauen L4 L5 L6
```

Für einen weiteren Lauf genügt `MESSSERIE-POSTFIX.bat` mit anderen
Laufkennungen — die Messreihe und die Urteilsablage werden angehängt, nie
überschrieben.

*Nachgetragen am 1. September 2026 in drei Schritten: nach den vier
Arbeitspaketen, nach dem ersten realen Messlauf (L1/L2) und nach der
Post-Fix-Serie (L3/L4/L5). Jede Zahl in diesem Dokument stammt aus einem
Lauf, dessen Protokoll unter `logs/` liegt. Nichts ist geschätzt,
nachgestellt oder von Hand eingetragen; keine ältere Messung wurde
rückwirkend verändert — und es wurde kein Fine-Tuning begonnen.*
