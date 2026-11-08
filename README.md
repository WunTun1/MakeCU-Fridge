# ReFridge

A smart fridge that knows what's inside, how much is left, how fast you use it,
when it goes bad, what to buy next — and what to cook. The fridge's touchscreen
shows what's inside and when it expires; in the phone app, say "I'm feeling
Italian and need more protein" and it suggests **real recipes** ranked by what
you have, what's about to expire, your goals, and what it has learned you like.

## How it fits together

```
 Raspberry Pi (in the fridge)                 Computer — or the same Pi ("all-in-one")
 ───────────────────────────                  ──────────────────────────────────────────
 HX711 load cells  ─┐                         main.py
 Grove micro switch ─┤  pi_node/agent.py ──►   FastAPI  /api/pi/*  (weights, door, conditions)
 Grove barometer    ─┤   pushes over HTTP      fridge loop: hand trips → vision → fusion
 Grove light sensor ─┘                         Gemini (item naming, recipe chat) — in the cloud
 USB webcam  ── GET /frame.jpg ◄─────────────  SQLite: inventory, taste profile, recipe library
 7" touchscreen ── Chromium /kiosk ◄─────────  serves the Expo web build
                                                     ▲
                              Phone: Expo app ───────┘
```

The Pi reads sensors and the camera. Vision, the database, and the recipe
engine run in `main.py`, on a computer (hybrid) or on the Pi itself
(all-in-one — fine on a Pi 4/5; the AI runs on Google's servers either way).
For testing on one machine, a **simulated Pi** stands in for the hardware over
the exact same HTTP calls.

## Test everything on your computer

```bash
python -m venv .venv
.venv\Scripts\activate                # Windows   (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
cp .env.example .env                  # add GEMINI_API_KEY for AI; everything has a no-key fallback

cd mobile && npm install && npx expo export --platform web && cd ..   # builds the fridge screen
python -m recipes.build               # optional: full ~230k-recipe library (one ~900 MB download, ~2 min)

.venv\Scripts\python run_local.py --seed       # --seed loads 3 weeks of demo history
.venv\Scripts\python run_local.py --camera "USB Camera"   # a real camera, by name (see --list-cameras)
```

Always run with the project's `.venv` Python — other Pythons may be missing packages.

| Open | What |
|---|---|
| **Simulated fridge** — http://127.0.0.1:8001 | Open the door, put items in, pour some out, take them out. With `--camera`, press "Put in" then place a real item in view. |
| **Fridge screen** — http://127.0.0.1:8000/kiosk | Touch-only display (best at 1024×600): what's in the fridge, how much, and when it goes bad — soonest first. Tap an item for details. |
| **Phone app** — `cd mobile && npx expo start` | Everything else: recipe chat, "Cook tonight" ideas, grocery list, profile. Scan the QR code with Expo Go (same Wi-Fi; on iPhone, sign in to the same Expo account with `npx expo login`), or press `w` for a browser. |

Use `127.0.0.1` rather than `localhost` — on Windows, `localhost` adds ~0.2 s to every request.

## How the camera sees a trip

1. **Door opens** → wait for a few steady frames, then take the *before* photo.
2. **Someone reaches in** — MediaPipe finds hands (21-joint skeleton) and people
   (selfie segmentation) in ~45 ms a frame. Shadows, exposure changes and the items
   themselves don't count as a hand. Needs 2 frames in a row to start a trip.
3. **Hand gone for 0.6 s** → take **one** *after* photo (median of the last steady
   frames), weigh every shelf, and compare.
4. **Compare** — exposure/white balance are matched first, then colors are compared in
   LAB with a noise-adaptive threshold, so only the item that moved shows up.
5. **New item** → that crop goes to Gemini (`--identify`; off by default while testing,
   when the crop is saved to `data/snapshots/` instead and the fridge screen asks "what is this?").

The simulated fridge window shows it live: orange outline + white skeleton = person and
hands, cyan = what changed, green flash = the photo that goes to Gemini. The two models
(~10 MB) download to `data/models/` on first run; without them it falls back to motion
detection (`HAND_DETECTOR=motion`, also used for the simulator's cartoon hand).

## Recipes, swaps, and learning your taste

- **Library** — real Food.com recipes in a local SQLite full-text index (`recipes/`).
  Without the full build, a bundled 3,000-recipe starter set loads automatically.
- **Chat** — Gemini turns requests into searches but may only suggest recipes the
  library returns; it never invents one. Results are ranked in plain code by
  ingredients you have, expiring items, protein goals, and taste. **Allergies are a
  hard filter** in code.
- **Swaps** — missing basil but have parsley? Similar-ingredient groups
  (`recipes/substitutions.py`) propose swaps with a cooking note and rewrite the steps.
- **Taste profile** — cooking a recipe, thumbs up/down, what you ask for, and what
  you buy all feed it, fading over ~30 days (`intelligence/taste.py`).
- **Grocery "unlock" suggestions** — the purchases that complete the most recipes
  you'd likely enjoy, alongside the usual "running low" restock list.
- **Expiry** — printed dates (read by Gemini) beat estimates; estimates are always
  labeled "(est.)" (`intelligence/expiry.py`).

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

2. **On the Pi** — pick a mode:
   ```bash
   # all-in-one (recommended for the demo): this Pi runs everything
   python -m venv .venv && .venv/bin/pip install -r requirements.txt -r pi_node/requirements.txt
   cp pi_node/.env.example pi_node/.env && cp .env.example .env    # put GEMINI_API_KEY in .env
   bash pi_node/kiosk/install.sh --all-in-one

   # hybrid: a computer runs main.py; the Pi only reads sensors + shows the screen
   python -m venv .venv && .venv/bin/pip install -r pi_node/requirements.txt
   cp pi_node/.env.example pi_node/.env      # set BACKEND_URL to the computer's IP
   bash pi_node/kiosk/install.sh
   ```
   Or, without installing services, run it by hand on the Pi — one command connects to the
   backend, runs the sensors and camera, and opens the fridge screen:
   `python3 ~/MakeCU-Fridge/pi_node/run.py`. Direct Ethernet between the Pi and the
   computer: see `pi_node/kiosk/HYBRID_SETUP.md`.
   Then calibrate each shelf inside the cold fridge:
   `.venv/bin/python -m pi_node.calibrate tare 0` (empty), then `cal 0 500` (with a 500 g weight).
   Pi 5: use `rpi-lgpio` instead of `RPi.GPIO`. Copy `data/recipes.db` from your computer
   for the full recipe library.

3. **Hybrid only — on the computer**, in `.env`: `SCALE_SOURCE=network`,
   `PI_AGENT_URL=http://<pi-ip>:8001`, `ENABLE_FRIDGE_LOOP=true`, then `python main.py`.

Once the camera is mounted, set `SHELF_BANDS` in `.env` to where each shelf appears in the image.

## Layout

| Path | What |
|---|---|
| `main.py` | Backend entry: API server + fridge loop (hand trips → vision → fusion) |
| `run_local.py` | Backend + simulated Pi together, for testing on one computer |
| `recipes/` | Recipe library (build, search), ingredient matching, swaps, ranking engine |
| `pi_node/` | Runs on the Pi: hardware drivers, sensor push agent, camera server, simulator, kiosk setup |
| `mobile/` | Expo app — phone screens, plus `/kiosk` for the fridge touchscreen |
| `api/` `inventory/` `intelligence/` `nutrition/` `vision/` `fusion/` `sensors/` | Backend modules |
| `software/` | Max's two-camera GPT capture experiment (own `requirements.txt`; uses OpenCV windows, so keep it in its own environment) |
| `firmware/scale_esp32/` | Legacy ESP32 load-cell firmware (`SCALE_SOURCE=serial`); unused with the Pi |

## Tests

```bash
pytest                          # backend, recipes, taste, expiry, Pi driver math (vs. Bosch datasheets)
cd mobile && npx tsc --noEmit && npx expo lint
```
