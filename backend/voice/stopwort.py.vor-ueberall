"""Hat da jemand „Stopp" gesagt?

## Warum das eine eigene Datei wert ist

Während der Orb spricht, hört das Mikrofon vor allem IHN. Der Stop-Späher
schneidet deshalb kurze Hörfenster mit und lässt ein kleines, schnelles
Whisper-Modell darüberlaufen. Was dabei herauskommt, ist keine saubere
Abschrift: Es ist der eigene Lautsprecher, durch den Raum zurück ins
Mikrofon, mit einem kurzen Zwischenruf irgendwo darin.

Im Protokoll des Benutzers steht, wie die Spracherkennung ein gesprochenes
„Stopp" tatsächlich aufschreibt - alles echte Zeilen::

    14.08. 13:36  "Stopp, Sourcesing."
    14.08. 19:38  "Stopp."
    16.08. 14:59  "Denoeidung, stopp."
    17.08. 21:23  "Nein, stopp, stopp, stopp, ich hab das jetzt ..."

Ein Wort, eingebettet in Verhörtes. Die alte Prüfung verlangte, dass ein
Wort BUCHSTABENGLEICH „stop", „stopp" oder „halt" lautet. Das trifft die
vier Zeilen oben - aber eben nur sie. „Stoppen", „Stoppt", „Stopt",
„Schtopp" fielen durch, und genau solche Formen liefert ein 'base'-Modell
auf einem Fenster, in dem gleichzeitig jemand anderes redet.

## Warum hier grosszügig geprüft werden darf

Grosszügigkeit ist bei einer Notbremse sonst gefährlich: Ein Orb, der bei
jedem ähnlich klingenden Wort verstummt, ist unbrauchbar. Hier ist sie es
nicht, und zwar wegen einer Eigenheit der Lage: Der Orb WEISS, was er
gerade selbst sagt. Ein Wort, das seinem eigenen Satz nahekommt, ist sein
Echo und kein Zwischenruf - diese Prüfung macht die Pipeline mit
``_naehe_zum_eigenen``, nachdem hier ein Verdacht entstanden ist.

Beide zusammen ergeben die richtige Strenge: Hier wird weit gefasst, was
klingt wie ein Halt; dort wird verworfen, was aus dem eigenen Mund kam.

## Der Rückschlag vom 19.08.2026 - und was daraus wurde

Die erste Fassung dieser Datei fasste zu weit, und der Benutzer meldete
binnen einer Stunde: „jetzt unterbricht der orb seine sätze ständig".
Drei Fehler, alle in dieselbe Richtung:

1. Die unscharfe Prüfung lief gegen neun Formen. Das ergibt **2883
   Wörter**, die als „Stopp" durchgehen - von „astoppen" bis „bchtop".
2. Das kleine Modell bekam einen Anker, in dem „Stopp. Halt. Warte."
   stand. Whisper setzt fort, was im Anker steht: Auf jedem undeutlichen
   Schnipsel schrieb es bereitwillig „Stopp." hin. Der Anker hat die
   Erkennung nicht geschärft, sondern ihr das Wort souffliert.
3. Beugungen zählten mit. „ich muss das stoppen", „ich halte das für
   richtig", „wo die Reihe aufhört" - alles echte Sätze des Orb, alle als
   Abbruch gewertet.

## Die Regeln im Einzelnen

* **Nur Befehlsformen.** „Stopp", „Stoppe", „Halt", „Aufhören" - nicht
  „stoppen" (Infinitiv), nicht „stoppt", nicht „halte", nicht „aufhört".
  Was man ruft, unterscheidet sich von dem, was man erzählt.
* **Die Stelle entscheidet.** Ein Zwischenruf steht am Anfang des
  Fensters. Steht das Wort weiter hinten, ist davor die Rede des Orb -
  und dann ist es sein Echo. Füllwortverdächtiges („halt", „aufhören")
  zählt nur an Stelle eins oder zwei.
* **Verhörer** zählen, aber nur gegen „stop" und „stopp" und nur in
  passender Länge („stopt", „stoppp"). Gegen die ganze Familie geprüft
  wäre die Zielfläche fünfmal so gross.
* **Ganze Wörter.** „Gehalt", „Haltung", „Stopfen" schlagen nicht an.
* **Wendungen** zählen, wenn sie das Fenster eröffnen: „hör auf",
  „sei still", „es reicht".
"""

from __future__ import annotations

import re

#: Die Stopp-Familie. Buchstabengleich zählt jede dieser Formen.
#:
#: NICHT dabei: "stoppen" und "stoppt". Der Imperativ heisst "Stopp" oder
#: "Stoppe"; "stoppen" ist der Infinitiv und steht in gewoehnlicher Rede
#: ("ich muss das stoppen" - echte Zeile aus der eigenen Antwort des Orb),
#: "stoppt" die dritte Person. Beide haben am 19.08.2026 mitgeholfen, dass
#: der Orb seine eigenen Saetze zerriss.
_STOPP_FAMILIE: tuple[str, ...] = (
    "stop", "stopp", "stoppe", "stopps", "schtopp", "schtop", "shtop",
)

#: Und NUR gegen diese zwei wird unscharf geprüft.
#:
#: Am 19.08.2026 lief die unscharfe Prüfung gegen alle neun Formen. Das
#: ergibt 2883 Wörter, die als "Stopp" durchgehen - von "astoppen" bis
#: "bchtop". Zusammen mit einem Anker, der dem kleinen Modell "Stopp"
#: geradezu in den Mund legte, hat der Orb sich daraufhin dauernd selbst
#: unterbrochen. Gegen zwei kurze Formen geprüft, bleibt ein Bruchteil
#: übrig - und die Verhörer, um die es wirklich geht ("stopt", "stoppp"),
#: sind weiterhin dabei.
_UNSCHARF_GEGEN: tuple[str, ...] = ("stop", "stopp")

#: Alles Weitere - nur buchstabengleich.
#:
#: Bewusst NICHT dabei: "ruhe", "still", "leise", "schluss". Sie klingen
#: nach Abbruch, stehen aber in gewoehnlicher Rede staendig herum ("in
#: Ruhe", "zum Schluss", "sei doch still zu ihm gewesen"). Eine Notbremse,
#: die bei "zum Schluss" zieht, waere schlimmer als gar keine. Als
#: Wendung ("sei still", "sei ruhig") sind sie eindeutig und stehen
#: deshalb unten.
#: Auch hier nur Befehlsformen. "halte" ("ich halte das für richtig"),
#: "aufhört" ("wo die Reihe aufhört") und "anhalten" stehen mitten in
#: gewoehnlicher Rede - und die Rede, die das Mikrofon waehrend des
#: Sprechens hoert, ist die des Orb selbst.
_WEITERE: tuple[str, ...] = (
    "halt", "aufhören", "aufhoeren", "abbrechen", "abbruch",
)

#: Wendungen, die als Ganzes gelten. Sie werden im zusammenhängenden Text
#: gesucht, nicht Wort für Wort.
_WENDUNGEN: tuple[str, ...] = (
    "hör auf", "hoer auf", "hört auf", "hoert auf",
    "sei still", "sei leise", "sei ruhig",
    "es reicht", "das reicht", "reicht schon",
    "halt mal", "halt stopp",
    "hör bitte auf", "hoer bitte auf",
)

#: Die Längen, in denen unscharf geprüft wird. "stop" und "stopp" haben
#: vier und fünf Zeichen; ein Verhörer davon hat drei bis sechs.
_UNSCHARF_VON = 4
_UNSCHARF_BIS = 6

#: Wo im Hörfenster ein Abbruchwort stehen muss: vorn.
#:
#: Der Grund ist die Lage, nicht die Sprache. Wer einen sprechenden Orb
#: unterbricht, RUFT dazwischen - das Wort steht am Anfang dessen, was
#: das Mikrofon dann aufnimmt. Steht es in der Mitte oder am Schluss, ist
#: davor die Rede des Orb, und dann ist es sein Echo: "und deshalb war
#: das für Russland ein stopp Problem".
#:
#: Eine Obergrenze für die Fensterlänge stand hier zuerst auch, und sie
#: war falsch. Sie hätte eine echte Protokollzeile verworfen: "Nein,
#: stopp, stopp, stopp, ich hab das jetzt ..." - acht Wörter, und ein
#: unmissverständlicher Abbruch. Wo das Wort steht, sagt mehr als wie
#: viele daneben stehen.
_SPAETESTENS_AN_STELLE = 3

#: Wörter, die NUR ganz am Anfang zählen - an Stelle eins oder zwei.
#:
#: "Halt" ist im deutschen Alltag vor allem ein Füllwort: "das ist halt
#: so", "was wir halt erleben", "es ist halt gelungen". Alle drei sind
#: echte Zeilen aus dem Protokoll, und alle drei hätten den Orb mitten
#: im Satz abgebrochen. Als Zwischenruf steht "Halt!" dagegen immer
#: vorn - niemand ruft es als viertes Wort.
#:
#: Dasselbe gilt für "aufhören": "wo die Reihe aufhören soll" ist Rede,
#: "Aufhören!" ist ein Befehl, und man erkennt sie an der Stelle.
_NUR_GANZ_VORN: frozenset[str] = frozenset((
    "halt", "aufhören", "aufhoeren", "stop",
))
_GANZ_VORN_BIS = 1

#: Echte deutsche Wörter, die einen Buchstaben neben einer Stopp-Form
#: liegen. Ohne diese Liste bräche der Orb bei "der Stopfen" ab - und ein
#: Wort, das es wirklich gibt, ist kein Verhörer, sondern ein anderes Wort.
_KEIN_STOPP: frozenset[str] = frozenset((
    "stopfen", "stopfe", "stopft", "stopfst", "stopfer", "gestopft",
    "stoppel", "stoppeln", "stoppelig", "stopper", "stoppuhr",
    "stoffe", "stoff", "stoffen", "stoisch",
))


def _abstand_eins(a: str, b: str) -> bool:
    """Ob sich zwei Wörter um höchstens einen Buchstaben unterscheiden.

    Bewusst keine volle Levenshtein-Rechnung: Gebraucht wird nur die
    Frage „höchstens eins?", und die lässt sich in einem Durchgang
    beantworten. Das zählt, weil diese Prüfung während jedes gesprochenen
    Satzes mehrmals pro Sekunde läuft.
    """

    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        unterschiede = sum(1 for x, y in zip(a, b) if x != y)
        return unterschiede <= 1
    # Genau ein Zeichen Unterschied: Das kürzere muss im längeren stecken.
    kurz, lang = (a, b) if la < lb else (b, a)
    i = j = 0
    uebersprungen = False
    while i < len(kurz) and j < len(lang):
        if kurz[i] == lang[j]:
            i += 1
            j += 1
            continue
        if uebersprungen:
            return False
        uebersprungen = True
        j += 1
    return True


def _woerter(text: str) -> list[str]:
    """Zerlegt in kleingeschriebene Wörter ohne Satzzeichen."""

    return [w for w in re.findall(r"[0-9a-zäöüßA-ZÄÖÜ]+", str(text or "").lower()) if w]


def stopwort_finden(text: str, zusaetzlich: frozenset[str] | None = None) -> str | None:
    """Sucht ein Abbruchwort und gibt es zurück - sonst ``None``.

    Der Rückgabewert ist das gefundene Wort und nicht bloss ``True``: Es
    steht danach im Protokoll, und ohne es wäre später nicht
    nachvollziehbar, WORAN der Orb einen Abbruch erkannt hat. Genau diese
    Angabe fehlte, als am 19.08.2026 zu klären war, warum das Stop-Wort
    nicht mehr greift.

    Args:
        text: Was die Erkennung aus dem Hörfenster gemacht hat.
        zusaetzlich: Weitere Wörter aus der Konfiguration
            (``voice.stop_words``). Sie gelten buchstabengleich.
    """

    if not text:
        return None

    knapp = " ".join(str(text).lower().split())

    # Auch eine Wendung muss VORN stehen. "an, das reicht mir jetzt" ist
    # ein Satz des Orb; "Das reicht, danke" ist ein Zwischenruf. Der
    # Unterschied ist die Stelle, nicht der Wortlaut.
    vorn = " ".join(_woerter(knapp)[: _SPAETESTENS_AN_STELLE + 2])
    for wendung in _WENDUNGEN:
        if vorn.startswith(wendung) or knapp.startswith(wendung):
            return wendung

    genau = set(_WEITERE)
    genau.update(_STOPP_FAMILIE)
    if zusaetzlich:
        genau.update(w.strip().lower() for w in zusaetzlich if w and w.strip())

    for stelle, wort in enumerate(_woerter(knapp)):
        # Und ein Zwischenruf steht vorn, nicht am Schluss.
        if stelle >= _SPAETESTENS_AN_STELLE:
            break
        if wort in genau:
            if wort in _NUR_GANZ_VORN and stelle > _GANZ_VORN_BIS:
                continue
            return wort
        # Unscharf nur gegen "stop"/"stopp", nur in passender Laenge, und
        # nie bei einem Wort, das es wirklich gibt.
        if wort in _KEIN_STOPP:
            continue
        if _UNSCHARF_VON <= len(wort) <= _UNSCHARF_BIS and any(
            _abstand_eins(wort, form) for form in _UNSCHARF_GEGEN
        ):
            return wort
    return None
