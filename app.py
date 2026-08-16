"""Hello Fresh meal planner: pick a week's recipes, get one merged shopping list."""

import os

from flask import (
    Flask, Response, flash, g, jsonify, redirect, render_template, request, url_for
)

import hellofresh
import store
from aggregate import format_quantity
from auth import init_auth
from db import close_db, get_db, init_db


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
    app.teardown_appcontext(close_db)

    @app.template_filter("quantity")
    def _quantity(qty, unit="", multiplier=1.0):
        if qty is None:
            return ""
        return format_quantity(qty * multiplier, unit or "")

    @app.template_filter("quantity_number")
    def _quantity_number(qty):
        """Bare number for form fields: 450.0 -> '450', 0.5 -> '0.5'."""
        if qty is None:
            return ""
        return str(int(qty)) if float(qty).is_integer() else f"{qty:g}"

    @app.context_processor
    def _template_globals():
        from auth import auth_enabled
        return {"auth_enabled": auth_enabled()}

    with app.app_context():
        migrated = init_db()
        if migrated:
            app.logger.info("Migrated %d recipe(s) from the legacy schema", migrated)
        # Recipes saved before tagging existed still group correctly.
        filled = store.backfill_proteins(get_db())
        if filled:
            app.logger.info("Derived a protein for %d existing recipe(s)", filled)

    register_routes(app)
    # Registered last so its before_request guard covers every route above.
    init_auth(app)
    return app


def register_routes(app):

    @app.route("/")
    def index():
        conn = get_db()
        plan = store.get_active_plan(conn)
        entries = store.plan_entries(conn, plan["id"])
        lines, extras = store.build_shopping_list(conn, plan["id"])
        return render_template(
            "plan.html",
            plan=plan,
            entries=entries,
            recipes=store.list_recipes(conn),
            item_count=len(lines) + len(extras),
            default_portions=store.default_portions(conn),
        )

    # --- recipe library -----------------------------------------------------

    @app.route("/recipes")
    def recipes():
        conn = get_db()
        plan = store.get_active_plan(conn)
        planned = {e["recipe_id"] for e in store.plan_entries(conn, plan["id"])}

        query = (request.args.get("q") or "").strip()
        tag = (request.args.get("tag") or "").strip()
        protein = (request.args.get("protein") or "").strip()
        group_by = request.args.get("group", "protein")

        found = store.search_recipes(conn, query or None, tag or None, protein or None)
        tags_by_recipe = store.tags_for_recipes(conn)

        # Group into an ordered mapping the template can just iterate.
        groups = {}
        if group_by in ("protein", "cuisine"):
            for recipe in found:
                labels = [
                    t["tag"] for t in tags_by_recipe.get(recipe["id"], [])
                    if t["kind"] == group_by
                ] or ["Other"]
                groups.setdefault(labels[0], []).append(recipe)
            groups = dict(sorted(groups.items(), key=lambda kv: (kv[0] == "Other", kv[0])))
        else:
            groups = {"": list(found)}

        return render_template(
            "recipes.html",
            groups=groups,
            total=len(found),
            planned=planned,
            tags_by_recipe=tags_by_recipe,
            proteins=store.all_tags(conn, "protein"),
            tag_options=store.all_tags(conn, "tag"),
            q=query, active_tag=tag, active_protein=protein, group_by=group_by,
        )

    @app.route("/recipes/<int:recipe_id>")
    def recipe_detail(recipe_id):
        conn = get_db()
        portions = request.args.get("portions", type=int)
        recipe = store.get_recipe(conn, recipe_id, portions)
        if not recipe:
            return render_template("404.html"), 404
        return render_template("recipe_detail.html", recipe=recipe)

    @app.route("/recipes/new", methods=["GET", "POST"])
    def recipe_new():
        if request.method == "POST":
            data = _recipe_from_form(request.form)
            if not data["name"]:
                flash("Give the recipe a name.", "error")
                return render_template("recipe_form.html", recipe=None, form=request.form)
            recipe_id = store.save_recipe(get_db(), data)
            flash("Recipe saved.", "success")
            return redirect(url_for("recipe_detail", recipe_id=recipe_id))
        return render_template("recipe_form.html", recipe=None, form=None)

    @app.route("/recipes/<int:recipe_id>/edit", methods=["GET", "POST"])
    def recipe_edit(recipe_id):
        conn = get_db()
        recipe = store.get_recipe(conn, recipe_id)
        if not recipe:
            return render_template("404.html"), 404

        if request.method == "POST":
            data = _recipe_from_form(request.form)
            if not data["name"]:
                flash("Give the recipe a name.", "error")
                return render_template("recipe_form.html", recipe=recipe, form=request.form)
            data["source_url"] = recipe["source_url"]
            store.save_recipe(conn, data, recipe_id=recipe_id)
            flash("Recipe updated.", "success")
            return redirect(url_for("recipe_detail", recipe_id=recipe_id))

        return render_template("recipe_form.html", recipe=recipe, form=None)

    @app.route("/recipes/<int:recipe_id>/delete", methods=["POST"])
    def recipe_delete(recipe_id):
        conn = get_db()
        recipe = conn.execute(
            "SELECT name FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
        if not recipe:
            return render_template("404.html"), 404

        store.delete_recipe(conn, recipe_id)
        flash(f"Deleted “{recipe['name']}”.", "success")

        # Return to the filtered list the delete was made from, but only ever
        # to a same-site path.
        target = request.form.get("next", "")
        if target.startswith("/") and not target.startswith("//"):
            return redirect(target)
        return redirect(url_for("recipes"))

    # --- import -------------------------------------------------------------

    @app.route("/import", methods=["GET", "POST"])
    def import_recipe():
        if request.method == "POST":
            url = request.form.get("url", "").strip()
            conn = get_db()
            try:
                data = hellofresh.import_recipe(url)
            except hellofresh.ImportError_ as exc:
                flash(str(exc), "error")
                return render_template("import.html", url=url)

            existing = store.find_by_source_url(conn, data["source_url"])
            recipe_id = store.save_recipe(
                conn, data, recipe_id=existing["id"] if existing else None
            )
            flash(
                f"{'Updated' if existing else 'Imported'} “{data['name']}” "
                f"({len(data['yields'])} portion size"
                f"{'s' if len(data['yields']) != 1 else ''}).",
                "success",
            )
            return redirect(url_for("recipe_detail", recipe_id=recipe_id))
        return render_template("import.html", url="")

    # --- weekly plan --------------------------------------------------------

    @app.route("/plan/add/<int:recipe_id>", methods=["POST"])
    def plan_add(recipe_id):
        conn = get_db()
        plan = store.get_active_plan(conn)
        store.add_to_plan(conn, plan["id"], recipe_id, request.form.get("portions", type=int))
        return redirect(request.referrer or url_for("index"))

    @app.route("/plan/remove/<int:recipe_id>", methods=["POST"])
    def plan_remove(recipe_id):
        conn = get_db()
        plan = store.get_active_plan(conn)
        store.remove_from_plan(conn, plan["id"], recipe_id)
        return redirect(request.referrer or url_for("index"))

    @app.route("/plan/portions/<int:recipe_id>", methods=["POST"])
    def plan_portions(recipe_id):
        conn = get_db()
        plan = store.get_active_plan(conn)
        portions = max(1, request.form.get("portions", type=int) or 2)
        store.set_portions(conn, plan["id"], recipe_id, portions)
        return redirect(url_for("index"))

    @app.route("/plan/default-portions", methods=["POST"])
    def plan_default_portions():
        """Set the household size, and apply it to everything already planned."""
        conn = get_db()
        plan = store.get_active_plan(conn)
        portions = max(1, request.form.get("portions", type=int) or 2)
        store.set_setting(conn, store.DEFAULT_PORTIONS_KEY, portions)

        for entry in store.plan_entries(conn, plan["id"]):
            store.set_portions(conn, plan["id"], entry["recipe_id"], portions)

        flash(f"Now cooking for {portions}.", "success")
        return redirect(url_for("index"))

    @app.route("/plan/clear", methods=["POST"])
    def plan_clear():
        conn = get_db()
        plan = store.get_active_plan(conn)
        store.clear_plan(conn, plan["id"])
        flash("Week cleared.", "success")
        return redirect(url_for("index"))

    # --- shopping list ------------------------------------------------------

    @app.route("/shopping")
    def shopping():
        conn = get_db()
        plan = store.get_active_plan(conn)
        include_pantry = request.args.get("pantry") == "1"
        lines, extras = store.build_shopping_list(conn, plan["id"], include_pantry)
        remaining = sum(1 for l in lines if not l["checked"]) + sum(
            1 for e in extras if not e["checked"]
        )
        return render_template(
            "shopping.html",
            plan=plan,
            lines=lines,
            extras=extras,
            include_pantry=include_pantry,
            remaining=remaining,
            total=len(lines) + len(extras),
        )

    @app.route("/shopping/toggle", methods=["POST"])
    def shopping_toggle():
        conn = get_db()
        plan = store.get_active_plan(conn)
        payload = request.get_json(silent=True) or request.form
        checked = str(payload.get("checked")).lower() in ("1", "true", "on", "yes")

        if payload.get("extra_id"):
            store.set_extra_checked(conn, int(payload["extra_id"]), checked)
        else:
            store.set_checked(conn, plan["id"], payload.get("key", ""), checked)

        if request.is_json:
            return jsonify({"ok": True})
        return redirect(url_for("shopping"))

    @app.route("/shopping/extra", methods=["POST"])
    def shopping_extra():
        conn = get_db()
        plan = store.get_active_plan(conn)
        store.add_extra(conn, plan["id"], request.form.get("text", ""))
        return redirect(url_for("shopping"))

    @app.route("/shopping/extra/<int:extra_id>/delete", methods=["POST"])
    def shopping_extra_delete(extra_id):
        store.delete_extra(get_db(), extra_id)
        return redirect(url_for("shopping"))

    @app.route("/shopping/reset", methods=["POST"])
    def shopping_reset():
        conn = get_db()
        plan = store.get_active_plan(conn)
        store.uncheck_all(conn, plan["id"])
        flash("All items unticked.", "success")
        return redirect(url_for("shopping"))

    @app.route("/publish", methods=["POST"])
    def publish():
        """Render the list into docs/ for GitHub Pages. Local use only."""
        import export_static

        conn = get_db()
        plan = store.get_active_plan(conn)
        include_pantry = request.form.get("pantry") == "1"
        lines, _ = store.build_shopping_list(conn, plan["id"], include_pantry)
        names = [e["name"] for e in store.plan_entries(conn, plan["id"])]
        recipes = export_static.collect_planned_recipes(conn, plan["id"])

        try:
            export_static.write_site(lines, names, recipes=recipes)
        except OSError as exc:
            flash(f"Couldn't write the files: {exc}", "error")
            return redirect(url_for("shopping"))

        built = f"{len(lines)} items and {len(recipes)} cook card{'s' if len(recipes) != 1 else ''}"

        # Pushing is what actually gets it onto the phone, so do it here rather
        # than leaving a git command as homework.
        try:
            status = export_static.git_publish()
        except export_static.PublishError as exc:
            flash(f"Built {built}, but couldn't publish: {exc}", "error")
            return redirect(url_for("shopping"))

        url = export_static.pages_url()
        flash(
            f"Published {built}. {status}" + (f" {url}" if url else ""),
            "success",
        )
        return redirect(url_for("shopping"))

    @app.route("/shopping.txt")
    def shopping_text():
        conn = get_db()
        plan = store.get_active_plan(conn)
        include_pantry = request.args.get("pantry") == "1"
        lines, extras = store.build_shopping_list(conn, plan["id"], include_pantry)
        return Response(
            store.shopping_list_as_text(lines, extras) + "\n",
            mimetype="text/plain; charset=utf-8",
        )

    @app.errorhandler(404)
    def not_found(_exc):
        return render_template("404.html"), 404


def _recipe_from_form(form):
    """Build a recipe dict from the manual add/edit form.

    The form captures one portion size; imported recipes may hold several.
    """
    try:
        servings = max(1, int(form.get("servings") or 2))
    except ValueError:
        servings = 2

    cooking_time = form.get("cooking_time_mins", "").strip()
    try:
        cooking_time = int(cooking_time) if cooking_time else None
    except ValueError:
        cooking_time = None

    quantities = form.getlist("ingredient_quantity[]")
    units = form.getlist("ingredient_unit[]")
    names = form.getlist("ingredient_name[]")
    # One hidden 0/1 per ingredient row, so the flag stays aligned with its row
    # even after rows are added or deleted client-side.
    pantry = form.getlist("ingredient_pantry[]")
    pantry += ["0"] * (len(names) - len(pantry))

    items = []
    for pos, (qty_raw, unit, name) in enumerate(zip(quantities, units, names)):
        if not name.strip():
            continue
        try:
            qty = float(qty_raw.replace(",", ".")) if qty_raw.strip() else None
        except ValueError:
            qty = None
        items.append(
            {
                "quantity": qty,
                "unit": unit.strip(),
                "name": name.strip(),
                "is_pantry": pantry[pos] == "1",
                "position": pos,
            }
        )

    return {
        "name": form.get("name", "").strip(),
        "cooking_time_mins": cooking_time,
        "servings": servings,
        "source_url": None,
        "yields": {servings: items},
        "instructions": [t for t in form.getlist("instruction[]") if t.strip()],
    }


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
