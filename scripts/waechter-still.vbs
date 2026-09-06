' Startet den Neustart-Waechter ohne sichtbares Fenster.
' Gedacht fuer den Autostart: beim Hochfahren soll nicht jedes Mal
' ein schwarzes Fenster aufgehen und im Weg stehen.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ordner = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
shell.CurrentDirectory = ordner
shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ordner & "\scripts\neustart_waechter.ps1""", 0, False
