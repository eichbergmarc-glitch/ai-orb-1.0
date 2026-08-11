"""Der Lehrplan – womit sich der Orb von selbst befasst.

Der Benutzer wollte, dass sich der Orb Fachwissen aneignet: Geschichts-
wissenschaft, globale Politik, globale Konflikte, und die Epochen von der
Antike bis zur Neuesten Geschichte.

Das liesse sich als eine Liste von Themen hinschreiben, die abgearbeitet
wird. Genau das tut dieses Modul NICHT, und der Grund ist der Kern der
Sache.

## Warum es Fragen sind und keine Stichworte

Ein Thema wie „Mittelalter" ist als Suchauftrag wertlos. Es gibt Millionen
Seiten dazu, die ersten drei sind Übersichtsartikel, und was der Orb
daraus destilliert, ist eine Enzyklopädie-Einleitung – Wissen, das jeder
hat und niemand braucht.

Eine Frage dagegen hat eine Antwort. „Woran bemisst die Forschung den
Beginn und das Ende des Mittelalters, und warum ist das umstritten?" führt
zu Texten, in denen jemand etwas behauptet und begründet. Daraus lassen
sich Aussagen destillieren, die etwas taugen.

Deshalb besteht der Lehrplan aus Fragen. Sie werden als offene Fragen in
die Themen eingetragen, und von da an ist es dieselbe Maschinerie wie
beim Vertiefen: Der Orb nimmt sich die älteste vor, geht ihr nach, und
was dabei an neuen Fragen entsteht, hängt er hinten an. Der Lehrplan ist
also nur der Anstoss, nicht das Programm.

## Warum die Themen nicht überschrieben werden

Wer den Orb schon zu einem Thema befragt hat, hat dort Aussagen und
eigene offene Fragen stehen – womöglich seine eigenen, im Gespräch
gegebenen. Der Lehrplan ergänzt und ersetzt nie. Angelegt wird nur, was
fehlt.
"""

from __future__ import annotations

from backend.learning.themenwissen import Themenspeicher
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


#: Der Lehrplan: je Gebiet die Fragen, mit denen der Orb beginnt.
#:
#: Die Fragen sind bewusst so gestellt, dass sie eine Kontroverse oder
#: eine Abgrenzung berühren. Was unstrittig ist, steht in jedem Lexikon;
#: interessant wird ein Gebiet dort, wo die Forschung uneins ist – und
#: genau dort lernt man, worauf es ankommt.
LEHRPLAN: dict[str, tuple[str, ...]] = {
    # --- Das Fach selbst ------------------------------------------------------
    "Geschichtswissenschaft": (
        "Welche Methoden der Quellenkritik gelten heute als Standard, und "
        "worin unterscheiden sich äussere und innere Quellenkritik?",
        "Wie unterscheidet die Forschung zwischen Primär- und "
        "Sekundärquellen, und wo ist diese Grenze umstritten?",
        "Was war der Historikerstreit, und welche methodischen Fragen "
        "standen dahinter?",
        "Welche Rolle spielt die Oral History, und welche Einwände gibt es "
        "gegen sie?",
        "Was bedeutet Geschichtsrevisionismus, und wie grenzt die "
        "Forschung ihn von legitimer Neubewertung ab?",
    ),
    # --- Die Epochen ----------------------------------------------------------
    "Antike": (
        "Woran bemisst die Forschung Beginn und Ende der Antike, und warum "
        "ist diese Einteilung umstritten?",
        "Welche Ursachen für den Untergang des Weströmischen Reiches "
        "werden in der neueren Forschung diskutiert?",
        "Wie funktionierte die attische Demokratie, und wer war davon "
        "ausgeschlossen?",
        "Welche Quellen zur Antike gelten als besonders problematisch, und "
        "warum?",
    ),
    "Mittelalter": (
        "Woran bemisst die Forschung Beginn und Ende des Mittelalters, und "
        "warum ist das umstritten?",
        "Was besagt die These vom Investiturstreit als Wendepunkt der "
        "europäischen Staatlichkeit?",
        "Wie ist der Begriff Feudalismus in der neueren Forschung "
        "kritisiert worden?",
        "Welche Folgen hatte die Pest von 1347 bis 1353 für die "
        "europäische Gesellschaft?",
    ),
    "Neuzeit": (
        "Welche Ereignisse markieren nach heutiger Forschung den Beginn "
        "der Neuzeit, und welche Einwände gibt es gegen diese Zäsur?",
        "Wie wirkte sich der Westfälische Friede von 1648 auf die "
        "europäische Staatenordnung aus?",
        "Welche Deutungen der Französischen Revolution stehen in der "
        "Forschung einander gegenüber?",
        "Was versteht die Forschung unter der Sattelzeit, und worauf "
        "stützt sich dieser Begriff?",
    ),
    "Neueste Geschichte": (
        "Welche Erklärungsansätze für den Ausbruch des Ersten Weltkriegs "
        "werden heute vertreten, und wie hat sich die Debatte seit "
        "Fritz Fischer verschoben?",
        "Wie erklärt die Forschung den Aufstieg des Nationalsozialismus, "
        "und welche Deutungen stehen dabei gegeneinander?",
        "Welche Zäsuren gliedern den Kalten Krieg, und wie begründet die "
        "Forschung sie?",
        "Wie wird die Dekolonisation in der neueren Forschung bewertet?",
    ),
    # --- Politik und Konflikte -------------------------------------------------
    "Globale Politik": (
        "Wie ist der UN-Sicherheitsrat aufgebaut, und welche Kritik gibt es "
        "an seinem Vetorecht?",
        "Welche Theorien der internationalen Beziehungen stehen einander "
        "gegenüber, und worin unterscheiden sich Realismus und "
        "Liberalismus in ihren Annahmen?",
        "Was besagt das Völkerrecht zur Souveränität von Staaten, und wo "
        "steht es im Konflikt mit der Schutzverantwortung?",
        "Wie verändert der Aufstieg Chinas die internationale Ordnung nach "
        "Einschätzung der Forschung?",
    ),
    # --- Künstliche Intelligenz -----------------------------------------------
    "Künstliche Intelligenz": (
        "Wie funktionieren grosse Sprachmodelle im Kern, und was können sie "
        "prinzipbedingt nicht?",
        "Welche Belege gibt es dafür, dass Sprachmodelle Inhalte erfinden, "
        "und welche Gegenmassnahmen gelten als wirksam?",
        "Welche Regulierungsansätze für KI stehen international einander "
        "gegenüber, und worin unterscheiden sie sich?",
        "Wie verändert KI die wissenschaftliche Arbeit, und welche "
        "methodischen Einwände werden dagegen erhoben?",
        "Welche Aussagen zur Leistungsfähigkeit von KI-Systemen gelten in "
        "der Fachwelt als überzogen, und warum?",
    ),
    # --- Wirtschaft ------------------------------------------------------------
    "Wirtschaft": (
        "Wie wirken Leitzinsentscheidungen auf Inflation und Beschäftigung, "
        "und wo ist dieser Zusammenhang in der Forschung umstritten?",
        "Welche Erklärungen für die Finanzkrise von 2008 stehen einander "
        "gegenüber?",
        "Wie wird wirtschaftliche Ungleichheit gemessen, und welche Kritik "
        "gibt es an diesen Massen?",
        "Welche Folgen hat die Entkopplung der Lieferketten zwischen China "
        "und dem Westen nach heutiger Einschätzung?",
        "Was besagt die Kritik am Bruttoinlandsprodukt als Wohlstandsmass, "
        "und welche Alternativen werden vorgeschlagen?",
    ),
    "Globale Konflikte": (
        "Welche Ursachen des russischen Angriffs auf die Ukraine werden in "
        "der Forschung diskutiert?",
        "Welche historischen Wurzeln hat der Nahostkonflikt, und welche "
        "Darstellungen stehen einander gegenüber?",
        "Welche Konflikte gelten derzeit als eingefroren, und was hält sie "
        "in diesem Zustand?",
        "Wie unterscheidet die Forschung zwischen zwischenstaatlichen "
        "Kriegen und Bürgerkriegen, und warum verschwimmt die Grenze?",
    ),
}


def lehrplan_anlegen(speicher: Themenspeicher, plan: dict | None = None) -> int:
    """Legt die Gebiete des Lehrplans an, soweit sie fehlen.

    Bestehende Themen werden ERGÄNZT und nie überschrieben: Wer den Orb
    schon zu einem Gebiet befragt hat, hat dort Aussagen stehen, womöglich
    seine eigenen aus dem Gespräch. Die dürfen nicht verlorengehen, nur
    weil ein Lehrplan dazukommt.

    Auch die Fragen werden nur ergänzt, wenn sie nicht schon dastehen –
    sonst wüchse die Liste bei jedem Start um denselben Satz.

    Returns:
        Wie viele Fragen neu hinzugekommen sind.
    """

    eintraege = LEHRPLAN if plan is None else plan
    neu = 0

    for gebiet, fragen in eintraege.items():
        thema = speicher.laden(gebiet)
        bekannt = {f.strip().lower() for f in thema.offene_fragen}
        # Auch das schon Beantwortete zaehlt: Eine Frage, zu der es bereits
        # Aussagen gibt, noch einmal zu stellen, waere Arbeit ohne Ertrag.
        beantwortet = " ".join(a.text.lower() for a in thema.aussagen)

        geaendert = False
        for frage in fragen:
            if frage.strip().lower() in bekannt:
                continue
            # Grob geprüft: Kommen die kennzeichnenden Wörter der Frage
            # bereits im Gelernten vor, ist sie wahrscheinlich abgedeckt.
            kern = [w for w in frage.lower().split() if len(w) >= 9]
            if kern and all(w.strip("?,.") in beantwortet for w in kern):
                continue
            thema.offene_fragen.append(frage)
            bekannt.add(frage.strip().lower())
            geaendert = True
            neu += 1

        if geaendert:
            speicher.speichern(thema)

    if neu:
        logger.info(
            "Lehrplan: %d Fragen zu %d Gebieten stehen zur Bearbeitung an.",
            neu,
            len(eintraege),
        )
    return neu
