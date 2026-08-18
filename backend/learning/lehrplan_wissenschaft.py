"""Der grosse Lehrplan: Personen und Gebiete des Denkens.

Der Benutzer hat am 18.08.2026 verlangt, der Orb solle das Wissen von
Sokrates, Platon, Aristoteles, Cicero, Marc Aurel, Picasso, Leonardo da
Vinci und Yuval Noah Harari erwerben - und dazu von allen weiteren
Personen, die Philosophie, Mathematik, Geschichtswissenschaft,
Quantenphysik, Physik, Chemie, Biologie, Religionen und Sprachwissenschaft
geprägt haben. Er soll es anwenden, erklären und lehren können.

## Was hier ehrlich möglich ist - und was nicht

„Alles, was sie jemals geschrieben und gedacht haben" ist als Datenbestand
nicht erreichbar; allein Aristoteles' erhaltenes Werk füllt Regalmeter, und
das meiste davon steht nicht frei im Netz. Was erreichbar ist - und was
einen Lehrenden ausmacht - ist etwas anderes: **die tragenden Thesen, ihre
Begründung, die Einwände dagegen und das, was heute davon gilt.** Wer das
zu einer Person sicher hat, kann über sie unterrichten. Wer nur ihre
Werkliste hat, kann sie aufsagen.

Deshalb bekommt jede Person vier Fragen nach demselben Schnitt: Was ist
der Kern? Worin steht er? Was wurde dagegen vorgebracht? Was gilt heute
noch? Diese vier tragen einen Vortrag - und sie führen zu Texten, in denen
jemand etwas behauptet und begründet, statt zu Lexikoneinleitungen.

## Warum so viele Personen, und warum diese

Der Auftrag lautete ausdrücklich: alle Geschlechter, alle genannten
Gebiete, auch die, die heute noch beitragen. Die Liste ist deshalb breit
angelegt und enthält neben den Namen, die in jedem Kanon stehen, auch
solche, die dort lange fehlten - Hypatia, Emmy Noether, Lise Meitner,
Rosalind Franklin, Barbara McClintock, Chien-Shiung Wu, Maryam
Mirzakhani, Hilma af Klint, Natalie Zemon Davis. Nicht als Zugabe: Ohne
Noether kein Erhaltungssatz-Verständnis, ohne Franklin keine Doppelhelix,
ohne Wu kein Sturz der Paritätserhaltung.

## Wie lange das dauert

Der Orb arbeitet je Durchgang GENAU EINE Frage ab (der Grund dafür steht
in ``lehrplan.py``: Eine Recherche, die sich selbst weitertreibt, ergibt
über Nacht dreihundert Aussagen, die niemand mehr durchsieht). Bei rund
fünfhundert Fragen und einem Takt von sieben Minuten sind das etwa sechzig
Stunden Arbeit im Leerlauf - also gut zwei bis drei Tage, wenn der Rechner
läuft. Das ist keine Schwäche des Aufbaus, sondern der ehrliche Preis
dafür, dass jede Aussage belegt ist.
"""

from __future__ import annotations

#: Die vier Fragen, die jede Person bekommt.
#:
#: Sie sind der Unterschied zwischen "kennt den Namen" und "kann darüber
#: unterrichten". Bewusst auf Kern, Beleg, Einwand und Geltung gerichtet -
#: wer diese vier zu einer Person beantworten kann, trägt eine Vorlesung.
_PERSONENFRAGEN: tuple[str, ...] = (
    "Welche zentrale These oder Entdeckung verbindet die Forschung mit "
    "{name}, und worin genau besteht ihr Gehalt?",
    "Welche Werke oder Arbeiten von {name} gelten als grundlegend, und "
    "was steht in ihnen?",
    "Welche Einwände wurden gegen {name} erhoben, und wie hat die "
    "Forschung darauf geantwortet?",
    "Was von {name} gilt heute noch, was gilt als überholt, und aus "
    "welchen Gründen?",
)

#: Die Personen, nach Gebiet geordnet. Die Reihenfolge ist die
#: Bearbeitungsreihenfolge: Die ausdrücklich genannten zuerst.
PERSONEN: dict[str, tuple[str, ...]] = {
    "Philosophie der Antike": (
        "Sokrates", "Platon", "Aristoteles", "Cicero", "Marc Aurel",
        "Heraklit", "Parmenides", "Demokrit", "Epikur", "Zenon von Kition",
        "Seneca", "Epiktet", "Diogenes von Sinope", "Pyrrhon von Elis",
        "Plotin", "Hypatia von Alexandria", "Aspasia von Milet",
    ),
    "Philosophie des Mittelalters und der islamischen Welt": (
        "Augustinus von Hippo", "Boethius", "Anselm von Canterbury",
        "Ibn Sina (Avicenna)", "Ibn Ruschd (Averroes)", "al-Farabi",
        "al-Ghazali", "Moses Maimonides", "Thomas von Aquin",
        "Wilhelm von Ockham", "Hildegard von Bingen",
        "Christine de Pizan", "Nikolaus von Kues",
    ),
    "Philosophie der Neuzeit": (
        "René Descartes", "Baruch de Spinoza", "Gottfried Wilhelm Leibniz",
        "Thomas Hobbes", "John Locke", "George Berkeley", "David Hume",
        "Jean-Jacques Rousseau", "Immanuel Kant", "Mary Wollstonecraft",
        "Johann Gottlieb Fichte", "Georg Wilhelm Friedrich Hegel",
        "Arthur Schopenhauer", "Søren Kierkegaard", "Karl Marx",
        "John Stuart Mill", "Harriet Taylor Mill", "Friedrich Nietzsche",
    ),
    "Philosophie der Gegenwart": (
        "Edmund Husserl", "Martin Heidegger", "Ludwig Wittgenstein",
        "Bertrand Russell", "Rudolf Carnap", "Karl Popper",
        "Hannah Arendt", "Simone de Beauvoir", "Simone Weil",
        "Jean-Paul Sartre", "Maurice Merleau-Ponty", "Theodor W. Adorno",
        "Max Horkheimer", "Michel Foucault", "Jacques Derrida",
        "Jürgen Habermas", "John Rawls", "Elizabeth Anscombe",
        "Philippa Foot", "Iris Murdoch", "Judith Butler",
        "Martha Nussbaum", "Peter Singer", "Thomas Nagel",
        "Daniel Dennett", "Markus Gabriel",
    ),
    "Mathematik": (
        "Euklid", "Archimedes", "Pythagoras", "Diophant",
        "al-Chwarizmi", "Leonardo Fibonacci", "Pierre de Fermat",
        "Blaise Pascal", "Isaac Newton", "Gottfried Wilhelm Leibniz",
        "Leonhard Euler", "Carl Friedrich Gauß", "Évariste Galois",
        "Bernhard Riemann", "Georg Cantor", "Sofia Kowalewskaja",
        "David Hilbert", "Emmy Noether", "Srinivasa Ramanujan",
        "Kurt Gödel", "Alan Turing", "Ada Lovelace",
        "John von Neumann", "Alexander Grothendieck",
        "Benoît Mandelbrot", "Maryam Mirzakhani", "Andrew Wiles",
    ),
    "Physik": (
        "Galileo Galilei", "Johannes Kepler", "Isaac Newton",
        "Christiaan Huygens", "Michael Faraday", "James Clerk Maxwell",
        "Ludwig Boltzmann", "Émilie du Châtelet", "Hermann von Helmholtz",
        "Albert Einstein", "Marie Curie", "Lise Meitner",
        "Emmy Noether", "Richard Feynman", "Stephen Hawking",
        "Roger Penrose", "Vera Rubin", "Chien-Shiung Wu",
        "Subrahmanyan Chandrasekhar",
    ),
    "Quantenphysik": (
        "Max Planck", "Albert Einstein", "Niels Bohr",
        "Werner Heisenberg", "Erwin Schrödinger", "Paul Dirac",
        "Wolfgang Pauli", "Max Born", "Louis de Broglie",
        "John Stewart Bell", "Hugh Everett III", "David Bohm",
        "Richard Feynman", "Anton Zeilinger", "John Clauser",
        "Alain Aspect", "Maria Goeppert-Mayer",
    ),
    "Chemie": (
        "Antoine Lavoisier", "John Dalton", "Dmitri Mendelejew",
        "Friedrich Wöhler", "August Kekulé", "Marie Curie",
        "Fritz Haber", "Linus Pauling", "Dorothy Crowfoot Hodgkin",
        "Rosalind Franklin", "Ahmed Zewail", "Stephanie Kwolek",
        "Jennifer Doudna", "Emmanuelle Charpentier", "Frances Arnold",
    ),
    "Biologie": (
        "Carl von Linné", "Jean-Baptiste de Lamarck", "Charles Darwin",
        "Alfred Russel Wallace", "Gregor Mendel", "Louis Pasteur",
        "Robert Koch", "Thomas Hunt Morgan", "Barbara McClintock",
        "Rosalind Franklin", "James Watson", "Francis Crick",
        "Lynn Margulis", "Rachel Carson", "Jane Goodall",
        "Richard Dawkins", "Edward O. Wilson", "Christiane Nüsslein-Volhard",
        "Svante Pääbo",
    ),
    "Geschichtswissenschaft": (
        "Yuval Noah Harari", "Herodot", "Thukydides", "Polybios",
        "Tacitus", "Ibn Chaldun", "Leopold von Ranke",
        "Jacob Burckhardt", "Marc Bloch", "Lucien Febvre",
        "Fernand Braudel", "Fritz Fischer", "Eric Hobsbawm",
        "Reinhart Koselleck", "Natalie Zemon Davis", "Carlo Ginzburg",
        "Jürgen Osterhammel", "Christopher Clark", "Mary Beard",
    ),
    "Religionen und Religionswissenschaft": (
        "Siddhartha Gautama (Buddha)", "Konfuzius", "Laozi",
        "Zarathustra", "Moses", "Jesus von Nazaret", "Paulus von Tarsus",
        "Mohammed", "Nagarjuna", "Schankara", "Rumi",
        "Martin Luther", "Johannes Calvin", "Teresa von Ávila",
        "Baruch de Spinoza", "Friedrich Schleiermacher", "Max Weber",
        "Mircea Eliade", "Karen Armstrong",
    ),
    "Sprache und Sprachwissenschaft": (
        "Panini", "Wilhelm von Humboldt", "Jacob Grimm",
        "Ferdinand de Saussure", "Edward Sapir", "Benjamin Lee Whorf",
        "Roman Jakobson", "Noam Chomsky", "Ludwig Wittgenstein",
        "J. L. Austin", "John Searle", "Mary Haas", "Robin Lakoff",
        "Deborah Tannen", "Steven Pinker", "Michael Tomasello",
    ),
    "Kunst und Bildende Wissenschaft": (
        "Leonardo da Vinci", "Pablo Picasso", "Albrecht Dürer",
        "Michelangelo Buonarroti", "Artemisia Gentileschi",
        "Rembrandt van Rijn", "Francisco de Goya", "Hilma af Klint",
        "Wassily Kandinsky", "Marcel Duchamp", "Käthe Kollwitz",
        "Frida Kahlo", "Paul Klee", "Joseph Beuys",
    ),
}

#: Zusätzliche, eigens zugeschnittene Fragen für die ausdrücklich
#: genannten Personen. Sie gehen über das Vierer-Schema hinaus und zielen
#: auf das, wofür man diese Namen wirklich kennt.
BESONDERE_FRAGEN: dict[str, tuple[str, ...]] = {
    "Sokrates": (
        "Was ist die sokratische Methode genau, und wie unterscheidet sie "
        "sich von blossem Nachfragen?",
        "Was bedeutet 'Ich weiss, dass ich nichts weiss' im Zusammenhang "
        "der Apologie, und was bedeutet es NICHT?",
        "Wie verlässlich ist unser Bild des Sokrates, wenn wir es nur aus "
        "Platon, Xenophon und Aristophanes kennen?",
    ),
    "Platon": (
        "Was besagt die Ideenlehre, und welche Probleme wirft sie auf?",
        "Wie ist das Höhlengleichnis aufgebaut, und wofür steht jedes "
        "seiner Elemente?",
        "Welchen Staat entwirft Platon in der Politeia, und warum gilt er "
        "vielen als Warnung statt als Vorbild?",
    ),
    "Aristoteles": (
        "Was sind die vier Ursachen bei Aristoteles, und wozu dienen sie?",
        "Was ist die Nikomachische Ethik in ihrem Kern, und was bedeutet "
        "Eudaimonia wirklich?",
        "Wie funktioniert der Syllogismus, und was leistet er gegenüber "
        "der modernen Logik nicht?",
    ),
    "Cicero": (
        "Welche griechische Philosophie hat Cicero ins Lateinische "
        "übertragen, und welche Begriffe verdanken wir ihm?",
        "Was ist Ciceros Naturrechtsgedanke in 'De re publica' und 'De "
        "legibus', und wie wirkte er bis in moderne Verfassungen?",
    ),
    "Marc Aurel": (
        "Was sind die 'Selbstbetrachtungen', für wen wurden sie "
        "geschrieben, und was folgt daraus für ihre Deutung?",
        "Welche stoischen Grundgedanken vertritt Marc Aurel, und wo "
        "weicht er von Epiktet und Seneca ab?",
    ),
    "Leonardo da Vinci": (
        "Was enthalten Leonardos Notizbücher an naturwissenschaftlichen "
        "Einsichten, und welche waren ihrer Zeit voraus?",
        "Wie verband Leonardo Anatomie, Optik und Malerei "
        "methodisch miteinander?",
    ),
    "Pablo Picasso": (
        "Wie entstand der Kubismus, was war daran der Bruch, und welchen "
        "Anteil hatte Georges Braque?",
        "Was zeigt 'Guernica', mit welchen Mitteln, und wie wurde es zum "
        "politischen Bild schlechthin?",
    ),
    "Yuval Noah Harari": (
        "Was ist Hararis These von den 'gemeinsamen Fiktionen', und worauf "
        "stützt er sie?",
        "Welche fachwissenschaftliche Kritik richtet sich gegen 'Eine "
        "kurze Geschichte der Menschheit', und was ist daran berechtigt?",
    ),
}

#: Die Gebiete selbst - Fragen, die keiner einzelnen Person gehören,
#: sondern dem Fach: seine Methode, seine Streitpunkte, seine Grenzen.
GEBIETE: dict[str, tuple[str, ...]] = {
    "Philosophie": (
        "Wie grenzen sich Metaphysik, Erkenntnistheorie, Ethik und Logik "
        "voneinander ab, und wo überschneiden sie sich?",
        "Was ist der Unterschied zwischen analytischer und "
        "kontinentaler Philosophie, und wie sinnvoll ist diese Trennung?",
        "Was besagt das Leib-Seele-Problem, und welche Lösungsvorschläge "
        "werden heute ernsthaft vertreten?",
        "Was ist der Unterschied zwischen Deontologie, Konsequentialismus "
        "und Tugendethik an einem konkreten Fall?",
        "Was besagt Humes Gesetz (Sein-Sollen-Fehlschluss), und welche "
        "Einwände gibt es dagegen?",
    ),
    "Mathematik": (
        "Was besagen Gödels Unvollständigkeitssätze genau, und was folgt "
        "aus ihnen NICHT?",
        "Worin bestand die Grundlagenkrise der Mathematik, und wie wurde "
        "sie beigelegt?",
        "Was ist der Unterschied zwischen Beweis, Plausibilität und "
        "numerischer Evidenz in der Mathematik?",
        "Warum gilt Cantors Diagonalargument als eines der wichtigsten "
        "Argumente der Mathematik?",
    ),
    "Physik": (
        "Wie verhalten sich klassische Mechanik, Relativitätstheorie und "
        "Quantenmechanik zueinander in ihren Geltungsbereichen?",
        "Was besagt das Noether-Theorem, und warum ist es für das "
        "Verständnis von Erhaltungssätzen zentral?",
        "Warum ist die Vereinigung von Quantenfeldtheorie und allgemeiner "
        "Relativitätstheorie bis heute nicht gelungen?",
        "Was ist Entropie, und warum ist der zweite Hauptsatz so "
        "eigentümlich unter den physikalischen Gesetzen?",
    ),
    "Quantenphysik": (
        "Was besagt die Kopenhagener Deutung, und welche ernsthaften "
        "Alternativen stehen ihr gegenüber?",
        "Was ist Verschränkung, und was folgt aus den Bellschen "
        "Ungleichungen für unser Weltbild?",
        "Was ist das Messproblem der Quantenmechanik, und warum ist es "
        "nicht bloss eine Frage der Interpretation?",
        "Was leistet Dekohärenz als Erklärung, und was leistet sie nicht?",
    ),
    "Chemie": (
        "Wie kam Mendelejew zum Periodensystem, und was sagte er damit "
        "voraus?",
        "Was ist eine chemische Bindung im quantenmechanischen Sinn?",
        "Wie hat das Haber-Bosch-Verfahren die Weltbevölkerung und die "
        "Kriegsführung des 20. Jahrhunderts verändert?",
    ),
    "Biologie": (
        "Was besagt die Synthetische Evolutionstheorie, und wie ist sie "
        "seit den 1940er Jahren erweitert worden?",
        "Was ist der Unterschied zwischen Genotyp, Phänotyp und "
        "Epigenetik, und wo wird Epigenetik überschätzt?",
        "Wie funktioniert CRISPR-Cas9, und welche ethischen Fragen wirft "
        "es auf?",
        "Welchen Anteil hatte Rosalind Franklin an der Aufklärung der "
        "DNA-Struktur, und wie wurde damit umgegangen?",
    ),
    "Religionen und Religionswissenschaft": (
        "Wie unterscheidet die Religionswissenschaft ihre Methode von der "
        "Theologie?",
        "Welche gemeinsamen Strukturen zeigen die abrahamitischen "
        "Religionen, und wo gehen sie grundlegend auseinander?",
        "Was besagt Max Webers These zur protestantischen Ethik, und wie "
        "steht die Forschung heute dazu?",
        "Wie verhalten sich buddhistische und westliche Vorstellungen vom "
        "Selbst zueinander?",
    ),
    "Sprache und Sprachwissenschaft": (
        "Was besagt Chomskys Universalgrammatik, und welche Einwände "
        "haben sich als tragfähig erwiesen?",
        "Was besagt die Sapir-Whorf-Hypothese in ihrer starken und ihrer "
        "schwachen Form, und was ist davon belegt?",
        "Was leistet Saussures Unterscheidung von langue und parole, "
        "Signifikant und Signifikat?",
        "Wie entstehen Sprachfamilien, und wie verlässlich ist die "
        "Rekonstruktion des Indogermanischen?",
    ),
    "Kunst und Ästhetik": (
        "Wie verhalten sich Perspektive, Anatomie und Optik in der "
        "Renaissance zur naturwissenschaftlichen Revolution?",
        "Was war der Bruch der klassischen Moderne, und warum geschah er "
        "gerade um 1900?",
        "Woran bemisst die Kunstwissenschaft die Bedeutung eines Werkes, "
        "wenn nicht am Können?",
    ),
}


def _fragen_zu(name: str) -> tuple[str, ...]:
    """Alle Fragen zu einer Person: das Vierer-Schema plus Besonderes."""

    fragen = [muster.format(name=name) for muster in _PERSONENFRAGEN]
    fragen.extend(BESONDERE_FRAGEN.get(name, ()))
    return tuple(fragen)


def wissenschaftlicher_lehrplan() -> dict[str, tuple[str, ...]]:
    """Baut den vollständigen Lehrplan: je Person und je Gebiet ein Thema.

    Jede Person wird ein eigenes Thema. Das ist Absicht: So lässt sich
    später gezielt fragen ("was weisst du über Emmy Noether"), und die
    Aussagen zu einer Person liegen beieinander statt in einem
    Sammeltopf "Physik", in dem niemand mehr etwas findet.

    Personen, die in mehreren Gebieten vorkommen (Leibniz in Mathematik
    und Philosophie, Marie Curie in Physik und Chemie, Wittgenstein in
    Philosophie und Sprachwissenschaft), bekommen dabei EIN Thema mit
    allen Fragen - nicht zwei halbe.
    """

    plan: dict[str, tuple[str, ...]] = {}

    for personen in PERSONEN.values():
        for name in personen:
            if name not in plan:
                plan[name] = _fragen_zu(name)

    for gebiet, fragen in GEBIETE.items():
        # Ein Gebiet kann denselben Namen tragen wie nichts sonst - aber
        # sicherheitshalber ergaenzen statt ueberschreiben.
        plan[gebiet] = plan.get(gebiet, ()) + fragen

    return plan


def umfang() -> tuple[int, int]:
    """Wie viele Themen und Fragen der Plan umfasst - für die Auskunft."""

    plan = wissenschaftlicher_lehrplan()
    return len(plan), sum(len(fragen) for fragen in plan.values())
