@echo off
rem Baut eine portable Angebote.exe nach dist\Angebote\ (Ordner komplett kopierbar).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo Erst start.bat einmal ausfuehren. & pause & exit /b 1 )
".venv\Scripts\python.exe" -m pip install -q pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name Angebote --paths .. --add-data "ui.html;." --distpath dist\Angebote angebote_app.py
if errorlevel 1 ( echo Build fehlgeschlagen. & pause & exit /b 1 )
echo.
echo Fertig: dist\Angebote\Angebote.exe
echo Der Ordner dist\Angebote ist portabel. Der Unterordner daten entsteht beim ersten Start.
pause
