"""GET /vision: the live camera, as the fridge loop sees it, and the photos it takes of new items."""

VISION_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ShelfLife camera</title>
<style>
  /* The fridge screen's light palette (mobile/src/lib/theme.ts). */
  :root {
    --bg: #faf9f5; --card: #ffffff; --border: #e5e2d9; --well: #f0eee6;
    --text: #141413; --soft: #5e5d59; --muted: #6f6e69;
    --accent: #ad5233; --good: #2f8a4a; --warn: #a15c07; --danger: #b53333;
    --gap: 16px; --radius: 14px;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
               font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  body { display: grid; grid-template-rows: auto 1fr; }

  header { display: flex; align-items: center; justify-content: space-between; gap: var(--gap);
           padding: 12px var(--gap); background: var(--card); border-bottom: 1px solid var(--border); }
  .title { display: flex; align-items: baseline; gap: 8px; }
  .title b { font-size: 17px; font-weight: 700; }
  .title span { color: var(--muted); }
  .pills { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
  .pill { display: inline-flex; align-items: center; gap: 7px; padding: 5px 11px; border-radius: 999px;
          background: var(--well); color: var(--soft); font-weight: 600; font-size: 13px; white-space: nowrap; }
  .pill i { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .pill.good i { background: var(--good); } .pill.warn { color: var(--warn); } .pill.warn i { background: var(--warn); }
  .pill.bad { color: var(--danger); } .pill.bad i { background: var(--danger); }

  main { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: var(--gap); padding: var(--gap); min-height: 0; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); min-height: 0; }

  .feed { display: grid; grid-template-rows: minmax(0, 1fr); padding: 12px; }
  .screen { position: relative; min-height: 0; background: #0d0d0d; border-radius: 10px; overflow: hidden;
            display: grid; place-items: center; }
  .screen img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; display: block; }
  .screen .waiting { position: absolute; inset: 0; display: grid; place-items: center; color: #bdbdbd;
                     background: #0d0d0d; font-size: 15px; text-align: center; padding: 24px; }
  .legend { display: flex; gap: 18px; flex-wrap: wrap; color: var(--soft); font-size: 13px; padding: 0 4px; }
  .legend span { display: inline-flex; align-items: center; gap: 7px; }
  .legend i { width: 12px; height: 12px; border-radius: 3px; }

  .photos { display: grid; grid-template-rows: auto minmax(0, 1fr); align-self: start; max-height: 62vh; }
  .photos-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px;
                 border-bottom: 1px solid var(--border); }
  .photos-head h2 { margin: 0; font-size: 13px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--soft); }
  .photos-head small { color: var(--muted); font-weight: 500; letter-spacing: 0; text-transform: none; margin-left: 6px; }
  button { font: inherit; font-weight: 600; color: var(--accent); background: none; border: 0; padding: 4px 8px;
           border-radius: 8px; cursor: pointer; }
  button:hover { background: var(--well); } button:disabled { color: var(--muted); cursor: default; background: none; }
  .list { overflow-y: auto; padding: 8px; }
  .shot { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 12px; align-items: center;
          padding: 8px; border-radius: 10px; border: 1px solid transparent; transition: border-color 1.5s, background 1.5s; }
  .shot + .shot { margin-top: 2px; }
  .shot.new { border-color: var(--good); background: #f3f8f2; }
  .shot img { width: 64px; height: 64px; object-fit: cover; border-radius: 8px; background: var(--well); display: block; }
  .shot .name { font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .shot .meta { color: var(--muted); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .badge { font-size: 12px; font-weight: 700; padding: 3px 8px; border-radius: 999px; white-space: nowrap; }
  .badge.good { color: var(--good); background: #e8f2ea; }
  .badge.warn { color: var(--warn); background: #f7eedd; }
  .badge.wait { color: var(--muted); background: var(--well); }
  .empty { height: 100%; display: grid; place-content: center; text-align: center; gap: 6px; color: var(--muted); padding: 32px; }
  .empty b { color: var(--soft); font-size: 15px; }

  #toast { position: fixed; top: 14px; left: 50%; transform: translate(-50%, -8px); opacity: 0;
           background: var(--good); color: #fff; font-weight: 700; padding: 8px 16px; border-radius: 999px;
           box-shadow: 0 6px 20px rgba(0,0,0,.15); transition: opacity .25s, transform .25s; pointer-events: none; }
  #toast.on { opacity: 1; transform: translate(-50%, 0); }

  @media (max-width: 900px) {
    main { grid-template-columns: 1fr; grid-template-rows: auto auto; }
    .screen { aspect-ratio: 4 / 3; }
    .photos { max-height: 60vh; }
  }
</style>
</head>
<body>
<header>
  <div class="title"><b>Camera</b><span>ShelfLife</span></div>
  <div class="pills">
    <span class="pill" id="live"><i></i><span>Connecting</span></span>
    <span class="pill" id="door"><i></i><span>Door</span></span>
    <span class="pill" id="temp"><i></i><span>Temp</span></span>
    <span class="pill" id="humidity"><i></i><span>Humidity</span></span>
    <span class="pill" id="pressure"><i></i><span>Pressure</span></span>
    <span class="pill" id="weight"><i></i><span>Shelf</span></span>
  </div>
</header>
<main>
  <section class="card feed">
    <div class="screen">
      <img id="feed" alt="Live camera">
      <div class="waiting" id="waiting">No camera</div>
    </div>
  </section>
  <section class="card photos">
    <div class="photos-head">
      <h2>Photos<small id="count"></small></h2>
      <button id="clear" disabled>Clear</button>
    </div>
    <div class="list" id="shots"></div>
  </section>
</main>
<div id="toast">Photo taken</div>
<script>
  const $ = (id) => document.getElementById(id);
  const cap = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function pill(id, text, tone) { const p = $(id); p.className = 'pill' + (tone ? ' ' + tone : ''); p.lastElementChild.textContent = text; }

  // Live feed: fetch the next frame as soon as the last one arrives.
  let frames = 0, since = performance.now();
  function nextFrame() {
    const probe = new Image();
    probe.onload = () => {
      $('feed').src = probe.src; $('waiting').style.display = 'none'; frames++;
      const s = (performance.now() - since) / 1000;
      if (s >= 1) { pill('live', 'Live · ' + Math.round(frames / s) + ' fps', 'good'); frames = 0; since = performance.now(); }
      setTimeout(nextFrame, 60);
    };
    probe.onerror = () => { $('waiting').style.display = ''; pill('live', 'No camera', 'bad'); setTimeout(nextFrame, 1000); };
    probe.src = '/api/vision/frame.jpg?t=' + Date.now();
  }
  nextFrame();

  // Status: door and shelf weight every second, the fridge's temperature every few.
  async function status() {
    try {
      const s = await (await fetch('/api/scale')).json();
      pill('door', s.door_open ? 'Door open' : 'Door closed', s.door_open ? 'warn' : '');
      const shelves = Object.entries(s.weights);
      pill('weight', shelves.length ? shelves.map(([n, g]) => 'Shelf ' + n + ' ' + Math.round(g) + ' g').join('  ·  ') : 'No scale', shelves.length ? '' : 'bad');
    } catch (e) { pill('door', 'Offline', 'bad'); }
    setTimeout(status, 1000);
  }
  async function conditions() {
    try {
      const c = (await (await fetch('/api/conditions')).json()).latest;
      const fresh = c && Date.now() - Date.parse(c.occurred_at) < 5 * 60 * 1000;
      const t = fresh ? c.temperature_c : null;
      const h = fresh ? c.humidity_pct : null;
      const p = fresh ? c.pressure_hpa : null;
      pill('temp', t == null ? 'Temp' : t.toFixed(1) + ' °C', '');
      pill('humidity', h == null ? 'Humidity' : Math.round(h) + '% humidity', '');
      pill('pressure', p == null ? 'Pressure' : Math.round(p) + ' hPa', '');
    } catch (e) { /* shown by the status pill */ }
    setTimeout(conditions, 5000);
  }
  status(); conditions();

  // Photos of new items, newest first, with what came of each.
  let newest = null;
  const clock = (s) => new Date(s * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
  function describe(s) {
    if (s.status === 'pending') return { name: 'Naming', badge: ['wait', 'Waiting'] };
    if (s.status === 'skipped') return { name: 'Not named', badge: ['wait', 'Gemini off'] };
    if (s.status === 'removed') {
      return s.item_name ? { name: s.item_name, badge: ['good', 'Taken out'] } : { name: 'Something taken out', badge: ['warn', 'Check app'] };
    }
    if (s.status === 'named') {
      const pct = s.confidence != null ? Math.round(s.confidence * 100) + '%' : '';
      return s.needs_confirmation
        ? { name: s.item_name || 'Not sure', badge: ['warn', 'Check app'], note: pct ? pct + ' sure' : '' }
        : { name: s.item_name || '?', badge: ['good', pct || 'Added'] };
    }
    return { name: 'Photo', badge: ['wait', 'Saved'] };
  }
  async function loadShots() {
    try {
      const list = await (await fetch('/api/vision/snapshots')).json();
      const fresh = newest !== null && list.length && list[0].name !== newest;
      if (fresh) { $('toast').classList.add('on'); setTimeout(() => $('toast').classList.remove('on'), 2200); }
      newest = list.length ? list[0].name : '';
      $('count').textContent = list.length ? list.length : '';
      $('clear').disabled = !list.length;
      $('shots').innerHTML = list.length ? list.map((s, i) => {
        const d = describe(s);
        const meta = [clock(s.at), s.grams != null ? (s.grams > 0 ? '+' : '') + Math.round(s.grams) + ' g' : '', d.note || ''].filter(Boolean).join(' · ');
        return '<div class="shot' + (fresh && i === 0 ? ' new' : '') + '">' +
          '<img src="/api/vision/snapshots/' + s.name + '" alt="">' +
          '<div><div class="name">' + esc(cap(d.name)) + '</div><div class="meta">' + esc(meta) + '</div></div>' +
          '<span class="badge ' + d.badge[0] + '">' + esc(d.badge[1]) + '</span></div>';
      }).join('') : '<div class="empty"><b>No photos</b></div>';
    } catch (e) { /* backend restarting: try again next tick */ }
    setTimeout(loadShots, 1500);
  }
  $('clear').onclick = async () => { await fetch('/api/vision/snapshots', { method: 'DELETE' }); newest = null; };
  loadShots();
</script>
</body>
</html>
"""
