"""PDF-Erzeugung als echtes, deterministisches Orb-Werkzeug."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pypdf import PdfReader

from backend.orchestrator.orchestrator import (
    pdf_titel_aus,
    will_pdf_erstellen,
    will_pdf_mit_fotos,
    will_pdf_mit_grafik,
)
from backend.security.path_guard import PathDecision
from backend.tools.base_tool import ToolResult
from backend.tools.grafik_tools import build_grafik_tools
from backend.tools.pdf_tools import CreatePdfTool, build_pdf_tools
from backend.tools.registry import ToolRegistry
from backend.tools.tool_engine import ToolEngine, ToolRun, _ausdruecklich_verlangtes_werkzeug


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


def test_visuelle_pdf_und_fotowunsch_werden_unterschieden():
    assert will_pdf_mit_grafik("Erstelle eine PDF mit hochwertigen Grafiken")
    assert not will_pdf_mit_fotos("Erstelle eine PDF mit einer Infografik")
    assert will_pdf_mit_fotos("Erstelle eine bebilderte PDF mit echten Fotos")


def test_tool_engine_verlangt_pdf_werkzeug_auch_ohne_technischen_namen():
    messages = [
        {"role": "user", "content": "Erstelle daraus bitte eine PDF mit Grafiken."}
    ]
    assert _ausdruecklich_verlangtes_werkzeug(messages, ["pdf_erstellen"]) == "pdf_erstellen"


def test_pdf_werkzeug_laesst_sich_in_der_runtime_registry_anmelden():
    registry = ToolRegistry()

    assert registry.register_many(build_pdf_tools(_Security())) == 1
    assert registry.get("pdf_erstellen") is not None


def test_pdf_auftrag_bekommt_nur_den_kleinen_relevanten_werkzeugkatalog():
    registry = ToolRegistry()
    registry.register_many(build_pdf_tools(_Security()))
    registry.register_many(build_grafik_tools(_Security()))
    engine = ToolEngine.__new__(ToolEngine)
    engine._registry = registry

    namen = engine._relevante_werkzeuge(
        "Erstelle eine PDF mit einer Infografik und echten Fotos."
    )

    assert namen is not None
    assert "pdf_erstellen" in namen
    assert "infografik_erstellen" in namen
    assert "bild_suchen" in namen
    assert len(namen) <= 6


def test_pdf_bildkette_verbindet_infografik_und_fotonachweise():
    class _Engine:
        enabled = True

        async def direkt_ausfuehren(self, name, arguments, *, actor):  # noqa: ANN001, ARG002
            if name == "infografik_erstellen":
                return ToolRun(
                    name,
                    arguments,
                    ToolResult.success(
                        "Infografik erstellt",
                        pfad="C:/tmp/ueberblick.png",
                        nachweis="Infografik: AI-Orb",
                    ),
                )
            assert name == "bild_suchen"
            return ToolRun(
                name,
                arguments,
                ToolResult.success(
                    "Fotos gefunden",
                    bilder=[
                        {
                            "pfad": "C:/tmp/foto.jpg",
                            "nachweis": "Foto: Beispiel / CC BY 4.0",
                        }
                    ],
                ),
            )

    orchestrator = SimpleNamespace(_tool_engine=_Engine())
    from backend.orchestrator.orchestrator import Orchestrator

    bilder, hinweise = asyncio.run(
        Orchestrator._pdf_bilder_beschaffen(
            orchestrator,
            "Erstelle eine bebilderte PDF mit echten Fotos zur Industrialisierung",
            "# Wandel\nFabriken und Dampfmaschinen veraenderten die Gesellschaft.",
            "https://example.org/quelle",
        )
    )

    assert hinweise == []
    assert [bild["pfad"] for bild in bilder] == [
        "C:/tmp/ueberblick.png",
        "C:/tmp/foto.jpg",
    ]
    assert "CC BY 4.0" in bilder[1]["beschriftung"]


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
