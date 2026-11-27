---
name: angebote
description: Aktuelle Supermarkt-Angebote (Aldi Nord/Süd, Rewe, Netto, Lidl, Kaufland, Edeka) suchen und Preisalarme verwalten. Benutzen, wenn Torsten nach Angeboten, Prospekten, Sonderangeboten oder Preisen im Supermarkt fragt oder einen Alarm will.
---

# Supermarkt-Angebote

Alle Daten kommen ausschließlich aus dem Skript `cli.py` im Ordner `~/angebots-bot`.
Erfinde nie Preise, Märkte oder Gültigkeitszeiträume. Wenn das Skript nichts findet
oder einen Fehler meldet, sag das genau so.

Aufruf immer so (Terminal-Toolset):

```
cd ~/angebots-bot && .venv/bin/python cli.py <befehl>
```

## Befehle

| Zweck | Befehl |
|---|---|
| Angebote suchen | `suche "Gefrierbeutel" --json` |
| mit Höchstpreis | `suche "Gefrierbeutel" --max 2 --json` |
| nur bestimmte Märkte | `suche "Kaffee" --maerkte "aldi-sued, lidl" --json` |
| Alarm anlegen | `alarm add "Gefrierbeutel" --max 2` |
| Alarme anzeigen | `alarm liste` |
| Alarm löschen | `alarm weg <nr>` |
| Alarme jetzt prüfen (nur Anzeige) | `pruefen` |
| PLZ/Märkte anzeigen | `einstellungen` |

Mögliche Märkte: aldi-nord, aldi-sued, rewe, netto, lidl, kaufland, edeka, alle.

## Regeln

- Bei unscharfen Wünschen ("was zum Einfrieren", "Waschmittel und Spülmittel") mehrere
  konkrete Suchbegriffe nacheinander abfragen und die Ergebnisse zusammenführen.
- Ergebnis knapp auf Deutsch: Markt, Produkt, Preis, Grundpreis, gültig von bis.
  Günstigsten Grundpreis zuerst. Hinweis "nur mit App/Karte" mitnehmen, wenn
  `nur_mit_karte` true ist.
- Alarme nur anlegen oder löschen, wenn Torsten das ausdrücklich sagt.
- Benachrichtigungen verschickt der Discord-Bot selbst jeden Morgen. Du musst dafür
  keinen Cron-Job anlegen.
- Keine anderen Befehle im Ordner ausführen, keine Dateien darin ändern.
