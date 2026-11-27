@echo off
rem Richtet die taegliche Hintergrundpruefung der Merkliste ein (Windows-Aufgabenplanung).
rem Liegt diese Datei neben Angebote.exe, wird die exe benutzt, sonst der Quellcode.
cd /d "%~dp0"
set ZEIT=07:00
if exist "%~dp0Angebote.exe" (
    set CMD="%~dp0Angebote.exe" --pruefen
) else (
    set CMD="%~dp0.venv\Scripts\pythonw.exe" "%~dp0angebote_app.py" --pruefen
)
schtasks /Create /F /SC DAILY /ST %ZEIT% /TN "Angebote Merkliste" /TR "%CMD%"
if errorlevel 1 ( echo Einrichten fehlgeschlagen. ) else ( echo Taegliche Pruefung um %ZEIT% eingerichtet. Entfernen: schtasks /Delete /TN "Angebote Merkliste" /F )
pause
