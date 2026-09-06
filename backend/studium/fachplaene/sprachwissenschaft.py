"""Sprachwissenschaft - Germanistik, Linguistik, Latein.

Der Studienplan folgt dem Aufbau, den germanistische Institute im
deutschsprachigen Raum gemeinsam haben: erst der Gegenstand und die
Methode, dann die sprachlichen Ebenen von unten nach oben (Laut, Wort,
Satz, Bedeutung), dann die Geschichte und die Variation, dann das
Handwerk der empirischen Arbeit. Latein steht nicht daneben, sondern
darin: Es ist die Sprache, an der die europäische Grammatikschreibung
entwickelt wurde, und ohne sie versteht man die Begriffe nicht, mit denen
das Deutsche bis heute beschrieben wird.

Die Reihenfolge ist kein Geschmack. Morphologie ohne Phonologie ist nicht
zu haben - man kann das Morphem nicht bestimmen, ohne das Phonem zu
kennen. ``setzt_voraus`` hält das fest, und ``Fach.pruefen()`` sorgt
dafür, dass die Reihenfolge auch im Semesterplan aufgeht.
"""

from __future__ import annotations

from backend.studium.landkarte import Anlass, Feld, Gebiet, Thema


def _f(frage: str, tiefe: str, *woran: str) -> Anlass:
    """Ein Gesprächsanlass - keine Prüfungsfrage.

    Gestellt wird sie, weil sie das Gespräch an die Stelle bringt, an der
    sich zeigt, ob jemand die Sache durchschaut. Was sie über den Stand
    des Gegenübers verrät, ist ein Nebenertrag.
    """

    return Anlass(frage=frage, tiefe=tiefe, woran_man_es_merkt=tuple(woran))


# ---------------------------------------------------------------------------
#  Semester 1 - Was das Fach ist
# ---------------------------------------------------------------------------

_GRUNDLAGEN = Gebiet(
    kennung="swi-grundlagen",
    titel="Grundlagen der Sprachwissenschaft",
    beschreibung=(
        "Was Sprachwissenschaft ist, was sie von Sprachpflege und "
        "Literaturwissenschaft trennt, und mit welchen Begriffen sie arbeitet."
    ),
    themen=(
        Thema(
            kennung="swi-was-ist-das",
            titel="Was Sprachwissenschaft ist und was sie nicht ist",
            abriss=(
                "Sprachwissenschaft beschreibt, wie Sprache tatsächlich "
                "funktioniert - sie schreibt nicht vor, wie man sprechen "
                "soll. Dieser Unterschied zwischen deskriptiv und normativ "
                "ist der Gründungsakt des Fachs und zugleich der Punkt, an "
                "dem Laien es regelmässig missverstehen. Wer fragt, ob "
                "'wegen dem Regen' falsch sei, stellt eine normative Frage; "
                "die Sprachwissenschaft fragt stattdessen, wer so spricht, "
                "seit wann, in welcher Lage - und warum sich der Dativ hier "
                "durchsetzt. Sie ist eine empirische Wissenschaft mit "
                "Daten, Hypothesen und Gegenbeispielen, keine Sammlung von "
                "Sprachregeln."
            ),
            worum_es_geht=(
                "den Unterschied zwischen deskriptiver und normativer "
                "Sprachbetrachtung an einem eigenen Beispiel erklären",
                "die Teilgebiete der Sprachwissenschaft nennen und ihren "
                "Gegenstand voneinander abgrenzen",
                "begründen, warum Sprachwandel kein Verfall ist",
            ),
            begriffe=(
                "deskriptiv", "normativ", "Sprachwandel", "Empirie",
                "Grammatikalität", "Akzeptabilität", "Introspektion",
            ),
            literatur=(
                "Ferdinand de Saussure: Cours de linguistique générale (1916)",
                "Duden Bd. 4: Die Grammatik",
                "Rudi Keller: Sprachwandel (1990)",
            ),
            zeigenswert=("ein Stammbaum der indogermanischen Sprachen",),
            anlaesse=(
                _f("Was ist der Unterschied zwischen einer deskriptiven und "
                   "einer normativen Aussage über Sprache?", "kennen",
                   "deskriptiv beschreibt tatsächlichen Gebrauch",
                   "normativ schreibt vor, was gelten soll",
                   "Sprachwissenschaft arbeitet deskriptiv"),
                _f("Ist 'wegen dem Regen' falsch? Begründe deine Antwort "
                   "sprachwissenschaftlich.", "anwenden",
                   "nicht falsch, sondern standardsprachlich anders bewertet",
                   "Dativ ist im Gebrauch weit verbreitet und breitet sich aus",
                   "Norm und Gebrauch fallen auseinander"),
                _f("Rudi Keller erklärt Sprachwandel als Ergebnis einer "
                   "'unsichtbaren Hand'. Was leistet diese Erklärung, und wo "
                   "stösst sie an Grenzen?", "beurteilen",
                   "Wandel als unbeabsichtigte Folge absichtsvoller Einzelakte",
                   "erklärt Ausbreitung ohne Planung",
                   "Grenze: erklärt schlecht, warum eine Variante überhaupt entsteht"),
            ),
        ),
        Thema(
            kennung="swi-zeichen",
            baut_auf=("swi-was-ist-das",),
            fuehrt_zu=("swi-implikatur", "swi-variation-grund"),
            titel="Das sprachliche Zeichen",
            abriss=(
                "Saussure hat das sprachliche Zeichen als Verbindung von "
                "Lautbild und Vorstellung beschrieben - signifiant und "
                "signifié - und zwei Eigenschaften herausgestellt, die bis "
                "heute tragen: Die Verbindung ist arbiträr, also nicht durch "
                "die Sache begründet, und sie ist linear, entfaltet sich "
                "also in der Zeit. Arbiträr heisst nicht beliebig: Der "
                "Einzelne kann nichts daran ändern, weil das Zeichen nur "
                "gilt, solange die Gemeinschaft es teilt. Daraus folgt der "
                "zweite grosse Schnitt des Fachs: langue als System gegen "
                "parole als einzelne Äusserung."
            ),
            worum_es_geht=(
                "signifiant und signifié an einem Beispiel auseinanderhalten",
                "die Arbitrarität des Zeichens gegen scheinbare Gegenbeispiele "
                "wie Lautmalerei verteidigen",
                "langue und parole unterscheiden und sagen, was das für die "
                "Datenerhebung bedeutet",
            ),
            begriffe=(
                "signifiant", "signifié", "Arbitrarität", "Linearität",
                "langue", "parole", "synchron", "diachron", "Wert (valeur)",
            ),
            literatur=(
                "Ferdinand de Saussure: Cours de linguistique générale",
                "Charles S. Peirce: Zeichentheorie (Ikon, Index, Symbol)",
            ),
            zeigenswert=("das Zeichenschema: signifiant über signifié",),
            anlaesse=(
                _f("Was meint Saussure mit der Arbitrarität des sprachlichen "
                   "Zeichens?", "kennen",
                   "kein natürlicher Zusammenhang zwischen Lautform und Bedeutung",
                   "verschiedene Sprachen, verschiedene Formen für dasselbe",
                   "nicht beliebig für den Einzelnen, weil konventionell"),
                _f("Lautmalerei wie 'Kuckuck' scheint gegen die Arbitrarität "
                   "zu sprechen. Entkräfte den Einwand.", "anwenden",
                   "Onomatopoetika sind sprachspezifisch geformt",
                   "Hahnenschrei heisst kikeriki, cock-a-doodle-doo, cocorico",
                   "auch sie folgen dem Lautsystem der jeweiligen Sprache"),
                _f("Was gewinnt die Sprachwissenschaft dadurch, dass Saussure "
                   "die Bedeutung eines Zeichens aus seinem Verhältnis zu den "
                   "anderen Zeichen bestimmt und nicht aus der Sache?",
                   "beurteilen",
                   "valeur: Bedeutung entsteht durch Abgrenzung im System",
                   "erlaubt Vergleich von Sprachen mit anderen Gliederungen",
                   "Beispiel: mouton gegen sheep/mutton"),
            ),
        ),
    ),
)

_PHONETIK = Gebiet(
    kennung="swi-phonetik",
    titel="Phonetik und Phonologie",
    beschreibung=(
        "Die Lautebene: wie Laute gebildet werden und wie eine Sprache "
        "aus dem Kontinuum des Hörbaren ihr eigenes System schneidet."
    ),
    themen=(
        Thema(
            kennung="swi-phon-laut",
            baut_auf=("swi-was-ist-das",),
            fuehrt_zu=("swi-morphem", "swi-lautverschiebung"),
            titel="Vom Laut zum Phonem",
            abriss=(
                "Die Phonetik beschreibt Laute als physikalische und "
                "artikulatorische Tatsachen: wo im Mundraum, mit welchem "
                "Hindernis, mit oder ohne Stimme. Die Phonologie fragt etwas "
                "anderes - welche dieser Unterschiede in einer bestimmten "
                "Sprache BEDEUTUNG unterscheiden. Das ist der Unterschied "
                "zwischen Phon und Phonem, und man findet ihn mit dem "
                "Minimalpaar: 'Rasse' gegen 'Rasse' mit langem a, 'Bein' "
                "gegen 'Pein'. Der Ich-Laut in 'ich' und der Ach-Laut in "
                "'ach' klingen für ein deutsches Ohr wie zwei Laute und sind "
                "doch ein Phonem, weil sie sich nie in derselben Umgebung "
                "gegenüberstehen."
            ),
            worum_es_geht=(
                "ein Minimalpaar bilden und damit ein Phonem nachweisen",
                "Phon, Phonem und Allophon auseinanderhalten",
                "einen deutschen Konsonanten nach Artikulationsort, -art und "
                "Stimmhaftigkeit bestimmen",
            ),
            begriffe=(
                "Phon", "Phonem", "Allophon", "Minimalpaar",
                "komplementäre Verteilung", "Artikulationsort",
                "Artikulationsart", "Stimmhaftigkeit", "IPA",
            ),
            literatur=(
                "T. Alan Hall: Phonologie. Eine Einführung",
                "Handbook of the International Phonetic Association",
            ),
            zeigenswert=("die IPA-Tabelle", "ein Sagittalschnitt des Ansatzrohrs"),
            anlaesse=(
                _f("Was ist ein Minimalpaar, und wozu dient es?", "kennen",
                   "zwei Wörter, die sich in genau einem Laut unterscheiden",
                   "unterschiedliche Bedeutung",
                   "Nachweis, dass der Unterschied phonemisch ist"),
                _f("Der Ich-Laut und der Ach-Laut: ein Phonem oder zwei? "
                   "Begründe.", "anwenden",
                   "ein Phonem mit zwei Allophonen",
                   "komplementäre Verteilung nach vorderem oder hinterem Vokal",
                   "kein Minimalpaar möglich"),
                _f("Das Wort 'Kuhchen' gegen 'Kuchen' wird als Gegenbeispiel "
                   "zur komplementären Verteilung angeführt. Was folgt daraus "
                   "für den Phonemstatus im Deutschen?", "beurteilen",
                   "scheinbares Minimalpaar an einer Morphemgrenze",
                   "Verteilung ist morphologisch bedingt, nicht rein phonologisch",
                   "zeigt: Phonologie ist nicht von der Morphologie zu trennen"),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  Semester 2 - Wort und Satz
# ---------------------------------------------------------------------------

_MORPHOLOGIE = Gebiet(
    kennung="swi-morphologie",
    titel="Morphologie",
    beschreibung="Der innere Bau des Wortes: Flexion und Wortbildung.",
    themen=(
        Thema(
            kennung="swi-morphem",
            baut_auf=("swi-phon-laut",),
            fuehrt_zu=("swi-topologie", "lat-kasus"),
            titel="Das Morphem und die Zerlegung des Wortes",
            abriss=(
                "Das Morphem ist die kleinste bedeutungstragende Einheit - "
                "die Zerlegung von 'Unverständlichkeit' in un-ver-ständ-lich-"
                "keit zeigt fünf davon. Der Begriff trägt weit und stösst "
                "doch schnell an Grenzen: Was ist das Morphem in 'nahm' "
                "gegenüber 'nehmen'? Das Deutsche baut Wörter überwiegend "
                "durch Zusammensetzung und Ableitung, und das Fugenelement "
                "in 'Schweinsbraten' oder 'Liebeslied' ist ein eigenes "
                "Problem: bedeutungslos und doch nicht beliebig."
            ),
            worum_es_geht=(
                "ein mehrgliedriges Wort vollständig in Morpheme zerlegen",
                "freie und gebundene Morpheme unterscheiden",
                "Flexion von Wortbildung abgrenzen und die Grenze begründen",
            ),
            begriffe=(
                "Morphem", "Allomorph", "Stamm", "Affix", "Präfix", "Suffix",
                "Flexion", "Derivation", "Komposition", "Fugenelement",
                "Kopf (der Ableitung)",
            ),
            literatur=(
                "Wolfgang Fleischer / Irmhild Barz: Wortbildung der deutschen "
                "Gegenwartssprache",
                "Elke Donalies: Die Wortbildung des Deutschen",
            ),
            zeigenswert=("ein Wortbaum: Unverständlichkeit in seine Morpheme zerlegt",),
            anlaesse=(
                _f("Was ist ein Morphem?", "kennen",
                   "kleinste bedeutungstragende Einheit",
                   "nicht identisch mit Silbe",
                   "kann frei oder gebunden sein"),
                _f("Zerlege 'Unverständlichkeit' vollständig und benenne "
                   "jedes Glied.", "anwenden",
                   "un- Präfix der Negation",
                   "ver- Präfix, -steh-/ständ- Stamm",
                   "-lich Adjektivsuffix, -keit Substantivsuffix"),
                _f("Der Ablaut in 'nehmen - nahm - genommen' lässt sich nur "
                   "schwer als Morphem beschreiben. Welche Lösungen bietet "
                   "die Forschung, und was kostet jede?", "beurteilen",
                   "Prozessmorphologie statt Segmentierung",
                   "Wort-und-Paradigma-Modell",
                   "Kosten: Verlust der einfachen Zerlegbarkeit"),
            ),
        ),
    ),
)

_SYNTAX = Gebiet(
    kennung="swi-syntax",
    titel="Syntax",
    beschreibung="Der Bau des Satzes und die Besonderheiten des Deutschen.",
    themen=(
        Thema(
            kennung="swi-topologie",
            baut_auf=("swi-morphem",),
            fuehrt_zu=("swi-implikatur",),
            titel="Das topologische Feldermodell",
            abriss=(
                "Das Deutsche ordnet den Satz nicht nach fester Wortstellung, "
                "sondern um die Verbklammer herum. Das Feldermodell macht das "
                "sichtbar: Vorfeld, linke Satzklammer, Mittelfeld, rechte "
                "Satzklammer, Nachfeld. Im Aussagesatz steht das finite Verb "
                "an zweiter Stelle, im Nebensatz am Ende - und beides ist "
                "dieselbe Klammer, nur anders gefüllt. Das Modell ist "
                "deskriptiv stark und theoretisch bescheiden; genau deshalb "
                "ist es in der Germanistik geblieben, während Theorien kamen "
                "und gingen."
            ),
            worum_es_geht=(
                "einen deutschen Satz vollständig in die Felder einordnen",
                "Verbzweit- und Verbletztstellung als eine Klammer erklären",
                "an einer Ausklammerung zeigen, wozu das Nachfeld dient",
            ),
            begriffe=(
                "Vorfeld", "linke Satzklammer", "Mittelfeld",
                "rechte Satzklammer", "Nachfeld", "Verbklammer",
                "Verbzweitstellung", "Ausklammerung", "Topikalisierung",
            ),
            literatur=(
                "Peter Eisenberg: Grundriss der deutschen Grammatik",
                "Hans Altmann / Suzan Hahnemann: Syntax fürs Examen",
                "Duden Bd. 4, Kapitel Satzbau",
            ),
            zeigenswert=("die Feldertabelle mit einem eingetragenen Beispielsatz",),
            anlaesse=(
                _f("Welche Felder unterscheidet das topologische Modell?",
                   "kennen",
                   "Vorfeld, linke Klammer, Mittelfeld, rechte Klammer, Nachfeld",
                   "Vorfeld ist genau eine Konstituente",
                   "die Klammern werden vom Verb gebildet"),
                _f("Ordne ein: 'Gestern hat der Professor dem Studenten das "
                   "Buch gegeben, das er suchte.'", "anwenden",
                   "Vorfeld: Gestern",
                   "linke Klammer: hat, Mittelfeld: der Professor … das Buch",
                   "rechte Klammer: gegeben, Nachfeld: das er suchte"),
                _f("Warum gilt die Verbzweitstellung als Kern der deutschen "
                   "Syntax, und wie erklärt die generative Grammatik sie?",
                   "beurteilen",
                   "Verbbewegung nach C, Vorfeldbesetzung als Bewegung nach SpecC",
                   "Nebensatz: C ist von der Konjunktion besetzt",
                   "erklärt Komplementarität von Konjunktion und Verbzweit"),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  Semester 3 - Bedeutung und Geschichte
# ---------------------------------------------------------------------------

_SEMANTIK = Gebiet(
    kennung="swi-semantik",
    titel="Semantik und Pragmatik",
    beschreibung=(
        "Was Wörter und Sätze bedeuten - und was Sprecher darüber hinaus "
        "meinen."
    ),
    themen=(
        Thema(
            kennung="swi-implikatur",
            baut_auf=("swi-zeichen",),
            fuehrt_zu=("swi-korpus",),
            titel="Gesagtes und Gemeintes: Grice und die Implikatur",
            abriss=(
                "„Einige Studenten haben bestanden“ heisst wörtlich nicht, "
                "dass nicht alle bestanden haben - und wird doch so "
                "verstanden. Paul Grice hat gezeigt, dass solche Schlüsse "
                "nicht aus der Bedeutung stammen, sondern aus der Annahme, "
                "der andere halte sich an das Kooperationsprinzip und seine "
                "Maximen. Implikaturen sind streichbar: 'Einige, ja "
                "eigentlich alle' ist kein Widerspruch. Genau diese "
                "Streichbarkeit trennt sie von der Bedeutung im engeren "
                "Sinn."
            ),
            worum_es_geht=(
                "die vier Grice'schen Maximen nennen und je ein Beispiel "
                "für ihre Verletzung geben",
                "eine konversationelle Implikatur durch Streichbarkeit von "
                "einer Präsupposition unterscheiden",
                "Ironie als Maximenverletzung analysieren",
            ),
            begriffe=(
                "Kooperationsprinzip", "Quantität", "Qualität", "Relation",
                "Modalität", "konversationelle Implikatur", "Präsupposition",
                "Streichbarkeit", "Sprechakt",
            ),
            literatur=(
                "H. Paul Grice: Logic and Conversation (1975)",
                "John L. Austin: How to Do Things with Words",
                "John Searle: Sprechakte",
            ),
            anlaesse=(
                _f("Nenne die vier Konversationsmaximen von Grice.",
                   "kennen",
                   "Quantität, Qualität, Relation, Modalität",
                   "sie folgen aus dem Kooperationsprinzip"),
                _f("„Der neue Kollege ist pünktlich und höflich“ – als "
                   "Antwort auf die Frage nach seiner fachlichen Eignung. "
                   "Welche Maxime wird verletzt und was folgt daraus?",
                   "anwenden",
                   "Quantität: zu wenig Information",
                   "Implikatur: fachlich nicht überzeugend",
                   "die Verletzung ist offensichtlich und deshalb bedeutungsvoll"),
                _f("Warum genügt Streichbarkeit allein nicht, um eine "
                   "Implikatur sicher zu bestimmen? Nenne ein weiteres "
                   "Kriterium.", "beurteilen",
                   "auch Nichtabtrennbarkeit und Berechenbarkeit",
                   "Präsuppositionen überleben Negation, Implikaturen nicht immer",
                   "Grenzfälle bei skalaren Ausdrücken"),
            ),
        ),
    ),
)

_SPRACHGESCHICHTE = Gebiet(
    kennung="swi-geschichte",
    titel="Deutsche Sprachgeschichte",
    beschreibung=(
        "Wie aus dem Germanischen das Deutsche wurde - und woran man die "
        "Stufen erkennt."
    ),
    themen=(
        Thema(
            kennung="swi-lautverschiebung",
            baut_auf=("swi-phon-laut",),
            fuehrt_zu=("swi-variation-grund", "lat-kasus"),
            titel="Die Zweite Lautverschiebung",
            abriss=(
                "Zwischen dem 6. und 8. Jahrhundert veränderten sich im "
                "Süden des deutschen Sprachgebiets die germanischen "
                "Verschlusslaute p, t, k systematisch zu Affrikaten und "
                "Reibelauten - und diese Veränderung wanderte nach Norden, "
                "wo sie stehen blieb. Genau daran hängt die Einteilung in "
                "Hochdeutsch und Niederdeutsch: Englisch 'apple' und "
                "niederdeutsch 'Appel' gegen hochdeutsch 'Apfel', 'water' "
                "und 'Water' gegen 'Wasser'. Die Benrather Linie, an der "
                "'ik' zu 'ich' wird, ist die bekannteste dieser Grenzen - "
                "und sie ist keine Linie, sondern ein Fächer."
            ),
            worum_es_geht=(
                "die betroffenen Laute und ihre Ergebnisse in beiden "
                "Stellungen angeben",
                "an einem Wortpaar Deutsch/Englisch die Verschiebung zeigen",
                "erklären, warum die Benrather Linie den Sprachraum gliedert",
            ),
            begriffe=(
                "Zweite Lautverschiebung", "Affrikate", "Frikativ",
                "Benrather Linie", "Rheinischer Fächer", "Althochdeutsch",
                "Hochdeutsch", "Niederdeutsch", "Isoglosse",
            ),
            literatur=(
                "Wilhelm Schmidt: Geschichte der deutschen Sprache",
                "Stefan Sonderegger: Grundzüge deutscher Sprachgeschichte",
                "Hermann Paul: Mittelhochdeutsche Grammatik",
            ),
            zeigenswert=("die Karte mit Benrather Linie und Rheinischem Fächer", "eine Tabelle p/t/k gegen ihre Ergebnisse"),
            anlaesse=(
                _f("Welche Laute sind von der Zweiten Lautverschiebung "
                   "betroffen?", "kennen",
                   "die stimmlosen Verschlusslaute p, t, k",
                   "im Anlaut und nach Konsonant zu Affrikaten",
                   "zwischen Vokalen und im Auslaut zu Reibelauten"),
                _f("Erkläre anhand von englisch 'water' und deutsch 'Wasser', "
                   "was genau geschehen ist.", "anwenden",
                   "germanisches t zwischen Vokalen",
                   "wird zum Reibelaut s bzw. ss",
                   "Englisch hat die Verschiebung nicht mitgemacht"),
                _f("Die Benrather Linie wird als Grenze gelehrt, ist aber ein "
                   "Bündel einzelner Isoglossen, die auseinanderlaufen. Was "
                   "folgt daraus für den Begriff der Dialektgrenze?",
                   "beurteilen",
                   "Rheinischer Fächer: die Isoglossen fallen nicht zusammen",
                   "Dialektgrenzen sind Übergangszonen, keine Linien",
                   "Erklärung über Verkehrswege und territoriale Grenzen"),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  Semester 4 - Latein und Variation
# ---------------------------------------------------------------------------

_LATEIN = Gebiet(
    kennung="swi-latein",
    titel="Lateinische Sprachwissenschaft",
    beschreibung=(
        "Latein als Sprache, als Beschreibungsmodell und als dauernder "
        "Geber an das Deutsche."
    ),
    themen=(
        Thema(
            kennung="lat-kasus",
            baut_auf=("swi-morphem",),
            fuehrt_zu=("swi-topologie",),
            titel="Das lateinische Kasussystem und was das Deutsche daraus machte",
            abriss=(
                "Latein hat sechs Kasus, das Deutsche vier - und die vier "
                "deutschen tragen lateinische Namen, weil die europäische "
                "Grammatikschreibung am Latein entwickelt und dann auf die "
                "Volkssprachen übertragen wurde. Das war fruchtbar und "
                "irreführend zugleich: Der lateinische Ablativ hat im "
                "Deutschen kein Gegenstück, und der deutsche Genitiv "
                "verhält sich anders als der lateinische. Wer das nicht "
                "trennt, beschreibt das Deutsche mit einer Brille, die für "
                "eine andere Sprache geschliffen wurde - ein Fehler mit "
                "langer Geschichte, vom Ablativus absolutus bis zum "
                "Verdikt über den 'falschen' Dativ."
            ),
            worum_es_geht=(
                "die sechs lateinischen Kasus mit ihrer Grundfunktion nennen",
                "einen Ablativus absolutus erkennen und ins Deutsche auflösen",
                "begründen, warum die Übertragung lateinischer Kategorien auf "
                "das Deutsche problematisch ist",
            ),
            begriffe=(
                "Nominativ", "Genitiv", "Dativ", "Akkusativ", "Ablativ",
                "Vokativ", "Ablativus absolutus", "Participium coniunctum",
                "Konsekutio temporum", "Kasusrektion",
            ),
            literatur=(
                "Hans Rubenbauer / J. B. Hofmann: Lateinische Grammatik",
                "Manu Leumann / J. B. Hofmann / A. Szantyr: Lateinische "
                "Grammatik (Handbuch)",
                "Perseus Digital Library (perseus.tufts.edu)",
            ),
            zeigenswert=("die Kasustabelle Latein gegen Deutsch",),
            anlaesse=(
                _f("Nenne die sechs lateinischen Kasus und je eine "
                   "Grundfunktion.", "kennen",
                   "Nominativ Subjekt, Genitiv Zugehörigkeit",
                   "Dativ indirektes Objekt, Akkusativ direktes Objekt",
                   "Ablativ Umstand, Vokativ Anrede"),
                _f("Löse auf: 'Urbe capta, cives fugerunt.' Nenne die "
                   "Konstruktion und drei mögliche deutsche Wiedergaben.",
                   "anwenden",
                   "Ablativus absolutus",
                   "temporal: nachdem die Stadt erobert worden war",
                   "kausal oder konzessiv je nach Zusammenhang"),
                _f("Die deutschen Kasusnamen stammen aus der lateinischen "
                   "Grammatik. Woran zeigt sich, dass diese Übertragung dem "
                   "Deutschen nicht gerecht wird?", "beurteilen",
                   "kein Ablativ, dafür Präpositionalgefüge",
                   "deutscher Genitiv weicht funktional ab und schwindet",
                   "normative Folgen: 'wegen dem' gilt als falsch, ist aber "
                   "systemgerecht"),
            ),
        ),
    ),
)

_VARIATION = Gebiet(
    kennung="swi-variation",
    titel="Variation und Soziolinguistik",
    beschreibung=(
        "Dass Sprache nie einheitlich ist, und wie man ihre Verschiedenheit "
        "untersucht."
    ),
    themen=(
        Thema(
            kennung="swi-variation-grund",
            baut_auf=("swi-was-ist-das",),
            fuehrt_zu=("swi-korpus",),
            titel="Standard, Dialekt und die Frage, wer bestimmt, was gilt",
            abriss=(
                "Es gibt keine Sprache ohne Variation - nach Region, nach "
                "sozialer Gruppe, nach Lage. Die Standardsprache ist kein "
                "natürlicher Zustand, sondern das Ergebnis von Auswahl, "
                "Kodifizierung und Durchsetzung; im deutschen Sprachraum "
                "mit der Besonderheit der Plurizentrik, also mehrerer "
                "gleichberechtigter Standards in Deutschland, Österreich "
                "und der Schweiz. Wer den Schweizer Standard als "
                "'Abweichung' beschreibt, hat den Begriff nicht "
                "verstanden."
            ),
            worum_es_geht=(
                "Dialekt, Regiolekt, Umgangssprache und Standard "
                "auseinanderhalten",
                "die Plurizentrik des Deutschen an Beispielen zeigen",
                "erklären, wie eine Varietät zum Standard wird",
            ),
            begriffe=(
                "Varietät", "Dialekt", "Regiolekt", "Soziolekt",
                "Diglossie", "Plurizentrik", "Kodifizierung", "Prestige",
                "verdeckte Prestige",
            ),
            literatur=(
                "Ulrich Ammon: Die deutsche Sprache in Deutschland, "
                "Österreich und der Schweiz",
                "William Labov: Sociolinguistic Patterns",
                "Variantenwörterbuch des Deutschen",
            ),
            zeigenswert=("eine Dialektkarte des deutschen Sprachraums",),
            anlaesse=(
                _f("Was heisst es, dass das Deutsche eine plurizentrische "
                   "Sprache ist?", "kennen",
                   "mehrere gleichberechtigte nationale Standards",
                   "Deutschland, Österreich, Schweiz",
                   "keine Abweichung von einem Zentrum"),
                _f("In der Deutschschweiz spricht man Dialekt und schreibt "
                   "Standard. Wie heisst diese Lage und was kennzeichnet "
                   "sie?", "anwenden",
                   "Diglossie nach Ferguson",
                   "funktionale Verteilung zweier Varietäten",
                   "hier: mediale Verteilung mündlich gegen schriftlich"),
                _f("Labov hat in New York gezeigt, dass die Aussprache von "
                   "/r/ nach sozialer Schicht und nach Aufmerksamkeit "
                   "variiert. Was war daran methodisch neu, und was folgt "
                   "daraus für den Begriff der Sprachgemeinschaft?",
                   "beurteilen",
                   "quantitative Erhebung sprachlicher Variablen im Feld",
                   "Variation ist geordnet, nicht zufällig",
                   "Sprachgemeinschaft teilt Bewertungen, nicht Formen"),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  Semester 5 - Das Handwerk
# ---------------------------------------------------------------------------

_METHODEN = Gebiet(
    kennung="swi-methoden",
    titel="Empirische Methoden und Korpuslinguistik",
    beschreibung=(
        "Wie man sprachwissenschaftliche Behauptungen prüft, statt sie zu "
        "glauben."
    ),
    themen=(
        Thema(
            kennung="swi-korpus",
            baut_auf=("swi-variation-grund",),
            titel="Arbeiten mit Korpora",
            abriss=(
                "Ein Korpus ist eine planvoll zusammengestellte Sammlung von "
                "Texten, kein Haufen. Was man daraus lesen kann, hängt "
                "vollständig davon ab, wie es zusammengestellt wurde - "
                "Repräsentativität und Ausgewogenheit sind deshalb keine "
                "Feinheiten, sondern die ganze Frage. Für das Deutsche "
                "stehen das DWDS, das Deutsche Referenzkorpus DeReKo am "
                "IDS Mannheim und die Korpora der Universitäten zur "
                "Verfügung. Die wichtigste Einsicht ist eine negative: Eine "
                "Frequenzangabe ohne Angabe des Korpus ist keine Angabe."
            ),
            worum_es_geht=(
                "eine Korpusabfrage formulieren und ihr Ergebnis kritisch lesen",
                "Type und Token unterscheiden und richtig zählen",
                "beurteilen, ob ein Korpus eine bestimmte Frage tragen kann",
            ),
            begriffe=(
                "Korpus", "Type", "Token", "Lemma", "Konkordanz", "KWIC",
                "Kollokation", "Frequenz", "Repräsentativität", "Annotation",
                "DeReKo", "DWDS",
            ),
            literatur=(
                "Institut für Deutsche Sprache: DeReKo und COSMAS II",
                "DWDS – Digitales Wörterbuch der deutschen Sprache",
                "Tony McEnery / Andrew Hardie: Corpus Linguistics",
            ),
            zeigenswert=("eine KWIC-Konkordanz, wie sie im DWDS aussieht",),
            anlaesse=(
                _f("Was ist der Unterschied zwischen Type und Token?",
                   "kennen",
                   "Token: jedes Vorkommen einzeln gezählt",
                   "Type: jede verschiedene Wortform einmal",
                   "Type-Token-Verhältnis als Mass der Vielfalt"),
                _f("Du willst zeigen, dass der Genitiv nach 'wegen' "
                   "zurückgeht. Welches Korpus wählst du, und welche zwei "
                   "Fehlerquellen musst du ausschliessen?", "anwenden",
                   "diachrones, ausgewogenes Korpus mit Zeitschichten",
                   "Textsortenverschiebung über die Zeit",
                   "Normierung der Trefferzahl auf Korpusgrösse"),
                _f("Korpusdaten zeigen Gebrauch, Grammatikalitätsurteile "
                   "zeigen Wissen. Wo widersprechen sich beide Zugänge, und "
                   "wie geht die Forschung damit um?", "beurteilen",
                   "seltene, aber akzeptable Sätze fehlen im Korpus",
                   "häufige, aber als falsch beurteilte Formen stehen darin",
                   "Konvergenzargument: beides erheben und vergleichen"),
            ),
        ),
    ),
)


SPRACHWISSENSCHAFT = Feld(
    kennung="sprachwissenschaft",
    titel="Sprachwissenschaft",
    gegenstand=(
        "Die menschliche Sprache in ihrem Bau, ihrem Gebrauch und ihrer "
        "Geschichte - mit dem Schwerpunkt auf dem Deutschen und dem "
        "Lateinischen."
    ),
    methode=(
        "Beschreiben statt vorschreiben. Die Sprachwissenschaft erhebt "
        "Daten - Belege, Korpora, Urteile von Sprechern -, bildet daraus "
        "Regeln und sucht dann gezielt nach dem, was diese Regeln "
        "widerlegt. Ihr eigentliches Handwerk ist die systematische "
        "Suche nach dem Gegenbeispiel."
    ),
    aufgaben=(
        "die Regeln beschreiben, denen Sprecher folgen, ohne sie nennen "
        "zu können",
        "erklären, warum Sprache sich wandelt, und den Wandel vom Verfall "
        "trennen",
        "Sprachen vergleichen und daraus auf Gemeinsames und Mögliches "
        "schliessen",
        "die Grundlagen für Sprachunterricht, Lexikographie, Übersetzung "
        "und Sprachtechnologie liefern",
        "sprachliche Vorurteile prüfbar machen, statt sie zu wiederholen",
    ),
    nachbarn=(
        "Literaturwissenschaft – untersucht Texte als Kunstwerke, nicht "
        "Sprache als System",
        "Philosophie – fragt nach Bedeutung und Wahrheit, nicht nach "
        "Gebrauch",
        "Psychologie – fragt nach Verarbeitung im Kopf, nicht nach dem "
        "System",
        "Sprachpflege – ist normativ und damit kein Teil des Fachs",
    ),
    # Mehrere Einstiege, und das ist der Punkt: Es gibt keinen ersten
    # Termin. Wer über Latein kommt, steigt woanders ein als wer über
    # Dialekte kommt - und beide sind richtig angekommen.
    einstiege=("swi-was-ist-das",),
    gebiete=(
        _GRUNDLAGEN, _PHONETIK, _MORPHOLOGIE, _SYNTAX,
        _SEMANTIK, _SPRACHGESCHICHTE, _LATEIN, _VARIATION, _METHODEN,
    ),
)
