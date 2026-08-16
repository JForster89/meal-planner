"""Publish the current shopping list as a self-contained static page.

The planning half of this app stays on your PC, where it can reach HelloFresh
and hold the database. Only the shopping list needs to travel, and in a shop it
needs exactly two things: to be readable, and to remember what you've ticked.
Neither needs a server, so this renders one HTML file with its state in
localStorage. It costs nothing to host and, unlike the Flask app, it keeps
working in a supermarket dead spot.
"""

import html
import json
import os
import re
import sys
from datetime import datetime

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#2f7d32">
<title>Shopping List</title>
<link rel="manifest" href="./manifest.json">
<link rel="icon" href="./icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="./icon.svg">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Shopping">
<style>
:root {
  --bg:#f6f7f5; --surface:#fff; --border:#e2e5e0; --text:#1c2119;
  --muted:#6b7280; --accent:#2f7d32; --accent-dark:#24631f; --accent-soft:#eaf4ea;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#14171a; --surface:#1d2125; --border:#2d3339; --text:#e8eae7;
    --muted:#9aa3ad; --accent:#5cbf60; --accent-dark:#7bd47f; --accent-soft:#1e2c1f;
  }
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
     background:var(--bg);color:var(--text);line-height:1.5;-webkit-text-size-adjust:100%}
header{position:sticky;top:0;z-index:10;background:var(--surface);
       border-bottom:1px solid var(--border);padding:.7rem 1rem}
.head-row{display:flex;align-items:center;gap:.75rem;max-width:700px;margin:0 auto}
h1{font-size:1.15rem;margin:0;flex:1}
main{max-width:700px;margin:0 auto;padding:1rem 1rem 4rem}
.track{flex:1;height:8px;background:var(--border);border-radius:999px;overflow:hidden}
.fill{height:100%;background:var(--accent);transition:width .25s ease}
.count{font-size:.85rem;color:var(--muted);white-space:nowrap}
ul{list-style:none;margin:0;padding:0}
li{background:var(--surface);border:1px solid var(--border);border-radius:12px;
   margin-bottom:.4rem;overflow:hidden}
label{display:flex;align-items:center;gap:.75rem;padding:.7rem .9rem;
      min-height:56px;cursor:pointer}
input[type=checkbox]{width:24px;height:24px;accent-color:var(--accent);flex:0 0 auto;cursor:pointer}
.txt{flex:1;min-width:0}
.qty{font-weight:700}
.for{display:block;font-size:.78rem;color:var(--muted)}
li.done{opacity:.5}
li.done .txt{text-decoration:line-through}
/* Aisle signposts: readable while scanning one-handed, without competing
   with the items themselves. */
li.aisle-head{background:transparent;border:none;border-radius:0;margin:1.1rem 0 .35rem;
  padding:0 .2rem .3rem;border-bottom:1px solid var(--border);
  font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.09em;
  color:var(--accent-dark);display:flex;justify-content:space-between;align-items:baseline}
li.aisle-head:first-child{margin-top:0}
li.aisle-head .n{font-weight:500;color:var(--muted);letter-spacing:0}
.pill{display:inline-block;font-size:.7rem;font-weight:700;text-transform:uppercase;
      letter-spacing:.03em;padding:.1rem .45rem;border-radius:999px;
      background:var(--accent-soft);color:var(--accent-dark);border:1px solid var(--border)}
.meta{color:var(--muted);font-size:.85rem;margin:.25rem 0 1rem}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;
     padding:.5rem 1rem;border:1px solid var(--border);border-radius:10px;
     background:transparent;color:var(--text);font-size:.9rem;font-weight:600;
     cursor:pointer;font-family:inherit}
.btn:hover{background:var(--accent-soft);color:var(--accent-dark)}
.row{display:flex;gap:.5rem;margin:1rem 0;flex-wrap:wrap}
.add{display:flex;gap:.5rem;margin-top:1rem}
.add input[type=text]{flex:1;padding:.65rem .7rem;min-height:44px;border:1px solid var(--border);
     border-radius:10px;background:var(--surface);color:var(--text);font-size:1rem}
h2{font-size:1rem;margin:1.5rem 0 .5rem;color:var(--muted)}
.empty{text-align:center;padding:2rem 1rem;color:var(--muted)}
</style>
</head>
<body>
<header>
  <div class="head-row">
    <h1>Shopping list</h1>
    <div class="track"><div class="fill" id="fill"></div></div>
    <span class="count" id="count"></span>
  </div>
</header>
<main>
  <p class="meta">__META__</p>
  <ul id="list">__ITEMS__</ul>

  <h2>Anything else</h2>
  <div class="add">
    <input type="text" id="extra" placeholder="Milk, bin bags, …" autocomplete="off">
    <button class="btn" id="add-btn">Add</button>
  </div>
  <ul id="extras"></ul>

  <div class="row">
    <a class="btn" href="./cook.html">Cook mode &rarr;</a>
    <button class="btn" id="reset">Untick all</button>
  </div>
  <p class="meta">Ticks are saved on this device. Works offline once loaded.</p>
</main>

<script>
(function () {
  // Ticks are keyed by ingredient, not by position, so republishing the list
  // after adding a recipe keeps everything you'd already ticked.
  var STORE = 'shopping-ticks-v1';
  var EXTRAS = 'shopping-extras-v1';

  function load(key) {
    try { return JSON.parse(localStorage.getItem(key)) || {}; }
    catch (e) { return {}; }
  }
  function save(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
  }

  var ticks = load(STORE);
  var extras = load(EXTRAS);
  if (!Array.isArray(extras.items)) extras = { items: [] };

  function refresh() {
    var boxes = document.querySelectorAll('input[type=checkbox]');
    var done = 0;
    boxes.forEach(function (b) { if (b.checked) done++; });
    var total = boxes.length;
    document.getElementById('fill').style.width = total ? (done / total * 100) + '%' : '0%';
    document.getElementById('count').textContent = done + '/' + total;
  }

  function wire(box) {
    box.addEventListener('change', function () {
      box.closest('li').classList.toggle('done', box.checked);
      if (box.dataset.key) {
        ticks[box.dataset.key] = box.checked;
        save(STORE, ticks);
      } else {
        var i = parseInt(box.dataset.extra, 10);
        extras.items[i].done = box.checked;
        save(EXTRAS, extras);
      }
      refresh();
    });
  }

  document.querySelectorAll('#list input[type=checkbox]').forEach(function (box) {
    if (ticks[box.dataset.key]) {
      box.checked = true;
      box.closest('li').classList.add('done');
    }
    wire(box);
  });

  function renderExtras() {
    var ul = document.getElementById('extras');
    ul.innerHTML = '';
    extras.items.forEach(function (item, i) {
      var li = document.createElement('li');
      if (item.done) li.className = 'done';
      var label = document.createElement('label');
      var box = document.createElement('input');
      box.type = 'checkbox';
      box.dataset.extra = i;
      box.checked = !!item.done;
      var span = document.createElement('span');
      span.className = 'txt';
      // textContent, not innerHTML - whatever gets typed here is never markup.
      span.textContent = item.text;
      label.appendChild(box);
      label.appendChild(span);
      li.appendChild(label);
      ul.appendChild(li);
      wire(box);
    });
    refresh();
  }

  document.getElementById('add-btn').addEventListener('click', function () {
    var input = document.getElementById('extra');
    var text = input.value.trim();
    if (!text) return;
    extras.items.push({ text: text, done: false });
    save(EXTRAS, extras);
    input.value = '';
    renderExtras();
  });

  document.getElementById('extra').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById('add-btn').click(); }
  });

  document.getElementById('reset').addEventListener('click', function () {
    if (!confirm('Untick everything?')) return;
    ticks = {};
    save(STORE, ticks);
    extras.items.forEach(function (i) { i.done = false; });
    save(EXTRAS, extras);
    document.querySelectorAll('#list input[type=checkbox]').forEach(function (b) {
      b.checked = false;
      b.closest('li').classList.remove('done');
    });
    renderExtras();
  });

  renderExtras();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(function () {});
  }
})();
</script>
</body>
</html>
"""

SERVICE_WORKER = """// Cache the list so it opens in a supermarket dead spot.
var CACHE = 'shopping-__STAMP__';
var ASSETS = ['./', './index.html', './cook.html', './manifest.json', './icon.svg'__EXTRA_ASSETS__];

self.addEventListener('install', function (e) {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(ASSETS); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== CACHE) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

// Network first so a republished list is picked up, falling back to the cached
// copy when there's no signal.
self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(function (res) {
      var copy = res.clone();
      caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
      return res;
    }).catch(function () {
      return caches.match(e.request).then(function (hit) {
        return hit || caches.match('./index.html');
      });
    })
  );
});
"""

# Raw string: the routing JS contains a regex with \d.
COOK_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#2f7d32">
<title>Cook</title>
<link rel="manifest" href="./manifest.json">
<link rel="icon" href="./icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="./icon.svg">
<meta name="apple-mobile-web-app-capable" content="yes">
<style>
:root {
  --bg:#f6f7f5; --surface:#fff; --border:#e2e5e0; --text:#1c2119;
  --muted:#6b7280; --accent:#2f7d32; --accent-dark:#24631f; --accent-soft:#eaf4ea;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#14171a; --surface:#1d2125; --border:#2d3339; --text:#e8eae7;
    --muted:#9aa3ad; --accent:#5cbf60; --accent-dark:#7bd47f; --accent-soft:#1e2c1f;
  }
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
     background:var(--bg);color:var(--text);line-height:1.5;-webkit-text-size-adjust:100%;
     display:flex;flex-direction:column;overscroll-behavior:none}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:.6rem 1rem;flex:0 0 auto}
.bar{display:flex;align-items:center;gap:.6rem;max-width:700px;margin:0 auto}
h1{font-size:1rem;margin:0;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
a.home{color:var(--muted);text-decoration:none;font-size:.85rem;font-weight:600;white-space:nowrap}
a.home:hover{color:var(--accent-dark)}
#back{display:none;min-width:44px;min-height:40px;border:1px solid var(--border);
      border-radius:9px;background:transparent;color:var(--text);font-size:1rem;
      cursor:pointer;font-family:inherit;flex:0 0 auto}
#back:hover{background:var(--accent-soft);color:var(--accent-dark)}
body.in-recipe #back{display:block}

/* --- chooser ---
   Visible by default so the page shows the list immediately, before the
   routing script runs. JS hides it once you pick a recipe. */
#chooser{display:block;padding:1.1rem 1.2rem 2rem;overflow-y:auto;flex:1 1 auto}
body.in-recipe #chooser{display:none}
footer{display:none}
body.in-recipe footer, body.no-chooser footer{display:block}
.chooser-inner{max-width:660px;margin:0 auto}
.chooser-inner h2{font-size:1.35rem;margin:0 0 .3rem}
.pick{display:flex;align-items:center;gap:.9rem;width:100%;text-align:left;
      background:var(--surface);border:1px solid var(--border);border-radius:12px;
      padding:.95rem 1rem;margin-bottom:.6rem;cursor:pointer;color:var(--text);
      font-family:inherit;font-size:1rem;min-height:64px}
.pick:hover{border-color:var(--accent);background:var(--accent-soft)}
.pick .n{flex:0 0 auto;width:30px;height:30px;border-radius:50%;background:var(--accent);
         color:#fff;display:flex;align-items:center;justify-content:center;
         font-weight:700;font-size:.85rem}
.pick .t{flex:1;min-width:0}
.pick .nm{display:block;font-weight:600;line-height:1.35}
.pick .sub{display:block;font-size:.82rem;color:var(--muted);margin-top:.15rem}
.pick .go{flex:0 0 auto;color:var(--muted);font-size:1.1rem}

main{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.deck{display:none;flex:1 1 auto;min-height:0;flex-direction:column}
.deck.active{display:flex}

.track{flex:1 1 auto;min-height:0;display:flex;overflow-x:auto;overflow-y:hidden;
       scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.track::-webkit-scrollbar{display:none}

.card{flex:0 0 100%;width:100%;scroll-snap-align:center;scroll-snap-stop:always;
      padding:1.1rem 1.2rem 1.5rem;overflow-y:auto;display:flex;flex-direction:column}
.card-inner{max-width:660px;margin:0 auto;width:100%}
.step-no{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
         color:var(--accent-dark);margin-bottom:.3rem}
.cap{font-size:1.05rem;font-weight:700;margin-bottom:.5rem}
.shot{width:100%;max-height:38vh;object-fit:cover;border-radius:10px;margin-bottom:.7rem;
      background:var(--border)}
.step-text{font-size:1.22rem;line-height:1.55}
@media (min-width:640px){ .step-text{font-size:1.3rem} }

ul.ing{list-style:none;margin:.3rem 0 0;padding:0}
ul.ing li{display:flex;gap:.6rem;padding:.5rem 0;border-bottom:1px solid var(--border);font-size:1.05rem}
ul.ing li:last-child{border-bottom:none}
.q{font-weight:700;flex:0 0 auto;min-width:4.5rem}
.pill{display:inline-block;font-size:.68rem;font-weight:700;text-transform:uppercase;
      letter-spacing:.03em;padding:.05rem .4rem;border-radius:999px;
      background:var(--accent-soft);color:var(--accent-dark);border:1px solid var(--border)}
.meta{color:var(--muted);font-size:.9rem;margin:.2rem 0 1rem}
h2{font-size:1.3rem;margin:0 0 .4rem}

footer{flex:0 0 auto;background:var(--surface);border-top:1px solid var(--border);padding:.5rem 1rem}
.nav{display:flex;align-items:center;gap:.6rem;max-width:700px;margin:0 auto}
.dots{flex:1;display:flex;gap:.3rem;justify-content:center;flex-wrap:wrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--border);transition:background .2s,transform .2s}
.dot.on{background:var(--accent);transform:scale(1.35)}
button.nav-btn{min-width:52px;min-height:46px;border:1px solid var(--border);border-radius:10px;
       background:transparent;color:var(--text);font-size:1.2rem;cursor:pointer;font-family:inherit}
button.nav-btn:hover:not(:disabled){background:var(--accent-soft);color:var(--accent-dark)}
button.nav-btn:disabled{opacity:.3;cursor:default}
.awake{display:flex;align-items:center;gap:.35rem;font-size:.8rem;color:var(--muted);
       justify-content:center;padding:.35rem 0 0}
.empty{text-align:center;padding:3rem 1rem;color:var(--muted)}
</style>
</head>
<body>
<header>
  <div class="bar">
    <button id="back" aria-label="Back to recipe list">&larr;</button>
    <h1 id="title">Cook</h1>
    <a class="home" href="./index.html">Shopping&nbsp;&rarr;</a>
  </div>
</header>

<main id="main">
__CHOOSER__
__DECKS__
</main>

<footer>
  <div class="nav">
    <button class="nav-btn" id="prev" aria-label="Previous step">&larr;</button>
    <div class="dots" id="dots"></div>
    <button class="nav-btn" id="next" aria-label="Next step">&rarr;</button>
  </div>
  <label class="awake">
    <input type="checkbox" id="awake"> Keep screen on while cooking
  </label>
</footer>

<script>
(function () {
  var decks = Array.prototype.slice.call(document.querySelectorAll('.deck'));
  if (!decks.length) return;

  var title = document.getElementById('title');
  var dots = document.getElementById('dots');
  var prev = document.getElementById('prev');
  var next = document.getElementById('next');
  var back = document.getElementById('back');
  var hasChooser = !!document.getElementById('chooser');
  var current = 0;

  // With a single recipe there is no list to go back to, so the footer nav
  // is always on and the page opens straight into the steps.
  if (!hasChooser) document.body.classList.add('no-chooser');

  function deck() { return decks[current]; }
  function track() { return deck().querySelector('.track'); }
  function cards() { return deck().querySelectorAll('.card'); }

  function index() {
    var t = track();
    // Round to the nearest card rather than truncating, so a part-way
    // swipe still reports the card you actually landed on.
    return Math.round(t.scrollLeft / t.clientWidth);
  }

  function paint() {
    var i = index(), n = cards().length;
    dots.innerHTML = '';
    for (var k = 0; k < n; k++) {
      var d = document.createElement('div');
      d.className = 'dot' + (k === i ? ' on' : '');
      dots.appendChild(d);
    }
    prev.disabled = i <= 0;
    next.disabled = i >= n - 1;
  }

  function go(delta) {
    var t = track();
    t.scrollTo({ left: (index() + delta) * t.clientWidth, behavior: 'smooth' });
  }

  function show(i) {
    decks.forEach(function (d, k) { d.classList.toggle('active', k === i); });
    current = i;
    document.body.classList.add('in-recipe');
    title.textContent = decks[i].dataset.name;
    track().scrollTo({ left: 0 });
    paint();
  }

  function showChooser() {
    decks.forEach(function (d) { d.classList.remove('active'); });
    document.body.classList.remove('in-recipe');
    title.textContent = 'What are you cooking?';
  }

  // Driven by the URL hash so the phone's own back button leaves a recipe
  // and returns to the list, rather than leaving the page entirely.
  function route() {
    var match = /^#r(\d+)$/.exec(window.location.hash);
    if (match && decks[+match[1]]) {
      show(+match[1]);
    } else if (hasChooser) {
      showChooser();
    } else {
      show(0);
    }
  }

  window.addEventListener('hashchange', route);

  Array.prototype.forEach.call(document.querySelectorAll('.pick'), function (btn) {
    btn.addEventListener('click', function () {
      window.location.hash = 'r' + btn.dataset.index;
    });
  });

  back.addEventListener('click', function () {
    if (hasChooser) window.location.hash = '';
  });

  decks.forEach(function (d) {
    var t = d.querySelector('.track');
    var timer;
    t.addEventListener('scroll', function () {
      clearTimeout(timer);
      timer = setTimeout(paint, 60);
    }, { passive: true });
  });

  prev.addEventListener('click', function () { go(-1); });
  next.addEventListener('click', function () { go(1); });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') go(-1);
    if (e.key === 'ArrowRight') go(1);
  });

  window.addEventListener('resize', paint);

  // Stops the phone locking mid-step. Not supported everywhere, and the lock
  // is dropped when the tab is hidden, so it's re-acquired on return.
  var lock = null;
  var awake = document.getElementById('awake');
  async function acquire() {
    try { lock = await navigator.wakeLock.request('screen'); } catch (e) { lock = null; }
  }
  if ('wakeLock' in navigator) {
    awake.addEventListener('change', function () {
      if (awake.checked) { acquire(); }
      else if (lock) { lock.release(); lock = null; }
    });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && awake.checked) acquire();
    });
  } else {
    awake.parentElement.style.display = 'none';
  }

  route();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(function () {});
  }
})();
</script>
</body>
</html>
"""

MANIFEST = {
    "name": "Shopping List",
    "short_name": "Shopping",
    "start_url": "./index.html",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#f6f7f5",
    "theme_color": "#2f7d32",
    "icons": [
        {"src": "./icon.svg", "sizes": "any", "type": "image/svg+xml",
         "purpose": "any maskable"}
    ],
}


def render_items(lines, by_aisle=True):
    """Render the list, grouped into aisles unless asked otherwise.

    This is the copy used in the shop, so it matters more here than in the
    local app that the order matches how you walk round.
    """
    if not lines:
        return '<li><div class="empty">Nothing planned this week.</div></li>'

    if by_aisle and any(line.get("aisle") for line in lines):
        import taxonomy

        grouped = {}
        for line in lines:
            grouped.setdefault(line.get("aisle") or "Other", []).append(line)

        chunks = []
        for aisle in sorted(grouped, key=taxonomy.aisle_sort_key):
            items = grouped[aisle]
            chunks.append(
                f'<li class="aisle-head">{html.escape(aisle)}'
                f'<span class="n">{len(items)}</span></li>'
            )
            chunks.append(render_items(items, by_aisle=False))
        return "\n".join(chunks)

    out = []
    for line in lines:
        qty = html.escape(line["display_quantity"])
        name = html.escape(line["name"])
        key = html.escape(line["key"], quote=True)
        recipes = html.escape(", ".join(line["recipes"]))
        pantry = ' <span class="pill">cupboard</span>' if line["is_pantry"] else ""
        qty_html = f'<span class="qty">{qty}</span> ' if qty else ""
        out.append(
            f'<li><label><input type="checkbox" data-key="{key}">'
            f'<span class="txt">{qty_html}{name}{pantry}'
            f'<span class="for">{recipes}</span></span></label></li>'
        )
    return "\n".join(out)


def render_cook_decks(recipes):
    """One deck per recipe: an ingredients card, then a card per step."""
    if not recipes:
        return '<div class="empty"><h2>Nothing planned</h2>' \
               '<p>Plan a week and publish again.</p></div>'

    decks = []
    for recipe in recipes:
        name = html.escape(recipe["name"])
        bits = []
        if recipe.get("cooking_time_mins"):
            bits.append(f"{recipe['cooking_time_mins']} mins")
        bits.append(f"serves {recipe.get('portions', 2)}")
        meta = html.escape(" · ".join(bits))

        items = []
        for ing in recipe.get("ingredients", []):
            qty = html.escape(ing.get("display_quantity") or "")
            pantry = ' <span class="pill">cupboard</span>' if ing.get("is_pantry") else ""
            items.append(
                f'<li><span class="q">{qty}</span>'
                f'<span>{html.escape(ing["name"])}{pantry}</span></li>'
            )

        cards = [
            '<div class="card"><div class="card-inner">'
            f'<h2>{name}</h2><p class="meta">{meta}</p>'
            f'<ul class="ing">{"".join(items)}</ul>'
            "</div></div>"
        ]

        steps = recipe.get("steps", [])
        for i, step in enumerate(steps, start=1):
            text = step if isinstance(step, str) else step.get("text", "")
            photo, caption = "", ""
            if not isinstance(step, str):
                src = step.get("local_image")
                if src:
                    alt = html.escape(step.get("caption") or f"Step {i}", quote=True)
                    photo = f'<img class="shot" src="{src}" alt="{alt}" loading="lazy">'
                if step.get("caption"):
                    caption = f'<div class="cap">{html.escape(step["caption"])}</div>'

            cards.append(
                '<div class="card"><div class="card-inner">'
                f'<div class="step-no">Step {i} of {len(steps)}</div>'
                f"{caption}{photo}"
                f'<div class="step-text">{html.escape(text)}</div>'
                "</div></div>"
            )

        if not steps:
            cards.append(
                '<div class="card"><div class="card-inner">'
                '<div class="step-text">No method saved for this recipe.</div>'
                "</div></div>"
            )

        decks.append(
            f'<div class="deck" data-name="{name}">'
            f'<div class="track">{"".join(cards)}</div></div>'
        )

    return "".join(decks)


def render_chooser(recipes):
    """A "what are you cooking?" screen, shown when a week has several meals.

    With one recipe there's nothing to choose, so it opens straight into it.
    """
    if len(recipes) < 2:
        return ""

    picks = []
    for i, recipe in enumerate(recipes):
        bits = []
        if recipe.get("cooking_time_mins"):
            bits.append(f"{recipe['cooking_time_mins']} mins")
        steps = len(recipe.get("steps", []))
        bits.append(f"{steps} step{'s' if steps != 1 else ''}")
        bits.append(f"serves {recipe.get('portions', 2)}")

        picks.append(
            f'<button class="pick" data-index="{i}">'
            f'<span class="n">{i + 1}</span>'
            f'<span class="t"><span class="nm">{html.escape(recipe["name"])}</span>'
            f'<span class="sub">{html.escape(" · ".join(bits))}</span></span>'
            f'<span class="go">&rarr;</span></button>'
        )

    return (
        '<div id="chooser"><div class="chooser-inner">'
        "<h2>What are you cooking?</h2>"
        f'<p class="meta">{len(recipes)} meals planned this week.</p>'
        f'{"".join(picks)}'
        "</div></div>"
    )


def build_cook_page(recipes):
    return (
        COOK_PAGE
        .replace("__DECKS__", render_cook_decks(recipes))
        .replace("__CHOOSER__", render_chooser(recipes))
    )


def build_page(lines, generated_at=None, recipe_names=()):
    generated_at = generated_at or datetime.now()
    stamp = generated_at.strftime("%a %d %b, %H:%M")
    if recipe_names:
        meta = f"{len(recipe_names)} recipes &middot; updated {html.escape(stamp)}"
    else:
        meta = f"Updated {html.escape(stamp)}"
    return PAGE.replace("__ITEMS__", render_items(lines)).replace("__META__", meta)


def write_site(lines, recipe_names=(), out_dir=OUT_DIR, recipes=(), with_images=True):
    """Write the shopping list, cook page and PWA plumbing into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now()
    recipes = list(recipes)

    images = download_images(recipes, out_dir) if with_images else []
    # Precache the photos too, so a recipe opens in a kitchen with no signal
    # even if you never viewed it online first.
    extra_assets = "".join(f", './{IMG_DIR}/{n}'" for n in sorted(set(images)))

    files = {
        "index.html": build_page(lines, now, recipe_names),
        "cook.html": build_cook_page(recipes),
        # A changing cache name makes the service worker fetch the new list.
        "sw.js": (SERVICE_WORKER
                  .replace("__STAMP__", now.strftime("%Y%m%d%H%M%S"))
                  .replace("__EXTRA_ASSETS__", extra_assets)),
        "manifest.json": json.dumps(MANIFEST, indent=2),
        ".nojekyll": "",
    }

    icon_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "icon.svg")
    if os.path.exists(icon_src):
        with open(icon_src, encoding="utf-8") as fh:
            files["icon.svg"] = fh.read()

    for name, content in files.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)

    return os.path.join(out_dir, "index.html")


class PublishError(Exception):
    """Raised when the generated site couldn't be pushed."""


def _no_window_kwargs():
    """Stop Windows opening a console for each child process.

    The app runs under pythonw.exe, which has no console of its own, so every
    git call would otherwise flash up its own cmd window - and a publish makes
    several in a row.
    """
    if sys.platform != "win32":
        return {}

    import subprocess

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startupinfo,
    }


def _git_env():
    """Keep git and its helpers from trying to talk to a user.

    CREATE_NO_WINDOW only covers git itself. During a push git spawns
    git-remote-https and git-credential-manager, and those grandchildren
    allocate their own console. Telling them never to prompt keeps them
    headless - the credential is already cached, so nothing needs asking.
    """
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_OPTIONAL_LOCKS": "0",
    })
    return env


def _git(args, cwd, timeout=90):
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
        env=_git_env(), **_no_window_kwargs(),
    )


def git_publish(repo_dir=None, docs_dir="docs"):
    """Commit and push just the generated site.

    Scoped to `docs/` on purpose: publishing a shopping list shouldn't sweep up
    whatever half-finished code edits happen to be in the working tree.

    Returns a short status string, or raises PublishError.
    """
    import subprocess

    repo_dir = repo_dir or os.path.dirname(os.path.abspath(__file__))

    try:
        inside = _git(["rev-parse", "--is-inside-work-tree"], repo_dir)
        if inside.returncode != 0:
            raise PublishError("This folder isn't a git repository.")

        if _git(["remote", "get-url", "origin"], repo_dir).returncode != 0:
            raise PublishError("No 'origin' remote is configured, so there's nowhere to push.")

        add = _git(["add", "--", docs_dir], repo_dir)
        if add.returncode != 0:
            raise PublishError(f"git add failed: {add.stderr.strip()}")

        staged = _git(["diff", "--cached", "--quiet", "--", docs_dir], repo_dir)
        if staged.returncode == 0:
            return "No changes since the last publish."

        commit = _git(
            ["commit", "-m", f"Shopping list {datetime.now():%d %b %H:%M}", "--", docs_dir],
            repo_dir,
        )
        if commit.returncode != 0:
            raise PublishError(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")

        push = _git(["push"], repo_dir, timeout=120)
        if push.returncode != 0:
            detail = (push.stderr or push.stdout).strip().splitlines()
            raise PublishError(
                "Pushed nothing - " + (detail[-1] if detail else "git push failed") +
                " (your local commit is safe; push by hand when you're back online)"
            )

        return "Pushed. Your phone updates in under a minute."

    except FileNotFoundError as exc:
        raise PublishError("git isn't installed or isn't on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PublishError("git timed out - check your connection.") from exc


def pages_url(repo_dir=None):
    """Best guess at the GitHub Pages address, from the origin remote."""
    repo_dir = repo_dir or os.path.dirname(os.path.abspath(__file__))
    result = _git(["remote", "get-url", "origin"], repo_dir, timeout=15)
    if result.returncode != 0:
        return None

    match = re.search(r"github\.com[:/]([^/]+)/([^/\s.]+)", result.stdout.strip())
    if not match:
        return None
    user, repo = match.groups()
    return f"https://{user.lower()}.github.io/{repo}/"


IMG_DIR = "img"


def download_images(recipes, out_dir, subdir=IMG_DIR):
    """Fetch step photos into the site so the cook page works offline.

    Hotlinking would be lighter, but the whole point of publishing a static
    page is that it opens in a kitchen with no signal. Files are named by a
    hash of their URL, so re-publishing an unchanged week downloads nothing.

    Returns the list of local filenames written or already present.
    """
    import hashlib

    import requests

    target = os.path.join(out_dir, subdir)
    os.makedirs(target, exist_ok=True)

    local_names = []
    for recipe in recipes:
        for step in recipe.get("steps", []):
            # Steps may be plain strings (manual recipes), which have no photo.
            if isinstance(step, str):
                continue
            url = step.get("image_url")
            if not url:
                continue

            name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
            path = os.path.join(target, name)
            step["local_image"] = f"./{subdir}/{name}"

            if os.path.exists(path):
                local_names.append(name)
                continue

            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200 and resp.content:
                    with open(path, "wb") as fh:
                        fh.write(resp.content)
                    local_names.append(name)
                else:
                    step["local_image"] = None
            except requests.RequestException:
                # A missing photo is a cosmetic loss; never fail a publish for it.
                step["local_image"] = None

    return local_names


def collect_planned_recipes(conn, plan_id):
    """Planned recipes with quantities resolved for the chosen portion count."""
    import store
    from aggregate import format_quantity, normalise_unit

    out = []
    for entry in store.plan_entries(conn, plan_id):
        recipe = store.get_recipe(conn, entry["recipe_id"], entry["portions"])
        if not recipe:
            continue

        ingredients = []
        for ing in recipe["ingredients"]:
            unit, factor = normalise_unit(ing["unit"])
            qty = ing["quantity"]
            scaled = qty * factor * recipe["multiplier"] if qty is not None else None
            ingredients.append({
                "display_quantity": format_quantity(scaled, unit),
                "name": ing["name"],
                "is_pantry": bool(ing["is_pantry"]),
            })

        out.append({
            "name": recipe["name"],
            "portions": entry["portions"],
            "cooking_time_mins": recipe["cooking_time_mins"],
            "ingredients": ingredients,
            "steps": [
                {
                    "text": s["text"],
                    "image_url": s["image_url"] if "image_url" in s.keys() else None,
                    "caption": s["caption"] if "caption" in s.keys() else None,
                }
                for s in recipe["instructions"]
            ],
            "utensils": recipe.get("utensils", []),
            "allergens": recipe.get("allergens", []),
        })
    return out


def main():
    """Render the active plan's shopping list and cook page into docs/."""
    from app import app
    import store
    from db import get_db

    include_pantry = "--pantry" in sys.argv

    with app.app_context():
        conn = get_db()
        plan = store.get_active_plan(conn)
        lines, extras = store.build_shopping_list(conn, plan["id"], include_pantry)
        names = [e["name"] for e in store.plan_entries(conn, plan["id"])]
        recipes = collect_planned_recipes(conn, plan["id"])

    path = write_site(lines, names, recipes=recipes)
    print(f"Wrote {len(lines)} items and {len(recipes)} cook cards to {path}")
    if not names:
        print("Warning: nothing is planned, so the list is empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
