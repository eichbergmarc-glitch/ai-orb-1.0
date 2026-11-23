"""Baut Synapse_Feintuning_v3.ipynb aus v2: zusaetzlich Wissen aus offenen Datensaetzen
(Auswahl aus de.shaip.com/offerings/open-datasets), ins Deutsche und in Synapses Stil gebracht."""
import json, re

nb = json.load(open("v2.ipynb", encoding="utf-8"))
zellen = nb["cells"]
src = lambda i: "".join(zellen[i]["source"])
def setze(i, text): zellen[i]["source"] = text.splitlines(keepends=True)
def code(text): return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text.splitlines(keepends=True)}

MD = r"""# Synapse – eigenes Modell trainieren, Version 3: mit offenen Datensätzen (gratis auf Colab)

Version 3 baut auf Version 2 auf (Stil, Persönlichkeit, Ehrlichkeit) und bringt Synapse zusätzlich **Allgemeinwissen aus offenen Datensätzen** bei – aus der Liste auf de.shaip.com/offerings/open-datasets:

* **SQuAD** (Stanford, Wissensfragen zu Wikipedia-Artikeln, CC BY-SA 4.0)
* **Natural Questions** (Google, echte Suchfragen mit Kurzantworten, CC BY-SA 3.0)
* **DBpedia** (Kurzbeschreibungen von Personen, Orten, Werken, CC BY-SA)

Diese Datensätze sind englisch. Sie werden deshalb **kostenlos direkt hier auf der Colab-GPU** ins Deutsche übersetzt (freies Übersetzungsmodell Helsinki-NLP/opus-mt-en-de) – ohne Cloud-Dienst, ohne Schlüssel, ohne Kosten. Die Antworten bestehen nur aus den Fakten des Datensatzes, kurz und direkt. Die Bild-, Video- und Tondatensätze der Liste (ImageNet, COCO, LibriSpeech …) passen nicht zu einem Sprachmodell und werden nicht verwendet.

**Vorbereitung (einmalig, ~1 Minute):**
1. Oben im Menü: **Laufzeit → Laufzeittyp ändern → T4-GPU** → Speichern.
2. **Kein Schlüssel nötig, alles kostenlos.** Die Übungsantworten aus Version 2 (`synapse_destillat_v2.jsonl` im Drive-Ordner) werden wiederverwendet; ein OpenAI-Schlüssel wird nicht gebraucht.
3. Optional: In Zelle 3b oben `ANZAHL_JE_DATENSATZ` ändern (Standard 300 – mehr = mehr Wissen, längeres Training).
4. **Laufzeit → Alle ausführen.** Beim Google-Drive-Fenster den Zugriff erlauben.

Dauer insgesamt **ca. 60–90 Minuten**. Lass den Tab offen. Am Ende liegt `synapse-v3-Q4_K_M.gguf` im Drive-Ordner **`Synapse-Modell`**.

*Ehrlich gesagt:* Ein 4-Milliarden-Modell kann nur begrenzt viel Wissen fest speichern. Das Training verbessert Allgemeinwissen und Antwortstil; für Detailwissen bleibt die Wissensbibliothek (Nachschlagen) der stärkere Weg.
"""

C_DATENSAETZE = r'''# 3b) Wissen aus offenen Datensätzen (SQuAD, Natural Questions, DBpedia) - kostenlos übersetzt
# Übersetzt wird direkt hier auf der Colab-GPU mit dem freien Modell Helsinki-NLP/opus-mt-en-de
# (keine Cloud, kein Schlüssel, keine Kosten).
ANZAHL_JE_DATENSATZ = 300          # pro Datensatz; 300 x 3 = ca. 900 Wissensbeispiele
from datasets import load_dataset
from collections import Counter

WISSEN_DATEI = ORDNER / 'synapse_wissen_v3.jsonl'

def erster_satz_mit(kontext, antwort):
    saetze = re.split(r'(?<=[.!?])\s+', kontext)
    for s in saetze:
        if antwort and antwort in s:
            return s.strip()
    return saetze[0].strip() if saetze else ""

def roh_beispiele():
    ausgabe = []
    try:
        squad = load_dataset("rajpurkar/squad", split="train").shuffle(seed=7).select(range(ANZAHL_JE_DATENSATZ * 4))
        je_artikel = Counter()
        for z in squad:                       # je Artikel hoechstens zwei Fragen -> breiteres Wissen
            if je_artikel[z["title"]] >= 2: continue
            satz = erster_satz_mit(z["context"], z["answers"]["text"][0])
            if not satz or len(satz) > 400: continue
            je_artikel[z["title"]] += 1
            ausgabe.append(("squad", z["question"], satz))
            if je_artikel.total() >= ANZAHL_JE_DATENSATZ: break
    except Exception as fehler: print("SQuAD nicht ladbar:", fehler)
    try:
        nq = load_dataset("google-research-datasets/nq_open", split="train").shuffle(seed=7).select(range(ANZAHL_JE_DATENSATZ))
        for z in nq:
            frage = z["question"].strip()
            frage = frage[0].upper() + frage[1:] + ("" if frage.endswith("?") else "?")
            ausgabe.append(("nq", frage, z["answer"][0].strip() + "."))
    except Exception as fehler: print("Natural Questions nicht ladbar:", fehler)
    try:
        db = load_dataset("fancyzhx/dbpedia_14", split="train").shuffle(seed=7).select(range(ANZAHL_JE_DATENSATZ))
        for z in db:
            name = z["title"].strip()
            frage = (f"Who is {name}?" if z["label"] in (2, 3, 4) else f"What is {name}?")
            text = " ".join(re.split(r'(?<=[.!?])\s+', z["content"].strip())[:2])[:450]
            ausgabe.append(("dbpedia", frage, text))
    except Exception as fehler: print("DBpedia nicht ladbar:", fehler)
    return ausgabe

def kaputt(text):
    woerter = text.split()
    return (not text or len(woerter) > 90 or
            (len(woerter) > 6 and max(Counter(woerter).values()) > len(woerter) / 3))   # Wiederholungsschleife

wissen = []
if WISSEN_DATEI.exists():
    wissen = [json.loads(z) for z in open(WISSEN_DATEI, encoding="utf-8") if z.strip()]
    print("Vorhandene Wissensbeispiele geladen:", len(wissen), "(Datei löschen für Neuerzeugung).")
else:
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    roh = roh_beispiele()
    print(len(roh), "Rohbeispiele geladen. Übersetze kostenlos auf der GPU ... (2–5 Minuten)")
    # Direkt ueber das Modell statt pipeline("translation"): neuere transformers-Versionen
    # (ab 5.0) kennen diese Pipeline nicht mehr.
    UEB_NAME = "Helsinki-NLP/opus-mt-en-de"
    ueb_tok = AutoTokenizer.from_pretrained(UEB_NAME)
    uebersetzer = AutoModelForSeq2SeqLM.from_pretrained(UEB_NAME).to("cuda").half().eval()
    texte = [x for _, f, a in roh for x in (f, a)]
    deutsch = []
    for start in range(0, len(texte), 32):
        stapel = ueb_tok(texte[start:start + 32], return_tensors="pt", padding=True,
                         truncation=True, max_length=256).to("cuda")
        with torch.no_grad():
            aus = uebersetzer.generate(**stapel, max_new_tokens=256, num_beams=4)
        deutsch += ueb_tok.batch_decode(aus, skip_special_tokens=True)
        if start % 320 == 0:
            print(f"  {min(start + 32, len(texte))} von {len(texte)} Texten übersetzt")
    for i, (quelle, _, _) in enumerate(roh):
        frage, antwort = deutsch[2 * i].strip(), deutsch[2 * i + 1].strip().replace("ß", "ss")
        frage = frage.replace("ß", "ss")
        if kaputt(frage) or kaputt(antwort) or len(antwort) < 3 or SCHLECHT.search(antwort):
            continue
        wissen.append({"quelle": quelle, "messages": [{"role": "system", "content": PERSONA},
                                                      {"role": "user", "content": frage},
                                                      {"role": "assistant", "content": antwort}]})
    del uebersetzer, ueb_tok; torch.cuda.empty_cache()       # GPU-Speicher fuers Training freigeben
    with open(WISSEN_DATEI, "w", encoding="utf-8") as datei:
        for w in wissen: datei.write(json.dumps(w, ensure_ascii=False) + "\n")
    print("Übersetzt und geprüft:", len(wissen), "von", len(roh))

print(Counter(w["quelle"] for w in wissen))
random.seed(11)
PRUEF_WISSEN = random.sample(wissen, min(4, len(wissen)))    # vier Fragen zum Nachprüfen nach dem Training
for w in wissen[:5]:
    print("\nF:", w["messages"][1]["content"], "\nA:", w["messages"][2]["content"])
'''

# Kostenlos: Destillation nur aus der vorhandenen Datei, nie ueber die bezahlte Cloud
t3 = src(3)
alt3 = "elif not OPENAI_KEY:"
assert alt3 in t3
t3 = t3.replace(alt3, "elif True:   # v3 kostenlos: keine Cloud-Anfragen. Fehlt die Datei, nur Grundbeispiele.", 1)
t3 = t3.replace("Kein Secret OPENAI_API_KEY -> Destillation übersprungen.", "Keine Datei synapse_destillat_v2.jsonl im Drive -> Destillation übersprungen (kostenlos).")
t3 = t3.replace("# 3) Destillation: die Cloud-Synapse erzeugt saubere Übungsantworten (optional)",
                "# 3) Übungsantworten aus Version 2 laden (kostenlos - es wird nichts neu angefragt)")
setze(3, t3)

setze(1, src(1).replace("!pip install -q unsloth", "!pip install -q unsloth sentencepiece sacremoses"))

# Zelle 0 ersetzen, Zelle 3b nach der Destillation einfuegen
setze(0, MD)
zellen.insert(4, code(C_DATENSAETZE))

# Training: Wissen einmischen, 2 Epochen (mehr Daten), Adapter v3
t = src(6)
assert "alle = basis * 3 + destillat + ehrlich * 2" in t, "Trainingszelle unerwartet"
t = t.replace("alle = basis * 3 + destillat + ehrlich * 2    # Grundbeispiele dreifach, Ehrlichkeit dreifach",
              "wissen_msgs = [{\"messages\": w[\"messages\"]} for w in wissen if w not in PRUEF_WISSEN]\n"
              "alle = basis * 3 + destillat + ehrlich * 2 + wissen_msgs   # v3: plus Wissen aus den Datensaetzen\n"
              "print(len(wissen_msgs), 'Wissensbeispiele aus den offenen Datensaetzen.')")
t = t.replace("num_train_epochs=3", "num_train_epochs=2").replace("# 5) Training (ca. 5–15 Minuten)", "# 5) Training (ca. 25–45 Minuten)")
setze(6, t)

# Test: Wissensfragen ergaenzen
t = src(7)
t = t.replace('print(f"Automatische Prüfung: {gut} von {geprueft} bestanden.")',
 'print(f"Automatische Prüfung: {gut} von {geprueft} bestanden.")\n'
 'print("\\n--- Wissensfragen aus den Datensätzen (nicht mittrainiert) ---")\n'
 'for w in PRUEF_WISSEN:\n'
 '    print("F:", w["messages"][1]["content"], "\\nErwartet:", w["messages"][2]["content"], "\\nSynapse:", frag(w["messages"][1]["content"]), "\\n")')
setze(7, t)

# Export: v3-Namen
t = src(8).replace("lora-adapter-v2", "lora-adapter-v3").replace("synapse-v2-Q4_K_M.gguf", "synapse-v3-Q4_K_M.gguf").replace("Modelfile-v2", "Modelfile-v3")
setze(8, t)
t = src(9).replace("synapse-v2-Q4_K_M.gguf", "synapse-v3-Q4_K_M.gguf").replace("ca. 2,5 GB", "ca. 2,5 GB").replace("Sag Claude Bescheid", "Sag Claude Bescheid (Version 3)")
setze(9, t)

json.dump(nb, open("Synapse_Feintuning_v3.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok", len(zellen), "Zellen")
