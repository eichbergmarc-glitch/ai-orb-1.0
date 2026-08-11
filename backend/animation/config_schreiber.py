"""Ändert einzelne Animationswerte in der config.yaml – kommentarschonend.

Der Orb schreibt zur Laufzeit Werte unter ``orb.animation`` um, wenn der
Benutzer die Animation per Sprache anpasst. Das darf die config.yaml nicht
verwüsten: Sie ist über und über kommentiert, und jeder Kommentar erklärt,
warum ein Wert so steht, wie er steht. Ein ``yaml.safe_load`` gefolgt von
``yaml.dump`` würde alle Kommentare wegwerfen.

Deshalb wird hier nicht geparst und neu geschrieben, sondern gezielt EINE
ZAHL in EINER ZEILE ersetzt – der Rest der Datei bleibt Zeichen für Zeichen
gleich.

Die Ersetzung ist auf den Block ``orb.animation`` eingegrenzt (und für
``scale`` auf die Ebene darunter), damit ein Schlüssel, der zufällig
anderswo denselben Namen trägt, nicht mitverändert wird.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


def _zahl(wert: float) -> str:
    """Formt eine Zahl knapp: ganze Zahlen ohne Nachkomma, sonst gerundet."""

    if float(wert).is_integer():
        return str(int(wert))
    return f"{float(wert):.4g}"


def _block_grenzen(zeilen: list[str], eltern: str, kind: str) -> tuple[int, int]:
    """Findet Anfang und Ende des ``kind``-Blocks unter ``eltern``.

    Gibt (start, ende) als Zeilenindizes zurück, start ist die Zeile
    ``  kind:``. Ende ist die erste Zeile, deren Einrückung nicht mehr
    tiefer ist als die von ``kind`` – also wo der Block aufhört.
    """

    tiefe_eltern = None
    for i, z in enumerate(zeilen):
        m = re.match(rf"^(\s*){re.escape(eltern)}:\s*$", z)
        if m:
            tiefe_eltern = len(m.group(1))
            start_suche = i + 1
            break
    else:
        return (-1, -1)

    for i in range(start_suche, len(zeilen)):
        m = re.match(rf"^(\s*){re.escape(kind)}:\s*$", zeilen[i])
        if m and len(m.group(1)) > tiefe_eltern:
            tiefe_kind = len(m.group(1))
            for j in range(i + 1, len(zeilen)):
                roh = zeilen[j]
                if not roh.strip() or roh.lstrip().startswith("#"):
                    continue
                einzug = len(roh) - len(roh.lstrip())
                if einzug <= tiefe_kind:
                    return (i, j)
            return (i, len(zeilen))
    return (-1, -1)


def _ersetze_in(zeilen: list[str], von: int, bis: int, schluessel: str, wert: float) -> bool:
    """Ersetzt die Zahl von ``schluessel`` zwischen den Zeilen [von, bis)."""

    muster = re.compile(rf"^(\s*{re.escape(schluessel)}:\s*)([-\d.]+)(.*)$")
    for i in range(max(0, von), min(bis, len(zeilen))):
        m = muster.match(zeilen[i])
        if m:
            zeilen[i] = f"{m.group(1)}{_zahl(wert)}{m.group(3)}"
            return True
    return False


def schreibe_animationswerte(
    pfad: Path, werte: dict[str, float]
) -> tuple[bool, list[str]]:
    """Schreibt die gegebenen Werte in config.yaml.

    ``scale`` wird auf der ``orb``-Ebene ersetzt, alles andere im Block
    ``orb.animation``.

    Returns:
        (erfolg, nicht_gefunden) – ``erfolg`` ist wahr, wenn mindestens ein
        Wert geschrieben wurde; ``nicht_gefunden`` listet die Schlüssel,
        deren Zeile nicht gefunden wurde.
    """

    text = pfad.read_text(encoding="utf-8")
    zeilen = text.splitlines()

    orb_start, orb_ende = _block_grenzen(zeilen, "orb", "animation")
    # Ebene der orb-Kinder (für scale): der animation-Block liegt darin, also
    # suchen wir scale zwischen dem orb-Doppelpunkt und animation.
    anim_von, anim_bis = orb_start, orb_ende

    geschrieben = 0
    fehlend: list[str] = []
    for schluessel, wert in werte.items():
        if schluessel == "scale":
            # scale steht direkt unter orb:, nicht in animation.
            ok = _ersetze_scale(zeilen, float(wert))
        else:
            if anim_von < 0:
                fehlend.append(schluessel)
                continue
            ok = _ersetze_in(zeilen, anim_von, anim_bis, schluessel, float(wert))
        if ok:
            geschrieben += 1
        else:
            fehlend.append(schluessel)

    if geschrieben:
        neu = "\n".join(zeilen)
        if text.endswith("\n"):
            neu += "\n"
        _sicher_schreiben(pfad, neu)
        logger.info(
            "Animationswerte geschrieben: %s",
            ", ".join(f"{k}={_zahl(v)}" for k, v in werte.items() if k not in fehlend),
        )

    return (geschrieben > 0, fehlend)


def _ersetze_scale(zeilen: list[str], wert: float) -> bool:
    """Ersetzt ``  scale:`` – aber nur die unter ``orb:``, nicht andere."""

    in_orb = False
    for i, z in enumerate(zeilen):
        if re.match(r"^orb:\s*$", z):
            in_orb = True
            continue
        if in_orb and re.match(r"^\S", z):  # nächster Block auf oberster Ebene
            in_orb = False
        if in_orb:
            m = re.match(r"^(\s+scale:\s*)([-\d.]+)(.*)$", z)
            if m:
                zeilen[i] = f"{m.group(1)}{_zahl(wert)}{m.group(3)}"
                return True
    return False


def _sicher_schreiben(pfad: Path, inhalt: str) -> None:
    """Schreibt die Datei über eine Zwischendatei – nie halb beschrieben."""

    import os
    import tempfile

    ordner = pfad.parent
    griff = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(ordner), delete=False
    )
    try:
        griff.write(inhalt)
        griff.flush()
        os.fsync(griff.fileno())
    finally:
        griff.close()
    os.replace(griff.name, pfad)


def lies_animationswerte(pfad: Path) -> dict[str, float]:
    """Liest die aktuellen Werte – für die relative Änderung ('grösser')."""

    try:
        import yaml

        daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    orb = daten.get("orb", {}) if isinstance(daten, dict) else {}
    anim = dict(orb.get("animation", {}) or {})
    if "scale" in orb:
        anim["scale"] = orb["scale"]
    return {k: float(v) for k, v in anim.items() if isinstance(v, (int, float))}
