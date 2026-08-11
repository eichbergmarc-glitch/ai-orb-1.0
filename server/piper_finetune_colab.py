"""Thorsten (Piper) auf eine eigene Stimme finetunen – in Google Colab.

Dies ist die ehrliche Antwort auf „können wir unseren Thorsten finetunen?“:
Ja – aber das Ziel entscheidet, ob es sich lohnt.

## Was Finetuning kann und was nicht

Finetuning macht Thorsten NICHT allgemein „natürlicher“. Die Architektur
hinter Piper (VITS) hat eine Qualitätsobergrenze, und ``thorsten-high``
schöpft sie bereits aus. Auf denselben Thorsten-Daten weiterzutrainieren
bringt nichts – das Modell kennt sie schon.

Wofür Finetuning WIRKLICH gut ist: eine EIGENE Stimme. Man nimmt Thorsten
als Startpunkt und trainiert ihn mit eigenen Aufnahmen auf eine andere
Stimme um – deine eigene, oder eine bestimmte Sprecherin. Weil man vom
fertigen Thorsten aus startet, braucht das viel weniger Daten als ein
Training von null: rund 100 saubere Sätze reichen für einen Anfang, mehr
ist besser.

Das Ergebnis klingt dann nach der neuen Stimme – aber immer noch in
Piper-Qualität, nicht wie CSM oder ElevenLabs. Wer „wie ein Mensch“ will,
ist beim GPU-Server mit CSM-1B richtig (siehe csm_tts_server.py). Wer eine
EIGENE, wiedererkennbare Stimme will, die lokal und kostenlos läuft, ist
hier richtig.

## Was du brauchst

* Eine GPU – Colab (kostenlos) genügt zum Ausprobieren.
* Einen Datensatz im LJSpeech-Format: kurze WAV-Dateien (22050 Hz, mono) und
  eine ``metadata.csv`` mit ``dateiname|gesprochener text`` je Zeile.
  Aufnehmen kannst du mit dem „Piper Recording Studio“ oder von Hand.
* Zeit: mit ~100 Sätzen und einer T4 einige Stunden.

## Ehrlichkeit zum Stand dieser Datei

Dies ist eine Vorlage nach der offiziellen Piper-Trainingsanleitung. Ich
kann ein GPU-Training hier nicht selbst ausführen, also konnte ich sie nicht
durchlaufen lassen – rechne damit, einzelne Pfade oder Versionsnummern
anzupassen. Die Schritte und Befehle folgen der dokumentierten
Vorgehensweise (OHF-Voice/piper1-gpl, „Training New Voices“).

=============================================================================
Ab hier in Colab-Zellen kopieren. GPU-Laufzeit einstellen!
=============================================================================
"""

# --- Zelle 1: Pakete -------------------------------------------------------
# !git clone https://github.com/OHF-Voice/piper1-gpl
# %cd piper1-gpl
# !pip install -e .[train]
# !pip install piper-tts

# --- Zelle 2: Basis-Checkpoint holen (Thorsten als Startpunkt) -------------
# Wir starten NICHT bei null, sondern beim fertigen Thorsten. Das ist der
# ganze Trick: Von einer guten deutschen Stimme aus braucht das Umlernen auf
# eine neue Stimme viel weniger Daten.
#
# !mkdir -p checkpoints
# !wget -O checkpoints/thorsten-high.ckpt \
#   "https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/de/de_DE/thorsten/high/epoch%3D2164-step%3D1355540.ckpt"
#
# Hinweis: Der genaue Dateiname des Checkpoints ändert sich gelegentlich.
# Sieh unter huggingface.co/datasets/rhasspy/piper-checkpoints im Ordner
# de/de_DE/thorsten/high nach der aktuellen .ckpt-Datei.

# --- Zelle 3: Deinen Datensatz hochladen -----------------------------------
# Lege deinen Datensatz nach ~/dataset:
#   ~/dataset/metadata.csv        Zeilen: "sprecher|dateiname|text"  bzw.
#                                 im single-speaker-Fall: "dateiname|text"
#   ~/dataset/wav/*.wav           kurze Aufnahmen, 22050 Hz, mono
#
# from google.colab import files
# import os, zipfile
# os.makedirs("/root/dataset", exist_ok=True)
# hoch = files.upload()             # ein zip mit metadata.csv + wav/ hochladen
# for name in hoch:
#     if name.endswith(".zip"):
#         with zipfile.ZipFile(name) as z: z.extractall("/root/dataset")

# --- Zelle 4: Vorverarbeiten -----------------------------------------------
# !python -m piper.train.preprocess \
#   --language de \
#   --input-dir /root/dataset \
#   --output-dir /root/training \
#   --dataset-format ljspeech \
#   --single-speaker \
#   --sample-rate 22050

# --- Zelle 5: Finetunen vom Thorsten-Checkpoint ----------------------------
# Wenige tausend Schritte genügen beim Finetunen – man trainiert nicht neu,
# man biegt eine fertige Stimme um. Beobachte die Beispiel-Ausgaben und
# brich ab, sobald die neue Stimme sitzt.
#
# !python -m piper.train fit \
#   --data.voice_name "meine-stimme" \
#   --data.csv_path /root/training/dataset.jsonl \
#   --data.audio_dir /root/training \
#   --model.sample_rate 22050 \
#   --ckpt_path checkpoints/thorsten-high.ckpt \
#   --trainer.max_epochs 1000 \
#   --trainer.accelerator gpu \
#   --data.batch_size 16

# --- Zelle 6: Nach ONNX exportieren ----------------------------------------
# Das Ergebnis sind ZWEI Dateien, die zusammengehören: die .onnx und eine
# .onnx.json daneben.
#
# !python -m piper.train.export_onnx \
#   --checkpoint lightning_logs/version_0/checkpoints/last.ckpt \
#   --output-file meine-stimme.onnx
#
# from google.colab import files
# files.download("meine-stimme.onnx")
# files.download("meine-stimme.onnx.json")

# =============================================================================
# In AI-Orb einbauen
# =============================================================================
# 1. Beide Dateien nach  models/piper/  in deinen AI-Orb-Ordner legen.
# 2. In config.yaml unter voice.output.piper:
#        voice: "meine-stimme"
# 3. AI-Orb neu starten. Fertig – die eigene Stimme läuft lokal und gratis.
