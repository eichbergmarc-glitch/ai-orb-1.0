"""Die eigenen Favoriten als durchsuchbare Quellensammlung.

Der Benutzer fragte, ob die Suchmaschinen aus seiner Edge-Favoritenleiste
für geschichtswissenschaftliche Fragen angebunden sind. Die ehrliche
Antwort war: halb.

Der Orb konnte die **Lesezeichen** durchsuchen – Titel, Adresse,
Ordnername. Was auf diesen Seiten steht, blieb ihm verschlossen. Aus einem
Archivportal in der Leiste wurde damit ein Link und keine Quelle: Wer den
Karlsruher Virtuellen Katalog gespeichert hat und nach dem Investiturstreit
fragt, fand sein Lesezeichen nur, wenn zufällig „Investitur" im Titel
stand.

Der Benutzer hat darauf das Entscheidende gesagt: *„er soll aber die
Suchmaschinen die verlinkt sind auch wirklich nutzen … sonst bringt die
Funktion nichts."* Das ist richtig, und es ist derselbe Punkt wie bei der
Internetsuche: Eine Anweisung im Systemprompt, die Favoriten zu befragen,
stand dort seit Wochen – und in keinem einzigen Protokoll taucht ein
Aufruf auf. Was verlässlich geschehen soll, gehört nicht in eine Bitte an
das Sprachmodell, sondern in den Ablauf.

Dieses Modul liefert dafür das Stück, das fehlte: aus den Favoriten die
**Domänen**, in denen dann gezielt gesucht wird.

## Warum Domänen und nicht Adressen

Ein Lesezeichen zeigt auf eine bestimmte Seite – oft die Startseite eines
Portals oder eine Trefferliste von damals. Die nützt für eine neue Frage
nichts. Die Domäne dagegen ist die Quelle selbst: ``site:dhi-roma.it``
durchsucht alles, was dort steht, nicht nur die eine gespeicherte Seite.

## Warum nach Häufigkeit sortiert wird

Wer sieben Lesezeichen aus einem Archivportal hat und eines von einem
Blog, sagt damit etwas über beide. Die Zahl der Lesezeichen je Domäne ist
das ehrlichste Mass für „das ist eine Quelle, mit der ich arbeite" – und
es kostet den Benutzer keine Pflegearbeit.
"""

from __future__ import annotations

import urllib.parse
from collections import Counter

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Was in Favoriten steht, aber keine Fachquelle ist.
#:
#: Ohne diese Liste landet bei jeder Recherche der Videodienst mit, weil
#: fast jeder ein paar Videos gespeichert hat. Sie ist kurz gehalten: Was
#: hier zu viel steht, nimmt dem Benutzer eine Quelle weg, ohne zu fragen.
_ALLTAG: frozenset[str] = frozenset({
    "youtube.com", "youtu.be", "google.com", "google.de", "google.ch",
    "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com",
    "amazon.de", "amazon.com", "ebay.de", "netflix.com", "spotify.com",
    "linkedin.com", "reddit.com", "pinterest.com", "whatsapp.com",
    "outlook.com", "office.com", "microsoft.com", "live.com",
})


def _domaene(url: str) -> str:
    """Die Domäne einer Adresse, ohne ``www.``."""

    try:
        wirt = urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return ""
    if wirt.startswith("www."):
        wirt = wirt[4:]
    return wirt.split(":")[0]


def eigene_domaenen(
    *, ordner: str = "", hoechstens: int = 4, mindestens_je: int = 1
) -> list[str]:
    """Die Domänen, mit denen der Benutzer wirklich arbeitet.

    Args:
        ordner: Nur Favoriten aus diesem Ordner (Teilzeichenfolge, ohne
            Rücksicht auf Gross- und Kleinschreibung). Leer heisst: alle.
        hoechstens: Wie viele Domänen zurückkommen.
        mindestens_je: Wie viele Lesezeichen eine Domäne mindestens haben
            muss. Auf eins gelassen, weil ein einzelnes Lesezeichen auf
            ein Archivportal schon eine Aussage ist.

    Returns:
        Die Domänen, nach Zahl der Lesezeichen absteigend.
    """

    from backend.research.browser_bookmarks import read_bookmarks

    try:
        favoriten = read_bookmarks()
    except Exception:  # noqa: BLE001 - ohne Favoriten laeuft der Rest weiter.
        logger.exception("Die Favoriten liessen sich nicht lesen.")
        return []

    if ordner.strip():
        gesucht = ordner.strip().lower()
        favoriten = [f for f in favoriten if gesucht in f.folder_path.lower()]
        if not favoriten:
            logger.info(
                "Im Favoritenordner %r steht nichts - es wird in allen gesucht.",
                ordner,
            )
            favoriten = read_bookmarks()

    zaehler: Counter[str] = Counter()
    for favorit in favoriten:
        wirt = _domaene(favorit.url)
        if not wirt or wirt in _ALLTAG:
            continue
        zaehler[wirt] += 1

    auswahl = [
        wirt for wirt, anzahl in zaehler.most_common() if anzahl >= mindestens_je
    ][: max(1, hoechstens)]

    if auswahl:
        logger.info(
            "Eigene Quellen aus den Favoriten: %s", ", ".join(auswahl)
        )
    return auswahl
