#!/usr/bin/env bash
# One-time Pi setup. Run from the repo on the Pi:
#
#   bash pi_node/kiosk/install.sh                # hybrid: a computer runs the backend (BACKEND_URL in pi_node/.env)
#   bash pi_node/kiosk/install.sh --all-in-one   # this Pi runs everything (backend + sensors + screen)
#
# Starts the sensor agent at boot (and the backend, all-in-one), and opens the fridge
# UI full-screen on the touchscreen at login. Assumes Raspberry Pi OS (Bookworm or
# later) with the desktop, auto-login enabled (raspi-config > System > Auto Login),
# and pi_node/.env filled in (copy pi_node/.env.example).
set -euo pipefail

MODE="hybrid"
[ "${1:-}" = "--all-in-one" ] && MODE="all-in-one"

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
KIOSK="$REPO/pi_node/kiosk/start-kiosk.sh"
PYTHON="$REPO/.venv/bin/python"

[ -f "$REPO/pi_node/.env" ] || { echo "Create pi_node/.env first (copy pi_node/.env.example)"; exit 1; }
if [ ! -x "$PYTHON" ]; then
  echo "Create the venv first:"
  if [ "$MODE" = "all-in-one" ]; then
    echo "  python -m venv .venv && .venv/bin/pip install -r requirements.txt -r pi_node/requirements.txt"
  else
    echo "  python -m venv .venv && .venv/bin/pip install -r pi_node/requirements.txt"
  fi
  exit 1
fi
chmod +x "$KIOSK"

service() {  # name, description, command, extra Environment= lines
  sudo tee "/etc/systemd/system/$1.service" >/dev/null <<EOF
[Unit]
Description=$2
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$REPO
ExecStart=$3
Restart=always
RestartSec=3
$4

[Install]
WantedBy=multi-user.target
EOF
}

# 1. Services: sensor agent always; backend too in all-in-one (both talk over localhost).
if [ "$MODE" = "all-in-one" ]; then
  service refridge-backend "ReFridge backend (API, vision, recipes)" "$PYTHON main.py" \
"Environment=SCALE_SOURCE=network
Environment=PI_AGENT_URL=http://localhost:8001
Environment=ENABLE_FRIDGE_LOOP=true"
  service refridge-pi "ReFridge Pi sensor agent" "$PYTHON -m pi_node.agent" \
    "Environment=BACKEND_URL=http://localhost:8000"
  KIOSK_LINE="KIOSK_BACKEND=http://localhost:8000 $KIOSK &"
  SERVICES="refridge-backend refridge-pi"
else
  service refridge-pi "ReFridge Pi sensor agent" "$PYTHON -m pi_node.agent" ""
  KIOSK_LINE="$KIOSK &"
  SERVICES="refridge-pi"
fi
sudo systemctl daemon-reload
sudo systemctl enable --now $SERVICES

# 2. Fridge UI at desktop login (labwc is Raspberry Pi OS's Wayland compositor).
mkdir -p "$HOME/.config/labwc"
AUTOSTART="$HOME/.config/labwc/autostart"
touch "$AUTOSTART"
grep -vF "$KIOSK" "$AUTOSTART" > "$AUTOSTART.tmp" || true   # replace any previous kiosk line
echo "$KIOSK_LINE" >> "$AUTOSTART.tmp"
mv "$AUTOSTART.tmp" "$AUTOSTART"

# 3. Keep the screen on, and enable I2C for the barometer.
sudo raspi-config nonint do_blanking 1
sudo raspi-config nonint do_i2c 0

echo "Done ($MODE). Status: sudo systemctl status $SERVICES   |   Reboot to start the fridge screen."
[ "$MODE" = "all-in-one" ] && [ ! -f "$REPO/data/recipes.db" ] && \
  echo "Tip: copy data/recipes.db from your computer for the full recipe library (the 3,000-recipe starter set is used until then)."
exit 0
