"""Geografie - die Landkarte über das Fach der Landkarten.

Zwei Eigenheiten dieser Karte. Erstens: Kaum ein Thema ist ohne
``zeigenswert`` - das liegt am Fach selbst, dessen Gegenstand räumlich
ist und dessen wichtigstes Werkzeug die Karte. Gerade deshalb steht die
Kartografie gleich am Anfang, und zwar mit ihrer kritischen Seite: Jede
Karte verzerrt, und wer Karten liest, ohne das zu wissen, wird von ihnen
gelesen.

Zweitens: Das Gebiet Erde enthält ein Thema zu Gesteinen und Fossilien.
Das ist streng genommen Geologie und nicht Geografie - es steht trotzdem
hier, weil der Benutzer nachweislich damit arbeitet: Sein Dokument
'Steine lesen - Fossilien, Gold, Mineralien Schweiz' liegt im Gedächtnis
des Orb, und er hat mehrfach danach gefragt. Eine Landkarte, die am
Interesse des Lernenden vorbeigezeichnet ist, verfehlt ihren Zweck.
"""

from __future__ import annotations

from backend.studium.landkarte import Anlass, Feld, Gebiet, Thema


def _f(frage: str, tiefe: str, *woran: str) -> Anlass:
    return Anlass(frage=frage, tiefe=tiefe, woran_man_es_merkt=tuple(woran))


_WERKZEUG = Gebiet(
    kennung="geo-werkzeug",
    titel="Das Fach und sein Werkzeug",
    beschreibung="Was Geografie ist, und die Karte als Instrument und Falle.",
    themen=(
        Thema(
            kennung="geo-was-ist-das",
            titel="Was Geografie ist und was sie nicht ist",
            abriss=(
                "Geografie ist die Wissenschaft von der Erdoberfläche als "
                "dem Raum, in dem Natur und Mensch aufeinandertreffen - "
                "nicht das Auswendigwissen von Hauptstädten. Ihre eine "
                "Hälfte, die physische Geografie, fragt nach Relief, Klima, "
                "Böden und Gewässern; die andere, die Humangeografie, nach "
                "Städten, Wirtschaft und Bevölkerung. Ihr eigentlicher "
                "Gegenstand ist die Schnittstelle: Warum siedeln Menschen "
                "am Vulkan, warum verschiebt der Klimawandel die "
                "Anbaugrenzen, warum wächst die eine Stadt und stirbt die "
                "andere? Ihre Kernfrage ist immer dieselbe: Warum ist etwas "
                "GENAU HIER so und nicht anderswo?"
            ),
            worum_es_geht=(
                "physische Geografie und Humangeografie unterscheiden",
                "an einem Beispiel die Mensch-Umwelt-Schnittstelle zeigen",
                "die Warum-hier-Frage als Kern des Fachs gebrauchen",
            ),
            fuehrt_zu=("geo-karten", "geo-platten", "geo-stadt"),
            begriffe=(
                "physische Geografie", "Humangeografie", "Raum",
                "Standortfaktor", "Massstab", "Region", "Mensch-Umwelt-System",
            ),
            literatur=(
                "Hans Gebhardt u. a. (Hrsg.): Geographie. Physische "
                "Geographie und Humangeographie",
                "Alexander von Humboldt: Kosmos (als historischer Bezugspunkt)",
            ),
            zeigenswert=(
                "ein Satellitenbild der Erde bei Nacht - Lichter als Karte "
                "der Besiedlung",
            ),
            anlaesse=(
                _f("Was untersucht die Geografie - und warum ist "
                   "'Hauptstädte kennen' die falsche Antwort?", "kennen",
                   "Raum als Gegenstand, nicht Fakten über Orte",
                   "die zwei Hälften und ihre Schnittstelle",
                   "die Warum-hier-Frage"),
                _f("Nimm deinen eigenen Wohnort: Welche natürlichen und "
                   "welche menschlichen Gründe erklären, dass er genau dort "
                   "liegt?", "anwenden",
                   "Wasser, Relief, Böden als Lagefaktoren",
                   "Verkehrswege, Herrschaft, Wirtschaft",
                   "Gründe von damals wirken als Beharrung fort"),
                _f("Determinismus oder Possibilismus: Bestimmt die Natur, "
                   "wie Menschen leben, oder eröffnet sie nur Spielräume? "
                   "Woran ist die alte Streitfrage heute noch lebendig?",
                   "beurteilen",
                   "Geodeterminismus und seine politische Geschichte",
                   "Possibilismus: Natur als Angebot",
                   "Klimawandel als neue Auflage der Frage"),
            ),
        ),
        Thema(
            kennung="geo-karten",
            titel="Kartografie: Karten lesen, Karten misstrauen",
            abriss=(
                "Eine Karte ist keine verkleinerte Wirklichkeit, sondern "
                "eine Behauptung über sie: verkleinert, verebnet, "
                "verallgemeinert - und jedes dieser drei Wörter ist eine "
                "Entscheidung. Die Erdkugel lässt sich nicht ohne Verzerrung "
                "auf eine Fläche bringen; die Mercator-Projektion hält die "
                "Winkel treu und macht dafür Grönland so gross wie Afrika, "
                "das in Wahrheit vierzehnmal grösser ist. Dazu kommen "
                "Auswahl und Weglassen, Farben und Schrift - eine Karte hat "
                "immer einen Zweck, und wer ihn nicht kennt, verwechselt "
                "die Karte mit dem Gebiet. Kartenlesen ist darum "
                "Quellenkritik mit anderen Mitteln."
            ),
            worum_es_geht=(
                "erklären, warum jede Projektion verzerren muss",
                "Mercator, Peters und flächentreue Projektionen einordnen",
                "eine thematische Karte auf ihre Machart hin befragen",
            ),
            baut_auf=("geo-was-ist-das",),
            fuehrt_zu=("geo-klima", "geo-bevoelkerung"),
            begriffe=(
                "Projektion", "Mercator", "winkeltreu", "flächentreu",
                "Massstab", "Generalisierung", "Signatur", "Isolinie",
                "thematische Karte", "Choroplethenkarte",
            ),
            literatur=(
                "Mark Monmonier: How to Lie with Maps",
                "Jürgen Bollmann / Wolf Koch (Hrsg.): Lexikon der "
                "Kartographie und Geomatik",
            ),
            zeigenswert=(
                "Mercator- und flächentreue Projektion nebeneinander",
                "Grönland und Afrika im wahren Grössenverhältnis",
            ),
            anlaesse=(
                _f("Warum kann keine Karte die Erde unverzerrt zeigen?",
                   "kennen",
                   "Kugeloberfläche lässt sich nicht abwickeln",
                   "winkeltreu, flächentreu, längentreu: nie alles zugleich",
                   "die Wahl der Projektion folgt dem Zweck"),
                _f("Auf einer Mercator-Karte wirkt Russland erdrückend "
                   "gross. Erkläre einem Laien, was da geschieht - und für "
                   "wen diese Projektion trotzdem die richtige ist.",
                   "anwenden",
                   "Streckung zu den Polen hin",
                   "winkeltreu: für die Seefahrt gebaut",
                   "fürs Vergleichen von Ländergrössen ungeeignet"),
                _f("'Karten sind Machtinstrumente' - von Kolonialgrenzen mit "
                   "dem Lineal bis zur Weltkarte mit Europa in der Mitte. "
                   "Wie weit trägt die These, und wo kippt sie in "
                   "Kartenverschwörung?", "beurteilen",
                   "Auswahl und Zentrierung als Entscheidungen",
                   "Peters-Karte: berechtigter Einwand, fragwürdige Lösung",
                   "Verzerrung aus Zweck gegen Verzerrung aus Absicht"),
            ),
        ),
    ),
)

_ERDE = Gebiet(
    kennung="geo-erde",
    titel="Die Erde",
    beschreibung="Platten, Gesteine, Klima - die physische Grundlage.",
    themen=(
        Thema(
            kennung="geo-platten",
            titel="Plattentektonik",
            abriss=(
                "Dass Afrika und Südamerika zusammenpassen wie Puzzleteile, "
                "war lange ein Kuriosum - bis Alfred Wegener 1912 die "
                "Kontinentalverschiebung behauptete und dafür verlacht "
                "wurde: Ihm fehlte der Mechanismus. Erst die Vermessung der "
                "Ozeanböden in den 1960ern lieferte ihn - an den "
                "mittelozeanischen Rücken entsteht neue Kruste, an den "
                "Tiefseerinnen taucht sie ab, und die Kontinente reiten auf "
                "diesem Förderband. Die Plattentektonik erklärt mit einem "
                "Schlag, wo Erdbeben, Vulkane und Gebirge liegen: an den "
                "Rändern der Platten. Sie ist zugleich das Lehrstück dafür, "
                "wie eine richtige Idee scheitert, solange der Mechanismus "
                "fehlt."
            ),
            worum_es_geht=(
                "die drei Plattengrenztypen mit ihren Folgen erklären",
                "Wegeners Belege und das fehlende Glied benennen",
                "aus der Plattenkarte Erdbeben- und Vulkanzonen vorhersagen",
            ),
            baut_auf=("geo-was-ist-das",),
            fuehrt_zu=("geo-gesteine",),
            begriffe=(
                "Wegener", "Erdbeben", "Vulkan", "Lithosphärenplatte",
                "divergent", "konvergent",
                "Transformstörung", "Subduktion", "mittelozeanischer Rücken",
                "Konvektion", "Pazifischer Feuerring", "Kontinentaldrift",
            ),
            literatur=(
                "Alfred Wegener: Die Entstehung der Kontinente und Ozeane "
                "(1915)",
                "Frank Press / Raymond Siever: Allgemeine Geologie",
            ),
            zeigenswert=(
                "eine Weltkarte der Plattengrenzen mit Erdbebenherden",
                "ein Schnitt durch eine Subduktionszone",
            ),
            anlaesse=(
                _f("Welche drei Arten von Plattengrenzen gibt es, und was "
                   "geschieht an jeder?", "kennen",
                   "divergent: Spreizung, neue Kruste",
                   "konvergent: Subduktion oder Kollision",
                   "transform: Vorbeigleiten, Beben ohne Vulkane"),
                _f("Japan hat Vulkane und schwere Beben, die Alpen haben "
                   "Beben, aber keine Vulkane. Erkläre den Unterschied aus "
                   "der Tektonik.", "anwenden",
                   "Japan: Subduktion - abtauchende Platte schmilzt auf",
                   "Alpen: Kontinentalkollision - nichts taucht tief genug ab",
                   "die Plattenkarte als Vorhersageinstrument"),
                _f("Wegener hatte recht und wurde abgelehnt. War die "
                   "Ablehnung ein Versagen der Wissenschaft - oder hat sie "
                   "richtig funktioniert?", "beurteilen",
                   "Belege ohne Mechanismus sind Korrelation",
                   "die Skepsis war methodisch begründbar",
                   "was der Fall über wissenschaftlichen Konsens lehrt"),
            ),
        ),
        Thema(
            kennung="geo-gesteine",
            titel="Gesteine und Fossilien lesen",
            abriss=(
                "Gesteine sind das Archiv der Erde, und man kann in ihnen "
                "lesen. Der Kreislauf kennt drei Familien: Magmatite "
                "erstarren aus Schmelze, Sedimente lagern sich in Schichten "
                "ab, Metamorphite entstehen unter Druck und Hitze aus "
                "beiden. Nur die Schichten der Sedimente führen Fossilien - "
                "wer im Jura Ammoniten findet, hält den Beweis in der Hand, "
                "dass dort ein Meer war, und die Alpen führen Meeresboden "
                "in dreitausend Metern Höhe. Leitfossilien datieren die "
                "Schichten, das Prinzip der Lagerung ordnet sie: unten ist "
                "älter. An einem Aufschluss liegen Fossilien meist entlang "
                "der Schichtflächen, und wo weiche Mergel mit harten "
                "Kalkbänken wechseln, sind sie am leichtesten zu finden."
            ),
            worum_es_geht=(
                "die drei Gesteinsfamilien und ihren Kreislauf erklären",
                "an einem Aufschluss gezielt nach Fossilien suchen",
                "aus Gestein und Fossil den Ablagerungsraum erschliessen",
            ),
            baut_auf=("geo-platten",),
            fuehrt_zu=("geo-klima",),
            begriffe=(
                "Magmatit", "Sediment", "Metamorphit", "Gesteinskreislauf",
                "Schichtung", "Fossil", "Leitfossil", "Ammonit",
                "Aufschluss", "Stratigraphie", "Jura",
            ),
            literatur=(
                "Frank Press / Raymond Siever: Allgemeine Geologie",
                "Nicolaus Steno: Grundlagen der Stratigraphie (1669)",
            ),
            zeigenswert=(
                "ein Ammonit im Gestein",
                "ein Aufschluss mit deutlicher Schichtung",
                "das Schema des Gesteinskreislaufs",
            ),
            anlaesse=(
                _f("Warum findet man Fossilien fast nur in Sedimentgestein?",
                   "kennen",
                   "Magmatite: Schmelze zerstört alles Organische",
                   "Metamorphite: Druck und Hitze verformen es",
                   "Sedimente: Einbettung und ruhige Ablagerung"),
                _f("Du stehst an einem Aufschluss im Schweizer Jura: Wo "
                   "suchst du zuerst, und woran erkennst du eine "
                   "vielversprechende Schicht?", "anwenden",
                   "entlang der Schichtflächen, nicht quer",
                   "Wechsel von weichem Mergel und harter Kalkbank",
                   "frisch verwitterte Partien vor glatten Wänden"),
                _f("Ammoniten auf dreitausend Metern: Erkläre die "
                   "Beweiskette vom Fossil bis zur Alpenfaltung - und wo "
                   "sie angreifbar wäre.", "beurteilen",
                   "Fossil belegt marinen Ablagerungsraum",
                   "Hebung durch Kontinentalkollision",
                   "Alternativen prüfen und ausschliessen: Transport, "
                   "Umlagerung"),
            ),
        ),
        Thema(
            kennung="geo-klima",
            titel="Das Klimasystem und die Klimazonen",
            abriss=(
                "Das Klima der Erde ist eine Maschine mit einem einzigen "
                "Antrieb: Am Äquator kommt mehr Sonnenenergie an als an den "
                "Polen, und die Zirkulation von Luft und Ozean schafft den "
                "Überschuss polwärts. Daraus folgen die grossen Muster - "
                "die Passate, die Westwinde, die Wüstengürtel dort, wo "
                "trockene Luft absinkt, der Regen dort, wo feuchte "
                "aufsteigt. Die Klimazonen von den Tropen bis zur polaren "
                "Zone sind das stehende Bild dieser Strömung, und die "
                "Klassifikation von Köppen übersetzt es in Karten. Wer "
                "diese Maschine verstanden hat, versteht auch, warum ein "
                "kleiner Schub am Antrieb - mehr zurückgehaltene Wärme - "
                "das ganze Muster verschiebt."
            ),
            worum_es_geht=(
                "die planetarische Zirkulation aus dem Energiegefälle "
                "entwickeln",
                "die Lage der Wüsten- und Regengürtel erklären",
                "Klima von Wetter methodisch sauber trennen",
            ),
            baut_auf=("geo-was-ist-das",),
            fuehrt_zu=("geo-klimawandel",),
            begriffe=(
                "Wüste", "Strahlungsbilanz", "Passat", "innertropische "
                "Konvergenzzone", "Hadley-Zelle", "Westwindzone",
                "Klimazone", "Köppen-Klassifikation", "Golfstrom",
                "Kontinentalität",
            ),
            literatur=(
                "Wladimir Köppen: Klassifikation der Klimate (1918)",
                "Hans Gebhardt u. a.: Geographie, Teil physische Geographie",
            ),
            zeigenswert=(
                "die Klimazonen der Erde nach Köppen",
                "ein Schema der planetarischen Zirkulation",
            ),
            anlaesse=(
                _f("Warum liegen die grossen Wüsten der Erde fast alle um "
                   "den dreissigsten Breitengrad?", "kennen",
                   "absinkende Luft der Hadley-Zelle",
                   "Absinken heisst Erwärmen und Austrocknen",
                   "Sahara, Arabien, Kalahari, australische Wüsten als Gürtel"),
                _f("Hamburg und Winnipeg liegen fast auf derselben Breite - "
                   "warum sind die Winter so verschieden?", "anwenden",
                   "Golfstrom und Westwinde als Wärmepumpe Europas",
                   "Kontinentalität: Land kühlt schneller aus als Meer",
                   "Breitengrad allein sagt wenig"),
                _f("'Ein kalter Winter widerlegt die Erwärmung' - wo genau "
                   "liegt der Denkfehler, und wie erklärst du ihn, ohne zu "
                   "belehren?", "beurteilen",
                   "Wetter ist ein Zustand, Klima eine Statistik",
                   "Einzelfall gegen Verteilung",
                   "die richtige Frage: verschieben sich die Häufigkeiten?"),
            ),
        ),
        Thema(
            kennung="geo-klimawandel",
            titel="Der Klimawandel",
            abriss=(
                "Dass CO2 Wärme zurückhält, ist seit Arrhenius 1896 "
                "gerechnet, seit den 1950ern gemessen und heute so gut "
                "belegt wie wenig sonst in der Wissenschaft: Die Keeling-"
                "Kurve zeigt den Anstieg des CO2 Jahr für Jahr, die "
                "Temperaturreihen den der Wärme, und die Isotopensignatur "
                "des Kohlenstoffs verrät die Herkunft aus fossilen Quellen. "
                "Geografisch ist der Wandel ungleich: Die Arktis erwärmt "
                "sich mehrfach so schnell wie der Schnitt, Gletscher und "
                "Permafrost gehen zurück, Anbauzonen und Niederschläge "
                "verschieben sich - und am härtesten trifft es Regionen, "
                "die am wenigsten dazu beigetragen haben. Das ist keine "
                "Meinungsfrage, wohl aber eine Verteilungsfrage."
            ),
            worum_es_geht=(
                "die Beweiskette vom Treibhauseffekt bis zur Zuordnung "
                "menschlicher Ursachen darstellen",
                "regionale Folgen von globalen Mittelwerten unterscheiden",
                "die Verteilungsfrage von der Faktenfrage trennen",
            ),
            baut_auf=("geo-klima",),
            fuehrt_zu=("geo-bevoelkerung",),
            begriffe=(
                "Klimawandel", "Treibhauseffekt", "Keeling-Kurve", "Attribution",
                "Kipppunkt", "polare Verstärkung", "Permafrost",
                "Klimaszenario", "Anpassung", "Vermeidung", "IPCC",
            ),
            literatur=(
                "IPCC: Sechster Sachstandsbericht (Zusammenfassung für "
                "politische Entscheidungsträger)",
                "Svante Arrhenius: On the Influence of Carbonic Acid in the "
                "Air upon the Temperature of the Ground (1896)",
                "Stefan Rahmstorf / Hans Joachim Schellnhuber: Der "
                "Klimawandel",
            ),
            zeigenswert=(
                "die Keeling-Kurve",
                "eine Karte der Erwärmung nach Regionen",
                "der Gletschervergleich: dieselbe Ansicht, hundert Jahre "
                "Abstand",
            ),
            anlaesse=(
                _f("Woher weiss man, dass das zusätzliche CO2 vom Menschen "
                   "stammt und nicht aus Vulkanen oder dem Ozean?", "kennen",
                   "Isotopensignatur fossilen Kohlenstoffs",
                   "sinkender Sauerstoffanteil passt zur Verbrennung",
                   "Bilanz: Vulkane liefern einen Bruchteil der Emissionen"),
                _f("Die Schweiz erwärmt sich etwa doppelt so schnell wie "
                   "der globale Schnitt. Welche Folgen erwartest du für "
                   "Gletscher, Permafrost und Wintertourismus - und woran "
                   "würde man sie messen?", "anwenden",
                   "Landmasse und Höhenlage als Verstärker",
                   "Permafrost als Baugrund: Steinschlag, Murgänge",
                   "Schneefallgrenze gegen Höhenlage der Skigebiete"),
                _f("Wenn die Fakten so klar sind - warum ist die Politik so "
                   "strittig? Trenne sauber, was Wissenschaft klären kann "
                   "und was sie nicht klären kann.", "beurteilen",
                   "Ist-Fragen gegen Soll-Fragen",
                   "Verteilung von Kosten und Lasten als politische Frage",
                   "wo Skepsis legitim ist und wo sie Fakten leugnet"),
            ),
        ),
    ),
)

_MENSCH = Gebiet(
    kennung="geo-mensch",
    titel="Der Mensch im Raum",
    beschreibung="Bevölkerung und Städte - die Humangeografie.",
    themen=(
        Thema(
            kennung="geo-bevoelkerung",
            titel="Bevölkerungsgeografie und demografischer Wandel",
            abriss=(
                "Die Weltbevölkerung wuchs von einer Milliarde um 1800 auf "
                "über acht heute - aber die Geschichte dahinter ist keine "
                "Explosion, sondern ein Übergang: Erst sinkt die "
                "Sterblichkeit, dann, mit ein bis zwei Generationen "
                "Verzögerung, die Geburtenrate. Dieses Modell des "
                "demografischen Übergangs erklärt, warum Europa alterte, "
                "während Afrika wächst, und warum das Wachstum global "
                "bereits kippt. Die Alterspyramide macht die Lage eines "
                "Landes auf einen Blick lesbar - Pyramide, Glocke oder "
                "Urne erzählen drei verschiedene Zukünfte. Wanderung ist "
                "die dritte Grösse neben Geburt und Tod, und die am "
                "stärksten politisierte."
            ),
            worum_es_geht=(
                "das Modell des demografischen Übergangs erklären",
                "eine Alterspyramide lesen und daraus Folgen ableiten",
                "Wanderungsbewegungen mit Push- und Pull-Faktoren "
                "analysieren",
            ),
            baut_auf=("geo-karten",),
            fuehrt_zu=("geo-stadt",),
            begriffe=(
                "demografischer Übergang", "Geburtenrate", "Sterberate",
                "Alterspyramide", "Lebenserwartung", "Migration",
                "Push-Faktor", "Pull-Faktor", "Urbanisierungsgrad",
            ),
            literatur=(
                "Rainer Münz / Albert F. Reiterer: Wie schnell wächst die "
                "Zahl der Menschen?",
                "UN World Population Prospects (laufend)",
            ),
            zeigenswert=(
                "drei Alterspyramiden im Vergleich: Niger, Deutschland, "
                "Japan",
                "die Kurve des Weltbevölkerungswachstums",
            ),
            anlaesse=(
                _f("Was geschieht in den Phasen des demografischen "
                   "Übergangs?", "kennen",
                   "erst fällt die Sterblichkeit, dann die Geburtenrate",
                   "dazwischen liegt das schnelle Wachstum",
                   "am Ende Alterung statt Wachstum"),
                _f("Lies die deutsche Alterspyramide: Woher kommen die "
                   "Einkerbungen, und was folgt für Rente und "
                   "Arbeitsmarkt?", "anwenden",
                   "Kriege und Krisen als Kerben",
                   "geburtenstarke Jahrgänge wandern nach oben",
                   "Verhältnis von Beitragszahlern zu Empfängern"),
                _f("'Überbevölkerung' war die Angst der 1970er, heute "
                   "fürchten dieselben Länder die Schrumpfung. Was sagt "
                   "dieser Umschwung über demografische Prognosen?",
                   "beurteilen",
                   "Ehrlichs 'Population Bomb' und ihr Scheitern",
                   "Prognosen verlängern Trends - Übergänge brechen sie",
                   "was heutige Projektionen robuster macht und was nicht"),
            ),
        ),
        Thema(
            kennung="geo-stadt",
            titel="Stadtgeografie",
            abriss=(
                "Mehr als die Hälfte der Menschheit lebt in Städten, und "
                "die Stadt ist das dichteste Untersuchungsobjekt des Fachs: "
                "Auf wenigen Quadratkilometern drängen sich alle Fragen von "
                "Wirtschaft, Verkehr, Wohnen und Macht. Stadtmodelle von "
                "den Ringen Burgess' bis zur europäischen Stadt mit ihrem "
                "historischen Kern beschreiben, wie sich Nutzungen ordnen; "
                "Bodenpreise erklären einen Grossteil davon. Die grossen "
                "Gegenwartsfragen sind Wachstum und Verdrängung: Megastädte "
                "des Südens wachsen ohne Plan, während in den Innenstädten "
                "des Nordens die Aufwertung die alten Bewohner verdrängt - "
                "Gentrifizierung ist der Fachbegriff für einen Vorgang, den "
                "jeder kennt, der eine Grossstadtmiete zahlt."
            ),
            worum_es_geht=(
                "Stadtmodelle als Ordnungsversuche einordnen",
                "die europäische von der nordamerikanischen Stadt "
                "unterscheiden",
                "Gentrifizierung als Prozess mit Phasen beschreiben",
            ),
            baut_auf=("geo-bevoelkerung",),
            begriffe=(
                "Urbanisierung", "Megastadt", "Stadtmodell", "Zentralität",
                "Bodenrente", "Segregation", "Gentrifizierung",
                "Suburbanisierung", "informelle Siedlung",
            ),
            literatur=(
                "Heinz Heineberg: Stadtgeographie",
                "Saskia Sassen: The Global City",
            ),
            zeigenswert=(
                "Luftbilder einer europäischen und einer "
                "nordamerikanischen Stadt im Vergleich",
                "ein Stadtmodell-Schema",
            ),
            anlaesse=(
                _f("Woran erkennt man auf dem Luftbild eine europäische "
                   "Stadt?", "kennen",
                   "historischer Kern, enge Strassen, Ringstrukturen",
                   "Kirchen und Plätze als alte Zentren",
                   "Gegenprobe: Raster und Downtown in Nordamerika"),
                _f("Ein Altbauviertel bekommt Cafés, dann steigen die "
                   "Mieten, dann ziehen die Alten weg. Beschreibe die "
                   "Phasen der Gentrifizierung an diesem Fall.", "anwenden",
                   "Pioniere, Aufwerter, Verdrängung",
                   "die Rolle von Bodenpreis und Eigentum",
                   "woran man die Phase eines Viertels erkennt"),
                _f("Ist Gentrifizierung ein Problem oder normale "
                   "Stadtentwicklung? Trenne die Beschreibungs- von der "
                   "Bewertungsfrage.", "beurteilen",
                   "Aufwertung gegen Verdrängung: zwei Seiten eines Vorgangs",
                   "wer gewinnt, wer verliert, wer entscheidet",
                   "welche Instrumente Städte haben und was sie kosten"),
            ),
        ),
    ),
)


GEOGRAFIE = Feld(
    kennung="geografie",
    titel="Geografie",
    gegenstand=(
        "Die Erdoberfläche als Raum, in dem Natur und Mensch "
        "aufeinandertreffen - vom Gestein unter den Füssen bis zur "
        "Megastadt."
    ),
    methode=(
        "Räumlich fragen: Warum ist etwas genau hier so und nicht anderswo? "
        "Beantwortet wird mit Karte, Messung und Feldarbeit - und mit dem "
        "ständigen Wechsel des Massstabs, denn was auf der Weltkarte wie "
        "ein Muster aussieht, ist vor Ort ein Einzelfall mit Geschichte."
    ),
    aufgaben=(
        "die Muster der Erdoberfläche beschreiben und erklären - Klima, "
        "Relief, Siedlung, Wirtschaft",
        "Mensch-Umwelt-Beziehungen untersuchen, vom Anbau bis zur "
        "Naturgefahr",
        "Karten herstellen und ihre Machart durchschaubar machen",
        "Grundlagen für Planung liefern: wo gebaut, geschützt, gewirtschaftet "
        "werden kann",
        "räumliche Behauptungen prüfbar machen - von der Wüstenausbreitung "
        "bis zur Wohnungsnot",
    ),
    nachbarn=(
        "Geologie – fragt nach dem Bau der Erde in der Tiefe und in "
        "Jahrmillionen; die Geografie nach der Oberfläche im Menschenmassstab",
        "Meteorologie – untersucht das Wetter als physikalischen Prozess; "
        "die Geografie das Klima als räumliches Muster",
        "Soziologie – untersucht Gesellschaft; die Humangeografie deren "
        "räumliche Seite",
        "Erdkunde-Quiz – Hauptstädte wissen ist Gedächtnissport, keine "
        "Geografie",
    ),
    einstiege=("geo-was-ist-das",),
    gebiete=(_WERKZEUG, _ERDE, _MENSCH),
)
