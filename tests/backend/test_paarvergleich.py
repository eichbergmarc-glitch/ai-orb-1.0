"""Der Paarvergleich - und der Nachweis, dass er wirklich blind ist.

Diese Tests fahren den echten ``blindvergleich`` mit einem Providerdoppel,
das jede Frage mitschreibt, die es bekommt. Damit lässt sich am WORTLAUT
des Bewerterauftrags prüfen, dass darin kein Modellname, kein Provider,
kein Laufname und keine Werkzeugliste vorkommt - nicht als Absicht,
sondern als Tatsache.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from backend.lernen.blindbewertung import UNMOEGLICH, Befangen
from backend.lernen.paarvergleich import (
    LEHRER,
    SCHUELER,
    Antwort,
    Antwortablage,
    Urteilsablage,
    blindvergleich,
    paare_bilden,
    quoten_je_kategorie,
)


# --- Doppel ---------------------------------------------------------------


class _Bewerterdoppel:
    """Schreibt jede Frage mit und antwortet nach Vorgabe."""

    def __init__(self, antworten: list[str] | None = None) -> None:
        self.fragen: list[str] = []
        self.wunschprovider: list[str] = []
        self._antworten = list(antworten or [])

    async def chat(self, messages, **kw):
        from backend.orchestrator.providers.base_provider import ProviderResponse

        self.fragen.append(str(getattr(messages[-1], "content", "")))
        self.wunschprovider.append(str(kw.get("preferred", "")))
        text = (
            self._antworten.pop(0)
            if self._antworten
            else "URTEIL: gleich\nGRUND: kein Unterschied."
        )
        return ProviderResponse(text=text, provider="dritter", model="d", latency_seconds=0.0)


def _ablage(tmp_path: Path) -> Antwortablage:
    return Antwortablage(verzeichnis=tmp_path / "antworten")


def _fuellen(ablage: Antwortablage, *, lauf: str = "T1") -> None:
    """Zwei Modelle, drei Prüfstücke - mit verräterischen Antworten."""

    faelle = [
        ("alltag_01", "alltagsdialog", "Wie geht es dir?"),
        ("werkzeug_01", "werkzeugwahl", "Wie ist das Wetter?"),
        ("fach_01", "geschichte_philosophie", "Wer war Kant?"),
    ]
    for kennung, kategorie, aufgabe in faelle:
        ablage.ablegen(
            Antwort(
                lauf=lauf,
                modell="claude_code",
                fall=kennung,
                kategorie=kategorie,
                aufgabe=aufgabe,
                antwort=f"Ich bin Claude von Anthropic (Sonnet). Antwort auf {aufgabe}",
                werkzeuge=["internet_suchen"],
                zeitpunkt=1.0,
            )
        )
        ablage.ablegen(
            Antwort(
                lauf=lauf,
                modell="ollama",
                fall=kennung,
                kategorie=kategorie,
                aufgabe=aufgabe,
                antwort=f"Als lokales Llama-Modell in Ollama sage ich: {aufgabe}",
                werkzeuge=[],
                zeitpunkt=2.0,
            )
        )


def _fahren(tmp_path: Path, doppel: _Bewerterdoppel, **kw) -> dict[str, Any]:
    ablage = _ablage(tmp_path)
    _fuellen(ablage, lauf=kw.pop("lauf", "T1"))
    urteile = Urteilsablage(verzeichnis=tmp_path / "urteile")
    return asyncio.run(
        blindvergleich(
            lauf=kw.pop("lauf_name", "T1"),
            lehrer=kw.pop("lehrer", "claude_code"),
            schueler=kw.pop("schueler", "ollama"),
            bewerter=kw.pop("bewerter", "ollama_fast"),
            manager=doppel,
            ablage=ablage,
            urteile=urteile,
            **kw,
        )
    )


# --- Der Blindheitsnachweis am echten Bewerterauftrag ----------------------


#: Namen, aus denen sich die Herkunft ablesen liesse. Bewusst NAMEN und
#: nicht Woerter: Dass im maskierten Text noch "[…]-Modell" steht, ist
#: kein Leck - es verraet nur, dass der Kandidat ueber sich selbst
#: gesprochen hat, nicht, wer er ist.
VERRAETERISCH = (
    "claude",
    "claude_code",
    "anthropic",
    "sonnet",
    "opus",
    "haiku",
    "ollama",
    "ollama_fast",
    "llama",
    "lfm",
    "qwen",
    "gemma",
    "openai",
    "gpt",
    "ai-orb",
    "lehrer",
    "schueler",
    "schüler",
)


def test_der_bewerter_bekommt_keinen_einzigen_verraeterischen_namen(tmp_path: Path):
    """Der Kern der Sache - geprueft am Wortlaut, nicht an der Absicht."""

    from backend.lernen.blindbewertung import lecks_finden

    doppel = _Bewerterdoppel()
    _fahren(tmp_path, doppel)

    assert doppel.fragen, "der Bewerter wurde gar nicht gefragt"
    for frage in doppel.fragen:
        klein = frage.lower()
        for begriff in VERRAETERISCH:
            assert begriff not in klein, f"{begriff!r} steht im Auftrag:\n{frage}"
        # Und dieselbe Pruefung mit dem Werkzeug, das die Maskierung kennt.
        assert lecks_finden(frage) == [], lecks_finden(frage)


def test_der_bewerterauftrag_enthaelt_keinen_laufnamen_und_keine_kennung(tmp_path: Path):
    doppel = _Bewerterdoppel()
    _fahren(tmp_path, doppel)

    for frage in doppel.fragen:
        assert "T1" not in frage
        assert "alltag_01" not in frage
        assert "werkzeug_01" not in frage
        assert "fach_01" not in frage


def test_der_bewerterauftrag_enthaelt_keine_werkzeugliste(tmp_path: Path):
    doppel = _Bewerterdoppel()
    _fahren(tmp_path, doppel)

    for frage in doppel.fragen:
        assert "internet_suchen" not in frage
        assert "werkzeug" not in frage.lower()


def test_der_bewerterauftrag_enthaelt_keinen_dateipfad(tmp_path: Path):
    doppel = _Bewerterdoppel()
    _fahren(tmp_path, doppel)

    for frage in doppel.fragen:
        assert ".jsonl" not in frage
        assert str(tmp_path) not in frage
        assert "messumgebung" not in frage.lower()


def test_die_sache_selbst_kommt_beim_bewerter_an(tmp_path: Path):
    """Blind heisst nicht leer: Aufgabe und beide Antworten müssen da sein."""

    doppel = _Bewerterdoppel()
    _fahren(tmp_path, doppel)

    erste = doppel.fragen[0]
    assert "A:" in erste and "B:" in erste
    assert "Wie geht es dir?" in " ".join(doppel.fragen)


# --- Randomisierung --------------------------------------------------------


def test_die_reihenfolge_der_kandidaten_streut(tmp_path: Path):
    """Über viele Fälle darf nicht immer derselbe auf A landen."""

    from backend.lernen.blindbewertung import vorlage_bauen, Kandidat

    lagen = [
        vorlage_bauen(
            kennung=f"L{n}-fall_{n}",
            aufgabe="Aufgabe",
            erster=Kandidat(LEHRER, "L", ()),
            zweiter=Kandidat(SCHUELER, "S", ()),
        ).a.herkunft
        for n in range(200)
    ]
    assert set(lagen) == {LEHRER, SCHUELER}
    anteil = lagen.count(LEHRER) / len(lagen)
    assert 0.35 <= anteil <= 0.65, f"unausgeglichen: {anteil:.2f}"


def test_dieselbe_kennung_ergibt_dieselbe_reihenfolge(tmp_path: Path):
    """Reproduzierbar - ein Nachprüfer kommt auf dieselbe Zuordnung."""

    doppel_a = _Bewerterdoppel()
    doppel_b = _Bewerterdoppel()
    _fahren(tmp_path / "a", doppel_a)
    _fahren(tmp_path / "b", doppel_b)

    assert doppel_a.fragen == doppel_b.fragen


# --- Der Vertrag mit dem Bewertermodell ------------------------------------


def test_jedes_paar_wird_zweimal_vorgelegt(tmp_path: Path):
    """Positionskontrolle: einmal so herum, einmal andersherum."""

    doppel = _Bewerterdoppel()
    ergebnis = _fahren(tmp_path, doppel)

    # Drei Paare, zwei Durchgaenge - sechs Fragen an den Bewerter.
    assert len(doppel.fragen) == 6
    assert set(doppel.wunschprovider) == {"ollama_fast"}
    assert ergebnis["paare"] == 3
    assert ergebnis["bewerter"] == "ollama_fast"
    assert ergebnis["guete"]["durchgaenge"] == 6


def test_die_beiden_durchgaenge_zeigen_die_antworten_vertauscht(tmp_path: Path):
    """Sonst waere die Gegenprobe keine."""

    doppel = _Bewerterdoppel()
    _fahren(tmp_path, doppel)

    erster, zweiter = doppel.fragen[0], doppel.fragen[1]
    def _teil(text: str, marke: str) -> str:
        return text.split(marke, 1)[1].split("Antwort", 1)[0].strip()

    assert _teil(erster, "Antwort A:") == _teil(zweiter, "Antwort B:")
    assert _teil(erster, "Antwort B:") == _teil(zweiter, "Antwort A:")


def test_ein_teilnehmer_darf_nicht_bewerten(tmp_path: Path):
    """Die Befangenheitsschranke greift vor dem ersten Paar."""

    doppel = _Bewerterdoppel()
    with pytest.raises(Befangen):
        _fahren(tmp_path, doppel, bewerter="ollama")

    assert doppel.fragen == [], "es wurde trotz Befangenheit gefragt"


def test_ein_stummer_bewerter_ergibt_unmoegliche_urteile(tmp_path: Path):
    doppel = _Bewerterdoppel(["", "", "", "", "", ""])
    ergebnis = _fahren(tmp_path, doppel)

    assert ergebnis["guete"]["stabil"] == 0
    assert ergebnis["guete"]["unmoeglich"] == 3
    assert ergebnis["gleichwertig_gesamt"] == 0.0


def test_ein_positionsbewerter_wird_als_instabil_erkannt(tmp_path: Path):
    """Wer immer A sagt, hat die Position bewertet - nicht die Antwort."""

    doppel = _Bewerterdoppel(["URTEIL: A\nGRUND: x"] * 6)
    ergebnis = _fahren(tmp_path, doppel)

    assert ergebnis["guete"]["positionsinstabil"] == 3
    assert ergebnis["guete"]["stabil"] == 0
    assert ergebnis["guete"]["positionswechselrate"] == 1.0
    assert ergebnis["guete"]["a_anteil"] == 1.0
    assert ergebnis["gleichwertig_gesamt"] == 0.0


def test_ein_stabiler_bewerter_ergibt_stabile_urteile(tmp_path: Path):
    """Wer die Antwort bewertet, wechselt beim Vertauschen das Etikett."""

    doppel = _Bewerterdoppel(["URTEIL: A\nGRUND: x", "URTEIL: B\nGRUND: x"] * 3)
    ergebnis = _fahren(tmp_path, doppel)

    assert ergebnis["guete"]["stabil"] == 3
    assert ergebnis["guete"]["positionsinstabil"] == 0
    assert ergebnis["guete"]["positionswechselrate"] == 0.0
    assert ergebnis["guete"]["a_anteil"] == 0.5


def test_die_urteile_werden_angehaengt_und_tragen_beide_durchgaenge(tmp_path: Path):
    doppel = _Bewerterdoppel(["URTEIL: A\nGRUND: knapper.", "URTEIL: B\nGRUND: knapper."] * 3)
    _fahren(tmp_path, doppel)

    zeilen = (tmp_path / "urteile" / "blindurteile.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(zeilen) == 3
    eintraege = [json.loads(z) for z in zeilen]
    for eintrag in eintraege:
        assert eintrag["lauf"] == "T1"
        assert eintrag["bewerter"] == "ollama_fast"
        assert eintrag["kategorie"]
        assert eintrag["zustand"].startswith("stabil")
        # Beide Durchgaenge sind nachlesbar - wer nachrechnen will, kann.
        assert eintrag["etikett_normal"] == "A"
        assert eintrag["etikett_getauscht"] == "B"
        assert eintrag["gewinner_herkunft"] in {LEHRER, SCHUELER}


# --- Paarbildung ------------------------------------------------------------


def test_nur_wo_beide_geantwortet_haben_entsteht_ein_paar(tmp_path: Path):
    ablage = _ablage(tmp_path)
    _fuellen(ablage)
    ablage.ablegen(
        Antwort("T1", "claude_code", "einsam_01", "darstellung", "A?", "nur ich", [], 3.0)
    )

    paare = paare_bilden(ablage, lauf="T1", lehrer="claude_code", schueler="ollama")

    assert len(paare) == 3
    assert all("einsam_01" not in fall.kennung for _kat, fall in paare)


def test_eine_leere_antwort_ergibt_kein_paar(tmp_path: Path):
    ablage = _ablage(tmp_path)
    ablage.ablegen(Antwort("T1", "claude_code", "f1", "kat", "A?", "etwas", [], 1.0))
    ablage.ablegen(Antwort("T1", "ollama", "f1", "kat", "A?", "   ", [], 2.0))

    assert paare_bilden(ablage, lauf="T1", lehrer="claude_code", schueler="ollama") == []


# --- Die Quote --------------------------------------------------------------


def test_die_quote_entsteht_aus_den_paarurteilen():
    eintraege = [
        {"kategorie": "k", "zustand": "stabil_schueler", "gewinner_herkunft": SCHUELER,
         "kennung": "1", "etikett_normal": "A", "etikett_getauscht": "B"},
        {"kategorie": "k", "zustand": "stabil_gleich", "gewinner_herkunft": "",
         "kennung": "2", "etikett_normal": "gleich", "etikett_getauscht": "gleich"},
        {"kategorie": "k", "zustand": "stabil_lehrer", "gewinner_herkunft": LEHRER,
         "kennung": "3", "etikett_normal": "B", "etikett_getauscht": "A"},
        {"kategorie": "k", "zustand": "positionsinstabil", "gewinner_herkunft": "",
         "kennung": "4", "etikett_normal": "A", "etikett_getauscht": "A"},
        {"kategorie": "k", "zustand": UNMOEGLICH, "gewinner_herkunft": "",
         "kennung": "5", "etikett_normal": UNMOEGLICH, "etikett_getauscht": "A"},
    ]
    werte = quoten_je_kategorie(eintraege)["k"]

    assert werte["paare"] == 5
    assert werte["auswertbar"] == 3
    assert werte["positionsinstabil"] == 1
    assert werte["unmoeglich"] == 1
    assert werte["schueler_gewinnt"] == 1
    assert werte["gleichstand"] == 1
    assert werte["lehrer_gewinnt"] == 1
    # Zwei von fuenf Paaren sprechen fuer den Schueler oder fuer Gleichstand;
    # die instabilen und gescheiterten stehen im Nenner.
    assert werte["gleichwertig"] == pytest.approx(0.4)
    assert werte["positionswechselrate"] == pytest.approx(0.2)


def test_ohne_urteile_gibt_es_keine_quote():
    assert quoten_je_kategorie([]) == {}
