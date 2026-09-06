"""Lade den offiziellen OpenVoice-V2-Klangfarbenkonverter lokal herunter."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    target = project / "data" / "cache" / "models" / "openvoice"
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("converter/config.json", "converter/checkpoint.pth"):
        path = hf_hub_download(
            repo_id="myshell-ai/OpenVoiceV2",
            filename=filename,
            local_dir=target,
        )
        print(path)


if __name__ == "__main__":
    main()
