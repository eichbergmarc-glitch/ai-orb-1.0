"""Holt Fotos aus dem Netz und laesst Bilder erzeugen.

Drei Quellen, in dieser Rangfolge:

1. **Wikimedia Commons** - das Bildarchiv hinter Wikipedia. Alles dort ist
   frei nutzbar, jedes Bild hat eine benannte Lizenz und einen Urheber.
2. **Openverse** - der Bildersucher der WordPress-Stiftung, der freie
   Bilder aus vielen Sammlungen zusammenfuehrt. Greift, wenn Commons zum
   Suchbegriff nichts hat.
3. **Pollinations** - erzeugt ein Bild aus einer Beschreibung. Das ist die
   letzte Wahl und nur fuer das gedacht, wofuer es kein Foto gibt:
   Titelbilder, Sinnbilder, Illustrationen.

Keine der drei braucht ein Konto oder einen Schluessel.

## Der Unterschied zwischen Beschaffen und Erfinden

Ein gesuchtes Foto zeigt etwas, das es gibt, und trägt einen Nachweis.
Ein erzeugtes Bild zeigt etwas, das es nie gab. Beides gehoert in ein
Dokument - aber nie ununterscheidbar. Deshalb fuehrt jeder Treffer seinen
Nachweis mit, und erzeugte Bilder bekommen einen, der sie als erzeugt
ausweist. Wer das weglaesst, macht aus einem Bericht eine Faelschung.

## Warum hier nichts hochgeworfen wird

Jede dieser Quellen kann jederzeit ausfallen. Ein Dienst antwortet nicht,
ein Suchbegriff findet nichts, das Netz ist weg. Keiner dieser Faelle darf
ein Dokument verhindern: Die Funktionen geben dann eine leere Liste oder
``None`` zurueck und schreiben den Grund ins Protokoll. Das Dokument
entsteht ohne Bild - mit einem Hinweis, warum.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

_COMMONS = "https://commons.wikimedia.org/w/api.php"
_OPENVERSE = "https://api.openverse.org/v1/images/"
_POLLINATIONS = "https://image.pollinations.ai/prompt/"

#: Wikimedia verlangt eine sprechende Kennung und weist anonyme Zugriffe ab.
_KENNUNG = "AI-Orb/0.26 (lokaler Sprachassistent; Kontakt ueber den Betreiber)"

#: Groesser laedt der Orb nicht herunter. Ein Bild fuer eine PDF-Seite hat
#: keine zwanzig Megabyte - was so gross ist, ist ein Versehen oder Absicht.
_MAX_BYTES = 12 * 1024 * 1024

_ZEITLIMIT = 25

#: Wie gross die laengere Kante eines brauchbaren Bildes mindestens ist.
#:
#: Der Anlass steht in ``data/grafiken/fotos``: Neben Aufnahmen mit 1600
#: Bildpunkten lagen dort Dateien mit 197x240 und 211x240 - Vorschaubilder,
#: die Openverse als Ergebnis liefert. Im Vorlesungsfenster, das mindestens
#: 680 Punkte breit ist, wird so ein Bild auf das Dreifache aufgeblasen. Es
#: ist dann nicht klein, sondern matschig, und genau das hat der Benutzer
#: als "ungenuegend und langweilig" beschrieben.
#:
#: 700 ist die Grenze, unterhalb derer ein Bild im Fenster nicht mehr
#: gewinnt, sondern verliert. Lieber gar kein Bild als ein verwaschenes:
#: Ein fehlendes faellt niemandem auf, ein unscharfes zieht den Blick an
#: und enttaeuscht ihn.
MINDESTKANTE = 700

#: Und die Untergrenze, unter der eine Datei ueberhaupt kein Bild sein kann.
#: In derselben Ablage lagen mehrfach 442 Byte grosse "Bilder" - Platzhalter
#: oder Fehlerseiten, die als JPEG durchgingen und im Fenster landeten.
_MINDESTBYTES = 3000

#: Wie oft ein zu schnelles "Nein" wiederholt wird.
#:
#: Am 18.08.2026 um 11:08 scheiterten drei Bilder in 1.4 Sekunden am
#: selben Grund: ``upload.wikimedia.org`` antwortete dreimal mit 429.
#: Das ist keine Ablehnung, sondern eine Bitte um Geduld - Wikimedia
#: drosselt Stossbetrieb pro Adresse. Der Orb gab trotzdem auf und sagte
#: dem Benutzer, es gebe keine Bilder. Es gab welche.
_WIEDERHOLUNGEN = 2

#: Wartezeiten zwischen den Versuchen, wenn der Dienst keine eigene
#: Angabe macht. Kurz genug, dass niemand denkt, es haenge.
_WARTEN = (1.2, 2.5)

#: Antwortcodes, bei denen sich ein zweiter Versuch lohnt. Alles andere
#: (404, 403) bleibt beim ersten Nein - da hilft Warten nicht.
_GEDULD_CODES = frozenset((429, 500, 502, 503, 504))


class BildquelleFehler(RuntimeError):
    """Eine Bildquelle war nicht zu erreichen oder lieferte Unbrauchbares."""


@dataclass(slots=True)
class Bildtreffer:
    """Ein gefundenes Bild samt allem, was fuer den Nachweis noetig ist."""

    titel: str
    bild_url: str
    seite_url: str = ""
    urheber: str = ""
    lizenz: str = ""
    quelle: str = ""
    breite: int = 0
    hoehe: int = 0

    def nachweis(self) -> str:
        """Die Zeile, die unter dem Bild steht."""

        teile = [teil for teil in (self.titel.strip(), self.urheber.strip()) if teil]
        kopf = " - ".join(teile) if teile else "Bild"
        anhang = ", ".join(t for t in (self.lizenz.strip(), self.quelle.strip()) if t)
        return f"{kopf} ({anhang})" if anhang else kopf

    def to_dict(self) -> dict[str, object]:
        return {
            "titel": self.titel,
            "bild_url": self.bild_url,
            "seite_url": self.seite_url,
            "urheber": self.urheber,
            "lizenz": self.lizenz,
            "quelle": self.quelle,
            "nachweis": self.nachweis(),
            # Die Lehrtafel kann damit unter mehreren fachlich passenden
            # Treffern das ausreichend grosse, gut proportionierte Bild
            # waehlen, statt blind den ersten Suchtreffer zu nehmen.
            "breite": self.breite,
            "hoehe": self.hoehe,
        }


# ---------------------------------------------------------------------------
#  Netz
# ---------------------------------------------------------------------------


def _wartezeit(fehler: urllib.error.HTTPError, versuch: int) -> float:
    """Wie lange vor dem naechsten Versuch gewartet wird.

    Sagt der Dienst selbst, wann er wieder mag (``Retry-After``), gilt
    seine Angabe - aber hoechstens fuenf Sekunden, denn laenger wartet
    niemand vor einem Bild.
    """

    angabe = ""
    with contextlib.suppress(Exception):
        angabe = str(fehler.headers.get("Retry-After") or "")
    with contextlib.suppress(ValueError):
        if angabe.strip():
            return max(0.5, min(5.0, float(angabe.strip())))
    return _WARTEN[min(versuch, len(_WARTEN) - 1)]


def _abrufen(url: str, *, zeitlimit: int = _ZEITLIMIT) -> bytes:
    """Holt eine Datei - und laesst sich von einem 429 nicht abschrecken.

    Wikimedia drosselt Stossbetrieb pro Adresse. Wer vier Vorschaubilder
    in einer Sekunde anfordert, bekommt drei Absagen, obwohl alle vier
    Bilder existieren und frei sind. Genau das stand am 18.08.2026 im
    Protokoll. Ein kurzes Warten loest es.
    """

    anfrage = urllib.request.Request(url, headers={"User-Agent": _KENNUNG})
    letzter: BildquelleFehler | None = None
    for versuch in range(_WIEDERHOLUNGEN + 1):
        try:
            with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
                daten = antwort.read(_MAX_BYTES + 1)
        except urllib.error.HTTPError as fehler:
            letzter = BildquelleFehler(f"Der Dienst antwortete mit {fehler.code}.")
            if fehler.code not in _GEDULD_CODES or versuch >= _WIEDERHOLUNGEN:
                raise letzter from fehler
            pause = _wartezeit(fehler, versuch)
            logger.info(
                "%s antwortete mit %d - noch einmal in %.1f s.",
                urllib.parse.urlsplit(url).netloc, fehler.code, pause,
            )
            time.sleep(pause)
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as fehler:
            raise BildquelleFehler(
                f"Der Dienst war nicht erreichbar: {fehler}"
            ) from fehler
        if len(daten) > _MAX_BYTES:
            raise BildquelleFehler("Die Datei ist zu gross.")
        return daten
    raise letzter or BildquelleFehler("Der Dienst antwortete nicht.")


def _json_abrufen(url: str, *, zeitlimit: int = _ZEITLIMIT) -> dict:
    roh = _abrufen(url, zeitlimit=zeitlimit)
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as fehler:
        raise BildquelleFehler("Die Antwort war kein gueltiges JSON.") from fehler
    return daten if isinstance(daten, dict) else {}


def _gross_genug(breite: int, hoehe: int) -> bool:
    """Ob die gemeldeten Masse fuer das Vorlesungsfenster reichen.

    Unbekannte Masse (0) gelten als in Ordnung: Manche Quellen melden sie
    nicht, und ein Bild wegen einer fehlenden Angabe zu verwerfen waere
    strenger als noetig. Beim Speichern wird ohnehin nachgemessen - dort
    gibt es das Bild selbst und nicht nur eine Auskunft darueber.
    """

    if breite <= 0 and hoehe <= 0:
        return True
    return max(breite, hoehe) >= MINDESTKANTE


def _entkleiden(text: str) -> str:
    """Nimmt HTML aus den Angaben - Commons liefert Urheber als Verweis."""

    ohne = re.sub(r"<[^>]+>", " ", str(text or ""))
    ohne = ohne.replace("&amp;", "&").replace("&nbsp;", " ").replace("&quot;", '"')
    return re.sub(r"\s+", " ", ohne).strip()


# ---------------------------------------------------------------------------
#  Suchen
# ---------------------------------------------------------------------------


def _commons_suchen(begriff: str, anzahl: int, zeitlimit: int) -> list[Bildtreffer]:
    frage = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": begriff,
            # Namensraum 6 ist der Dateibereich.
            "gsrnamespace": "6",
            "gsrlimit": str(max(1, min(anzahl * 3, 30))),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|mime",
            # Eine gerenderte Vorschau: damit kommen auch SVG und TIFF als
            # brauchbares Rasterbild an, und riesige Originale bleiben aussen
            # vor. 1600 statt 1400, weil genau bei 1600 auch abgelegt wird -
            # jede kleinere Anforderung verschenkte Schaerfe, die die Ablage
            # danach nicht mehr herstellen kann.
            "iiurlwidth": "1600",
        }
    )
    daten = _json_abrufen(f"{_COMMONS}?{frage}", zeitlimit=zeitlimit)

    treffer: list[Bildtreffer] = []
    for seite in (daten.get("query", {}) or {}).get("pages", []) or []:
        infos = seite.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if not str(info.get("mime", "")).startswith("image/"):
            continue
        zusatz = info.get("extmetadata", {}) or {}

        def feld(name: str) -> str:
            eintrag = zusatz.get(name) or {}
            return _entkleiden(eintrag.get("value", "")) if isinstance(eintrag, dict) else ""

        breite = int(info.get("thumbwidth") or info.get("width") or 0)
        hoehe = int(info.get("thumbheight") or info.get("height") or 0)
        if not _gross_genug(breite, hoehe):
            continue

        titel = str(seite.get("title", "")).removeprefix("Datei:").removeprefix("File:")
        treffer.append(
            Bildtreffer(
                titel=Path(titel).stem.replace("_", " ").strip() or begriff,
                bild_url=str(info.get("thumburl") or info.get("url") or ""),
                seite_url=str(info.get("descriptionurl", "")),
                urheber=feld("Artist"),
                lizenz=feld("LicenseShortName") or feld("License"),
                quelle="Wikimedia Commons",
                breite=breite,
                hoehe=hoehe,
            )
        )
        if len(treffer) >= anzahl:
            break
    return treffer


def _openverse_suchen(begriff: str, anzahl: int, zeitlimit: int) -> list[Bildtreffer]:
    frage = urllib.parse.urlencode(
        {"q": begriff, "page_size": str(max(1, min(anzahl * 2, 20))), "mature": "false"}
    )
    daten = _json_abrufen(f"{_OPENVERSE}?{frage}", zeitlimit=zeitlimit)

    treffer: list[Bildtreffer] = []
    for eintrag in daten.get("results", []) or []:
        adresse = str(eintrag.get("url") or "")
        if not adresse:
            continue
        breite = int(eintrag.get("width") or 0)
        hoehe = int(eintrag.get("height") or 0)
        # Von hier kamen die 197x240 grossen Vorschaubilder. Openverse nennt
        # die Masse mit; wer sie nicht liest, laedt sie herunter.
        if not _gross_genug(breite, hoehe):
            continue
        lizenz = str(eintrag.get("license", "")).upper()
        fassung = str(eintrag.get("license_version", ""))
        treffer.append(
            Bildtreffer(
                titel=str(eintrag.get("title") or begriff),
                bild_url=adresse,
                seite_url=str(eintrag.get("foreign_landing_url") or ""),
                urheber=str(eintrag.get("creator") or ""),
                lizenz=f"{lizenz} {fassung}".strip(),
                quelle="Openverse",
                breite=breite,
                hoehe=hoehe,
            )
        )
        if len(treffer) >= anzahl:
            break
    return treffer


def bilder_suchen(
    begriff: str,
    *,
    anzahl: int = 3,
    zeitlimit: int = _ZEITLIMIT,
    akzeptieren: Callable[[Bildtreffer], bool] | None = None,
) -> list[Bildtreffer]:
    """Sucht freie Bilder zu einem Begriff.

    Erst Wikimedia Commons, dann Openverse. Faellt eine Quelle aus, wird das
    protokolliert und die naechste versucht; faellt alles aus, kommt eine
    leere Liste zurueck - kein Fehler nach oben.
    """

    begriff = (begriff or "").strip()
    if not begriff:
        return []

    gefunden: list[Bildtreffer] = []
    for name, sucher in (("Wikimedia Commons", _commons_suchen), ("Openverse", _openverse_suchen)):
        try:
            fehlen = anzahl - len(gefunden)
            # Bei fachlicher Relevanzpruefung mehr Metadaten ansehen, aber nur
            # passende Dateien herunterladen. So blockieren zwei irrelevante
            # Commons-Treffer nicht mehr den anschliessenden Openverse-Versuch.
            pruefmenge = min(12, max(fehlen, fehlen * 4)) if akzeptieren else fehlen
            kandidaten = sucher(begriff, pruefmenge, zeitlimit)
            if akzeptieren is not None:
                kandidaten = [treffer for treffer in kandidaten if akzeptieren(treffer)]
            gefunden.extend(kandidaten[:fehlen])
        except BildquelleFehler as fehler:
            logger.info("Bildsuche bei %s fehlgeschlagen: %s", name, fehler)
        except Exception:  # noqa: BLE001 - eine Bildsuche darf nichts umwerfen.
            logger.exception("Bildsuche bei %s abgebrochen.", name)
        if len(gefunden) >= anzahl:
            break

    logger.info(
        "Bildsuche '%s': %d passende Treffer%s.",
        begriff,
        len(gefunden),
        " (fachlich gefiltert)" if akzeptieren else "",
    )
    return gefunden[:anzahl]


# ---------------------------------------------------------------------------
#  Herunterladen und pruefen
# ---------------------------------------------------------------------------


def _sichern(
    daten: bytes, ziel: Path, *, max_kante: int = 1600, min_kante: int = MINDESTKANTE
) -> Path:
    """Prueft, dass es wirklich ein BRAUCHBARES Bild ist, und schreibt es neu.

    Das Neuschreiben ist kein Selbstzweck: Es wirft alles weg, was ausser
    Bildpunkten in der Datei stand - eingebettete Vorschauen, Ortsangaben,
    Kommentarfelder. Was aus dem Netz kommt, geht so nur als Bild weiter.

    Neu ist die Groessenpruefung. "Ist es ein Bild?" war zu wenig gefragt:
    Ein 197x240 grosses Vorschaubild ist ein Bild, und ein 442 Byte grosser
    Platzhalter ist es formal auch. Beide sind trotzdem unbrauchbar, und
    beide lagen in der Ablage des Benutzers. Wer hier durchfaellt, wird
    verworfen - der Aufrufer nimmt dann den naechsten Treffer.
    """

    from PIL import Image, ImageOps, UnidentifiedImageError

    import io

    if len(daten) < _MINDESTBYTES:
        raise BildquelleFehler(
            f"Die Antwort war mit {len(daten)} Byte zu klein fuer ein Bild."
        )

    try:
        with Image.open(io.BytesIO(daten)) as geoeffnet:
            geoeffnet.load()
            bild = ImageOps.exif_transpose(geoeffnet)
            if max(bild.size) < min_kante:
                raise BildquelleFehler(
                    f"Das Bild ist mit {bild.size[0]}x{bild.size[1]} zu klein; "
                    f"mindestens {min_kante} Bildpunkte an der langen Kante."
                )
            if bild.mode not in ("RGB", "L"):
                bild = bild.convert("RGB")
            bild.thumbnail((max_kante, max_kante))
            ziel.parent.mkdir(parents=True, exist_ok=True)
            if ziel.suffix.lower() in (".jpg", ".jpeg"):
                bild.convert("RGB").save(ziel, format="JPEG", quality=88, optimize=True)
            else:
                bild.save(ziel, format="PNG", optimize=True)
    except UnidentifiedImageError as fehler:
        raise BildquelleFehler("Die Antwort war kein Bild.") from fehler
    except OSError as fehler:
        raise BildquelleFehler(f"Das Bild liess sich nicht speichern: {fehler}") from fehler
    return ziel


def bild_holen(
    treffer: Bildtreffer | str, ziel: Path, *, zeitlimit: int = _ZEITLIMIT
) -> Path | None:
    """Laedt ein gefundenes Bild herunter. ``None``, wenn es nicht klappt."""

    adresse = treffer.bild_url if isinstance(treffer, Bildtreffer) else str(treffer)
    if not adresse.startswith(("http://", "https://")):
        logger.info("Bildadresse verworfen (kein http): %s", adresse[:80])
        return None
    try:
        daten = _abrufen(adresse, zeitlimit=zeitlimit)
        return _sichern(daten, Path(ziel))
    except BildquelleFehler as fehler:
        logger.info("Bild nicht ladbar (%s): %s", adresse[:80], fehler)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Bild nicht ladbar: %s", adresse[:80])
        return None


# ---------------------------------------------------------------------------
#  Erzeugen
# ---------------------------------------------------------------------------


def bild_erzeugen(
    beschreibung: str,
    ziel: Path,
    *,
    breite: int = 1024,
    hoehe: int = 640,
    stil: str = "",
    zeitlimit: int = 90,
) -> Path | None:
    """Laesst ein Bild aus einer Beschreibung erzeugen. ``None`` bei Ausfall.

    Der Dienst ist kostenfrei und ohne Konto - und gibt entsprechend keine
    Zusage, dass er antwortet. Das Zeitlimit ist grosszuegig, weil das
    Erzeugen selbst zwanzig bis sechzig Sekunden dauern kann.
    """

    text = " ".join((beschreibung or "").split())
    if not text:
        return None
    if stil.strip():
        text = f"{text}, {stil.strip()}"

    frage = urllib.parse.urlencode(
        {
            "width": max(256, min(int(breite), 1536)),
            "height": max(256, min(int(hoehe), 1536)),
            # Ohne Wasserzeichen, und ohne den Text noch einmal ins Bild zu
            # schreiben.
            "nologo": "true",
            "enhance": "false",
        }
    )
    adresse = f"{_POLLINATIONS}{urllib.parse.quote(text, safe='')}?{frage}"

    try:
        daten = _abrufen(adresse, zeitlimit=zeitlimit)
        pfad = _sichern(daten, Path(ziel), max_kante=1536)
    except BildquelleFehler as fehler:
        logger.info("Bilderzeugung fehlgeschlagen: %s", fehler)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Bilderzeugung abgebrochen.")
        return None

    logger.info("Bild erzeugt: %s ('%s').", pfad, text[:60])
    return pfad
