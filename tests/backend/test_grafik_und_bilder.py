"""Diagramme zeichnen, Bilder beschaffen, beides in eine PDF setzen.

Geprüft wird hier vor allem das, was im Alltag schiefgeht - nicht der
Schönwetterfall:

* Ein Sprachmodell liefert Zahlen als Text, mit Komma, mit Einheit. Wenn das
  nicht ankommt, bekommt der Benutzer eine Fehlermeldung statt eines Bildes.
* Ein Bilddienst antwortet nicht. Dann muss das Dokument trotzdem entstehen.
* Ein Bildpfad stimmt nicht ganz. Dann soll die Datei gesucht werden, statt
  das Bild wortlos wegzulassen.
* Eine PDF mit einem Diagramm muss das Diagramm auch wirklich enthalten -
  und zwar verlustfrei, sonst sind die Achsenzahlen Matsch.

Die Netzdienste werden dabei nie echt gerufen: Ein Test, der ein fremdes
Rechenzentrum braucht, prüft am Ende dessen Verfügbarkeit und nicht diesen
Code.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import wave  # noqa: F401  (hält die Testumgebung mit der übrigen Suite gleich)
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.grafik import bildquellen
from backend.grafik.diagramm import DiagrammFehler, Reihe, diagramm_zeichnen
from backend.tools.grafik_tools import (
    ErzeugeBildTool,
    ErzeugeInfografikTool,
    SucheBildTool,
    ZeichneDiagrammTool,
    _zahlen,
)
from backend.tools.pdf_tools import CreatePdfTool


# --- Ein Sicherheitsdienst, der alles erlaubt ------------------------------
#
# Die Pfadrechte haben eigene Tests. Hier geht es um Bilder, und ein
# Rechtefehler mitten in einem Bildtest würde nur verdecken, was wirklich
# geprüft werden soll.


class _Entscheidung:
    def __init__(self, pfad):
        self.allowed = True
        self.path = Path(pfad)
        self.reason = ""


class _Pfade:
    def check_write(self, pfad):
        return _Entscheidung(pfad)

    def check_read(self, pfad):
        return _Entscheidung(pfad)


class _Sicherheit:
    paths = _Pfade()


def _bild(tmp_path: Path, name: str = "probe.png", groesse=(80, 60)) -> Path:
    from PIL import Image

    ziel = tmp_path / name
    Image.new("RGB", groesse, (12, 90, 200)).save(ziel)
    return ziel


# ---------------------------------------------------------------------------
#  Zahlen einlesen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "eingabe, erwartet",
    [
        ([1, 2, 3], [1.0, 2.0, 3.0]),
        (["1", "2"], [1.0, 2.0]),
        (["3,5", "4,25"], [3.5, 4.25]),          # deutsches Komma
        (["42 %", "13 %"], [42.0, 13.0]),        # Einheit dahinter
        (["1.234.567"], [1234567.0]),            # zwei Punkte: nur Gliederung moeglich
        (["3.142"], [3.142]),                    # ein Punkt bleibt Dezimalpunkt
        (["1.234,50"], [1234.5]),                # deutsch, mit beidem
        (["-180", "+95"], [-180.0, 95.0]),
        ("10, 20, 30", [10.0, 20.0, 30.0]),      # alles in einer Zeichenkette
        (12, [12.0]),
    ],
)
def test_zahlen_kommen_in_jeder_ueblichen_schreibweise_an(eingabe, erwartet):
    assert _zahlen(eingabe) == erwartet


# ---------------------------------------------------------------------------
#  Zeichnen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("art", ["balken", "linie", "torte", "punkte"])
def test_jede_art_ergibt_ein_lesbares_png(tmp_path, art):
    from PIL import Image

    ziel = diagramm_zeichnen(
        art=art, titel="Probe", kategorien=["A", "B", "C"],
        reihen=[Reihe("Werte", [3, 7, 5])], ziel=tmp_path / f"{art}.png",
    )
    with Image.open(ziel) as bild:
        assert bild.format == "PNG"
        assert bild.size == (1000, 620)
        # Nicht nur weiss: Es soll wirklich etwas gezeichnet worden sein.
        assert len(bild.convert("RGB").getcolors(maxcolors=100000) or []) > 20


def test_negative_werte_haengen_an_der_nulllinie(tmp_path):
    # Ein Balken nach unten ist der Fall, bei dem eine selbstgebaute
    # Achsenrechnung zuerst bricht.
    ziel = diagramm_zeichnen(
        art="balken", titel="Saldo", kategorien=["Jan", "Feb"],
        reihen=[Reihe("Saldo", [400, -300])], ziel=tmp_path / "s.png",
    )
    assert ziel.is_file() and ziel.stat().st_size > 2000


def test_zu_viele_reihen_werden_zusammengefasst_statt_farben_zu_wiederholen(tmp_path):
    # Zwei Reihen in derselben Farbe waeren schlimmer als eine Sammelreihe:
    # Das Bild saehe richtig aus und waere falsch.
    from backend.grafik.diagramm import REIHENFARBEN, _vorbereiten

    _, reihen, _ = _vorbereiten(
        "balken", ["A"], [Reihe(f"R{i}", [i]) for i in range(12)]
    )
    assert len(reihen) == len(REIHENFARBEN)
    assert reihen[-1].name == "Sonstige"
    assert reihen[-1].werte[0] == sum(range(len(REIHENFARBEN) - 1, 12))


def test_punktdiagramm_bleibt_bei_drei_reihen(tmp_path):
    from backend.grafik.diagramm import _vorbereiten

    _, reihen, _ = _vorbereiten("punkte", ["A"], [Reihe(f"R{i}", [i]) for i in range(6)])
    assert len(reihen) == 3


def test_unbekannte_art_wird_deutlich_abgewiesen(tmp_path):
    with pytest.raises(DiagrammFehler, match="Unbekannte Diagrammart"):
        diagramm_zeichnen(art="spirale", titel="X", kategorien=["A"],
                          reihen=[Reihe("W", [1])], ziel=tmp_path / "x.png")


def test_ohne_zahlen_kein_diagramm(tmp_path):
    with pytest.raises(DiagrammFehler):
        diagramm_zeichnen(art="balken", titel="X", kategorien=[],
                          reihen=[Reihe("W", [1])], ziel=tmp_path / "x.png")


# ---------------------------------------------------------------------------
#  Das Werkzeug
# ---------------------------------------------------------------------------


def test_werkzeug_zeichnet_und_nennt_den_pfad(tmp_path):
    werkzeug = ZeichneDiagrammTool(_Sicherheit())
    ergebnis = asyncio.run(werkzeug.execute({
        "art": "balken", "titel": "Umsatz",
        "kategorien": ["Q1", "Q2"], "werte": ["1.200", "1.450"],
        "pfad": str(tmp_path / "u.png"),
    }))
    assert ergebnis.ok, ergebnis.error
    assert Path(ergebnis.context["pfad"]).is_file()
    # Der Hinweis auf die PDF gehoert dazu: Ohne ihn zeichnet der Orb ein
    # Bild und legt es beiseite, statt es zu benutzen.
    assert "pdf_erstellen" in ergebnis.output


def test_werkzeug_versteht_mehrere_reihen(tmp_path):
    werkzeug = ZeichneDiagrammTool(_Sicherheit())
    ergebnis = asyncio.run(werkzeug.execute({
        "art": "linie", "titel": "Temperatur", "kategorien": ["Jan", "Feb", "Mrz"],
        "reihen": [
            {"name": "Berlin", "werte": [1, 2, 6]},
            {"name": "München", "werte": ["-0,4", "1,1", "4,9"]},
        ],
        "pfad": str(tmp_path / "t.png"),
    }))
    assert ergebnis.ok, ergebnis.error
    assert ergebnis.context["reihen"] == 2


def test_infografik_entsteht_lokal_und_hochaufgeloest(tmp_path):
    from PIL import Image

    werkzeug = ErzeugeInfografikTool(_Sicherheit())
    ziel = tmp_path / "ueberblick.png"
    ergebnis = asyncio.run(
        werkzeug.execute(
            {
                "titel": "Die Industrialisierung",
                "inhalt": (
                    "# Voraussetzungen\nKohle, Kapital und technische Innovationen.\n\n"
                    "# Wandel\nFabriken veraenderten Arbeit, Staedte und Gesellschaft.\n\n"
                    "# Folgen\nWachstum ging mit sozialen Konflikten und Umweltlasten einher."
                ),
                "quelle": "Fachliteratur und Quellenvergleich",
                "pfad": str(ziel),
            }
        )
    )

    assert ergebnis.ok, ergebnis.error
    with Image.open(ziel) as bild:
        assert bild.format == "PNG"
        assert bild.size[0] >= 1600
        assert bild.size[1] >= 1000


def test_konzeptlayout_entsteht_als_vernetzte_uebersicht(tmp_path):
    from PIL import Image

    werkzeug = ErzeugeInfografikTool(_Sicherheit())
    ziel = tmp_path / "konzept.png"
    ergebnis = asyncio.run(
        werkzeug.execute(
            {
                "titel": "Keilschrift in Sumer",
                "inhalt": (
                    "## Kernzusammenhang\nSchrift entstand aus Verwaltung.\n\n"
                    "## Zeitliche Einordnung\nUm 3300 v. u. Z.\n\n"
                    "## Raum & Akteure\nSumer und Uruk.\n\n"
                    "## Quellenlage\nErhaltene Tontafeln.\n\n"
                    "## Bedeutung & Folge\nDauerhafte Herrschaftserinnerung."
                ),
                "layout": "konzept",
                "pfad": str(ziel),
            }
        )
    )

    assert ergebnis.ok, ergebnis.error
    with Image.open(ziel) as bild:
        assert bild.size == (1600, 1000)
        assert len(bild.convert("RGB").getcolors(maxcolors=100000) or []) > 20


def test_werkzeug_sagt_was_fehlt_statt_leer_zu_scheitern(tmp_path):
    werkzeug = ZeichneDiagrammTool(_Sicherheit())
    ohne_zahlen = asyncio.run(werkzeug.execute({"titel": "X", "kategorien": ["A"]}))
    assert not ohne_zahlen.ok
    assert "werte" in ohne_zahlen.error.lower()

    ohne_kategorien = asyncio.run(werkzeug.execute({"titel": "X", "werte": [1, 2]}))
    assert not ohne_kategorien.ok
    assert "kategorien" in ohne_kategorien.error.lower()


# ---------------------------------------------------------------------------
#  Bildquellen - mit einem eigenen kleinen Server statt des echten Netzes
# ---------------------------------------------------------------------------


class _Dienst:
    """Bildet Commons, Openverse und den Bilderzeuger nach."""

    def __init__(self, verhalten: str = "gut"):
        self.verhalten = verhalten
        self.pfade: list[str] = []
        gegenstand = self

        def _png() -> bytes:
            from PIL import Image

            # Bewusst gross und nicht einfarbig.
            #
            # Vorher stand hier eine einfarbige Flaeche von 200x120. Die
            # komprimiert auf 392 Byte - und ist damit genau das, was seit
            # dem 26.08.2026 als unbrauchbar verworfen wird: zu klein fuer
            # das Vorlesungsfenster. Der Pruefling muss aussehen wie das,
            # was im Betrieb ankommt, sonst prueft er das Falsche.
            puffer = io.BytesIO()
            bild = Image.new("RGB", (1200, 900))
            bild.putdata([
                ((x * 7) % 256, (y * 5) % 256, (x + y) % 256)
                for y in range(900)
                for x in range(1200)
            ])
            bild.save(puffer, format="PNG")
            return puffer.getvalue()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _senden(self, koerper: bytes, typ: str, code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", typ)
                self.send_header("Content-Length", str(len(koerper)))
                self.end_headers()
                self.wfile.write(koerper)

            def do_GET(self):
                gegenstand.pfade.append(self.path)
                if gegenstand.verhalten == "kaputt":
                    self._senden(b"nein", "text/plain", 503)
                    return
                if self.path.startswith("/bild"):
                    self._senden(_png(), "image/png")
                    return
                if self.path.startswith("/kein-bild"):
                    self._senden(b"<html>Fehlerseite</html>", "text/html")
                    return
                if self.path.startswith("/commons"):
                    if gegenstand.verhalten == "leer":
                        self._senden(json.dumps({"query": {"pages": []}}).encode(),
                                     "application/json")
                        return
                    daten = {"query": {"pages": [{
                        "title": "File:Brandenburger Tor.jpg",
                        "imageinfo": [{
                            "mime": "image/jpeg",
                            "thumburl": f"http://127.0.0.1:{gegenstand.port}/bild.png",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:X",
                            "thumbwidth": 1200, "thumbheight": 900,
                            "extmetadata": {
                                "Artist": {"value": '<a href="#">Anna Beispiel</a>'},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            },
                        }],
                    }]}}
                    self._senden(json.dumps(daten).encode(), "application/json")
                    return
                if self.path.startswith("/openverse"):
                    daten = {"results": [{
                        "title": "Ein Tor",
                        "url": f"http://127.0.0.1:{gegenstand.port}/bild.png",
                        "foreign_landing_url": "https://example.org/x",
                        "creator": "Bert Beispiel",
                        "license": "cc-by", "license_version": "4.0",
                        "width": 1200, "height": 900,
                    }]}
                    self._senden(json.dumps(daten).encode(), "application/json")
                    return
                self._senden(b"?", "text/plain", 404)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def adresse(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def schliessen(self):
        self._server.shutdown()


@pytest.fixture
def dienst(monkeypatch):
    laufend = _Dienst()
    monkeypatch.setattr(bildquellen, "_COMMONS", f"{laufend.adresse}/commons")
    monkeypatch.setattr(bildquellen, "_OPENVERSE", f"{laufend.adresse}/openverse")
    monkeypatch.setattr(bildquellen, "_POLLINATIONS", f"{laufend.adresse}/bild/")
    yield laufend
    laufend.schliessen()


def test_bildsuche_liefert_treffer_mit_nachweis(dienst):
    treffer = bildquellen.bilder_suchen("Brandenburger Tor", anzahl=1)
    assert treffer
    nachweis = treffer[0].nachweis()
    # Ohne Urheber und Lizenz waere das Bild im Dokument nicht nachweisbar.
    assert "Anna Beispiel" in nachweis
    assert "CC BY-SA 4.0" in nachweis
    assert "Wikimedia Commons" in nachweis


def test_bildsuche_weicht_auf_openverse_aus(dienst):
    dienst.verhalten = "leer"
    treffer = bildquellen.bilder_suchen("etwas ganz Seltenes", anzahl=1)
    assert treffer and treffer[0].quelle == "Openverse"
    assert any(p.startswith("/openverse") for p in dienst.pfade)


def test_ausgefallener_dienst_ergibt_eine_leere_liste_keinen_absturz(dienst):
    dienst.verhalten = "kaputt"
    assert bildquellen.bilder_suchen("irgendwas") == []


def test_heruntergeladenes_bild_wird_neu_geschrieben(dienst, tmp_path):
    treffer = bildquellen.bilder_suchen("Tor", anzahl=1)
    ziel = bildquellen.bild_holen(treffer[0], tmp_path / "foto.jpg")
    from PIL import Image

    assert ziel is not None
    with Image.open(ziel) as bild:
        # Neu geschrieben heisst: als JPEG, ohne alles, was sonst noch in
        # der Datei stand.
        assert bild.format == "JPEG"


def test_eine_fehlerseite_wird_nicht_als_bild_gespeichert(dienst, tmp_path):
    ziel = bildquellen.bild_holen(f"{dienst.adresse}/kein-bild", tmp_path / "x.jpg")
    assert ziel is None
    assert not (tmp_path / "x.jpg").exists()


def test_bilderzeugung_liefert_eine_datei(dienst, tmp_path):
    ziel = bildquellen.bild_erzeugen("a blue cube on white", tmp_path / "e.jpg")
    assert ziel is not None and ziel.is_file()


def test_ausgefallener_bilderzeuger_gibt_none_zurueck(dienst, tmp_path):
    dienst.verhalten = "kaputt"
    assert bildquellen.bild_erzeugen("irgendwas", tmp_path / "e.jpg") is None


def test_werkzeug_bild_erzeugen_meldet_den_ausfall_verstaendlich(dienst, tmp_path):
    dienst.verhalten = "kaputt"
    ergebnis = asyncio.run(ErzeugeBildTool().execute({"beschreibung": "a cat"}))
    assert not ergebnis.ok
    # Der Orb soll daraufhin weitermachen, nicht abbrechen - das muss in der
    # Meldung stehen, sonst weiss das Modell es nicht.
    assert "ohne Bild" in ergebnis.error


def test_werkzeug_bild_suchen_gibt_pfade_und_unterschriften(dienst):
    ergebnis = asyncio.run(SucheBildTool().execute({"begriff": "Tor", "anzahl": 1}))
    assert ergebnis.ok, ergebnis.error
    assert Path(ergebnis.context["pfad"]).is_file()
    assert "CC BY-SA 4.0" in ergebnis.output


# ---------------------------------------------------------------------------
#  Bilder in der PDF
# ---------------------------------------------------------------------------


def _pdf_bauen(tmp_path: Path, inhalt: str, **zusatz):
    werkzeug = CreatePdfTool(_Sicherheit())
    argumente = {
        "titel": "Ein Bericht",
        "inhalt": inhalt,
        "pfad": str(tmp_path / "bericht.pdf"),
        "ueberschreiben": True,
    }
    argumente.update(zusatz)
    return asyncio.run(werkzeug.execute(argumente))


def test_bildmarke_setzt_das_bild_in_den_fliesstext(tmp_path):
    bild = _bild(tmp_path)
    inhalt = (
        "Ein Absatz davor, lang genug fuer die Mindestlaenge dieses Werkzeugs.\n\n"
        f"[BILD: {bild} | Die Unterschrift]\n\n"
        "Und ein Absatz danach, damit die Reihenfolge pruefbar ist."
    )
    ergebnis = _pdf_bauen(tmp_path, inhalt)
    assert ergebnis.ok, ergebnis.error
    assert ergebnis.context["images"] == 1

    roh = Path(ergebnis.context["path"]).read_bytes()
    assert b"/Subtype /Image" in roh
    assert b"Die Unterschrift" in roh
    # Das Bild muss ZWISCHEN den Absaetzen stehen, nicht dahinter.
    assert roh.index(b"Ein Absatz davor") < roh.index(b"Do Q") < roh.index(b"Absatz danach")


def test_diagramme_gehen_verlustfrei_in_die_pdf(tmp_path):
    # JPEG wuerde aus den Achsenzahlen Matsch machen. Deshalb muss ein PNG
    # als FlateDecode drinstehen und nicht als DCTDecode.
    diagramm = diagramm_zeichnen(
        art="balken", titel="Zahlen", kategorien=["A", "B"],
        reihen=[Reihe("W", [3, 8])], ziel=tmp_path / "d.png",
    )
    ergebnis = _pdf_bauen(
        tmp_path,
        f"Ein Text, der lang genug ist fuer dieses Werkzeug.\n\n[BILD: {diagramm}]",
    )
    roh = Path(ergebnis.context["path"]).read_bytes()
    assert b"/Filter /FlateDecode" in roh
    assert b"/Filter /DCTDecode" not in roh


def test_fotos_gehen_als_jpeg_hinein(tmp_path):
    from PIL import Image

    foto = tmp_path / "foto.jpg"
    Image.new("RGB", (120, 90), (40, 160, 90)).save(foto, format="JPEG")
    ergebnis = _pdf_bauen(
        tmp_path, f"Ein Text, der lang genug ist fuer dieses Werkzeug.\n\n[BILD: {foto}]"
    )
    assert b"/Filter /DCTDecode" in Path(ergebnis.context["path"]).read_bytes()


def test_ein_fehlendes_bild_verhindert_die_pdf_nicht(tmp_path):
    ergebnis = _pdf_bauen(
        tmp_path,
        "Ein Text, der lang genug ist fuer dieses Werkzeug.\n\n"
        f"[BILD: {tmp_path / 'gibt-es-nicht.png'}]\n\n"
        "Und danach geht es weiter.",
    )
    assert ergebnis.ok, "das Dokument muss trotzdem entstehen"
    assert ergebnis.context["ignored_images"], "und es muss gesagt werden, was fehlt"
    # Beim Namen nennen, nicht nur zaehlen.
    assert "gibt-es-nicht" in ergebnis.output


def test_ein_leicht_falscher_bildpfad_wird_gesucht(tmp_path, monkeypatch):
    # Sprachmodelle tippen Pfade aus dem Gedaechtnis ab und vertauschen dabei
    # einen Ordner. Wortlos weglassen waere die schlechteste Antwort darauf.
    echtes = _bild(tmp_path, "abbildung.png")
    monkeypatch.setattr(
        "backend.tools.datei_finden.datei_finden",
        lambda text, wurzeln=None: (echtes, [echtes]),
    )
    ergebnis = _pdf_bauen(
        tmp_path,
        "Ein Text, der lang genug ist fuer dieses Werkzeug.\n\n"
        "[BILD: C:\\falscher\\ordner\\abbildung.png | Gefunden]",
    )
    assert ergebnis.ok and ergebnis.context["images"] == 1


def test_bilder_gehen_weiterhin_auch_ueber_den_parameter(tmp_path):
    # Die alte Form darf nicht kaputtgehen, nur weil es jetzt Bildmarken gibt.
    bild = _bild(tmp_path)
    ergebnis = _pdf_bauen(
        tmp_path, "Ein Text, der lang genug ist fuer dieses Werkzeug.",
        bilder=[{"pfad": str(bild), "beschriftung": "Angehaengt"}],
    )
    assert ergebnis.ok and ergebnis.context["images"] == 1
    assert b"Angehaengt" in Path(ergebnis.context["path"]).read_bytes()


@pytest.mark.parametrize(
    "zeile",
    ["[BILD: {p}]", "[Bild: {p}]", "[bild {p}]", "[GRAFIK: {p}]", "[IMG: {p}]"],
)
def test_die_ueblichen_schreibweisen_der_bildmarke_werden_erkannt(tmp_path, zeile):
    bild = _bild(tmp_path)
    ergebnis = _pdf_bauen(
        tmp_path,
        "Ein Text, der lang genug ist fuer dieses Werkzeug.\n\n"
        + zeile.format(p=bild),
    )
    assert ergebnis.context["images"] == 1, f"nicht erkannt: {zeile}"


def test_ein_windows_pfad_mit_doppelpunkt_bleibt_heil(tmp_path):
    # Am Komma zu trennen waere naheliegend und falsch: 'C:' waere weg.
    from backend.tools.pdf_tools import _bildmarke_teilen

    pfad, text = _bildmarke_teilen(r"C:\Users\info\data\bild, mit Komma.png")
    assert pfad == r"C:\Users\info\data\bild, mit Komma.png"
    assert text == ""

    pfad, text = _bildmarke_teilen(r"C:\Users\info\bild.png | Eine Unterschrift")
    assert pfad == r"C:\Users\info\bild.png"
    assert text == "Eine Unterschrift"


def test_die_werkzeugbeschreibung_erklaert_die_bildmarke():
    # Ohne diesen Satz in der Beschreibung weiss das Sprachmodell nicht, dass
    # es Bilder in den Text setzen kann - und tut es nie.
    beschreibung = CreatePdfTool.description
    assert "[BILD:" in beschreibung
    assert "diagramm_zeichnen" in beschreibung


def test_das_diagramm_im_pdf_ist_wirklich_das_gezeichnete(tmp_path):
    # Die Bildpunkte aus der PDF zurueckholen und mit dem Original
    # vergleichen. Ein Test, der nur '/Subtype /Image' sucht, wuerde auch
    # ein leeres Bild durchgehen lassen.
    from PIL import Image

    quelle = diagramm_zeichnen(
        art="balken", titel="Zahlen", kategorien=["A", "B"],
        reihen=[Reihe("W", [3, 8])], ziel=tmp_path / "d.png",
    )
    ergebnis = _pdf_bauen(
        tmp_path, f"Ein Text, der lang genug ist fuer dieses Werkzeug.\n\n[BILD: {quelle}]"
    )
    roh = Path(ergebnis.context["path"]).read_bytes()

    anfang = roh.index(b"/Subtype /Image")
    kopf = roh[anfang:anfang + 260].decode("ascii", errors="replace")
    breite = int(kopf.split("/Width ")[1].split()[0])
    hoehe = int(kopf.split("/Height ")[1].split()[0])
    strom = roh.index(b"stream\n", anfang) + len(b"stream\n")
    ende = roh.index(b"\nendstream", strom)
    punkte = zlib.decompress(roh[strom:ende])

    aus_pdf = Image.frombytes("RGB", (breite, hoehe), punkte)
    with Image.open(quelle) as original:
        verkleinert = original.convert("RGB").copy()
        verkleinert.thumbnail((1500, 1000))
        assert aus_pdf.tobytes() == verkleinert.tobytes()
