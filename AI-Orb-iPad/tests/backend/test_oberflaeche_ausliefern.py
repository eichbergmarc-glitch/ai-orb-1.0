"""Der Server liefert die Oberflaeche selbst aus.

Damit der Orb auf iPad, Handy oder einem fremden Rechner laeuft, muss
eine einzige Adresse genuegen: dieselbe Stelle, die die Fragen
beantwortet, liefert auch die Seite, die sie stellt.

Geprueft wird das, worauf es dabei ankommt:

* Die Startseite kommt ohne Pfadangabe.
* Skript und Stilvorlage bekommen den richtigen Medientyp - Windows
  meldet fuer ``.js`` sonst gern ``text/plain``, und dann verweigert
  jeder Browser das Skript.
* Die API behaelt Vorrang vor einer gleichnamigen Datei.
* Ein Pfad, der aus dem Verzeichnis hinausfuehrt, wird abgewiesen.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

import pytest

from backend.api.http_server import ApiRouter, LocalApiServer, SseBroker

#: Das Losungswort des Prueflings.
LOSUNGSWORT = "abcd-efgh-jkmn"


@pytest.fixture()
def oberflaeche(tmp_path):
    """Ein kleines, aber vollstaendiges Abbild der gebauten Oberflaeche."""

    wurzel = tmp_path / "renderer"
    (wurzel / "styles").mkdir(parents=True)
    (wurzel / "index.html").write_text("<!DOCTYPE html><title>Orb</title>", encoding="utf-8")
    (wurzel / "web-bridge.js").write_text("window.aiOrb = {};", encoding="utf-8")
    (wurzel / "styles" / "orb.css").write_text("body { margin: 0; }", encoding="utf-8")
    # Liegt bewusst NEBEN dem Verzeichnis: Diese Datei darf niemand ueber
    # den Server zu sehen bekommen.
    (tmp_path / "geheim.txt").write_text("nicht fuer das Netz", encoding="utf-8")
    return wurzel


@pytest.fixture()
def adresse(oberflaeche):
    """Startet den Server auf einem freien Port."""

    router = ApiRouter()
    router.get("/status", lambda _: {"zustand": "wach"})

    server = LocalApiServer(
        host="127.0.0.1",
        port=0,
        router=router,
        broker=SseBroker(),
        static_root=oberflaeche,
        zugangstoken=LOSUNGSWORT,
    )
    server.start()
    yield f"http://127.0.0.1:{server.port}"
    server.stop()


def _hole(url: str) -> tuple[int, str, str]:
    """Holt eine Adresse und gibt Status, Medientyp und Inhalt zurueck."""

    try:
        with urllib.request.urlopen(url, timeout=5) as antwort:
            return (
                antwort.status,
                antwort.headers.get("Content-Type", ""),
                antwort.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.headers.get("Content-Type", ""), fehler.read().decode("utf-8")


def test_startseite_kommt_ohne_pfadangabe(adresse):
    status, typ, inhalt = _hole(f"{adresse}/")
    assert status == 200
    assert "text/html" in typ
    assert "<title>Orb</title>" in inhalt


def test_skript_bekommt_den_richtigen_medientyp(adresse):
    status, typ, inhalt = _hole(f"{adresse}/web-bridge.js")
    assert status == 200
    assert "javascript" in typ
    assert "window.aiOrb" in inhalt


def test_stilvorlage_aus_unterverzeichnis(adresse):
    status, typ, _ = _hole(f"{adresse}/styles/orb.css")
    assert status == 200
    assert "text/css" in typ


def test_api_behaelt_vorrang(adresse):
    """Eine Route ist eine Route - auch wenn eine Datei so heisst."""

    status, typ, inhalt = _hole(f"{adresse}/status")
    assert status == 200
    assert "application/json" in typ
    assert "wach" in inhalt


@pytest.mark.parametrize(
    "pfad",
    [
        "/../geheim.txt",
        "/styles/../../geheim.txt",
        "/%2e%2e/geheim.txt",
    ],
)
def test_kein_ausbruch_aus_dem_verzeichnis(adresse, pfad):
    status, _, inhalt = _hole(f"{adresse}{pfad}")
    assert status == 404
    assert "nicht fuer das Netz" not in inhalt


def test_unbekannte_adresse_bleibt_json(adresse):
    status, typ, _ = _hole(f"{adresse}/gibt-es-nicht")
    assert status == 404
    assert "application/json" in typ


# --- Zugang von anderen Geraeten ---------------------------------------
#
# Der Test sitzt notgedrungen auf demselben Rechner wie der Server. Ein
# fremdes Geraet wird deshalb so nachgestellt, wie ein Tunnel sich meldet:
# ueber ``X-Forwarded-For``. Genau daran unterscheidet der Server "hier"
# von "weitergeleitet".

FREMD = {"X-Forwarded-For": "100.64.0.7"}


class _OhneUmleitung(urllib.request.HTTPRedirectHandler):
    """Laesst die Umleitung stehen, statt ihr zu folgen."""

    def redirect_request(self, *_args, **_kwargs):
        return None


def _hole_roh(url: str, kopfzeilen: dict[str, str]):
    """Holt eine Adresse und gibt die Antwort unveraendert zurueck."""

    oeffner = urllib.request.build_opener(_OhneUmleitung)
    anfrage = urllib.request.Request(url, headers=kopfzeilen)
    try:
        with oeffner.open(anfrage, timeout=5) as antwort:
            return antwort.status, dict(antwort.headers), antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, dict(fehler.headers), fehler.read().decode("utf-8")


def test_eigener_rechner_braucht_kein_losungswort(adresse):
    """Electron fragt von hier - und soll nicht ausgesperrt werden."""

    status, _, _ = _hole_roh(f"{adresse}/", {})
    assert status == 200


def test_fremdes_geraet_ohne_losungswort_kommt_nicht_herein(adresse):
    status, _, inhalt = _hole_roh(f"{adresse}/", FREMD)
    assert status == 401
    assert "<title>Orb</title>" not in inhalt


def test_fremdes_geraet_mit_falschem_losungswort(adresse):
    status, _, _ = _hole_roh(f"{adresse}/?token=daneben", FREMD)
    assert status == 401


def test_losungswort_in_der_adresse_zieht_in_den_keks_um(adresse):
    """Danach bleibt die Adresse sauber - wichtig fuer das Symbol am iPad."""

    status, kopf, _ = _hole_roh(f"{adresse}/?token={LOSUNGSWORT}", FREMD)
    assert status == 303
    assert kopf.get("Location") == "/"
    keks = kopf.get("Set-Cookie", "")
    assert LOSUNGSWORT in keks
    assert "HttpOnly" in keks
    assert "SameSite=Lax" in keks


def test_mit_keks_kommt_das_geraet_herein(adresse):
    kopfzeilen = dict(FREMD)
    kopfzeilen["Cookie"] = f"orb_zugang={LOSUNGSWORT}"
    status, _, inhalt = _hole_roh(f"{adresse}/", kopfzeilen)
    assert status == 200
    assert "<title>Orb</title>" in inhalt


def test_auch_die_api_bleibt_fuer_fremde_zu(adresse):
    """Der Schutz haengt nicht an der Seite, sondern am Server."""

    status, _, _ = _hole_roh(f"{adresse}/status", FREMD)
    assert status == 401


# --- Die Anmeldung eines neuen Geraets ---------------------------------
#
# Auf einem iPad ist das Losungswort in die Adresszeile zu tippen eine
# Zumutung. Deshalb gibt es ein Formular - und diese Tests halten fest,
# dass es seine Aufgabe erfuellt.


def _abschicken(url: str, wort: str, kopfzeilen: dict[str, str]):
    """Schickt das Formular ab, ohne der Umleitung zu folgen."""

    oeffner = urllib.request.build_opener(_OhneUmleitung)
    daten = urllib.parse.urlencode({"wort": wort}).encode()
    anfrage = urllib.request.Request(url, data=daten, headers=kopfzeilen)
    try:
        with oeffner.open(anfrage, timeout=5) as antwort:
            return antwort.status, dict(antwort.headers), antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, dict(fehler.headers), fehler.read().decode("utf-8")


def test_fremdes_geraet_bekommt_ein_eingabefeld(adresse):
    status, _, inhalt = _hole_roh(f"{adresse}/", FREMD)
    assert status == 401
    assert "<form" in inhalt
    assert 'action="/zugang"' in inhalt or "action='/zugang'" in inhalt
    # Ohne diese drei macht iOS aus einem Losungswort etwas anderes.
    assert "autocapitalize" in inhalt
    assert "autocorrect" in inhalt
    assert "spellcheck" in inhalt


def test_richtiges_wort_im_formular_meldet_an(adresse):
    status, kopf, _ = _abschicken(f"{adresse}/zugang", LOSUNGSWORT, FREMD)
    assert status == 303
    assert kopf.get("Location") == "/"
    assert LOSUNGSWORT in kopf.get("Set-Cookie", "")


def test_grossschreibung_und_leerzeichen_sperren_niemanden_aus(adresse):
    """Ein iPad schreibt gern gross - das darf nicht der Fehler sein."""

    status, kopf, _ = _abschicken(f"{adresse}/zugang", f"  {LOSUNGSWORT.upper()} ", FREMD)
    assert status == 303
    assert LOSUNGSWORT in kopf.get("Set-Cookie", "")


def test_falsches_wort_fuehrt_zurueck_zum_feld(adresse):
    status, kopf, inhalt = _abschicken(f"{adresse}/zugang", "daneben", FREMD)
    assert status == 401
    assert "<form" in inhalt
    assert "Set-Cookie" not in kopf


def test_anmeldung_ist_auch_ohne_losungswort_erreichbar(adresse):
    """Sonst koennte sich nie ein Geraet zum ersten Mal vorstellen."""

    status, _, _ = _abschicken(f"{adresse}/zugang", "irgendwas", FREMD)
    assert status != 404
