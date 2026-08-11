"""Die Browsersteuerung des Orb.

Ein eigenes, vom Orb gesteuertes Browserfenster: öffnen, scrollen, klicken,
tippen, Formulare bedienen. Getragen von Playwright, aber so gekapselt, dass
der Rest des Backends nichts davon wissen muss.
"""

from backend.browser.steuerung import Browsersteuerung

__all__ = ["Browsersteuerung"]
