"""
qr.py - Ein kleiner QR-Erzeuger, nur mit der Standardbibliothek.
================================================================================

Warum es diese Datei gibt
-------------------------
Die Adresse, mit der das iPad den Orb erreicht, ist lang und der Schluessel
zufaellig. Beides auf einem iPad abzutippen ist muehsam und fehleranfaellig.
Ein QR-Code im Konsolenfenster loest das: Kamera drauf, tippen, fertig.

Der Orb bringt keine fremden Pakete mit, also steht der Erzeuger hier - klein
gehalten, aber vollstaendig: Byte-Modus, Fehlerkorrektur L, Version 1 bis 10.
Das reicht fuer Adressen bis 271 Zeichen und damit fuer jeden Tailnet-Namen.

Benutzung
---------
    from qr import qr_ascii
    print(qr_ascii("https://beispiel.ts.net/?key=..."))
"""

from __future__ import annotations

# --------------------------------------------------------------- Tabellen
# Pro Version (Index 1..10) bei Fehlerkorrektur L:
#   (Fehlerkorrektur-Woerter je Block, [(Anzahl Bloecke, Datenwoerter je Block), ...])
BLOECKE_L = {
    1:  (7,  [(1, 19)]),
    2:  (10, [(1, 34)]),
    3:  (15, [(1, 55)]),
    4:  (20, [(1, 80)]),
    5:  (26, [(1, 108)]),
    6:  (18, [(2, 68)]),
    7:  (20, [(2, 78)]),
    8:  (24, [(2, 97)]),
    9:  (30, [(2, 116)]),
    10: (18, [(2, 68), (2, 69)]),
}

# Wie viele Zeichen im Byte-Modus hoechstens hineinpassen.
FASSUNG_L = {1: 17, 2: 32, 3: 53, 4: 78, 5: 106,
             6: 134, 7: 154, 8: 192, 9: 230, 10: 271}

# Mittelpunkte der Ausrichtungsmuster.
AUSRICHTUNG = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}


# ------------------------------------------------- Rechnen im Galois-Feld
_EXP = [0] * 512
_LOG = [0] * 256


def _feld_aufbauen() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_feld_aufbauen()


def _mal(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(grad: int) -> list[int]:
    g = [1]
    for i in range(grad):
        neu = [0] * (len(g) + 1)
        for j, wert in enumerate(g):
            neu[j] ^= wert
            neu[j + 1] ^= _mal(wert, _EXP[i])
        g = neu
    return g


def _fehlerkorrektur(daten: list[int], anzahl: int) -> list[int]:
    g = _generator(anzahl)
    rest = list(daten) + [0] * anzahl
    for i in range(len(daten)):
        f = rest[i]
        if f:
            for j, wert in enumerate(g):
                rest[i + j] ^= _mal(wert, f)
    return rest[len(daten):]


# ------------------------------------------------------------ Datenstrom
def _version_waehlen(laenge: int) -> int:
    for v in range(1, 11):
        if laenge <= FASSUNG_L[v]:
            return v
    raise ValueError("Text zu lang fuer diesen kleinen QR-Erzeuger (max. 271 Zeichen).")


def _bitstrom(text: bytes, version: int) -> list[int]:
    ec_je_block, gruppen = BLOECKE_L[version]
    daten_woerter = sum(anzahl * groesse for anzahl, groesse in gruppen)

    bits: list[int] = []

    def schiebe(wert: int, breite: int) -> None:
        for i in range(breite - 1, -1, -1):
            bits.append((wert >> i) & 1)

    schiebe(0b0100, 4)                       # Byte-Modus
    schiebe(len(text), 8 if version < 10 else 16)
    for byte in text:
        schiebe(byte, 8)

    # Abschluss, dann auf volle Woerter auffuellen.
    for _ in range(min(4, daten_woerter * 8 - len(bits))):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)

    woerter = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]
    fueller = [0xEC, 0x11]
    i = 0
    while len(woerter) < daten_woerter:
        woerter.append(fueller[i % 2])
        i += 1

    # In Bloecke zerlegen, je Block die Fehlerkorrektur rechnen.
    bloecke: list[list[int]] = []
    ec_bloecke: list[list[int]] = []
    pos = 0
    for anzahl, groesse in gruppen:
        for _ in range(anzahl):
            block = woerter[pos:pos + groesse]
            pos += groesse
            bloecke.append(block)
            ec_bloecke.append(_fehlerkorrektur(block, ec_je_block))

    # Verschraenkt zusammensetzen, wie die Norm es verlangt.
    strom: list[int] = []
    for i in range(max(len(b) for b in bloecke)):
        for b in bloecke:
            if i < len(b):
                strom.append(b[i])
    for i in range(ec_je_block):
        for b in ec_bloecke:
            strom.append(b[i])
    return strom


# ------------------------------------------------------------- Zeichnung
def _leer(n: int) -> list[list[int | None]]:
    return [[None] * n for _ in range(n)]


def _muster_setzen(m: list[list[int | None]], version: int) -> None:
    n = len(m)

    def sucher(zx: int, zy: int) -> None:
        for y in range(-1, 8):
            for x in range(-1, 8):
                px, py = zx + x, zy + y
                if not (0 <= px < n and 0 <= py < n):
                    continue
                rand = (0 <= x <= 6 and y in (0, 6)) or (0 <= y <= 6 and x in (0, 6))
                kern = 2 <= x <= 4 and 2 <= y <= 4
                m[py][px] = 1 if (rand or kern) else 0

    sucher(0, 0)
    sucher(n - 7, 0)
    sucher(0, n - 7)

    # Taktreihen
    for i in range(8, n - 8):
        wert = 1 if i % 2 == 0 else 0
        m[6][i] = wert
        m[i][6] = wert

    # Ausrichtungsmuster
    zentren = AUSRICHTUNG[version]
    for zy in zentren:
        for zx in zentren:
            if (zx, zy) in ((6, 6), (6, n - 7), (n - 7, 6)):
                continue
            for y in range(-2, 3):
                for x in range(-2, 3):
                    m[zy + y][zx + x] = 1 if max(abs(x), abs(y)) != 1 else 0

    # Dunkles Pflichtmodul
    m[n - 8][8] = 1

    # Platz fuer die Formatangaben freihalten (als 0 markiert, spaeter ersetzt).
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = 0
        if m[i][8] is None:
            m[i][8] = 0
    for i in range(8):
        if m[8][n - 1 - i] is None:
            m[8][n - 1 - i] = 0
        if m[n - 1 - i][8] is None:
            m[n - 1 - i][8] = 0

    # Versionsangabe ab Version 7.
    if version >= 7:
        rest = version << 12
        while rest.bit_length() > 12:
            rest ^= 0x1F25 << (rest.bit_length() - 13)
        bits = (version << 12) | rest
        for i in range(18):
            b = (bits >> i) & 1
            m[i // 3][n - 11 + i % 3] = b
            m[n - 11 + i % 3][i // 3] = b


def _reserviert(m: list[list[int | None]], version: int) -> list[list[bool]]:
    n = len(m)
    r = [[False] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            r[y][x] = m[y][x] is not None
    return r


def _daten_legen(m: list[list[int | None]], reserviert: list[list[bool]], strom: list[int]) -> None:
    n = len(m)
    bits = []
    for wort in strom:
        for i in range(7, -1, -1):
            bits.append((wort >> i) & 1)

    i = 0
    hoch = True
    spalte = n - 1
    while spalte > 0:
        if spalte == 6:
            spalte -= 1
        zeilen = range(n - 1, -1, -1) if hoch else range(n)
        for y in zeilen:
            for dx in (0, 1):
                x = spalte - dx
                if reserviert[y][x]:
                    continue
                m[y][x] = bits[i] if i < len(bits) else 0
                i += 1
        hoch = not hoch
        spalte -= 2


def _maske(x: int, y: int, nr: int) -> bool:
    if nr == 0: return (x + y) % 2 == 0
    if nr == 1: return y % 2 == 0
    if nr == 2: return x % 3 == 0
    if nr == 3: return (x + y) % 3 == 0
    if nr == 4: return (y // 2 + x // 3) % 2 == 0
    if nr == 5: return (x * y) % 2 + (x * y) % 3 == 0
    if nr == 6: return ((x * y) % 2 + (x * y) % 3) % 2 == 0
    return ((x + y) % 2 + (x * y) % 3) % 2 == 0


def _format_bits(maske_nr: int) -> int:
    # Fehlerkorrektur L hat die Kennung 01.
    daten = (0b01 << 3) | maske_nr
    rest = daten << 10
    for _ in range(15):
        if rest >> 10:
            grad = rest.bit_length() - 1
            rest ^= 0x537 << (grad - 10)
        else:
            break
    return ((daten << 10) | rest) ^ 0b101010000010010


def _strafe(m: list[list[int]]) -> int:
    n = len(m)
    punkte = 0

    # Regel 1: Reihen gleicher Farbe.
    for richtung in range(2):
        for a in range(n):
            lauf, letzt = 0, -1
            for b in range(n):
                wert = m[a][b] if richtung == 0 else m[b][a]
                if wert == letzt:
                    lauf += 1
                else:
                    if lauf >= 5:
                        punkte += lauf - 2
                    lauf, letzt = 1, wert
            if lauf >= 5:
                punkte += lauf - 2

    # Regel 2: gleichfarbige Bloecke 2x2.
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                punkte += 3

    # Regel 3: sucherartige Folgen.
    folge_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    folge_b = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for y in range(n):
        for x in range(n - 10):
            fenster = m[y][x:x + 11]
            if fenster == folge_a or fenster == folge_b:
                punkte += 40
    for x in range(n):
        spalte = [m[y][x] for y in range(n)]
        for y in range(n - 10):
            fenster = spalte[y:y + 11]
            if fenster == folge_a or fenster == folge_b:
                punkte += 40

    # Regel 4: Verhaeltnis dunkel zu hell.
    dunkel = sum(sum(reihe) for reihe in m)
    anteil = dunkel * 100 // (n * n)
    punkte += 10 * (abs(anteil - 50) // 5)
    return punkte


def matrix(text: str) -> list[list[int]]:
    """Baut die fertige QR-Matrix: 1 = dunkel, 0 = hell."""
    roh = text.encode("utf-8")
    version = _version_waehlen(len(roh))
    n = version * 4 + 17

    grund = _leer(n)
    _muster_setzen(grund, version)
    reserviert = _reserviert(grund, version)
    _daten_legen(grund, reserviert, _bitstrom(roh, version))

    bester: list[list[int]] | None = None
    beste_punkte = None
    for nr in range(8):
        kandidat = [[0] * n for _ in range(n)]
        for y in range(n):
            for x in range(n):
                wert = grund[y][x] or 0
                if not reserviert[y][x] and _maske(x, y, nr):
                    wert ^= 1
                kandidat[y][x] = wert

        # Formatangaben eintragen. Sie werden mit dem hoechstwertigen Bit
        # zuerst gelegt - das ist die haeufigste Fehlerquelle beim Nachbauen.
        bits = _format_bits(nr)
        for i in range(15):
            b = (bits >> (14 - i)) & 1
            if i < 6:
                kandidat[8][i] = b
            elif i == 6:
                kandidat[8][7] = b
            elif i == 7:
                kandidat[8][8] = b
            elif i == 8:
                kandidat[7][8] = b
            else:
                kandidat[14 - i][8] = b
        for i in range(15):
            b = (bits >> (14 - i)) & 1
            if i < 7:
                # Bits 0 bis 6 stehen senkrecht unter der linken Formatspalte.
                kandidat[n - 1 - i][8] = b
            else:
                # Bits 7 bis 14 stehen waagerecht rechts in Zeile 8.
                kandidat[8][n - 15 + i] = b
        kandidat[n - 8][8] = 1

        punkte = _strafe(kandidat)
        if beste_punkte is None or punkte < beste_punkte:
            beste_punkte, bester = punkte, kandidat

    assert bester is not None
    return bester


def qr_ascii(text: str, rand: int = 2) -> str:
    """Zeichnet den QR-Code mit Halbblockzeichen, damit er quadratisch wirkt."""
    m = matrix(text)
    n = len(m)
    breite = n + 2 * rand

    reihen: list[list[int]] = []
    for _ in range(rand):
        reihen.append([0] * breite)
    for zeile in m:
        reihen.append([0] * rand + list(zeile) + [0] * rand)
    for _ in range(rand):
        reihen.append([0] * breite)
    if len(reihen) % 2:
        reihen.append([0] * breite)

    # Helle Module muessen hell sein: der Hintergrund der Konsole ist dunkel,
    # deshalb wird invertiert gezeichnet - dunkles Modul = Leerzeichen.
    zeilen = []
    for i in range(0, len(reihen), 2):
        oben, unten = reihen[i], reihen[i + 1]
        stueck = []
        for x in range(breite):
            o, u = oben[x] == 0, unten[x] == 0   # True = hell = gezeichnet
            if o and u:
                stueck.append("█")
            elif o:
                stueck.append("▀")
            elif u:
                stueck.append("▄")
            else:
                stueck.append(" ")
        zeilen.append("".join(stueck))
    return "\n".join(zeilen)


if __name__ == "__main__":
    import sys
    print(qr_ascii(sys.argv[1] if len(sys.argv) > 1 else "https://example.ts.net/?key=test"))
