"""Anbindungen an externe Dienste (Gmail, spaeter weitere).

Jede Anbindung liegt in einem eigenen Unterpaket und wird ueber einen
Agenten und Werkzeuge verfuegbar gemacht - nicht durch direkte Aufrufe aus
dem Kern. So bleibt eine ausgefallene Anbindung ein Ausfall dieser einen
Anbindung und reisst nichts anderes mit (Master-Prompt Abschnitt 62).
"""
