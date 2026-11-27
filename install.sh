#!/usr/bin/env bash
# Installiert bzw. aktualisiert den Angebots-Bot für den aktuellen User (gedacht: moltbook).
# Braucht kein root. Den systemd-Dienst richtet am Ende einmalig root ein (Befehle werden ausgegeben).
#
#   bash install.sh          installieren / aktualisieren
#
set -euo pipefail

REPO="https://github.com/primeschakal-png/angebots-bot.git"
ZIEL="${HOME}/angebots-bot"
SKILL_DIR="${HOME}/.hermes/skills/angebote"

echo "== Angebots-Bot installieren nach ${ZIEL} =="

if ! command -v python3 >/dev/null; then
    echo "FEHLER: python3 fehlt." >&2; exit 1
fi
if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
    echo "FEHLER: python3-venv fehlt. Als root: apt install -y python3-venv" >&2; exit 1
fi

if [ -d "${ZIEL}/.git" ]; then
    echo "-- Repo vorhanden, aktualisiere"
    git -C "${ZIEL}" pull --ff-only
else
    echo "-- Klone Repo"
    git clone "${REPO}" "${ZIEL}"
fi

cd "${ZIEL}"

if [ ! -x .venv/bin/python ]; then
    echo "-- Lege virtuelle Umgebung an"
    python3 -m venv .venv
fi
echo "-- Installiere Pakete"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    ENV_NEU=1
    echo "-- .env aus Vorlage angelegt"
else
    ENV_NEU=0
fi

echo "-- Hermes-Skill nach ${SKILL_DIR}"
mkdir -p "${SKILL_DIR}"
cp hermes-skill/SKILL.md "${SKILL_DIR}/SKILL.md"

echo "-- Selbsttest (Marktguru-Abfrage)"
if .venv/bin/python cli.py suche Gefrierbeutel --anzahl 5; then
    echo "-- Selbsttest ok"
else
    echo "!! Selbsttest fehlgeschlagen, Ausgabe oben an Claude schicken"
fi
echo "-- Händler laut Marktguru:"
.venv/bin/python cli.py haendler Gefrierbeutel || true

# systemd-Unit mit dem echten Pfad/User erzeugen
sed -e "s#/home/moltbook/angebots-bot#${ZIEL}#g" -e "s#User=moltbook#User=$(id -un)#" \
    systemd/angebots-bot.service > angebots-bot.service.lokal

echo
echo "================ FERTIG (User-Teil) ================"
if [ "${ENV_NEU}" = "1" ] || ! grep -q '^DISCORD_TOKEN=.\+' .env; then
    echo "1. Token & IDs eintragen:  nano ${ZIEL}/.env"
    echo "   (DISCORD_TOKEN, GUILD_ID, CLI_USER_ID)"
fi
echo "2. Einmalig als root den Dienst einrichten:"
echo "   sudo cp ${ZIEL}/angebots-bot.service.lokal /etc/systemd/system/angebots-bot.service"
echo "   sudo systemctl daemon-reload && sudo systemctl enable --now angebots-bot"
echo "   journalctl -u angebots-bot -f"
echo "Bei späteren Updates: bash ${ZIEL}/install.sh && sudo systemctl restart angebots-bot"
