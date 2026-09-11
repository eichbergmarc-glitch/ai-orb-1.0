# installer/

Dieser Ordner ist für die spätere Paketierung von AI-Orb als eigenständiges
Windows-Installationsprogramm reserviert (z. B. mittels `electron-builder`
und einem NSIS-Installer, der Python-Runtime, Node-Abhängigkeiten und die
kompilierte Desktop-Anwendung zu einer einzigen `AI-Orb-Setup.exe` bündelt).

In der aktuellen Ausbaustufe (v2 Phase 1 + Phase 2) wird AI-Orb über
`install.ps1` / `install.bat` direkt aus dem Quellordner heraus eingerichtet
(siehe `README.md` im Projekt-Root). Die Erstellung eines eigenständigen
Installers ist für eine spätere Ausbaustufe vorgesehen und wird hier
ergänzt, ohne die bestehende Installationsroutine zu verändern.
