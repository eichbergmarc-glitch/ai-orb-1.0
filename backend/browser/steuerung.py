"""Steuert ein echtes Browserfenster – öffnen, scrollen, klicken, tippen.

Der Benutzer wollte, dass der Orb einen Browser allgemein bedienen kann, so
wie ein Mensch es täte: eine Seite öffnen, hinunterscrollen, auf einen Knopf
klicken, in ein Feld schreiben, absenden. ``webseite_lesen`` und
``webseite_erkunden`` holen eine Seite nur über HTTP und lesen ihren Text –
das reicht für Nachrichtenseiten, aber nicht für alles, was erst durch
JavaScript entsteht, hinter einer Anmeldung liegt oder auf einen Klick
wartet. Dafür braucht es einen echten Browser.

Getragen wird das von **Playwright**. Zwei Entscheidungen prägen den Aufbau:

* **Ein eigenes, dauerhaftes Profil.** Der Orb startet nicht bei null,
  sondern in einem eigenen Chrome-Profil (``models/browser-profil``). Wer
  sich dort einmal irgendwo anmeldet, ist beim nächsten Mal noch angemeldet –
  genau wie in einem gewöhnlichen Browser. So bleiben die Logins erhalten,
  ohne dass der Orb je ein Passwort sieht.

* **Klicken über nummerierte Elemente.** Ein Sprachmodell kennt keine
  CSS-Pfade. Es sieht eine Seite und will „auf den zweiten Knopf" oder „auf
  Anmelden" klicken. Darum zählt ``elemente()`` die anklickbaren Dinge durch
  und heftet jedem eine unsichtbare Nummer an (``data-orb-idx``); ``klicken``
  und ``tippen`` sprechen genau diese Nummer an. Das ist zuverlässiger als
  jeder Rateversuch über Koordinaten.

Playwright wird **erst beim ersten Gebrauch** geladen. Ist es nicht
installiert, stürzt nichts ab – die Methoden melden ruhig, dass die
Einrichtung (``BROWSER-EINRICHTEN.bat``) noch fehlt.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class BrowserNichtBereit(RuntimeError):
    """Der Browser ließ sich nicht starten – mit einem Grund in Klartext."""


@dataclass
class Element:
    """Ein anklickbares Ding auf der Seite, wie der Orb es zu sehen bekommt."""

    nummer: int
    art: str          # "link", "knopf", "feld", "auswahl", ...
    beschriftung: str
    adresse: str = ""  # bei Links: wohin sie führen

    def zeile(self) -> str:
        kopf = f"{self.nummer}. [{self.art}] {self.beschriftung}".rstrip()
        if self.adresse:
            kopf += f"\n    {self.adresse}"
        return kopf


#: Das JavaScript, das die anklickbaren Elemente einsammelt und nummeriert.
#: Es läuft IM Browser. Jedem sichtbaren Element wird ``data-orb-idx``
#: angeheftet, damit ``klicken``/``tippen`` es hinterher eindeutig trifft.
_SAMMEL_JS = r"""
() => {
  const auswahl = 'a,button,input,textarea,select,[role=button],[role=link],[role=tab],[role=menuitem],[onclick],[tabindex]';
  const knoten = Array.from(document.querySelectorAll(auswahl));
  const raus = [];
  let i = 0;
  for (const el of knoten) {
    const r = el.getBoundingClientRect();
    const stil = getComputedStyle(el);
    const sichtbar = r.width > 1 && r.height > 1
      && r.bottom > 0 && r.top < (window.innerHeight || 0) + 1
      && stil.visibility !== 'hidden' && stil.display !== 'none'
      && stil.opacity !== '0';
    if (!sichtbar) continue;
    const tag = el.tagName.toLowerCase();
    const typ = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && (typ === 'hidden')) continue;
    el.setAttribute('data-orb-idx', String(i));
    const text = (el.innerText || el.value || '').replace(/\s+/g, ' ').trim();
    raus.push({
      idx: i,
      tag: tag,
      typ: typ,
      text: text.slice(0, 90),
      aria: (el.getAttribute('aria-label') || '').slice(0, 90),
      platzhalter: (el.getAttribute('placeholder') || '').slice(0, 90),
      name: (el.getAttribute('name') || '').slice(0, 60),
      wert: (el.getAttribute('value') || '').slice(0, 60),
      href: (el.tagName.toLowerCase() === 'a' ? (el.href || '') : ''),
      rolle: (el.getAttribute('role') || ''),
    });
    i++;
  }
  return raus;
}
"""


def _art_von(roh: dict[str, Any]) -> str:
    """Übersetzt Tag/Typ in ein Wort, das der Orb dem Benutzer sagen kann."""

    tag = str(roh.get("tag", ""))
    typ = str(roh.get("typ", ""))
    rolle = str(roh.get("rolle", ""))
    if tag == "a" or rolle == "link":
        return "link"
    if tag == "button" or rolle in ("button", "tab", "menuitem") or typ in ("submit", "button"):
        return "knopf"
    if tag == "select":
        return "auswahl"
    if tag in ("input", "textarea"):
        if typ in ("checkbox", "radio"):
            return "haken"
        return "feld"
    return "element"


def _beschriftung_von(roh: dict[str, Any]) -> str:
    """Die beste sichtbare Beschriftung – Text vor Aria vor Platzhalter …"""

    for schluessel in ("text", "aria", "platzhalter", "wert", "name"):
        wert = str(roh.get(schluessel, "")).strip()
        if wert:
            return wert
    return "(ohne Beschriftung)"


def elemente_aus_roh(rohliste: list[dict[str, Any]]) -> list[Element]:
    """Formt die Rohdaten aus dem Browser in nummerierte Elemente.

    Reine Funktion, ohne Browser – damit genau diese Übersetzung (die der
    Orb dem Benutzer vorliest) geprüft werden kann, ohne Playwright zu
    starten.
    """

    raus: list[Element] = []
    for roh in rohliste:
        try:
            nummer = int(roh.get("idx"))
        except (TypeError, ValueError):
            continue
        raus.append(
            Element(
                nummer=nummer,
                art=_art_von(roh),
                beschriftung=_beschriftung_von(roh),
                adresse=str(roh.get("href", "") or ""),
            )
        )
    return raus


@dataclass
class Browsersteuerung:
    """Ein einzelnes, dauerhaftes Browserfenster, das der Orb bedient."""

    profil_pfad: Path
    sichtbar: bool = True
    cdp_url: str = ""
    kanal: str = "chrome"
    zeitlimit_ms: int = 15000

    _playwright: Any = field(default=None, init=False, repr=False)
    _kontext: Any = field(default=None, init=False, repr=False)
    _seite: Any = field(default=None, init=False, repr=False)
    _letzte_elemente: list[Element] = field(default_factory=list, init=False, repr=False)
    _sperre: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._sperre = asyncio.Lock()

    # --- Start und Ende -------------------------------------------------------

    @property
    def laeuft(self) -> bool:
        return self._seite is not None

    async def _sicherstellen(self) -> None:
        """Startet den Browser beim ersten Gebrauch – und nur dann."""

        if self._seite is not None:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError as fehler:
            raise BrowserNichtBereit(
                "Die Browsersteuerung ist noch nicht eingerichtet. Fuehre "
                "einmal 'BROWSER-EINRICHTEN.bat' aus, dann kann ich einen "
                "Browser oeffnen."
            ) from fehler

        self._playwright = await async_playwright().start()

        try:
            if self.cdp_url:
                # An ein schon laufendes Chrome anhaengen (mit dem Debug-Port
                # gestartet). Dann sind dessen Anmeldungen da.
                browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
                self._kontext = (
                    browser.contexts[0]
                    if browser.contexts
                    else await browser.new_context()
                )
                self._seite = (
                    self._kontext.pages[0]
                    if self._kontext.pages
                    else await self._kontext.new_page()
                )
            else:
                self.profil_pfad.mkdir(parents=True, exist_ok=True)
                # Ein eigenes, dauerhaftes Profil: Anmeldungen bleiben.
                self._kontext = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profil_pfad),
                    headless=not self.sichtbar,
                    channel=self.kanal or None,
                    args=["--start-maximized"],
                    no_viewport=True,
                )
                self._seite = (
                    self._kontext.pages[0]
                    if self._kontext.pages
                    else await self._kontext.new_page()
                )
            self._seite.set_default_timeout(self.zeitlimit_ms)
            logger.info("Browser gestartet (%s).", "CDP" if self.cdp_url else "eigenes Profil")
        except Exception as fehler:  # noqa: BLE001
            # channel="chrome" schlaegt fehl, wenn kein echtes Chrome da ist.
            #
            # Und genau dann half die Fehlermeldung nicht weiter:
            # 'BROWSER-EINRICHTEN.bat' installiert Chromium ausdruecklich
            # als Rueckfall - nur benutzte den nie jemand, weil in der
            # Konfiguration "chrome" steht und der Start ohne zweiten
            # Versuch aufgab. Der Rueckfall war da und unerreichbar.
            if self.kanal and not self.cdp_url:
                logger.info(
                    "Chrome liess sich nicht starten (%s). Zweiter Versuch "
                    "mit dem mitgelieferten Chromium.",
                    type(fehler).__name__,
                )
                await self._aufraeumen()
                try:
                    self._playwright = await async_playwright().start()
                    self.profil_pfad.mkdir(parents=True, exist_ok=True)
                    self._kontext = (
                        await self._playwright.chromium.launch_persistent_context(
                            user_data_dir=str(self.profil_pfad),
                            headless=not self.sichtbar,
                            args=["--start-maximized"],
                            no_viewport=True,
                        )
                    )
                    self._seite = (
                        self._kontext.pages[0]
                        if self._kontext.pages
                        else await self._kontext.new_page()
                    )
                    self._seite.set_default_timeout(self.zeitlimit_ms)
                    logger.info("Browser gestartet (Chromium, ohne Kanal).")
                    return
                except Exception as zweiter:  # noqa: BLE001
                    await self._aufraeumen()
                    raise BrowserNichtBereit(
                        "Der Browser liess sich nicht starten - weder Chrome "
                        "noch das mitgelieferte Chromium. Ist "
                        "'BROWSER-EINRICHTEN.bat' einmal gelaufen? "
                        f"({type(zweiter).__name__}: {zweiter})"
                    ) from zweiter

            await self._aufraeumen()
            raise BrowserNichtBereit(
                "Der Browser liess sich nicht starten. Ist Chrome installiert "
                "und 'BROWSER-EINRICHTEN.bat' gelaufen? "
                f"({type(fehler).__name__}: {fehler})"
            ) from fehler

    async def _aufraeumen(self) -> None:
        for name in ("_kontext", "_playwright"):
            obj = getattr(self, name, None)
            if obj is None:
                continue
            try:
                schliessen = getattr(obj, "close", None) or getattr(obj, "stop", None)
                if schliessen is not None:
                    ergebnis = schliessen()
                    if asyncio.iscoroutine(ergebnis):
                        await ergebnis
            except Exception:  # noqa: BLE001
                pass
        self._kontext = None
        self._playwright = None
        self._seite = None
        self._letzte_elemente = []

    async def schliessen(self) -> str:
        async with self._sperre:
            if self._seite is None:
                return "Es war kein Browser offen."
            await self._aufraeumen()
            return "Browser geschlossen."

    # --- Bedienen -------------------------------------------------------------

    async def oeffnen(self, url: str) -> dict[str, str]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        async with self._sperre:
            await self._sicherstellen()
            await self._seite.goto(url, wait_until="domcontentloaded")
            return await self._stand()

    async def _stand(self) -> dict[str, str]:
        titel = await self._seite.title()
        return {"titel": titel or "", "url": self._seite.url}

    async def stand(self) -> dict[str, str]:
        async with self._sperre:
            await self._sicherstellen()
            return await self._stand()

    async def elemente(self, grenze: int = 40) -> list[Element]:
        async with self._sperre:
            await self._sicherstellen()
            roh = await self._seite.evaluate(_SAMMEL_JS)
            self._letzte_elemente = elemente_aus_roh(roh)
            return self._letzte_elemente[: max(1, grenze)]

    async def _sicher_ziel(self, ziel: str) -> str:
        """Deutet ``ziel`` als Nummer oder als sichtbaren Text und gibt einen
        eindeutigen Selektor (``[data-orb-idx="N"]``) zurueck."""

        knapp = ziel.strip().lstrip("#").strip()
        if knapp.isdigit():
            return f'[data-orb-idx="{int(knapp)}"]'

        # Sonst: ueber den Text das passende Element finden. Dafuer muessen
        # die Elemente frisch eingesammelt sein (sie tragen dann die idx).
        if not self._letzte_elemente:
            roh = await self._seite.evaluate(_SAMMEL_JS)
            self._letzte_elemente = elemente_aus_roh(roh)
        klein = ziel.lower()
        for el in self._letzte_elemente:
            if klein in el.beschriftung.lower():
                return f'[data-orb-idx="{el.nummer}"]'
        raise BrowserNichtBereit(
            f"Auf der Seite ist nichts, das zu '{ziel}' passt. Lass dir mit "
            "der Aktion 'elemente' zeigen, was anklickbar ist."
        )

    async def klicken(self, ziel: str) -> dict[str, str]:
        async with self._sperre:
            await self._sicherstellen()
            selektor = await self._sicher_ziel(ziel)
            await self._seite.click(selektor)
            # Nach dem Klick kann sich alles geaendert haben.
            self._letzte_elemente = []
            try:
                await self._seite.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:  # noqa: BLE001 - nicht jeder Klick laedt neu.
                pass
            return await self._stand()

    async def tippen(self, ziel: str, text: str, absenden: bool = False) -> dict[str, str]:
        async with self._sperre:
            await self._sicherstellen()
            selektor = await self._sicher_ziel(ziel)
            await self._seite.fill(selektor, text)
            if absenden:
                await self._seite.press(selektor, "Enter")
                self._letzte_elemente = []
                try:
                    await self._seite.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:  # noqa: BLE001
                    pass
            return await self._stand()

    async def taste(self, name: str) -> dict[str, str]:
        async with self._sperre:
            await self._sicherstellen()
            await self._seite.keyboard.press(name)
            self._letzte_elemente = []
            return await self._stand()

    async def scrollen(self, richtung: str = "runter", betrag: int = 0) -> dict[str, str]:
        async with self._sperre:
            await self._sicherstellen()
            hoehe = await self._seite.evaluate("() => window.innerHeight") or 800
            schritt = betrag if betrag > 0 else int(hoehe * 0.85)
            if richtung in ("hoch", "oben", "hinauf", "zurueck"):
                schritt = -schritt
            elif richtung in ("anfang", "ganz_oben"):
                await self._seite.evaluate("() => window.scrollTo(0, 0)")
                self._letzte_elemente = []
                return await self._stand()
            elif richtung in ("ende", "ganz_unten"):
                await self._seite.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                self._letzte_elemente = []
                return await self._stand()
            await self._seite.mouse.wheel(0, schritt)
            self._letzte_elemente = []
            return await self._stand()

    async def zurueck(self) -> dict[str, str]:
        async with self._sperre:
            await self._sicherstellen()
            await self._seite.go_back(wait_until="domcontentloaded")
            self._letzte_elemente = []
            return await self._stand()

    async def lesen(self, grenze: int = 4000) -> str:
        async with self._sperre:
            await self._sicherstellen()
            text = await self._seite.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
        text = _eindampfen(str(text or ""))
        if len(text) > grenze:
            text = text[:grenze] + "\n[… gekürzt]"
        return text


def _eindampfen(roh: str) -> str:
    import re

    roh = re.sub(r"[ \t]+", " ", roh)
    roh = re.sub(r" ?\n ?", "\n", roh)
    roh = re.sub(r"\n{3,}", "\n\n", roh)
    return roh.strip()
