"""Geschichtswissenschaft - die Landkarte.

Der Aufbau folgt dem, was das Fach von allen anderen unterscheidet: Es
hat keinen unmittelbaren Zugang zu seinem Gegenstand. Die Vergangenheit
ist vorbei; was bleibt, sind Quellen - und deshalb steht das Handwerk der
Quellenkritik nicht am Rand, sondern gleich hinter dem Einstieg. Von dort
aus öffnen sich die Epochen, und quer dazu liegt die Historiographie: die
Geschichte der Geschichtsschreibung selbst, ohne die man keine
Darstellung einordnen kann.

Der Benutzer arbeitet nachweislich mit diesem Feld - die Julikrise, die
Quellenkritik und die Epochengrenzen tauchen in seinen Gesprächen mit dem
Orb seit Wochen auf. Die Julikrise hat deshalb ein eigenes Thema: Sie ist
das beste Lehrstück des Fachs für die Frage, wie aus Handlungen ohne
Absicht eine Katastrophe wird - und wie hundert Jahre Forschung dieselben
Quellen immer wieder anders gelesen haben.
"""

from __future__ import annotations

from backend.studium.landkarte import Anlass, Feld, Gebiet, Thema


def _f(frage: str, tiefe: str, *woran: str) -> Anlass:
    return Anlass(frage=frage, tiefe=tiefe, woran_man_es_merkt=tuple(woran))


_HANDWERK = Gebiet(
    kennung="ges-handwerk",
    titel="Das Handwerk",
    beschreibung=(
        "Was Geschichtswissenschaft ist und wie sie zu ihren Aussagen "
        "kommt - Quellenkritik, Fragestellung, Darstellung."
    ),
    themen=(
        Thema(
            kennung="ges-was-ist-das",
            titel="Was Geschichtswissenschaft ist und was sie nicht ist",
            abriss=(
                "Geschichtswissenschaft ist nicht das Sammeln von "
                "Jahreszahlen, sondern die methodisch geprüfte Antwort auf "
                "Fragen an die Vergangenheit. Ihr Grundproblem ist einzig: "
                "Der Gegenstand ist unwiederbringlich vorbei, und alles "
                "Wissen über ihn läuft über Überreste und Berichte. Daraus "
                "folgt ihre Arbeitsweise - eine Frage stellen, Quellen "
                "finden, sie kritisch prüfen, und aus ihnen eine Darstellung "
                "bauen, die andere an denselben Quellen nachprüfen können. "
                "Was sich nicht auf Quellen stützt, ist Meinung über die "
                "Vergangenheit, keine Geschichtswissenschaft."
            ),
            worum_es_geht=(
                "erklären, warum Geschichte nur über Quellen zugänglich ist",
                "eine historische Frage von einer blossen Themenangabe "
                "unterscheiden",
                "den Weg von der Frage über die Quelle zur Darstellung "
                "beschreiben",
            ),
            fuehrt_zu=("ges-quellenkritik", "ges-epochen"),
            begriffe=(
                "Quelle", "Darstellung", "Fragestellung", "Überrest",
                "Tradition", "Fachliteratur", "Sekundärliteratur", "Historik",
            ),
            literatur=(
                "Marc Bloch: Apologie der Geschichtswissenschaft",
                "Volker Sellin: Einführung in die Geschichtswissenschaft",
                "Stefan Jordan: Einführung in das Geschichtsstudium",
            ),
            anlaesse=(
                _f("Was unterscheidet eine Quelle von einer Darstellung?",
                   "kennen",
                   "Quelle: aus der Zeit selbst",
                   "Darstellung: später und aus Quellen gebaut",
                   "dieselbe Schrift kann je nach Frage beides sein"),
                _f("'Das Mittelalter' ist keine Fragestellung. Mach aus dem "
                   "Stichwort eine erforschbare Frage.", "anwenden",
                   "eingegrenzt nach Raum, Zeit und Gegenstand",
                   "beantwortbar aus benennbaren Quellen",
                   "offen formuliert, nicht auf ein Ergebnis hin"),
                _f("Kann Geschichtsschreibung objektiv sein, wenn jeder "
                   "Historiker aus seiner Zeit heraus fragt?", "beurteilen",
                   "Standortgebundenheit der Fragen, Prüfbarkeit der Antworten",
                   "Objektivität als Verfahren, nicht als Standpunktlosigkeit",
                   "Max Webers Trennung von Wertbezug und Werturteil"),
            ),
        ),
        Thema(
            kennung="ges-quellenkritik",
            titel="Quellenkritik",
            abriss=(
                "Die Quellenkritik ist das Kernhandwerk: Bevor eine Quelle "
                "etwas beweisen darf, wird sie verhört. Die äussere Kritik "
                "fragt nach dem Stück selbst - ist es echt, wann und wo "
                "entstanden, in wessen Auftrag? Die innere Kritik fragt nach "
                "dem Inhalt - was konnte der Verfasser wissen, was wollte er "
                "bewirken, wem nützt seine Darstellung? Eine Fälschung kann "
                "dabei wertvoller sein als ein echtes Stück: Die "
                "Konstantinische Schenkung beweist nichts über Konstantin, "
                "aber viel über die Interessen des Papsttums, das sie "
                "brauchte."
            ),
            worum_es_geht=(
                "äussere und innere Quellenkritik an einem Stück durchführen",
                "die Absicht eines Verfassers aus Anlass und Adressat "
                "erschliessen",
                "erklären, warum auch eine Fälschung eine Quelle ist",
            ),
            baut_auf=("ges-was-ist-das",),
            fuehrt_zu=("ges-historiografie", "ges-julikrise"),
            begriffe=(
                "äussere Kritik", "innere Kritik", "Echtheit", "Provenienz",
                "Tendenz", "Adressat", "Fälschung", "Konstantinische Schenkung",
                "Paläographie", "Diplomatik",
            ),
            literatur=(
                "Ahasver von Brandt: Werkzeug des Historikers",
                "Lorenzo Valla: De falso credita et ementita Constantini "
                "donatione (1440)",
            ),
            zeigenswert=(
                "eine mittelalterliche Urkunde mit Siegel",
                "eine Gegenüberstellung: echte und gefälschte Urkunde",
            ),
            anlaesse=(
                _f("Welche Fragen stellt die äussere, welche die innere "
                   "Quellenkritik?", "kennen",
                   "äussere: Echtheit, Entstehung, Überlieferung",
                   "innere: Inhalt, Absicht, Wissenshorizont des Verfassers"),
                _f("Ein Chronist berichtet, sein Fürst habe eine Schlacht "
                   "gegen zehnfache Übermacht gewonnen. Wie prüfst du das?",
                   "anwenden",
                   "Abhängigkeit des Chronisten vom Fürsten",
                   "Gegenquellen der anderen Seite suchen",
                   "Topos der Übermacht als literarische Konvention erkennen"),
                _f("Lorenzo Valla hat die Konstantinische Schenkung mit "
                   "sprachlichen Argumenten als Fälschung entlarvt. Was "
                   "macht diesen Nachweis zum Gründungsmoment der Kritik?",
                   "beurteilen",
                   "Sprachstand als datierbares Merkmal - Philologie als Werkzeug",
                   "Autorität der Kirche gegen Evidenz des Textes",
                   "die Fälschung bleibt Quelle: für das 8. Jahrhundert"),
            ),
        ),
        Thema(
            kennung="ges-historiografie",
            titel="Historiographie: die Geschichte der Geschichtsschreibung",
            abriss=(
                "Wer eine Darstellung liest, muss wissen, in welcher "
                "Tradition sie steht. Von Herodots Erkundung über die "
                "christliche Heilsgeschichte zur Kritik der Aufklärung; von "
                "Rankes Quellenideal - zeigen, 'wie es eigentlich gewesen' - "
                "über die Sozialgeschichte, die Strukturen statt grosser "
                "Männer untersucht, bis zur Alltagsgeschichte und zur "
                "globalen Perspektive: Jede Epoche schreibt die Geschichte "
                "neu, weil sie andere Fragen hat. Das ist kein Mangel, "
                "sondern der Motor des Fachs - aber nur, wer die Brille des "
                "Verfassers kennt, kann seine Darstellung benutzen."
            ),
            worum_es_geht=(
                "eine Darstellung ihrer historiographischen Richtung zuordnen",
                "Rankes Programm und seine Grenzen erklären",
                "begründen, warum Geschichte immer wieder neu geschrieben wird",
            ),
            baut_auf=("ges-quellenkritik",),
            fuehrt_zu=("ges-julikrise",),
            begriffe=(
                "Historismus", "Leopold von Ranke", "Annales-Schule",
                "Sozialgeschichte", "Alltagsgeschichte", "Globalgeschichte",
                "Meistererzählung", "Perspektivität",
            ),
            literatur=(
                "Georg G. Iggers: Geschichtswissenschaft im 20. Jahrhundert",
                "Leopold von Ranke: Geschichten der romanischen und "
                "germanischen Völker (Vorrede, 1824)",
                "Marc Bloch / Lucien Febvre: die Annales (ab 1929)",
            ),
            anlaesse=(
                _f("Was wollte Ranke mit dem Satz, man müsse zeigen, 'wie es "
                   "eigentlich gewesen'?", "kennen",
                   "Absage an richtende und belehrende Geschichtsschreibung",
                   "Vorrang der Quelle vor der Konstruktion",
                   "Historismus: jede Epoche unmittelbar zu Gott"),
                _f("Nimm eine Schlacht: Wie würde ein Militärhistoriker, ein "
                   "Sozialhistoriker und ein Alltagshistoriker sie "
                   "untersuchen?", "anwenden",
                   "Operationen und Entscheidungen gegen Strukturen",
                   "Versorgung, Rekrutierung, Wirtschaft",
                   "Erfahrung des einzelnen Soldaten, Briefe, Tagebücher"),
                _f("Wenn jede Generation die Geschichte neu schreibt - gibt "
                   "es dann Fortschritt in der Geschichtswissenschaft, oder "
                   "nur Wechsel der Moden?", "beurteilen",
                   "kumulativ: mehr erschlossene Quellen, geprüfte Irrtümer",
                   "nicht kumulativ: wechselnde Fragen und Massstäbe",
                   "der Unterschied zwischen Revision und Beliebigkeit"),
            ),
        ),
    ),
)

_EPOCHEN = Gebiet(
    kennung="ges-epochen",
    titel="Die Epochen",
    beschreibung=(
        "Der Gang durch die europäische Geschichte - mit dem ständigen "
        "Vorbehalt, dass die Epochengrenzen Werkzeuge sind und keine "
        "Tatsachen."
    ),
    themen=(
        Thema(
            kennung="ges-epochen",
            titel="Epochen und ihre Grenzen",
            abriss=(
                "Antike, Mittelalter, Neuzeit - die Dreiteilung stammt aus "
                "dem Humanismus und ist ein Urteil: Die Humanisten erfanden "
                "das 'mittlere Zeitalter' als finsteres Tal zwischen sich "
                "und der bewunderten Antike. Epochengrenzen sind Setzungen "
                "für bestimmte Fragen. Für die Herrschaftsgeschichte endet "
                "die Antike 476 mit dem letzten weströmischen Kaiser; für "
                "die Wirtschaftsgeschichte des Mittelmeers ändert sich an "
                "diesem Datum fast nichts. Wer eine Epochengrenze benutzt, "
                "sollte sagen können, für welche Frage sie taugt - sonst "
                "benutzt die Grenze ihn."
            ),
            worum_es_geht=(
                "die klassische Epochengliederung und ihre Herkunft nennen",
                "an einem Beispiel zeigen, dass eine Epochengrenze von der "
                "Fragestellung abhängt",
                "den Begriff der Periodisierung als Werkzeug gebrauchen",
            ),
            baut_auf=("ges-was-ist-das",),
            fuehrt_zu=("ges-rom", "ges-mittelalter"),
            begriffe=(
                "Periodisierung", "Antike", "Mittelalter", "Frühe Neuzeit",
                "Spätantike", "Epochenschwelle", "Humanismus", "Sattelzeit",
            ),
            literatur=(
                "Reinhart Koselleck: Vergangene Zukunft",
                "Peter Brown: The World of Late Antiquity",
            ),
            zeigenswert=(
                "ein Zeitstrahl der europäischen Epochen mit unscharfen "
                "Übergängen",
            ),
            anlaesse=(
                _f("Woher stammt die Einteilung in Antike, Mittelalter und "
                   "Neuzeit?", "kennen",
                   "humanistische Selbstverortung",
                   "das Mittelalter als abwertende Fremdbezeichnung",
                   "keine Selbstbeschreibung der Zeitgenossen"),
                _f("Nenne für das Jahr 476 eine Frage, für die es eine "
                   "sinnvolle Grenze ist - und eine, für die nicht.",
                   "anwenden",
                   "Reichsgeschichte des Westens: ja",
                   "Alltag, Wirtschaft, Ostrom: kaum eine Zäsur",
                   "Begriff der Spätantike als Antwort der Forschung"),
                _f("Peter Brown hat mit der 'Spätantike' eine ganze Epoche "
                   "zwischen die Epochen geschoben. Was gewinnt und was "
                   "verliert die Forschung durch solche Neuzuschnitte?",
                   "beurteilen",
                   "Gewinn: Kontinuitäten werden sichtbar",
                   "Verlust: Vergleichbarkeit mit älterer Literatur",
                   "Periodisierung als Forschungsprogramm, nicht Etikett"),
            ),
        ),
        Thema(
            kennung="ges-rom",
            titel="Rom: von der Republik zum Prinzipat",
            abriss=(
                "Die römische Republik scheiterte nicht an einem Feind, "
                "sondern an ihrem Erfolg: Die Eroberungen schufen Heere, die "
                "ihren Feldherren treuer waren als dem Senat, und eine "
                "soziale Frage, die die Gracchen mit Reformen und ihre "
                "Gegner mit Gewalt beantworteten. Nach einem Jahrhundert der "
                "Bürgerkriege errichtete Augustus den Prinzipat - eine "
                "Alleinherrschaft in den Formen der Republik: Er nannte sich "
                "nicht König, sondern erster Bürger, und liess sich die "
                "Vollmachten einzeln und scheinbar freiwillig übertragen. "
                "Die Fassade war keine Nebensache, sondern die Bedingung "
                "seines Überlebens - Caesar, der sie verschmähte, wurde "
                "ermordet."
            ),
            worum_es_geht=(
                "die Krise der Republik aus ihren inneren Spannungen erklären",
                "den Prinzipat als Herrschaftsform beschreiben",
                "an Augustus zeigen, wie Macht durch Formen legitimiert wird",
            ),
            baut_auf=("ges-epochen",),
            fuehrt_zu=("ges-mittelalter",),
            begriffe=(
                "Republik", "Senat", "Gracchen", "Bürgerkrieg", "Prinzipat",
                "Augustus", "princeps", "res publica restituta", "Imperium",
                "Legitimität",
            ),
            literatur=(
                "Augustus: Res gestae divi Augusti",
                "Ronald Syme: The Roman Revolution",
                "Karl Christ: Krise und Untergang der römischen Republik",
            ),
            zeigenswert=(
                "eine Karte des römischen Reichs unter Augustus",
                "die Augustusstatue von Primaporta",
            ),
            anlaesse=(
                _f("Was ist der Prinzipat, und wovon grenzt er sich ab?",
                   "kennen",
                   "Alleinherrschaft in republikanischen Formen",
                   "princeps statt rex - die Namensfrage ist politisch",
                   "Bündelung bestehender Ämter und Vollmachten"),
                _f("Augustus schreibt in den Res gestae, er habe die "
                   "Republik wiederhergestellt. Unterzieh diesen Satz einer "
                   "Quellenkritik.", "anwenden",
                   "Selbstdarstellung des Herrschers, für die Nachwelt gesetzt",
                   "formal zutreffend, der Sache nach irreführend",
                   "Adressat und Absicht: Rechtfertigung der neuen Ordnung"),
                _f("War der Untergang der Republik vermeidbar - oder machte "
                   "die Grösse des Reichs die Alleinherrschaft nötig? Welche "
                   "Position vertritt Syme, und was spricht dagegen?",
                   "beurteilen",
                   "Syme: Revolution der Machteliten, keine Verfassungsfrage",
                   "strukturell: Heeresklientel und Reichsverwaltung",
                   "kontingent: Entscheidungen einzelner in offenen Momenten"),
            ),
        ),
        Thema(
            kennung="ges-mittelalter",
            titel="Herrschaft im Mittelalter: Lehnswesen und Investiturstreit",
            abriss=(
                "Mittelalterliche Herrschaft funktionierte ohne stehendes "
                "Heer, ohne Beamtenapparat und weitgehend ohne Geldwirtschaft "
                "- sie beruhte auf persönlichen Bindungen: Der Herr gab "
                "Schutz und Land, der Vasall Treue und Dienst. Über dieser "
                "weltlichen Ordnung lag der Anspruch der Kirche, und im "
                "Investiturstreit brachen beide Ansprüche aneinander: Wer "
                "setzt die Bischöfe ein, König oder Papst? Der Gang nach "
                "Canossa 1077 wurde zum Sinnbild - und ist zugleich ein "
                "Lehrstück der Quellenkritik, denn fast alles, was wir "
                "darüber wissen, stammt aus Feder der einen Partei."
            ),
            worum_es_geht=(
                "das Lehnswesen als Herrschaft durch persönliche Bindung "
                "erklären",
                "den Investiturstreit als Konflikt zweier Ordnungsansprüche "
                "darstellen",
                "an Canossa zeigen, wie ein Ereignis zum Symbol wird",
            ),
            baut_auf=("ges-epochen",),
            fuehrt_zu=("ges-reformation",),
            begriffe=(
                "Lehnswesen", "Vasall", "Investitur", "Investiturstreit",
                "Gregor VII.", "Heinrich IV.", "Canossa", "Wormser Konkordat",
                "Zweischwerterlehre", "Personenverbandsstaat",
            ),
            literatur=(
                "Marc Bloch: Die Feudalgesellschaft",
                "Gerd Althoff: Heinrich IV.",
            ),
            zeigenswert=(
                "eine Darstellung des Gangs nach Canossa aus der Chronik",
                "ein Schema des Lehnswesens",
            ),
            anlaesse=(
                _f("Wie funktioniert Herrschaft im Lehnswesen?", "kennen",
                   "gegenseitige Bindung: Schutz gegen Treue und Dienst",
                   "Land als Lehen statt Sold",
                   "Herrschaft über Personen, nicht über ein Territorium"),
                _f("Worum ging es im Investiturstreit wirklich - um ein "
                   "Ritual oder um mehr?", "anwenden",
                   "vordergründig: Einsetzung der Bischöfe mit Ring und Stab",
                   "dahinter: Bischöfe als Stützen der Königsherrschaft",
                   "Kompromiss von Worms: Trennung von Amt und Gut"),
                _f("'Nach Canossa gehen wir nicht' - Bismarck machte aus dem "
                   "Ereignis eine Parole. Was sagt die Nachgeschichte von "
                   "Canossa über den Umgang mit Geschichte?", "beurteilen",
                   "Ereignis gegen Erinnerungsort",
                   "Althoff: Canossa als inszenierter Rechtsakt, keine "
                   "Demütigung",
                   "politische Indienstnahme im Kulturkampf"),
            ),
        ),
        Thema(
            kennung="ges-reformation",
            titel="Reformation und Buchdruck",
            abriss=(
                "Luthers Thesen von 1517 waren nicht die erste "
                "Kirchenkritik - aber die erste mit einem Massenmedium im "
                "Rücken. Der Buchdruck machte aus einer akademischen "
                "Disputation binnen Wochen eine öffentliche Sache; "
                "Flugschriften trugen den Streit in die Städte, "
                "Übersetzungen in die Volkssprache machten die Bibel selbst "
                "zum Argument. Die Reformation zerbrach die Einheit der "
                "lateinischen Christenheit und zwang Europa, das "
                "Zusammenleben verschiedener Bekenntnisse zu regeln - der "
                "Augsburger Religionsfrieden von 1555 ist ein Meilenstein "
                "auf dem langen Weg dorthin, kein Ziel."
            ),
            worum_es_geht=(
                "die Reformation als Medienereignis beschreiben",
                "Luthers theologische Kernanliegen benennen",
                "die politischen Folgen bis 1555 einordnen",
            ),
            baut_auf=("ges-mittelalter",),
            fuehrt_zu=("ges-revolution",),
            begriffe=(
                "Reformation", "Luther", "Ablass", "Thesenanschlag", "Flugschrift",
                "Buchdruck", "sola scriptura", "Bauernkrieg",
                "Augsburger Religionsfrieden", "Konfessionalisierung",
            ),
            literatur=(
                "Thomas Kaufmann: Geschichte der Reformation",
                "Elizabeth Eisenstein: The Printing Press as an Agent of "
                "Change",
            ),
            zeigenswert=(
                "eine reformatorische Flugschrift mit Holzschnitt",
                "eine Karte der Konfessionen um 1555",
            ),
            anlaesse=(
                _f("Warum gilt der Buchdruck als Bedingung der Reformation?",
                   "kennen",
                   "Geschwindigkeit und Reichweite der Flugschriften",
                   "Volkssprache statt Latein",
                   "frühere Reformbewegungen blieben lokal"),
                _f("Der Thesenanschlag an der Schlosskirche ist als Ereignis "
                   "umstritten. Was folgt daraus für den Umgang mit dem "
                   "Datum 1517?", "anwenden",
                   "erst spät bezeugt, von Melanchthon nach Luthers Tod",
                   "die Thesen selbst und ihre Verbreitung sind gesichert",
                   "Symboldatum bleibt brauchbar, wenn man es als solches "
                   "ausweist"),
                _f("War die Reformation eine religiöse, eine politische oder "
                   "eine mediale Revolution - und schliessen sich diese "
                   "Deutungen aus?", "beurteilen",
                   "theologischer Kern und politische Trägerschaft",
                   "Eisensteins Medienthese und ihre Kritiker",
                   "mehrdimensionale Erklärung statt Entweder-oder"),
            ),
        ),
        Thema(
            kennung="ges-revolution",
            titel="Die Französische Revolution",
            abriss=(
                "1789 brach nicht einfach ein Aufstand los - es zerbrach "
                "eine Ordnung, die sich selbst für gottgegeben hielt. Die "
                "Revolution erklärte die Menschen für frei und gleich an "
                "Rechten, erfand die Nation als Träger der Souveränität und "
                "schuf mit Verfassung, Parlament und Menschenrechtserklärung "
                "das Vokabular, in dem Politik bis heute gedacht wird. Sie "
                "zeigte zugleich, wie eine Befreiung in Schrecken umschlagen "
                "kann: Die Terreur von 1793 gehört zur Revolution wie die "
                "Erklärung der Menschenrechte, und der Streit darüber, ob "
                "sie ihr Unfall oder ihre Konsequenz war, ist so alt wie die "
                "Revolution selbst."
            ),
            worum_es_geht=(
                "Ursachen und Verlauf in Grundzügen darstellen",
                "die Erklärung der Menschenrechte als Bruch mit der alten "
                "Ordnung lesen",
                "die Terreur als Deutungsproblem der Forschung erklären",
            ),
            baut_auf=("ges-reformation",),
            fuehrt_zu=("ges-julikrise",),
            begriffe=(
                "Französische Revolution", "Ancien Régime", "Generalstände",
                "Nationalversammlung",
                "Menschenrechtserklärung", "Verfassung", "Jakobiner",
                "Terreur", "Napoleon", "Souveränität", "Nation",
            ),
            literatur=(
                "Ernst Schulin: Die Französische Revolution",
                "François Furet: Penser la Révolution française",
                "Erklärung der Menschen- und Bürgerrechte (1789)",
            ),
            zeigenswert=(
                "Delacroix: Die Freiheit führt das Volk (1830, zur "
                "Julirevolution - selbst ein Deutungsbild)",
                "ein Zeitstrahl 1789 bis 1799",
            ),
            anlaesse=(
                _f("Welche drei Stände kannte das Ancien Régime, und warum "
                   "wurde die Ständeordnung 1789 unhaltbar?", "kennen",
                   "Klerus, Adel, Dritter Stand",
                   "Steuerlast und Ausschluss von der Macht beim Dritten Stand",
                   "Finanzkrise als Auslöser, nicht als Ursache"),
                _f("Lies Artikel 1 der Menschenrechtserklärung als "
                   "Historiker: Was verändert dieser Satz, und was lässt er "
                   "offen?", "anwenden",
                   "Bruch: Rechte aus Geburt statt Stand",
                   "offen: Frauen, Sklaven in den Kolonien, Besitzlose",
                   "Olympe de Gouges als zeitgenössische Kritik"),
                _f("War die Terreur ein Verrat an 1789 oder in der "
                   "Revolutionslogik angelegt? Skizziere die Kontroverse "
                   "zwischen marxistischer Deutung und Furet.", "beurteilen",
                   "Umstände-These: Krieg und Konterrevolution",
                   "Furet: Ideologie der Einheit duldet keine Gegner",
                   "woran sich die Frage entscheiden liesse"),
            ),
        ),
        Thema(
            kennung="ges-julikrise",
            titel="Die Julikrise 1914",
            abriss=(
                "Zwischen dem Attentat von Sarajevo am 28. Juni 1914 und den "
                "Kriegserklärungen Anfang August liegen fünf Wochen, in "
                "denen eine Regionalkrise zur Weltkatastrophe wurde. Die "
                "Julikrise ist das dichteste Lehrstück des Fachs: Fast "
                "jede Stunde ist durch Akten, Telegramme und Memoiren "
                "belegt, und doch streitet die Forschung seit hundert Jahren "
                "über die Verantwortung - von der Kriegsschuldfrage des "
                "Versailler Vertrags über Fritz Fischers These vom "
                "deutschen 'Griff nach der Weltmacht' bis zu Christopher "
                "Clarks Schlafwandlern, die in den Krieg stolperten, ohne "
                "ihn zu wollen. Wer die Julikrise durchdringt, lernt, wie "
                "Quellenlage und Deutung zusammenhängen."
            ),
            worum_es_geht=(
                "die Eskalationsschritte der fünf Wochen darstellen",
                "die Rolle der Bündnissysteme und Mobilmachungspläne erklären",
                "die Deutungsgeschichte von Versailles über Fischer zu Clark "
                "einordnen",
            ),
            baut_auf=("ges-quellenkritik", "ges-historiografie"),
            begriffe=(
                "Julikrise", "Attentat von Sarajevo", "Sarajevo", "Blankoscheck",
                "Erster Weltkrieg", "Ultimatum",
                "Mobilmachung", "Schlieffenplan", "Bündnissystem",
                "Kriegsschuldfrage", "Fischer-Kontroverse", "Schlafwandler",
            ),
            literatur=(
                "Christopher Clark: Die Schlafwandler",
                "Fritz Fischer: Griff nach der Weltmacht",
                "Jörn Leonhard: Die Büchse der Pandora",
            ),
            zeigenswert=(
                "eine Karte der europäischen Bündnissysteme 1914",
                "ein Zeitstrahl der fünf Wochen vom Attentat zur "
                "Kriegserklärung",
            ),
            anlaesse=(
                _f("Was war der 'Blankoscheck', und warum gilt er als "
                   "Wegmarke der Eskalation?", "kennen",
                   "deutsche Rückendeckung für Wien am 5./6. Juli",
                   "nahm Österreich-Ungarn das Risiko-Kalkül ab",
                   "verwandelte eine Balkankrise in eine Grossmachtfrage"),
                _f("Warum machte die Mobilmachung den Krieg fast "
                   "unumkehrbar? Erkläre es am Schlieffenplan.", "anwenden",
                   "Fahrpläne: Mobilmachung als militärischer Automatismus",
                   "Schlieffenplan verlangte den Angriff im Westen zuerst",
                   "der Zeitdruck frass den diplomatischen Spielraum"),
                _f("Fischer sah die Hauptverantwortung in Berlin, Clark "
                   "verteilt sie auf schlafwandelnde Kabinette. Woran würde "
                   "sich entscheiden, wer recht hat - und ist die Frage "
                   "überhaupt entscheidbar?", "beurteilen",
                   "Absichten gegen Risikobereitschaft gegen Strukturen",
                   "Quellenlage: was Akten zeigen können und was nicht",
                   "der Unterschied zwischen Schuld und Verantwortung"),
            ),
        ),
    ),
)


GESCHICHTE = Feld(
    kennung="geschichte",
    titel="Geschichtswissenschaft",
    gegenstand=(
        "Die menschliche Vergangenheit, soweit sie aus Quellen erschliessbar "
        "ist - mit dem Schwerpunkt auf der europäischen Geschichte von der "
        "Antike bis ins 20. Jahrhundert."
    ),
    methode=(
        "Fragen an die Vergangenheit stellen und sie aus kritisch geprüften "
        "Quellen beantworten. Der Kern ist die Quellenkritik: Kein Zeugnis "
        "wird geglaubt, bevor geklärt ist, wer es wann, für wen und wozu "
        "hervorgebracht hat. Und jede Darstellung bleibt Deutung - prüfbar "
        "an den Quellen, aber nie deren blosse Abschrift."
    ),
    aufgaben=(
        "rekonstruieren, was geschehen ist, und belegen, woher man es weiss",
        "erklären, warum es geschah - aus Strukturen, Interessen und "
        "Entscheidungen",
        "Mythen und politische Indienstnahmen der Vergangenheit prüfbar "
        "machen",
        "die Gegenwart als gewordene zeigen: was heute selbstverständlich "
        "scheint, hat eine Geschichte und war einmal strittig",
        "den Umgang mit Überlieferung lehren - von der Urkunde bis zum "
        "digitalen Archiv",
    ),
    nachbarn=(
        "Archäologie – erschliesst die Vergangenheit aus Sachüberresten, "
        "nicht primär aus Schrift",
        "Politikwissenschaft – fragt systematisch nach Herrschaft heute, "
        "nicht nach ihrem Gewordensein",
        "Literaturwissenschaft – liest Texte als Kunstwerke; die Geschichte "
        "liest sie als Zeugnisse",
        "Gedenkpolitik – ist Gebrauch der Vergangenheit, nicht ihre "
        "Erforschung",
    ),
    einstiege=("ges-was-ist-das",),
    gebiete=(_HANDWERK, _EPOCHEN),
)
