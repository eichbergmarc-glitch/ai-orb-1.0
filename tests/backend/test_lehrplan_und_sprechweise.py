"""Tests des Lehrplans, der Sprechweise und der Spracherkennung.

Drei Wuensche des Benutzers auf einmal, und alle drei haben eine Falle:

**"Er versteht mich schlecht"** liess sich nicht nachpruefen, weil im
Protokoll zwar stand, WANN etwas ankam, aber nie WAS. Das Verstandene lag
auf "debug" und war damit unsichtbar. Eine Fehlerkennung, die man nicht
sieht, kann man nicht beheben - man kann nur an Einstellungen drehen und
hoffen.

**"Klinge menschlicher"** verleitet dazu, "sei menschlich" in den Prompt
zu schreiben. Das erzeugt Anbiederung: Begeisterung, Rueckfragen, Floskeln
vor jeder Antwort. Das klingt nach Kundendienst, nicht nach einem
Menschen. Die Tests halten deshalb das Gegenteil fest.

**"Lerne die Epochen"** verleitet dazu, Stichworte einzutragen. Ein Thema
wie "Mittelalter" ist als Suchauftrag wertlos - dabei kommt eine
Lexikoneinleitung heraus. Der Lehrplan besteht deshalb aus FRAGEN.
"""

from __future__ import annotations

from pathlib import Path

from backend.config import get_config
from backend.learning.lehrplan import LEHRPLAN, lehrplan_anlegen
from backend.learning.themenwissen import Aussage, Thema, Themenspeicher


# --- Der Lehrplan -----------------------------------------------------------------


def test_alle_gewuenschten_gebiete_stehen_darin():
    """Geschichtswissenschaft, alle Epochen, Politik, Konflikte."""

    for gebiet in (
        "Geschichtswissenschaft",
        "Antike",
        "Mittelalter",
        "Neuzeit",
        "Neueste Geschichte",
        "Globale Politik",
        "Globale Konflikte",
        "Künstliche Intelligenz",
        "Wirtschaft",
    ):
        assert gebiet in LEHRPLAN, f"{gebiet} fehlt im Lehrplan"


def test_der_lehrplan_besteht_aus_fragen():
    """Ein Stichwort ist als Suchauftrag wertlos.

    "Mittelalter" fuehrt auf Uebersichtsartikel, und was dabei
    herauskommt, ist Wissen, das jeder hat und niemand braucht. Eine Frage
    fuehrt zu Texten, in denen jemand etwas behauptet und begruendet.
    """

    for gebiet, fragen in LEHRPLAN.items():
        assert fragen, f"{gebiet} hat keine Fragen"
        for frage in fragen:
            assert frage.rstrip().endswith("?"), f"keine Frage: {frage}"
            assert len(frage) > 40, f"zu unbestimmt: {frage}"


def test_die_fragen_zielen_auf_das_umstrittene():
    """Was unstrittig ist, steht in jedem Lexikon."""

    alle = " ".join(f.lower() for fragen in LEHRPLAN.values() for f in fragen)
    for wort in ("umstritten", "forschung", "kritisiert", "gegenüber"):
        assert wort in alle, f"keine Frage zielt auf {wort}"


def test_der_lehrplan_wird_angelegt(tmp_path: Path):
    speicher = Themenspeicher(tmp_path / "themen")
    neu = lehrplan_anlegen(speicher)

    assert neu > 0
    assert len(speicher.laden("Mittelalter").offene_fragen) > 0


def test_zweimal_anlegen_verdoppelt_nichts(tmp_path: Path):
    """Sonst wuechse die Liste bei jedem Start um denselben Satz."""

    speicher = Themenspeicher(tmp_path / "themen")
    lehrplan_anlegen(speicher)
    vorher = len(speicher.laden("Antike").offene_fragen)

    assert lehrplan_anlegen(speicher) == 0
    assert len(speicher.laden("Antike").offene_fragen) == vorher


def test_bestehendes_wissen_wird_nicht_ueberschrieben(tmp_path: Path):
    """Der wichtigste Test hier.

    Wer den Orb schon befragt hat, hat dort Aussagen stehen - womoeglich
    seine eigenen, im Gespraech gegebenen. Die duerfen nicht verlorengehen,
    nur weil ein Lehrplan dazukommt.
    """

    speicher = Themenspeicher(tmp_path / "themen")
    speicher.speichern(
        Thema(
            name="Mittelalter",
            aussagen=[Aussage(text="Das habe ich ihm selbst erklaert.",
                              quelle="Vom Benutzer erklärt")],
            offene_fragen=["Meine eigene offene Frage dazu?"],
        )
    )

    lehrplan_anlegen(speicher)
    thema = speicher.laden("Mittelalter")

    assert any("selbst erklaert" in a.text for a in thema.aussagen)
    assert "Meine eigene offene Frage dazu?" in thema.offene_fragen


def test_der_lehrplan_ist_eingeschaltet():
    assert bool(get_config().get("learning.curriculum", False))


# --- Die Sprechweise ---------------------------------------------------------------


def _prompt() -> str:
    return str(get_config().get("conversation.system_prompt", "")).lower()


def test_die_sprechweise_verbietet_die_floskeln():
    """"Gerne", "gute Frage" und das Wiederholen der Frage sind genau das,
    was einen Assistenten nach Kundendienst klingen laesst."""

    prompt = _prompt()
    assert "gerne" in prompt, "die Floskeln werden nicht angesprochen"
    assert "gute frage" in prompt


def test_die_sprechweise_verlangt_widerspruch():
    """Ein Gegenueber, das allem zustimmt, wirkt nie menschlich."""

    assert "widersprich" in _prompt()


def test_die_sprechweise_erlaubt_nichtwissen():
    """"Das weiss ich nicht" ist besser als drei Saetze darum herum."""

    assert "nicht weisst" in _prompt() or "weiss ich nicht" in _prompt()


def test_die_sprechweise_sagt_nicht_bloss_sei_menschlich():
    """Eine solche Anweisung erzeugt Anbiederung statt Menschlichkeit."""

    prompt = _prompt()
    assert "sei menschlich" not in prompt
    assert "wie ein mensch" not in prompt


def test_das_erfinden_bleibt_verboten():
    """Beim Benutzer ist das keine Stilfrage - er arbeitet wissenschaftlich."""

    assert "erfinde niemals" in _prompt()


# --- Die Spracherkennung ------------------------------------------------------------


def test_es_gibt_einen_anfangshinweis():
    """Der billigste Hebel gegen Fehlerkennungen, und er kostet nichts."""

    hinweis = str(get_config().get("voice.input.initial_prompt", ""))
    assert len(hinweis) > 80, "es gibt keinen Anfangshinweis"
    assert "Orb" in hinweis, "das Weckwort ist nicht verankert"
    assert "Geschicht" in hinweis, "die Fachbegriffe fehlen"


def test_die_suchbreite_wurde_erhoeht():
    """Faengt die Faelle ab, in denen die erste Vermutung knapp danebenliegt."""

    assert int(get_config().get("voice.input.beam_size", 1)) >= 4


def test_der_anfangshinweis_kommt_beim_erkenner_an():
    """Eine Einstellung, die niemand liest, ist keine."""

    from backend.utils.paths import get_project_root

    pipeline = (
        get_project_root() / "backend" / "voice" / "voice_pipeline.py"
    ).read_text(encoding="utf-8")
    assert "voice.input.initial_prompt" in pipeline

    erkenner = (
        get_project_root() / "backend" / "whisper" / "transcriber.py"
    ).read_text(encoding="utf-8")
    assert "initial_prompt=self._anfangshinweis" in erkenner


def test_das_verstandene_steht_jetzt_im_protokoll():
    """Sonst laesst sich eine Fehlerkennung nicht nachsehen."""

    from backend.utils.paths import get_project_root

    quelle = (
        get_project_root() / "backend" / "voice" / "voice_pipeline.py"
    ).read_text(encoding="utf-8")

    stelle = quelle.index('"Verstanden (%.2f): %s"')
    davor = quelle[stelle - 200 : stelle]
    assert "logger.info(" in davor, "das Verstandene steht weiterhin auf debug"


def test_ein_grosses_modell_faellt_auf_ein_kleineres_zurueck():
    """Sonst waere die Folge nicht 'etwas schlechter', sondern 'taub'."""

    from backend.whisper.transcriber import _ist_kleiner

    assert _ist_kleiner("small", "medium")
    assert _ist_kleiner("base", "small")
    assert not _ist_kleiner("medium", "small")
    assert not _ist_kleiner("unbekannt", "small")


# --- Selbstverbesserung und Neustart -------------------------------------------------


def test_der_orb_kann_an_sich_selbst_arbeiten():
    """Lesen, aendern, zuruecknehmen, neu starten - alle vier."""

    from backend.tools.self_tools import build_self_tools

    class _Nichts:
        def __getattr__(self, name):
            return lambda *a, **kw: None

    namen = {w.name for w in build_self_tools(rollback=_Nichts(), neustart=_Nichts())}
    assert {
        "eigenen_code_lesen",
        "eigenen_code_aendern",
        "letzte_selbstaenderung_zuruecknehmen",
        "neu_starten",
    } <= namen, f"es fehlen Werkzeuge: {namen}"


def test_eine_aenderung_laesst_sich_zuruecknehmen():
    """Ohne Rueckweg waere Selbstaenderung kein Werkzeug, sondern ein Risiko."""

    from backend.tools.self_tools import build_self_tools

    class _Nichts:
        def __getattr__(self, name):
            return lambda *a, **kw: None

    werkzeuge = {w.name: w for w in build_self_tools(rollback=_Nichts(), neustart=_Nichts())}
    assert "letzte_selbstaenderung_zuruecknehmen" in werkzeuge


def test_der_neustart_findet_seinen_weg_auch_ohne_eintrag():
    """`system.restart_command` ist leer - gesucht wird dann selbst."""

    from backend.system.restart import baue_neustarter

    neustarter = baue_neustarter(get_config())
    assert neustarter is not None
