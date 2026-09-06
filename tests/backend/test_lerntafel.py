"""Die Lehrtafel muss zur laufenden Vorlesung passen.

Der Anlass: "die lerntafel ist so nicht zu gebrauchen, sie zeigt irgend
welche komischen sachen an, aber sie soll ja der vorlesung entsprechende
dinge anzeigen."

Der Befund im Code: Die Tafel hatte FUENF FESTE Ueberschriften - "Zeit &
Ausgangslage", "Akteure & Raum", "Beleg & Quellenlage", "Ursache →
Veraenderung", "Bedeutung & Folge". Sie stammten aus einer Vorlesung ueber
Mesopotamien und galten danach fuer jede Vorlesung. Zwei Muster darin waren
ausserdem so weit, dass sie fast immer trafen: ``ur\\b`` (also auch
"Ursprung", "Urteil", "Natur") und ``\\b\\d{3,4}\\b`` (jede Zahl).

In einem Abschnitt ueber Platon und Aristoteles landete deshalb ein
beliebiger Satz unter "Akteure & Raum". Die Ueberschrift versprach etwas,
das der Satz nicht hielt - und eine falsch beschriftete Karte ist
schlimmer als gar keine.
"""

from __future__ import annotations

from backend.studium.vorlesungs_bilder import _saetze, uebersichtskarten


PHILOSOPHIE = (
    "Aristoteles bricht mit Platon an der entscheidenden Stelle, naemlich bei "
    "der Frage, wo die Form steckt. Bei Platon existiert sie getrennt vom Ding. "
    "Man muss hier den Begriff der Substanz vom Begriff der Akzidenz "
    "unterscheiden, im Unterschied zu einer blossen Eigenschaft. "
    "Dagegen spricht ein Einwand, der die These bestreitet. "
    "Daher folgt daraus, dass das Gute nicht jenseitig ist, weil es sich in der "
    "gelingenden Verwirklichung zeigt. "
    "Die Wirkung dieser Lehre praegte das Mittelalter bis heute."
)

GESCHICHTE = (
    "Um 3000 v. Chr. entstehen in Mesopotamien die ersten Stadtstaaten. "
    "Der Koenig von Uruk liess Mauern errichten, die noch heute nachweisbar sind. "
    "Unsere Quellen sind vor allem Keilschrift-Inschriften auf Tontafeln. "
    "Die Ueberlieferung ist lueckenhaft, und der Forschungsstand ist umstritten."
)


def _ueberschriften(abschnitt: str) -> set[str]:
    return {karte["title"] for karte in uebersichtskarten(abschnitt)}


# --- Der Inhalt waehlt die Ueberschriften ----------------------------------


def test_ein_philosophischer_abschnitt_bekommt_philosophische_karten():
    titel = _ueberschriften(PHILOSOPHIE)
    assert "Begriff & Unterscheidung" in titel
    assert "These & Einwand" in titel


def test_ein_philosophischer_abschnitt_bekommt_keine_geschichtskarten():
    """Genau das war der gemeldete Fehler."""

    titel = _ueberschriften(PHILOSOPHIE)
    assert "Akteure & Raum" not in titel
    assert "Quellen & Belege" not in titel


def test_ein_geschichtlicher_abschnitt_bekommt_geschichtliche_karten():
    titel = _ueberschriften(GESCHICHTE)
    assert "Quellen & Belege" in titel
    assert "Akteure & Raum" in titel


def test_ein_geschichtlicher_abschnitt_bekommt_keine_philosophiekarten():
    assert "These & Einwand" not in _ueberschriften(GESCHICHTE)


def test_jede_karte_gehoert_zu_ihrer_ueberschrift():
    """Die Probe aufs Ganze: Steht in der Karte, was oben drueber steht?"""

    belege = {
        "Begriff & Unterscheidung": ("unterscheid", "begriff", "unterschied"),
        "These & Einwand": ("einwand", "these", "bestreit", "dagegen"),
        "Begruendung": ("weil", "daher", "folgt", "denn"),
        "Wirkung & Nachleben": ("wirkung", "praegte", "bis heute"),
    }
    for karte in uebersichtskarten(PHILOSOPHIE):
        erwartet = belege.get(karte["title"])
        if erwartet is None:
            continue
        klein = karte["text"].casefold()
        assert any(wort in klein for wort in erwartet), karte


def test_ohne_belegte_dimension_bleibt_es_bei_der_leitidee():
    """Lieber eine Karte als fuenf, von denen vier etwas Falsches versprechen."""

    schlicht = (
        "Diese Sitzung dient allein der Wiederholung des bisher Gesagten. "
        "Wir gehen die Gliederung noch einmal ruhig durch."
    )
    karten = uebersichtskarten(schlicht)
    assert karten and karten[0]["title"] == "Leitidee"
    assert len(karten) <= 2


def test_die_tafel_zeigt_hoechstens_fuenf_karten():
    assert len(uebersichtskarten(PHILOSOPHIE)) <= 5
    assert len(uebersichtskarten(GESCHICHTE)) <= 5


# --- Saetze duerfen nicht an Abkuerzungen zerbrechen -----------------------


def test_eine_jahresangabe_zerreisst_den_satz_nicht():
    """"v. Chr." ist kein Satzende - vorher stand auf der Tafel ein Bruchstueck."""

    saetze = _saetze("Um 3000 v. Chr. entstehen die ersten Stadtstaaten. Das ist wichtig.")
    assert saetze[0] == "Um 3000 v. Chr. entstehen die ersten Stadtstaaten."
    assert len(saetze) == 2


def test_die_leitidee_beginnt_nicht_mit_einer_abkuerzung():
    kern = uebersichtskarten(GESCHICHTE)[0]["text"]
    assert not kern.startswith("Chr.")


def test_ein_gewoehnlicher_punkt_trennt_weiterhin():
    assert len(_saetze("Platon lehrte die Ideen. Aristoteles widersprach.")) == 2


# ---------------------------------------------------------------------------
# Zeitleiste und Gegenueberstellung (26.08.2026)
# ---------------------------------------------------------------------------
#
# Bis dahin goss die Tafel jeden Inhalt in dieselbe nummerierte Liste. Eine
# Abfolge von Jahren und zwei gegeneinander stehende Positionen verlieren
# dabei genau das, was sie ausmacht - die Reihenfolge und die
# Gegenueberstellung.

from backend.studium.vorlesungs_bilder import uebersichtsart


ZEITSTRANG = (
    "Um 3000 v. Chr. entstehen in Mesopotamien die ersten Stadtstaaten. "
    "Um 2350 v. Chr. einigt Sargon von Akkad die Region zu einem Reich. "
    "Um 1750 v. Chr. laesst Hammurabi seinen Rechtskodex in Stein schlagen. "
    "Im 6. Jahrhundert v. Chr. faellt Babylon an die Perser."
)

ZWEI_POSITIONEN = (
    "Bei Platon existiert die Form getrennt vom Ding, in einer eigenen Welt der Ideen. "
    "Bei Aristoteles steckt die Form im Ding selbst und gibt ihm seine Wesensbestimmung. "
    "Genau hier bricht Aristoteles mit Platon, und der Streit betrifft die Substanz. "
    "Platon lehrte seine Schueler in der Akademie zu Athen. "
    "Aristoteles gruendete spaeter das Lykeion."
)


def test_eine_jahresabfolge_wird_zur_zeitleiste():
    assert uebersichtsart(ZEITSTRANG) == "timeline"


def test_die_zeitleiste_steht_in_chronologischer_ordnung():
    """Ohne Sortierung ist es keine Leiste, sondern wieder eine Liste."""

    titel = [karte["title"] for karte in uebersichtskarten(ZEITSTRANG)]
    assert titel[0].startswith("3000")
    assert titel[1].startswith("2350")
    assert titel[2].startswith("1750")


def test_vor_christus_liegt_vor_nach_christus():
    text = (
        "Im 6. Jahrhundert v. Chr. faellt Babylon an die Perser. "
        "Im 2. Jahrhundert n. Chr. bluehte die Provinz unter roemischer Herrschaft. "
        "Um 3000 v. Chr. entstehen die ersten Stadtstaaten."
    )
    titel = [karte["title"] for karte in uebersichtskarten(text)]
    assert titel[-1].startswith("2. Jahrhundert")


def test_zwei_positionen_werden_gegenuebergestellt():
    assert uebersichtsart(ZWEI_POSITIONEN) == "comparison"


def test_die_gegenueberstellung_nennt_beide_namen_und_den_streitpunkt():
    karten = uebersichtskarten(ZWEI_POSITIONEN)
    assert [karte["title"] for karte in karten][:2] == ["Platon", "Aristoteles"]
    assert karten[2]["title"] == "Der Streitpunkt"
    # Jede Seite bekommt einen Satz, in dem NUR sie vorkommt.
    assert "Aristoteles" not in karten[0]["text"]
    assert "Platon" not in karten[1]["text"]


def test_ein_name_allein_ergibt_keine_gegenueberstellung():
    """Kommen beide Namen immer zusammen vor, ist es kein Vergleich."""

    text = (
        "Platon und Aristoteles werden oft gemeinsam genannt. "
        "Platon und Aristoteles pruegten die Schulphilosophie. "
        "Beide gehoeren zur klassischen Zeit Athens."
    )
    assert uebersichtsart(text) != "comparison"


def test_ein_gewoehnlicher_abschnitt_bleibt_bei_der_uebersicht():
    assert uebersichtsart(PHILOSOPHIE) in {"overview", "comparison"}
    assert uebersichtsart("Wir wiederholen heute in Ruhe das Gesagte.") == "overview"
