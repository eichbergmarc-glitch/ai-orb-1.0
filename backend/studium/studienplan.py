"""ENTFERNT am 20.08.2026 - ersetzt durch ``landkarte.py``.

Hier stand ein Studienplan: Module in Semestern, feste Reihenfolge,
Prüffragen auf drei Stufen. Der Benutzer hat das zurückgewiesen::

    "Ich will nicht ein zeitlich eingeschränktes Studium machen ... Wie
     lange ich für welches Thema benötige ist unerheblich. Also benötigen
     wir keinen Studienplan, dieser ist dynamisch und passt sich dem
     jeweiligen Wissensstand und den jeweiligen Interessen an."

An seine Stelle ist :mod:`backend.studium.landkarte` getreten: dieselben
Inhalte, aber als Landkarte statt als Ordnung. Abhängigkeiten sind dort
eine Auskunft ("dafür brauchst du noch X") und keine Vorschrift.

Diese Datei bleibt leer und tut nichts. Wer sie einbindet, hat einen
veralteten Verweis - und bekommt hier den Grund dafür zu lesen.
"""

raise ImportError(
    "backend.studium.studienplan wurde durch backend.studium.landkarte "
    "ersetzt. Ein Studienplan schreibt eine Reihenfolge vor; die Landkarte "
    "sagt nur, was womit zusammenhängt. Siehe den Kopf dieser Datei."
)
