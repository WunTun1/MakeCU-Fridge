#!/usr/bin/env bash
# Full-screen fridge UI on the Pi's touchscreen. Launched at login by labwc
# (see install.sh). Waits for the backend, then opens /kiosk.
set -u

PI_NODE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# KIOSK_BACKEND is set by install.sh --all-in-one (backend on this Pi); otherwise use pi_node/.env.
BACKEND_URL="${KIOSK_BACKEND:-$(grep -E '^BACKEND_URL=' "$PI_NODE_DIR/.env" 2>/dev/null | cut -d= -f2-)}"
BACKEND_URL="${BACKEND_URL:-http://192.168.1.50:8000}"

# The backend may boot after the Pi; don't show an error page in the meantime.
until curl -sf "$BACKEND_URL/api/health" >/dev/null; do sleep 3; done

BROWSER="$(command -v chromium-browser || command -v chromium)"
exec "$BROWSER" \
  --kiosk "$BACKEND_URL/kiosk" \
  --ozone-platform=wayland \
  --touch-events=enabled \
  --noerrdialogs --disable-infobars --no-first-run \
  --disable-session-crashed-bubble \
  --disable-pinch --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000
