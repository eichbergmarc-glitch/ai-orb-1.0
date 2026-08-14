"""Warum Aufgaben scheiterten – und dass sie es nicht mehr tun.

Alle drei Fälle stammen aus dem Protokoll des Benutzers vom 13./14.08.:

1. ``wissen_vertiefen`` stürzte im ERFOLGSFALL ab:
   „'ToolResult' object has no attribute 'data'". Wenn also wirklich etwas
   gelernt worden war, ging es verloren.
2. Werkzeugaufrufe mit einem Tippfehler wurden verworfen statt repariert:
   ``{"werkzeug": "rechnen" "argumente": {}}`` (Komma fehlt) und
   ``{"werkzeug": "internet_suchen", "argumente": {"suchbegriff": "Iran"}``
   (Klammer fehlt). Beide waren eindeutig - das Werkzeug lief trotzdem nie.
3. Der Orb riet Dateipfade und gab nach zwei Fehlversuchen auf, statt nach
   dem Dateinamen zu suchen.
"""

from __future__ import annotations

import asyncio

from backend.tools.datei_finden import _vergleichbar, datei_finden, hinweis_zu
from backend.tools.tool_engine import parse_tool_calls


# --- 1. Werkzeugaufrufe mit Tippfehlern werden repariert -------------------


def test_fehlendes_komma_wird_repariert():
    roh = '{"werkzeug": "rechnen" "argumente": {}}'
    calls = parse_tool_calls(roh)
    assert [c.tool for c in calls] == ["rechnen"]


def test_fehlende_klammer_wird_repariert():
    # Die abgeschnittene Antwort - im Protokoll wörtlich so aufgetreten.
    roh = '{"werkzeug": "internet_suchen", "argumente": {"suchbegriff": "Iran"}'
    calls = parse_tool_calls(roh)
    assert [c.tool for c in calls] == ["internet_suchen"]
    assert calls[0].arguments == {"suchbegriff": "Iran"}


def test_abgeschnittener_aufruf_im_fliesstext():
    roh = 'Ich suche das kurz: {"werkzeug": "internet_suchen", "argumente": {"suchbegriff": "Nahost"'
    calls = parse_tool_calls(roh)
    assert [c.tool for c in calls] == ["internet_suchen"]
    assert calls[0].arguments["suchbegriff"] == "Nahost"


def test_python_schreibweisen_werden_gelesen():
    roh = '{"werkzeug": "datei_lesen", "argumente": {"pfad": "x", "roh": True}}'
    calls = parse_tool_calls(roh)
    assert calls and calls[0].arguments["roh"] is True


def test_komma_zu_viel_wird_repariert():
    roh = '{"werkzeug": "rechnen", "argumente": {"ausdruck": "1+1",}}'
    calls = parse_tool_calls(roh)
    assert [c.tool for c in calls] == ["rechnen"]


def test_gueltige_aufrufe_bleiben_unveraendert():
    roh = '{"werkzeug": "rechnen", "argumente": {"ausdruck": "2+2"}}'
    calls = parse_tool_calls(roh)
    assert calls[0].arguments == {"ausdruck": "2+2"}


def test_fliesstext_wird_nicht_zum_werkzeugaufruf():
    # Kein Freibrief für die Reparatur: Was kein Aufruf ist, bleibt keiner.
    assert parse_tool_calls('Er sagte "ja" und ich sagte "nein".') == []
    assert parse_tool_calls("Hier ist einfach nur Text.") == []


def test_unreparierbares_wird_nicht_geraten():
    # Ohne Werkzeugnamen darf nichts entstehen - eine falsch geratene
    # Handlung wäre schlimmer als eine nicht ausgeführte.
    assert parse_tool_calls('{"argumente": {"a": 1}}') == []


# --- 2. Dateien werden gefunden, nicht geraten ------------------------------


def test_der_protokollfall_wird_gefunden(tmp_path):
    ordner = tmp_path / "OneDrive" / "Daniel - Persönlich" / "Dokumente" / "Geschichtswissenschaft"
    ordner.mkdir(parents=True)
    echt = ordner / "Studienplan_Geschichte_BA_Zeitgeschichte.md"
    echt.write_text("Inhalt", encoding="utf-8")

    # Genau der Pfad, den der Orb im Protokoll geraten hat: falscher
    # Zwischenordner UND Leerzeichen statt Unterstrich.
    geraten = r"C:\Users\info\OneDrive\Dokumente\Geschichtswissenschaft\Studienplan_Geschichte BA Zeitgeschichte.md"
    gefunden, kandidaten = datei_finden(geraten, [str(tmp_path)])

    assert gefunden == echt, f"nicht gefunden; Kandidaten: {kandidaten}"


def test_gross_klein_und_endung_sind_egal(tmp_path):
    (tmp_path / "Bericht_Q3.md").write_text("x", encoding="utf-8")
    assert datei_finden("bericht q3.md", [str(tmp_path)])[0] is not None
    # Falsche Endung geraten - der Stamm entscheidet.
    assert datei_finden("Bericht_Q3.docx", [str(tmp_path)])[0] is not None


def test_vorhandener_pfad_wird_direkt_genommen(tmp_path):
    datei = tmp_path / "da.txt"
    datei.write_text("x", encoding="utf-8")
    gefunden, _ = datei_finden(str(datei), [str(tmp_path)])
    assert gefunden == datei


def test_mehrere_kandidaten_werden_nicht_geraten(tmp_path):
    for unterordner in ("a", "b"):
        ordner = tmp_path / unterordner
        ordner.mkdir()
        (ordner / "Notizen.md").write_text("x", encoding="utf-8")

    gefunden, kandidaten = datei_finden("Notizen.md", [str(tmp_path)])
    assert gefunden is None, "bei mehreren Treffern darf nicht geraten werden"
    assert len(kandidaten) == 2
    hinweis = hinweis_zu("Notizen.md", kandidaten)
    assert "welche gemeint ist" in hinweis


def test_ohne_treffer_kommt_ein_brauchbarer_hinweis(tmp_path):
    gefunden, kandidaten = datei_finden("gibtsnicht.md", [str(tmp_path)])
    assert gefunden is None and kandidaten == []
    assert "nenn mir" in hinweis_zu("gibtsnicht.md", kandidaten).lower()


def test_namen_werden_vergleichbar_gemacht():
    assert _vergleichbar("Studienplan_Geschichte BA") == _vergleichbar(
        "studienplan-geschichte-ba"
    )


# --- 3. wissen_vertiefen stürzt nicht mehr ab ------------------------------


def test_wissen_vertiefen_nutzt_context_statt_data():
    # Der Absturz sass in EINER Zeile: `**antwort.data` auf einem
    # ToolResult, das nur `context` hat. Hier wird die Quelle geprüft,
    # weil der Fehlerpfad sonst nur mit vollem Lerner erreichbar wäre.
    from pathlib import Path

    quelle = Path("backend/tools/learning_tools.py").read_text(encoding="utf-8")
    assert "**antwort.data" not in quelle, "der Absturz ist zurück"
    assert "antwort.context" in quelle


def test_toolresult_hat_wirklich_kein_data_feld():
    import dataclasses

    from backend.tools.base_tool import ToolResult

    felder = {f.name for f in dataclasses.fields(ToolResult)}
    assert "data" not in felder
    assert "context" in felder


# --- 4. Die Suche feuert nicht mehr bei Fragen ueber den Orb selbst -------
#
# Der teuerste Fehler im Protokoll: Die Zeitwoerter ("aktuell", "gerade",
# "zurzeit") stehen auch in Saetzen ueber den Orb, den Bildschirm oder eine
# Datei. Jeder davon loeste eine Suche bei sechs Nachrichtenhaeusern aus,
# und deren Schlagzeilen standen im Kontext, bevor das Modell zu denken
# anfing - es sollte die Helligkeit erklaeren und bekam Nahost.


def test_fragen_ueber_den_orb_loesen_keine_suche_aus():
    from backend.orchestrator.orchestrator import braucht_aktuelles

    # Wortlaut aus dem Protokoll des Benutzers.
    protokollfaelle = [
        "Eine Darstellung ist aktuell sehr dunkel. Am Anfang war sie hell",
        "Befindest du dich zurzeit auf dem erweiterten Bildschirm",
        "lies das dokument komplett durch welches ich gerade offen habe",
        "was ist gerade auf dem bildschirm",
        "warum ist die animation gerade so dunkel",
        "welche datei habe ich gerade offen",
    ]
    for satz in protokollfaelle:
        assert not braucht_aktuelles(satz), f"sollte NICHT suchen: {satz!r}"


def test_echte_fragen_nach_der_welt_suchen_weiterhin():
    from backend.orchestrator.orchestrator import braucht_aktuelles

    for satz in [
        "kannst du mir die news des tages aus aller welt beschreiben",
        "was sind die aktuellen nachrichten",
        "wie ist das wetter heute",
        "was kostet der bitcoin gerade",
        "was ist gerade in Nahost passiert",
    ]:
        assert braucht_aktuelles(satz), f"sollte suchen: {satz!r}"


def test_ausdrueckliche_suchbitte_schlaegt_das_veto():
    from backend.orchestrator.orchestrator import braucht_aktuelles

    # Wer "such im Internet" sagt, meint suchen - auch wenn ein Bildschirm
    # im Satz vorkommt.
    assert braucht_aktuelles("such im internet was das fuer ein fenster ist")


def test_mehrquellen_nur_bei_echten_nachrichten():
    from backend.orchestrator.orchestrator import Orchestrator

    o = Orchestrator.__new__(Orchestrator)
    # Sechs Suchlaeufe fuer eine Hoeflichkeitsfloskel - das lief vorher so.
    assert not o._will_nachrichten("wie geht es dir heute")
    assert not o._will_nachrichten("was hast du gerade gemacht")
    # Und die Faelle, fuer die das Werkzeug gedacht ist:
    assert o._will_nachrichten("was sind die aktuellen nachrichten")
    assert o._will_nachrichten("news des tages aus aller welt")
    assert o._will_nachrichten("wie wird ueber den konflikt berichtet")


# --- 5. Werkzeug-Aufgaben landen nie beim werkzeuglosen Modell -------------
#
# Die Regression, die ich selbst gebaut habe: Der Ablauf schaltet fuer kurze
# Alltagsfragen auf das lokale Modell um und nimmt ihm dabei die Werkzeuge.
# Ob eine Anfrage dorthin darf, wurde an ``braucht_aktuelles`` abgelesen -
# und als dort das Veto fuer Fragen ueber den Orb einzog, fiel dieser Satz
# des Benutzers durch:
#
#   "ich habe gerade ein Dokument geoeffnet, erstelle ein Printscreen und
#    lies das Dokument ein und merke es dir"
#
# Drei Auftraege, kein Werkzeug, keine Loesung.


def test_der_protokollsatz_braucht_werkzeuge():
    from backend.orchestrator.orchestrator import braucht_werkzeuge, will_bildschirm

    satz = (
        "ich habe gerade ein Dokument geöffnet, erstelle ein Prinzscreen "
        "und liest das Dokument ein und merke es dir"
    )
    assert braucht_werkzeuge(satz), "die Aufgabe braucht Werkzeuge"
    # Und der Verhoerer der Spracherkennung darf sie nicht kosten.
    assert will_bildschirm(satz), "'Prinzscreen' muss als Bildschirmauftrag gelten"


def test_handlungen_brauchen_werkzeuge():
    from backend.orchestrator.orchestrator import braucht_werkzeuge

    for satz in [
        "mach einen screenshot",
        "lies mir die datei vor",
        "merk dir das bitte",
        "öffne den browser",
        "erstelle eine notiz",
        "schau auf den bildschirm",
    ]:
        assert braucht_werkzeuge(satz), f"sollte Werkzeuge verlangen: {satz!r}"


def test_reines_geplauder_braucht_keine_werkzeuge():
    from backend.orchestrator.orchestrator import braucht_werkzeuge

    for satz in [
        "erzähl mir einen witz",
        "wie geht es dir",
        "nenne mir ein tier",
        "was ist die hauptstadt von frankreich",
    ]:
        assert not braucht_werkzeuge(satz), f"sollte OHNE Werkzeuge gehen: {satz!r}"


def test_claude_bleibt_hauptprovider():
    # Der Benutzer hat es ausdruecklich verlangt: Die Hauptantwort kommt von
    # Claude; gespart wird bei den Teilaufgaben (agents.modelle).
    from backend.orchestrator.orchestrator import Orchestrator

    class _Cfg:
        def get(self, key, default=None):
            return default  # Standardwerte - lokal_fuer_alltag ist False

    class _Intent:
        intent = "chat"

    orch = Orchestrator.__new__(Orchestrator)
    orch._config = _Cfg()
    orch._providers = type("P", (), {"local_provider_names": ["ollama"]})()

    assert orch._preferred_spoken_provider("wie geht es dir", _Intent(), None) is None
