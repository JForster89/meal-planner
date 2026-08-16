# Meal Planner

Plan the week's HelloFresh recipes, get one combined shopping list, and tick it
off on your phone in the shop.

## What it does

- **Import recipes** by pasting a HelloFresh URL — pulls the name, cooking time,
  method, and exact quantities for every portion size they publish.
- **Plan a week** by picking recipes and how many portions of each.
- **One shopping list** that merges ingredients across recipes: 450 g potatoes in
  one meal plus 0.5 kg in another becomes a single `950 g Potatoes` line.
- **Tick items off** as you shop. State saves instantly and syncs across devices.
- **Cupboard items hidden** by default — HelloFresh flags things like oil, butter
  and salt as "not included in your delivery", so they're filtered out unless asked for.

## Running locally

```bash
python -m venv venv
venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: venv/bin/pip
venv/Scripts/python app.py
```

Then open <http://127.0.0.1:5000>.

The database is created and migrated automatically on first run. Set `RECIPES_DB`
to put it somewhere else.

### Tests

```bash
venv/Scripts/python -m pytest tests/ -q
```

## Deploying

The shopping list is only useful if it works inside a supermarket, which means
hosting it somewhere your phone can reach.

**Fly.io** (SQLite on a persistent volume, scales to zero between uses):

```bash
fly launch --no-deploy          # edit the app name in fly.toml first
fly volumes create recipes_data --size 1
fly secrets set SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
fly deploy
```

Any Docker host works the same way — the only requirements are a persistent
volume mounted at `/data` and a `SECRET_KEY`.

Once deployed, open it on your phone and use "Add to Home Screen". The manifest
makes it launch fullscreen, straight to the shopping list.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `RECIPES_DB` | `./recipes.db` | SQLite file location |
| `SECRET_KEY` | insecure dev value | **Set this in production** — signs flash-message cookies |
| `FLASK_DEBUG` | off | `1` enables the debug console. Never set in production |
| `PORT` / `HOST` | `5000` / `127.0.0.1` | Dev server binding |

## How it's put together

| File | Role |
|---|---|
| `app.py` | Routes and form parsing |
| `db.py` | Schema, connection handling, legacy migration |
| `store.py` | Recipe, plan and shopping-list persistence |
| `aggregate.py` | Unit normalisation and cross-recipe ingredient merging |
| `hellofresh.py` | Recipe import from a HelloFresh URL |

### Why ingredients are stored the way they are

Quantity, unit and name live in separate columns. That's the whole reason the
shopping list can add things up — the previous version stored `"1 can sweetcorn"`
as one string, which can't be merged with anything.

HelloFresh publishes a *separate* quantity table per portion size, and those
numbers aren't a linear scale of each other (a recipe needing 450 g of potatoes
for two people wants 900 g for four, but 1 garlic clove becomes 2, not 2 exactly
proportionally). So every published yield is stored, and the app uses the real
table when one exists, only falling back to multiplication for portion counts
HelloFresh never published.

### Importing, and its limits

The importer reads the `__NEXT_DATA__` blob the page ships, which has quantity
and unit already separated plus a `shipped` flag marking cupboard items. It falls
back to the page's schema.org JSON-LD if that structure ever changes, though the
fallback loses the cupboard distinction.

Two known limits, both from the source data:

- Some recipes publish **empty units** (`400 Penne Pasta` with no `g`). Nothing
  can recover those at import time. They're kept unitless rather than guessed,
  and the merge key includes the unit — so an unitless `400 Penne` never gets
  silently summed with a `200 g Penne`. Edit the recipe to add the unit if you
  want them to combine.
- There's **no official HelloFresh API**. This reads public recipe pages, so a
  site redesign can break it. Manual entry always works as a fallback.
