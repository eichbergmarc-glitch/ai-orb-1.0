"""Die Folien zur Vorlesung.

## Warum überhaupt Folien

Der Benutzer hat es genau begründet: „damit auch über den visuellen Weg
gelernt wird". Ein Vortrag, der nur gesprochen wird, verlangt vom Zuhörer,
Namen, Jahreszahlen und Gliederungen im Kopf zu behalten, während er
gleichzeitig zuhört. Genau daran scheitert Zuhören. Was auf einer Folie
steht, muss man nicht behalten - man kann es ansehen.

## Die Bauweise und warum sie so gewählt ist

Eine einzige HTML-Datei, in der alles steckt: Schrift, Farben, Bilder als
``data:``-Adressen. Das hat drei Gründe, und alle drei sind praktisch:

1. **Sie läuft ohne alles.** Kein PowerPoint, keine Zusatzbibliothek, kein
   Playwright - der Browser, der ohnehin auf jedem Rechner ist, genügt.
   Das ist hier keine Kleinigkeit: Der Browserzugriff des Orb hängt an
   Playwright, und Playwright fehlt auf dem Rechner des Benutzers seit
   Wochen. Eine Präsentation, die daran scheitert, wäre keine.
2. **Sie bleibt.** Eine Datei, die man behalten, verschicken und in einem
   Jahr wieder öffnen kann. Bilder aus dem Netz sind eingebettet und nicht
   verlinkt - eine Vorlesung, die nach sechs Monaten nur noch kaputte
   Bildsymbole zeigt, wäre wertlos.
3. **Der Orb kann sie führen.** Wird sie vom eigenen Webserver des Orb
   ausgeliefert, fragt die Seite ihn im Sekundentakt, welche Folie gerade
   dran ist - er blättert also selbst, während er spricht. Als blosse
   Datei geöffnet, schlägt diese Abfrage fehl, und dann blättert man mit
   der Leertaste. Beides ist vorgesehen, keines ist Bedingung.

## Was auf eine Folie gehört

Nicht der Sprechtext. Das ist der häufigste Fehler bei Vorlesungsfolien
und der Grund, warum so viele unerträglich sind: Wenn dasteht, was ohnehin
gesagt wird, liest das Publikum, statt zuzuhören, und ist schneller fertig
als der Vortragende. Deshalb trägt jede Folie hier zwei getrennte Dinge -
``punkte`` für die Leinwand, ``sprechtext`` für den Mund. Der Sprechtext
steht nie auf der Folie.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Die Farben. Dieselben wie in ``backend/grafik/diagramm.py`` - ein
#: Diagramm auf einer Folie soll nicht aussehen, als käme es von woanders.
AKZENT = "#4a9eff"
AKZENT_WARM = "#eb6834"
GRUND = "#0e1420"
GRUND_HELL = "#161e2e"
SCHRIFT = "#e8eef7"
SCHRIFT_MATT = "#93a4bd"

#: Grösser laden wir kein Bild in eine Folie. Zwanzig Bilder zu je zwei
#: Megabyte ergäben eine Datei, die kein Browser mehr gern öffnet.
_BILD_HOECHSTENS = 3 * 1024 * 1024

ARTEN = ("titel", "abschnitt", "inhalt", "bild", "zitat", "quellen")


@dataclass(slots=True)
class Folie:
    """Eine Folie.

    ``punkte`` steht auf der Leinwand, ``sprechtext`` wird gesagt. Sie
    dürfen einander ergänzen, aber nie wiederholen.
    """

    art: str = "inhalt"
    titel: str = ""
    punkte: tuple[str, ...] = ()
    #: Pfad einer Bilddatei auf diesem Rechner. Sie wird eingebettet.
    bild: str = ""
    bildnachweis: str = ""
    zitat: str = ""
    quelle: str = ""
    sprechtext: str = ""

    def __post_init__(self) -> None:
        if self.art not in ARTEN:
            self.art = "inhalt"


@dataclass(slots=True)
class Praesentation:
    """Eine ganze Vorlesung als Folienfolge."""

    titel: str
    untertitel: str = ""
    fach: str = ""
    folien: list[Folie] = field(default_factory=list)

    def hinzufuegen(self, folie: Folie) -> Folie:
        self.folien.append(folie)
        return folie

    @property
    def sprechtexte(self) -> tuple[str, ...]:
        """Was zu jeder Folie gesagt wird - in der Reihenfolge der Folien."""

        return tuple(f.sprechtext for f in self.folien)

    def html(self) -> str:
        """Baut die vollständige, in sich geschlossene Seite."""

        folien_html = "\n".join(
            _folie_html(folie, nummer) for nummer, folie in enumerate(self.folien)
        )
        daten = json.dumps(
            {"anzahl": len(self.folien), "titel": self.titel},
            ensure_ascii=False,
        )
        return _RAHMEN.format(
            titel=html.escape(self.titel or "Vorlesung"),
            folien=folien_html,
            daten=daten,
            akzent=AKZENT,
            akzent_warm=AKZENT_WARM,
            grund=GRUND,
            grund_hell=GRUND_HELL,
            schrift=SCHRIFT,
            schrift_matt=SCHRIFT_MATT,
        )

    def speichern(self, pfad: Path) -> Path:
        """Schreibt die Seite und gibt den Pfad zurück."""

        pfad = Path(pfad)
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(self.html(), encoding="utf-8")
        logger.info(
            "Präsentation gespeichert: %s (%d Folien, %d KB).",
            pfad, len(self.folien), pfad.stat().st_size // 1024,
        )
        return pfad


# ---------------------------------------------------------------------------
#  Die einzelnen Folien
# ---------------------------------------------------------------------------


def _bild_einbetten(pfad: str) -> str:
    """Macht aus einer Bilddatei eine ``data:``-Adresse.

    Schlägt es fehl, kommt eine leere Zeichenkette zurück und die Folie
    entsteht ohne Bild. Ein fehlendes Bild darf nie eine Vorlesung
    verhindern - dieselbe Regel wie in ``bildquellen``.
    """

    if not pfad:
        return ""
    datei = Path(pfad)
    try:
        if not datei.is_file():
            logger.info("Bild für die Folie nicht gefunden: %s", pfad)
            return ""
        groesse = datei.stat().st_size
        if groesse > _BILD_HOECHSTENS:
            logger.info(
                "Bild %s ist mit %d KB zu gross für eine Folie.", pfad, groesse // 1024
            )
            return ""
        roh = datei.read_bytes()
    except OSError as fehler:
        logger.info("Bild %s liess sich nicht lesen: %s", pfad, fehler)
        return ""

    typ = mimetypes.guess_type(datei.name)[0] or "image/png"
    return f"data:{typ};base64," + base64.b64encode(roh).decode("ascii")


def _punkte_html(punkte: tuple[str, ...]) -> str:
    if not punkte:
        return ""
    sauber = [" ".join(str(p).split()) for p in punkte if str(p).strip()]
    if not sauber:
        return ""

    strukturiert: list[tuple[str, str]] = []
    for punkt in sauber:
        teile = re.split(r"\s+(?:—|–|-|:)\s+", punkt, maxsplit=1)
        if len(teile) == 2 and 1 <= len(teile[0].split()) <= 6:
            strukturiert.append((teile[0].strip(), teile[1].strip()))
        else:
            strukturiert.append(("", punkt))

    # Benannte Fachbegriffe sind keine gewoehnlichen Bullets. Eine eigene
    # Karte pro Begriff macht Ordnung und Vollstaendigkeit sofort sichtbar.
    if 2 <= len(strukturiert) <= 6 and sum(bool(titel) for titel, _ in strukturiert) >= 2:
        karten = "".join(
            "<article class='punkt-karte'>"
            f"<span class='punkt-nr'>{nummer}</span>"
            f"<div><h3>{html.escape(titel or f'Punkt {nummer}')}</h3>"
            f"<p>{html.escape(text)}</p></div></article>"
            for nummer, (titel, text) in enumerate(strukturiert, start=1)
        )
        return f"<div class='punkt-raster'>{karten}</div>"

    zeilen = "".join(f"<li>{html.escape(p)}</li>" for p in sauber)
    return f"<ul>{zeilen}</ul>"


def _folie_html(folie: Folie, nummer: int) -> str:
    titel = html.escape(folie.titel)
    teile: list[str] = []
    bild = _bild_einbetten(folie.bild)
    figur = ""
    if bild:
        nachweis = (
            f"<figcaption>{html.escape(folie.bildnachweis)}</figcaption>"
            if folie.bildnachweis
            else ""
        )
        figur = f"<figure><img src='{bild}' alt='{titel}'>{nachweis}</figure>"

    if folie.art == "titel":
        teile.append(f"<h1>{titel}</h1>")
        if folie.punkte:
            teile.append(
                f"<p class='untertitel'>{html.escape(' · '.join(folie.punkte))}</p>"
            )
        if figur:
            teile.append(figur)
    elif folie.art == "abschnitt":
        teile.append("<p class='marke'>Abschnitt</p>")
        teile.append(f"<h1>{titel}</h1>")
        if figur:
            teile.append(figur)
    elif folie.art == "zitat":
        teile.append(f"<blockquote>{html.escape(folie.zitat)}</blockquote>")
        if folie.quelle:
            teile.append(f"<p class='quelle'>{html.escape(folie.quelle)}</p>")
        if figur:
            teile.append(figur)
    else:
        if titel:
            teile.append(f"<h2>{titel}</h2>")
        textblock = _punkte_html(folie.punkte)
        if folie.quelle:
            textblock += f"<p class='quelle'>{html.escape(folie.quelle)}</p>"
        if figur:
            teile.append(
                "<div class='folien-grid'>"
                f"<div class='textblock'>{textblock}</div>{figur}</div>"
            )
        else:
            teile.append(textblock)

    if folie.quelle and folie.art not in ("zitat", "inhalt", "bild"):
        teile.append(f"<p class='quelle'>{html.escape(folie.quelle)}</p>")

    klassen = f"folie folie--{folie.art}" + (" folie--mit-bild" if bild else "")
    return (
        f"<section class='{klassen}' data-nr='{nummer}'>"
        f"<div class='inhalt'>{''.join(teile)}</div></section>"
    )


# ---------------------------------------------------------------------------
#  Der Rahmen
# ---------------------------------------------------------------------------

#: Die Seite selbst. Bewusst ohne jede fremde Bibliothek: Was hier steht,
#: laeuft in zehn Jahren noch und in jedem Browser.
_RAHMEN = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titel}</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; overflow: hidden; }}
  body {{
    background: {grund};
    color: {schrift};
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    font-size: clamp(18px, 1.9vw, 30px);
    line-height: 1.55;
  }}
  .buehne {{ position: relative; height: 100%; }}
  .folie {{
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    padding: 6vh 8vw 10vh;
    opacity: 0; visibility: hidden;
    transition: opacity .32s ease;
  }}
  .folie.aktiv {{ opacity: 1; visibility: visible; }}
  .inhalt {{ width: 100%; max-width: 76rem; }}

  h1 {{ font-size: 2.6em; line-height: 1.15; margin: 0 0 .4em; font-weight: 600; }}
  h2 {{
    font-size: 1.7em; line-height: 1.2; margin: 0 0 .8em; font-weight: 600;
    color: {akzent};
  }}
  ul {{ margin: 0; padding-left: 1.1em; }}
  li {{ margin: 0 0 .55em; }}
  li::marker {{ color: {akzent}; }}
  .folien-grid {{ display: grid; grid-template-columns: minmax(0, 1.16fr) minmax(300px, .84fr);
    align-items: center; gap: clamp(1rem, 3vw, 3rem); }}
  .textblock {{ min-width: 0; }}
  .punkt-raster {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: clamp(.55rem, 1.1vw, 1rem); }}
  .punkt-karte {{ display: grid; grid-template-columns: 1.8em minmax(0, 1fr);
    gap: .55em; padding: .65em; border-radius: .55em;
    background: #16243a; border: 1px solid #2d4668; border-left: 4px solid {akzent}; }}
  .punkt-nr {{ width: 1.65em; height: 1.65em; display: grid; place-items: center;
    border-radius: 50%; background: {akzent}; color: {grund}; font-size: .68em;
    font-weight: 800; }}
  .punkt-karte h3 {{ margin: 0 0 .24em; color: {schrift}; font-size: .86em;
    line-height: 1.15; }}
  .punkt-karte p {{ margin: 0; color: {schrift_matt}; font-size: .65em;
    line-height: 1.35; }}
  .untertitel {{ color: {schrift_matt}; font-size: 1.15em; margin: 0; }}
  .marke {{
    color: {akzent_warm}; text-transform: uppercase; letter-spacing: .18em;
    font-size: .7em; margin: 0 0 .8em;
  }}
  blockquote {{
    margin: 0; font-size: 1.6em; line-height: 1.4; font-style: italic;
    border-left: 4px solid {akzent}; padding-left: .8em;
  }}
  .quelle {{ color: {schrift_matt}; font-size: .78em; margin: 1.4em 0 0; }}
  figure {{ margin: 1.4em 0 0; text-align: center; }}
  .folien-grid figure {{ margin: 0; }}
  figure img {{
    max-width: 100%; max-height: 58vh; border-radius: 12px;
    background: {grund_hell};
  }}
  figcaption {{ color: {schrift_matt}; font-size: .72em; margin-top: .6em; }}

  /* Steht ein Bild neben Text, teilen sie sich die Breite - sonst
     schrumpft die Schrift, damit das Bild passt, und niemand liest mehr
     mit. */
  @media (min-aspect-ratio: 4/3) {{
    .folie--mit-bild .inhalt {{ max-width: 74rem; }}
    .folie--mit-bild figure {{ margin-top: 1em; }}
  }}
  @media (max-width: 820px), (max-aspect-ratio: 4/3) {{
    .folien-grid {{ grid-template-columns: 1fr; gap: .7rem; }}
    .folien-grid figure img {{ max-height: 30vh; }}
    .punkt-raster {{ grid-template-columns: 1fr; }}
  }}

  .fuss {{
    position: absolute; left: 0; right: 0; bottom: 0;
    display: flex; align-items: center; gap: 1rem;
    padding: 0 8vw 2.4vh; color: {schrift_matt}; font-size: .72em;
  }}
  .balken {{ flex: 1; height: 3px; background: {grund_hell}; border-radius: 2px; }}
  .balken > i {{
    display: block; height: 100%; width: 0; background: {akzent};
    border-radius: 2px; transition: width .32s ease;
  }}
  .hinweis {{
    position: absolute; top: 2.4vh; right: 8vw;
    color: {schrift_matt}; font-size: .68em; opacity: .55;
  }}
</style>
</head>
<body>
<div class="buehne" id="buehne">
{folien}
</div>
<div class="hinweis" id="hinweis">Leertaste oder Pfeiltasten zum Blättern</div>
<div class="fuss">
  <span id="zaehler">1 / 1</span>
  <span class="balken"><i id="balken"></i></span>
</div>
<script>
(function () {{
  var daten = {daten};
  var folien = Array.prototype.slice.call(document.querySelectorAll('.folie'));
  var zaehler = document.getElementById('zaehler');
  var balken = document.getElementById('balken');
  var hinweis = document.getElementById('hinweis');
  var jetzt = -1;
  var vonHand = false;

  function zeigen(nr) {{
    if (!folien.length) return;
    nr = Math.max(0, Math.min(folien.length - 1, nr));
    if (nr === jetzt) return;
    if (folien[jetzt]) folien[jetzt].classList.remove('aktiv');
    folien[nr].classList.add('aktiv');
    jetzt = nr;
    zaehler.textContent = (nr + 1) + ' / ' + folien.length;
    balken.style.width = ((nr + 1) / folien.length * 100) + '%';
  }}

  function weiter(schritt) {{ vonHand = true; zeigen(jetzt + schritt); }}

  document.addEventListener('keydown', function (e) {{
    if (e.key === ' ' || e.key === 'ArrowRight' || e.key === 'PageDown') {{
      e.preventDefault(); weiter(1);
    }} else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {{
      e.preventDefault(); weiter(-1);
    }} else if (e.key === 'Home') {{ vonHand = true; zeigen(0); }}
    else if (e.key === 'End') {{ vonHand = true; zeigen(folien.length - 1); }}
    else if (e.key === 'f' || e.key === 'F') {{
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen();
    }}
  }});
  document.addEventListener('click', function (e) {{
    weiter(e.clientX < window.innerWidth * 0.25 ? -1 : 1);
  }});

  // Der Orb blaettert selbst, wenn die Seite von seinem eigenen Server
  // kommt. Als blosse Datei geoeffnet schlaegt die Abfrage fehl - dann
  // bleibt es beim Blaettern von Hand, und niemand merkt einen Unterschied.
  // Sobald von Hand geblaettert wurde, gibt der Orb die Fuehrung ab: Wer
  // zurueckblaettert, will nachlesen und nicht wieder nach vorn gerissen
  // werden.
  function nachfragen() {{
    fetch('stand', {{ cache: 'no-store' }})
      .then(function (a) {{ return a.ok ? a.json() : null; }})
      .then(function (d) {{
        if (!d || vonHand) return;
        if (typeof d.folie === 'number') zeigen(d.folie);
        if (d.ende) hinweis.textContent = 'Ende der Vorlesung';
      }})
      .catch(function () {{ /* Datei statt Server - kein Fehler. */ }});
  }}
  setInterval(nachfragen, 900);
  nachfragen();

  zeigen(0);
  setTimeout(function () {{ hinweis.style.opacity = '0'; }}, 6000);
}})();
</script>
</body>
</html>
"""
