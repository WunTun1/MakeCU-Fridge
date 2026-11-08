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
- `PI_HARDWARE=real`
- `BACKEND_URL` — the backend computer's IPv4 address on the cable (see the
  options below), e.g. `http://192.168.50.1:8000`.

## After plugging the Ethernet directly into the backend computer

Both ends need an **IPv4** address on the cable. Don't count on the automatic one:
with nothing handing out addresses, NetworkManager on the Pi doesn't fall back to
169.254.x.x by itself — tested on a Windows laptop, the Pi only got an IPv6
link-local address. `ping raspberrypi.local` still works (over IPv6), but the
backend and the Pi agent listen on IPv4 only (`0.0.0.0`), so they can't reach each
other that way. Pick one of these:

### Option A: fixed addresses (no internet sharing)

On the Pi:

```
sudo nmcli con add type ethernet ifname eth0 con-name direct ipv4.method manual ipv4.addresses 192.168.50.2/24
sudo nmcli con up direct
```

On the computer — Windows, PowerShell as administrator (`Get-NetAdapter` shows
the cable adapter's name; here it was "Ethernet 2"):

```
New-NetIPAddress -InterfaceAlias "Ethernet 2" -IPAddress 192.168.50.1 -PrefixLength 24
```

(Mac/Linux: give the cable interface `192.168.50.1/24` in network settings.)

Configs:
- Pi's `pi_node/.env`: `BACKEND_URL=http://192.168.50.1:8000`
- Computer's root `.env`: `SCALE_SOURCE=network`, `ENABLE_FRIDGE_LOOP=true`,
  `NUM_SHELVES=1`, `PI_AGENT_URL=http://192.168.50.2:8001`

The Pi has no internet on this link, so install first (above). To plug the Pi
back into a router later: `sudo nmcli con down direct` (and `up` to come back).

### Option B: share the computer's internet (nothing to run on the Pi)

On Windows: Win+R → `ncpa.cpl` → right-click **Wi-Fi** → Properties → Sharing →
tick "Allow other network users to connect…" → pick the cable adapter → OK.
The computer becomes `192.168.137.1` and hands the Pi an address in
`192.168.137.x` (its default wired profile asks for one); the Pi also gets
internet through the computer. Find the Pi's address from the computer with
`arp -a` (the `192.168.137.x` entry), or on the Pi with `hostname -I`.

Configs:
- Pi's `pi_node/.env`: `BACKEND_URL=http://192.168.137.1:8000`
- Computer's root `.env`: as in option A, with `PI_AGENT_URL=http://<pi's 192.168.137.x address>:8001`

Windows may turn sharing off after a reboot or a Wi-Fi change; re-tick it if the
Pi loses its address.

### Check the link

From the computer: `ping 192.168.50.2` (or the Pi's 192.168.137.x address).
Windows treats the cable as a "Public" network: the first time `main.py` starts,
allow Python through the firewall with **Public networks** ticked, or the Pi
can't reach the backend. From the Pi, `curl http://<computer-ip>:8000/api/health`
should answer once the backend is running.

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

Then open `http://<computer-ip>:8000/kiosk` in a browser on
either machine — that's local traffic over the direct link, no internet
needed.
