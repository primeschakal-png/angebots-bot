@echo off
rem Startet das Programm aus dem Quellcode. Beim ersten Start wird .venv angelegt.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Erster Start: lege virtuelle Umgebung an ...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 ( echo Python nicht gefunden. & pause & exit /b 1 )
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
    if errorlevel 1 ( echo Installation fehlgeschlagen. & pause & exit /b 1 )
)
start "" ".venv\Scripts\pythonw.exe" angebote_app.py
