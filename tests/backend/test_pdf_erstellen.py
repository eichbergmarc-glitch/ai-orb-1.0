"""PDF-Erzeugung als echtes, deterministisches Orb-Werkzeug."""

from __future__ import annotations

import asyncio

from pypdf import PdfReader

from backend.orchestrator.orchestrator import pdf_titel_aus, will_pdf_erstellen
from backend.security.path_guard import PathDecision
from backend.tools.pdf_tools import CreatePdfTool, build_pdf_tools
from backend.tools.registry import ToolRegistry
from backend.tools.tool_engine import _ausdruecklich_verlangtes_werkzeug


class _Paths:
    def check_write(self, candidate):  # noqa: ANN001
        from pathlib import Path

        return PathDecision(True, Path(candidate).resolve())

    def check_read(self, candidate):  # noqa: ANN001
        from pathlib import Path

        return PathDecision(True, Path(candidate).resolve())


class _Security:
    paths = _Paths()


def test_natuerlicher_pdf_auftrag_wird_als_werkzeugauftrag_erkannt():
    assert will_pdf_erstellen("Erstelle mir eine PDF zum Thema Industrialisierung")
    assert not will_pdf_erstellen("Kannst du grundsätzlich PDFs lesen?")
    assert pdf_titel_aus(
        "Suche nach einer Anleitung zum intuitiven Bogenschießen und erstelle daraus eine PDF."
    ) == "intuitiven Bogenschießen"


def test_tool_engine_verlangt_pdf_werkzeug_auch_ohne_technischen_namen():
    messages = [
        {"role": "user", "content": "Erstelle daraus bitte eine PDF mit Grafiken."}
    ]
    assert _ausdruecklich_verlangtes_werkzeug(messages, ["pdf_erstellen"]) == "pdf_erstellen"


def test_pdf_werkzeug_laesst_sich_in_der_runtime_registry_anmelden():
    registry = ToolRegistry()

    assert registry.register_many(build_pdf_tools(_Security())) == 1
    assert registry.get("pdf_erstellen") is not None


def test_pdf_ist_durchsuchbar_und_mehrseitig(tmp_path):
    path = tmp_path / "test-dokument.pdf"
    content = "# Einführung\n\n" + (
        "Dies ist ein fachlicher Absatz über Geschichte und Quellenkritik. " * 180
    )
    tool = CreatePdfTool(_Security())

    result = asyncio.run(
        tool.execute(
            {
                "titel": "Prüfung der PDF-Erzeugung",
                "inhalt": content,
                "pfad": str(path),
                "quellen": "https://example.org/quelle",
                "bilder": [],
                "ueberschreiben": False,
            }
        )
    )

    assert result.ok, result.error
    assert path.read_bytes().startswith(b"%PDF-1.4")
    reader = PdfReader(path)
    assert len(reader.pages) >= 2
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Prüfung der PDF-Erzeugung" in extracted
    assert "Quellenkritik" in extracted
    assert "https://example.org/quelle" in extracted


def test_pdf_bettet_lokales_bild_ein(tmp_path):
    from PIL import Image

    image_path = tmp_path / "grafik.png"
    Image.new("RGB", (320, 180), (20, 130, 210)).save(image_path)
    pdf_path = tmp_path / "mit-grafik.pdf"
    tool = CreatePdfTool(_Security())

    result = asyncio.run(
        tool.execute(
            {
                "titel": "Dokument mit Grafik",
                "inhalt": "## Erklärung\n\nDieser Inhalt erklärt die eingebettete Grafik ausführlich.",
                "pfad": str(pdf_path),
                "quellen": "",
                "bilder": [str(image_path)],
                "ueberschreiben": False,
            }
        )
    )

    assert result.ok, result.error
    reader = PdfReader(pdf_path)
    assert reader.pages[0].images, "Die Grafik wurde nicht in die PDF eingebettet."
