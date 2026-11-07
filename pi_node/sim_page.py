"""Control page for the simulated fridge (served at / by pi_node/server.py)."""

SIM_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulated Fridge</title>
<style>
  :root { --bg:#0f1115; --card:#1a1d24; --border:#2a2e37; --text:#e8e9ec; --muted:#9aa0ac; --accent:#4ade80; --danger:#f87171; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px system-ui, sans-serif; }
  main { max-width:1000px; margin:0 auto; padding:16px; display:grid; gap:16px; grid-template-columns:1fr; }
  @media (min-width:860px) { main { grid-template-columns: 1.3fr 1fr; } }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:14px; }
  h1 { font-size:18px; margin:0 0 4px; } h2 { font-size:15px; margin:0 0 10px; }
  .muted { color:var(--muted); font-size:13px; }
  img { width:100%; border-radius:8px; display:block; background:#000; }
  button { background:var(--accent); color:#06230f; border:0; border-radius:8px; padding:8px 12px; font-weight:600; cursor:pointer; }
  button.secondary { background:var(--border); color:var(--text); } button.danger { background:var(--danger); color:#210505; }
  input, select { background:#11131a; color:var(--text); border:1px solid var(--border); border-radius:8px; padding:8px; min-width:0; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  table { width:100%; border-collapse:collapse; } td { padding:6px 4px; border-top:1px solid var(--border); }
  .pill { padding:2px 8px; border-radius:99px; font-size:12px; background:var(--border); }
  .open { background:var(--accent); color:#06230f; }
</style></head>
<body><main>
  <section class="card">
    <h1>Simulated fridge</h1>
    <p class="muted">Stands in for the Raspberry Pi. Weights, door, and sensor readings are pushed to the backend
      exactly like the real Pi will.</p>
    <img id="cam" alt="Fridge camera">
    <p class="muted" id="camlabel" style="margin:6px 0 0"></p>
    <div class="row" style="margin-top:10px">
      <span>Door: <span id="door" class="pill">?</span></span>
      <button onclick="door(true)">Open</button>
      <button class="secondary" onclick="door(false)">Close</button>
      <span id="busy" class="muted"></span>
    </div>
  </section>

  <section style="display:grid; gap:16px; align-content:start">
    <div class="card">
      <h2>Put something in</h2>
      <div class="row">
        <input id="name" placeholder="Milk" style="flex:2">
        <input id="grams" type="number" placeholder="grams" value="1000" style="width:90px">
        <select id="shelf"></select>
        <button onclick="place()">Put in</button>
      </div>
      <div class="row" style="margin-top:8px" id="presets"></div>
      <p class="muted">Opens the door if it's closed, then a hand reaches in. Close the door when you're done.</p>
    </div>

    <div class="card">
      <h2>In the fridge</h2>
      <table id="items"></table>
    </div>

    <div class="card">
      <h2>Sensors</h2>
      <div id="weights" class="muted"></div>
      <div id="conds" class="muted" style="margin-top:6px"></div>
      <div class="row" style="margin-top:8px">
        <button class="secondary" onclick="temp(9)">Fridge too warm (9&deg;C)</button>
        <button class="secondary" onclick="temp(null)">Back to normal</button>
      </div>
    </div>
  </section>
</main>
<script>
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const PRESETS = [["Milk",1000],["Eggs",600],["Greek Yogurt",500],["Baby Spinach",150],["Chicken Breast",700]];
const post = (url, body) => fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body||{})}).then(r => r.ok ? r.json() : r.json().then(e => alert(e.detail)));
const door = open => post("/sim/door", {open}).then(render);
const temp = t => post("/sim/temperature", {temperature_c: t}).then(render);
const place = () => {
  const name = document.getElementById("name").value.trim() || "Item";
  post("/sim/place", {name, grams: +document.getElementById("grams").value || 500, shelf: +document.getElementById("shelf").value}).then(render);
};
document.getElementById("presets").innerHTML = PRESETS.map(([n,g]) =>
  `<button class="secondary" data-n="${n}" data-g="${g}">${n}</button>`).join("");
document.getElementById("presets").onclick = e => {
  if (!e.target.dataset.n) return;
  document.getElementById("name").value = e.target.dataset.n;
  document.getElementById("grams").value = e.target.dataset.g;
};

let shelvesInit = false;
function render(s) {
  if (!s) return;
  const d = document.getElementById("door");
  d.textContent = s.door_open ? "open" : "closed"; d.className = "pill" + (s.door_open ? " open" : "");
  document.getElementById("busy").textContent = s.queued_actions ? (s.hand_busy ? "hand in fridge..." : "waiting for door...") : "";
  const shelves = Object.keys(s.weights);
  if (!shelvesInit) {
    document.getElementById("shelf").innerHTML = shelves.map(k => `<option value="${k}">Shelf ${k}</option>`).join("");
    shelvesInit = true;
  }
  document.getElementById("weights").textContent = shelves.map(k => `Shelf ${k}: ${s.weights[k]} g`).join("  ·  ");
  const c = s.conditions;
  document.getElementById("conds").textContent = `${c.temperature_c} °C · ${c.pressure_hpa} hPa · ${c.humidity_pct}% RH · light ${c.light_raw}`;
  const rows = s.items.map(i => `<tr><td><span class="pill" style="background:rgb(${i.color[2]},${i.color[1]},${i.color[0]})">&nbsp;</span> ${esc(i.name)}</td>
    <td>${i.grams} g</td><td>shelf ${i.shelf}</td>
    <td style="text-align:right"><button class="secondary" onclick="post('/sim/items/${i.id}/use',{grams:100}).then(render)">Use 100 g</button>
    <button class="danger" onclick="post('/sim/items/${i.id}/remove').then(render)">Take out</button></td></tr>`);
  document.getElementById("items").innerHTML = rows.join("") || '<tr><td class="muted">Empty.</td></tr>';
}
setInterval(() => fetch("/sim/state").then(r => r.json()).then(render), 500);
fetch("/sim/state").then(r => r.json()).then(render);
// Show the backend's annotated vision view; fall back to the raw camera when the
// vision loop isn't running (and retry the vision view every few seconds).
const BACKEND = "__BACKEND__";
const cam = document.getElementById("cam");
const camLabel = document.getElementById("camlabel");
let visionOk = true;
cam.onload = () => {
  camLabel.innerHTML = visionOk
    ? '<b>Live vision view</b> &mdash; <span style="color:#ff8c00">orange</span> = your hand, '
      + '<span style="color:#00dcff">cyan</span> = what changed, '
      + '<span style="color:#4ade80">green flash</span> = the snapshot for Gemini'
    : "Raw camera (the backend's vision view isn't available yet)";
};
cam.onerror = () => {
  if (visionOk) { visionOk = false; setTimeout(() => { visionOk = true; }, 4000); }
};
setInterval(() => {
  cam.src = (visionOk ? BACKEND + "/api/vision/frame.jpg" : "/frame.jpg") + "?t=" + Date.now();
}, 200);
</script>
</body></html>
"""
