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
var ASSETS = ['./', './index.html', './manifest.json', './icon.svg'];

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


def render_items(lines):
    if not lines:
        return '<li><div class="empty">Nothing planned this week.</div></li>'

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


def build_page(lines, generated_at=None, recipe_names=()):
    generated_at = generated_at or datetime.now()
    stamp = generated_at.strftime("%a %d %b, %H:%M")
    if recipe_names:
        meta = f"{len(recipe_names)} recipes &middot; updated {html.escape(stamp)}"
    else:
        meta = f"Updated {html.escape(stamp)}"
    return PAGE.replace("__ITEMS__", render_items(lines)).replace("__META__", meta)


def write_site(lines, recipe_names=(), out_dir=OUT_DIR):
    """Write index.html, the service worker, manifest and icon into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now()

    files = {
        "index.html": build_page(lines, now, recipe_names),
        # A changing cache name makes the service worker fetch the new list.
        "sw.js": SERVICE_WORKER.replace("__STAMP__", now.strftime("%Y%m%d%H%M%S")),
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


def main():
    """Render the active plan's shopping list into docs/."""
    from app import app
    import store
    from db import get_db

    include_pantry = "--pantry" in sys.argv

    with app.app_context():
        conn = get_db()
        plan = store.get_active_plan(conn)
        lines, extras = store.build_shopping_list(conn, plan["id"], include_pantry)
        names = [e["name"] for e in store.plan_entries(conn, plan["id"])]

    path = write_site(lines, names)
    print(f"Wrote {len(lines)} items to {path}")
    if not names:
        print("Warning: nothing is planned, so the list is empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
