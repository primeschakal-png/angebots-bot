"""Discord-Bot für Supermarkt-Angebote. Kein LLM, keine Shell, nur feste Befehle.

Slash-Commands:
  /angebot begriff [max_preis] [oeffentlich]
  /plz plz
  /maerkte auswahl
  /einstellungen
  /alarm add begriff [max_preis]
  /alarm liste
  /alarm weg nr
  /alarm pruefen

Einmal täglich (PRUEFZEIT, Standard 06:30 Uhr) prüft der Bot alle Alarme und schickt
neue Treffer per DM. Was gemeldet wurde, steht in der Datenbank und kommt nicht nochmal.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import time as dtime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from kern import (
    MAERKTE,
    Angebot,
    Datenbank,
    Marktguru,
    MarktguruFehler,
    euro,
    normalisiere_maerkte,
    pruefe_alarme,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("angebots-bot")

TOKEN = os.environ.get("DISCORD_TOKEN", "")
GUILD_ID = os.environ.get("GUILD_ID", "").strip()
ZEITZONE = ZoneInfo(os.environ.get("ZEITZONE", "Europe/Berlin"))
_std, _min = (int(x) for x in os.environ.get("PRUEFZEIT", "06:30").split(":"))
PRUEFZEIT = dtime(hour=_std, minute=_min, tzinfo=ZEITZONE)
MAX_ZEILEN = 10
FARBE = discord.Color.from_rgb(46, 160, 67)

db = Datenbank()
mg = Marktguru()


# ---------------------------------------------------------------------------
# Darstellung
# ---------------------------------------------------------------------------

def zeile(a: Angebot) -> str:
    teil = f"**{a.markt}**: {a.titel} · **{a.preis_text}**"
    if a.grundpreis_text:
        teil += f" ({a.grundpreis_text})"
    if a.alter_preis:
        teil += f" ~~{euro(a.alter_preis)}~~"
    teil += f" · {a.gueltig_text}"
    if a.nur_mit_karte:
        teil += " · nur mit App/Karte"
    return teil


def embed_angebote(titel: str, angebote: list[Angebot], fuss: str = "") -> discord.Embed:
    e = discord.Embed(title=titel[:256], color=FARBE)
    if not angebote:
        e.description = "Keine aktuellen Angebote gefunden."
    else:
        zeilen = [f"{i}. {zeile(a)}" for i, a in enumerate(angebote[:MAX_ZEILEN], 1)]
        if len(angebote) > MAX_ZEILEN:
            zeilen.append(f"… und {len(angebote) - MAX_ZEILEN} weitere")
        e.description = "\n".join(zeilen)[:4000]
        e.set_thumbnail(url=angebote[0].bild)
    e.set_footer(text=(fuss + " · " if fuss else "") + "Daten: marktguru.de, sortiert nach Grundpreis")
    return e


def maerkte_text(keys: list[str]) -> str:
    return ", ".join(MAERKTE[k]["name"] for k in keys if k in MAERKTE)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Bot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.tree.add_command(alarm_gruppe)
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Befehle für Server %s synchronisiert", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Befehle global synchronisiert (kann bis zu 1 h dauern)")
        taegliche_pruefung.start()

    async def on_ready(self) -> None:
        log.info("Eingeloggt als %s, tägliche Prüfung um %s", self.user, PRUEFZEIT.strftime("%H:%M"))


bot = Bot()


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------

@bot.tree.command(name="angebot", description="Aktuelle Angebote in deinen Märkten suchen")
@app_commands.describe(
    begriff="Was suchst du? z.B. Gefrierbeutel",
    max_preis="Höchstpreis in Euro (optional)",
    oeffentlich="Ergebnis für alle im Kanal sichtbar machen",
)
async def cmd_angebot(
    interaction: discord.Interaction,
    begriff: str,
    max_preis: float | None = None,
    oeffentlich: bool = False,
) -> None:
    await interaction.response.defer(ephemeral=not oeffentlich, thinking=True)
    n = db.nutzer(interaction.user.id)
    try:
        angebote = await asyncio.to_thread(mg.suche, begriff, n["plz"], n["maerkte"], max_preis)
    except MarktguruFehler as ex:
        await interaction.followup.send(f"Marktguru macht gerade Probleme: {ex}", ephemeral=True)
        return
    titel = f"{begriff}" + (f" bis {euro(max_preis)}" if max_preis is not None else "")
    await interaction.followup.send(embed=embed_angebote(titel, angebote, f"PLZ {n['plz']}"))


@bot.tree.command(name="plz", description="Deine Postleitzahl setzen")
@app_commands.describe(plz="Fünfstellige PLZ")
async def cmd_plz(interaction: discord.Interaction, plz: str) -> None:
    try:
        db.setze_plz(interaction.user.id, plz)
    except ValueError as ex:
        await interaction.response.send_message(str(ex), ephemeral=True)
        return
    await interaction.response.send_message(f"PLZ gesetzt: {plz.strip()}", ephemeral=True)


@bot.tree.command(name="maerkte", description="Deine Märkte festlegen")
@app_commands.describe(auswahl="z.B. 'aldi-sued, rewe, lidl' oder 'alle'. Möglich: " + ", ".join(MAERKTE))
async def cmd_maerkte(interaction: discord.Interaction, auswahl: str) -> None:
    try:
        keys = normalisiere_maerkte(auswahl)
        db.setze_maerkte(interaction.user.id, keys)
    except ValueError as ex:
        await interaction.response.send_message(str(ex), ephemeral=True)
        return
    await interaction.response.send_message(f"Deine Märkte: {maerkte_text(keys)}", ephemeral=True)


@bot.tree.command(name="einstellungen", description="Deine PLZ, Märkte und Alarme anzeigen")
async def cmd_einstellungen(interaction: discord.Interaction) -> None:
    n = db.nutzer(interaction.user.id)
    alarme = db.alarme(interaction.user.id)
    text = f"**PLZ:** {n['plz']}\n**Märkte:** {maerkte_text(n['maerkte'])}\n**Alarme:** {len(alarme)}"
    await interaction.response.send_message(text, ephemeral=True)


alarm_gruppe = app_commands.Group(name="alarm", description="Preisalarme verwalten")


@alarm_gruppe.command(name="add", description="Alarm anlegen, du bekommst eine DM bei neuen Angeboten")
@app_commands.describe(begriff="z.B. Gefrierbeutel", max_preis="Nur melden bis zu diesem Preis (optional)")
async def alarm_add(interaction: discord.Interaction, begriff: str, max_preis: float | None = None) -> None:
    try:
        nr = db.alarm_neu(interaction.user.id, begriff, max_preis)
    except ValueError as ex:
        await interaction.response.send_message(str(ex), ephemeral=True)
        return
    grenze = f" bis {euro(max_preis)}" if max_preis is not None else ""
    await interaction.response.send_message(
        f"Alarm **{nr}** angelegt: {begriff}{grenze}. Ich prüfe täglich um {PRUEFZEIT.strftime('%H:%M')} Uhr "
        "und schreib dir per DM. Damit das klappt, müssen DMs von Servermitgliedern erlaubt sein.",
        ephemeral=True,
    )


@alarm_gruppe.command(name="liste", description="Deine Alarme anzeigen")
async def alarm_liste(interaction: discord.Interaction) -> None:
    alarme = db.alarme(interaction.user.id)
    if not alarme:
        await interaction.response.send_message("Du hast keine Alarme.", ephemeral=True)
        return
    zeilen = []
    for al in alarme:
        grenze = f" (max {euro(al['max_preis'])})" if al["max_preis"] is not None else ""
        zeilen.append(f"**{al['id']}**: {al['begriff']}{grenze}")
    await interaction.response.send_message("\n".join(zeilen), ephemeral=True)


@alarm_gruppe.command(name="weg", description="Alarm löschen")
@app_commands.describe(nr="Nummer aus /alarm liste")
async def alarm_weg(interaction: discord.Interaction, nr: int) -> None:
    ok = db.alarm_weg(interaction.user.id, nr)
    await interaction.response.send_message(
        f"Alarm {nr} gelöscht." if ok else f"Alarm {nr} gibt es bei dir nicht.", ephemeral=True
    )


@alarm_gruppe.command(name="pruefen", description="Deine Alarme sofort prüfen (zählt nicht als gemeldet)")
async def alarm_pruefen(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        treffer = await asyncio.to_thread(pruefe_alarme, db, mg, str(interaction.user.id))
    except MarktguruFehler as ex:
        await interaction.followup.send(f"Marktguru macht gerade Probleme: {ex}", ephemeral=True)
        return
    if not treffer:
        await interaction.followup.send("Keine neuen Treffer für deine Alarme.", ephemeral=True)
        return
    embeds = [embed_angebote(f"Alarm {t.alarm_id}: {t.begriff}", t.angebote) for t in treffer[:10]]
    await interaction.followup.send(embeds=embeds, ephemeral=True)


# ---------------------------------------------------------------------------
# Tägliche Prüfung
# ---------------------------------------------------------------------------

@tasks.loop(time=PRUEFZEIT)
async def taegliche_pruefung() -> None:
    await alarme_versenden()


async def alarme_versenden() -> None:
    log.info("Prüfe Alarme …")
    try:
        treffer = await asyncio.to_thread(pruefe_alarme, db, mg, None)
    except MarktguruFehler as ex:
        log.error("Alarmprüfung abgebrochen: %s", ex)
        return

    je_nutzer: dict[str, list] = {}
    for t in treffer:
        je_nutzer.setdefault(t.user_id, []).append(t)

    for user_id, liste in je_nutzer.items():
        if not user_id.isdigit():
            continue  # z.B. 'cli' ohne Discord-ID
        try:
            user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
            # max. 10 Embeds pro Nachricht
            for i in range(0, len(liste), 10):
                block = liste[i : i + 10]
                embeds = [
                    embed_angebote(
                        f"Neu im Angebot: {t.begriff}" + (f" bis {euro(t.max_preis)}" if t.max_preis else ""),
                        t.angebote,
                        f"Alarm {t.alarm_id}",
                    )
                    for t in block
                ]
                await user.send(embeds=embeds)
                for t in block:
                    db.markiere_gemeldet(t.alarm_id, [a.id for a in t.angebote])
        except discord.Forbidden:
            log.warning("DM an %s nicht möglich (DMs gesperrt)", user_id)
        except discord.HTTPException as ex:
            log.warning("DM an %s fehlgeschlagen: %s", user_id, ex)
    log.info("Alarmprüfung fertig: %d Treffer bei %d Nutzern", len(treffer), len(je_nutzer))


@taegliche_pruefung.before_loop
async def vor_pruefung() -> None:
    await bot.wait_until_ready()


def main() -> None:
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN fehlt in .env")
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
