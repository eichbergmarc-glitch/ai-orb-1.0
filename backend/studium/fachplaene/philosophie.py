"""Philosophie - die Landkarte.

Zwei Entscheidungen prägen diese Karte, und beide haben einen Grund im
Auftrag des Benutzers.

Erstens die Personen: Sokrates, Platon und Aristoteles haben eigene
Themen, denn der Benutzer hat sie namentlich verlangt - und Markus
Gabriel ebenso, nach dem er den Orb in mehreren Sitzungen vergeblich
gefragt hat (die Suche fand damals Sigmar Gabriel). Personen sind in der
Philosophie keine Randnotiz zur Sache; bei ihnen IST der Denkweg die
Sache.

Zweitens das Zeigen: Fast alle Themen hier haben ABSICHTLICH kein
``zeigenswert``. Ein Argument hat kein Aussehen - wer den Gottesbeweis
oder die Implikatur bebildert, malt Tapete. Die zwei Ausnahmen sind
begründet: das Höhlengleichnis ist selbst ein Bild, und die Schulen von
Athen tragen ein Gemälde, das eine These über sie enthält.
"""

from __future__ import annotations

from backend.studium.landkarte import Anlass, Feld, Gebiet, Thema


def _f(frage: str, tiefe: str, *woran: str) -> Anlass:
    return Anlass(frage=frage, tiefe=tiefe, woran_man_es_merkt=tuple(woran))


_ANFAENGE = Gebiet(
    kennung="phi-anfaenge",
    titel="Was Philosophie ist und wie sie anfing",
    beschreibung=(
        "Der Gegenstand des Fachs und die drei Athener, an denen sich bis "
        "heute entscheidet, was Philosophieren heisst."
    ),
    themen=(
        Thema(
            kennung="phi-was-ist-das",
            titel="Was Philosophie ist und was sie nicht ist",
            abriss=(
                "Philosophie ist das Nachdenken über Fragen, die sich nicht "
                "durch Messen und Zählen erledigen lassen: Was kann ich "
                "wissen? Was soll ich tun? Was ist der Mensch? Ihr Werkzeug "
                "ist das Argument - eine Behauptung gilt hier genau so viel "
                "wie ihre Begründung, und die berühmteste Autorität ist "
                "widerlegt, sobald ein besseres Argument dagegen steht. "
                "Damit unterscheidet sie sich von der Weltanschauung, die "
                "Antworten hat, ohne die Gegengründe zu prüfen, und von den "
                "Einzelwissenschaften, deren Fragen sie oft gestellt hat, "
                "bevor diese sich abspalteten - die Physik hiess einmal "
                "Naturphilosophie, die Psychologie war ein Kapitel der "
                "Seelenlehre."
            ),
            worum_es_geht=(
                "philosophische von empirischen Fragen unterscheiden",
                "ein Argument in Prämissen und Konklusion zerlegen",
                "erklären, was Philosophie von Weltanschauung trennt",
            ),
            fuehrt_zu=("phi-sokrates", "phi-erkenntnis", "phi-ethik"),
            begriffe=(
                "Argument", "Prämisse", "Konklusion", "Gültigkeit",
                "Metaphysik", "Erkenntnistheorie", "Ethik", "Logik",
                "Weltanschauung",
            ),
            literatur=(
                "Thomas Nagel: Was bedeutet das alles?",
                "Jay F. Rosenberg: Philosophieren. Ein Handbuch für Anfänger",
            ),
            anlaesse=(
                _f("Woran erkennt man, dass eine Frage philosophisch ist und "
                   "nicht empirisch?", "kennen",
                   "nicht durch Beobachtung oder Experiment entscheidbar",
                   "es geht um Begriffe, Gründe, Geltung",
                   "Beispiel: 'Was ist Gerechtigkeit?' gegen 'Wie hoch ist "
                   "die Kriminalität?'"),
                _f("Zerlege das Argument: 'Alle Menschen sind sterblich, "
                   "Sokrates ist ein Mensch, also ist Sokrates sterblich.' "
                   "Was macht es gültig - und was würde es wahr machen?",
                   "anwenden",
                   "Gültigkeit: Form, aus der die Konklusion folgt",
                   "Wahrheit: die Prämissen müssen zutreffen",
                   "gültig und wahr sind zwei verschiedene Prüfungen"),
                _f("Die Physik hat sich von der Philosophie gelöst, die "
                   "Psychologie auch. Bleibt der Philosophie am Ende nichts "
                   "- oder gibt es Fragen, die grundsätzlich bei ihr "
                   "bleiben?", "beurteilen",
                   "Abspaltungsthese und ihre Grenze",
                   "Normen, Begriffe und Geltungsfragen wandern nicht ab",
                   "Wissenschaftstheorie als Philosophie ÜBER die Abspaltungen"),
            ),
        ),
        Thema(
            kennung="phi-sokrates",
            titel="Sokrates und die Kunst des Fragens",
            abriss=(
                "Sokrates hat kein Buch geschrieben und keine Lehre "
                "hinterlassen - sein Beitrag ist eine Methode. Er ging auf "
                "den Markt von Athen und fragte die Leute, was das sei, "
                "wovon sie wie selbstverständlich redeten: Tapferkeit, "
                "Frömmigkeit, Gerechtigkeit. Die Befragten verwickelten "
                "sich in Widersprüche, und genau darin lag der Ertrag - das "
                "Wissen des Nichtwissens ist der Anfang der Prüfung. Seine "
                "Gesprächsführung, die Mäeutik oder Hebammenkunst, holt aus "
                "dem Gegenüber heraus, was es unausgesprochen schon denkt. "
                "Athen hat ihn dafür 399 v. Chr. zum Tod verurteilt: wegen "
                "Gottlosigkeit und Verführung der Jugend - der Prozess ist "
                "die Gründungsurkunde der Frage, was Denken kosten darf."
            ),
            worum_es_geht=(
                "die sokratische Methode an einem Beispiel vorführen",
                "erklären, was das Wissen des Nichtwissens leistet",
                "den Prozess gegen Sokrates historisch und philosophisch "
                "einordnen",
            ),
            baut_auf=("phi-was-ist-das",),
            fuehrt_zu=("phi-platon",),
            begriffe=(
                "Sokrates", "Mäeutik", "Elenktik", "Aporie", "sokratische Ironie",
                "Wissen des Nichtwissens", "Definition", "Apologie",
            ),
            literatur=(
                "Platon: Apologie des Sokrates",
                "Platon: Laches (über die Tapferkeit)",
                "Xenophon: Erinnerungen an Sokrates",
            ),
            anlaesse=(
                _f("Warum nannte Sokrates seine Methode Hebammenkunst?",
                   "kennen",
                   "er trägt kein Wissen ein, er hilft beim Hervorbringen",
                   "Fragen statt Belehren",
                   "die Aporie als produktive Ratlosigkeit"),
                _f("Führe ein sokratisches Gespräch: Was ist Mut? Prüfe die "
                   "erste Antwort, die dir einfällt, auf ein Gegenbeispiel.",
                   "anwenden",
                   "Definition statt Beispielliste verlangen",
                   "Gegenbeispiel: Ist der Draufgänger mutig?",
                   "die Definition verbessern statt sie aufgeben"),
                _f("Sokrates hätte fliehen können und blieb. Im 'Kriton' "
                   "begründet er das mit dem Gehorsam gegen die Gesetze - "
                   "überzeugt dich das Argument?", "beurteilen",
                   "die Personifikation der Gesetze und der stille Vertrag",
                   "Spannung zur Apologie: Gehorsam gegen den eigenen Logos",
                   "ziviler Ungehorsam als Gegenposition"),
            ),
        ),
        Thema(
            kennung="phi-platon",
            titel="Platon: Ideenlehre und Höhlengleichnis",
            abriss=(
                "Platon zog aus dem sokratischen Fragen einen radikalen "
                "Schluss: Wenn wir nach DER Gerechtigkeit fragen können, "
                "obwohl wir nur einzelne gerechte Handlungen sehen, muss es "
                "etwas geben, worauf die Frage zielt - die Idee, die "
                "unveränderliche Gestalt hinter den wandelbaren Dingen. Das "
                "Höhlengleichnis erzählt diese Lehre als Bild: Gefesselte "
                "sehen Schatten an der Wand und halten sie für die Welt; "
                "einer wird losgebunden, steigt ans Licht, erkennt - und "
                "wird beim Wiederabstieg verlacht. Es ist zugleich Platons "
                "Bildungstheorie und seine Erklärung, warum Athen den "
                "Aufgestiegenen tötete."
            ),
            worum_es_geht=(
                "die Ideenlehre aus dem Problem des Allgemeinen entwickeln",
                "das Höhlengleichnis deuten, Stufe für Stufe",
                "die klassischen Einwände gegen die Ideenlehre kennen",
            ),
            baut_auf=("phi-sokrates",),
            fuehrt_zu=("phi-aristoteles", "phi-erkenntnis"),
            begriffe=(
                "Platon", "Idee", "Ideenlehre", "Teilhabe", "Höhlengleichnis",
                "Liniengleichnis",
                "das Gute", "Anamnesis", "Dialog", "Akademie",
                "Universalienproblem",
            ),
            literatur=(
                "Platon: Politeia, Buch VI und VII",
                "Platon: Phaidon",
                "Michael Erler: Platon (Beck Denker)",
            ),
            zeigenswert=(
                "ein Schema des Höhlengleichnisses - das Gleichnis ist "
                "selbst ein Bild und will als Bild verstanden werden",
            ),
            anlaesse=(
                _f("Was ist eine Idee bei Platon - und was ist sie nicht?",
                   "kennen",
                   "unveränderliches Urbild, nicht Vorstellung im Kopf",
                   "die Dinge haben an ihr teil",
                   "erkennbar durch Denken, nicht durch die Sinne"),
                _f("Geh das Höhlengleichnis durch: Wofür stehen Schatten, "
                   "Feuer, Aufstieg und Rückkehr?", "anwenden",
                   "Schatten: Meinungen und Bilder",
                   "Aufstieg: Bildung als Umwendung der ganzen Seele",
                   "Rückkehr: die Pflicht des Erkennenden - und ihr Preis"),
                _f("Aristoteles wendet ein, die Ideenlehre verdopple die "
                   "Welt, ohne etwas zu erklären. Trifft der Einwand - und "
                   "was bliebe von Platon, wenn er trifft?", "beurteilen",
                   "der 'dritte Mensch' als Regressargument",
                   "was die Teilhabe erklären soll und was nicht",
                   "Platon ohne Zwei-Welten: Ideen als Massstäbe"),
            ),
        ),
        Thema(
            kennung="phi-aristoteles",
            titel="Aristoteles: Logik, Natur und das gute Leben",
            abriss=(
                "Aristoteles, zwanzig Jahre Schüler Platons, holte die Ideen "
                "auf die Erde zurück: Das Allgemeine existiert nicht neben "
                "den Dingen, sondern in ihnen - die Form des Menschen gibt "
                "es nur in Menschen. Er erfand die Logik als Lehre vom "
                "gültigen Schluss, ordnete das Wissen seiner Zeit von der "
                "Biologie bis zur Dichtung, und begründete die Ethik neu: "
                "Gut leben heisst nicht Regeln befolgen, sondern zur besten "
                "Ausübung der eigenen Anlagen finden - Tugend ist die durch "
                "Übung erworbene Haltung, und Glück ist kein Gefühl, sondern "
                "gelingende Tätigkeit. Zweitausend Jahre lang war 'der "
                "Philosoph' sein Name."
            ),
            worum_es_geht=(
                "den Unterschied zu Platon am Universalienproblem erklären",
                "die Tugendethik mit der Lehre von der Mitte darstellen",
                "erklären, warum Glück bei Aristoteles Tätigkeit ist",
            ),
            baut_auf=("phi-platon",),
            fuehrt_zu=("phi-ethik",),
            begriffe=(
                "Aristoteles", "Form und Stoff", "Substanz", "Syllogismus",
                "Teleologie",
                "eudaimonia", "Tugend", "Mesotes", "Praxis", "Lykeion",
            ),
            literatur=(
                "Aristoteles: Nikomachische Ethik, Buch I und II",
                "Aristoteles: Metaphysik, Buch I",
                "Otfried Höffe: Aristoteles",
            ),
            zeigenswert=(
                "Raffaels Schule von Athen - Platon zeigt nach oben, "
                "Aristoteles zur Erde: das Gemälde enthält eine These über "
                "beide",
            ),
            anlaesse=(
                _f("Was meint Aristoteles mit der Mitte zwischen den "
                   "Extremen?", "kennen",
                   "Tugend als Mitte zwischen Zuviel und Zuwenig",
                   "Mut zwischen Feigheit und Tollkühnheit",
                   "Mitte relativ zu uns, kein Rechenmittelwert"),
                _f("Wende die Mesotes-Lehre auf die Freigebigkeit an: Wo "
                   "liegen die Extreme, und wovon hängt die Mitte ab?",
                   "anwenden",
                   "Geiz und Verschwendung als Ränder",
                   "abhängig von Vermögen, Lage, Empfänger",
                   "die Klugheit als Vermögen, die Mitte zu treffen"),
                _f("Aristoteles gründet die Ethik auf die Natur des "
                   "Menschen. Was wird aus diesem Fundament, wenn man keine "
                   "feste Natur des Menschen mehr annimmt?", "beurteilen",
                   "der naturalistische Fehlschluss als Einwand",
                   "moderne Tugendethik ohne Teleologie: MacIntyre, Nussbaum",
                   "was 'gelingendes Leben' ohne Wesensbestimmung heissen kann"),
            ),
        ),
    ),
)

_FRAGEN = Gebiet(
    kennung="phi-fragen",
    titel="Die grossen Fragen",
    beschreibung=(
        "Erkenntnis, Ethik, Sprache, Geist - die Felder, auf denen bis "
        "heute gearbeitet wird, bis zur Gegenwartsphilosophie."
    ),
    themen=(
        Thema(
            kennung="phi-erkenntnis",
            titel="Erkenntnistheorie: von Descartes zu Kant",
            abriss=(
                "Descartes suchte einen Punkt, an dem der Zweifel abprallt, "
                "und fand ihn im Zweifeln selbst: cogito, ergo sum - wer "
                "zweifelt, denkt, und wer denkt, ist. Von dort spaltete sich "
                "die Neuzeit in zwei Lager: Die Rationalisten trauten der "
                "Vernunft, die Empiristen den Sinnen, und Hume trieb den "
                "Empirismus in die Krise, als er zeigte, dass wir Ursache "
                "und Wirkung nie beobachten, sondern nur Gewohnheit. Kants "
                "Antwort war eine Umkehrung: Nicht unser Erkennen richtet "
                "sich nach den Gegenständen, sondern die Gegenstände der "
                "Erfahrung richten sich nach den Formen unseres Erkennens - "
                "Raum, Zeit und Kategorien sind die Brille, die wir nicht "
                "absetzen können."
            ),
            worum_es_geht=(
                "das cogito-Argument Schritt für Schritt nachvollziehen",
                "Rationalismus und Empirismus an Beispielen unterscheiden",
                "Kants kopernikanische Wende erklären",
            ),
            baut_auf=("phi-platon",),
            fuehrt_zu=("phi-sprache", "phi-geist"),
            begriffe=(
                "Descartes", "Kant", "Hume", "cogito", "methodischer Zweifel",
                "Rationalismus",
                "Empirismus", "Kausalität", "a priori", "a posteriori",
                "synthetische Urteile a priori", "Ding an sich",
                "kopernikanische Wende",
            ),
            literatur=(
                "René Descartes: Meditationen über die Erste Philosophie",
                "David Hume: Eine Untersuchung über den menschlichen "
                "Verstand",
                "Immanuel Kant: Kritik der reinen Vernunft (Vorrede B)",
            ),
            anlaesse=(
                _f("Was genau überlebt bei Descartes den methodischen "
                   "Zweifel - und was nicht?", "kennen",
                   "das denkende Ich im Vollzug des Zweifelns",
                   "nicht: Körper, Aussenwelt, Mathematik",
                   "der Zweifel als Werkzeug, nicht als Ziel"),
                _f("Hume sagt, wir sehen nie Verursachung, nur Abfolge. "
                   "Prüfe das am Billardstoss: Was beobachtest du wirklich?",
                   "anwenden",
                   "Berührung, dann Bewegung - keine 'Kraft' sichtbar",
                   "Erwartung aus Gewohnheit, nicht aus Einsicht",
                   "warum das die Naturwissenschaft trotzdem nicht lähmt"),
                _f("Kant rettet die Notwendigkeit der Naturgesetze um den "
                   "Preis, dass wir das Ding an sich nie erkennen. Ist der "
                   "Preis zu hoch?", "beurteilen",
                   "was 'Erscheinung' bei Kant NICHT heisst: Schein",
                   "der deutsche Idealismus als Aufstand gegen das Ding an sich",
                   "heutige Erben: Konstruktivismus und seine Kritiker"),
            ),
        ),
        Thema(
            kennung="phi-ethik",
            titel="Ethik: Pflicht, Nutzen, Tugend",
            abriss=(
                "Auf die Frage, was ich tun soll, gibt die Philosophie drei "
                "grosse Antwortfamilien. Die Deontologie prüft die Handlung "
                "selbst: Kants kategorischer Imperativ verlangt, nur nach "
                "Maximen zu handeln, die jeder wollen könnte - lügen bleibt "
                "falsch, auch wenn es nützt. Der Utilitarismus prüft die "
                "Folgen: richtig ist, was das Wohlergehen aller Betroffenen "
                "am meisten mehrt - und nimmt dafür in Kauf, dass im "
                "Grenzfall einer für viele geopfert wird. Die Tugendethik "
                "prüft den Handelnden: Was würde ein Mensch tun, der so "
                "geworden ist, wie man werden sollte? Die drei Familien "
                "geben in den meisten Fällen dieselbe Auskunft - "
                "philosophisch lehrreich sind die Fälle, in denen nicht."
            ),
            worum_es_geht=(
                "die drei Ansätze an einem Fall durchspielen",
                "den kategorischen Imperativ korrekt anwenden",
                "die Standardeinwände gegen jede der drei Familien kennen",
            ),
            baut_auf=("phi-aristoteles",),
            fuehrt_zu=("phi-gegenwart",),
            begriffe=(
                "Deontologie", "kategorischer Imperativ", "Imperativ", "Maxime",
                "Utilitarismus", "Konsequentialismus", "Nutzen",
                "Tugendethik", "Trolley-Problem", "Menschenwürde",
            ),
            literatur=(
                "Immanuel Kant: Grundlegung zur Metaphysik der Sitten",
                "John Stuart Mill: Der Utilitarismus",
                "Philippa Foot: Das Problem der Abtreibung und die Doktrin "
                "der Doppelwirkung (1967, Ursprung des Trolley-Falls)",
            ),
            anlaesse=(
                _f("Wie lautet der kategorische Imperativ, und was "
                   "unterscheidet ihn von der Goldenen Regel?", "kennen",
                   "Universalisierbarkeit der Maxime",
                   "Goldene Regel hängt an meinen Wünschen, der Imperativ nicht",
                   "die Selbstzweckformel als zweite Fassung"),
                _f("Am Weichenhebel: fünf retten, einen opfern? Spiele den "
                   "Fall mit allen drei Ansätzen durch.", "anwenden",
                   "Utilitarist: umlegen - fünf gegen einen",
                   "Kantianer: der eine wird zum blossen Mittel",
                   "warum die Brücken-Variante die Intuition kippt"),
                _f("Der Utilitarismus behandelt jeden gleich - und gerade "
                   "das wirft man ihm vor. Wie kann Gleichbehandlung ein "
                   "Einwand sein?", "beurteilen",
                   "keine Sonderpflichten: das eigene Kind zählt wie ein Fremder",
                   "Integritätseinwand von Bernard Williams",
                   "Regel-Utilitarismus als Reparaturversuch"),
            ),
        ),
        Thema(
            kennung="phi-sprache",
            titel="Sprachphilosophie: Wittgenstein",
            abriss=(
                "Wittgenstein hat die Philosophie zweimal umgebaut. Der "
                "frühe Wittgenstein des Tractatus sah die Sprache als Bild "
                "der Welt: Sätze bilden Tatsachen ab, und was sich nicht "
                "abbilden lässt - Ethik, Ästhetik, der Sinn des Lebens -, "
                "darüber muss man schweigen. Der späte Wittgenstein der "
                "Philosophischen Untersuchungen riss das selbst wieder ein: "
                "Die Bedeutung eines Wortes ist sein Gebrauch, und Sprache "
                "ist kein Bild, sondern ein Gewimmel von Sprachspielen, "
                "verwoben in Lebensformen. Viele philosophische Probleme, so "
                "seine Diagnose, entstehen, wenn die Sprache feiert - wenn "
                "Wörter aus ihrem Arbeitszusammenhang gerissen werden. Hier "
                "berührt die Philosophie die Sprachwissenschaft."
            ),
            worum_es_geht=(
                "Bildtheorie und Gebrauchstheorie der Bedeutung "
                "gegenüberstellen",
                "den Begriff des Sprachspiels an Beispielen erläutern",
                "das Privatsprachenargument in Grundzügen nachvollziehen",
            ),
            baut_auf=("phi-erkenntnis",),
            fuehrt_zu=("phi-geist",),
            begriffe=(
                "Wittgenstein", "Tractatus", "Sprachspiel", "Lebensform",
                "Familienähnlichkeit", "Gebrauchstheorie",
                "Privatsprachenargument", "Regelfolgen",
            ),
            literatur=(
                "Ludwig Wittgenstein: Tractatus logico-philosophicus",
                "Ludwig Wittgenstein: Philosophische Untersuchungen",
                "Joachim Schulte: Wittgenstein. Eine Einführung",
            ),
            anlaesse=(
                _f("Was heisst: Die Bedeutung eines Wortes ist sein "
                   "Gebrauch?", "kennen",
                   "gegen die Vorstellung, Bedeutung sei ein inneres Bild",
                   "Bedeutung zeigt sich im Sprachspiel",
                   "dasselbe Wort, verschiedene Spiele, verschiedene Bedeutung"),
                _f("'Spiel' lässt sich nicht durch gemeinsame Merkmale "
                   "definieren, sagt Wittgenstein. Prüfe es: Suche das "
                   "Merkmal, das Schach, Patience und Fangen teilen.",
                   "anwenden",
                   "Wettbewerb? Patience hat keinen Gegner",
                   "Regeln? Fangen hat kaum welche",
                   "Familienähnlichkeit statt Wesensdefinition"),
                _f("Wenn philosophische Probleme Sprachverwirrungen sind, "
                   "ist Philosophie dann Therapie statt Erkenntnis - und "
                   "löst sie sich damit selbst auf?", "beurteilen",
                   "Wittgensteins Fliegenglas-Bild",
                   "was übrig bleibt: Übersicht statt Theorie",
                   "der Einwand: manche Probleme überleben die Klärung"),
            ),
        ),
        Thema(
            kennung="phi-geist",
            titel="Philosophie des Geistes: Bewusstsein",
            abriss=(
                "Dass es sich irgendwie anfühlt, dieses Wesen zu sein - das "
                "ist das eigentliche Rätsel. Die leichten Probleme des "
                "Bewusstseins betreffen Funktionen: Wahrnehmen, Erinnern, "
                "Steuern - alles im Prinzip neuronal erklärbar. Das schwere "
                "Problem, wie Chalmers es nannte, ist das Erleben selbst: "
                "Warum ist all diese Verarbeitung von etwas begleitet, "
                "statt im Dunkeln zu laufen? Nagels Frage, wie es ist, eine "
                "Fledermaus zu sein, und Jacksons Gedankenexperiment von "
                "der Farbforscherin Mary, die alles über Rot weiss und es "
                "nie gesehen hat, halten das Rätsel offen - gegen jede "
                "vorschnelle Auskunft, das Gehirn sei eben ein Computer. Für "
                "ein Gespräch mit einer Maschine ist das kein fernes Thema."
            ),
            worum_es_geht=(
                "leichte und schweres Problem des Bewusstseins unterscheiden",
                "die Gedankenexperimente von Nagel und Jackson wiedergeben",
                "die Hauptpositionen von Dualismus bis Illusionismus "
                "einordnen",
            ),
            baut_auf=("phi-erkenntnis",),
            fuehrt_zu=("phi-gegenwart",),
            begriffe=(
                "Bewusstsein", "Qualia", "das schwere Problem", "Physikalismus",
                "Dualismus", "Funktionalismus", "Wissensargument",
                "Fledermaus-Argument", "Emergenz", "Leib-Seele-Problem",
            ),
            literatur=(
                "Thomas Nagel: What Is It Like to Be a Bat? (1974)",
                "Frank Jackson: Epiphenomenal Qualia (1982)",
                "David Chalmers: The Conscious Mind",
            ),
            anlaesse=(
                _f("Was unterscheidet das schwere Problem des Bewusstseins "
                   "von den leichten?", "kennen",
                   "Funktionen erklären gegen Erleben erklären",
                   "warum Verarbeitung überhaupt von Erleben begleitet ist",
                   "die Erklärungslücke"),
                _f("Mary kennt alle physikalischen Tatsachen über Farbe und "
                   "sieht zum ersten Mal Rot. Lernt sie etwas Neues? Spiele "
                   "beide Antworten durch.", "anwenden",
                   "ja: dann sind physikalische Tatsachen nicht alle Tatsachen",
                   "nein: dann ist Wissen-wie kein Wissen-dass",
                   "die Fähigkeits-Antwort von Lewis"),
                _f("Wenn ein Sprachmodell sagt, es verstehe dich - was "
                   "würde entscheiden, ob dahinter Erleben steht? Ist die "
                   "Frage überhaupt empirisch entscheidbar?", "beurteilen",
                   "Verhalten gegen Innenperspektive",
                   "das Problem des Fremdpsychischen, verschärft",
                   "warum Vorsicht in beide Richtungen geboten ist"),
            ),
        ),
        Thema(
            kennung="phi-gegenwart",
            titel="Gegenwartsphilosophie: Markus Gabriel und der Neue "
                  "Realismus",
            abriss=(
                "Markus Gabriel, seit 2009 Professor in Bonn, vertritt den "
                "Neuen Realismus - eine Antwort auf die Postmoderne, für die "
                "alles Konstruktion war, und auf den Szientismus, für den "
                "nur zählt, was die Physik beschreibt. Seine Sinnfeld-"
                "Ontologie behauptet beides zugleich: Es gibt unendlich "
                "viele Sinnfelder, in denen Dinge erscheinen - Zahlen in der "
                "Mathematik, Faust im Drama, Planeten im All -, und alle "
                "existieren wirklich, jeweils in ihrem Feld. Nur eines gibt "
                "es nicht: die Welt als Gesamtheit von allem, denn ein Feld, "
                "das alle Felder enthielte, müsste in einem weiteren Feld "
                "erscheinen. Daher der provokante Buchtitel: Warum es die "
                "Welt nicht gibt. In 'Der Sinn des Denkens' wendet er das "
                "gegen die These, Denken sei Informationsverarbeitung - für "
                "das Gespräch mit einem digitalen Professor eine reizvolle "
                "Pointe."
            ),
            worum_es_geht=(
                "den Neuen Realismus gegen Postmoderne und Szientismus "
                "abgrenzen",
                "die Sinnfeld-Ontologie und das Welt-Argument wiedergeben",
                "Gabriels Kritik am Naturalismus des Geistes einordnen",
            ),
            baut_auf=("phi-erkenntnis", "phi-geist"),
            begriffe=(
                "Neuer Realismus", "Sinnfeld", "Sinnfeld-Ontologie",
                "Existenz als Erscheinen", "Weltbegriff", "Szientismus",
                "Konstruktivismus", "Neuroexistenzialismus",
            ),
            literatur=(
                "Markus Gabriel: Warum es die Welt nicht gibt",
                "Markus Gabriel: Der Sinn des Denkens",
                "Markus Gabriel: Fiktionen",
            ),
            anlaesse=(
                _f("Was ist ein Sinnfeld, und was heisst dann 'existieren'?",
                   "kennen",
                   "Existenz ist Erscheinen in einem Sinnfeld",
                   "Faust existiert - im Drama, nicht in Weimar",
                   "kein Feld ist das grundlegende"),
                _f("Skizziere das Argument, warum es die Welt nicht geben "
                   "soll. Wo ist die angreifbarste Stelle?", "anwenden",
                   "die Welt müsste in einem Sinnfeld erscheinen",
                   "das Gesamtfeld führt in den Regress",
                   "angreifbar: gilt das für jede Fassung von 'Gesamtheit'?"),
                _f("Kritiker sagen, der Neue Realismus sei alter Wein: "
                   "Meinong und der Pluralismus hätten das schon gehabt. "
                   "Was ist an Gabriel neu - und trägt es?", "beurteilen",
                   "gegen Meinong: kein Bestand ohne Feld",
                   "Anti-Weltbild statt neuer Gesamttheorie",
                   "die Auseinandersetzung mit dem Naturalismus als Kern"),
            ),
        ),
    ),
)


PHILOSOPHIE = Feld(
    kennung="philosophie",
    titel="Philosophie",
    gegenstand=(
        "Die Fragen, die sich nicht durch Messen erledigen lassen: Erkennen, "
        "Handeln, Bedeutung, Bewusstsein - von den Athenern bis zur "
        "Gegenwart."
    ),
    methode=(
        "Das Argument. Eine Behauptung gilt so viel wie ihre Begründung, und "
        "geprüft wird durch Gegenbeispiel, Widerspruchsnachweis und "
        "Gedankenexperiment. Die Geschichte des Fachs ist dabei nicht "
        "Vorgeschichte, sondern Werkzeugkasten: Platon ist ein "
        "Gesprächspartner, kein Museumsstück."
    ),
    aufgaben=(
        "Begriffe klären, mit denen alle hantieren und die niemand definiert "
        "hat - Wahrheit, Freiheit, Gerechtigkeit",
        "Argumente prüfen: verborgene Prämissen aufdecken, Fehlschlüsse "
        "benennen",
        "die Voraussetzungen der Wissenschaften untersuchen, die diese "
        "selbst nicht prüfen können",
        "Orientierung im Handeln geben, ohne sie zu verordnen",
        "die grossen Texte lesbar machen - als Denkwege, nicht als "
        "Zitatensammlung",
    ),
    nachbarn=(
        "Theologie – argumentiert innerhalb einer Offenbarung; die "
        "Philosophie setzt keine voraus",
        "Psychologie – beschreibt, wie Menschen denken; die Philosophie "
        "fragt, was gültiges Denken ist",
        "Sprachwissenschaft – beschreibt den Gebrauch; die Sprachphilosophie "
        "fragt, was Bedeutung überhaupt ist",
        "Lebenshilfe – gibt Antworten ohne die Gegengründe; Philosophie "
        "beginnt bei den Gegengründen",
    ),
    einstiege=("phi-was-ist-das",),
    gebiete=(_ANFAENGE, _FRAGEN),
)
