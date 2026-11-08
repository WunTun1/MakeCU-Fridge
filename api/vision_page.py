"""GET /vision: the live camera, as the fridge loop sees it, and the photos it takes of new items."""

VISION_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReFridge camera</title>
<style>
  :root { --bg: #121212; --panel: #1c1c1c; --line: #2c2c2c; --text: #ececec; --muted: #9a9a9a;
          --green: #5fd068; --amber: #f0b429; --red: #ef6461; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
               font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { display: grid; grid-template-rows: auto 1fr; }
  header { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--line); }
  header h1 { font-size: 16px; margin: 0; font-weight: 650; }
  #state { color: var(--muted); }
  #state.bad { color: var(--red); }
  main { display: grid; grid-template-columns: 1fr 300px; min-height: 0; }
  .live { display: grid; grid-template-rows: 1fr auto; min-height: 0; padding: 12px; gap: 8px; }
  .live img { width: 100%; height: 100%; min-height: 0; object-fit: contain; background: #000; border-radius: 8px; }
  .legend { display: flex; gap: 16px; color: var(--muted); font-size: 13px; flex-wrap: wrap; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
  aside { border-left: 1px solid var(--line); padding: 12px; overflow-y: auto; }
  aside h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 0 0 10px; }
  .shot { display: grid; grid-template-columns: 84px 1fr; gap: 10px; padding: 8px; margin-bottom: 8px;
          background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
  .shot.new { border-color: var(--green); }
  .shot img { width: 84px; height: 84px; object-fit: cover; border-radius: 6px; background: #000; }
  .shot b { display: block; font-weight: 600; }
  .shot .when { color: var(--muted); font-size: 12px; }
  .ok { color: var(--green); } .unsure { color: var(--amber); } .wait { color: var(--muted); }
  .empty { color: var(--muted); }
  #flash { position: fixed; top: 12px; left: 50%; transform: translateX(-50%); background: var(--green); color: #06230f;
           padding: 8px 16px; border-radius: 999px; font-weight: 650; opacity: 0; transition: opacity .3s; pointer-events: none; }
  #flash.on { opacity: 1; }
  @media (max-width: 760px) { main { grid-template-columns: 1fr; } aside { border-left: 0; border-top: 1px solid var(--line); } }
</style>
</head>
<body>
<header><h1>ReFridge camera</h1><span id="state">Connecting…</span></header>
<main>
  <section class="live">
    <img id="feed" alt="Live camera">
    <div class="legend">
      <span><i style="background:#ff8c00"></i>Person and hands</span>
      <span><i style="background:#00dcff"></i>What changed</span>
      <span><i style="background:#3cdc50"></i>Photo taken</span>
    </div>
  </section>
  <aside>
    <h2>Photos of new items</h2>
    <div id="shots"><p class="empty">None yet. Put something on the shelf and take your hand away.</p></div>
  </aside>
</main>
<div id="flash">Photo taken</div>
<script>
  const feed = document.getElementById('feed'), state = document.getElementById('state');
  let frames = 0, since = performance.now();
  function nextFrame() {
    const probe = new Image();
    probe.onload = () => {
      feed.src = probe.src; frames++;
      const s = (performance.now() - since) / 1000;
      if (s >= 1) { state.textContent = 'Live · ' + (frames / s).toFixed(0) + ' fps'; state.className = ''; frames = 0; since = performance.now(); }
      setTimeout(nextFrame, 60);
    };
    probe.onerror = () => {
      state.textContent = 'No camera picture — is the Pi running and the fridge loop on?'; state.className = 'bad';
      setTimeout(nextFrame, 1000);
    };
    probe.src = '/api/vision/frame.jpg?t=' + Date.now();
  }
  nextFrame();

  const shots = document.getElementById('shots'), flash = document.getElementById('flash');
  let newest = null;
  const time = (s) => new Date(s * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
  function result(s) {
    if (s.status === 'pending') return '<span class="wait">Asking Gemini…</span>';
    if (s.status === 'skipped') return '<span class="wait">Gemini off — name it in the app</span>';
    if (s.status === 'named') {
      const pct = s.confidence != null ? ' (' + Math.round(s.confidence * 100) + '%)' : '';
      return s.needs_confirmation
        ? '<span class="unsure">Not sure: ' + esc(s.item_name || '?') + pct + ' — check the app</span>'
        : '<span class="ok">' + esc(s.item_name || '?') + pct + '</span>';
    }
    return '<span class="wait">Saved</span>';
  }
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  async function loadShots() {
    try {
      const list = await (await fetch('/api/vision/snapshots')).json();
      if (list.length) {
        const fresh = newest !== null && list[0].name !== newest;
        if (fresh) { flash.classList.add('on'); setTimeout(() => flash.classList.remove('on'), 2500); }
        shots.innerHTML = list.map((s, i) =>
          '<div class="shot' + (fresh && i === 0 ? ' new' : '') + '">' +
            '<img src="/api/vision/snapshots/' + s.name + '" alt="">' +
            '<div><b>' + result(s) + '</b>' +
            '<div class="when">' + time(s.at) + (s.grams != null ? ' · ' + (s.grams > 0 ? '+' : '') + Math.round(s.grams) + ' g' : '') + '</div></div>' +
          '</div>').join('');
        newest = list[0].name;
      } else if (newest === null) {
        newest = '';
      }
    } catch (e) { /* backend restarting: try again next tick */ }
    setTimeout(loadShots, 1500);
  }
  loadShots();
</script>
</body>
</html>
"""
