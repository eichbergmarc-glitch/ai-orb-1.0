"""Lehrtafel vom Sprachmodell geplant (19.11.2026)."""

from backend.studium.tafelplan import auswerten, nachrichten


def test_guter_plan_wird_uebernommen() -> None:
    antwort = """Hier ist der Plan:
    {"titel": "Das Frankenreich unter Karl dem Grossen",
     "darstellung": "timeline",
     "karten": [{"titel": "768", "text": "Karl wird König der Franken."},
                {"titel": "800", "text": "Kaiserkrönung in Rom durch Papst Leo III."},
                {"titel": "814", "text": "Karl stirbt in Aachen; das Reich ist auf dem Höhepunkt."}],
     "bildbegriff": "Karte Frankenreich 814"}"""
    plan = auswerten(antwort)
    assert plan is not None
    assert plan.darstellung == "timeline"
    assert [k["title"] for k in plan.karten] == ["768", "800", "814"]
    assert plan.bildbegriff == "Karte Frankenreich 814"
    assert plan.als_ereignis()["layout"] == "timeline"


def test_abstrakter_abschnitt_ohne_bild() -> None:
    plan = auswerten('{"titel": "Quellenkritik", "darstellung": "enumeration", '
                     '"karten": [{"titel": "Herkunft", "text": "Wer hat die Quelle verfasst?"}, '
                     '{"titel": "Absicht", "text": "Wozu wurde sie geschrieben?"}], "bildbegriff": ""}')
    assert plan is not None and plan.bildbegriff == ""


def test_unbrauchbares_wird_verworfen() -> None:
    assert auswerten("Ich kann das leider nicht.") is None
    assert auswerten('{"titel": "", "karten": []}') is None
    assert auswerten('{"titel": "X", "karten": [{"titel": "a", "text": "nur eine"}]}') is None


def test_unbekannte_darstellung_und_zu_lange_texte() -> None:
    lang = " ".join(["Wort"] * 60)
    plan = auswerten('{"titel": "T", "darstellung": "kreisdiagramm", "karten": ['
                     f'{{"titel": "A", "text": "{lang}"}}, {{"titel": "B", "text": "kurz und klar"}},'
                     '{"titel": "B2", "text": "kurz und klar"}]}')
    assert plan is not None
    assert plan.darstellung == "overview"
    assert len(plan.karten[0]["text"]) <= 170
    assert len(plan.karten) == 2  # doppelte Karte entfernt


def test_vergleich_mit_zu_vielen_karten_wird_aufzaehlung() -> None:
    karten = ",".join(f'{{"titel": "K{i}", "text": "Aussage {i}"}}' for i in range(5))
    plan = auswerten(f'{{"titel": "T", "darstellung": "comparison", "karten": [{karten}]}}')
    assert plan is not None and plan.darstellung == "enumeration"


def test_nachrichten_enthalten_thema_und_abschnitt() -> None:
    rolle, inhalt = nachrichten("Karl wurde 800 gekrönt.", "Mittelalter")[1]
    assert rolle == "user" and "Mittelalter" in inhalt and "800" in inhalt
