"""Webcam: Standbild aufnehmen, ansehen lassen, Marc wiedererkennen (07.11.2026)."""

from __future__ import annotations

import asyncio
import sys
import types

from PIL import Image

from backend.vision import kamera as kamera_modul


class _Frame:
    def to_image(self):
        return Image.new("RGB", (1280, 720), (120, 80, 40))


class _Container:
    def __init__(self):
        self.streams = types.SimpleNamespace(video=[object()])
        self.geschlossen = False

    def decode(self, stream):
        for _ in range(30):
            yield _Frame()

    def close(self):
        self.geschlossen = True


def _fake_av(monkeypatch, geoeffnet):
    modul = types.ModuleType("av")

    def _open(name, format=None, options=None):  # noqa: A002
        geoeffnet.append((name, format))
        return _Container()

    modul.open = _open
    monkeypatch.setitem(sys.modules, "av", modul)


class _Provider:
    def __init__(self):
        self.aufrufe = []

    async def complete(self, prompt, *, system_prompt="", images=None):
        self.aufrufe.append((prompt, images))
        return "Marc sitzt vor dem Rechner."


def test_aufnahme_ueber_directshow_liefert_jpeg(monkeypatch):
    geoeffnet = []
    _fake_av(monkeypatch, geoeffnet)
    daten = kamera_modul.aufnehmen_blocking({"geraet": "Logi C270 HD WebCam"})
    assert daten[:2] == b"\xff\xd8"
    assert geoeffnet == [("video=Logi C270 HD WebCam", "dshow")]


def test_ansehen_mit_referenz_schickt_zwei_bilder(monkeypatch, tmp_path):
    _fake_av(monkeypatch, [])
    monkeypatch.setattr(kamera_modul, "referenz_pfad", lambda: tmp_path / "referenz.jpg")
    provider = _Provider()
    k = kamera_modul.Kamera(provider_manager=provider, einstellungen={"geraet": "x", "name": "Marc"})

    asyncio.run(k.referenz_speichern())
    assert (tmp_path / "referenz.jpg").is_file()

    antwort = asyncio.run(k.ansehen("Wer sitzt da?"))
    assert "Marc" in antwort
    prompt, bilder = provider.aufrufe[-1]
    assert len(bilder) == 2
    assert "Referenzfoto" in prompt and "Wer sitzt da?" in prompt


def test_ohne_kamera_klare_fehlermeldung(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", None)
    monkeypatch.setitem(sys.modules, "cv2", None)
    try:
        kamera_modul.aufnehmen_blocking({"geraet": "x"})
    except kamera_modul.KameraFehler as fehler:
        assert "fehlt" in str(fehler)
    else:  # pragma: no cover
        raise AssertionError("Fehler erwartet")
