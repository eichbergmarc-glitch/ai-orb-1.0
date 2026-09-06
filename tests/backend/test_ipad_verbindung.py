"""Die Verbindung zum iPad, hergestellt beim Start des Orb.

Geprüft wird nicht Tailscale - das ist fremdes Programm -, sondern das
Verhalten drumherum: dass keine Lage den Start des Orb gefährdet, dass
eine bestehende Weiterleitung nicht jedes Mal neu gesetzt wird, und dass
die verschiedenen Ausgänge auseinandergehalten werden. Ein iPad ist
schön, aber der Orb läuft auch ohne.
"""

from __future__ import annotations

import json

import pytest

from backend.system import ipad_verbindung


@pytest.fixture()
def antworten(monkeypatch):
    """Ersetzt Tailscale durch vorgegebene Antworten."""

    aufrufe: list[tuple[str, ...]] = []
    plan: dict[tuple[str, ...], tuple[int, str]] = {}

    def falsches_tailscale(programm, *argumente):
        aufrufe.append(argumente)
        for muster, ergebnis in plan.items():
            if argumente[: len(muster)] == muster:
                return ergebnis
        return 1, "unbekannter Befehl"

    monkeypatch.setattr(ipad_verbindung, "fragen", falsches_tailscale)
    monkeypatch.setattr(ipad_verbindung, "tailscale_finden", lambda: "tailscale")
    return plan, aufrufe


def _status(name: str = "rechner.beispiel.ts.net.") -> tuple[int, str]:
    return 0, json.dumps({"Self": {"DNSName": name}})


def test_ohne_tailscale_kein_drama(monkeypatch):
    """Nicht installiert ist ein Zustand, kein Fehler."""

    monkeypatch.setattr(ipad_verbindung, "tailscale_finden", lambda: None)
    bericht = ipad_verbindung.einrichten(8756)
    assert bericht["zustand"] == "kein_tailscale"
    assert bericht["adresse"] == ""
    assert "nicht installiert" in bericht["hinweis"]


def test_nicht_angemeldet_wird_als_solches_gemeldet(antworten):
    plan, _ = antworten
    plan[("status", "--json")] = (1, "not logged in")

    bericht = ipad_verbindung.einrichten(8756)
    assert bericht["zustand"] == "nicht_angemeldet"
    assert "anmelden" in bericht["hinweis"].lower()


def test_bestehende_weiterleitung_wird_nicht_neu_gesetzt(antworten):
    """`serve --bg` überlebt Neustarts. Es jedes Mal neu zu setzen wäre
    unnötige Arbeit - und könnte bei jedem Start nach Rechten fragen."""

    plan, aufrufe = antworten
    plan[("status", "--json")] = _status()
    plan[("serve", "status")] = (0, "https://rechner.beispiel.ts.net -> http://127.0.0.1:8756")

    bericht = ipad_verbindung.einrichten(8756)

    assert bericht["zustand"] == "stand_schon"
    assert bericht["adresse"] == "https://rechner.beispiel.ts.net"
    assert not any(a[:2] == ("serve", "--bg") for a in aufrufe)


def test_fehlende_weiterleitung_wird_eingerichtet(antworten):
    plan, aufrufe = antworten
    plan[("status", "--json")] = _status()
    plan[("serve", "status")] = (0, "keine Weiterleitung")
    plan[("serve", "--bg", "--https=443")] = (0, "")

    bericht = ipad_verbindung.einrichten(8756)

    assert bericht["zustand"] == "eingerichtet"
    assert bericht["adresse"] == "https://rechner.beispiel.ts.net"
    assert any(a[:2] == ("serve", "--bg") for a in aufrufe)


def test_alte_schreibweise_wird_auch_versucht(antworten):
    """Tailscale hat die Schreibweise zwischen Versionen geändert. Wer nur
    eine kennt, scheitert an jedem Rechner mit einer anderen Fassung."""

    plan, aufrufe = antworten
    plan[("status", "--json")] = _status()
    plan[("serve", "status")] = (0, "nichts")
    # Nur die aelteste Form wird angenommen.
    plan[("serve", "https", "/")] = (0, "")

    bericht = ipad_verbindung.einrichten(8756)

    assert bericht["zustand"] == "eingerichtet"
    assert len([a for a in aufrufe if a[0] == "serve" and a[1] != "status"]) == 4


def test_scheitern_nennt_den_ausweg(antworten):
    plan, _ = antworten
    plan[("status", "--json")] = _status()
    plan[("serve", "status")] = (0, "nichts")

    bericht = ipad_verbindung.einrichten(8756)

    assert bericht["zustand"] == "fehlgeschlagen"
    assert "FERNZUGANG.bat" in bericht["hinweis"]
    # Die Adresse steht trotzdem fest - das Gerät heißt ja schon so.
    assert bericht["adresse"] == "https://rechner.beispiel.ts.net"


def test_der_start_haengt_nicht_an_tailscale(monkeypatch):
    """Selbst wenn hier alles zusammenbricht, läuft der Orb weiter."""

    def bricht_zusammen(_port):
        raise RuntimeError("Tailscale ist explodiert")

    monkeypatch.setattr(ipad_verbindung, "einrichten", bricht_zusammen)

    # Darf keine Ausnahme nach draußen lassen.
    ipad_verbindung.im_hintergrund_einrichten(8756, "192.168.1.5")

    import time

    time.sleep(0.3)


def test_adresse_wird_aufgeschrieben(tmp_path, monkeypatch):
    """Wer das iPad einrichtet, soll die Adresse nicht im Protokoll suchen."""

    import backend.utils.paths as pfade

    monkeypatch.setattr(pfade, "get_project_root", lambda: tmp_path)

    ipad_verbindung.adresse_ablegen(
        8756,
        {"zustand": "stand_schon", "adresse": "https://rechner.beispiel.ts.net"},
        "192.168.1.5",
    )

    text = (tmp_path / "logs" / "ipad-adresse.txt").read_text(encoding="utf-8")
    assert "https://rechner.beispiel.ts.net" in text
    assert "192.168.1.5:8756" in text
    assert "AI_ORB_WEB_TOKEN" in text


def test_fehlende_zertifikate_werden_erkannt(antworten, monkeypatch):
    """Ohne Zertifikate hängt der Browser - ohne jede Fehlermeldung.

    Das ist die tückischste Lage von allen: Die Weiterleitung steht, der
    Orb läuft, alles sieht richtig aus, und trotzdem lädt nichts. Wer das
    nicht benennt, sucht den Fehler überall sonst.
    """

    plan, _ = antworten
    plan[("status", "--json")] = (
        0,
        json.dumps({"Self": {"DNSName": "rechner.beispiel.ts.net."}, "CertDomains": []}),
    )

    bericht = ipad_verbindung.einrichten(8756)

    assert bericht["zustand"] == "kein_zertifikat"
    assert "HTTPS Certificates" in bericht["hinweis"]
    assert bericht["adresse"] == "https://rechner.beispiel.ts.net"


def test_vorhandene_zertifikate_stehen_nicht_im_weg(antworten):
    plan, _ = antworten
    plan[("status", "--json")] = (
        0,
        json.dumps({
            "Self": {"DNSName": "rechner.beispiel.ts.net."},
            "CertDomains": ["rechner.beispiel.ts.net"],
        }),
    )
    plan[("serve", "status")] = (0, "-> http://127.0.0.1:8756")

    bericht = ipad_verbindung.einrichten(8756)
    assert bericht["zustand"] == "stand_schon"


def test_alte_tailscale_fassung_blockiert_nicht(antworten):
    """Kennt die Fassung das Feld nicht, wird nicht geraten - sondern
    weitergemacht. Eine unbekannte Antwort ist kein Nein."""

    plan, _ = antworten
    plan[("status", "--json")] = (
        0,
        json.dumps({"Self": {"DNSName": "rechner.beispiel.ts.net."}}),
    )
    plan[("serve", "status")] = (0, "-> http://127.0.0.1:8756")

    bericht = ipad_verbindung.einrichten(8756)
    assert bericht["zustand"] == "stand_schon"
