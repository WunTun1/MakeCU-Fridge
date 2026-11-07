#!/usr/bin/env bash
# One-time Pi setup: run the sensor agent at boot, and open the fridge UI
# full-screen on the touchscreen at login. Run from the repo on the Pi:
#   bash pi_node/kiosk/install.sh
# Assumes Raspberry Pi OS (Bookworm or later) with the desktop, auto-login
# enabled (raspi-config > System > Auto Login), and pi_node/.env filled in.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
KIOSK="$REPO/pi_node/kiosk/start-kiosk.sh"
PYTHON="$REPO/.venv/bin/python"

[ -f "$REPO/pi_node/.env" ] || { echo "Create pi_node/.env first (copy pi_node/.env.example)"; exit 1; }
[ -x "$PYTHON" ] || { echo "Create the venv first: python -m venv .venv && .venv/bin/pip install -r pi_node/requirements.txt"; exit 1; }
chmod +x "$KIOSK"

# 1. Sensor agent as a systemd service (starts at boot, restarts on crash).
sudo tee /etc/systemd/system/refridge-pi.service >/dev/null <<EOF
[Unit]
Description=ReFridge Pi sensor agent
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$REPO
ExecStart=$PYTHON -m pi_node.agent
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now refridge-pi.service

# 2. Fridge UI at desktop login (labwc is Raspberry Pi OS's Wayland compositor).
mkdir -p "$HOME/.config/labwc"
AUTOSTART="$HOME/.config/labwc/autostart"
grep -qF "$KIOSK" "$AUTOSTART" 2>/dev/null || echo "$KIOSK &" >> "$AUTOSTART"

# 3. Keep the screen on, and enable I2C for the barometer.
sudo raspi-config nonint do_blanking 1
sudo raspi-config nonint do_i2c 0

echo "Done. Agent status: sudo systemctl status refridge-pi   |   Reboot to start the fridge screen."
