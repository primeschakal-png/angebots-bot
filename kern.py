"""Kern des Angebots-Bots: Marktguru-Abfrage, Filter, Sortierung und Datenbank.

Wird von cli.py (Kommandozeile, Hermes) und discord_bot.py gemeinsam benutzt.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASIS = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

def lade_env(pfad: Path = BASIS / ".env") -> None:
    """Liest eine einfache .env-Datei (KEY=WERT) in os.environ, ohne Fremdpaket."""
    if not pfad.exists():
        return
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        key, wert = zeile.split("=", 1)
        os.environ.setdefault(key.strip(), wert.strip().strip('"').strip("'"))


lade_env()

# Kürzel -> Präfixe, mit denen der Marktguru-uniqueName des Händlers beginnt.
# Präfix statt exakter Name, weil z.B. Rewe/Edeka regionale Varianten haben
# (rewe-center, edeka-center ...).
MAERKTE: dict[str, dict] = {
    "aldi-nord": {"name": "Aldi Nord", "praefixe": ["aldi-nord"]},
    "aldi-sued": {"name": "Aldi Süd", "praefixe": ["aldi-sued", "aldi-sud"]},
    "rewe": {"name": "Rewe", "praefixe": ["rewe"]},
    "netto": {"name": "Netto Marken-Discount", "praefixe": ["netto-marken-discount"]},
    "lidl": {"name": "Lidl", "praefixe": ["lidl"]},
    "kaufland": {"name": "Kaufland", "praefixe": ["kaufland"]},
    "edeka": {"name": "Edeka", "praefixe": ["edeka", "e-center"]},
}

STANDARD_PLZ = os.environ.get("STANDARD_PLZ", "42579")
STANDARD_MAERKTE = [
    m.strip() for m in os.environ.get("STANDARD_MAERKTE", ",".join(MAERKTE)).split(",") if m.strip()
]
DB_PFAD = Path(os.environ.get("DB_PFAD", str(BASIS / "angebote.db")))
try:
    ZEITZONE = ZoneInfo(os.environ.get("ZEITZONE", "Europe/Berlin"))
except Exception:  # Windows ohne Paket tzdata: Ortszeit des Rechners nehmen
    ZEITZONE = None
CACHE_SEKUNDEN = int(os.environ.get("CACHE_SEKUNDEN", "1800"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def normalisiere_maerkte(eingabe: str | list[str]) -> list[str]:
    """Macht aus 'Aldi Süd, rewe, Netto' die internen Kürzel. Unbekanntes -> ValueError."""
    if isinstance(eingabe, str):
        teile = re.split(r"[,;\s]+", eingabe.strip())
    else:
        teile = list(eingabe)
    ersatz = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "_": "-"}
    ergebnis: list[str] = []
    fehler: list[str] = []
    i = 0
    while i < len(teile):
        t = teile[i].lower().strip()
        if not t:
            i += 1
            continue
        for a, b in ersatz.items():
            t = t.replace(a, b)
        # "aldi sued" in zwei Wörtern zusammenziehen
        if t == "aldi" and i + 1 < len(teile):
            naechstes = teile[i + 1].lower().replace("ü", "ue")
            if naechstes in ("nord", "sued", "sud"):
                t = "aldi-" + ("sued" if naechstes != "nord" else "nord")
                i += 1
        if t in ("alle", "standard"):
            ergebnis.extend(STANDARD_MAERKTE if t == "standard" else MAERKTE.keys())
        elif t in MAERKTE:
            ergebnis.append(t)
        elif t == "aldisued":
            ergebnis.append("aldi-sued")
        elif t == "aldinord":
            ergebnis.append("aldi-nord")
        else:
            fehler.append(teile[i])
        i += 1
    if fehler:
        raise ValueError(
            "Unbekannte Märkte: " + ", ".join(fehler) + ". Möglich: " + ", ".join(MAERKTE)
        )
    # Reihenfolge behalten, Dubletten raus
    return list(dict.fromkeys(ergebnis))


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class Angebot:
    id: int
    markt: str            # Anzeigename des Händlers laut Marktguru
    markt_key: str | None  # internes Kürzel (aldi-nord, rewe ...) oder None
    titel: str
    beschreibung: str
    preis: float | None
    alter_preis: float | None
    grundpreis: float | None
    einheit: str
    gueltig_von: datetime | None
    gueltig_bis: datetime | None
    nur_mit_karte: bool
    bild: str = field(default="")

    @property
    def preis_text(self) -> str:
        return euro(self.preis) if self.preis is not None else "?"

    @property
    def grundpreis_text(self) -> str:
        if self.grundpreis is None:
            return ""
        if self.preis is not None and abs(self.grundpreis - self.preis) < 0.005 and self.einheit.lower() in ("stk", "stück", "st"):
            return ""
        return f"{euro(self.grundpreis)}/{self.einheit}" if self.einheit else euro(self.grundpreis)

    @property
    def gueltig_text(self) -> str:
        von = self.gueltig_von.astimezone(ZEITZONE).strftime("%d.%m.") if self.gueltig_von else "?"
        bis = self.gueltig_bis.astimezone(ZEITZONE).strftime("%d.%m.") if self.gueltig_bis else "?"
        return f"{von} bis {bis}"

    def als_dict(self) -> dict:
        return {
            "id": self.id,
            "markt": self.markt,
            "titel": self.titel,
            "preis": self.preis,
            "alter_preis": self.alter_preis,
            "grundpreis": self.grundpreis,
            "einheit": self.einheit,
            "gueltig_von": self.gueltig_von.isoformat() if self.gueltig_von else None,
            "gueltig_bis": self.gueltig_bis.isoformat() if self.gueltig_bis else None,
            "nur_mit_karte": self.nur_mit_karte,
            "beschreibung": self.beschreibung,
        }


def euro(wert: float) -> str:
    return f"{wert:.2f}".replace(".", ",") + " €"


def _datum(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def markt_key_fuer(unique_name: str, name: str) -> str | None:
    un = (unique_name or "").lower()
    nm = re.sub(r"[^a-z0-9]+", "-", (name or "").lower().replace("ü", "ue").replace("ä", "ae").replace("ö", "oe"))
    for key, info in MAERKTE.items():
        for p in info["praefixe"]:
            if un.startswith(p) or nm.startswith(p):
                return key
    return None


# ---------------------------------------------------------------------------
# Marktguru-Client (inoffizielle Schnittstelle)
# ---------------------------------------------------------------------------

class MarktguruFehler(RuntimeError):
    pass


class Marktguru:
    """Holt Angebote über die Web-Schnittstelle von marktguru.de.

    Die Schlüssel (apiKey/clientKey) stehen als JSON im Quelltext der Startseite.
    Sie werden einmal geholt und bei 401/403 automatisch erneuert.
    """

    API = "https://api.marktguru.de/api/v1"
    START = "https://www.marktguru.de/"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"})
        self._keys: tuple[str, str] | None = None
        if os.environ.get("MARKTGURU_APIKEY") and os.environ.get("MARKTGURU_CLIENTKEY"):
            self._keys = (os.environ["MARKTGURU_APIKEY"], os.environ["MARKTGURU_CLIENTKEY"])
        self._cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
        self.letzte_statistik: list[dict] = []

    # -- Schlüssel ---------------------------------------------------------
    def _hole_keys(self) -> tuple[str, str]:
        try:
            r = self.session.get(self.START, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            raise MarktguruFehler(f"Startseite nicht erreichbar: {e}") from e
        bloecke = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', r.text, re.S)
        for block in bloecke:
            try:
                daten = json.loads(block)
            except json.JSONDecodeError:
                continue
            api = _suche_schluessel(daten, "apiKey")
            client = _suche_schluessel(daten, "clientKey")
            if api and client:
                return api, client
        # Fallback: direkt im Quelltext suchen
        api = re.search(r'"apiKey"\s*:\s*"([^"]+)"', r.text)
        client = re.search(r'"clientKey"\s*:\s*"([^"]+)"', r.text)
        if api and client:
            return api.group(1), client.group(1)
        raise MarktguruFehler(
            "Keine API-Schlüssel auf marktguru.de gefunden. Die Seite hat sich vermutlich geändert. "
            "Notlösung: MARKTGURU_APIKEY und MARKTGURU_CLIENTKEY in .env eintragen."
        )

    def _keys_holen(self, neu: bool = False) -> tuple[str, str]:
        if self._keys is None or neu:
            self._keys = self._hole_keys()
        return self._keys

    # -- Suche -------------------------------------------------------------
    def suche_roh(self, begriff: str, plz: str, limit: int = 300) -> list[dict]:
        schluessel = (begriff.lower().strip(), str(plz))
        jetzt = time.time()
        if schluessel in self._cache and jetzt - self._cache[schluessel][0] < CACHE_SEKUNDEN:
            return self._cache[schluessel][1]

        ergebnisse: list[dict] = []
        offset = 0
        self.letzte_statistik = []
        for _ in range(5):  # max. 5 Seiten
            daten = self._anfrage(begriff, plz, limit, offset)
            seite = daten.get("results") or []
            ergebnisse.extend(seite)
            gesamt = daten.get("totalResults") or len(ergebnisse)
            self.letzte_statistik.append({"offset": offset, "geliefert": len(seite), "totalResults": daten.get("totalResults")})
            offset += len(seite)
            if not seite or offset >= gesamt:
                break
        self._cache[schluessel] = (jetzt, ergebnisse)
        return ergebnisse

    def _anfrage(self, begriff: str, plz: str, limit: int, offset: int) -> dict:
        params = {"as": "web", "q": begriff, "zipCode": str(plz), "limit": limit, "offset": offset}
        for versuch in range(2):
            api, client = self._keys_holen(neu=versuch > 0)
            try:
                r = self.session.get(
                    f"{self.API}/offers/search",
                    params=params,
                    headers={"x-apikey": api, "x-clientkey": client, "Accept": "application/json"},
                    timeout=20,
                )
            except requests.RequestException as e:
                raise MarktguruFehler(f"Marktguru-API nicht erreichbar: {e}") from e
            if r.status_code in (401, 403) and versuch == 0:
                continue  # Schlüssel abgelaufen, neu holen
            if r.status_code == 429:
                raise MarktguruFehler("Marktguru bremst (HTTP 429). Später nochmal versuchen.")
            if not r.ok:
                raise MarktguruFehler(f"Marktguru-API antwortet mit HTTP {r.status_code}: {r.text[:200]}")
            try:
                return r.json()
            except ValueError as e:
                raise MarktguruFehler("Marktguru-API liefert kein JSON.") from e
        raise MarktguruFehler("Marktguru lehnt die Schlüssel ab (HTTP 401/403).")

    def suche(
        self,
        begriff: str,
        plz: str,
        maerkte: list[str] | None = None,
        max_preis: float | None = None,
        nur_gueltige: bool = True,
    ) -> list[Angebot]:
        """Sucht, filtert nach Märkten/Preis/Gültigkeit und sortiert nach Grundpreis."""
        roh = self.suche_roh(begriff, plz)
        erlaubte = set(maerkte) if maerkte else None
        jetzt = datetime.now(timezone.utc)
        ergebnis: list[Angebot] = []
        gesehen: set[int] = set()
        for o in roh:
            a = _baue_angebot(o)
            if a is None or a.id in gesehen:
                continue
            if erlaubte is not None and a.markt_key not in erlaubte:
                continue
            if nur_gueltige and a.gueltig_bis is not None and a.gueltig_bis < jetzt:
                continue
            if max_preis is not None and (a.preis is None or a.preis > max_preis):
                continue
            gesehen.add(a.id)
            ergebnis.append(a)
        return sortiere(ergebnis)

    def haendler(self, begriff: str, plz: str) -> dict[str, str]:
        """Alle Händler (uniqueName -> Name), die zu einem Suchbegriff auftauchen. Zur Fehlersuche."""
        out: dict[str, str] = {}
        for o in self.suche_roh(begriff, plz):
            for adv in o.get("advertisers") or []:
                out[adv.get("uniqueName", "?")] = adv.get("name", "?")
        return dict(sorted(out.items()))


def _suche_schluessel(daten, name: str):
    if isinstance(daten, dict):
        if isinstance(daten.get(name), str):
            return daten[name]
        for wert in daten.values():
            treffer = _suche_schluessel(wert, name)
            if treffer:
                return treffer
    elif isinstance(daten, list):
        for wert in daten:
            treffer = _suche_schluessel(wert, name)
            if treffer:
                return treffer
    return None


def _baue_angebot(o: dict) -> Angebot | None:
    try:
        oid = int(o["id"])
    except (KeyError, TypeError, ValueError):
        return None
    advs = o.get("advertisers") or []
    markt, key = "?", None
    for adv in advs:
        k = markt_key_fuer(adv.get("uniqueName", ""), adv.get("name", ""))
        markt = adv.get("name") or markt
        if k:
            key = k
            break
    brand = (o.get("brand") or {}).get("name") or ""
    if re.match(r"(?i)thisisnobrand|no.?brand|keine marke", brand):
        brand = ""
    produkt = (o.get("product") or {}).get("name") or ""
    produkt = re.sub(r"(?i)\bthisisnobrand\w*\s*", "", produkt).strip()
    titel = produkt if brand and brand.lower() in produkt.lower() else f"{brand} {produkt}".strip()
    von = [_datum(v.get("from")) for v in o.get("validityDates") or []]
    bis = [_datum(v.get("to")) for v in o.get("validityDates") or []]
    von = [d for d in von if d]
    bis = [d for d in bis if d]
    einheit = (o.get("unit") or {}).get("shortName") or ""
    return Angebot(
        id=oid,
        markt=markt,
        markt_key=key,
        titel=titel or "(ohne Namen)",
        beschreibung=(o.get("description") or "").strip(),
        preis=_zahl(o.get("price")),
        alter_preis=_zahl(o.get("oldPrice")),
        grundpreis=_zahl(o.get("referencePrice")),
        einheit=einheit,
        gueltig_von=min(von) if von else None,
        gueltig_bis=max(bis) if bis else None,
        nur_mit_karte=bool(o.get("requiresLoyalityMembership")),
        bild=f"https://mg2de.b-cdn.net/api/v1/offers/{oid}/images/default/0/small.jpg",
    )


def _zahl(w) -> float | None:
    try:
        return float(w) if w is not None else None
    except (TypeError, ValueError):
        return None


def sortiere(angebote: list[Angebot]) -> list[Angebot]:
    """Gruppiert nach Grundpreis-Einheit, die häufigste Einheit zuerst (bei 'Kaffee' also kg,
    nicht Stk), innerhalb der Gruppe nach Grundpreis. Ohne Grundpreis nach Preis ans Ende."""
    haeufigkeit: dict[str, int] = {}
    for a in angebote:
        if a.grundpreis:
            haeufigkeit[a.einheit.lower()] = haeufigkeit.get(a.einheit.lower(), 0) + 1
    rang = {e: i for i, (e, _) in enumerate(sorted(haeufigkeit.items(), key=lambda x: -x[1]))}

    def schluessel(a: Angebot):
        if a.grundpreis:
            return (rang[a.einheit.lower()], a.grundpreis, a.preis or 0)
        return (len(rang), a.preis if a.preis is not None else 9999, 0)

    return sorted(angebote, key=schluessel)


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS nutzer (
    user_id  TEXT PRIMARY KEY,
    plz      TEXT NOT NULL,
    maerkte  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alarme (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   TEXT NOT NULL,
    begriff   TEXT NOT NULL,
    max_preis REAL,
    erstellt  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gemeldet (
    alarm_id  INTEGER NOT NULL,
    offer_id  INTEGER NOT NULL,
    zeit      TEXT NOT NULL,
    PRIMARY KEY (alarm_id, offer_id)
);
"""


class Datenbank:
    def __init__(self, pfad: Path = DB_PFAD) -> None:
        self.con = sqlite3.connect(pfad, timeout=10, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        self.con.commit()

    # -- Nutzer ------------------------------------------------------------
    def nutzer(self, user_id: str) -> dict:
        row = self.con.execute("SELECT * FROM nutzer WHERE user_id=?", (str(user_id),)).fetchone()
        if row:
            return {"user_id": row["user_id"], "plz": row["plz"], "maerkte": json.loads(row["maerkte"])}
        return {"user_id": str(user_id), "plz": STANDARD_PLZ, "maerkte": list(STANDARD_MAERKTE)}

    def setze_plz(self, user_id: str, plz: str) -> None:
        if not re.fullmatch(r"\d{5}", plz.strip()):
            raise ValueError("PLZ muss fünfstellig sein.")
        n = self.nutzer(user_id)
        self._speichere(user_id, plz.strip(), n["maerkte"])

    def setze_maerkte(self, user_id: str, maerkte: list[str]) -> None:
        if not maerkte:
            raise ValueError("Mindestens ein Markt nötig.")
        n = self.nutzer(user_id)
        self._speichere(user_id, n["plz"], maerkte)

    def _speichere(self, user_id: str, plz: str, maerkte: list[str]) -> None:
        self.con.execute(
            "INSERT INTO nutzer(user_id, plz, maerkte) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET plz=excluded.plz, maerkte=excluded.maerkte",
            (str(user_id), plz, json.dumps(maerkte)),
        )
        self.con.commit()

    # -- Alarme ------------------------------------------------------------
    def alarm_neu(self, user_id: str, begriff: str, max_preis: float | None) -> int:
        begriff = begriff.strip()
        if not begriff:
            raise ValueError("Suchbegriff fehlt.")
        if len(self.alarme(user_id)) >= int(os.environ.get("MAX_ALARME", "25")):
            raise ValueError("Zu viele Alarme. Lösch erst einen.")
        cur = self.con.execute(
            "INSERT INTO alarme(user_id, begriff, max_preis, erstellt) VALUES(?,?,?,?)",
            (str(user_id), begriff, max_preis, datetime.now(timezone.utc).isoformat()),
        )
        self.con.commit()
        return int(cur.lastrowid)

    def alarme(self, user_id: str | None = None) -> list[sqlite3.Row]:
        if user_id is None:
            return self.con.execute("SELECT * FROM alarme ORDER BY user_id, id").fetchall()
        return self.con.execute(
            "SELECT * FROM alarme WHERE user_id=? ORDER BY id", (str(user_id),)
        ).fetchall()

    def alarm_weg(self, user_id: str, alarm_id: int) -> bool:
        cur = self.con.execute(
            "DELETE FROM alarme WHERE id=? AND user_id=?", (int(alarm_id), str(user_id))
        )
        self.con.execute("DELETE FROM gemeldet WHERE alarm_id=?", (int(alarm_id),))
        self.con.commit()
        return cur.rowcount > 0

    def schon_gemeldet(self, alarm_id: int, offer_id: int) -> bool:
        return (
            self.con.execute(
                "SELECT 1 FROM gemeldet WHERE alarm_id=? AND offer_id=?", (alarm_id, offer_id)
            ).fetchone()
            is not None
        )

    def markiere_gemeldet(self, alarm_id: int, offer_ids: list[int]) -> None:
        jetzt = datetime.now(timezone.utc).isoformat()
        self.con.executemany(
            "INSERT OR IGNORE INTO gemeldet(alarm_id, offer_id, zeit) VALUES(?,?,?)",
            [(alarm_id, oid, jetzt) for oid in offer_ids],
        )
        self.con.commit()


# ---------------------------------------------------------------------------
# Alarmprüfung
# ---------------------------------------------------------------------------

@dataclass
class Treffer:
    user_id: str
    alarm_id: int
    begriff: str
    max_preis: float | None
    angebote: list[Angebot]


def pruefe_alarme(db: Datenbank, mg: Marktguru, user_id: str | None = None) -> list[Treffer]:
    """Liefert neue Treffer je Alarm. Markiert NICHTS als gemeldet, das macht der Absender
    erst nach erfolgreichem Versand (db.markiere_gemeldet)."""
    treffer: list[Treffer] = []
    for alarm in db.alarme(user_id):
        n = db.nutzer(alarm["user_id"])
        angebote = mg.suche(alarm["begriff"], n["plz"], n["maerkte"], alarm["max_preis"])
        neu = [a for a in angebote if not db.schon_gemeldet(alarm["id"], a.id)]
        if neu:
            treffer.append(
                Treffer(alarm["user_id"], alarm["id"], alarm["begriff"], alarm["max_preis"], neu)
            )
    return treffer


def angebot_zeile(a: Angebot) -> str:
    """Einzeilige Textdarstellung für CLI und DMs."""
    teile = [f"{a.markt}: {a.titel}", a.preis_text]
    if a.grundpreis_text:
        teile.append(f"({a.grundpreis_text})")
    if a.alter_preis:
        teile.append(f"statt {euro(a.alter_preis)}")
    teile.append(f"[{a.gueltig_text}]")
    if a.nur_mit_karte:
        teile.append("nur mit Kundenkarte/App")
    return " ".join(teile)
