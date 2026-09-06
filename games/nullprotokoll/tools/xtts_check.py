"""Sammelt alles, was zur Diagnose der XTTS-Umgebung noetig ist."""
import platform
import sys
import traceback

print("Python  :", sys.version.replace("\n", " "))
print("Platform:", platform.platform())
print()

for name in ["torch", "torchaudio", "transformers", "tokenizers",
             "huggingface_hub", "numpy", "TTS"]:
    try:
        module = __import__(name)
        print(f"{name:17s} {getattr(module, '__version__', '?')}")
    except Exception as error:
        print(f"{name:17s} FEHLER: {type(error).__name__}: {error}")

print()
print("--- from TTS.api import TTS ---")
try:
    from TTS.api import TTS  # noqa: F401
    print("XTTS_IMPORT_OK")
except Exception:
    traceback.print_exc()
