"""Landkarte, Mitlesen, Zeigen - das Studium nach der Korrektur.

Der Benutzer hat am 20.08.2026 drei Dinge zurückgewiesen, die ich zuerst
gebaut hatte, und jede Zurückweisung steht hier als Test:

1. **Kein Zeitplan.** „Wie lange ich für welches Thema benötige ist
   unerheblich." – Es gibt keine Semester und keine vorgeschriebene
   Reihenfolge mehr, nur noch Abhängigkeiten als Auskunft.
2. **Keine fertigen Präsentationen.** „Der Orb muss je nach Thema
   entscheiden, ob es sinnvoll wäre." – Folien entstehen aus dem, was es
   zu sehen gibt, nicht aus einer Schablone.
3. **Keine Tests.** „Er soll dies durch das Gespräch mit mir
   feststellen." – Der Stand wird mitgelesen, nicht abgefragt.
"""

from __future__ import annotations

import uuid

import pytest

from backend.studium.landkarte import (
    TIEFEN,
    Anlass,
    Feld,
    Gebiet,
    LandkarteFehler,
    Thema,
    feld,
    felder,
    thema_suchen,
)
from backend.studium.lernstand import Lernstand
from backend.studium.mitlesen import einschaetzung_im_klartext, mitlesen
from backend.studium.praesentation import Folie, Praesentation
from backend.studium.zeigen import lohnt_sich
from backend.utils.paths import get_data_dir


# --- 1. Keine Studienordnung, eine Landkarte -------------------------------


def test_die_landkarte_kennt_keine_semester():
    # Ein Zeitplan beantwortet die Frage einer Pruefungsordnung. Hier
    # stellt sie sich nicht.
    for f in felder():
        for gebiet in f.gebiete:
            assert not hasattr(gebiet, "semester")
        for thema in f.alle_themen():
            assert not hasattr(thema, "stufe")


def test_jede_landkarte_ist_in_sich_stimmig():
    assert felder(), "es ist kein einziges Feld eingetragen"
    for f in felder():
        assert f.pruefen() == [], f"{f.kennung}: {f.pruefen()}"


def test_abhaengigkeiten_sind_auskunft_und_kein_verbot():
    # Wer bei Latein einsteigen will, darf das - er erfaehrt nur, was ihm
    # dabei fehlen wird.
    f = feld("sprachwissenschaft")
    fehlt = f.was_fehlt("lat-kasus", [])
    assert "swi-morphem" in fehlt
    # Rekursiv: Die Voraussetzung der Voraussetzung gehoert dazu.
    assert "swi-phon-laut" in fehlt

    # Und wer das Meiste schon kennt, dem fehlt entsprechend weniger.
    assert f.was_fehlt("lat-kasus", ["swi-morphem", "swi-phon-laut",
                                     "swi-was-ist-das"]) == ()


def test_ein_ringschluss_kaeme_gar_nicht_erst_herein():
    from backend.studium.landkarte import eintragen

    def _t(kennung, auf):
        return Thema(kennung=kennung, titel=kennung, abriss="x" * 30,
                     worum_es_geht=("y",), baut_auf=auf,
                     anlaesse=(Anlass(frage="?", tiefe="kennen"),))

    ring = Feld(
        kennung="ring", titel="Ring", gegenstand="x", methode="y",
        aufgaben=("z",),
        gebiete=(Gebiet(kennung="g", titel="G", beschreibung="",
                        themen=(_t("a", ("b",)), _t("b", ("a",)))),),
    )
    with pytest.raises(LandkarteFehler) as fehler:
        eintragen(ring)
    assert "Ringschluss" in str(fehler.value)


def test_es_gibt_mehr_als_einen_einstieg_und_der_setzt_nichts_voraus():
    for f in felder():
        assert f.einstiege, f"{f.kennung} hat keinen Einstieg"
        for kennung in f.einstiege:
            thema = f.thema(kennung)
            assert thema is not None and not thema.baut_auf


def test_die_nachbarschaft_zeigt_auch_den_rueckweg():
    f = feld("sprachwissenschaft")
    umfeld = f.nachbarschaft("swi-morphem")
    assert "swi-phon-laut" in umfeld["baut_auf"]
    assert "lat-kasus" in umfeld["fuehrt_zu"]


def test_ein_thema_wird_auch_ueber_einen_fachbegriff_gefunden():
    # Wer "Affrikate" sagt, meint die Lautverschiebung, auch ohne sie zu
    # nennen.
    treffer = thema_suchen("Wie entsteht eigentlich eine Affrikate?")
    assert treffer is not None
    assert treffer[1].kennung == "swi-lautverschiebung"


def test_fachnamen_und_gaengige_aliasse_finden_die_richtige_landkarte():
    from backend.studium.landkarte import feld_suchen

    assert feld_suchen("Linguistik").kennung == "sprachwissenschaft"
    assert feld_suchen("Literaturwissenschaft").kennung == "germanistik"
    assert feld_suchen("Volkswirtschaft").kennung == "wirtschaft"


# --- 2. Zeigen nur, wenn es etwas zu sehen gibt ----------------------------


def test_bei_einem_gedankengang_wird_nicht_gezeigt():
    # Eine Implikatur hat kein Aussehen. Genau dieser Fall war gemeint.
    f = feld("sprachwissenschaft")
    thema = f.thema("swi-implikatur")
    assert not thema.zeigenswert
    urteil = lohnt_sich(thema.abriss, thema)
    assert not urteil.lohnt_sich
    assert "KEINE Folien" in urteil.als_hinweis()


def test_bei_einer_karte_wird_gezeigt():
    f = feld("sprachwissenschaft")
    thema = f.thema("swi-lautverschiebung")
    urteil = lohnt_sich(thema.abriss, thema)
    assert urteil.lohnt_sich
    assert any("Karte" in v for v in urteil.vorschlaege)


@pytest.mark.parametrize(
    "text, erwartet",
    [
        ("Zeig mir die Verbreitung der Dialekte auf einer Karte", True),
        ("Wie hat sich der Anteil über die Jahrzehnte entwickelt?", True),
        ("Die Tabelle der Kasusendungen im Paradigma", True),
        ("Warum ist diese Begründung ein Fehlschluss?", False),
        ("Was spricht gegen diese Position? Nenne den Einwand.", False),
    ],
)
def test_die_entscheidung_haengt_am_gegenstand(text, erwartet):
    assert lohnt_sich(text).lohnt_sich is erwartet


def test_der_hinweis_sagt_dem_modell_was_zu_tun_ist():
    # Er entscheidet nicht - er liefert die Frage, an der zu entscheiden ist.
    dafuer = lohnt_sich("Die Karte zeigt die Grenze der Verbreitung")
    assert "folien_zeigen" in dafuer.als_hinweis()
    dagegen = lohnt_sich("Diese Begründung, dieser Einwand, jene Position")
    assert "Gedankengang" in dagegen.als_hinweis()


# --- 3. Der Stand kommt aus dem Gespräch ------------------------------------


@pytest.fixture
def stand():
    name = f"studium/test-{uuid.uuid4().hex}.json"
    yield Lernstand(dateiname=name)
    (get_data_dir() / name).unlink(missing_ok=True)


def _thema():
    return feld("sprachwissenschaft").thema("swi-morphem")


@pytest.mark.parametrize(
    "satz, erwartete_tiefe",
    [
        ("Was ist eigentlich ein Morphem?", "kennen"),
        ("Davon habe ich noch nie gehört.", "kennen"),
        ("Wie zerlege ich das in Morpheme?", "anwenden"),
        ("Zeig mir das an einem Beispiel", "anwenden"),
        ("Warum scheitert der Morphembegriff beim Ablaut?", "beurteilen"),
        ("Was spricht dagegen, das als Morphem zu fassen?", "beurteilen"),
    ],
)
def test_die_art_der_frage_verraet_die_hoehe(satz, erwartete_tiefe):
    assert mitlesen(satz, _thema()).tiefe == erwartete_tiefe


def test_eigene_fachbegriffe_heben_die_einschaetzung():
    schlicht = mitlesen("Was ist ein Morphem?", _thema())
    belesen = mitlesen(
        "Allomorph und Flexion sind mir klar, aber was ist mit der Derivation?",
        _thema(),
    )
    assert belesen.gewicht > schlicht.gewicht
    assert "Allomorph" in belesen.eigene_begriffe
    # Wer das Umfeld kennt und trotzdem nach dem Was fragt, fragt nach
    # einem EINZELNEN Begriff und nicht nach dem Gebiet.
    assert belesen.tiefe == "anwenden"


def test_ein_begriff_in_einer_zusammensetzung_zaehlt_auch():
    # Im Deutschen steckt der Fachbegriff meist in einem langen Wort.
    beobachtung = mitlesen("Die Flexionsendung ist doch ein Morphem?", _thema())
    assert "Flexion" in beobachtung.eigene_begriffe


def test_die_selbstauskunft_schlaegt_die_frageform():
    # "Ich verstehe nicht" sagt mehr als jede Frageform verraet.
    beobachtung = mitlesen(
        "Warum scheitert das? Ich verstehe das nicht.", _thema()
    )
    assert beobachtung.selbstauskunft == "kennt es nicht"
    assert beobachtung.tiefe == "kennen"


def test_interesse_wird_bemerkt():
    dafuer = mitlesen("Das interessiert mich, erzähl mehr davon", _thema())
    dagegen = mitlesen("Interessiert mich nicht, anderes Thema", _thema())
    assert dafuer.interesse == 1
    assert dagegen.interesse == -1


def test_belangloses_verraet_nichts():
    beobachtung = mitlesen("Und dann sind wir essen gegangen.", _thema())
    assert not beobachtung.sagt_etwas


def test_der_hinweis_ans_modell_nennt_seinen_grund_und_bleibt_widerruflich():
    # Eine Zahl ohne Begruendung wuerde das Modell entweder blind
    # befolgen oder ganz uebergehen.
    hinweis = einschaetzung_im_klartext(
        mitlesen("Warum scheitert der Morphembegriff?", _thema())
    )
    assert "Woran:" in hinweis
    assert "folge deinem Eindruck" in hinweis


def test_eine_einzelne_bemerkung_macht_noch_keinen_stand(stand):
    stand.beobachten("sprachwissenschaft", mitlesen("Was ist ein Morphem?", _thema()))
    eintrag = stand.stand("sprachwissenschaft", "swi-morphem")
    assert eintrag is not None
    assert not eintrag.erreicht("kennen"), "eine Bemerkung ist kein Nachweis"


def test_mehrere_gespraeche_verdichten_sich(stand):
    for satz in ("Was ist ein Morphem?", "Und was heisst Allomorph?",
                 "Was bedeutet Derivation?"):
        stand.beobachten("sprachwissenschaft", mitlesen(satz, _thema()))
    eintrag = stand.stand("sprachwissenschaft", "swi-morphem")
    assert eintrag.erreicht("kennen")
    assert eintrag.schwerpunkt() == "kennen"


def test_widerspruch_loescht_nichts(stand):
    # Wer sich fortgeschritten zeigt und danach eine Grundfrage stellt,
    # verliert seinen Stand nicht - es kommt eine Beobachtung hinzu.
    for _ in range(3):
        stand.beobachten("sprachwissenschaft",
                         mitlesen("Warum scheitert der Morphembegriff?", _thema()))
    vorher = stand.stand("sprachwissenschaft", "swi-morphem").wert("beurteilen")
    stand.beobachten("sprachwissenschaft", mitlesen("Was ist ein Morphem?", _thema()))
    nachher = stand.stand("sprachwissenschaft", "swi-morphem").wert("beurteilen")
    assert nachher == pytest.approx(vorher, abs=0.01)


def test_zugehoert_ist_kein_koennen(stand):
    stand.erklaert("sprachwissenschaft", "swi-morphem")
    stand.erklaert("sprachwissenschaft", "swi-morphem")
    eintrag = stand.stand("sprachwissenschaft", "swi-morphem")
    assert eintrag.beruehrungen == 2
    assert not eintrag.erreicht("kennen")


def test_interesse_bestimmt_wohin_es_weitergeht(stand):
    # Das ist der Kern der Korrektur: nicht die Ordnung entscheidet,
    # sondern was den Lernenden umtreibt.
    stand.beobachten(
        "sprachwissenschaft",
        mitlesen("Das interessiert mich sehr, erzähl mehr davon",
                 feld("sprachwissenschaft").thema("swi-phon-laut")),
    )
    vorschlag = stand.woran_weiter("sprachwissenschaft")
    assert vorschlag["thema"] in ("swi-morphem", "swi-lautverschiebung")
    assert "Interesse" in vorschlag["grund"]


def test_wo_er_selbst_sagt_dass_es_hakt_kommt_vor_dem_rest(stand):
    stand.beobachten(
        "sprachwissenschaft",
        mitlesen("Von Morphemen habe ich noch nie gehört", _thema()),
    )
    vorschlag = stand.woran_weiter("sprachwissenschaft")
    assert vorschlag["thema"] == "swi-morphem"
    assert "hakt" in vorschlag["grund"]


def test_ohne_vorgeschichte_kommt_ein_einstieg(stand):
    vorschlag = stand.woran_weiter("sprachwissenschaft")
    assert vorschlag["thema"] in feld("sprachwissenschaft").einstiege
    assert "voraus" in vorschlag["grund"]


def test_der_stand_ueberlebt_einen_neustart():
    name = f"studium/test-{uuid.uuid4().hex}.json"
    try:
        erst = Lernstand(dateiname=name)
        for _ in range(3):
            erst.beobachten("sprachwissenschaft",
                            mitlesen("Was ist ein Morphem?", _thema()))
        wieder = Lernstand(dateiname=name)
        assert wieder.stand("sprachwissenschaft", "swi-morphem").erreicht("kennen")
    finally:
        (get_data_dir() / name).unlink(missing_ok=True)


# --- Die Präsentation ------------------------------------------------------


def test_die_seite_traegt_alles_in_sich():
    p = Praesentation(titel="Probe")
    p.hinzufuegen(Folie(art="titel", titel="Probe"))
    p.hinzufuegen(Folie(titel="Inhalt", punkte=("Erstens", "Zweitens")))
    seite = p.html()
    assert seite.startswith("<!DOCTYPE html>")
    # Nichts wird von aussen nachgeladen - sonst waere die Datei in einem
    # Jahr eine Sammlung kaputter Bildsymbole.
    assert "http://" not in seite and "https://" not in seite
    assert "<script src" not in seite and "<link" not in seite


def test_spitze_klammern_zerlegen_die_seite_nicht():
    p = Praesentation(titel="Probe")
    p.hinzufuegen(Folie(titel="<script>alert(1)</script>", punkte=("a & b",)))
    assert "<script>alert(1)</script>" not in p.html()


def test_ein_fehlendes_bild_verhindert_keine_folie(tmp_path):
    p = Praesentation(titel="Probe")
    p.hinzufuegen(Folie(titel="Mit Bild", bild=str(tmp_path / "weg.png")))
    seite = p.html()
    assert "Mit Bild" in seite and "<img" not in seite


def test_benannte_fachpunkte_werden_als_lesbare_karten_dargestellt():
    p = Praesentation(titel="Aristoteles")
    p.hinzufuegen(Folie(
        titel="Die vier Ursachen",
        punkte=(
            "Materialursache — Woraus etwas besteht",
            "Formursache — Welche Gestalt es hat",
            "Wirkursache — Was die Veraenderung hervorbringt",
            "Zweckursache — Wozu es entsteht",
        ),
    ))

    seite = p.html()

    assert "class='punkt-raster'" in seite
    assert seite.count("class='punkt-karte'") == 4
    assert all(name in seite for name in (
        "Materialursache", "Formursache", "Wirkursache", "Zweckursache"
    ))


# --- Und dass das alles erreichbar ist -------------------------------------


def test_es_gibt_werkzeuge_und_kein_abfragewerkzeug():
    # DAS ist der Punkt, an dem der Vorgaenger scheiterte: 3.500 Zeilen
    # Professor ohne einen einzigen Werkzeugnamen. Und das Abfragen ist
    # ausdruecklich NICHT dabei.
    from backend.tools.studium_tools import build_studium_tools

    name = f"studium/test-{uuid.uuid4().hex}.json"
    try:
        namen = {t.name for t in build_studium_tools(Lernstand(dateiname=name))}
        assert {"wissen_nachsehen", "woran_weiter", "lernstand_notieren",
                "folien_zeigen"} <= namen
        assert not any("pruef" in n or "test" in n for n in namen)
    finally:
        (get_data_dir() / name).unlink(missing_ok=True)


def test_der_orchestrator_liest_bei_jeder_aeusserung_mit():
    # Ohne Werkzeugaufruf - genau das war die Bedingung.
    from pathlib import Path

    quelle = Path("backend/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    assert "_aus_dem_gespraech_lernen(text)" in quelle
    assert "attach_lernstand" in quelle
    laufzeit = Path("backend/runtime.py").read_text(encoding="utf-8")
    assert "attach_lernstand(self.lernstand)" in laufzeit


# --- Der innere Antrieb ----------------------------------------------------
#
# Vorgegeben am 20.08.2026: „Der Mensch ist gut und strebt nach Glück und
# Erfolg ... Mein Innerer Antrieb ist es, dem Menschen dabei zu helfen."


def test_die_haltung_nennt_die_grundannahme_und_die_ziele():
    from backend.studium.antrieb import haltung_im_klartext

    text = haltung_im_klartext()
    assert "Der Mensch ist gut" in text
    for ziel in ("wohlbefinden", "erfolg", "gesundheit", "fachwissen",
                 "sprachgewandtheit"):
        assert ziel in text.lower(), ziel


def test_gesamtglueck_hat_mehrere_miteinander_verbundene_schichten():
    from backend.studium.antrieb import GLUECKSSCHICHTEN, haltung_im_klartext

    assert len(GLUECKSSCHICHTEN) >= 7
    text = haltung_im_klartext().lower()
    for begriff in ("wirtschaft", "emotional", "gesundheit", "beziehungen",
                    "allgemeinwissen", "umgangsformen", "selbstbestimmung"):
        assert begriff in text
    assert "nicht gefühle diagnostizieren" in text


def test_lernprofil_bewertet_erprobte_wege_statt_starren_lerntyp(tmp_path):
    from backend.studium.lernstand import Lernstand
    from backend.utils.paths import get_data_dir

    name = f"studium/test-lernweg-{uuid.uuid4().hex}.json"
    try:
        stand = Lernstand(dateiname=name)
        stand.lehrweg_notieren("Ein konkretes Beispiel: Erstens Schritt eins, zweitens Schritt zwei.")
        stand.lernweg_beobachten("Jetzt ist es klar, so kann ich es mir merken.")
        stand.lehrweg_notieren("Noch ein konkretes Beispiel mit einem Ablauf in Schritten.")
        stand.lernweg_beobachten("Genau so verstehe ich es.")

        hinweis = stand.lernprofil_hinweis()
        assert "konkrete_beispiele" in hinweis
        assert "schritte_und_struktur" in hinweis
        assert "2 echte Rückmeldungen" in hinweis
        assert "kein Lerntyp-Etikett" in hinweis
    finally:
        (get_data_dir() / name).unlink(missing_ok=True)


def test_jedes_ziel_bringt_seine_grenze_mit():
    # Ein Ziel ohne Grenze wird zur Anmassung. Ein Assistent, der ueber
    # das Leben eines Menschen raet, hilft nicht, sondern stoert.
    from backend.studium.antrieb import ZIELE, haltung_im_klartext

    for ziel, dafuer, dagegen in ZIELE:
        assert dafuer.strip() and dagegen.strip(), ziel
    ausfuehrlich = haltung_im_klartext(ausfuehrlich=True)
    assert "keine diagnose" in ausfuehrlich.lower()
    assert "geldanlagen" in ausfuehrlich.lower()
    assert "verlustrisiko" in ausfuehrlich.lower()
    assert "steuern" in ausfuehrlich.lower()


def test_die_haltung_verbietet_draengen_und_schmeicheln():
    from backend.studium.antrieb import haltung_im_klartext

    text = haltung_im_klartext().lower()
    assert "drängen" in text and "schmeicheln" in text


def test_gelehrt_wird_nicht_linear():
    from backend.studium.antrieb import haltung_im_klartext

    text = haltung_im_klartext()
    assert "Nicht linear" in text
    assert "Netz" in text and "Kette" in text


def test_dem_interesse_folgen_aber_nicht_sprunghaft():
    from backend.studium.antrieb import beharrlich

    # Frisch beim Thema: bleiben.
    assert not beharrlich(wechsel_beim_thema=1).wechseln
    assert not beharrlich(wechsel_beim_thema=3).wechseln
    # Lange genug: darf gewechselt werden.
    assert beharrlich(wechsel_beim_thema=6).wechseln


@pytest.mark.parametrize(
    "lage",
    [
        {"will_wechseln": True},
        {"winkt_ab": True},
        {"thema_steht": True},
    ],
)
def test_der_wunsch_des_benutzers_schlaegt_die_beharrlichkeit(lage):
    from backend.studium.antrieb import beharrlich

    assert beharrlich(wechsel_beim_thema=1, **lage).wechseln


def test_der_hinweis_sagt_auch_wie_man_ihn_uebergeht():
    from backend.studium.antrieb import beharrlich

    hinweis = beharrlich(wechsel_beim_thema=1).als_hinweis()
    assert "Bleib vorerst dabei" in hinweis
    assert "ausdrücklich wechseln will, folge ihm sofort" in hinweis


def test_die_beharrlichkeit_zaehlt_am_laufenden_thema_mit(stand):
    for _ in range(3):
        stand.beobachten("sprachwissenschaft",
                         mitlesen("Was ist ein Morphem?", _thema()))
    assert not stand.wechselurteil().wechseln
    assert stand.laufendes_thema == "swi-morphem"

    # Ein anderes Thema setzt den Zaehler zurueck.
    stand.beobachten(
        "sprachwissenschaft",
        mitlesen("Was ist ein Phonem?",
                 feld("sprachwissenschaft").thema("swi-phon-laut")),
    )
    assert stand.laufendes_thema == "swi-phon-laut"
    assert not stand.wechselurteil().wechseln


def test_was_lange_liegt_wird_wieder_vorgeschlagen(stand):
    # Die andere Haelfte der Aktualisierungstendenz: nicht nur neue
    # Gegenden erschliessen, sondern die bekannten auf dem Stand halten.
    import time as _t

    stand.beobachten("sprachwissenschaft", mitlesen("Was ist ein Morphem?", _thema()))
    eintrag = stand.stand("sprachwissenschaft", "swi-morphem")
    eintrag.zuletzt = _t.time() - 200 * 86400

    assert "swi-morphem" in stand.veraltet("sprachwissenschaft")
    vorschlag = stand.woran_weiter("sprachwissenschaft")
    assert vorschlag["thema"] == "swi-morphem"
    assert "auffrischen" in vorschlag["grund"]


def test_die_haltung_kommt_beim_modell_an():
    from pathlib import Path

    quelle = Path("backend/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    assert "haltung_im_klartext()" in quelle
    assert "wechselurteil(" in quelle


# --- Die sechs Felder ------------------------------------------------------
#
# Der Auftrag vom 19.08.2026 nennt sie alle: Sprachwissenschaft (mit
# Latein), Geschichte, Philosophie, Geografie und Wirtschaft - jeweils
# auf dem Niveau, auf dem man hindurchführen kann.


def test_alle_sechs_felder_sind_da():
    kennungen = {f.kennung for f in felder()}
    assert {"sprachwissenschaft", "geschichte", "philosophie",
            "germanistik", "geografie", "wirtschaft"} <= kennungen


def test_jedes_feld_traegt_genug_um_hindurchzufuehren():
    for f in felder():
        u = f.umfang()
        assert u["themen"] >= 8, f"{f.kennung}: nur {u['themen']} Themen"
        assert u["anlaesse"] >= 3 * u["themen"] - 3, f.kennung
        assert f.methode and f.gegenstand and f.aufgaben


def test_die_philosophie_lebt_vom_argument_die_geografie_vom_bild():
    # Die Zeigen-Entscheidung ist je Fach verschieden, und das ist der
    # Punkt: Ein Gedankengang hat kein Aussehen, eine Karte schon.
    phi = feld("philosophie")
    geo = feld("geografie")
    phi_zeigbar = sum(1 for t in phi.alle_themen() if t.zeigenswert)
    geo_zeigbar = sum(1 for t in geo.alle_themen() if t.zeigenswert)
    assert phi_zeigbar <= len(phi.alle_themen()) // 3
    assert geo_zeigbar == len(geo.alle_themen())


@pytest.mark.parametrize(
    "frage, feld_kennung",
    [
        ("Erklär mir die Julikrise", "geschichte"),
        ("Erzähl mir von Sokrates", "philosophie"),
        ("Was sagt Markus Gabriel über Sinnfelder?", "philosophie"),
        ("Wie finde ich Fossilien an einem Aufschluss?", "geografie"),
        ("Was macht die Zentralbank mit dem Leitzins?", "wirtschaft"),
        ("Was ist die Zweite Lautverschiebung?", "sprachwissenschaft"),
        ("Wie analysiert die Germanistik Kafkas Prozess?", "germanistik"),
        ("Was ist der hermeneutische Zirkel bei einer Textanalyse?", "germanistik"),
        ("Was sagt Kant zur Erkenntnis?", "philosophie"),
        ("Warum gibt es am dreissigsten Breitengrad Wüsten?", "geografie"),
        ("Erklär mir das Bruttoinlandsprodukt", "wirtschaft"),
        ("Was war der Investiturstreit?", "geschichte"),
    ],
)
def test_gesprochene_fragen_finden_ihr_thema(frage, feld_kennung):
    treffer = thema_suchen(frage)
    assert treffer is not None, frage
    assert treffer[0].kennung == feld_kennung, f"{frage} -> {treffer[0].kennung}"


def test_kurze_namen_zaehlen_nur_als_ganzes_wort():
    # "Kant" trifft Kant - aber nicht die Kantone. Vier-Zeichen-Begriffe
    # gelten nur als exaktes Wort, laengere auch als Wortanfang.
    assert thema_suchen("Was sagt Kant dazu?") is not None
    assert thema_suchen("Wie viele Kantone hat die Schweiz?") is None


def test_die_interessen_des_benutzers_stehen_auf_der_karte():
    # Fossilien (sein Dokument), Markus Gabriel (mehrfach erfragt),
    # Julikrise (sein Geschichtsthema): Eine Landkarte, die am Interesse
    # des Lernenden vorbeigezeichnet ist, verfehlt ihren Zweck.
    geo = feld("geografie")
    fossil = geo.thema("geo-gesteine")
    assert fossil is not None and "Aufschluss" in " ".join(fossil.begriffe)

    phi = feld("philosophie")
    gabriel = phi.thema("phi-gegenwart")
    assert gabriel is not None and "Sinnfeld" in " ".join(gabriel.begriffe)

    ges = feld("geschichte")
    assert ges.thema("ges-julikrise") is not None
