"""Kommandozeile für den Angebots-Bot. Wird auch vom Hermes-Skill benutzt.

Beispiele:
  python cli.py suche Gefrierbeutel
  python cli.py suche Gefrierbeutel --max 2 --json
  python cli.py alarm add Gefrierbeutel --max 2
  python cli.py alarm liste
  python cli.py alarm weg 3
  python cli.py pruefen
  python cli.py einstellungen --plz 42579 --maerkte "aldi-nord, aldi-sued, rewe"
  python cli.py haendler Gefrierbeutel
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from kern import (
    MAERKTE,
    Datenbank,
    Marktguru,
    MarktguruFehler,
    angebot_zeile,
    normalisiere_maerkte,
    pruefe_alarme,
)

# Unter dieser ID legt die CLI Alarme an. Trag in .env deine Discord-User-ID ein,
# dann siehst du dieselben Alarme im Discord-Bot und bekommst die DMs.
CLI_USER = os.environ.get("CLI_USER_ID", "cli")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(description="Supermarkt-Angebote über Marktguru")
    p.add_argument("--user", default=CLI_USER, help="Nutzer-ID (Standard: CLI_USER_ID aus .env)")
    sub = p.add_subparsers(dest="befehl", required=True)

    s = sub.add_parser("suche", help="Angebote suchen")
    s.add_argument("begriff", nargs="+")
    s.add_argument("--max", type=float, default=None, help="Höchstpreis in Euro")
    s.add_argument("--plz", default=None)
    s.add_argument("--maerkte", default=None, help='z.B. "aldi-sued, rewe" oder "alle"')
    s.add_argument("--anzahl", type=int, default=15)
    s.add_argument("--json", action="store_true", help="Ausgabe als JSON (für Hermes)")

    a = sub.add_parser("alarm", help="Alarme verwalten")
    asub = a.add_subparsers(dest="aktion", required=True)
    aa = asub.add_parser("add")
    aa.add_argument("begriff", nargs="+")
    aa.add_argument("--max", type=float, default=None)
    asub.add_parser("liste")
    aw = asub.add_parser("weg")
    aw.add_argument("nr", type=int)

    pr = sub.add_parser("pruefen", help="Alarme jetzt prüfen (nur Anzeige, markiert nichts)")
    pr.add_argument("--alle", action="store_true", help="Alarme aller Nutzer prüfen")

    e = sub.add_parser("einstellungen", help="PLZ/Märkte anzeigen oder ändern")
    e.add_argument("--plz", default=None)
    e.add_argument("--maerkte", default=None)

    h = sub.add_parser("haendler", help="Welche Händler Marktguru zu einem Begriff liefert")
    h.add_argument("begriff", nargs="+")
    h.add_argument("--plz", default=None)

    args = p.parse_args()
    db = Datenbank()
    mg = Marktguru()

    try:
        if args.befehl == "suche":
            return cmd_suche(args, db, mg)
        if args.befehl == "alarm":
            return cmd_alarm(args, db)
        if args.befehl == "pruefen":
            return cmd_pruefen(args, db, mg)
        if args.befehl == "einstellungen":
            return cmd_einstellungen(args, db)
        if args.befehl == "haendler":
            n = db.nutzer(args.user)
            for un, name in mg.haendler(" ".join(args.begriff), args.plz or n["plz"]).items():
                print(f"{un:35} {name}")
            for st in mg.letzte_statistik:
                print(f"# Seite ab {st['offset']}: {st['geliefert']} Angebote, totalResults={st['totalResults']}")
            return 0
    except MarktguruFehler as ex:
        print(f"Fehler bei Marktguru: {ex}", file=sys.stderr)
        return 2
    except ValueError as ex:
        print(f"Fehler: {ex}", file=sys.stderr)
        return 1
    return 0


def cmd_suche(args, db: Datenbank, mg: Marktguru) -> int:
    n = db.nutzer(args.user)
    plz = args.plz or n["plz"]
    maerkte = normalisiere_maerkte(args.maerkte) if args.maerkte else n["maerkte"]
    begriff = " ".join(args.begriff)
    angebote = mg.suche(begriff, plz, maerkte, args.max)[: args.anzahl]
    if args.json:
        print(json.dumps(
            {"begriff": begriff, "plz": plz, "maerkte": maerkte, "angebote": [x.als_dict() for x in angebote]},
            ensure_ascii=False, indent=2,
        ))
        return 0
    print(f"'{begriff}' bei PLZ {plz}, Märkte: {', '.join(maerkte)}")
    if not angebote:
        print("Keine aktuellen Angebote gefunden.")
        return 0
    for i, x in enumerate(angebote, 1):
        print(f"{i:2}. {angebot_zeile(x)}")
    return 0


def cmd_alarm(args, db: Datenbank) -> int:
    if args.aktion == "add":
        begriff = " ".join(args.begriff)
        nr = db.alarm_neu(args.user, begriff, args.max)
        grenze = f" bis {args.max:.2f} €".replace(".", ",") if args.max is not None else ""
        print(f"Alarm {nr} angelegt: {begriff}{grenze}")
    elif args.aktion == "liste":
        alarme = db.alarme(args.user)
        if not alarme:
            print("Keine Alarme.")
        for al in alarme:
            grenze = f" (max {al['max_preis']:.2f} €)".replace(".", ",") if al["max_preis"] is not None else ""
            print(f"{al['id']:3}  {al['begriff']}{grenze}")
    elif args.aktion == "weg":
        if db.alarm_weg(args.user, args.nr):
            print(f"Alarm {args.nr} gelöscht.")
        else:
            print(f"Alarm {args.nr} gibt es bei dir nicht.", file=sys.stderr)
            return 1
    return 0


def cmd_pruefen(args, db: Datenbank, mg: Marktguru) -> int:
    treffer = pruefe_alarme(db, mg, None if args.alle else args.user)
    if not treffer:
        print("Keine neuen Treffer.")
        return 0
    for t in treffer:
        print(f"Alarm {t.alarm_id} '{t.begriff}' (Nutzer {t.user_id}): {len(t.angebote)} neu")
        for x in t.angebote[:10]:
            print(f"    {angebot_zeile(x)}")
    return 0


def cmd_einstellungen(args, db: Datenbank) -> int:
    if args.plz:
        db.setze_plz(args.user, args.plz)
    if args.maerkte:
        db.setze_maerkte(args.user, normalisiere_maerkte(args.maerkte))
    n = db.nutzer(args.user)
    print(f"Nutzer: {n['user_id']}")
    print(f"PLZ:    {n['plz']}")
    print(f"Märkte: {', '.join(MAERKTE[m]['name'] for m in n['maerkte'] if m in MAERKTE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
