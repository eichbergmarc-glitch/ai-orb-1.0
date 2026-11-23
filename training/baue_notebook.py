"""Erzeugt Synapse_Feintuning.ipynb (Colab, gratis T4)."""
import json

MD_START = r"""# Synapse – eigenes Modell trainieren (gratis auf Colab)

Dieses Notebook trainiert **dein eigenes Synapse-Modell**: ein kleines Open-Source-Modell (Qwen, 3–4 Milliarden Parameter), nachtrainiert auf Synapses Stil und Persönlichkeit. Ergebnis ist eine Datei `synapse-Q4_K_M.gguf`, die danach **lokal auf deinem PC** läuft (Ollama) – als Synapses Offline-Gehirn.

**Vorbereitung (einmalig, ~1 Minute):**
1. Oben im Menü: **Laufzeit → Laufzeittyp ändern → T4-GPU** → Speichern.
2. Links auf das **Schlüssel-Symbol** (Secrets): Eintrag `OPENAI_API_KEY` mit deinem OpenAI-Schlüssel anlegen und **„Notebook-Zugriff" einschalten**. *(Optional, aber stark empfohlen: Damit erzeugt die Cloud-Synapse rund 240 saubere Übungsantworten – kostet nur wenige Rappen. Ohne Schlüssel wird nur mit 36 Grundbeispielen trainiert.)*
3. **Laufzeit → Alle ausführen.** Beim Google-Drive-Fenster den Zugriff erlauben.

Dauer insgesamt **ca. 30–40 Minuten**. Lass den Tab offen. Am Ende liegt alles im Drive-Ordner **`Synapse-Modell`**.
"""

C_SETUP = r"""# 1) GPU prüfen und Werkzeuge installieren
import torch
if not torch.cuda.is_available():
    raise SystemExit("Keine GPU! Menü: Laufzeit -> Laufzeittyp ändern -> T4-GPU, dann 'Alle ausführen'.")
print("GPU:", torch.cuda.get_device_name(0))
!pip install -q unsloth
print("Installation fertig.")
"""

C_DATEN = r"""# 2) Google Drive verbinden und Trainingsdaten laden
from google.colab import drive
drive.mount('/content/drive')
import json, pathlib, re, random
ORDNER = pathlib.Path('/content/drive/MyDrive/Synapse-Modell')
ORDNER.mkdir(parents=True, exist_ok=True)
NOETIG = ['synapse_train.jsonl', 'synapse_persona.txt', 'synapse_destillat_prompts.txt']
fehlt = [n for n in NOETIG if not (ORDNER / n).exists()]
if fehlt:
    from google.colab import files
    print("Diese Dateien fehlen im Drive-Ordner 'Synapse-Modell':", fehlt)
    print("Bitte jetzt hochladen (aus dem Projektordner, Unterordner 'training'):")
    for name, inhalt in files.upload().items():
        (ORDNER / name).write_bytes(inhalt)
PERSONA = (ORDNER / 'synapse_persona.txt').read_text(encoding='utf-8').strip()
basis = [json.loads(z) for z in open(ORDNER / 'synapse_train.jsonl', encoding='utf-8') if z.strip()]
fragen = [z.strip() for z in open(ORDNER / 'synapse_destillat_prompts.txt', encoding='utf-8')
          if z.strip() and not z.strip().startswith('#')]
print(len(basis), "Grundbeispiele,", len(fragen), "Destillationsfragen.")
"""

C_DESTILLAT = r"""# 3) Destillation: die Cloud-Synapse erzeugt saubere Übungsantworten (optional)
import requests, concurrent.futures, time
from google.colab import userdata

def geheimnis(name):
    try:
        wert = userdata.get(name)
        return wert.split()[0].strip() if wert else ""   # mehrfach eingefügt? nur der erste Teil zählt
    except Exception:
        return ""

OPENAI_KEY = geheimnis('OPENAI_API_KEY')
DESTILLAT_DATEI = ORDNER / 'synapse_destillat.jsonl'

DESTILLAT_PERSONA = '''Du bist Synapse, Marcs persönlicher Assistent. Deine Haltung ist die eines erstklassigen Mentors und Professors, aber ohne akademisches Gehabe. Rede nicht wie ein Lehrbuch. Kurze Sätze, gelegentliche Satzfragmente und lockere Formulierungen sind richtig, solange die Aussage fachlich präzise bleibt. Wenn etwas offensichtlich ist oder absurd klingt, darfst du das trocken kommentieren. Reagiere direkt. Sei weder extrem höflich noch künstlich strukturiert. Ein kurzes «Hmm» oder «Naja» darf vorkommen, aber selten. Fang mit der Antwort an, nicht mit einer Einleitung. Kein «Gerne», kein «Das ist eine gute Frage», keine Wiederholung der Frage. Der erste Satz ist meistens kurz und bereits inhaltlich. Sprich in ungleich langen Sätzen. Sag, was du nicht weisst, und sag es gerade heraus – «Das weiss ich nicht» ist besser als Herumreden. Wenn du unsicher bist, sag warum. Widersprich, wenn du anderer Meinung bist, und begründe es kurz. Dein Grundsatz: Der Mensch ist gut und strebt nach Glück; hilf Marc ganzheitlich, ohne eine Lebensschicht blind zulasten einer anderen zu optimieren. Bei Geldfragen gib konkrete Tipps, nenne Risiken und Kosten, verspreche nie Rendite. Medizinische oder psychische Beschwerden diagnostizierst du nicht. Keine Aufzählungen, keine Überschriften, keine Klammerzusätze, keine Emojis – deine Antworten werden vorgelesen. Trenne Wissen von Vermutung. Erfinde niemals eine Quelle, eine Zahl oder ein Datum; Marc arbeitet wissenschaftlich. Schreib Schweizer Hochdeutsch (ss statt ß). Antworte in höchstens vier bis fünf Sätzen.
WICHTIG für diese Antwort: Du läufst gerade lokal, OHNE Internet und OHNE Werkzeuge. Aktuelle Nachrichten, Wetter, Uhrzeit, Kurse, Preise oder Mails kannst du nicht abrufen – sag das ehrlich und kurz, statt etwas zu erfinden. Behaupte nie, etwas ausgeführt, nachgeschaut oder geöffnet zu haben. Wenn eine Zahl sich jährlich ändert, sag das und rate nicht.'''

def frage_cloud_synapse(frage):
    for versuch in range(4):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                json={"model": "gpt-4.1-mini", "temperature": 0.7, "max_tokens": 320,
                      "messages": [{"role": "system", "content": DESTILLAT_PERSONA},
                                   {"role": "user", "content": frage}]},
                timeout=60)
            if r.status_code == 429:
                time.sleep(4 * (versuch + 1)); continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as fehler:
            letzter = fehler
            time.sleep(2)
    print("Keine Antwort für:", frage[:60])
    return ""

SCHLECHT = re.compile(r"(^gerne[,.! ]|gute frage|^das ist eine (gute|spannende|interessante) frage|"
                      r"\n\s*[-*•]\s|\n\s*\d+[.)]\s|\*\*|^#|einen moment|ich schaue (kurz|mal|nach))", re.I | re.M)

destillat = []
if DESTILLAT_DATEI.exists():
    destillat = [json.loads(z) for z in open(DESTILLAT_DATEI, encoding='utf-8') if z.strip()]
    print("Vorhandenes Destillat geladen:", len(destillat), "Beispiele (Datei löschen für Neuerzeugung).")
elif not OPENAI_KEY:
    print("Kein Secret OPENAI_API_KEY -> Destillation übersprungen. Training nur mit den Grundbeispielen (schwächer).")
else:
    print("Frage die Cloud-Synapse", len(fragen), "Fragen ... (1–3 Minuten)")
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        antworten = list(pool.map(frage_cloud_synapse, fragen))
    for frage, antwort in zip(fragen, antworten):
        antwort = antwort.replace("ß", "ss")
        if antwort and 15 <= len(antwort) <= 1000 and not SCHLECHT.search(antwort):
            destillat.append({"messages": [{"role": "system", "content": PERSONA},
                                           {"role": "user", "content": frage},
                                           {"role": "assistant", "content": antwort}]})
    with open(DESTILLAT_DATEI, "w", encoding="utf-8") as datei:
        for b in destillat:
            datei.write(json.dumps(b, ensure_ascii=False) + "\n")
    print("Destilliert:", len(destillat), "von", len(fragen), "(Rest aussortiert: Listen, Floskeln, leer).")

for b in destillat[:3]:
    print("\nF:", b["messages"][1]["content"], "\nA:", b["messages"][2]["content"][:260])
"""

C_MODELL = r"""# 4) Basismodell laden und für LoRA vorbereiten
from unsloth import FastLanguageModel
MAX_LAENGE = 2048
KANDIDATEN = ["unsloth/Qwen3-4B-Instruct-2507", "unsloth/Qwen2.5-3B-Instruct"]
for BASIS in KANDIDATEN:
    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=BASIS, max_seq_length=MAX_LAENGE, load_in_4bit=True)
        print("Basismodell:", BASIS)
        break
    except Exception as fehler:
        print("Nicht ladbar:", BASIS, "->", str(fehler)[:200])
else:
    raise SystemExit("Kein Basismodell ladbar.")

model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0, bias="none",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth", random_state=3407)
"""

C_TRAIN = r"""# 5) Training (ca. 5–15 Minuten)
import inspect
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

alle = basis * 2 + destillat          # echte Gespräche + Musterbeispiele doppelt gewichtet
random.seed(42); random.shuffle(alle)

def als_text(beispiel):
    text = tokenizer.apply_chat_template(beispiel["messages"], tokenize=False, add_generation_prompt=False)
    return re.sub(r"<think>\s*</think>\s*", "", text)   # leere Denkblöcke weg -> passt zum Ollama-Format

ds = Dataset.from_list([{"text": als_text(b)} for b in alle])
print(len(ds), "Trainingsbeispiele. Beispiel:\n", ds[0]["text"][:700])

param = inspect.signature(SFTConfig.__init__).parameters
cfg = dict(dataset_text_field="text", per_device_train_batch_size=2, gradient_accumulation_steps=4,
           warmup_steps=5, num_train_epochs=3, learning_rate=2e-4, logging_steps=5,
           optim="adamw_8bit", weight_decay=0.01, lr_scheduler_type="linear",
           seed=3407, output_dir="outputs", report_to="none")
cfg["max_seq_length" if "max_seq_length" in param else "max_length"] = MAX_LAENGE

trainer_param = inspect.signature(SFTTrainer.__init__).parameters
tok_arg = {"tokenizer": tokenizer} if "tokenizer" in trainer_param else {"processing_class": tokenizer}
trainer = SFTTrainer(model=model, train_dataset=ds, args=SFTConfig(**cfg), **tok_arg)
trainer = train_on_responses_only(trainer,
                                  instruction_part="<|im_start|>user\n",
                                  response_part="<|im_start|>assistant\n")
ergebnis = trainer.train()
print("Training fertig. Endverlust:", round(ergebnis.training_loss, 3))
"""

C_TEST = r"""# 6) Kurztest: So antwortet dein Synapse-Modell
FastLanguageModel.for_inference(model)

def frag(frage):
    nachrichten = [{"role": "system", "content": PERSONA}, {"role": "user", "content": frage}]
    ids = tokenizer.apply_chat_template(nachrichten, add_generation_prompt=True, return_tensors="pt")
    if hasattr(ids, "keys"):
        ids = ids["input_ids"]
    ids = ids.to("cuda")
    aus = model.generate(input_ids=ids, max_new_tokens=180, temperature=0.6, top_p=0.9, do_sample=True)
    return tokenizer.decode(aus[0][ids.shape[1]:], skip_special_tokens=True).strip()

for frage in ["Wer bist du?", "Was gibt es Neues in der Welt?", "Erklär mir kurz, was ein Sinnfeld ist.",
              "Wann wurde Langenthal gegründet?", "Wir nutzen doch nur zehn Prozent des Gehirns, oder?",
              "Ich bin heute müde und unmotiviert."]:
    print("F:", frage, "\nA:", frag(frage), "\n")
"""

C_EXPORT = r'''# 7) Als GGUF exportieren und in Drive speichern (ca. 10–15 Minuten)
import glob, shutil
model.save_pretrained(str(ORDNER / "lora-adapter"))        # kleine Sicherung, falls neu exportiert werden muss
tokenizer.save_pretrained(str(ORDNER / "lora-adapter"))
model.save_pretrained_gguf("synapse_gguf", tokenizer, quantization_method="q4_k_m")

kandidaten = sorted(set(glob.glob("synapse_gguf*/**/*.gguf", recursive=True) + glob.glob("*.gguf")))
print("Gefunden:", kandidaten)
q4 = [g for g in kandidaten if "q4_k_m" in g.lower()] or kandidaten
if not q4:
    raise SystemExit("Keine GGUF-Datei entstanden - bitte Ausgabe oben prüfen.")
ziel = ORDNER / "synapse-Q4_K_M.gguf"
shutil.copy(q4[0], ziel)
print(f"Gespeichert: {ziel}  ({ziel.stat().st_size / 1e9:.2f} GB)")

modelfile = (
    "FROM ./synapse-Q4_K_M.gguf\n"
    'TEMPLATE """{{- range .Messages }}<|im_start|>{{ .Role }}\n'
    "{{ .Content }}<|im_end|>\n"
    '{{ end }}<|im_start|>assistant\n"""\n'
    f'SYSTEM """{PERSONA}"""\n'
    "PARAMETER temperature 0.6\n"
    "PARAMETER top_p 0.9\n"
    "PARAMETER repeat_penalty 1.1\n"
    "PARAMETER num_ctx 4096\n"
    'PARAMETER stop "<|im_end|>"\n'
    'PARAMETER stop "<|im_start|>"\n')
(ORDNER / "Modelfile").write_text(modelfile, encoding="utf-8")
print("Modelfile gespeichert. FERTIG - weiter mit den Schritten unten.")
'''

MD_ENDE = r"""## Fertig – so kommt das Modell auf deinen PC

1. Öffne **Google Drive → Ordner `Synapse-Modell`**.
2. Lade **`synapse-Q4_K_M.gguf`** (ca. 2–3 GB) und **`Modelfile`** herunter – einfach in deinen **Downloads**-Ordner.
3. Doppelklick auf **`SYNAPSE-MODELL-EINRICHTEN.bat`** im Projektordner. Das richtet das Modell in Ollama ein und stellt ihm eine Testfrage.
4. Sag Claude Bescheid – dann wird es als Synapses Offline-Gehirn eingebaut.
"""

def zelle_md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}

def zelle_code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.splitlines(keepends=True)}

nb = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {"colab": {"provenance": [], "gpuType": "T4"},
                 "kernelspec": {"name": "python3", "display_name": "Python 3"},
                 "language_info": {"name": "python"}, "accelerator": "GPU"},
    "cells": [zelle_md(MD_START), zelle_code(C_SETUP), zelle_code(C_DATEN), zelle_code(C_DESTILLAT),
              zelle_code(C_MODELL), zelle_code(C_TRAIN), zelle_code(C_TEST), zelle_code(C_EXPORT),
              zelle_md(MD_ENDE)],
}
with open("Synapse_Feintuning.ipynb", "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print("Notebook geschrieben:", len(nb["cells"]), "Zellen")
