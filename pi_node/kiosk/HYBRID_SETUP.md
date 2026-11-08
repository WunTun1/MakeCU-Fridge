# Hybrid setup: Pi + direct Ethernet to the backend computer

This Pi has one Ethernet port, normally used for internet. Moving that
same cable to a direct link into the backend computer means the Pi loses
internet access — so install everything on the Pi *before* unplugging.

## On the Pi, while it still has internet

```
cd ~/MakeCU-Fridge
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r pi_node/requirements.txt
cp pi_node/.env.example pi_node/.env   # if not already done
```

`--system-site-packages` reuses the apt-installed `RPi.GPIO`, `smbus2`, and
`numpy` so they don't need to build from source.

Edit `pi_node/.env`:
- `HX711_PINS` — one `DT:SCK` pair per shelf actually wired (e.g. `16:17`
  for a single load cell on Grove port D16).
- `BACKEND_URL` — the backend computer's address, e.g.
  `http://<computer-hostname>.local:8000`. The Pi's own hostname is
  `raspberrypi`, and `avahi-daemon` (mDNS) is already running, which is why
  the project defaults to `raspberrypi.local` for the reverse direction.

## After plugging the Ethernet directly into the backend computer

1. Give it ~30–60s. With no DHCP server on the direct link, NetworkManager
   falls back to a self-assigned link-local address (169.254.x.x)
   automatically.
2. From the backend computer, try `ping raspberrypi.local`. Direct Ethernet
   links still carry multicast, so mDNS (`.local` names) generally still
   resolves with no extra config (native on Mac/Linux; Windows 10/11 usually
   works too).
3. If that ping fails, fall back to static IPs on both ends instead (same
   subnet, e.g. Pi `10.0.0.1/24`, computer `10.0.0.2/24`), and use the IP
   instead of the hostname everywhere below.
4. Fill in the configs:
   - Pi's `pi_node/.env`: `BACKEND_URL=http://<computer-hostname>.local:8000`
   - Backend computer's root `.env`: `SCALE_SOURCE=network`,
     `PI_AGENT_URL=http://raspberrypi.local:8001` (already the default).

## Running it

On the Pi — just the sensor/camera agent, nothing backend-related:

```
cd ~/MakeCU-Fridge
.venv/bin/python -m pi_node.agent
```

On the backend computer:

```
python main.py
```

Then open `http://<computer-hostname-or-ip>:8000/kiosk` in a browser on
either machine — that's local traffic over the direct link, no internet
needed.
