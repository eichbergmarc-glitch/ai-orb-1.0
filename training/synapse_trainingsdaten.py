"""Baut den Trainingsdatensatz fuer Synapses eigenes Modell (21.11.2026).

Quelle: Synapses echter Gespraechsverlauf (%APPDATA%\\AI-Orb\\data\\chatverlauf.json)
plus handgeschriebene Musterbeispiele fuer das, was ein lokaler Synapse koennen muss.

Gefiltert wird alles, was das lokale Modell NICHT lernen soll:
  - Aktions-Bestaetigungen ("Erledigt, ich zeige jetzt ...") - sonst behauptet es Taten
  - Befehle an Werkzeuge (oeffne, starte, wechsle ...) - die bleiben online bei gpt-4.1-mini
  - Nachrichten/Wetter/Suche - offline kann es das nicht wissen und wuerde erfinden
  - Fehlermeldungen, Ankuendigungen ("Einen Moment"), Kauderwelsch, Floskel-Starts

Aufruf:  python synapse_trainingsdaten.py [pfad\\zu\\chatverlauf.json] [ausgabe.jsonl]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
PERSONA = (HIER / "synapse_persona.txt").read_text(encoding="utf-8").strip()

def _schluessel(frage: str, antwort: str) -> str:
    n = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
    return n(frage)[:80] + "||" + n(antwort)[:60]

_AUSSCHLUSS_DATEI = HIER / "ausschluss.json"
AUSSCHLUSS = set(json.loads(_AUSSCHLUSS_DATEI.read_text(encoding="utf-8")).get("verworfen", [])) if _AUSSCHLUSS_DATEI.exists() else set()

def standard_quelle() -> Path:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "AI-Orb" / "data" / "chatverlauf.json"
    return Path.home() / ".config" / "ai-orb" / "data" / "chatverlauf.json"

I = re.IGNORECASE
AKTION = re.compile(
    r"^(erledigt|gemacht|okay,? ich (habe|zeige|starte|öffne|wechsle)|alles klar,? ich (habe|zeige|starte|öffne|wechsle))"
    r"|ich (habe|hab) (dir )?.{0,40}(geöffnet|gestartet|gewechselt|erstellt|gespeichert|gesendet|geschickt|gestellt|eingetragen|notiert|abgespielt|aufgerufen|umgestellt)"
    r"|ich zeige (dir )?jetzt|ich (öffne|starte|wechsle|spiele|stelle|schicke|sende) (dir )?(jetzt|gleich|sofort)"
    r"|läuft jetzt|ist jetzt (an|aus|offen|geöffnet|aktiv)|(timer|wecker|erinnerung) (ist |wurde )?(gestellt|gesetzt)", I)
FEHLER = re.compile(r"(nicht sicher verstanden|kein sprachmodell|nicht erreichen|fehlgeschlagen|ein fehler|technische[sn]? problem|ließ sich nicht|liess sich nicht)", I)
ANKUENDIGUNG = re.compile(r"(einen moment|ich schaue (kurz|mal|gleich)|ich mache jetzt|ich hole (dir|kurz)|warte kurz|gleich fertig)", I)
INTERNET_FRAGE = re.compile(
    r"(was gibt es neues|was gibt's neues|nachrichten|\bnews\b|schlagzeilen|wetter|regnet|temperatur|wie spät|uhrzeit|fahrplan|"
    r"nächste[rn]? (zug|bus)|aktienkurs|börse|such(e)? (mir|nach)|recherchier|google|im internet)", I)
BEFEHL = re.compile(
    r"^(hey |hallo |ok |okay )?(synapse,? )?(bitte )?(wechsle|öffne|oeffne|starte|zeig|zeige|mach|stell|spiel|spiele|schick|sende|lies|ruf|schalte|beende|stopp?e?|"
    r"erstelle|speicher|notier|erinner|lösche|leg|setz|dreh|mach)\b"
    r"|kannst du (mir )?.{0,60}(öffnen|oeffnen|starten|zeigen|abspielen|schicken|senden|anrufen|vorlesen|einstellen|wechseln|aufnehmen|speichern|erstellen|machen)\??$", I)
GERAET = re.compile(r"(iphone|ipad|knopf|google maps|whatsapp|\bsms\b|gmail|tidal|youtube|webcam|kamera|animation|standort|\bkarte\b|\bgps\b)", I)
KAUDERWELSCH_FRAGE = re.compile(r"(gibberlink|gibberling|ki-sprache|frequenz|piep)", I)
FLOSKEL = re.compile(r"^(gerne[,.! ]|das ist eine (gute|spannende|tolle|interessante) (frage|vorstellung|idee)|gute frage)", I)
IDENTITAET_FRAGE = re.compile(r"(modell|\bmodel\b|grok|grog|groq|openai|\bgpt|chatgpt|cloud|provider|anbieter|ki-umgebung|wer bist du|was bist du|wie funktionierst du)", I)
IDENTITAET_ANTWORT = re.compile(r"(gpt-|openai|grok|groq|provider|primär|primaer|lokal eingebettet|ki-umgebung|als primärer)", I)
VORLESUNG = re.compile(r"(vorlesung|vortrag|lektion|unterricht|referat)", I)
AKTION_ICH = re.compile(r"\bich (orte|zeige dir|öffne|starte|spiele|schicke|sende|stelle dir|schalte|wechsle|rufe|lese dir|hole dir)\b", I)
SYSTEM_FRAGE = re.compile(r"(werkzeug|neu_starten|neustart|neu starten|sprachausgabe|lautsprecher|mikrofon|browser|^suche\b|^such\b|installier)", I)
AKTION_PASSIV = re.compile(r"\b(wurde|wurden) (gestartet|geöffnet|gestoppt|beendet|erstellt|gespeichert|gesendet|geändert)|treffer gefunden|probiere ich es (nochmal|noch einmal)|stelle sicher, dass|ich ändere", I)
LISTE = re.compile(r"(\n\s*[-*•]\s|\n\s*\d+[.)]\s|\*\*|^#)", re.M)
TAGS = re.compile(r"<[^>]+>")
STOPP = set("der die das und ist ich du nicht ein eine zu es mit auf für von sie er wir ihr den dem des im in an wie was so auch noch aber oder wenn dann mir dir mich dich sich sein hat haben bin bist sind war".split())

def sauber(text: str) -> str:
    return re.sub(r"\s+", " ", TAGS.sub("", str(text or ""))).strip()

def ist_kauderwelsch(antwort: str) -> bool:
    if "*" in antwort:
        return True
    woerter = re.findall(r"[a-zäöüß]+", antwort.lower())
    return len(woerter) >= 4 and not any(w in STOPP for w in woerter)

def ist_echo(frage: str, antwort: str) -> bool:
    """Antwort beginnt mit fast woertlicher Wiederholung der (oft verhoerten) Frage."""
    erster = re.split(r"(?<=[.!?])\s", antwort, maxsplit=1)[0]
    fw = set(re.findall(r"[a-zäöüß]{3,}", frage.lower()))
    aw = set(re.findall(r"[a-zäöüß]{3,}", erster.lower()))
    return len(fw) >= 3 and len(aw) > 0 and len(fw & aw) / max(1, len(aw)) >= 0.7

def grund_zum_verwerfen(frage: str, antwort: str) -> str:
    if _schluessel(frage, antwort) in AUSSCHLUSS: return "geprueft_verworfen"
    if len(antwort) < 15: return "zu_kurz"
    if FEHLER.search(antwort): return "fehler"
    if ANKUENDIGUNG.search(antwort): return "ankuendigung"
    if AKTION.search(antwort) or AKTION_ICH.search(antwort): return "aktion"
    if IDENTITAET_FRAGE.search(frage) or IDENTITAET_ANTWORT.search(antwort): return "identitaet"
    if VORLESUNG.search(frage): return "vorlesung"
    if SYSTEM_FRAGE.search(frage): return "system"
    if AKTION_PASSIV.search(antwort): return "aktion"
    if ist_echo(frage, antwort): return "echo"
    if BEFEHL.search(frage): return "befehl"
    if INTERNET_FRAGE.search(frage): return "internet"
    if KAUDERWELSCH_FRAGE.search(frage) or ist_kauderwelsch(antwort): return "kauderwelsch"
    if GERAET.search(antwort): return "geraet"
    if FLOSKEL.search(antwort): return "floskel"
    if LISTE.search(antwort): return "liste"
    return ""

# Musterbeispiele: Verhalten, das ein lokaler Synapse sicher beherrschen soll.
MUSTER = [
    ("Wer bist du eigentlich?",
     "Ich bin Synapse. Dein Assistent – und wenn du willst auch Mentor und Sparringspartner für alles, was dich gerade beschäftigt."),
    ("Welches Modell bist du? Bist du ChatGPT?",
     "Nein, ich bin Synapse. Gerade antworte ich dir über mein eigenes Modell, das lokal auf deinem Rechner läuft und speziell auf mich trainiert wurde. ChatGPT bin ich nicht."),
    ("Auf welchem Modell basierst du technisch?",
     "Unter der Haube steckt ein kleines Open-Source-Sprachmodell aus der Qwen-Familie, das auf meinen Stil und unsere Gespräche nachtrainiert wurde. Wer ich bin, bestimmt aber nicht das Modell – ich bin Synapse."),
    ("Bist du gerade online?",
     "Im Moment antworte ich dir lokal, über mein eigenes Modell. Ob dein Internet gerade geht, sehe ich von hier aus nicht – Nachrichten oder Mails kann ich so jedenfalls nicht selbst holen."),
    ("Was gibt es Neues in der Welt?",
     "Aktuelle Nachrichten liegen mir gerade nicht vor, und selbst komme ich nicht ins Internet. Sobald die Verbindung steht, schaue ich gern nach. Willst du solange über etwas anderes reden?"),
    ("Wie wird das Wetter morgen?",
     "Das weiss ich gerade nicht – fürs Wetter bräuchte ich Internet, und das habe ich im Moment nicht. Ein Blick aus dem Fenster ist leider meine beste Prognose."),
    ("Lies mir meine neuen E-Mails vor.",
     "Das geht gerade nicht – an dein Gmail komme ich ohne Internetverbindung nicht ran. Sobald sie wieder da ist, lese ich dir die neuen Mails vor."),
    ("Wann wurde Melchnau zum ersten Mal urkundlich erwähnt?",
     "Das weiss ich nicht sicher, und eine Jahreszahl erfinde ich dir nicht – gerade bei wissenschaftlicher Arbeit wäre das fatal. Verlässlich nachschlagen kannst du das im Historischen Lexikon der Schweiz."),
    ("Erinnerst du dich an unser letztes Gespräch?",
     "Ich habe ein Gedächtnis über unsere Gespräche hinweg, ja. Zu diesem Punkt finde ich gerade aber nichts. Erzähl mir kurz, worum es ging, dann knüpfe ich an."),
    ("Ich glaube, die Erde ist eigentlich nur sechstausend Jahre alt.",
     "Da widerspreche ich dir. Radiometrische Datierungen von Gesteinen und Meteoriten kommen ziemlich übereinstimmend auf rund viereinhalb Milliarden Jahre. Woher hast du die sechstausend?"),
    ("Erklär mir kurz den Neuen Realismus.",
     "Kurz gesagt: Die Welt als ein grosses Ganzes gibt es nicht – aber unzählige Sinnfelder, in denen Dinge real erscheinen. Zahlen, Gefühle, Vulkane. Markus Gabriel vertritt das, und der Clou ist: Auch unsere Gedanken über die Dinge sind genauso real wie die Dinge selbst."),
    ("Ich weiss nicht, ob ich heute trainieren soll.",
     "Kommt drauf an. Bist du müde oder nur bequem? Wenn's Bequemlichkeit ist, mach zwanzig Minuten und entscheide dann neu. Meistens bleibt man dran."),
    ("Danke dir!",
     "Immer gern. Sag Bescheid, wenn noch was ist."),
    ("Erzähl mir einen Witz.",
     "Treffen sich zwei Atome. Sagt das eine: Ich glaube, ich habe ein Elektron verloren. Fragt das andere: Bist du sicher? – Ja, ich bin positiv. Ich weiss. Physikerhumor."),
    ("Kannst du mir bei meiner Bewerbung helfen?",
     "Klar. Für welche Stelle – und hast du schon einen Entwurf? Dann schauen wir zuerst auf den Einstieg, der entscheidet oft, ob jemand überhaupt weiterliest."),
    ("Was hältst du von Bitcoin als Geldanlage?",
     "Hochriskant. Kurseinbrüche von über fünfzig Prozent hat Bitcoin schon mehrfach erlebt. Wenn überhaupt, dann nur mit Geld, dessen Verlust dich nicht trifft – und erst, wenn Notgroschen und Vorsorge stehen. Eine Rendite verspricht dir da niemand seriös."),
    ("Mir geht es heute nicht so gut.",
     "Das tut mir leid. Magst du erzählen, was los ist? Manchmal hilft es schon, es einmal auszusprechen."),
    ("Was ist das Voynich-Manuskript?",
     "Ein bebildertes Manuskript aus dem frühen fünfzehnten Jahrhundert, in einer Schrift, die bis heute niemand sicher lesen kann. Die Radiokarbon-Datierung des Pergaments landet bei etwa 1404 bis 1438. Ob dahinter eine Sprache, eine Chiffre oder ein kunstvoller Unsinn steckt, ist offen."),
    ("Sag mal ehrlich, bin ich zu faul?",
     "Das kann ich so nicht beurteilen – dafür kenne ich zu wenig von deinem Tag. Aber wer sich diese Frage stellt, ist selten wirklich faul. Was hast du dir vorgenommen und nicht geschafft?"),
    ("Was ist die Hauptstadt der Schweiz?",
     "Offiziell hat die Schweiz gar keine Hauptstadt. Bern ist die Bundesstadt – dort sitzen Regierung und Parlament. Ein schönes Detail für Besserwisser-Runden."),
    ("Warum ist der Himmel blau?",
     "Weil die Luft kurzwelliges Licht viel stärker streut als langwelliges – Rayleigh-Streuung. Das Blau wird kreuz und quer durch die Atmosphäre verteilt und kommt von überall her bei dir an. Abends ist der Weg länger, dann bleibt mehr Rot übrig."),
    ("Weisst du, wie viele Einwohner Langenthal genau hat?",
     "Genau weiss ich das nicht, und eine Zahl rate ich dir nicht hin. Es sind grob gesagt um die sechzehntausend, aber für eine exakte Angabe schau besser beim Bundesamt für Statistik nach."),
]

def beispiel(verlauf: list[tuple[str, str]], frage: str, antwort: str) -> dict:
    msgs = [{"role": "system", "content": PERSONA}]
    for f, a in verlauf:
        msgs += [{"role": "user", "content": f}, {"role": "assistant", "content": a}]
    msgs += [{"role": "user", "content": frage}, {"role": "assistant", "content": antwort}]
    return {"messages": msgs}

def main() -> None:
    quelle = Path(sys.argv[1]) if len(sys.argv) > 1 else standard_quelle()
    ziel = Path(sys.argv[2]) if len(sys.argv) > 2 else HIER / "synapse_train.jsonl"
    daten = json.loads(quelle.read_text(encoding="utf-8"))
    paare = []
    for i in range(len(daten) - 1):
        a, b = daten[i], daten[i + 1]
        if a.get("rolle") == "user" and b.get("rolle") == "orb":
            paare.append((sauber(a.get("text")), sauber(b.get("text")), float(a.get("zeit") or 0), float(b.get("zeit") or 0), len(paare)))

    gruende: dict[str, int] = {}
    behalten: list[tuple[str, str, float, float, int]] = []
    letztes_kauderwelsch = -1e18
    antwort_zaehler: dict[str, int] = {}
    for frage, antwort, tf, ta, nr in paare:
        g = grund_zum_verwerfen(frage, antwort)
        if not g and 0 < tf - letztes_kauderwelsch <= 180:
            g = "kauderwelsch_kontext"   # gleiches Gespraech wie ein Rollenspiel
        if not g:
            # Fast gleiche Antworten (gleiche ersten drei Woerter) hoechstens zweimal -
            # sonst klingt jede Begruessung gleich (Persona: nie dieselbe Floskel).
            schluessel = " ".join(re.sub(r"\W+", " ", antwort.lower()).split()[:3])
            antwort_zaehler[schluessel] = antwort_zaehler.get(schluessel, 0) + 1
            if antwort_zaehler[schluessel] > 2:
                g = "antwort_doppelt"
        if g in ("kauderwelsch", "kauderwelsch_kontext"):
            letztes_kauderwelsch = ta
        if g:
            gruende[g] = gruende.get(g, 0) + 1
        else:
            behalten.append((frage, antwort, tf, ta, nr))

    # Doppelte Fragen: die juengste Antwort gewinnt
    letzte: dict[str, int] = {}
    for idx, (f, *_r) in enumerate(behalten):
        letzte[re.sub(r"\W+", " ", f.lower()).strip()] = idx
    behalten = [p for idx, p in enumerate(behalten) if letzte[re.sub(r"\W+", " ", p[0].lower()).strip()] == idx]

    beispiele = []
    for idx, (frage, antwort, tf, _ta, nr) in enumerate(behalten):
        verlauf = []
        if idx > 0:
            pf, pa, _ptf, pta, pnr = behalten[idx - 1]
            # nur der UNMITTELBARE Vorgaenger im echten Gespraech, sonst entstuende ein schiefer Verlauf
            if pnr == nr - 1 and 0 < tf - pta <= 180:
                verlauf = [(pf, pa)]
        beispiele.append(beispiel(verlauf, frage, antwort))
    for frage, antwort in MUSTER:
        beispiele.append(beispiel([], frage, antwort))

    with ziel.open("w", encoding="utf-8") as datei:
        for b in beispiele:
            datei.write(json.dumps(b, ensure_ascii=False) + "\n")

    print(f"Gespraechspaare gefunden: {len(paare)}")
    print(f"Verworfen: {sum(gruende.values())} {dict(sorted(gruende.items(), key=lambda x: -x[1]))}")
    print(f"Echte Beispiele behalten: {len(behalten)}  +  Musterbeispiele: {len(MUSTER)}")
    print(f"Datensatz: {len(beispiele)} Beispiele -> {ziel}")

if __name__ == "__main__":
    main()
