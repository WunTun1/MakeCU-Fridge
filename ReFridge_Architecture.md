# ReFridge — Full System Architecture

A smart fridge that knows what's inside, how much is left, how fast you use it, what to buy next, and what you can cook to hit your nutrition goals.

**Core principle:** use cheap, reliable, non-AI tools for everything they can do, and use AI only where it's actually needed.

| Job | Done by | AI? |
|---|---|---|
| *How much* changed | Load cells under each shelf | No |
| *Where* it changed and *which* item | Camera + OpenCV + tracking | No |
| *When* to measure | Door switch + hand detection | No |
| *What* a brand-new item is | Vision AI model | **Yes** (only for new items) |
| Usage forecasting, low alerts, grocery planning | Plain Python math | No |
| Nutrition numbers | USDA / Open Food Facts database + code | No |
| Conversation and recipe ideas | Chatbot AI model with tools | **Yes** |

---

## 1. Overall system

```text
                         ┌──────────── FRIDGE ────────────┐
Door switch ─┐           │                                │
Load cells ──┼─> ESP32 ──┤  Hand detection (OpenCV)       │
             │   (USB)   │  Change detection (OpenCV)     │
Webcam ──────┴──────────>│  Tracking (match known items)  │
                         │  Fusion (weight + camera)      │
                         │  AI naming (new items only)    │
                         └───────────────┬────────────────┘
                                         │ events: add / remove / consume / move / needs_review
                                         v
Manual entry (pantry, ──────────>  SQLite database  <────────── Meal log (chatbot / "I made this")
barcode, chatbot)                        │
                                         v
                         Intelligence layer (plain Python)
                         usage rates · days left · low alerts
                         grocery plan · nutrition totals
                                         │
                                         v
                         FastAPI backend  <──>  Nutritionist chatbot (AI + tools)
                                         │
                                         v
                         Web app (phone-friendly)
                         inventory · search · alerts · grocery list · chat
```

---

## 2. When the fridge measures: door + hand "trips"

The fridge measures **once per hand trip**, not continuously and not only at door close.

1. **Door opens** → save a reference photo and the settled weight of every shelf.
2. **Hand enters** the camera view → wait. Ignore weights (hands touch shelves).
3. **Hand leaves** the frame and no motion for ~0.5 s → wait for the scale to settle, then:
   - weigh every shelf,
   - take a new photo,
   - compare against the previous reference → this trip's changes,
   - run fusion (section 6) → write events,
   - the new photo + weights become the reference for the next trip.
4. Repeat for every trip while the door is open.
5. **Door closes** → one final measurement as a safety check.

Putting in milk, then yogurt = two trips = two clean, separate measurements. No weight-splitting needed.

### Hand detection (OpenCV)

You don't need to recognize a hand exactly, just *motion in front of the shelves*.

- **Default:** `cv2.createBackgroundSubtractorMOG2()` learns the still fridge. A large moving foreground blob = hand present. "Hand gone" = no significant foreground for ~0.5 s.
- **Upgrade if shadows or the door light cause false triggers:** MediaPipe Hands (free, runs alongside OpenCV, actually detects hands).
- **Camera placement:** top of the fridge, looking down and slightly outward, so it sees the front edge of every shelf where hands enter.

### Edge cases

| Situation | Handling |
|---|---|
| Two items carried in one trip | One combined weight for two new items → section 6b |
| Hand never fully leaves (rummaging) | Keep waiting; door close always forces a final measurement |
| Items rearranged inside the fridge | Weight ≈ unchanged, item at new spot → `move` |
| Door light flicker on open | Let the background model re-learn for ~1 s after the door opens |

---

## 3. Load cell hardware

```text
 Shelf platform (rigid board: acrylic / plywood)
 ─────────────────────────────────────────────
        ▲ bar load cell (5 kg or 10 kg), cantilever-mounted with spacers
 ─────────────────────────────────────────────
 Fridge wire shelf

 Load cell ──> HX711 amp ──> ESP32 ──USB serial──> laptop / Pi
 Door switch (reed / microswitch) ──────> ESP32
```

- **One bar load cell + HX711 per shelf.** Bar cells are much easier to mount than bathroom-scale half-bridge cells.
- The platform must rest only on the load cell, touching nothing else. Rubbing against walls loses weight.
- **Set the HX711 to 80 samples/sec** (RATE pin high) so readings settle quickly after a hand leaves.
- The ESP32 also reads the door switch and can later drive the retrieval motors. Tag every serial message with a type (`{"t":"w",...}`, `{"t":"door",...}`) so streams don't collide.
- **Optional upgrade:** 4 load cells per shelf (one per corner) → the shift in the shelf's balance point tells you *where* weight was added (see 6b).

**Calibration (do it inside the cold fridge, because load cells drift with temperature):**
1. Empty shelf → `tare <shelf>`.
2. Place a known weight (e.g. a water bottle weighed on a kitchen scale) → `cal <shelf> <grams>`.
3. Saved in ESP32 flash. Re-tare occasionally when the shelf is empty to cancel slow drift.

**Noise handling (host side):** a shelf is "settled" when its recent readings vary by less than ~3 g; use the **median** to ignore spikes. Treat changes under ~15 g (or 10%) as noise.

---

## 4. Camera change detection (OpenCV)

Compare the previous reference photo with the new one:

```python
diff = cv2.absdiff(before, after)
gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
blur = cv2.GaussianBlur(gray, (5, 5), 0)
_, mask = cv2.threshold(blur, 30, 255, cv2.THRESH_BINARY)
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
```

Each contour is a **changed region**, not necessarily one object. A moved item can create two regions (where it was, where it is now). Keep framing and lighting consistent and filter out tiny contours.

---

## 5. Tracking known items

Every item has a persistent ID:

```json
{
  "item_id": 17,
  "name": "Milk",
  "shelf": 0,
  "bbox": [120, 80, 75, 160],
  "position": [0.42, 0.31],
  "weight_g": 650,
  "last_seen": "2026-11-07T11:00:00",
  "confidence": 0.96
}
```

On each new photo:
- Match current regions to known items by bounding-box overlap (IoU), center distance, size, and color histogram. The Hungarian algorithm gives the best one-to-one matching.
- Item gone → candidate removal (confirmed by weight).
- Item at a new spot → move.
- New unmatched region → new item → send to AI for naming.

**Limit:** one camera can't tell identical products apart if they swap, or see fully hidden items. Treat identical units as interchangeable; the scale catches hidden ones.

---

## 6. Fusion: weight + camera → events

Runs once per hand trip, per shelf. The scale says **how much**, the camera says **where / which**.

| Weight change | Camera saw | Meaning | Event |
|---|---|---|---|
| ≈ 0 | nothing | nothing happened | — |
| ≈ 0 | item gone + new region nearby | item moved / put back differently | `move` |
| ≈ 0 | some change | shadow / lighting | `needs_review` or ignore |
| − matches removed item(s) | item(s) gone | taken out | `remove` |
| − matches a subset of vanished items | several gone | some only hidden | `remove` (best-matching subset) |
| − | nothing gone | **used some** (poured milk, took 2 eggs) → assign to the only visible item heavy enough | `consume` |
| + | one new region | new item, weight = measured change | `add` → AI names it |
| + | several new regions | combined weight, split needed | section 6b |
| + | nothing new visible | placed behind something | `restock_hidden` → ask user |
| mixed | item gone + new region | swap: new weight = change + removed weight | `remove` + `add` |

Anything that doesn't add up → `needs_review` → the app asks the user instead of guessing.

**Returned items:** if an item that was removed earlier comes back (tracker recognizes it), log `return` so the round trip doesn't count as eating it.

### 6b. Several new items, one combined weight

Rare with per-trip measuring, but it happens (two items in one hand). Handle in this order:

1. **Different shelves** → each shelf's scale measures its own item. Solved.
2. **Typical package weights** → AI names both items ("milk carton" ≈ 1,050 g, "yogurt tub" ≈ 500 g). If they sum close to the measured total, split that way.
3. **4-corner load cells (optional hardware)** → two equations, two unknowns:
   `w₁ + w₂ = total` and `w₁·x₁ + w₂·x₂ = total · x_balance`, where x₁, x₂ come from the camera.
4. **Ask the user** → "You added milk and yogurt, ~950 g total. Does this split look right?"
5. **Self-correct later** → when one item is removed, its exact weight is measured, which fixes both.

---

## 7. AI identification (new items only)

Called only when a region can't be matched to a known item.

**Input:** cropped photo of the item, the full shelf photo for context, and the measured weight (helps tell a full tub from an empty one).

```json
{
  "item_name": "Baby Spinach",
  "category": "Leafy Greens",
  "visible_expiration_date": null,
  "confidence": 0.92
}
```

Quantity comes from the scale, not the AI. Don't let the model invent expiration dates it can't read. Low confidence → ask the user to confirm the name.

---

## 8. Data model (SQLite)

| Table | What it holds |
|---|---|
| `products` | A kind of food: name, category, usual package size, staple yes/no, nutrition per 100 g |
| `items` | A physical unit: product, **location** (fridge / pantry / freezer), shelf, position, current grams, added date, expiration date |
| `events` | Every change: add / remove / consume / move / return / waste / needs_review, with grams, time, and a resolved flag |
| `meals` | What the user ate: time, recipe or food, servings, computed nutrition |
| `profile` | Goals (protein, calories, presets), diet type, allergies, dislikes |
| `chat_memory` | Recent conversation and a short summary of preferences |

**Log every event from day one.** All forecasting is built from the event history.

---

## 9. Pantry and manual items

Things that aren't in the fridge (rice, pasta, cans, spices, bread) are first-class items with `location = pantry` or `freezer`.

**Adding:**
- Type it: "rice, 2 kg". Nutrition is looked up automatically.
- Scan the barcode with the phone camera → Open Food Facts fills in name, size, nutrition.
- Tell the chatbot: "I bought rice and two cans of chickpeas."
- *Stretch:* photo of a grocery receipt → add everything at once.

**Keeping amounts current (no sensors):**
- "I made this" on a recipe subtracts the pantry ingredients used.
- Quick buttons: used some / used half / finished.
- Chatbot: "I used the last of the rice."
- Occasional check-in: "Still have rice?" for items untouched in a while.

Pantry forecasts are labeled **estimated**; fridge forecasts are **measured**.

---

## 10. Intelligence layer (plain Python, no AI)

**Daily usage per product** = grams consumed + removed − returned, per day. Waste is logged separately so spoiled food doesn't count as eating.

**Usage rate** = weighted average of daily usage where recent days count more (exponential decay, e.g. half-life of 7 days). Adapts when habits change; easy to explain.

**Days left** = grams on hand ÷ daily rate.

**Low-stock alert** when any of:
- days left ≤ threshold (default 3),
- on hand < 20% of a package,
- a staple is out,
- an item expires within 2 days.

**Grocery plan:**
- **Next trip date** = earliest date a staple runs out, minus 1 day (none needed if nothing runs out within ~2 weeks).
- **How much to buy** = enough to last from the trip until the following trip plus a safety buffer, minus what will still be on hand at the trip, rounded up to whole packages.
- Don't suggest more of something likely to expire before it's used.

**Search:** match name and category, with typo tolerance (fuzzy matching). Answers in plain language: "You have about 800 g of milk, roughly 4 days left."

**Stage 2 (if time allows):** weekly patterns (Holt-Winters style seasonality), better handling of rarely-used foods (Croston's method), waste-aware buying.

---

## 11. Nutritionist chatbot

A normal conversation: "I'm feeling Italian today," "I need more protein," "something quick."

**The AI talks and suggests; code does the math and checks facts.** The chatbot is an AI model with **tool calling**:

| Tool | Returns / does |
|---|---|
| `get_inventory()` | Everything on hand (fridge + pantry), amounts, what's expiring |
| `get_goals()` | Protein / calorie targets, diet, allergies, dislikes |
| `get_intake(period)` | What the user has eaten today / this week |
| `check_recipe(ingredients_g)` | Backend computes real nutrition from the database and confirms stock is sufficient |
| `log_meal(recipe, servings)` | Records the meal, updates intake, subtracts pantry items |
| `add_item(...)` / `update_item(...)` | Manual pantry changes from chat |

**Flow:** the user asks → the AI proposes a recipe with ingredient grams → `check_recipe` validates nutrition and stock → if something fails (not enough chicken, contains an allergen), the AI adjusts → the user sees a recipe card with macros, "uses expiring: spinach," and an **I made this** button.

**Nutrition data:** USDA FoodData Central (free API) for general foods; Open Food Facts for packaged/barcoded products. Look up each product once and store it.

**Tracking what you ate:** fridge removals aren't the same as what *you* ate (shared meals, other people). So:
- Recipes: "I made this" → "How many servings did you eat?"
- Manual: "I had a yogurt" in chat.
- Other removals → optional prompt: "Chicken left the fridge — did you eat some?"

**Allergies are a hard filter in code**, never left to the AI's judgment.

**Responsible design:** label it as general wellness info, not medical advice; suggest a doctor or dietitian for medical conditions; keep goals in healthy ranges; never shame the user about food.

---

## 12. App

Phone-friendly web app served by the FastAPI backend. Polls for updates every few seconds (WebSockets optional).

| Screen | Contents |
|---|---|
| **Home** | Alerts (out / low / expiring / needs review) → next trip suggestion → today's nutrition progress → inventory grid with fill bars and days left |
| **Search** | Plain-language answers, fridge + pantry |
| **Item detail** | 4-week usage chart, amount, expiry, location/shelf, *Retrieve* button (robot) |
| **Grocery list** | Suggested trip date (adjustable), items + packages, check off while shopping |
| **Chat** | Nutritionist chatbot with recipe cards and *I made this* |
| **Add item** | Type, barcode scan, or location picker for pantry/freezer |
| **Review queue** | One-tap answers for uncertain fridge events |
| **Profile** | Goals, diet, allergies |

### API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/events` | Fridge pipeline sends events |
| `GET /api/summary` | Everything the home screen needs |
| `GET /api/search?q=` | Search answers |
| `GET /api/products/{id}/usage` | Usage chart data |
| `GET /api/grocery?trip_in_days=` | Grocery plan |
| `GET /api/review`, `POST /api/review/{id}` | Review queue |
| `POST /api/items`, `/consume`, `/remove` | Manual edits, pantry, demo controls |
| `POST /api/barcode` | Look up a scanned barcode |
| `GET/PUT /api/profile` | Goals and diet |
| `POST /api/chat` | Chatbot message → reply (+ recipe cards) |
| `POST /api/meals` | Log a meal |

---

## 13. Robotic retrieval (stretch)

Convert camera pixels to physical shelf coordinates with a 4-point calibration (homography). Use the item's base, not its visual center, for tall objects.

```json
{ "command": "retrieve", "item_id": 17, "target_x_mm": 185, "target_y_mm": 240 }
```

The ESP32 converts this to motor movement using calibration and limit switches. Check the path for obstacles first. Verify success with **both** the camera (item gone) and the scale (shelf lost ~item's weight).

---

## 14. Repository structure

```text
refridge/
├── main.py                    # Runs the fridge loop + API server
├── firmware/
│   └── scale_esp32/           # ESP32: HX711 load cells + door switch (+ motors later)
├── vision/
│   ├── camera.py              # Webcam capture
│   ├── hands.py               # Hand / motion detection → trip start/end
│   ├── change.py              # Before/after comparison
│   ├── tracking.py            # Match known items
│   ├── classifier.py          # AI naming for new items
│   └── calibration.py         # Pixels → shelf coordinates
├── sensors/
│   └── scale.py               # Load-cell reader, settling filter
├── fusion/
│   └── reconcile.py           # Weight + camera → events
├── inventory/
│   ├── database.py            # SQLite schema + queries
│   └── events.py              # Apply events, returns, waste
├── intelligence/
│   ├── consumption.py         # Usage rates, days left
│   ├── alerts.py              # Low / out / expiring
│   ├── grocery.py             # Trip date + shopping list
│   └── search.py              # Fuzzy search + plain-language answers
├── nutrition/
│   ├── lookup.py              # USDA + Open Food Facts
│   ├── intake.py              # Meal log + daily totals
│   └── chatbot.py             # AI model + tools
├── hardware/
│   ├── controller.py          # ESP32 serial (motors)
│   └── planner.py             # Safe retrieval planning
├── api/
│   └── server.py              # FastAPI endpoints
├── web/                       # Phone-friendly app
├── scripts/
│   └── seed_demo.py           # Fake weeks of realistic history
└── tests/
```

**Already written** (starter zip): `firmware/scale_esp32`, `sensors/scale.py`, `fusion/reconcile.py` with tests. **To add:** the main loop should call `scale.wait_until_stable()` each time `hands.py` reports a hand has left (not only on door close), and run `reconcile()` once per trip.

---

## 15. Build order (24 hours, 3 people)

| Hours | Hardware | Backend / AI | Frontend |
|---|---|---|---|
| 0–3 | Load cell + HX711 + ESP32 streaming; door switch | Database tables, event logging, `POST /api/events` | App skeleton, home layout |
| 3–6 | Mount shelf platform, calibrate cold | **Demo seeder** (weeks of fake history) | Inventory grid, search |
| 6–10 | Webcam mount, change detection | Usage rates, alerts, grocery plan, search | Item detail + usage chart, grocery list |
| 10–14 | Hand detection → per-trip measuring; tracking | Nutrition lookup, profile, chatbot + tools | Chat screen, recipe cards, add-item / barcode |
| 14–18 | Fusion wired to real events; AI naming | Meal log, pantry updates from recipes | Review queue, nutrition progress |
| 18–21 | **Everyone:** connect it all end to end, fix bugs | | |
| 21–24 | **Everyone:** freeze features, rehearse demo | | |

**If hardware breaks on demo day:** the app runs on seeded data, and manual add/consume buttons can simulate fridge events.

---

## 16. Demo script

1. Show the home screen: inventory, a low-stock alert, a suggested grocery trip.
2. Put two items in the fridge one at a time → each appears in the app with its measured weight.
3. Tell the chatbot: "I'm feeling Italian and need more protein."
4. It suggests a pasta with ~50 g protein that uses the spinach expiring tomorrow.
5. Tap **I made this** and take the ingredients out of the fridge.
6. The fridge sees them leave → inventory drops → protein for the day goes up → spinach lands on the grocery list.

---

## 17. Open decisions

1. Which AI model/provider (needs tool calling and vision) and API key.
2. Recipes generated fresh by the AI, or adapted from a recipe database?
3. Goals as simple presets or custom numbers?
4. One user or a household?
5. Motion detection or MediaPipe Hands for hand tracking?
