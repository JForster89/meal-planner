"""Persistence for recipes, weekly plans and the shopping list."""

from aggregate import aggregate
from db import available_yields, ingredients_for, now_iso

DEFAULT_PORTIONS_KEY = "default_portions"


# --- settings ---------------------------------------------------------------

def get_setting(conn, key, fallback=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else fallback


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()


def default_portions(conn):
    """How many people you normally cook for; used for newly planned recipes."""
    try:
        return max(1, int(get_setting(conn, DEFAULT_PORTIONS_KEY, 2)))
    except (TypeError, ValueError):
        return 2


# --- recipes ----------------------------------------------------------------

def list_recipes(conn):
    return conn.execute(
        "SELECT r.id, r.name, r.cooking_time_mins, r.servings, r.source_url, "
        "       (SELECT COUNT(*) FROM ingredients i "
        "         WHERE i.recipe_id = r.id AND i.yields = r.servings) AS n_ingredients "
        "FROM recipes r ORDER BY r.name COLLATE NOCASE"
    ).fetchall()


def get_recipe(conn, recipe_id, portions=None):
    recipe = conn.execute(
        "SELECT id, name, cooking_time_mins, servings, source_url, difficulty "
        "FROM recipes WHERE id = ?",
        (recipe_id,),
    ).fetchone()
    if not recipe:
        return None

    portions = portions or recipe["servings"]
    rows, multiplier = ingredients_for(conn, recipe_id, portions)
    instructions = conn.execute(
        "SELECT step_no, text FROM instructions WHERE recipe_id = ? ORDER BY step_no",
        (recipe_id,),
    ).fetchall()

    return {
        "id": recipe["id"],
        "name": recipe["name"],
        "cooking_time_mins": recipe["cooking_time_mins"],
        "servings": recipe["servings"],
        "source_url": recipe["source_url"],
        "difficulty": recipe["difficulty"],
        "portions": portions,
        "multiplier": multiplier,
        "available_yields": available_yields(conn, recipe_id),
        "ingredients": rows,
        "instructions": instructions,
        "tags": get_tags(conn, recipe_id),
    }


def find_by_source_url(conn, url):
    if not url:
        return None
    return conn.execute("SELECT id FROM recipes WHERE source_url = ?", (url,)).fetchone()


def save_recipe(conn, data, recipe_id=None):
    """Insert or fully replace a recipe and its ingredients/instructions.

    `data["yields"]` maps a portion count to its ingredient list, so a single
    recipe can carry HelloFresh's published 2/3/4-portion quantity tables.
    """
    name = (data.get("name") or "").strip() or "Untitled recipe"
    servings = data.get("servings") or 2
    source_url = data.get("source_url") or None

    if recipe_id:
        conn.execute(
            "UPDATE recipes SET name = ?, cooking_time_mins = ?, servings = ?, source_url = ? "
            "WHERE id = ?",
            (name, data.get("cooking_time_mins"), servings, source_url, recipe_id),
        )
        conn.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
        conn.execute("DELETE FROM instructions WHERE recipe_id = ?", (recipe_id,))
    else:
        cur = conn.execute(
            "INSERT INTO recipes (name, cooking_time_mins, servings, source_url, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, data.get("cooking_time_mins"), servings, source_url, now_iso()),
        )
        recipe_id = cur.lastrowid

    for portions, items in (data.get("yields") or {}).items():
        for pos, ing in enumerate(items):
            if not (ing.get("name") or "").strip():
                continue
            conn.execute(
                "INSERT INTO ingredients "
                "(recipe_id, yields, quantity, unit, name, is_pantry, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    recipe_id,
                    int(portions),
                    ing.get("quantity"),
                    (ing.get("unit") or "").strip(),
                    ing["name"].strip(),
                    1 if ing.get("is_pantry") else 0,
                    ing.get("position", pos),
                ),
            )

    for step, text in enumerate((t for t in data.get("instructions", []) if t.strip()), start=1):
        conn.execute(
            "INSERT INTO instructions (recipe_id, step_no, text) VALUES (?, ?, ?)",
            (recipe_id, step, text.strip()),
        )

    conn.execute("UPDATE recipes SET difficulty = ? WHERE id = ?",
                 (data.get("difficulty"), recipe_id))

    conn.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
    tagged = [("tag", t) for t in data.get("tags", [])]
    tagged += [("cuisine", c) for c in data.get("cuisines", [])]
    if data.get("protein"):
        tagged.append(("protein", data["protein"]))
    for kind, tag in tagged:
        if tag and tag.strip():
            conn.execute(
                "INSERT OR IGNORE INTO recipe_tags (recipe_id, tag, kind) VALUES (?, ?, ?)",
                (recipe_id, tag.strip(), kind),
            )

    conn.commit()
    return recipe_id


def backfill_proteins(conn):
    """Give a protein to recipes saved before tagging existed.

    The ingredients are already stored, so this needs no network call. Tags and
    cuisine can't be recovered this way - those only come from HelloFresh - so
    re-importing is still worthwhile, but grouping works immediately.
    """
    import taxonomy

    rows = conn.execute(
        "SELECT r.id FROM recipes r WHERE NOT EXISTS ("
        "  SELECT 1 FROM recipe_tags t WHERE t.recipe_id = r.id AND t.kind = 'protein')"
    ).fetchall()

    for row in rows:
        names = [
            r["name"] for r in conn.execute(
                "SELECT DISTINCT name FROM ingredients WHERE recipe_id = ?", (row["id"],)
            )
        ]
        conn.execute(
            "INSERT OR IGNORE INTO recipe_tags (recipe_id, tag, kind) VALUES (?, ?, 'protein')",
            (row["id"], taxonomy.detect_protein(names)),
        )

    if rows:
        conn.commit()
    return len(rows)


def get_tags(conn, recipe_id):
    rows = conn.execute(
        "SELECT tag, kind FROM recipe_tags WHERE recipe_id = ? ORDER BY kind, tag",
        (recipe_id,),
    ).fetchall()
    return [{"tag": r["tag"], "kind": r["kind"]} for r in rows]


def tags_for_recipes(conn, kinds=("tag", "cuisine", "protein")):
    """{recipe_id: [tags]} in one query, to avoid a lookup per card."""
    placeholders = ",".join("?" * len(kinds))
    rows = conn.execute(
        f"SELECT recipe_id, tag, kind FROM recipe_tags WHERE kind IN ({placeholders}) "
        "ORDER BY CASE kind WHEN 'protein' THEN 0 WHEN 'cuisine' THEN 1 ELSE 2 END, tag",
        tuple(kinds),
    ).fetchall()
    out = {}
    for row in rows:
        out.setdefault(row["recipe_id"], []).append(
            {"tag": row["tag"], "kind": row["kind"]}
        )
    return out


def count_refreshable(conn):
    """Imported recipes with no tags or cuisine yet.

    Protein is backfilled locally, but tags and cuisine only exist on the
    HelloFresh page, so these need re-fetching to be complete.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM recipes r "
        "WHERE r.source_url IS NOT NULL AND r.source_url != '' "
        "  AND NOT EXISTS (SELECT 1 FROM recipe_tags t "
        "                  WHERE t.recipe_id = r.id AND t.kind IN ('tag', 'cuisine'))"
    ).fetchone()
    return row["n"] if row else 0


def all_tags(conn, kind):
    rows = conn.execute(
        "SELECT tag, COUNT(*) AS n FROM recipe_tags WHERE kind = ? "
        "GROUP BY tag ORDER BY n DESC, tag",
        (kind,),
    ).fetchall()
    return [{"tag": r["tag"], "count": r["n"]} for r in rows]


def search_recipes(conn, query=None, tag=None, protein=None):
    """Filter the library by free text and/or an exact tag.

    Free text matches the recipe name or any of its ingredient names, so
    "chorizo" finds the pasta dish even though the word isn't in its title.
    """
    sql = [
        "SELECT DISTINCT r.id, r.name, r.cooking_time_mins, r.servings, r.source_url,",
        "  r.difficulty,",
        "  (SELECT COUNT(*) FROM ingredients i",
        "    WHERE i.recipe_id = r.id AND i.yields = r.servings) AS n_ingredients",
        "FROM recipes r",
    ]
    where, params = [], []

    if query:
        sql.append(
            "LEFT JOIN ingredients ing ON ing.recipe_id = r.id "
            "AND ing.yields = r.servings"
        )
        where.append("(r.name LIKE ? OR ing.name LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]

    for value, kind in ((tag, "tag"), (protein, "protein")):
        if value:
            where.append(
                "EXISTS (SELECT 1 FROM recipe_tags rt WHERE rt.recipe_id = r.id "
                "AND rt.kind = ? AND rt.tag = ?)"
            )
            params += [kind, value]

    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY r.name COLLATE NOCASE")

    return conn.execute("\n".join(sql), params).fetchall()


def delete_recipe(conn, recipe_id):
    conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    conn.commit()


# --- plans ------------------------------------------------------------------

def get_active_plan(conn):
    plan = conn.execute(
        "SELECT id, name, created_at FROM plans WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if plan:
        return plan
    cur = conn.execute(
        "INSERT INTO plans (name, created_at, is_active) VALUES (?, ?, 1)",
        ("This week", now_iso()),
    )
    conn.commit()
    return conn.execute(
        "SELECT id, name, created_at FROM plans WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def plan_entries(conn, plan_id):
    return conn.execute(
        "SELECT pr.recipe_id, pr.portions, r.name, r.cooking_time_mins, r.servings "
        "FROM plan_recipes pr JOIN recipes r ON r.id = pr.recipe_id "
        "WHERE pr.plan_id = ? ORDER BY r.name COLLATE NOCASE",
        (plan_id,),
    ).fetchall()


def add_to_plan(conn, plan_id, recipe_id, portions=None):
    if portions is None:
        portions = default_portions(conn)
    conn.execute(
        "INSERT INTO plan_recipes (plan_id, recipe_id, portions) VALUES (?, ?, ?) "
        "ON CONFLICT(plan_id, recipe_id) DO UPDATE SET portions = excluded.portions",
        (plan_id, recipe_id, portions),
    )
    conn.commit()


def remove_from_plan(conn, plan_id, recipe_id):
    conn.execute(
        "DELETE FROM plan_recipes WHERE plan_id = ? AND recipe_id = ?", (plan_id, recipe_id)
    )
    conn.commit()


def set_portions(conn, plan_id, recipe_id, portions):
    conn.execute(
        "UPDATE plan_recipes SET portions = ? WHERE plan_id = ? AND recipe_id = ?",
        (portions, plan_id, recipe_id),
    )
    conn.commit()


def clear_plan(conn, plan_id):
    conn.execute("DELETE FROM plan_recipes WHERE plan_id = ?", (plan_id,))
    conn.execute("DELETE FROM shopping_state WHERE plan_id = ?", (plan_id,))
    conn.commit()


# --- shopping list ----------------------------------------------------------

def build_shopping_list(conn, plan_id, include_pantry=False):
    """Aggregate every planned recipe's ingredients into one tickable list."""
    rows = []
    for entry in plan_entries(conn, plan_id):
        ingredients, multiplier = ingredients_for(conn, entry["recipe_id"], entry["portions"])
        for ing in ingredients:
            rows.append(
                {
                    "quantity": ing["quantity"],
                    "unit": ing["unit"],
                    "name": ing["name"],
                    "is_pantry": ing["is_pantry"],
                    "recipe_name": entry["name"],
                    "multiplier": multiplier,
                }
            )

    lines = aggregate(rows, include_pantry=include_pantry)

    checked = {
        r["item_key"]
        for r in conn.execute(
            "SELECT item_key FROM shopping_state WHERE plan_id = ? AND checked = 1", (plan_id,)
        )
    }
    for line in lines:
        line["checked"] = line["key"] in checked

    extras = conn.execute(
        "SELECT id, text, checked FROM extra_items WHERE plan_id = ? ORDER BY id", (plan_id,)
    ).fetchall()

    return lines, extras


def set_checked(conn, plan_id, item_key, checked):
    conn.execute(
        "INSERT INTO shopping_state (plan_id, item_key, checked) VALUES (?, ?, ?) "
        "ON CONFLICT(plan_id, item_key) DO UPDATE SET checked = excluded.checked",
        (plan_id, item_key, 1 if checked else 0),
    )
    conn.commit()


def uncheck_all(conn, plan_id):
    conn.execute("UPDATE shopping_state SET checked = 0 WHERE plan_id = ?", (plan_id,))
    conn.execute("UPDATE extra_items SET checked = 0 WHERE plan_id = ?", (plan_id,))
    conn.commit()


def add_extra(conn, plan_id, text):
    text = (text or "").strip()
    if text:
        conn.execute("INSERT INTO extra_items (plan_id, text) VALUES (?, ?)", (plan_id, text))
        conn.commit()


def set_extra_checked(conn, extra_id, checked):
    conn.execute("UPDATE extra_items SET checked = ? WHERE id = ?", (1 if checked else 0, extra_id))
    conn.commit()


def delete_extra(conn, extra_id):
    conn.execute("DELETE FROM extra_items WHERE id = ?", (extra_id,))
    conn.commit()


def shopping_list_as_text(lines, extras):
    """Plain-text rendering, for sharing the list to a phone or pasting elsewhere."""
    out = []
    for line in lines:
        qty = line["display_quantity"]
        out.append(f"- {qty} {line['name']}".replace("-  ", "- ") if qty else f"- {line['name']}")
    for extra in extras:
        out.append(f"- {extra['text']}")
    return "\n".join(out)
