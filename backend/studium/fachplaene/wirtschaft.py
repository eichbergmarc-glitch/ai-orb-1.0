"""Wirtschaftswissenschaft - die Landkarte.

Die Auswahl der Themen folgt zwei Spuren. Die erste ist das Fach selbst:
Knappheit, Markt, Geld, Konjunktur, Handel - ohne diese Grundbegriffe
lässt sich keine Wirtschaftsnachricht verstehen. Die zweite Spur ist der
Benutzer: In seinem Whisper-Anker stehen seit Wochen Inflation, Leitzins,
Lieferkette, Bruttoinlandsprodukt und Ungleichheit - das sind die Wörter,
mit denen er dem Orb kommt, und jedes davon führt hier auf ein Thema.

Eine Grenze zieht sich durch das ganze Feld, und sie steht auch im
inneren Antrieb des Orb: Wirtschaft ERKLÄREN ja, zu Geschäften RATEN
nein. Die Themen liefern die Sachkenntnis, aus der jemand selbst
entscheidet - keine Anlageempfehlung und keine Prognose, die als
Gewissheit auftritt. Gerade das Prognose-Thema sagt ausdrücklich, warum.
"""

from __future__ import annotations

from backend.studium.landkarte import Anlass, Feld, Gebiet, Thema


def _f(frage: str, tiefe: str, *woran: str) -> Anlass:
    return Anlass(frage=frage, tiefe=tiefe, woran_man_es_merkt=tuple(woran))


_GRUNDBEGRIFFE = Gebiet(
    kennung="wir-grund",
    titel="Die Grundbegriffe",
    beschreibung="Knappheit, Markt und Preis - das Handwerkszeug.",
    themen=(
        Thema(
            kennung="wir-was-ist-das",
            titel="Was Ökonomie ist und was sie nicht ist",
            abriss=(
                "Ökonomie ist die Wissenschaft vom Umgang mit Knappheit: "
                "Bedürfnisse sind unbegrenzt, Mittel nicht, also muss "
                "gewählt werden - und jede Wahl hat einen Preis, nämlich "
                "das Beste, worauf man verzichtet. Diese Opportunitätskosten "
                "sind der Grundbegriff des Fachs, und sie stehen nirgends "
                "auf einer Rechnung. Ökonomie ist dabei keine Lehre vom "
                "Geldverdienen und keine Börsenkunde: Sie untersucht, wie "
                "Menschen, Unternehmen und Staaten unter Knappheit "
                "entscheiden - mit Modellen, die absichtlich vereinfachen. "
                "Ein Modell ist eine Landkarte, kein Foto: Es lässt weg, "
                "um etwas zu zeigen, und die Kunst besteht darin zu wissen, "
                "wann die Karte nicht mehr passt."
            ),
            worum_es_geht=(
                "Knappheit und Opportunitätskosten an eigenen Beispielen "
                "erklären",
                "Modell und Wirklichkeit methodisch auseinanderhalten",
                "Mikro- und Makroökonomie unterscheiden",
            ),
            fuehrt_zu=("wir-markt", "wir-bip"),
            begriffe=(
                "Knappheit", "Opportunitätskosten", "Modell",
                "Mikroökonomie", "Makroökonomie", "homo oeconomicus",
                "Anreiz", "Effizienz",
            ),
            literatur=(
                "N. Gregory Mankiw / Mark P. Taylor: Grundzüge der "
                "Volkswirtschaftslehre",
                "Adam Smith: Der Wohlstand der Nationen (1776)",
            ),
            anlaesse=(
                _f("Was sind Opportunitätskosten - und warum stehen sie auf "
                   "keiner Rechnung?", "kennen",
                   "der Wert der besten nicht gewählten Alternative",
                   "Verzicht statt Ausgabe",
                   "Beispiel: das Studium kostet vor allem entgangenen Lohn"),
                _f("Ein Konzert mit Freikarte oder ein Abend Arbeit für 200 "
                   "Franken: Was kostet dich das Konzert wirklich?",
                   "anwenden",
                   "die Freikarte macht es nicht kostenlos",
                   "entgangene 200 Franken als Opportunitätskosten",
                   "die Entscheidung hängt am Wert des Konzerts für DICH"),
                _f("Der homo oeconomicus entscheidet stets rational und "
                   "eigennützig - offensichtlich falsch als Menschenbild. "
                   "Warum rechnen Ökonomen trotzdem damit, und wann wird es "
                   "gefährlich?", "beurteilen",
                   "Modellannahme, kein Menschenbild",
                   "brauchbar, wo Anreize dominieren; blind für Fairness",
                   "die Verhaltensökonomik als systematische Korrektur"),
            ),
        ),
        Thema(
            kennung="wir-markt",
            titel="Angebot, Nachfrage und der Preis",
            abriss=(
                "Der Preis ist keine Zahl, die jemand festlegt, sondern ein "
                "Signal, das Wissen transportiert: Steigt er, lohnt sich "
                "das Anbieten und das Sparen zugleich - Millionen Menschen "
                "reagieren auf eine Knappheit, von der die meisten nie "
                "gehört haben. Das Marktdiagramm mit fallender Nachfrage- "
                "und steigender Angebotskurve ist das berühmteste Modell "
                "des Fachs, und seine eigentliche Pointe ist das "
                "Gleichgewicht: Dort räumt der Markt. Eingriffe wie "
                "Preisdeckel und Mindestpreise verschieben nicht die Kurven, "
                "sondern verbieten das Gleichgewicht - mit vorhersagbaren "
                "Nebenwirkungen. Und ebenso wichtig ist die Rückseite: Bei "
                "externen Effekten, Monopolen und öffentlichen Gütern lügt "
                "der Preis, und dann versagt der Markt."
            ),
            worum_es_geht=(
                "das Marktdiagramm zeichnen und Verschiebungen durchspielen",
                "Preisbildung als Informationsverarbeitung erklären",
                "Marktversagen an den klassischen Fällen erkennen",
            ),
            baut_auf=("wir-was-ist-das",),
            fuehrt_zu=("wir-geld", "wir-handel", "wir-ungleichheit"),
            begriffe=(
                "Angebot", "Nachfrage", "Gleichgewichtspreis", "Elastizität",
                "Preisdeckel", "Marktversagen", "externer Effekt", "Monopol",
                "öffentliches Gut", "unsichtbare Hand",
            ),
            literatur=(
                "Alfred Marshall: Principles of Economics (1890)",
                "Friedrich A. von Hayek: Die Verwertung des Wissens in der "
                "Gesellschaft (1945)",
            ),
            zeigenswert=(
                "das Marktdiagramm mit Gleichgewicht",
                "dasselbe Diagramm mit Preisdeckel und der entstehenden "
                "Lücke",
            ),
            anlaesse=(
                _f("Warum fällt die Nachfragekurve und steigt die "
                   "Angebotskurve?", "kennen",
                   "teurer heisst: weniger Käufer, mehr Anbieter",
                   "das Gleichgewicht als Schnittpunkt",
                   "der Preis räumt den Markt"),
                _f("Eine Stadt deckelt die Mieten. Spiele im Diagramm durch, "
                   "was kurzfristig und was langfristig geschieht.",
                   "anwenden",
                   "Nachfrageüberhang: mehr Suchende als Wohnungen",
                   "langfristig: weniger Neubau, Umgehung, Schwarzmarkt",
                   "wem es nützt und wem es schadet - differenzieren"),
                _f("Hayek nennt den Preis ein Wunder der Wissensverwertung, "
                   "Kritiker halten dagegen, dass er bei Klima und Wohnen "
                   "systematisch versagt. Wie passt beides zusammen?",
                   "beurteilen",
                   "Preissignal funktioniert nur bei wahren Kosten",
                   "externe Effekte: die Kosten tragen Unbeteiligte",
                   "Korrektur durch Bepreisung statt Abschaffung des Preises"),
            ),
        ),
    ),
)

_MAKRO = Gebiet(
    kennung="wir-makro",
    titel="Die grossen Grössen",
    beschreibung=(
        "BIP, Geld, Inflation, Konjunktur - die Makroökonomie und ihre "
        "Steuerung."
    ),
    themen=(
        Thema(
            kennung="wir-bip",
            titel="Das Bruttoinlandsprodukt und seine Grenzen",
            abriss=(
                "Das BIP misst den Wert aller im Inland erzeugten Güter und "
                "Dienstleistungen eines Jahres - die eine Zahl, an der "
                "Wachstum, Rezession und Wohlstand festgemacht werden. Man "
                "muss sie lesen können: nominal oder real, gesamt oder pro "
                "Kopf, und kaufkraftbereinigt, wenn Länder verglichen "
                "werden. Und man muss wissen, was sie nicht misst: unbezahlte "
                "Arbeit, Verteilung, Umweltverbrauch - ein Erdbeben kann das "
                "BIP erhöhen, weil der Wiederaufbau zählt und die Zerstörung "
                "nicht. Wer das BIP als Wohlstandsmass verwendet, benutzt "
                "ein Thermometer als Waage: nicht falsch gebaut, aber für "
                "eine andere Frage."
            ),
            worum_es_geht=(
                "das BIP in seinen Varianten lesen: nominal, real, pro Kopf",
                "erklären, was das BIP misst und was systematisch nicht",
                "Wachstum als Grösse einordnen, nicht anbeten oder verdammen",
            ),
            baut_auf=("wir-was-ist-das",),
            fuehrt_zu=("wir-konjunktur",),
            begriffe=(
                "Bruttoinlandsprodukt", "nominal", "real", "pro Kopf",
                "Kaufkraftparität", "Wachstum", "Rezession",
                "unbezahlte Arbeit", "Wohlstandsindikator",
            ),
            literatur=(
                "Philipp Lepenies: Die Macht der einen Zahl",
                "Joseph Stiglitz / Amartya Sen / Jean-Paul Fitoussi: "
                "Mismeasuring Our Lives",
            ),
            zeigenswert=(
                "das reale BIP pro Kopf ausgewählter Länder über fünfzig "
                "Jahre",
            ),
            anlaesse=(
                _f("Was ist der Unterschied zwischen nominalem und realem "
                   "BIP - und warum ist er entscheidend?", "kennen",
                   "nominal: in laufenden Preisen, enthält die Inflation",
                   "real: preisbereinigt, misst die Menge",
                   "nominales Wachstum kann reale Schrumpfung verdecken"),
                _f("Land A hat das doppelte BIP von Land B, aber die "
                   "vierfache Bevölkerung. Wo lebt es sich im Schnitt "
                   "besser - und welche Angaben fehlen dir noch?",
                   "anwenden",
                   "pro Kopf rechnen: B liegt vorn",
                   "Kaufkraft und Preisniveau einbeziehen",
                   "Verteilung: der Schnitt sagt nichts über den Median"),
                _f("Ein Erdbeben kann das BIP steigern. Ist das ein Fehler "
                   "der Statistik oder ein Fehler ihrer Benutzer?",
                   "beurteilen",
                   "das BIP misst Ströme, nicht Bestände",
                   "zerstörtes Vermögen taucht nirgends auf",
                   "die Zahl tut, was sie soll - die Deutung überdehnt sie"),
            ),
        ),
        Thema(
            kennung="wir-geld",
            titel="Geld und Inflation",
            abriss=(
                "Geld ist eine geteilte Übereinkunft: Es taugt als "
                "Tauschmittel, Recheneinheit und Wertspeicher genau so "
                "lange, wie alle darauf vertrauen. Inflation ist der "
                "Vertrauensverschleiss in Zahlen - ein anhaltender Anstieg "
                "des Preisniveaus, gemessen am Warenkorb des "
                "Konsumentenpreisindex. Ihre Kosten sind ungleich verteilt: "
                "Sie entwertet Ersparnisse und Löhne, entlastet Schuldner "
                "und trifft am härtesten, wer sein Einkommen nicht anpassen "
                "kann. Die Hyperinflation von 1923, in der ein Brot "
                "Milliarden kostete, ist der deutsche Erinnerungsort dafür - "
                "und erklärt bis heute, warum die Geldpolitik hierzulande "
                "strenger diskutiert wird als anderswo."
            ),
            worum_es_geht=(
                "die drei Geldfunktionen und ihren Zusammenhang erklären",
                "Inflation messen: Warenkorb, Index, Kerninflation",
                "Gewinner und Verlierer der Inflation benennen",
            ),
            baut_auf=("wir-markt",),
            fuehrt_zu=("wir-zins",),
            begriffe=(
                "Tauschmittel", "Recheneinheit", "Wertspeicher", "Inflation",
                "Konsumentenpreisindex", "Warenkorb", "Kerninflation",
                "Deflation", "Hyperinflation", "Geldmenge", "Realzins",
            ),
            literatur=(
                "Milton Friedman: Die optimale Geldmenge",
                "Adam Fergusson: Das Ende des Geldes (über 1923)",
            ),
            zeigenswert=(
                "eine Banknote über hundert Billionen Mark von 1923",
                "die Inflationsrate der letzten Jahrzehnte als Kurve",
            ),
            anlaesse=(
                _f("Welche drei Funktionen erfüllt Geld, und welche leidet "
                   "bei Inflation zuerst?", "kennen",
                   "Tauschmittel, Recheneinheit, Wertspeicher",
                   "der Wertspeicher bricht zuerst",
                   "bei Hyperinflation flieht alles in Sachwerte"),
                _f("Dein Lohn steigt um zwei Prozent, die Inflation beträgt "
                   "drei. Bist du reicher geworden? Rechne real.",
                   "anwenden",
                   "Realwert: nominal minus Inflation",
                   "ein Prozent weniger Kaufkraft trotz Lohnerhöhung",
                   "Geldillusion als verbreiteter Denkfehler"),
                _f("Moderate Inflation gilt als schmierendes Öl, Deflation "
                   "als gefährlicher. Warum fürchten Notenbanken fallende "
                   "Preise mehr als steigende?", "beurteilen",
                   "Kaufzurückhaltung: warten wird rational",
                   "reale Schuldenlast steigt bei Deflation",
                   "Japans verlorene Jahrzehnte als Anschauung"),
            ),
        ),
        Thema(
            kennung="wir-zins",
            titel="Zentralbanken und der Leitzins",
            abriss=(
                "Der Leitzins ist der Preis, zu dem sich Banken bei der "
                "Zentralbank Geld beschaffen - und der Hebel, mit dem die "
                "Notenbank die ganze Volkswirtschaft berührt. Hebt sie ihn "
                "an, werden Kredite teurer, Investitionen und Konsum kühlen "
                "ab, die Inflation sinkt - um den Preis schwächerer "
                "Konjunktur. Senkt sie ihn, gilt das Umgekehrte. Die Wirkung "
                "kommt mit Verzögerung von Monaten bis Jahren, weshalb "
                "Geldpolitik Steuern auf Sicht durch Nebel ist. "
                "Zentralbanken wie SNB, EZB und Fed sind bewusst unabhängig "
                "von der Politik: Eine Regierung vor der Wahl will billiges "
                "Geld, und die Rechnung dafür kommt nach der Wahl - genau "
                "diese Versuchung soll die Unabhängigkeit ausschalten."
            ),
            worum_es_geht=(
                "den Wirkungsweg vom Leitzins bis zu Preisen und "
                "Beschäftigung nachzeichnen",
                "erklären, warum Zentralbanken unabhängig sind",
                "die Grenzen der Geldpolitik an der Nullzinsgrenze kennen",
            ),
            baut_auf=("wir-geld",),
            fuehrt_zu=("wir-konjunktur",),
            begriffe=(
                "Leitzins", "Zentralbank", "SNB", "EZB", "Fed",
                "Transmissionsmechanismus", "Preisstabilität",
                "Unabhängigkeit", "Nullzinsgrenze", "quantitative Lockerung",
            ),
            literatur=(
                "Mervyn King: The End of Alchemy",
                "die geldpolitischen Lagebeurteilungen der Schweizerischen "
                "Nationalbank (laufend)",
            ),
            zeigenswert=(
                "der Leitzins von SNB, EZB und Fed über zwanzig Jahre als "
                "Kurve",
            ),
            anlaesse=(
                _f("Über welche Stationen wirkt eine Leitzinserhöhung auf "
                   "die Inflation?", "kennen",
                   "Kreditzinsen steigen, Nachfrage sinkt",
                   "weniger Nachfrage bremst die Preise",
                   "Wechselkurs als zweiter Kanal"),
                _f("Die Inflation liegt über dem Ziel, die Wirtschaft "
                   "schwächelt bereits. Du sitzt im Zinsentscheid: Welche "
                   "Abwägung triffst du, und welche Daten willst du sehen?",
                   "anwenden",
                   "Zielkonflikt Preisstabilität gegen Konjunktur",
                   "Kerninflation, Lohnentwicklung, Erwartungen",
                   "die Verzögerung: heute wirkt erst übernächstes Jahr"),
                _f("Unabhängige Zentralbanken treffen folgenreiche "
                   "Entscheidungen ohne Wahl und Abwahl. Ist das ein "
                   "Demokratieproblem - und was wäre die Alternative?",
                   "beurteilen",
                   "Zeitinkonsistenz als Grund der Unabhängigkeit",
                   "Mandat durch Gesetz als demokratische Rückbindung",
                   "die Erfahrung politisch gelenkter Notenbanken"),
            ),
        ),
        Thema(
            kennung="wir-konjunktur",
            titel="Konjunktur, Krisen und Prognosen",
            abriss=(
                "Marktwirtschaften wachsen nicht gleichmässig, sondern in "
                "Wellen: Aufschwung, Boom, Abschwung, Rezession. Keynes' "
                "bleibende Einsicht ist, dass sich ein Abschwung selbst "
                "verstärken kann - wer Entlassungen fürchtet, spart, und "
                "das Sparen aller erzeugt genau die Entlassungen, die jeder "
                "einzelne vermeiden wollte. Deshalb stützt der Staat in der "
                "Krise die Nachfrage. Die Kehrseite des Fachs ist seine "
                "Prognoseschwäche: Die Finanzkrise 2008 haben fast alle "
                "Modelle verfehlt, und das liegt nicht an Faulheit, sondern "
                "am Gegenstand - Wirtschaft besteht aus Menschen, die auf "
                "Prognosen reagieren und sie damit verändern. Wer dir "
                "sichere Wirtschaftsprognosen verkauft, verkauft etwas "
                "anderes als Wissenschaft."
            ),
            worum_es_geht=(
                "den Konjunkturzyklus mit seinen Phasen beschreiben",
                "das Paradox des Sparens und die Nachfragepolitik erklären",
                "begründen, warum Wirtschaftsprognosen prinzipiell unsicher "
                "sind",
            ),
            baut_auf=("wir-bip", "wir-zins"),
            fuehrt_zu=("wir-verhalten",),
            begriffe=(
                "Keynes", "Konjunkturzyklus", "Rezession", "Paradox des Sparens",
                "Fiskalpolitik", "automatische Stabilisatoren",
                "Finanzkrise 2008", "Reflexivität", "Frühindikator",
            ),
            literatur=(
                "John Maynard Keynes: Allgemeine Theorie der Beschäftigung, "
                "des Zinses und des Geldes (1936)",
                "Carmen Reinhart / Kenneth Rogoff: Dieses Mal ist alles "
                "anders",
            ),
            zeigenswert=(
                "der Konjunkturzyklus als Schema",
                "das BIP um die Krise von 2008 als Kurve",
            ),
            anlaesse=(
                _f("Was besagt das Paradox des Sparens?", "kennen",
                   "einzeln vernünftig, gemeinsam schädlich",
                   "Nachfrageausfall verstärkt den Abschwung",
                   "der Trugschluss der Verallgemeinerung"),
                _f("In der Rezession brechen die Steuereinnahmen ein. Soll "
                   "der Staat sparen, um den Haushalt zu retten? Spiele "
                   "beide Wege durch.", "anwenden",
                   "Sparen verschärft den Einbruch - Prozyklik",
                   "Stützen kostet Schulden, stabilisiert die Nachfrage",
                   "automatische Stabilisatoren wirken lassen"),
                _f("Warum hat kaum ein Modell 2008 kommen sehen - und was "
                   "folgt daraus für den Umgang mit der nächsten Prognose?",
                   "beurteilen",
                   "Modelle ohne Finanzsektor und ohne Panik",
                   "Reflexivität: Prognosen verändern das Prognostizierte",
                   "Bandbreiten und Szenarien statt Punktprognosen"),
            ),
        ),
    ),
)

_WELT = Gebiet(
    kennung="wir-welt",
    titel="Wirtschaft und Gesellschaft",
    beschreibung="Handel, Verteilung und die Grenzen des Rationalen.",
    themen=(
        Thema(
            kennung="wir-handel",
            titel="Aussenhandel und Lieferketten",
            abriss=(
                "Ricardos Einsicht von 1817 ist bis heute das "
                "kontraintuitivste Ergebnis des Fachs: Handel lohnt sich "
                "selbst dann, wenn ein Land ALLES besser kann als das "
                "andere - entscheidend sind nicht die absoluten, sondern "
                "die komparativen Vorteile, denn jede Stunde, die der "
                "Bessere mit dem Zweitbesten verbringt, fehlt ihm beim "
                "Besten. Die Globalisierung hat daraus Lieferketten "
                "gemacht, in denen ein Produkt durch Dutzende Länder "
                "wandert - effizient, aber verwundbar, wie die Pandemie und "
                "die Blockade des Suezkanals gezeigt haben. Seither ringt "
                "die Politik um das Verhältnis von Effizienz und "
                "Widerstandskraft, und Zölle sind zurück im Werkzeugkasten - "
                "samt ihrer alten Nebenwirkungen."
            ),
            worum_es_geht=(
                "den komparativen Vorteil an einem Zahlenbeispiel vorrechnen",
                "Nutzen und Verwundbarkeit globaler Lieferketten abwägen",
                "die Wirkung von Zöllen auf beide Seiten durchspielen",
            ),
            baut_auf=("wir-markt",),
            fuehrt_zu=("wir-ungleichheit",),
            begriffe=(
                "Ricardo", "komparativer Vorteil", "absoluter Vorteil", "Freihandel",
                "Zoll", "Lieferkette", "Globalisierung", "Offshoring",
                "Resilienz", "Handelsbilanz",
            ),
            literatur=(
                "David Ricardo: Über die Grundsätze der politischen "
                "Ökonomie und der Besteuerung (1817)",
                "Richard Baldwin: The Great Convergence",
            ),
            zeigenswert=(
                "der Weg eines Smartphones durch die Weltkarte seiner "
                "Zulieferer",
            ),
            anlaesse=(
                _f("Was unterscheidet den komparativen vom absoluten "
                   "Vorteil?", "kennen",
                   "absolut: wer etwas billiger kann",
                   "komparativ: wessen Verzicht kleiner ist",
                   "Handel lohnt auch für den, der alles besser kann"),
                _f("Eine Anwältin tippt schneller als ihre Sekretärin. Soll "
                   "sie selbst tippen? Rechne mit Opportunitätskosten.",
                   "anwenden",
                   "ihre Stunde bringt als Anwältin ein Vielfaches",
                   "Spezialisierung nach komparativem Vorteil",
                   "dasselbe Argument im Länder-Massstab"),
                _f("'Handel nützt allen' - und doch verlieren ganze "
                   "Regionen durch Verlagerung. Widerlegt das Ricardo, oder "
                   "sagt sein Modell etwas anderes, als man ihm nachsagt?",
                   "beurteilen",
                   "Gesamtgewinn heisst nicht Gewinn für jeden",
                   "das Modell schweigt über die Verteilung",
                   "der China-Schock als empirisches Lehrstück"),
            ),
        ),
        Thema(
            kennung="wir-ungleichheit",
            titel="Ungleichheit",
            abriss=(
                "Wie ungleich Einkommen und Vermögen verteilt sind, ist "
                "messbar - die Lorenzkurve zeigt es als Bild, der Gini-"
                "Koeffizient fasst es in eine Zahl zwischen null und eins. "
                "Ob eine gemessene Ungleichheit GERECHT ist, ist dagegen "
                "keine Messfrage: Sie hängt daran, ob sie aus Leistung oder "
                "aus Herkunft stammt, ob sie Anreize schafft oder Chancen "
                "verbaut. Piketty hat die Debatte mit einer historischen "
                "These neu entfacht: Wo die Kapitalrendite dauerhaft über "
                "dem Wachstum liegt, konzentriert sich Vermögen von selbst. "
                "Sauber diskutieren heisst hier dreierlei auseinanderhalten: "
                "was gemessen ist, was erklärt ist und was gefordert wird."
            ),
            worum_es_geht=(
                "Lorenzkurve und Gini-Koeffizient lesen",
                "Einkommens- von Vermögensungleichheit unterscheiden",
                "Mess-, Erklärungs- und Gerechtigkeitsfrage trennen",
            ),
            baut_auf=("wir-markt", "wir-handel"),
            begriffe=(
                "Piketty", "Lorenzkurve", "Gini-Koeffizient",
                "Einkommensungleichheit",
                "Vermögensungleichheit", "Umverteilung", "Chancengleichheit",
                "soziale Mobilität", "Kapitalrendite", "Progression",
            ),
            literatur=(
                "Thomas Piketty: Das Kapital im 21. Jahrhundert",
                "Anthony B. Atkinson: Ungleichheit. Was wir dagegen tun "
                "können",
                "John Rawls: Eine Theorie der Gerechtigkeit (als Brücke zur "
                "Philosophie)",
            ),
            zeigenswert=(
                "die Lorenzkurve mit eingezeichnetem Gini-Koeffizienten",
                "Einkommens- gegen Vermögensverteilung im selben Diagramm",
            ),
            anlaesse=(
                _f("Was zeigt die Lorenzkurve, und was bedeutet ein Gini "
                   "von null und von eins?", "kennen",
                   "kumulierte Anteile gegen die Gleichverteilungsgerade",
                   "null: alle gleich, eins: einer hat alles",
                   "eine Zahl verdichtet, die Kurve zeigt wo"),
                _f("Die Vermögen sind fast überall ungleicher verteilt als "
                   "die Einkommen. Erkläre, warum das systematisch so ist.",
                   "anwenden",
                   "Vermögen speichert Einkommensüberschüsse über Zeit",
                   "Erbschaft und Rendite wirken kumulativ",
                   "Sparfähigkeit wächst mit dem Einkommen"),
                _f("Piketty folgert aus r > g eine eingebaute Tendenz zur "
                   "Konzentration. Was setzen ihm Kritiker entgegen, und "
                   "woran liesse sich der Streit entscheiden?", "beurteilen",
                   "Datenkritik und die Rolle von Humankapital",
                   "Kriege und Politik als historische Gegenkräfte",
                   "Messfrage und Gerechtigkeitsfrage nicht vermengen"),
            ),
        ),
        Thema(
            kennung="wir-verhalten",
            titel="Verhaltensökonomik",
            abriss=(
                "Menschen entscheiden nicht wie der homo oeconomicus, und "
                "zwar nicht zufällig falsch, sondern systematisch: Verluste "
                "schmerzen etwa doppelt so stark, wie gleich grosse Gewinne "
                "freuen; die erstgenannte Zahl verankert jede Verhandlung; "
                "was leicht erinnerbar ist, erscheint wahrscheinlich. "
                "Kahneman und Tversky haben diese Verzerrungen in "
                "Experimenten kartiert und der Ökonomie damit ein neues "
                "Fundament eingezogen - Kahneman erhielt 2002 als Psychologe "
                "den Wirtschaftsnobelpreis. Praktisch folgt daraus das "
                "Nudging: Wer die Voreinstellung setzt, lenkt die Wahl, ohne "
                "sie zu verbieten. Und wer die Verzerrungen kennt, erkennt "
                "sie zuerst bei sich selbst - das ist der eigentliche "
                "Nutzen."
            ),
            worum_es_geht=(
                "die wichtigsten Verzerrungen an Beispielen erkennen",
                "Verlustaversion von Risikoscheu unterscheiden",
                "Nudging beschreiben und seine Legitimität abwägen",
            ),
            baut_auf=("wir-konjunktur",),
            begriffe=(
                "Kahneman", "Verlustaversion", "Ankereffekt",
                "Verfügbarkeitsheuristik",
                "Framing", "Status-quo-Verzerrung", "Prospect Theory",
                "Nudge", "Voreinstellung", "System 1 und System 2",
            ),
            literatur=(
                "Daniel Kahneman: Schnelles Denken, langsames Denken",
                "Richard Thaler / Cass Sunstein: Nudge",
            ),
            anlaesse=(
                _f("Was besagt die Verlustaversion, und wie wurde sie "
                   "gemessen?", "kennen",
                   "Verluste wiegen rund doppelt so schwer wie Gewinne",
                   "Experimente mit Lotterien und Besitz",
                   "der Besitztumseffekt als Folge"),
                _f("Ein Händler schreibt 'nur noch 3 Stück' und streicht "
                   "einen Mondpreis durch. Welche Verzerrungen bespielt er? "
                   "Und woran merkst du es bei dir selbst?", "anwenden",
                   "Knappheit und Verlustangst",
                   "der durchgestrichene Preis als Anker",
                   "Gegenmittel: Zahlungsbereitschaft vorher festlegen"),
                _f("Beim Nudging entscheidet der Staat, was die 'bessere' "
                   "Wahl ist, und macht sie zur Voreinstellung. Sanfter "
                   "Paternalismus oder Bevormundung - und wo verläuft die "
                   "Grenze?", "beurteilen",
                   "Wahlfreiheit bleibt formal erhalten",
                   "irgendeine Voreinstellung gibt es immer",
                   "Transparenz als Kriterium der Legitimität"),
            ),
        ),
    ),
)


WIRTSCHAFT = Feld(
    kennung="wirtschaft",
    titel="Wirtschaftswissenschaft",
    gegenstand=(
        "Wie Menschen, Unternehmen und Staaten unter Knappheit entscheiden - "
        "vom einzelnen Markt bis zu Geld, Konjunktur und Welthandel."
    ),
    methode=(
        "Modelle bauen, die absichtlich vereinfachen, und sie an Daten "
        "prüfen. Ein Modell ist eine Landkarte, kein Foto - die Kunst ist zu "
        "wissen, wann es nicht mehr passt. Und stets in Anreizen und "
        "Opportunitätskosten denken: Nicht was gesagt wird, sondern was sich "
        "lohnt, erklärt das Verhalten."
    ),
    aufgaben=(
        "Wirtschaftsnachrichten verständlich machen: was Inflation, Leitzins "
        "und BIP bedeuten und was nicht",
        "die Folgen von Eingriffen durchspielen, Nebenwirkungen inbegriffen",
        "Knappheitsentscheidungen strukturieren - im Staat wie im Alltag",
        "Verteilungsfragen versachlichen: messen, erklären und fordern "
        "auseinanderhalten",
        "gegen Zahlenzauber wappnen: was eine Statistik zeigt und was ihre "
        "Deutung ihr unterschiebt",
    ),
    nachbarn=(
        "Betriebswirtschaft – führt das einzelne Unternehmen; die "
        "Volkswirtschaft fragt nach dem Ganzen",
        "Politikwissenschaft – untersucht, wie kollektiv entschieden wird; "
        "die Ökonomie, was die Entscheidungen kosten",
        "Psychologie – liefert der Verhaltensökonomik das Fundament",
        "Anlageberatung – verkauft Empfehlungen; die Wissenschaft liefert "
        "die Kenntnis, aus der man selbst entscheidet",
    ),
    einstiege=("wir-was-ist-das",),
    gebiete=(_GRUNDBEGRIFFE, _MAKRO, _WELT),
)
