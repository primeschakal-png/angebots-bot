# angebots-bot

Sucht aktuelle Supermarkt-Angebote über marktguru.de und meldet sie per Discord.
Ein Python-Kern, zwei Oberflächen:

- **Discord-Bot** für alle auf dem Server: feste Slash-Commands, kein LLM, keine Shell.
- **CLI** für Hermes (und zum Testen): `cli.py`, dazu der Skill in `hermes-skill/`.

Beide benutzen dieselbe SQLite-Datenbank (`angebote.db`). Der Bot prüft jeden Morgen
alle Alarme und schickt neue Treffer per DM, jedes Angebot nur einmal pro Alarm.

Standard: PLZ 42579, Märkte Aldi Nord, Aldi Süd, Rewe, Netto, Lidl, Kaufland, Edeka.
Jeder Nutzer kann PLZ und Märkte selbst ändern.

## Dateien

| Datei | Zweck |
|---|---|
| `kern.py` | Marktguru-Abfrage, Filter, Sortierung nach Grundpreis, Datenbank, Alarmprüfung |
| `cli.py` | Kommandozeile |
| `discord_bot.py` | Discord-Bot mit täglicher Alarmprüfung |
| `hermes-skill/SKILL.md` | Skill für Hermes, ruft nur `cli.py` auf |
| `systemd/angebots-bot.service` | Dienst für den VPS |
| `.env.example` | Vorlage für die Einstellungen |

## 1. Discord-Bot anlegen

1. https://discord.com/developers/applications → **New Application**, Name z.B. "Angebote".
2. Links **Bot** → **Reset Token** → Token kopieren (kommt in `.env`).
   Privileged Intents brauchst du keine.
3. Links **OAuth2 → URL Generator**: Scopes `bot` und `applications.commands`,
   Bot Permissions `Send Messages` und `Embed Links`. URL öffnen, Bot auf deinen Server holen.
4. In Discord Entwicklermodus an (Einstellungen → Erweitert), dann Rechtsklick auf
   den Server → **Server-ID kopieren** und Rechtsklick auf dich → **User-ID kopieren**.

## 2. Installation auf dem VPS

Läuft unter dem Hermes-User `moltbook`, damit Hermes `cli.py` direkt aufrufen kann.

```bash
sudo -iu moltbook
git clone https://github.com/primeschakal-png/angebots-bot.git
cd angebots-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env        # DISCORD_TOKEN, GUILD_ID, CLI_USER_ID eintragen
```

Erster Test, bevor der Bot läuft:

```bash
.venv/bin/python cli.py suche Gefrierbeutel
.venv/bin/python cli.py haendler Gefrierbeutel
```

`haendler` zeigt, unter welchen Namen Marktguru die Märkte führt. Fehlt ein Markt in den
Treffern, obwohl er dort auftaucht, muss das Präfix in `MAERKTE` in `kern.py` angepasst werden.

## 3. Als Dienst starten

```bash
exit   # zurück zum root/sudo-User
sudo cp /home/moltbook/angebots-bot/systemd/angebots-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now angebots-bot
journalctl -u angebots-bot -f
```

Im Log muss `Befehle für Server … synchronisiert` und `Eingeloggt als …` stehen.

## 4. Hermes-Skill

```bash
sudo -iu moltbook
mkdir -p ~/.hermes/skills/angebote
cp ~/angebots-bot/hermes-skill/SKILL.md ~/.hermes/skills/angebote/
```

Das Terminal-Toolset der Instanz muss aktiv sein. Danach z.B. an Hermes:
"Gibt es gerade irgendwo Gefrierbeutel unter 2 Euro?"

## Discord-Befehle

| Befehl | Was |
|---|---|
| `/angebot begriff [max_preis] [oeffentlich]` | sofort suchen, Top 10 nach Grundpreis |
| `/plz 42579` | eigene PLZ |
| `/maerkte aldi-sued, rewe, lidl` | eigene Märkte, `alle` geht auch |
| `/einstellungen` | PLZ, Märkte, Anzahl Alarme |
| `/alarm add begriff [max_preis]` | Alarm anlegen |
| `/alarm liste` / `/alarm weg nr` | Alarme anzeigen / löschen |
| `/alarm pruefen` | Alarme sofort prüfen, ohne als gemeldet zu markieren |

Antworten sind nur für den Fragenden sichtbar, außer bei `/angebot … oeffentlich:True`.
Für die DMs muss der Nutzer Direktnachrichten von Servermitgliedern zulassen.

## Grenzen

- Die Marktguru-Schnittstelle ist inoffiziell. Ändert Marktguru etwas, kommt
  `Fehler bei Marktguru: …`. Dann die Meldung schicken, der Code muss angepasst werden.
- Marktguru filtert nach PLZ, einen Umkreis gibt es nicht. Welche Filialen zählen,
  entscheidet Marktguru anhand der PLZ.
- Einzelne Aktionsartikel stehen manchmal nur im Prospekt und nicht als Einzelangebot.
- Suchergebnisse werden 30 Minuten zwischengespeichert, damit gleiche Anfragen
  mehrerer Nutzer Marktguru nicht mehrfach abfragen.
