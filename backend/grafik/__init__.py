"""Bilder, die der Orb selbst herstellt oder beschafft.

Zwei getrennte Wege, und die Trennung ist Absicht:

* :mod:`backend.grafik.diagramm` zeichnet Diagramme aus Zahlen. Das
  passiert vollstaendig auf dem Rechner, ohne Netz, ohne Konto, ohne
  zusaetzliches Paket. Es kann deshalb nicht ausfallen.
* :mod:`backend.grafik.bildquellen` holt Fotos aus dem Netz und laesst
  Bilder erzeugen. Das kann jederzeit ausfallen - ein Dienst antwortet
  nicht, ein Suchbegriff findet nichts. Jeder Fehler dort ist ein
  sauberes Ergebnis mit Begruendung, nie eine Ausnahme nach oben: Ein
  fehlendes Bild darf ein Dokument nicht verhindern.
"""

from __future__ import annotations

__all__ = ["diagramm", "bildquellen"]
