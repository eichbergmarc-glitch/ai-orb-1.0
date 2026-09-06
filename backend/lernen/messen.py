"""Der Messlauf: dieselben Aufgaben, zwei Modelle, gleiche Bedingungen.

Aufruf auf dem Rechner des Benutzers::

    python -m backend.lernen.messen --modell claude_code --lauf L1
    python -m backend.lernen.messen --modell ollama      --lauf L1
    python -m backend.lernen.messen --bericht

Warum ein eigenes Programm und kein Test: Ein Test sagt bestanden oder
nicht. Hier geht es um Zahlen - Erfolgsquote, Zeit bis zum ersten Wort,
Werkzeugerfolg -, und die entstehen nur, wenn wirklich beide Modelle
laufen. Diese Datei kann deshalb nichts messen, solange sie nicht auf dem
Rechner mit Ollama und Claude Code läuft.

Der Lauf schreibt nach ``data/lernen/messungen.jsonl``. Jede Zeile ist eine
Messung, es wird nur angehängt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import subprocess
import time
from typing import Any

from backend.lernen.bewertung import (
    deterministisch_pruefen,
    halluzination_verdacht,
    rubrik_pruefen,
    werkzeuge_pruefen,
    zusammenfuehren,
)
from backend.lernen.faehigkeitskatalog import KATEGORIEN, Pruefstueck, katalog
from backend.lernen.messwerte import Messreihe, Messung, zusammenfassen
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


def umgebung() -> dict[str, Any]:
    """Was über Rechner, Ollama und Modelle feststellbar ist.

    Ohne diese Angaben ist eine Messung nicht vergleichbar: Dieselbe
    Aufgabe auf einem anderen Rechner ergibt andere Zahlen.
    """

    bericht: dict[str, Any] = {
        "system": platform.platform(),
        "prozessor": platform.processor() or "unbekannt",
        "python": platform.python_version(),
        "kerne": None,
        "ollama_version": "",
        "ollama_modelle": [],
    }
    try:
        import os

        bericht["kerne"] = os.cpu_count()
    except Exception:  # noqa: BLE001
        pass

    ollama = shutil.which("ollama")
    if not ollama:
        bericht["ollama_version"] = "nicht gefunden"
        return bericht
    for befehl, schluessel in (
        (["ollama", "--version"], "ollama_version"),
        (["ollama", "list"], "ollama_modelle"),
    ):
        try:
            ausgabe = subprocess.run(  # noqa: S603
                befehl, capture_output=True, text=True, timeout=20
            ).stdout.strip()
        except Exception as fehler:  # noqa: BLE001
            bericht[schluessel] = f"nicht abfragbar ({fehler})"
            continue
        if schluessel == "ollama_modelle":
            bericht[schluessel] = [
                zeile.split()[0]
                for zeile in ausgabe.splitlines()[1:]
                if zeile.strip()
            ]
        else:
            bericht[schluessel] = ausgabe
    return bericht



#: Woran sich ein Anmeldeproblem im Fehlertext erkennen laesst. Bewusst
#: eine kleine, nachlesbare Liste statt einer Ahnung: Was hier nicht
#: draufsteht, gilt als fachlicher Werkzeugfehler und damit als Sache des
#: Modells - im Zweifel also strenger, nicht milder.
_ANMELDEWOERTER: tuple[str, ...] = (
    "anmeld", "login", "credential", "token", "unauthorized", "401", "403",
    "zugangsdaten", "nicht angemeldet", "oauth", "authentifiz",
)

#: Woran eine fehlende Umgebung zu erkennen ist.
_UMGEBUNGSWOERTER: tuple[str, ...] = (
    "nicht erreichbar", "connection", "netzwerk", "network", "timeout",
    "zeitueberschreitung", "dns", "unreachable",
)


def fehlerklasse_einordnen(
    stueck: Pruefstueck,
    *,
    angemeldete_werkzeuge: set[str],
    gelaufen: list[str],
    werkzeugspur: list[dict[str, Any]],
    erfolg: bool,
    hinweis: str,
) -> tuple[str, bool]:
    """Ordnet einen Fehlschlag ein und sagt, ob er dem Modell anzulasten ist.

    Die Reihenfolge ist die Aussagekraft: Zuerst wird geprueft, ob die
    Umgebung ueberhaupt erlaubt hat, die Aufgabe zu loesen. Erst wenn sie
    das tat, wird ueber das Modell geurteilt.

    Returns:
        Die Fehlerklasse und ob die Messung etwas ueber das Modell aussagt.
    """

    if erfolg:
        return "keiner", True

    # 1. Verlangt das Pruefstueck ein Werkzeug, das gar nicht angemeldet
    #    ist? Dann konnte kein Modell der Welt bestehen.
    fehlend = [w for w in stueck.werkzeuge if w not in angemeldete_werkzeuge]
    if fehlend:
        return "umgebung", False

    # 2. Ist ein Werkzeug an Zugangsdaten oder am Netz gescheitert?
    for lauf in werkzeugspur:
        if lauf.get("erfolg"):
            continue
        text = str(lauf.get("fehler", "")).lower()
        if any(wort in text for wort in _ANMELDEWOERTER):
            return "authentifizierung", False
        if any(wort in text for wort in _UMGEBUNGSWOERTER):
            return "umgebung", False

    # 3. Ist der Lauf selbst an der Umgebung gescheitert (kein Modell
    #    erreichbar, Zeitueberschreitung)?
    kleiner_hinweis = str(hinweis or "").lower()
    if kleiner_hinweis:
        if any(wort in kleiner_hinweis for wort in _ANMELDEWOERTER):
            return "authentifizierung", False
        if any(wort in kleiner_hinweis for wort in _UMGEBUNGSWOERTER):
            return "umgebung", False

    # Ab hier ist die Umgebung aus dem Schneider - es geht ums Modell.
    if stueck.werkzeuge:
        if not gelaufen:
            return "werkzeugauswahl", True
        if any(w not in gelaufen for w in stueck.werkzeuge):
            return "werkzeugauswahl", True
        if any(not lauf.get("erfolg") for lauf in werkzeugspur):
            return "werkzeugausfuehrung", True
    return "modell", True


async def _einen_fall_messen(
    manager: Any,
    stueck: Pruefstueck,
    *,
    modell: str,
    lauf: str,
    betriebsart: str,
    werkzeugschleife: Any | None = None,
    antwort_ablegen: Any | None = None,
    angemeldete_werkzeuge: set[str] | None = None,
) -> Messung:
    """Führt EIN Prüfstück gegen EIN Modell aus und bewertet es.

    Mit Werkzeugschleife, wenn eine übergeben wird - und das ist der
    Unterschied zwischen "das Modell sagt, es habe nachgesehen" und "es hat
    nachgesehen". Gemessen wird der ganze Ablauf: welche Werkzeuge liefen,
    ob sie erfolgreich waren, wie viele Runden es brauchte und warum die
    Schleife endete.
    """

    from backend.orchestrator.providers.base_provider import ChatMessage

    kat = katalog()
    messung = Messung(
        katalog_version=kat.version,
        katalog_pruefsumme=kat.pruefsumme,
        lauf=lauf,
        kategorie=stueck.kategorie,
        fall=stueck.kennung,
        modell=modell,
        betriebsart=betriebsart,
        werkzeuge_verlangt=list(stueck.werkzeuge),
    )

    begonnen = time.perf_counter()
    antwort = ""
    gelaufen: list[str] = []
    alle_erfolgreich = True

    # Werkzeuge kommen zum Einsatz, wenn das Pruefstueck welche verlangt
    # ODER wenn die Kategorie ohne sie gar nicht messbar waere. Die uebrigen
    # Kategorien werden weiterhin an der reinen Antwort gemessen - eine
    # Werkzeugschleife um eine Wissensfrage misst nur Umwege.
    mit_werkzeugen = werkzeugschleife is not None and (
        stueck.werkzeuge
        or stueck.kategorie in {"werkzeugwahl", "rechnerbedienung", "gedaechtnis"}
    )

    try:
        if mit_werkzeugen:
            ergebnis = await werkzeugschleife.run(stueck.aufgabe, actor="messlauf")
            antwort = getattr(ergebnis, "answer", "") or ""
            messung.runden = int(getattr(ergebnis, "rounds", 0) or 0)
            messung.abbruchgrund = str(getattr(ergebnis, "stopped_because", ""))
            for run in getattr(ergebnis, "runs", []) or []:
                name = str(getattr(run, "tool", ""))
                erfolg = bool(getattr(getattr(run, "result", None), "ok", False))
                fehler = str(getattr(getattr(run, "result", None), "error", "") or "")
                gelaufen.append(name)
                alle_erfolgreich = alle_erfolgreich and erfolg
                messung.werkzeugspur.append(
                    {
                        "werkzeug": name,
                        "erfolg": erfolg,
                        "fehler": fehler[:200],
                        "sekunden": round(float(getattr(run, "seconds", 0.0)), 3),
                        "ausgabe_zeichen": len(
                            str(getattr(getattr(run, "result", None), "output", "") or "")
                        ),
                    }
                )
        else:
            ergebnis = await manager.chat(
                [ChatMessage(role="user", content=stueck.aufgabe)],
                preferred=modell,
            )
            antwort = getattr(ergebnis, "text", "") or ""
            messung.ttft_sekunden = getattr(ergebnis, "latency_seconds", 0.0) or 0.0
    except Exception as fehler:  # noqa: BLE001 - ein Ausfall ist ein Messwert.
        messung.hinweis = f"{type(fehler).__name__}: {fehler}"[:200]
        alle_erfolgreich = False

    messung.dauer_sekunden = time.perf_counter() - begonnen
    messung.tokens = max(1, len(antwort) // 4)
    if messung.dauer_sekunden > 0:
        messung.tokens_pro_sekunde = messung.tokens / messung.dauer_sekunden
    messung.werkzeuge_gelaufen = gelaufen

    urteile = []
    if stueck.art == "deterministisch":
        urteile.append(deterministisch_pruefen(stueck, antwort))
    elif stueck.art == "werkzeug":
        urteile.append(werkzeuge_pruefen(stueck, gelaufen, alle_erfolgreich))
        # Ein Werkzeugfall mit Erwartung prueft zwei Dinge: dass das
        # Werkzeug lief UND dass seine Ausgabe in der Antwort ankam. Sonst
        # bestuende auch, wer das Werkzeug ruft und das Ergebnis ignoriert.
        if stueck.erwartet or stueck.verboten:
            urteile.append(deterministisch_pruefen(stueck, antwort))
    else:
        urteile.append(rubrik_pruefen(stueck, antwort, bewerter="ersatz"))

    # Als werkzeugtechnisch erfolgreich gilt nur, was wirklich lief.
    werkzeuge_ok = (
        all(w in gelaufen for w in stueck.werkzeuge) and alle_erfolgreich
        if stueck.werkzeuge
        else True
    )

    gesamt = zusammenfuehren(
        urteile,
        halluzination=halluzination_verdacht(antwort, stueck),
        werkzeuge_erfolgreich=werkzeuge_ok,
    )
    messung.erfolg = gesamt.erfolg
    messung.punkte = gesamt.punkte
    messung.hoechstpunkte = gesamt.hoechstpunkte
    messung.halluzination = gesamt.halluzination
    messung.werkzeuge_erfolgreich = werkzeuge_ok
    messung.bewerter = ", ".join(sorted({u.bewerter for u in gesamt.teilurteile}))
    messung.fehlerklasse, messung.messbar = fehlerklasse_einordnen(
        stueck,
        angemeldete_werkzeuge=set(angemeldete_werkzeuge or ()),
        gelaufen=gelaufen,
        werkzeugspur=messung.werkzeugspur,
        erfolg=messung.erfolg,
        hinweis=messung.hinweis,
    )
    if not messung.messbar:
        logger.warning(
            "%s / %s: %s - das ist ein Umgebungsbefund, kein Modellbefund; "
            "die Messung zaehlt nicht gegen das Modell.",
            modell,
            stueck.kennung,
            messung.fehlerklasse,
        )

    # Die Antwort wird aufgehoben, damit sie spaeter verglichen werden kann.
    # Ohne diesen Schritt gaebe es keinen Paarvergleich und damit keine
    # Blindbewertung - genau daran hing `blindurteil_gleichwertig` bis zum
    # 01.09.2026 auf 0 fest.
    if antwort_ablegen is not None:
        try:
            antwort_ablegen(stueck, antwort, gelaufen)
        except Exception:  # noqa: BLE001 - die Ablage darf keine Messung kippen.
            logger.debug("Die Antwort liess sich nicht aufheben.", exc_info=True)

    return messung


async def messen(
    *,
    modell: str,
    lauf: str,
    betriebsart: str = "warm",
    kategorie: str = "",
    mit_werkzeugen: bool = True,
) -> list[Messung]:
    """Misst den ganzen Katalog gegen ein Modell.

    Mit echter Werkzeugschleife (``mit_werkzeugen``), eingehegt durch die
    Erlaubnisliste und ein eigenes Datenverzeichnis - siehe
    ``backend/lernen/messwerkzeuge.py``.
    """

    from backend.events.event_bus import EventBus
    from backend.lernen.messwerkzeuge import (
        alle_messwerkzeuge,
        messregister,
        messumgebung,
    )
    from backend.orchestrator.provider_manager import ProviderManager
    from backend.security.security_engine import SecurityEngine
    from backend.tools.tool_engine import ToolEngine
    from backend.utils.paths import get_data_dir

    # Je Lauf UND Modell ein eigener Ordner. Beim ersten echten Messlauf am
    # 01.09.2026 teilten sich beide Modelle einen: Claude legte in
    # gedaechtnis_02 die Karteikarte an, und Ollama bekam anschliessend fuer
    # dieselbe Aufgabe "Im Stapel 'allgemein' gibt es diese Frage bereits."
    # Das ist kein Unterschied zwischen den Modellen, sondern einer zwischen
    # der ersten und der zweiten Messung - und macht den Vergleich ungueltig.
    # Gleiche Bedingungen heisst: jeder faengt bei derselben Ausgangslage an.
    sauberer_name = "".join(
        zeichen if zeichen.isalnum() or zeichen in "-_" else "_"
        for zeichen in f"{lauf}-{modell}"
    )
    messordner = get_data_dir() / "lernen" / "messumgebung" / sauberer_name
    kat = katalog()
    stuecke = kat.fuer(kategorie) if kategorie else kat.stuecke
    reihe = Messreihe(lauf)
    ergebnisse: list[Messung] = []

    from backend.lernen.paarvergleich import Antwort, Antwortablage

    # Die Ablage steht ABSICHTLICH ausserhalb der Messumgebung: Sie gehoert
    # zur Messreihe, nicht zum abgeschotteten Arbeitsordner des Laufs, und
    # muss den Lauf ueberdauern, damit hinterher verglichen werden kann.
    ablage = Antwortablage()

    def _aufheben(stueck: Pruefstueck, antwort: str, werkzeuge: list[str]) -> None:
        ablage.ablegen(
            Antwort(
                lauf=lauf,
                modell=modell,
                fall=stueck.kennung,
                kategorie=stueck.kategorie,
                aufgabe=stueck.aufgabe,
                antwort=antwort,
                werkzeuge=list(werkzeuge),
                zeitpunkt=time.time(),
            )
        )

    with messumgebung(messordner):
        manager = ProviderManager()
        await manager.start()

        schleife = None
        angemeldet: set[str] = set()
        if mit_werkzeugen:
            sicherheit = SecurityEngine(EventBus())
            register = messregister(alle_messwerkzeuge(sicherheit))
            schleife = ToolEngine(
                registry=register,
                security=sicherheit,
                provider_manager=manager,
                event_bus=None,
            )
            logger.info(
                "Messlauf mit %d Werkzeugen: %s",
                len(register),
                ", ".join(sorted(register.names())),
            )

            # Ein Pruefstueck, dessen Werkzeug gar nicht angemeldet ist, misst
            # nichts: Das Modell kann eine Faehigkeit nicht zeigen, die es in
            # diesem Lauf nicht gibt, und die Messung schreibt trotzdem
            # "nicht bestanden". Beim ersten echten Lauf am 01.09.2026 traf
            # das rechner_02 (verlangt 'termine_ansehen'; die Kalender-
            # werkzeuge fehlen ohne Google-Anmeldung) - beide Modelle standen
            # dort auf 0 von 2, ohne dass das etwas ueber sie aussagt.
            # Das bleibt ein Fehlschlag, wird aber nicht mehr stillschweigend
            # zu einem: Es steht als Warnung im Protokoll.
            angemeldet = set(register.names())
            fehlend = sorted(
                {
                    werkzeug
                    for stueck in stuecke
                    for werkzeug in stueck.werkzeuge
                    if werkzeug not in angemeldet
                }
            )
            if fehlend:
                logger.warning(
                    "ACHTUNG: %d verlangte Werkzeuge sind in diesem Lauf nicht "
                    "angemeldet: %s. Die betroffenen Pruefstuecke koennen nicht "
                    "bestanden werden - ihr Ergebnis sagt nichts ueber das "
                    "Modell aus.",
                    len(fehlend),
                    ", ".join(fehlend),
                )

        for stueck in stuecke:
            if betriebsart == "offline" and not stueck.offline_loesbar:
                continue
            messung = await _einen_fall_messen(
                manager,
                stueck,
                modell=modell,
                lauf=lauf,
                betriebsart=betriebsart,
                werkzeugschleife=schleife,
                antwort_ablegen=_aufheben,
                angemeldete_werkzeuge=angemeldet,
            )
            reihe.anhaengen(messung)
            ergebnisse.append(messung)
            logger.info(
                "%s / %s: %s (%.1f s, Werkzeuge: %s)",
                modell,
                stueck.kennung,
                "bestanden" if messung.erfolg else "nicht bestanden",
                messung.dauer_sekunden,
                ", ".join(messung.werkzeuge_gelaufen) or "keine",
            )

        await manager.stop()

    return ergebnisse



async def blindvergleich_fahren(
    *, lauf: str, lehrer: str, schueler: str, bewerter: str
) -> dict[str, Any]:
    """Führt den Paarvergleich eines Laufs mit einem echten Modell durch.

    Das ist der Anschluss, der bis zum 01.09.2026 fehlte: Der Messlauf
    bewertete jede Antwort für sich, verglich aber nie zwei miteinander.
    Übergabebedingung 4 fragt genau danach, und ohne diesen Aufruf blieb
    ``blindurteil_gleichwertig`` dauerhaft 0.
    """

    from backend.lernen.paarvergleich import blindvergleich
    from backend.orchestrator.provider_manager import ProviderManager

    manager = ProviderManager()
    await manager.start()
    try:
        return await blindvergleich(
            lauf=lauf,
            lehrer=lehrer,
            schueler=schueler,
            bewerter=bewerter,
            manager=manager,
        )
    finally:
        await manager.stop()



def regressionslage() -> tuple[bool, str]:
    """Ob die jüngste Offline-Abnahme grün war - und welche das ist.

    Übergabebedingung 6 verlangt bestandene Regressionstests. Bis zum
    01.09.2026 stand dafür im Prüfergebnis eine feste ``False`` - ehrlich,
    aber nutzlos: Damit konnte keine Kategorie je bestehen, und die
    Bedingung sagte nichts mehr aus. Statt einer Behauptung wird jetzt der
    Bericht gelesen, den ``scripts/offline_abnahme.py`` ablegt. Er trägt
    das Ergebnis eines echten Testlaufs mit nachgewiesener Netzsperre.

    Returns:
        Ob bestanden, und der Name des Berichts als Beleg. Gibt es keinen,
        gilt "nicht bestanden" - fehlende Nachweise sind keine guten.
    """

    from backend.utils.paths import get_logs_dir

    try:
        berichte = sorted(get_logs_dir().glob("offline-abnahme-*.json"))
    except OSError:
        return False, "Berichtsordner nicht lesbar"
    if not berichte:
        return False, "keine Offline-Abnahme gefunden"

    juengster = berichte[-1]
    try:
        daten = json.loads(juengster.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"{juengster.name} ist nicht lesbar"
    return bool(daten.get("bestanden")), juengster.name



#: Der Satz, der fallen muss, wenn der Richter selbst nicht taugt. Er steht
#: hier als Konstante, damit er ueberall gleich lautet und sich nicht in
#: eine mildere Formulierung verwandeln kann.
KEIN_BELASTBARES_URTEIL = (
    "KEINE BELASTBARE UEBERGABEENTSCHEIDUNG - BLINDBEWERTER NICHT "
    "AUSREICHEND STABIL"
)


def gesamturteil_bilden(guete: dict[str, Any], staende: dict[str, Any]) -> dict[str, Any]:
    """Fasst zusammen, was aus einer Serie folgt - in dieser Reihenfolge.

    1. Taugt der Bewerter? Ist seine Positionswechselrate zu hoch, ist gar
       keine Aussage moeglich - weder fuer noch gegen eine Uebergabe. Ein
       untauglicher Richter spricht niemanden frei.
    2. Erst danach: Ist etwas uebergeben worden?

    Die Reihenfolge ist der Punkt. Andersherum koennte man aus einem
    Zufallsergebnis eine Entscheidung machen.
    """

    from backend.config import get_config

    grenze = float(
        get_config().get("lernen.bewerter_max_positionswechsel", 0.30) or 0.30
    )
    wechselrate = float(guete.get("positionswechselrate", 1.0))
    uebergeben = {
        kennung: stand.get("stufe", 0)
        for kennung, stand in staende.items()
        if int(stand.get("stufe", 0)) > 0
    }

    if guete.get("paare", 0) <= 0:
        return {
            "urteil": KEIN_BELASTBARES_URTEIL,
            "grund": "es liegen ueberhaupt keine Blindurteile vor",
            "bewerter_stabil": False,
            "uebergeben": {},
        }
    if wechselrate > grenze:
        return {
            "urteil": KEIN_BELASTBARES_URTEIL,
            "grund": (
                f"Positionswechselrate {wechselrate:.0%} ueber der Grenze von "
                f"{grenze:.0%}: Bei {guete.get('positionsinstabil', 0)} von "
                f"{guete.get('paare', 0)} Paaren entschied die Reihenfolge und "
                "nicht die Antwort."
            ),
            "bewerter_stabil": False,
            "uebergeben": {},
        }
    if not uebergeben:
        return {
            "urteil": "NICHT UEBERGEBEN",
            "grund": (
                "Der Bewerter war stabil genug; die Bedingungen sind trotzdem "
                "nicht erfuellt."
            ),
            "bewerter_stabil": True,
            "uebergeben": {},
        }
    return {
        "urteil": "UEBERGEBEN",
        "grund": "alle Bedingungen erfuellt",
        "bewerter_stabil": True,
        "uebergeben": uebergeben,
    }


def pruefergebnisse_bilden(*, lauf: str, lehrer: str, schueler: str) -> list[Any]:
    """Baut aus Messungen UND Blindurteilen je Kategorie ein Prüfergebnis.

    Jeder Wert entsteht hier aus abgelegten Daten - Erfolgsquoten aus
    ``messungen.jsonl``, die Gleichwertigkeit aus ``blindurteile.jsonl``.
    Nichts davon wird eingetragen, gesetzt oder geschätzt; gibt es keine
    Blindurteile, ist die Quote 0 und die Bedingung fällt durch. Das ist
    die richtige Antwort auf fehlende Daten.
    """

    from backend.lernen.paarvergleich import Urteilsablage, quoten_je_kategorie
    from backend.lernen.uebergabe import Pruefergebnis

    alle = Messreihe(lauf).alle()
    des_laufs = [m for m in alle if m.lauf == lauf]
    quoten = quoten_je_kategorie(Urteilsablage().alle(lauf=lauf))
    tests_gruen, testbeleg = regressionslage()
    logger.info("Regressionslage: %s (%s)", "gruen" if tests_gruen else "rot", testbeleg)

    ergebnisse: list[Any] = []
    for kennung, _titel in KATEGORIEN:
        vom_lehrer = [m for m in des_laufs if m.kategorie == kennung and m.modell == lehrer]
        vom_schueler = [
            m for m in des_laufs if m.kategorie == kennung and m.modell == schueler
        ]
        if not vom_lehrer or not vom_schueler:
            continue

        def _anteil(messungen: list[Any], merkmal: str) -> float:
            # Nur was ueber das Modell etwas aussagt: Ein Fall, der an der
            # Umgebung scheiterte, gehoert nicht in seine Quote.
            grundmenge = [m for m in messungen if getattr(m, "messbar", True)]
            if not grundmenge:
                return 0.0
            treffer = sum(1 for m in grundmenge if getattr(m, merkmal))
            return treffer / len(grundmenge)

        werte = quoten.get(kennung, {})
        ergebnisse.append(
            Pruefergebnis(
                kategorie=kennung,
                lauf=lauf,
                erfolgsquote_lehrer=_anteil(vom_lehrer, "erfolg"),
                erfolgsquote_schueler=_anteil(vom_schueler, "erfolg"),
                halluzination_lehrer=_anteil(vom_lehrer, "halluzination"),
                halluzination_schueler=_anteil(vom_schueler, "halluzination"),
                sicherheitsfehler_lehrer=_anteil(vom_lehrer, "sicherheitsfehler"),
                sicherheitsfehler_schueler=_anteil(vom_schueler, "sicherheitsfehler"),
                werkzeugquote_schueler=_anteil(vom_schueler, "werkzeuge_erfolgreich"),
                blindurteil_gleichwertig=float(werte.get("gleichwertig", 0.0)),
                blindurteile_auswertbar=int(werte.get("auswertbar", 0)),
                positionswechselrate=float(werte.get("positionswechselrate", 0.0)),
                regressionstests_bestanden=tests_gruen,
            )
        )
    return ergebnisse


def bericht() -> dict[str, Any]:
    """Verdichtet alle bisherigen Messungen je Kategorie und Modell."""

    reihe = Messreihe("bericht")
    alle = reihe.alle()
    modelle = sorted({m.modell for m in alle})
    ausgabe: dict[str, Any] = {
        "umgebung": umgebung(),
        "messungen": len(alle),
        "laeufe": sorted({m.lauf for m in alle}),
        "modelle": modelle,
        "kategorien": {},
    }
    for kennung, titel in KATEGORIEN:
        ausgabe["kategorien"][kennung] = {
            "titel": titel,
            "modelle": {
                modell: zusammenfassen(alle, kategorie=kennung, modell=modell)
                for modell in modelle
            },
        }
    return ausgabe



def _protokoll_auf_fehlerkanal() -> None:
    """Schiebt die Bildschirmprotokolle auf den Fehlerkanal.

    ``--bericht`` und ``--umgebung`` geben JSON aus, und JSON mit einer
    Protokollzeile davor ist kein JSON mehr: Beim ersten echten Lauf am
    01.09.2026 begann ``4-bericht.json`` mit "Logging initialisiert ..."
    und liess sich nicht einlesen. Die Protokollzeilen sind trotzdem
    nuetzlich - sie gehoeren nur nicht in die Datenausgabe. Auf dem
    Fehlerkanal bleiben sie sichtbar und lassen sich mit ``2>`` trennen.
    """

    import logging
    import sys as _sys

    for handler in logging.getLogger("ai_orb").handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            handler.setStream(_sys.stderr)


def _hauptprogramm() -> int:
    zerleger = argparse.ArgumentParser(description="Messlauf fuer AI-Orb")
    zerleger.add_argument("--modell", default="", help="Providername, etwa claude_code oder ollama")
    zerleger.add_argument("--lauf", default="", help="Kennung des Laufs, etwa L1")
    zerleger.add_argument("--kategorie", default="", help="nur diese Kategorie")
    zerleger.add_argument(
        "--betriebsart", default="warm", choices=("warm", "kalt", "offline")
    )
    zerleger.add_argument("--umgebung", action="store_true", help="nur die Umgebung zeigen")
    zerleger.add_argument("--bericht", action="store_true", help="Auswertung zeigen")
    zerleger.add_argument(
        "--ohne-werkzeuge",
        action="store_true",
        help="nur die reine Textantwort messen (Kategorien 4-6 werden dann nicht gemessen)",
    )
    zerleger.add_argument(
        "--blindvergleich",
        action="store_true",
        help="die Antworten eines Laufs paarweise blind bewerten lassen",
    )
    zerleger.add_argument(
        "--pruefergebnis",
        action="store_true",
        help="aus Messungen und Blindurteilen die Uebergabebedingungen pruefen",
    )
    zerleger.add_argument("--lehrer", default="claude_code", help="Providername des Lehrers")
    zerleger.add_argument("--schueler", default="ollama", help="Providername des Schuelers")
    zerleger.add_argument(
        "--bewerter",
        default="",
        help="Providername des blinden Bewerters (weder Lehrer noch Schueler)",
    )
    zerleger.add_argument(
        "--eintragen",
        action="store_true",
        help="die Pruefergebnisse in den Uebergabestand eintragen (veraendert Stufen)",
    )
    zerleger.add_argument(
        "--stand-neu-aufbauen",
        nargs="*",
        default=None,
        metavar="LAUF",
        help=(
            "den Uebergabestand verwerfen und aus den genannten Laeufen in "
            "dieser Reihenfolge neu aufbauen - aus abgelegten Messungen und "
            "Blindurteilen, ohne ein Modell zu fragen"
        ),
    )
    argumente = zerleger.parse_args()

    if argumente.umgebung:
        _protokoll_auf_fehlerkanal()
        print(json.dumps(umgebung(), ensure_ascii=False, indent=2))
        return 0
    if argumente.bericht:
        _protokoll_auf_fehlerkanal()
        print(json.dumps(bericht(), ensure_ascii=False, indent=2))
        return 0
    if argumente.blindvergleich:
        if not argumente.lauf or not argumente.bewerter:
            zerleger.error("--lauf und --bewerter werden gebraucht")
        # VOR dem Lauf umschalten, nicht erst vor der Ausgabe: Waehrend des
        # Vergleichs protokollieren Providermanager und Bewerter munter
        # weiter, und jede dieser Zeilen landete sonst vor der ersten
        # geschweiften Klammer. Im Lauf L3 am 01.09.2026 war die
        # Vergleichsdatei genau deshalb kein lesbares JSON.
        _protokoll_auf_fehlerkanal()
        bericht_blind = asyncio.run(
            blindvergleich_fahren(
                lauf=argumente.lauf,
                lehrer=argumente.lehrer,
                schueler=argumente.schueler,
                bewerter=argumente.bewerter,
            )
        )
        print(json.dumps(bericht_blind, ensure_ascii=False, indent=2))
        return 0 if bericht_blind.get("paare") else 1

    if argumente.stand_neu_aufbauen is not None:
        # Der Uebergabestand ist eine ABGELEITETE Entscheidung, keine
        # Messung. Ihn aus unveraenderten Rohdaten neu zu rechnen ist
        # deshalb erlaubt und manchmal noetig - etwa wenn ein Lauf noch
        # mit einer aelteren Fassung der Bedingungspruefung eingetragen
        # wurde und die Laeufe sonst nicht vergleichbar waeren. Die
        # Messungen und Blindurteile selbst ruehrt das nicht an.
        _protokoll_auf_fehlerkanal()
        from backend.lernen.uebergabe import Uebergabe

        laeufe = list(argumente.stand_neu_aufbauen)
        if not laeufe:
            zerleger.error("--stand-neu-aufbauen braucht mindestens einen Lauf")
        uebergabe = Uebergabe()
        for kennung, _titel in KATEGORIEN:
            uebergabe.zuruecksetzen(
                kennung, f"Neuaufbau aus den Laeufen {', '.join(laeufe)}"
            )
        verlauf: list[dict[str, Any]] = []
        for lauf_kennung in laeufe:
            for ergebnis in pruefergebnisse_bilden(
                lauf=lauf_kennung,
                lehrer=argumente.lehrer,
                schueler=argumente.schueler,
            ):
                stand = uebergabe.eintragen(ergebnis)
                verlauf.append(
                    {
                        "lauf": lauf_kennung,
                        "kategorie": ergebnis.kategorie,
                        "blindurteil_gleichwertig": round(
                            ergebnis.blindurteil_gleichwertig, 4
                        ),
                        "blindurteile_auswertbar": ergebnis.blindurteile_auswertbar,
                        "stufe": stand.stufe,
                        "grund": stand.letzter_grund,
                    }
                )
        from backend.lernen.blindbewertung import Paarurteil, bewerterguete
        from backend.lernen.paarvergleich import Urteilsablage

        ablage = Urteilsablage()
        alle_urteile = [
            Paarurteil(
                kennung=str(r.get("kennung", "")),
                zustand=str(r.get("zustand", "")),
                gewinner_herkunft=str(r.get("gewinner_herkunft", "")),
                etikett_normal=str(r.get("etikett_normal", "")),
                etikett_getauscht=str(r.get("etikett_getauscht", "")),
            )
            for lauf_kennung in laeufe
            for r in ablage.alle(lauf=lauf_kennung)
        ]
        guete = bewerterguete(alle_urteile)
        staende = uebergabe.alle_staende()
        urteil = gesamturteil_bilden(guete, staende)
        logger.info("Gesamturteil: %s (%s)", urteil["urteil"], urteil["grund"])
        print(
            json.dumps(
                {
                    "laeufe": laeufe,
                    "gesamturteil": urteil,
                    "bewerterguete": guete,
                    "bewerterguete_je_lauf": {
                        lauf_kennung: bewerterguete(
                            [
                                Paarurteil(
                                    kennung=str(r.get("kennung", "")),
                                    zustand=str(r.get("zustand", "")),
                                    gewinner_herkunft=str(r.get("gewinner_herkunft", "")),
                                    etikett_normal=str(r.get("etikett_normal", "")),
                                    etikett_getauscht=str(r.get("etikett_getauscht", "")),
                                )
                                for r in ablage.alle(lauf=lauf_kennung)
                            ]
                        )
                        for lauf_kennung in laeufe
                    },
                    "verlauf": verlauf,
                    "stand": staende,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if argumente.pruefergebnis:
        if not argumente.lauf:
            zerleger.error("--lauf wird gebraucht")
        _protokoll_auf_fehlerkanal()
        from backend.lernen.uebergabe import Uebergabe

        uebergabe = Uebergabe()
        ergebnisse = pruefergebnisse_bilden(
            lauf=argumente.lauf, lehrer=argumente.lehrer, schueler=argumente.schueler
        )
        tests_gruen, testbeleg = regressionslage()
        from backend.lernen.blindbewertung import Paarurteil, bewerterguete
        from backend.lernen.paarvergleich import Urteilsablage

        alle_urteile = [
            Paarurteil(
                kennung=str(r.get("kennung", "")),
                zustand=str(r.get("zustand", "")),
                gewinner_herkunft=str(r.get("gewinner_herkunft", "")),
                etikett_normal=str(r.get("etikett_normal", "")),
                etikett_getauscht=str(r.get("etikett_getauscht", "")),
            )
            for r in Urteilsablage().alle(lauf=argumente.lauf)
        ]
        ausgabe: dict[str, Any] = {
            "lauf": argumente.lauf,
            "regressionstests_bestanden": tests_gruen,
            "regressionsbeleg": testbeleg,
            "bewerterguete": bewerterguete(alle_urteile),
            "kategorien": {},
        }
        for ergebnis in ergebnisse:
            bestanden, grund = uebergabe.bewerte(ergebnis)
            eintrag: dict[str, Any] = {
                **ergebnis.to_dict(),
                "bedingungen_erfuellt": bestanden,
                "begruendung": grund,
            }
            if argumente.eintragen:
                eintrag["stand"] = uebergabe.eintragen(ergebnis).to_dict()
            else:
                eintrag["stand"] = uebergabe.stand(ergebnis.kategorie).to_dict()
            ausgabe["kategorien"][ergebnis.kategorie] = eintrag
        ausgabe["uebergeben"] = {
            kennung: eintrag["stand"]["stufe"]
            for kennung, eintrag in ausgabe["kategorien"].items()
        }
        print(json.dumps(ausgabe, ensure_ascii=False, indent=2))
        return 0

    if not argumente.modell or not argumente.lauf:
        zerleger.error("--modell und --lauf werden gebraucht")

    ergebnisse = asyncio.run(
        messen(
            modell=argumente.modell,
            lauf=argumente.lauf,
            betriebsart=argumente.betriebsart,
            kategorie=argumente.kategorie,
            mit_werkzeugen=not argumente.ohne_werkzeuge,
        )
    )
    bestanden = sum(1 for m in ergebnisse if m.erfolg)
    print(
        f"{bestanden} von {len(ergebnisse)} Pruefstuecken bestanden "
        f"({argumente.modell}, Lauf {argumente.lauf}, {argumente.betriebsart})."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    raise SystemExit(_hauptprogramm())
