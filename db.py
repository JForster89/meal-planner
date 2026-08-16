"""Database connection, schema and migration from the legacy single-table layout."""

import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import g

DB_PATH = os.environ.get("RECIPES_DB", os.path.join(os.path.dirname(__file__), "recipes.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    cooking_time_mins INTEGER,
    servings          INTEGER NOT NULL DEFAULT 2,
    source_url        TEXT    UNIQUE,
    created_at        TEXT    NOT NULL
);

-- One row per (recipe, portion-count, ingredient). HelloFresh publishes a
-- separate quantity table per yield and its numbers are not a linear scale of
-- each other, so we keep every variant rather than multiplying by a ratio.
CREATE TABLE IF NOT EXISTS ingredients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    yields    INTEGER NOT NULL DEFAULT 2,
    quantity  REAL,
    unit      TEXT,
    name      TEXT    NOT NULL,
    is_pantry INTEGER NOT NULL DEFAULT 0,
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ingredients_recipe ON ingredients(recipe_id, yields);

CREATE TABLE IF NOT EXISTS instructions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    step_no   INTEGER NOT NULL,
    text      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instructions_recipe ON instructions(recipe_id);

CREATE TABLE IF NOT EXISTS plans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    is_active  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS plan_recipes (
    plan_id   INTEGER NOT NULL REFERENCES plans(id)   ON DELETE CASCADE,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    portions  INTEGER NOT NULL DEFAULT 2,
    PRIMARY KEY (plan_id, recipe_id)
);

-- Tick-off state for merged shopping lines, keyed by the aggregation key
-- so it survives recipes being added to or removed from the plan.
CREATE TABLE IF NOT EXISTS shopping_state (
    plan_id  INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    item_key TEXT    NOT NULL,
    checked  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_id, item_key)
);

-- Tags, cuisine and derived protein, for grouping and search.
-- kind is 'tag', 'cuisine' or 'protein'.
CREATE TABLE IF NOT EXISTS recipe_tags (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    tag       TEXT    NOT NULL,
    kind      TEXT    NOT NULL DEFAULT 'tag',
    PRIMARY KEY (recipe_id, tag, kind)
);
CREATE INDEX IF NOT EXISTS idx_recipe_tags_kind ON recipe_tags(kind, tag);

-- App-wide preferences, e.g. how many people you normally cook for.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Ad-hoc things you need that no recipe asked for (milk, bin bags).
CREATE TABLE IF NOT EXISTS extra_items (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    text    TEXT    NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    """Per-request connection, closed by close_db on teardown."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --- legacy migration -------------------------------------------------------

LEGACY_COLUMNS = {"ingredients", "instructions", "cooking_time"}

# "1 can sweetcorn" -> (1, "can", "sweetcorn"); falls back to name-only.
_LEGACY_INGREDIENT = re.compile(
    r"^\s*(?P<qty>\d+(?:[./]\d+)?)?\s*(?P<unit>[a-zA-Z()]+)?\s+(?P<name>.+?)\s*$"
)

KNOWN_UNITS = {
    "g", "gram", "grams", "gramme", "grammes", "kg", "kilogram", "kilograms",
    "ml", "millilitre", "millilitres", "l", "litre", "litres",
    "tsp", "tbsp", "unit", "units", "unit(s)", "can", "cans", "tin", "tins",
    "pack", "packs", "clove", "cloves", "bunch", "punnet", "sachet", "pinch",
    "slice", "slices", "piece", "pieces", "handful", "jar", "bottle", "cup", "cups",
}


def parse_legacy_ingredient(text):
    """Best-effort split of a free-text ingredient into (qty, unit, name)."""
    text = text.strip()
    if not text:
        return None
    m = _LEGACY_INGREDIENT.match(text)
    if not m:
        return (None, None, text)

    qty_raw, unit, name = m.group("qty"), m.group("unit"), m.group("name")

    # Only treat the second token as a unit if it actually looks like one;
    # otherwise it is part of the ingredient name ("2 red onions").
    if unit and unit.lower() not in KNOWN_UNITS:
        name = f"{unit} {name}".strip()
        unit = None

    qty = None
    if qty_raw:
        try:
            if "/" in qty_raw:
                num, den = qty_raw.split("/", 1)
                qty = float(num) / float(den)
            else:
                qty = float(qty_raw)
        except (ValueError, ZeroDivisionError):
            qty = None

    return (qty, unit.lower() if unit else None, name)


def _legacy_table_present(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='recipes'"
    ).fetchone()
    if not row or not row[0]:
        return False
    sql = row[0].lower()
    return "ingredients" in sql and "instructions" in sql


def migrate_legacy(conn):
    """Move rows from the old flat `recipes` table into the relational schema."""
    if not _legacy_table_present(conn):
        return 0

    legacy = conn.execute(
        "SELECT id, name, cooking_time, servings, ingredients, instructions FROM recipes"
    ).fetchall()

    conn.execute("ALTER TABLE recipes RENAME TO recipes_legacy_backup")
    conn.executescript(SCHEMA)

    migrated = 0
    for row in legacy:
        _id, name, cooking_time, servings, ingredients, instructions = row

        mins = None
        if cooking_time:
            digits = re.search(r"\d+", str(cooking_time))
            if digits:
                mins = int(digits.group())

        try:
            servings = int(servings) if servings else 2
        except (TypeError, ValueError):
            servings = 2

        cur = conn.execute(
            "INSERT INTO recipes (name, cooking_time_mins, servings, created_at) "
            "VALUES (?, ?, ?, ?)",
            (name or "Untitled recipe", mins, servings, now_iso()),
        )
        recipe_id = cur.lastrowid

        for pos, raw in enumerate(p for p in (ingredients or "").split(";") if p.strip()):
            parsed = parse_legacy_ingredient(raw)
            if not parsed:
                continue
            qty, unit, ing_name = parsed
            conn.execute(
                "INSERT INTO ingredients "
                "(recipe_id, yields, quantity, unit, name, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (recipe_id, servings, qty, unit, ing_name, pos),
            )

        for step, text in enumerate(
            (s.strip() for s in (instructions or "").split(";") if s.strip()), start=1
        ):
            conn.execute(
                "INSERT INTO instructions (recipe_id, step_no, text) VALUES (?, ?, ?)",
                (recipe_id, step, text),
            )
        migrated += 1

    conn.commit()
    return migrated


# --- queries ----------------------------------------------------------------

def available_yields(conn, recipe_id):
    """Portion counts this recipe has published quantities for."""
    rows = conn.execute(
        "SELECT DISTINCT yields FROM ingredients WHERE recipe_id = ? ORDER BY yields",
        (recipe_id,),
    ).fetchall()
    return [r[0] for r in rows]


def ingredients_for(conn, recipe_id, portions):
    """Ingredient rows for `portions`, plus the multiplier still to apply.

    Prefers an exact published yield table (multiplier 1.0). Only when the
    requested portion count was never published does it fall back to scaling
    from the nearest available yield.
    """
    yields = available_yields(conn, recipe_id)
    if not yields:
        return [], 1.0

    if portions in yields:
        base, multiplier = portions, 1.0
    else:
        base = min(yields, key=lambda y: (abs(y - portions), y))
        multiplier = portions / base if base else 1.0

    rows = conn.execute(
        "SELECT quantity, unit, name, is_pantry FROM ingredients "
        "WHERE recipe_id = ? AND yields = ? ORDER BY position, id",
        (recipe_id, base),
    ).fetchall()
    return rows, multiplier


def ensure_column(conn, table, column, ddl):
    """Add a column if it's missing. SQLite has no ADD COLUMN IF NOT EXISTS."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db():
    """Create the schema, migrating the legacy table first if one is present."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        migrated = migrate_legacy(conn)
        conn.executescript(SCHEMA)
        # Columns added after the first release.
        ensure_column(conn, "recipes", "difficulty", "INTEGER")
        ensure_column(conn, "recipes", "image_url", "TEXT")
        conn.commit()
        return migrated
    finally:
        conn.close()
