# Angebote (Desktop, portabel)

Eigenständiges Windows-Programm zur Suche in Supermarkt-Angeboten über die Marktguru-API.
Alles Veränderliche liegt im Unterordner `daten\` neben dem Programm:

| Datei | Inhalt |
|---|---|
| `daten\angebote.db` | PLZ, Märkte, Merkliste, bereits gesehene Treffer |
| `daten\angebote.log` | Fehlerprotokoll |
| `daten\benachrichtigt.json` | was die Hintergrundprüfung schon gemeldet hat |
| `daten\webview\` | Zwischenspeicher des Programmfensters |

Ordner kopieren = Programm samt Einstellungen umgezogen. Nichts landet in `%APPDATA%` oder in der Registry
(außer du richtest die optionale Hintergrundprüfung ein, die steht in der Windows-Aufgabenplanung).

## Aus dem Quellcode starten

Voraussetzung: Python 3.10 oder neuer. Das ganze Repo klonen, weil `kern.py` eine Ebene höher liegt.

```
git clone https://github.com/primeschakal-png/angebots-bot.git
cd angebots-bot\desktop
start.bat
```

Beim ersten Start legt `start.bat` die virtuelle Umgebung `.venv` im selben Ordner an.

## Portable .exe bauen

```
build_exe.bat
```

Ergebnis: `dist\Angebote\Angebote.exe`. Den Ordner `dist\Angebote` kannst du hinkopieren, wohin du willst,
z.B. auf einen USB-Stick. `daten\` entsteht beim ersten Start daneben.
Für die Hintergrundprüfung `aufgabe_einrichten.bat` neben die exe legen.

## Bedienung

- Suchbegriff eingeben, Enter. Optional Höchstpreis in Euro.
- Märkte links an- und abklicken, PLZ ändern. Wird sofort gespeichert.
- **Merken** legt Begriff plus Höchstpreis auf die Merkliste.
- Beim Programmstart wird die Merkliste geprüft. Neue Treffer stehen als grüne Zahl am Eintrag.
  Anklicken zeigt sie und hakt sie ab. Eintrag ohne neue Treffer anklicken sucht den Begriff einfach.

## Tägliche Prüfung im Hintergrund (optional)

`aufgabe_einrichten.bat` legt eine Windows-Aufgabe an, die jeden Tag um 07:00 Uhr
`--pruefen` ausführt und neue Treffer als Windows-Benachrichtigung zeigt. Jeder Treffer wird nur
einmal gemeldet. Uhrzeit oben in der .bat änderbar. Entfernen:
`schtasks /Delete /TN "Angebote Merkliste" /F`

## Bekannte Grenzen

- Aldi Nord, Aldi Süd und Edeka liefern bei Marktguru für PLZ 42579 keine Einzelangebote,
  nur Prospekte. Die Chips sind trotzdem da, bringen aber derzeit keine Treffer.
- Die Marktguru-API ist inoffiziell. Fehler stehen in `daten\angebote.log`.
