"""Angebote: portables Desktop-Programm zur Suche in Supermarkt-Angeboten (Marktguru).

Alles liegt im Unterordner 'daten' neben der .exe bzw. neben diesem Skript:
  daten/angebote.db   Einstellungen (PLZ, Märkte) und Merkliste
  daten/angebote.log  Fehlerprotokoll

Start:
  angebote_app.py             Programmfenster
  angebote_app.py --pruefen   ohne Fenster: Merkliste prüfen, neue Treffer als
                              Windows-Benachrichtigung (für die Aufgabenplanung)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Portable Pfade: VOR dem Import von kern setzen
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):          # PyInstaller-.exe
    PROGRAMM_DIR = Path(sys.executable).resolve().parent
    RESSOURCEN = Path(getattr(sys, "_MEIPASS", PROGRAMM_DIR))
else:                                      # als Skript
    PROGRAMM_DIR = Path(__file__).resolve().parent
    RESSOURCEN = PROGRAMM_DIR
    sys.path.insert(0, str(PROGRAMM_DIR.parent))  # kern.py liegt eine Ebene höher

DATEN_DIR = PROGRAMM_DIR / "daten"
DATEN_DIR.mkdir(exist_ok=True)
os.environ["DB_PFAD"] = str(DATEN_DIR / "angebote.db")

logging.basicConfig(
    filename=DATEN_DIR / "angebote.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("angebote")

from kern import (  # noqa: E402
    MAERKTE,
    Angebot,
    Datenbank,
    Marktguru,
    MarktguruFehler,
    pruefe_alarme,
)

NUTZER = "desktop"
APP_NAME = "Angebote"


def angebot_json(a: Angebot) -> dict:
    return {
        "id": a.id,
        "markt": a.markt,
        "titel": a.titel,
        "beschreibung": a.beschreibung[:300],
        "preis": a.preis_text,
        "alter_preis": f"{a.alter_preis:.2f} €".replace(".", ",") if a.alter_preis else "",
        "grundpreis": a.grundpreis_text,
        "gueltig": a.gueltig_text,
        "karte": a.nur_mit_karte,
        "bild": a.bild,
    }


# ---------------------------------------------------------------------------
# Schnittstelle für die Oberfläche (window.pywebview.api.*)
# ---------------------------------------------------------------------------

class Api:
    def __init__(self) -> None:
        self.db = Datenbank()
        self.mg = Marktguru()

    def start(self) -> dict:
        n = self.db.nutzer(NUTZER)
        return {
            "plz": n["plz"],
            "maerkte": n["maerkte"],
            "alle_maerkte": [{"key": k, "name": v["name"]} for k, v in MAERKTE.items()],
            "datenordner": str(DATEN_DIR),
        }

    def einstellungen_speichern(self, plz: str, maerkte: list[str]) -> dict:
        try:
            self.db.setze_plz(NUTZER, plz)
            self.db.setze_maerkte(NUTZER, [m for m in maerkte if m in MAERKTE])
            return {"ok": True}
        except ValueError as ex:
            return {"ok": False, "fehler": str(ex)}

    def suche(self, begriff: str, max_preis=None) -> dict:
        begriff = (begriff or "").strip()
        if not begriff:
            return {"ok": False, "fehler": "Suchbegriff fehlt."}
        n = self.db.nutzer(NUTZER)
        try:
            mp = float(str(max_preis).replace(",", ".")) if max_preis not in (None, "") else None
        except ValueError:
            return {"ok": False, "fehler": "Höchstpreis ist keine Zahl."}
        try:
            angebote = self.mg.suche(begriff, n["plz"], n["maerkte"], mp)
        except MarktguruFehler as ex:
            log.error("Suche '%s': %s", begriff, ex)
            return {"ok": False, "fehler": str(ex)}
        except Exception as ex:  # Netzwerk o.ä., Programm soll nicht abstürzen
            log.exception("Suche '%s'", begriff)
            return {"ok": False, "fehler": f"Unerwarteter Fehler: {ex}"}
        return {"ok": True, "angebote": [angebot_json(a) for a in angebote]}

    # -- Merkliste -----------------------------------------------------------
    def merkliste(self) -> list[dict]:
        return [
            {"id": r["id"], "begriff": r["begriff"], "max_preis": r["max_preis"]}
            for r in self.db.alarme(NUTZER)
        ]

    def merken(self, begriff: str, max_preis=None) -> dict:
        try:
            mp = float(str(max_preis).replace(",", ".")) if max_preis not in (None, "") else None
            self.db.alarm_neu(NUTZER, begriff, mp)
            return {"ok": True}
        except ValueError as ex:
            return {"ok": False, "fehler": str(ex)}

    def vergessen(self, alarm_id: int) -> dict:
        return {"ok": self.db.alarm_weg(NUTZER, int(alarm_id))}

    def merkliste_pruefen(self) -> dict:
        """Neue Treffer je Eintrag. Markiert sie nicht, das macht gesehen()."""
        try:
            treffer = pruefe_alarme(self.db, self.mg, NUTZER)
        except MarktguruFehler as ex:
            return {"ok": False, "fehler": str(ex)}
        except Exception as ex:
            log.exception("Merkliste prüfen")
            return {"ok": False, "fehler": f"Unerwarteter Fehler: {ex}"}
        return {
            "ok": True,
            "treffer": [
                {
                    "alarm_id": t.alarm_id,
                    "begriff": t.begriff,
                    "angebote": [angebot_json(a) for a in t.angebote],
                }
                for t in treffer
            ],
        }

    def gesehen(self, alarm_id: int, offer_ids: list[int]) -> dict:
        self.db.markiere_gemeldet(int(alarm_id), [int(x) for x in offer_ids])
        return {"ok": True}

    def datenordner_oeffnen(self) -> None:
        if sys.platform.startswith("win"):
            os.startfile(DATEN_DIR)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Hintergrundprüfung ohne Fenster
# ---------------------------------------------------------------------------

def hintergrund_pruefen() -> int:
    api = Api()
    erg = api.merkliste_pruefen()
    if not erg["ok"]:
        log.error("Hintergrundprüfung: %s", erg["fehler"])
        return 2
    # Nur melden, was noch nie per Benachrichtigung gemeldet wurde. Im Programm
    # bleiben die Treffer trotzdem "neu", bis du sie dort abhakst.
    import json
    merk_datei = DATEN_DIR / "benachrichtigt.json"
    try:
        schon = set(json.loads(merk_datei.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        schon = set()
    zeilen = []
    for t in erg["treffer"]:
        neu = [a for a in t["angebote"] if f"{t['alarm_id']}:{a['id']}" not in schon]
        if not neu:
            continue
        schon.update(f"{t['alarm_id']}:{a['id']}" for a in neu)
        zeilen.append(f"{t['begriff']}: {neu[0]['markt']} {neu[0]['preis']}"
                      + (f" (+{len(neu) - 1})" if len(neu) > 1 else ""))
    if not zeilen:
        log.info("Hintergrundprüfung: nichts Neues zu melden")
        return 0
    merk_datei.write_text(json.dumps(sorted(schon)), encoding="utf-8")
    text = "\n".join(zeilen[:4])
    log.info("Hintergrundprüfung: %s", text.replace("\n", " | "))
    try:
        from win11toast import toast  # nur unter Windows installiert
        toast(f"{APP_NAME}: neue Angebote", text)
    except Exception as ex:
        log.warning("Benachrichtigung nicht möglich: %s", ex)
    return 0


def main() -> int:
    if "--pruefen" in sys.argv:
        return hintergrund_pruefen()

    import webview

    api = Api()
    html = RESSOURCEN / "ui.html"
    webview.create_window(
        APP_NAME,
        url=str(html),
        js_api=api,
        width=1150,
        height=820,
        min_size=(760, 520),
        background_color="#14171c",
    )
    webview.start(private_mode=False, storage_path=str(DATEN_DIR / "webview"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
