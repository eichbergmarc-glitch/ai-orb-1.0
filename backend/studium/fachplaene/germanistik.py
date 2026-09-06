"""Germanistik – Literatur, Sprache und Kultur in deutscher Überlieferung.

Die allgemeine Linguistik besitzt eine eigene Landkarte. Germanistik ist
deshalb hier nicht bloss ein zweiter Name für Grammatik, sondern verbindet
textnahe Literaturwissenschaft, Literaturgeschichte, Editionspraxis und die
sprachgeschichtliche Seite des Deutschen. Jede Interpretation muss am Text
prüfbar bleiben; Epochennamen sind Hilfsmittel und keine Schubladen.
"""

from __future__ import annotations

from backend.studium.landkarte import Anlass, Feld, Gebiet, Thema


def _a(frage: str, tiefe: str, *woran: str) -> Anlass:
    return Anlass(frage=frage, tiefe=tiefe, woran_man_es_merkt=tuple(woran))


_METHODEN = Gebiet(
    kennung="ger-methoden",
    titel="Gegenstand und Methoden",
    beschreibung="Wie aus genauem Lesen eine begründete Interpretation wird.",
    themen=(
        Thema(
            kennung="ger-fach",
            titel="Was Germanistik untersucht",
            abriss=(
                "Germanistik untersucht deutschsprachige Literatur, Sprache und "
                "Kultur in ihrer historischen Überlieferung. Literaturwissenschaft "
                "fragt nach Form, Bedeutung, Gattung, Medien und gesellschaftlichem "
                "Kontext; germanistische Linguistik untersucht Bau und Geschichte "
                "des Deutschen. Entscheidend ist die Methode: Eine Interpretation "
                "ist kein persönlicher Eindruck, sondern eine am Text belegte und "
                "gegen Alternativen abgewogene Erklärung."
            ),
            worum_es_geht=(
                "Literatur- und Sprachwissenschaft innerhalb der Germanistik unterscheiden",
                "Textbeleg, Kontextwissen und Interpretation auseinanderhalten",
                "den Kanon als historisch veränderliche Auswahl verstehen",
            ),
            fuehrt_zu=("ger-textanalyse", "ger-gattungen", "ger-mittelalter"),
            begriffe=(
                "Germanistik", "Literaturwissenschaft", "germanistische Linguistik",
                "Philologie", "Kanon", "Edition", "Interpretation", "Textbeleg",
            ),
            literatur=(
                "Thomas Eicher / Volker Wiemann: Arbeitsbuch Literaturwissenschaft",
                "Dieter Burdorf: Einführung in die Gedichtanalyse",
            ),
            anlaesse=(
                _a("Was unterscheidet Germanistik von allgemeiner Linguistik?", "kennen",
                   "deutsche Sprache und Literatur als historisch-kultureller Gegenstand",
                   "Literaturwissenschaft als eigener Schwerpunkt"),
                _a("Trenne an einem kurzen Text Beobachtung, Beleg und Deutung.", "anwenden",
                   "zuerst sprachliche Form benennen", "Deutung mit einer Textstelle begründen"),
                _a("Wer entscheidet, welche Texte zum Kanon gehören?", "beurteilen",
                   "Institutionen und Macht", "Revision durch neue Forschungsfragen"),
            ),
        ),
        Thema(
            kennung="ger-textanalyse",
            titel="Textanalyse und Hermeneutik",
            abriss=(
                "Textanalyse beginnt beim Wortlaut: Wortwahl, Syntax, Klang, Bildlichkeit, "
                "Erzählperspektive und Komposition. Hermeneutik beschreibt, wie einzelne "
                "Stellen aus dem Ganzen und das Ganze aus den Stellen verstanden werden. "
                "Dieser Zirkel ist kein Fehler, solange Vorannahmen offengelegt und am "
                "Text korrigiert werden. Mehrere Lesarten sind möglich, aber nicht jede "
                "ist gleich gut belegt."
            ),
            worum_es_geht=(
                "Formbeobachtung und Deutung methodisch verbinden",
                "den hermeneutischen Zirkel produktiv verwenden",
                "plausible von bloss assoziativen Lesarten unterscheiden",
            ),
            baut_auf=("ger-fach",),
            fuehrt_zu=("ger-gattungen", "ger-moderne"),
            begriffe=(
                "Hermeneutik", "hermeneutischer Zirkel", "hermeneutisch",
                "close reading", "Motiv", "Metapher", "Symbol",
                "Erzählperspektive", "Fokalisierung", "Intertextualität",
            ),
            anlaesse=(
                _a("Was ist der hermeneutische Zirkel?", "kennen",
                   "Teil und Ganzes erschliessen einander", "Vorverständnis bleibt revidierbar"),
                _a("Analysiere, wie Perspektive und Wortwahl eine Figur charakterisieren.", "anwenden",
                   "konkrete Formsignale", "keine psychologische Behauptung ohne Textbeleg"),
                _a("Kann ein Text mehrere richtige Interpretationen haben?", "beurteilen",
                   "Pluralität ja, Beliebigkeit nein", "Erklärungskraft und Textdeckung abwägen"),
            ),
        ),
        Thema(
            kennung="ger-gattungen",
            titel="Lyrik, Drama und Erzählen",
            abriss=(
                "Gattungen sind Bündel historischer Erwartungen. Lyrik verdichtet Sprache "
                "durch Rhythmus, Klang und Bild; Drama organisiert Konflikt für eine Bühne; "
                "Erzähltexte vermitteln Geschehen durch eine Erzählinstanz. Ballade, Novelle "
                "oder Essay überschreiten diese Grenzen und zeigen, dass Gattungen Werkzeuge "
                "der Analyse sind, keine Naturgesetze."
            ),
            worum_es_geht=(
                "die Formmittel der drei Hauptgattungen bestimmen",
                "Erzähler und Autor strikt unterscheiden",
                "Gattungsmischungen historisch erklären",
            ),
            baut_auf=("ger-textanalyse",),
            fuehrt_zu=("ger-klassik-romantik", "ger-moderne"),
            begriffe=(
                "Lyrik", "Metrum", "Rhythmus", "Drama", "Figurenrede", "Erzähler",
                "Fokalisierung", "Novelle", "Ballade", "Gattung",
            ),
            zeigenswert=("Versschema", "Dramenaufbau", "Erzählperspektiven als Schema"),
            anlaesse=(
                _a("Woran unterscheiden sich Autor und Erzähler?", "kennen",
                   "reale Person gegen textinterne Vermittlungsinstanz"),
                _a("Bestimme an einem Gedicht Metrum, Sprecher und Bildfeld.", "anwenden",
                   "Formbefund vor Deutung", "Zusammenspiel statt Merkmalliste"),
                _a("Was gewinnt und verliert eine Einteilung in Gattungen?", "beurteilen",
                   "Vergleichbarkeit", "historische und hybride Grenzfälle"),
            ),
        ),
    ),
)


_GESCHICHTE = Gebiet(
    kennung="ger-literaturgeschichte",
    titel="Literaturgeschichte und Medien",
    beschreibung="Texte von der Handschrift bis zur digitalen Gegenwart.",
    themen=(
        Thema(
            kennung="ger-mittelalter",
            titel="Mittelalterliche Literatur und Überlieferung",
            abriss=(
                "Mittelalterliche Texte leben in Handschriften, nicht in autorisierten "
                "Erstausgaben. Das Nibelungenlied, höfische Romane und Minnesang wurden "
                "vorgetragen, abgeschrieben und verändert. Editionen stellen deshalb aus "
                "abweichenden Handschriften einen lesbaren Text her. Autorschaft, Publikum "
                "und Fiktion funktionieren anders als im modernen Buchmarkt."
            ),
            worum_es_geht=(
                "mündliche, handschriftliche und editorische Überlieferung unterscheiden",
                "höfische Literatur aus ihren sozialen Funktionen erklären",
                "Varianten als Erkenntnisquelle statt als Fehler lesen",
            ),
            baut_auf=("ger-fach",),
            fuehrt_zu=("ger-aufklaerung",),
            begriffe=(
                "Nibelungenlied", "Minnesang", "höfischer Roman", "Handschrift",
                "Überlieferung", "Edition", "Walther von der Vogelweide", "Parzival",
            ),
            zeigenswert=("Handschriftseite des Nibelungenlieds", "mittelalterlicher Codex"),
            anlaesse=(
                _a("Warum gibt es nicht den einen ursprünglichen Text des Nibelungenlieds?", "kennen",
                   "mehrere Handschriften", "mündliche und schriftliche Veränderung"),
                _a("Vergleiche zwei Handschriftenvarianten und begründe eine Editionsentscheidung.", "anwenden",
                   "Lesarten dokumentieren", "Eingriff transparent machen"),
                _a("Ist moderne Autorschaft ein brauchbares Modell für das Mittelalter?", "beurteilen",
                   "andere Produktionsbedingungen", "anonyme und kollektive Überlieferung"),
            ),
        ),
        Thema(
            kennung="ger-aufklaerung",
            titel="Aufklärung und Sturm und Drang",
            abriss=(
                "Im 18. Jahrhundert wird Literatur zum Labor bürgerlicher Öffentlichkeit. "
                "Lessings Drama prüft religiöse Toleranz und gesellschaftliche Macht, "
                "während der Sturm und Drang Genie, Gefühl und Konflikt gegen Normen setzt. "
                "Goethes Werther zeigt zugleich, wie Briefform, Perspektive und Lesekultur "
                "eine empfindsame Innenwelt erzeugen."
            ),
            worum_es_geht=(
                "Literatur und entstehende Öffentlichkeit verbinden",
                "Toleranz, Genie und Empfindsamkeit als historische Konzepte verstehen",
                "Briefroman und bürgerliches Trauerspiel formal analysieren",
            ),
            baut_auf=("ger-textanalyse",),
            fuehrt_zu=("ger-klassik-romantik",),
            begriffe=(
                "Aufklärung", "Sturm und Drang", "Lessing", "Nathan der Weise",
                "Goethe", "Werther", "Briefroman", "bürgerliches Trauerspiel",
            ),
            zeigenswert=("Lessing-Porträt", "historische Werther-Ausgabe"),
            anlaesse=(
                _a("Wie verändert die bürgerliche Öffentlichkeit die Literatur?", "kennen",
                   "Lesepublikum, Zeitschriften und Theater", "öffentliche Kritik"),
                _a("Zeige am Werther, was die Briefform mit unserem Wissen macht.", "anwenden",
                   "begrenzte Perspektive", "Nähe und Unzuverlässigkeit"),
                _a("Ist Nathans Ringparabel ein zeitloses Toleranzmodell?", "beurteilen",
                   "historischer Kontext", "Leistung und Grenzen des Gleichnisses"),
            ),
        ),
        Thema(
            kennung="ger-klassik-romantik",
            titel="Weimarer Klassik und Romantik",
            abriss=(
                "Klassik und Romantik reagieren verschieden auf Moderne und Revolution. "
                "Goethe und Schiller suchen Bildung, Form und Ausgleich; die Romantik "
                "betont Fragment, Ironie, Nachtseite und die Sehnsucht nach einer verlorenen "
                "Einheit. Die nachträglichen Epochenetiketten verdecken Übergänge, persönliche "
                "Entwicklungen und politische Spannungen."
            ),
            worum_es_geht=(
                "klassische Bildungsidee und romantische Poetik vergleichen",
                "Ironie, Fragment und Symbol textnah bestimmen",
                "Epochenbegriffe als Forschungsmodelle kritisch verwenden",
            ),
            baut_auf=("ger-aufklaerung", "ger-gattungen"),
            fuehrt_zu=("ger-moderne",),
            begriffe=(
                "Weimarer Klassik", "Romantik", "Goethe", "Schiller", "Novalis",
                "Hoffmann", "Bildung", "Fragment", "romantische Ironie",
            ),
            zeigenswert=("Goethe und Schiller in Weimar", "romantische Buchillustration"),
            anlaesse=(
                _a("Was trennt klassische Bildung von romantischer Sehnsucht?", "kennen",
                   "Form und Ausgleich", "Fragment und offene Bewegung"),
                _a("Analysiere romantische Ironie an einem Erzählbruch.", "anwenden",
                   "Text zeigt seine Gemachtheit", "Wechsel zwischen Illusion und Reflexion"),
                _a("Wie brauchbar sind Klassik und Romantik als Epochen?", "beurteilen",
                   "Orientierung", "Übergänge und nachträgliche Kanonbildung"),
            ),
        ),
        Thema(
            kennung="ger-moderne",
            titel="Realismus, Moderne, Exil und Nachkrieg",
            abriss=(
                "Vom poetischen Realismus bis zur Nachkriegsliteratur verändert sich das "
                "Verhältnis von Erzählen und Wirklichkeit. Fontane gestaltet Gesellschaft "
                "durch Perspektive und Gespräch; Kafka macht Institutionen und Schuld in "
                "paradoxen Verfahren erfahrbar; Exil- und Trümmerliteratur ringen um Sprache "
                "nach Diktatur, Krieg und Shoah. Historischer Kontext erklärt Texte, ersetzt "
                "aber nie ihre Formanalyse."
            ),
            worum_es_geht=(
                "Realismus und literarische Moderne formal unterscheiden",
                "Kafka ohne vorschnelle Symbolauflösung lesen",
                "Exil, Shoah und Nachkrieg sprach- und erinnerungskritisch einordnen",
            ),
            baut_auf=("ger-gattungen", "ger-klassik-romantik"),
            fuehrt_zu=("ger-gegenwart",),
            begriffe=(
                "poetischer Realismus", "Moderne", "Fontane", "Kafka", "Brecht",
                "Exilliteratur", "Shoah", "Trümmerliteratur", "Gruppe 47",
            ),
            zeigenswert=("Kafka-Porträt", "Exilzeitschrift", "Theaterinszenierung Brechts"),
            anlaesse=(
                _a("Warum ist poetischer Realismus kein blosses Abbild der Wirklichkeit?", "kennen",
                   "ästhetische Auswahl und Verklärung", "gesellschaftliche Beobachtung"),
                _a("Analysiere eine Kafka-Szene, ohne ihr Symbol vorschnell aufzulösen.", "anwenden",
                   "Verfahren, Perspektive und Sprachlogik", "Mehrdeutigkeit erhalten"),
                _a("Was kann Literatur nach der Shoah leisten, und wo liegen ihre Grenzen?", "beurteilen",
                   "Zeugnis und ästhetische Form", "Repräsentationsproblem und Verantwortung"),
            ),
        ),
        Thema(
            kennung="ger-gegenwart",
            titel="Gegenwartsliteratur, Erinnerung und digitale Medien",
            abriss=(
                "Gegenwartsliteratur verhandelt Migration, Erinnerung, Geschlecht, soziale "
                "Ungleichheit und globale Verflechtung. Hörbuch, Serie, Computerspiel und "
                "soziale Medien verändern Autorschaft, Erzählen und Öffentlichkeit. Eine "
                "gegenwärtige Germanistik verbindet genaue Lektüre mit Buchmarkt-, Medien- "
                "und Diskursanalyse, ohne den Text auf seine politische Botschaft zu reduzieren."
            ),
            worum_es_geht=(
                "Erinnerungs- und Migrationsliteratur ohne Etikettenreduktion lesen",
                "Medienwechsel und Adaptation analysieren",
                "ästhetisches Urteil und politische Bewertung unterscheiden",
            ),
            baut_auf=("ger-moderne",),
            begriffe=(
                "Gegenwartsliteratur", "Erinnerungskultur", "Migrationsliteratur",
                "Autofiktion", "Intermedialität", "Adaptation", "Buchmarkt", "Diskursanalyse",
            ),
            zeigenswert=("Buchcover im historischen Vergleich", "Adaptation über mehrere Medien"),
            anlaesse=(
                _a("Was ist Autofiktion, und wie unterscheidet sie sich von Autobiografie?", "kennen",
                   "bewusste Schwebe zwischen Fakt und Fiktion", "Autorname allein ist kein Wahrheitsvertrag"),
                _a("Vergleiche eine Romanstelle mit ihrer Verfilmung.", "anwenden",
                   "medienabhängige Mittel", "Veränderung statt blosser Verlustliste"),
                _a("Wie lässt sich politische Relevanz bewerten, ohne Literatur zur Botschaft zu verkürzen?", "beurteilen",
                   "Form und Wirkung mitprüfen", "normatives Urteil kenntlich machen"),
            ),
        ),
    ),
)


GERMANISTIK = Feld(
    kennung="germanistik",
    titel="Germanistik",
    gegenstand=(
        "Deutschsprachige Literatur, Sprache und Kultur von der handschriftlichen "
        "Überlieferung bis zu digitalen Gegenwartsmedien."
    ),
    methode=(
        "Textnah lesen, Form und sprachliche Verfahren beschreiben, Überlieferung "
        "prüfen und Deutungen am Wortlaut sowie am historischen Kontext begründen."
    ),
    aufgaben=(
        "literarische Texte präzise analysieren und interpretieren",
        "Literaturgeschichte ohne starre Epochenschubladen erschliessen",
        "Editionen, Handschriften und Medienwechsel kritisch untersuchen",
        "Kanonbildung, Erinnerung und kulturelle Deutungsmacht reflektieren",
        "die Verbindung zur germanistischen Sprachwissenschaft sichtbar halten",
    ),
    nachbarn=(
        "Sprachwissenschaft – untersucht Sprache als System; Germanistik verbindet sie mit deutscher Überlieferung",
        "Geschichtswissenschaft – rekonstruiert vergangene Wirklichkeit; Literatur gestaltet mögliche Wirklichkeiten",
        "Philosophie – prüft Geltungsansprüche; Literatur erprobt Denken in Formen und Figuren",
        "Medienwissenschaft – untersucht Medien allgemein; Germanistik folgt Texten und Erzählformen durch die Medien",
    ),
    einstiege=("ger-fach",),
    gebiete=(_METHODEN, _GESCHICHTE),
)
