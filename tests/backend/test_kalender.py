"""Der Google-Kalender: Zeiten lesen, Termine ansehen, anlegen, ändern, löschen.

Geprüft wird das, was im Alltag schiefgeht:

* Gesagt wird "morgen um halb drei", verlangt wird RFC-3339. Wenn die
  Übersetzung dazwischen nicht sitzt, scheitert jeder dritte Termin an der
  Schreibweise - und der Benutzer hört "verstehe ich nicht", obwohl er sich
  klar ausgedrückt hat.
* Zum Löschen und Ändern kennt niemand die Google-Kennung. Es wird über
  einen Suchbegriff gesucht - und wenn mehrere passen, darf **nicht**
  geraten werden. Das ist die wichtigste Prüfung in dieser Datei.
* Wer sich vor der Kalenderfunktion bei Gmail angemeldet hat, besitzt ein
  gültiges Token ohne Kalenderrecht. Daraus muss ein verständlicher Satz
  werden, kein nacktes 403.

Es wird nie ein echter Kalender angesprochen. Ein Test, der das Löschen am
echten Kalender prüft, löscht einen echten Termin.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.integrations.gmail.oauth import (
    CALENDAR_SCOPE,
    DEFAULT_SCOPE,
    OAuthConfig,
    kalender_bereich_enthalten,
)
from backend.integrations.kalender.client import KalenderClient, KalenderFehler, Termin
from backend.integrations.kalender.erinnerung import Terminerinnerung
from backend.integrations.kalender.zeit import ZeitFehler, dauer_lesen, zeit_lesen
from backend.tools.kalender_tools import (
    TermineAnsehenTool,
    TerminAendernTool,
    TerminErstellenTool,
    TerminLoeschenTool,
)

ZONE = timezone(timedelta(hours=2))
JETZT = datetime(2026, 8, 15, 11, 0, tzinfo=ZONE)  # ein Samstag


# ---------------------------------------------------------------------------
#  Zeiten lesen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gesagt, erwartet",
    [
        ("2026-09-15T14:30", (2026, 9, 15, 14, 30)),
        ("2026-09-15 14:30", (2026, 9, 15, 14, 30)),
        ("15.09.2026 14:30", (2026, 9, 15, 14, 30)),
        ("15.9.2026 14 Uhr", (2026, 9, 15, 14, 0)),
        ("morgen 14 Uhr", (2026, 8, 16, 14, 0)),
        ("heute 18:00", (2026, 8, 15, 18, 0)),
        ("übermorgen 9 Uhr", (2026, 8, 17, 9, 0)),
        ("morgen halb drei", (2026, 8, 16, 14, 30)),
        ("morgen viertel nach zehn", (2026, 8, 16, 10, 15)),
        ("morgen viertel vor acht", (2026, 8, 16, 7, 45)),
        ("Dienstag 9 Uhr", (2026, 8, 18, 9, 0)),
        ("nächsten Montag 8 Uhr", (2026, 8, 17, 8, 0)),
        ("15. September 2026 10:00", (2026, 9, 15, 10, 0)),
        ("morgen abends", (2026, 8, 16, 18, 0)),
        ("morgen mittags", (2026, 8, 16, 12, 0)),
        ("in 2 Stunden", (2026, 8, 15, 13, 0)),
        ("in 30 Minuten", (2026, 8, 15, 11, 30)),
        ("in drei Tagen", (2026, 8, 18, 11, 0)),
        ("in einer Woche", (2026, 8, 22, 11, 0)),
    ],
)
def test_gesprochene_zeiten_werden_richtig_gelesen(gesagt, erwartet):
    wann, _ = zeit_lesen(gesagt, jetzt=JETZT)
    assert (wann.year, wann.month, wann.day, wann.hour, wann.minute) == erwartet


def test_eine_uhrzeit_die_heute_vorbei_ist_meint_morgen():
    # 9 Uhr ist um 11 Uhr vorbei. "Um neun" heisst dann morgen früh -
    # einen Termin in der Vergangenheit anzulegen hilft niemandem.
    wann, _ = zeit_lesen("9 Uhr", jetzt=JETZT)
    assert (wann.day, wann.hour) == (16, 9)

    wann, _ = zeit_lesen("18 Uhr", jetzt=JETZT)
    assert (wann.day, wann.hour) == (15, 18)


def test_ein_datum_ohne_jahr_meint_das_naechste_vorkommen():
    wann, _ = zeit_lesen("3.2. 10:00", jetzt=JETZT)
    assert (wann.year, wann.month, wann.day) == (2027, 2, 3)


def test_ein_datum_ohne_uhrzeit_gilt_als_ganztaegig():
    wann, ganztags = zeit_lesen("2026-09-15", jetzt=JETZT)
    assert ganztags and wann.day == 15

    _, ganztags = zeit_lesen("morgen", jetzt=JETZT)
    assert ganztags


def test_unverstaendliches_wird_abgewiesen_statt_geraten():
    # Eine geratene Zeit im Kalender ist schlimmer als eine Rueckfrage.
    with pytest.raises(ZeitFehler, match="eindeutige Zeit"):
        zeit_lesen("irgendwann demnächst mal", jetzt=JETZT)
    with pytest.raises(ZeitFehler):
        zeit_lesen("", jetzt=JETZT)


@pytest.mark.parametrize(
    "gesagt, minuten",
    [("90 Minuten", 90), ("2 Stunden", 120), ("1,5 Stunden", 90),
     ("zwei Stunden", 120), ("45", 45), ("", 60), ("bisschen", 60)],
)
def test_dauer_wird_gelesen(gesagt, minuten):
    assert dauer_lesen(gesagt) == minuten


# ---------------------------------------------------------------------------
#  Anmeldung und Rechte
# ---------------------------------------------------------------------------


def test_eine_anmeldung_fragt_post_und_kalender_zusammen(monkeypatch):
    monkeypatch.delenv("GMAIL_SCOPE", raising=False)
    monkeypatch.setenv("GMAIL_CLIENT_ID", "x")
    umfang = OAuthConfig.from_env().scope
    assert DEFAULT_SCOPE in umfang and CALENDAR_SCOPE in umfang


def test_ein_selbst_gesetzter_umfang_wird_nicht_ergaenzt(monkeypatch):
    monkeypatch.setenv("GMAIL_SCOPE", "https://www.googleapis.com/auth/gmail.readonly")
    assert OAuthConfig.from_env().scope.endswith("gmail.readonly")


def test_ein_altes_token_ohne_kalenderrecht_wird_erkannt():
    assert not kalender_bereich_enthalten(DEFAULT_SCOPE)
    assert kalender_bereich_enthalten(f"{DEFAULT_SCOPE} {CALENDAR_SCOPE}")


# ---------------------------------------------------------------------------
#  Ein Kalender aus Papier
# ---------------------------------------------------------------------------


class _Auth:
    def __init__(self, *, angemeldet=True, mit_kalender=True, eingerichtet=True):
        self._angemeldet = angemeldet
        self._umfang = f"{DEFAULT_SCOPE} {CALENDAR_SCOPE}" if mit_kalender else DEFAULT_SCOPE
        self.config = type("C", (), {"is_configured": eingerichtet})()

    @property
    def is_authenticated(self):
        return self._angemeldet

    def granted_scopes(self):
        return self._umfang if self._angemeldet else ""

    def access_token(self):
        return "tok"


class _Transport:
    """Ein Kalender im Speicher, der das Wesentliche der API nachbildet."""

    def __init__(self):
        self.eintraege: dict[str, dict[str, Any]] = {}
        self.rufe: list[tuple[str, str]] = []
        self._zaehler = 0
        self.zeitzone = "Europe/Zurich"

    def _neu_id(self):
        self._zaehler += 1
        return f"ev{self._zaehler}"

    def request(self, method, url, *, token, body):
        self.rufe.append((method, url))
        pfad = url.split("/events", 1)[1] if "/events" in url else ""

        if method == "GET" and (not pfad or pfad.startswith("?")):
            from urllib.parse import parse_qs, urlparse

            frage = parse_qs(urlparse(url).query)
            suche = (frage.get("q") or [""])[0].lower()
            von = datetime.fromisoformat(frage["timeMin"][0])
            bis = datetime.fromisoformat(frage["timeMax"][0])
            passend = []
            for eintrag in self.eintraege.values():
                start = eintrag["start"]
                if "dateTime" in start:
                    beginn = datetime.fromisoformat(start["dateTime"])
                else:
                    beginn = datetime.fromisoformat(start["date"]).replace(
                        tzinfo=von.tzinfo
                    )
                if not (von <= beginn <= bis):
                    continue
                if suche and suche not in eintrag.get("summary", "").lower():
                    continue
                passend.append(eintrag)
            passend.sort(key=lambda e: e["start"]["dateTime"])
            return {"items": passend, "timeZone": self.zeitzone}

        kennung = pfad.lstrip("/").split("?")[0]
        if method == "GET":
            if kennung not in self.eintraege:
                raise KalenderFehler("Diesen Termin gibt es nicht (mehr).")
            return self.eintraege[kennung]
        if method == "POST":
            kennung = self._neu_id()
            eintrag = dict(body)
            eintrag["id"] = kennung
            eintrag["htmlLink"] = f"https://calendar.google.com/{kennung}"
            self.eintraege[kennung] = eintrag
            return eintrag
        if method == "PATCH":
            self.eintraege[kennung].update(body)
            return self.eintraege[kennung]
        if method == "DELETE":
            self.eintraege.pop(kennung, None)
            return {}
        raise AssertionError(method)


def _client(**auth_argumente) -> tuple[KalenderClient, _Transport]:
    transport = _Transport()
    return KalenderClient(_Auth(**auth_argumente), transport=transport), transport


def _eintragen(client, titel, beginn, *, dauer=60, ort=""):
    return client.anlegen(
        titel=titel, beginn=beginn, ende=beginn + timedelta(minutes=dauer), ort=ort
    )


# ---------------------------------------------------------------------------
#  Der Client
# ---------------------------------------------------------------------------


def test_ohne_kalenderrecht_kommt_ein_verstaendlicher_satz():
    client, _ = _client(mit_kalender=False)
    assert not client.ist_bereit
    with pytest.raises(KalenderFehler, match="Melde mich bei Gmail an"):
        client.naechste()


def test_ohne_anmeldung_wird_zur_anmeldung_geraten():
    client, _ = _client(angemeldet=False)
    with pytest.raises(KalenderFehler, match="kein Google-Konto angemeldet"):
        client.naechste()


def test_ohne_einrichtung_wird_auf_die_env_verwiesen():
    client, _ = _client(eingerichtet=False, angemeldet=False)
    with pytest.raises(KalenderFehler, match="GMAIL_CLIENT_ID"):
        client.naechste()


def test_termine_kommen_nach_beginn_geordnet():
    client, _ = _client()
    _eintragen(client, "Spaet", JETZT + timedelta(days=2))
    _eintragen(client, "Frueh", JETZT + timedelta(hours=3))
    namen = [t.titel for t in client.termine(von=JETZT, bis=JETZT + timedelta(days=7))]
    assert namen == ["Frueh", "Spaet"]


def test_wiederkehrende_termine_werden_einzeln_abgefragt():
    # Ohne singleEvents kaeme eine Serie als EIN Eintrag zurueck, und
    # "was steht morgen an" waere bei jedem woechentlichen Termin falsch.
    client, transport = _client()
    client.termine(von=JETZT, bis=JETZT + timedelta(days=7))
    assert "singleEvents=true" in transport.rufe[-1][1]


def test_google_utc_wird_in_der_kalender_ortszeit_angezeigt():
    client, transport = _client()
    transport.eintraege["utc-termin"] = {
        "id": "utc-termin",
        "summary": "Bewährungshilfe",
        "start": {"dateTime": "2026-09-02T13:00:00Z"},
        "end": {"dateTime": "2026-09-02T14:00:00Z"},
    }

    termin = client.holen("utc-termin")

    assert termin.beginn.hour == 15
    assert str(termin.beginn.tzinfo) == "Europe/Zurich"
    assert "15 Uhr" in termin.zum_vorlesen(jetzt=JETZT)


def test_eigene_terminzone_ist_staerker_als_die_kalenderzone():
    client, transport = _client()
    transport.eintraege["reise"] = {
        "id": "reise",
        "summary": "Videotermin in UTC",
        "start": {
            "dateTime": "2026-09-02T17:00:00+02:00",
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": "2026-09-02T18:00:00+02:00",
            "timeZone": "UTC",
        },
    }

    termin = client.holen("reise")

    assert termin.beginn.hour == 15
    assert termin.zeitzone == "UTC"
    assert "15 Uhr" in termin.zum_vorlesen(jetzt=JETZT)


def test_google_abgleich_uebernimmt_die_kalenderzone_fuer_schreibzugriffe():
    client, transport = _client()
    client.termine(von=JETZT, bis=JETZT + timedelta(days=1))
    assert client.zustand()["zeitzone"] == "Europe/Zurich"
    assert "timeZone=" not in transport.rufe[-1][1]

    termin = _eintragen(client, "Ortszeit", JETZT + timedelta(hours=2))
    eintrag = transport.eintraege[termin.id]
    assert eintrag["start"]["timeZone"] == "Europe/Zurich"
    assert eintrag["end"]["timeZone"] == "Europe/Zurich"


def test_eine_geaenderte_google_kalenderzone_wird_dynamisch_uebernommen():
    client, transport = _client()
    transport.zeitzone = "UTC"
    transport.eintraege["utc-kalender"] = {
        "id": "utc-kalender",
        "summary": "UTC-Kalender",
        "start": {"dateTime": "2026-08-16T15:00:00Z"},
        "end": {"dateTime": "2026-08-16T16:00:00Z"},
    }

    termine = client.termine(
        von=datetime(2026, 8, 16, 0, tzinfo=timezone.utc),
        bis=datetime(2026, 8, 17, 0, tzinfo=timezone.utc),
    )

    assert termine[0].beginn.hour == 15
    assert str(termine[0].beginn.tzinfo) == "UTC"
    assert client.zustand()["zeitzone"] == "UTC"


def test_ein_termin_ohne_ende_dauert_eine_stunde():
    client, _ = _client()
    termin = client.anlegen(titel="Kurz", beginn=JETZT + timedelta(hours=1))
    assert termin.ende - termin.beginn == timedelta(hours=1)


def test_ein_ende_vor_dem_beginn_wird_abgewiesen():
    client, _ = _client()
    with pytest.raises(KalenderFehler, match="Ende liegt vor dem Beginn"):
        client.anlegen(titel="X", beginn=JETZT, ende=JETZT - timedelta(hours=1))


def test_verschieben_behaelt_die_dauer():
    # "Verschieb das auf 15 Uhr" heisst nicht "und mach eine Stunde daraus".
    client, _ = _client()
    termin = _eintragen(client, "Besprechung", JETZT + timedelta(hours=2), dauer=150)
    neu = client.aendern(termin.id, beginn=JETZT + timedelta(days=1))
    assert neu.ende - neu.beginn == timedelta(minutes=150)


def test_geaendert_wird_mit_patch_damit_nichts_verlorengeht():
    # Bei PUT waere alles weg, was nicht mitgeschickt wurde - Teilnehmer,
    # Erinnerungen, Videokonferenz. Wer die Uhrzeit verschiebt, will nicht
    # die Gaeste verlieren.
    client, transport = _client()
    termin = _eintragen(client, "Mit Gaesten", JETZT + timedelta(hours=2))
    transport.eintraege[termin.id]["attendees"] = [{"email": "anna@example.org"}]
    neu = client.aendern(termin.id, titel="Umbenannt")
    assert any(m == "PATCH" for m, _ in transport.rufe)
    assert neu.teilnehmer == ["anna@example.org"]


def test_loeschen_entfernt_den_termin():
    client, transport = _client()
    termin = _eintragen(client, "Weg damit", JETZT + timedelta(hours=2))
    client.loeschen(termin.id)
    assert termin.id not in transport.eintraege


def test_ein_termin_laesst_sich_vorlesen():
    termin = Termin(
        titel="Zahnarzt", beginn=JETZT + timedelta(days=1, hours=3), ort="Hauptstraße 4"
    )
    satz = termin.zum_vorlesen(jetzt=JETZT)
    # Kein ISO-Datum und keine Sekunden: Das hoert sich niemand an.
    assert "morgen" in satz and "Zahnarzt" in satz and "Hauptstraße 4" in satz
    assert "2026-" not in satz and "T14" not in satz


# ---------------------------------------------------------------------------
#  Die Werkzeuge
# ---------------------------------------------------------------------------


def test_werkzeug_zeigt_was_heute_ansteht():
    client, _ = _client()
    jetzt = datetime.now().astimezone()
    # Ein fester Zeitpunkt am heutigen Kalendertag. ``jetzt + 2 Stunden``
    # wird nach 22 Uhr bereits morgen und machte den Test uhrzeitabhaengig.
    heute = jetzt.replace(hour=12, minute=0, second=0, microsecond=0)
    _eintragen(client, "Heute etwas", heute)
    _eintragen(client, "In zwei Wochen", heute + timedelta(days=14))
    ergebnis = asyncio.run(TermineAnsehenTool(client).execute({"zeitraum": "heute"}))
    assert ergebnis.ok
    assert ergebnis.context["anzahl"] == 1
    assert "Heute etwas" in ergebnis.output


def test_werkzeug_sagt_deutlich_wenn_nichts_ansteht():
    client, _ = _client()
    ergebnis = asyncio.run(TermineAnsehenTool(client).execute({"zeitraum": "heute"}))
    assert ergebnis.ok and "nichts an" in ergebnis.output


def test_werkzeug_traegt_einen_gesprochenen_termin_ein():
    client, transport = _client()
    ergebnis = asyncio.run(TerminErstellenTool(client).execute({
        "titel": "Zahnarzt", "beginn": "morgen 14 Uhr", "dauer": "90 Minuten",
        "ort": "Hauptstraße 4",
    }))
    assert ergebnis.ok, ergebnis.error
    eintrag = transport.eintraege[ergebnis.context["id"]]
    assert eintrag["summary"] == "Zahnarzt"
    assert eintrag["location"] == "Hauptstraße 4"
    beginn = datetime.fromisoformat(eintrag["start"]["dateTime"])
    ende = datetime.fromisoformat(eintrag["end"]["dateTime"])
    assert beginn.hour == 14 and (ende - beginn) == timedelta(minutes=90)


def test_werkzeug_weist_eine_unlesbare_zeit_zurueck():
    client, _ = _client()
    ergebnis = asyncio.run(TerminErstellenTool(client).execute({
        "titel": "X", "beginn": "irgendwann demnächst",
    }))
    assert not ergebnis.ok and "eindeutige Zeit" in ergebnis.error


def test_werkzeug_findet_den_termin_ueber_ein_stichwort():
    client, _ = _client()
    _eintragen(client, "Zahnarzt Kontrolle", datetime.now().astimezone() + timedelta(days=2))
    ergebnis = asyncio.run(TerminAendernTool(client).execute({
        "suchbegriff": "Zahnarzt", "neuer_ort": "Neue Praxis",
    }))
    assert ergebnis.ok, ergebnis.error
    assert ergebnis.context["termin"]["ort"] == "Neue Praxis"


def test_bei_mehreren_treffern_wird_nachgefragt_statt_geraten():
    # Die wichtigste Pruefung hier. Wer beim Loeschen raet, ist kein
    # Assistent mehr, sondern ein Risiko.
    client, transport = _client()
    jetzt = datetime.now().astimezone()
    _eintragen(client, "Zahnarzt Kontrolle", jetzt + timedelta(days=2))
    _eintragen(client, "Zahnarzt Nachbehandlung", jetzt + timedelta(days=9))

    ergebnis = asyncio.run(TerminLoeschenTool(client).execute({"suchbegriff": "Zahnarzt"}))
    assert not ergebnis.ok
    assert "genauer" in ergebnis.error
    assert len(ergebnis.context["treffer"]) == 2
    assert len(transport.eintraege) == 2, "es darf nichts geloescht worden sein"


def test_ein_eindeutiger_treffer_wird_geloescht_und_benannt():
    client, transport = _client()
    _eintragen(client, "Zahnarzt", datetime.now().astimezone() + timedelta(days=2))
    ergebnis = asyncio.run(TerminLoeschenTool(client).execute({"suchbegriff": "Zahnarzt"}))
    assert ergebnis.ok
    # Der Benutzer muss erfahren, WAS geloescht wurde.
    assert "Zahnarzt" in ergebnis.output
    assert transport.eintraege == {}


def test_ohne_treffer_wird_das_gesagt():
    client, _ = _client()
    ergebnis = asyncio.run(TerminLoeschenTool(client).execute({"suchbegriff": "Segelkurs"}))
    assert not ergebnis.ok and "Segelkurs" in ergebnis.error


def test_aendern_ohne_angabe_was_wird_abgewiesen():
    client, _ = _client()
    _eintragen(client, "Termin", datetime.now().astimezone() + timedelta(days=1))
    ergebnis = asyncio.run(TerminAendernTool(client).execute({"suchbegriff": "Termin"}))
    assert not ergebnis.ok and "aendern soll" in ergebnis.error


def test_die_werkzeuge_trennen_lesen_und_aendern():
    # Wer nur wissen will, was ansteht, soll dafuer nicht das Recht zum
    # Loeschen erteilen muessen.
    assert TermineAnsehenTool.permission == "read_calendar"
    for werkzeug in (TerminErstellenTool, TerminAendernTool, TerminLoeschenTool):
        assert werkzeug.permission == "write_calendar"


def test_die_berechtigungen_sind_dem_orb_bekannt():
    # Ohne diesen Eintrag weist die Werkzeugverwaltung die Kalenderwerkzeuge
    # bei der Anmeldung ab - stillschweigend.
    from backend.security.permissions import get_permission

    assert get_permission("read_calendar") is not None
    assert get_permission("write_calendar") is not None


# ---------------------------------------------------------------------------
#  Die Erinnerung
# ---------------------------------------------------------------------------


def _erinnerung(client, **argumente):
    gesagt: list[str] = []

    async def ansagen(satz: str) -> bool:
        gesagt.append(satz)
        return True

    argumente.setdefault("vorlaufzeiten", [60, 10])
    return Terminerinnerung(client, ansagen, **argumente), gesagt


def test_es_wird_rechtzeitig_erinnert():
    client, _ = _client()
    _eintragen(client, "Zahnarzt", datetime.now().astimezone() + timedelta(minutes=9))
    dienst, gesagt = _erinnerung(client)
    asyncio.run(dienst.einmal_nachsehen())
    assert gesagt and "Zahnarzt" in gesagt[0]
    assert "Minuten" in gesagt[0]


def test_dieselbe_erinnerung_kommt_nur_einmal():
    # Alle drei Minuten nachzusehen heisst nicht, alle drei Minuten dasselbe
    # zu sagen.
    client, _ = _client()
    _eintragen(client, "Zahnarzt", datetime.now().astimezone() + timedelta(minutes=9))
    dienst, gesagt = _erinnerung(client)
    asyncio.run(dienst.einmal_nachsehen())
    asyncio.run(dienst.einmal_nachsehen())
    asyncio.run(dienst.einmal_nachsehen())
    assert len(gesagt) == 1


def test_was_laengst_faellig_war_wird_nicht_nachgeholt():
    # Wer den Orb zwoelf Minuten vor dem Termin startet, soll die
    # Stunde-vorher-Erinnerung nicht mehr hoeren.
    client, _ = _client()
    _eintragen(client, "Gleich", datetime.now().astimezone() + timedelta(minutes=12))
    dienst, gesagt = _erinnerung(client, vorlaufzeiten=[60, 10])
    asyncio.run(dienst.einmal_nachsehen())
    assert gesagt == []


def test_ganztaegige_termine_loesen_keine_vorlauferinnerung_aus():
    # Bei ihnen gibt es keine Uhrzeit, auf die sich ein Vorlauf beziehen
    # koennte.
    client, transport = _client()
    termin = _eintragen(client, "Urlaub", datetime.now().astimezone() + timedelta(minutes=5))
    transport.eintraege[termin.id]["start"] = {
        "date": (datetime.now().astimezone()).date().isoformat()
    }
    dienst, gesagt = _erinnerung(client)
    asyncio.run(dienst.einmal_nachsehen())
    assert gesagt == []


def test_bei_erbetener_ruhe_wird_geschwiegen():
    client, _ = _client()
    _eintragen(client, "Zahnarzt", datetime.now().astimezone() + timedelta(minutes=9))
    dienst, gesagt = _erinnerung(client, darf_sprechen=lambda: False)
    asyncio.run(dienst.einmal_nachsehen())
    assert gesagt == []


def test_ohne_kalenderrecht_wird_still_nichts_getan():
    # Alle drei Minuten eine Fehlermeldung vorzulesen waere schlimmer als
    # keine Erinnerung.
    client, _ = _client(mit_kalender=False)
    dienst, gesagt = _erinnerung(client)
    assert asyncio.run(dienst.einmal_nachsehen()) == []
    assert gesagt == []


def test_ein_ausfall_des_kalenders_beendet_die_ueberwachung_nicht():
    client, transport = _client()

    def _streiken(*args, **kwargs):
        raise KalenderFehler("kein Netz")

    transport.request = _streiken
    dienst, gesagt = _erinnerung(client)
    assert asyncio.run(dienst.einmal_nachsehen()) == []
    assert gesagt == []


def test_die_erinnerung_klingt_wie_gesprochen():
    from backend.integrations.kalender.erinnerung import _satz

    jetzt = datetime.now().astimezone()
    termin = Termin(titel="Zahnarzt", beginn=jetzt + timedelta(minutes=10), ort="Praxis")
    assert _satz(termin, 10, jetzt) == "In 10 Minuten: Zahnarzt - Praxis."
    assert _satz(termin, 60, jetzt) == "In einer Stunde: Zahnarzt - Praxis."
    assert _satz(termin, 0, jetzt) == "Zahnarzt beginnt jetzt - Praxis."


# ---------------------------------------------------------------------------
#  Der Weg zum Werkzeug
# ---------------------------------------------------------------------------
#
# Die beste Kalenderanbindung nützt nichts, wenn eine Terminfrage gar nicht
# erst bei ihr ankommt. Zwei Weichen im Ablauf entscheiden darüber, und
# beide standen auf der falschen Seite: "Was steht heute an?" enthält
# "heute" und löste damit eine Internetsuche aus, und "Trag mir morgen den
# Zahnarzt ein" galt als Plauderei ohne Werkzeugbedarf.


@pytest.mark.parametrize(
    "satz",
    [
        "Was steht heute an?",
        "Was habe ich morgen für Termine?",
        "Zeig mir meinen Kalender für diese Woche",
        "Was steht morgen an?",
    ],
)
def test_terminfragen_loesen_keine_internetsuche_aus(satz):
    from backend.orchestrator.orchestrator import braucht_aktuelles

    assert not braucht_aktuelles(satz), (
        "Der eigene Kalender steht nicht im Internet - eine Suche dazu "
        "verdrängt im Kontext genau das, was zur Antwort nötig wäre."
    )


@pytest.mark.parametrize(
    "satz",
    [
        "Was steht heute an?",
        "Trag mir morgen 14 Uhr den Zahnarzt ein",
        "Verschieb den Zahnarzt auf 16 Uhr",
        "Sag den Termin am Freitag ab",
        "Lösch den Termin beim Zahnarzt",
        "Erinner mich an den Zahnarzt",
    ],
)
def test_terminsaetze_behalten_ihre_werkzeuge(satz):
    from backend.orchestrator.orchestrator import braucht_werkzeuge

    assert braucht_werkzeuge(satz), (
        "Ohne Werkzeuge landet der Satz beim lokalen Modell - und das kann "
        "keinen Termin eintragen, sondern nur so tun."
    )


def test_eine_terminfrage_im_wortsinn_bleibt_eine_suchfrage():
    # Die Kehrseite der Kalenderwörter: "Wahltermin" oder "Liefertermin"
    # enthalten "termin", meinen aber den eigenen Kalender nicht.
    from backend.orchestrator.orchestrator import betrifft_eigenes_umfeld

    assert not betrifft_eigenes_umfeld("Wann ist der Wahltermin in den USA?")
    assert not betrifft_eigenes_umfeld("Wie ist der aktuelle Liefertermin?")
    assert betrifft_eigenes_umfeld("Wann habe ich morgen meinen Termin?")
