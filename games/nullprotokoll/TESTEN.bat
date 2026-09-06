@echo off
setlocal
title NULLPROTOKOLL - Tests
set "NP_PROJECT=%~dp0"
set "NP_PROJECT=%NP_PROJECT:~0,-1%"
set "NP_GODOT=%NP_PROJECT%\.tools\godot\bin\Godot_v4.7.2-stable_win64_console.exe"

pushd "%NP_PROJECT%"
node tests\validate_story.mjs
if errorlevel 1 goto :failed

if exist "%NP_GODOT%" (
  rem Erst einlesen: neue Skripte mit class_name sind sonst der Engine unbekannt.
  "%NP_GODOT%" --headless --path "%NP_PROJECT%" --import >nul 2>nul
  "%NP_GODOT%" --headless --path "%NP_PROJECT%" --scene res://tests/test_runner.tscn
  if errorlevel 1 goto :failed
  "%NP_GODOT%" --headless --path "%NP_PROJECT%" --scene res://tests/point_click_runner.tscn
  if errorlevel 1 goto :failed
  "%NP_GODOT%" --headless --path "%NP_PROJECT%" --scene res://tests/voice_runner.tscn
  if errorlevel 1 goto :failed
) else (
  echo Godot-Integrationstest uebersprungen: portable Engine nicht gefunden.
)

echo.
echo Alle verfuegbaren Tests bestanden.
popd
pause
exit /b 0

:failed
echo.
echo Mindestens ein Test ist fehlgeschlagen.
popd
pause
exit /b 1
