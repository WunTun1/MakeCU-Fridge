# ReFridge

A smart fridge that knows what's inside, how much is left, how fast you use it,
what to buy next, and what you can cook to hit your nutrition goals.

## How it fits together

```
 Raspberry Pi (in the fridge)                 Computer (the compute)
 ───────────────────────────                  ──────────────────────────────────────
 HX711 load cells  ─┐                         main.py
 Grove micro switch ─┤  pi_node/agent.py ──►   FastAPI  /api/pi/*  (weights, door, conditions)
 Grove barometer    ─┤   pushes over Wi-Fi     fridge loop: hand trips → vision → fusion
 Grove light sensor ─┘                         Gemini (item naming + nutrition chat)
 USB webcam  ── GET /frame.jpg ◄─────────────  SQLite, forecasting, grocery plan
 7" touchscreen ── Chromium /kiosk ◄─────────  serves the Expo web build
                                                     ▲
                              Phone: Expo app ───────┘
```

The Pi only reads sensors and the camera; all OpenCV, AI, and storage run on
the computer. For testing on one machine, a **simulated Pi** stands in for
the hardware and talks to the backend over the exact same HTTP calls.

## Test everything on your computer

```bash
python -m venv .venv
.venv\Scripts\activate                # Windows   (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
cp .env.example .env                  # add GEMINI_API_KEY to enable AI; optional

cd mobile && npm install && npx expo export --platform web && cd ..   # builds the fridge screen

python run_local.py --seed            # --seed loads 3 weeks of demo history
```

Then open:

| | |
|---|---|
| **Simulated fridge** — http://localhost:8001 | Open the door, put items in, pour some out, take them out. A hand reaches in on the camera feed and the weight changes, just like the real thing. |
| **Fridge screen** — http://localhost:8000/kiosk | The touchscreen UI. Size the window to 1024×600 to see it as it'll look on the door. |
| **Phone app** — `cd mobile && npx expo start` | Scan the QR code with Expo Go (phone on the same Wi-Fi), or press `w` for a browser. |

Without a Gemini key, new items can't be named automatically — the fridge
screen asks "what is it?" with one-tap answers instead. `--webcam` swaps the
synthetic camera for your laptop's webcam.

## Moving to the real Pi

No code changes — just configuration.

1. **Wire it** (Grove Base Hat on the Pi):

   | Part | Connect to | Setting in `pi_node/.env` |
   |---|---|---|
   | HX711 load-cell amp, shelf 0 / 1 | Grove ports D16 / D18 (DT, SCK = GPIO n, n+1) | `HX711_PINS=16:17,18:19` |
   | Grove Micro Switch v1.0 (door) | D5 | `DOOR_SWITCH_PIN=5` |
   | Grove Light Sensor v1.2 | A0 | `LIGHT_ADC_CHANNEL=0` |
   | Grove barometer (BMP280/BME280/BMP180, auto-detected) | any I2C port | — |
   | USB webcam, top of fridge looking down | USB | `CAMERA_INDEX=0` |
   | 7" HDMI touchscreen | HDMI + USB (touch) | — |

   Tie each HX711's RATE pin high (80 samples/s) so readings settle quickly.

2. **On the Pi:**
   ```bash
   python -m venv .venv && .venv/bin/pip install -r pi_node/requirements.txt   # Pi 5: rpi-lgpio instead of RPi.GPIO
   cp pi_node/.env.example pi_node/.env      # set BACKEND_URL to the computer's IP
   .venv/bin/python -m pi_node.calibrate tare 0        # empty shelf, inside the cold fridge
   .venv/bin/python -m pi_node.calibrate cal 0 500     # with a known 500 g weight
   bash pi_node/kiosk/install.sh             # agent at boot + fridge screen at login
   ```

3. **On the computer**, in `.env`: `SCALE_SOURCE=network`, `PI_AGENT_URL=http://<pi-ip>:8001`,
   `ENABLE_FRIDGE_LOOP=true`, then `python main.py`. Once the camera is mounted,
   set `SHELF_BANDS` to where each shelf appears in the image.

## Layout

| Path | What |
|---|---|
| `main.py` | Backend entry: API server + fridge loop (hand trips → vision → fusion) |
| `run_local.py` | Backend + simulated Pi together, for testing on one computer |
| `pi_node/` | Runs on the Pi: hardware drivers, sensor push agent, camera server, simulator, kiosk setup |
| `mobile/` | Expo app — phone screens, plus `/kiosk` for the fridge touchscreen |
| `api/` `inventory/` `intelligence/` `nutrition/` `vision/` `fusion/` `sensors/` | Backend modules |
| `firmware/scale_esp32/` | Legacy ESP32 load-cell firmware (`SCALE_SOURCE=serial`); unused with the Pi |

## Tests

```bash
pytest                          # backend + Pi driver math (checked against the Bosch datasheets)
cd mobile && npx tsc --noEmit && npx expo lint
```
