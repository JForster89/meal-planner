"""The static shopping list published to GitHub Pages."""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_static import build_cook_page, build_page, render_items, write_site


def line(name, qty="450 g", key=None, recipes=("Curry",), pantry=False):
    return {
        "key": key or name.lower(), "name": name, "display_quantity": qty,
        "recipes": list(recipes), "is_pantry": pantry, "unit": "g", "quantity": 450,
    }


def test_items_render_with_quantity_and_source():
    out = render_items([line("Potatoes", "450 g", recipes=("Curry", "Pasta"))])
    assert "450 g" in out
    assert "Potatoes" in out
    assert "Curry, Pasta" in out


def test_unquantified_items_omit_the_number():
    out = render_items([line("Sweetcorn", "")])
    assert "Sweetcorn" in out
    assert 'class="qty"' not in out


def test_pantry_items_are_marked():
    assert "cupboard" in render_items([line("Butter", pantry=True)])
    assert "cupboard" not in render_items([line("Potatoes")])


def test_checkbox_carries_the_stable_key():
    """Ticks are keyed by ingredient so republishing keeps them."""
    out = render_items([line("Potatoes", key="potato|g")])
    assert 'data-key="potato|g"' in out


def test_empty_list_says_so():
    assert "Nothing planned" in render_items([])


def test_html_in_names_is_escaped():
    out = render_items([line('<script>alert(1)</script>')])
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_quotes_in_key_cannot_break_the_attribute():
    out = render_items([line("X", key='a" onerror="alert(1)')])
    assert 'onerror="alert(1)"' not in out
    assert "&quot;" in out


def test_page_is_self_contained():
    """No external requests - it has to work with no signal."""
    page = build_page([line("Potatoes")])
    assert "<style>" in page and "<script>" in page
    for pattern in ["src=\"http", "href=\"http", "cdn.", "googleapis"]:
        assert pattern not in page


def test_page_reports_recipe_count():
    page = build_page([line("Potatoes")], recipe_names=["A", "B"])
    assert "2 recipes" in page


def test_write_site_emits_every_file(tmp_path):
    out = str(tmp_path)
    write_site([line("Potatoes")], ["Curry"], out_dir=out)
    for name in ["index.html", "sw.js", "manifest.json", ".nojekyll"]:
        assert os.path.exists(os.path.join(out, name)), name


def test_manifest_is_valid_json_with_relative_urls(tmp_path):
    """GitHub Pages serves project sites from a subpath, so absolute URLs break."""
    out = str(tmp_path)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["start_url"].startswith("./")
    assert manifest["icons"][0]["src"].startswith("./")


def test_page_uses_relative_asset_paths(tmp_path):
    out = str(tmp_path)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    assert 'href="./manifest.json"' in page
    assert "register('./sw.js')" in page
    assert 'href="/manifest.json"' not in page


def test_service_worker_cache_name_changes_per_publish(tmp_path):
    """A fixed cache name would serve last week's list forever."""
    import time
    out = str(tmp_path)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "sw.js"), encoding="utf-8") as fh:
        first = re.search(r"var CACHE = '([^']+)'", fh.read()).group(1)
    time.sleep(1.1)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "sw.js"), encoding="utf-8") as fh:
        second = re.search(r"var CACHE = '([^']+)'", fh.read()).group(1)
    assert first != second


def test_publish_route_writes_the_site(client, tmp_path, monkeypatch):
    import export_static
    import store
    from db import get_db

    monkeypatch.setattr(export_static, "OUT_DIR", str(tmp_path))
    original = export_static.write_site
    monkeypatch.setattr(
        export_static, "write_site",
        lambda lines, names=(), out_dir=None, recipes=():
            original(lines, names, str(tmp_path), recipes),
    )
    # Never let a test commit or push the real repository.
    monkeypatch.setattr(export_static, "git_publish", lambda *a, **k: "stubbed")
    monkeypatch.setattr(export_static, "pages_url", lambda *a, **k: None)

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Curry", "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [{"quantity": 450, "unit": "grams",
                            "name": "Potatoes", "is_pantry": False}]},
            "instructions": [],
        })
    client.post("/plan/add/1", data={"portions": 2})

    assert client.post("/publish").status_code == 302
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    assert "Potatoes" in page
    assert "450 g" in page


# --- cook page --------------------------------------------------------------

RECIPE = {
    "name": "Korma Salmon", "portions": 3, "cooking_time_mins": 35,
    "ingredients": [
        {"display_quantity": "700 g", "name": "Potatoes", "is_pantry": False},
        {"display_quantity": "30 g", "name": "Butter", "is_pantry": True},
    ],
    "steps": ["Preheat the oven.", "Chop the potatoes.", "Bake for 25 minutes."],
}


def test_cook_page_has_a_card_per_step_plus_ingredients():
    from export_static import build_cook_page
    page = build_cook_page([RECIPE])
    assert page.count('class="card"') == len(RECIPE["steps"]) + 1
    assert "Step 1 of 3" in page and "Step 3 of 3" in page


def test_cook_page_shows_ingredients_and_marks_pantry():
    from export_static import build_cook_page
    page = build_cook_page([RECIPE])
    assert "700 g" in page and "Potatoes" in page
    assert "cupboard" in page


def test_single_recipe_opens_straight_into_it():
    """With one meal there's nothing to choose, so don't ask."""
    page = build_cook_page([RECIPE])
    assert 'id="chooser"' not in page
    assert page.count('class="deck"') == 1


def test_several_recipes_ask_which_one_first():
    page = build_cook_page([RECIPE, dict(RECIPE, name="Second Dish")])
    assert 'id="chooser"' in page
    assert "What are you cooking?" in page
    assert page.count('class="pick"') == 2
    assert page.count('class="deck"') == 2
    assert "Second Dish" in page


def test_chooser_entries_summarise_each_recipe():
    page = build_cook_page([RECIPE, dict(RECIPE, name="Second Dish")])
    assert "35 mins" in page
    assert "3 steps" in page
    assert "serves 3" in page


def test_chooser_buttons_carry_their_index():
    page = build_cook_page([RECIPE, dict(RECIPE, name="Second Dish")])
    assert 'data-index="0"' in page
    assert 'data-index="1"' in page


def test_cook_page_routes_on_the_hash():
    """Hash routing means the phone's back button returns to the list."""
    page = build_cook_page([RECIPE, dict(RECIPE, name="Second")])
    assert "hashchange" in page
    assert "location.hash" in page


def test_chooser_escapes_recipe_names():
    page = build_cook_page([
        dict(RECIPE, name='<img src=x onerror=alert(1)>'),
        dict(RECIPE, name="Second"),
    ])
    assert "<img src=x" not in page
    assert "&lt;img" in page


def test_cook_page_handles_missing_method():
    from export_static import build_cook_page
    page = build_cook_page([dict(RECIPE, steps=[])])
    assert "No method saved" in page


def test_cook_page_with_nothing_planned():
    from export_static import build_cook_page
    assert "Nothing planned" in build_cook_page([])


def test_cook_page_escapes_recipe_content():
    from export_static import build_cook_page
    page = build_cook_page([dict(RECIPE, name='<img src=x onerror=alert(1)>',
                                 steps=["<script>bad()</script>"])])
    assert "<img src=x" not in page
    assert "<script>bad()</script>" not in page
    assert "&lt;script&gt;" in page


def test_cook_page_is_self_contained():
    from export_static import build_cook_page
    page = build_cook_page([RECIPE])
    for pattern in ['src="http', 'href="http', "cdn."]:
        assert pattern not in page


def test_write_site_emits_cook_page(tmp_path):
    from export_static import write_site
    write_site([line("Potatoes")], ["Korma Salmon"], out_dir=str(tmp_path), recipes=[RECIPE])
    cook = os.path.join(str(tmp_path), "cook.html")
    assert os.path.exists(cook)
    with open(cook, encoding="utf-8") as fh:
        assert "Korma Salmon" in fh.read()


def test_service_worker_caches_the_cook_page(tmp_path):
    from export_static import write_site
    write_site([line("Potatoes")], out_dir=str(tmp_path), recipes=[RECIPE])
    with open(os.path.join(str(tmp_path), "sw.js"), encoding="utf-8") as fh:
        assert "./cook.html" in fh.read()


def test_shopping_page_links_to_cook_mode():
    from export_static import build_page
    assert './cook.html' in build_page([line("Potatoes")])


# --- one-click publish ------------------------------------------------------

def test_pages_url_derived_from_remote(tmp_path):
    import subprocess
    from export_static import pages_url

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                    "https://github.com/JForster89/meal-planner.git"], check=True)
    assert pages_url(repo) == "https://jforster89.github.io/meal-planner/"


def test_pages_url_handles_ssh_remote(tmp_path):
    import subprocess
    from export_static import pages_url

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                    "git@github.com:JForster89/meal-planner.git"], check=True)
    assert pages_url(repo) == "https://jforster89.github.io/meal-planner/"


def test_pages_url_none_without_remote(tmp_path):
    import subprocess
    from export_static import pages_url

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    assert pages_url(repo) is None


def test_publish_refuses_outside_a_repo(tmp_path):
    from export_static import PublishError, git_publish
    import pytest as _pytest

    with _pytest.raises(PublishError, match="git repository"):
        git_publish(repo_dir=str(tmp_path))


def test_publish_refuses_without_a_remote(tmp_path):
    import subprocess
    from export_static import PublishError, git_publish
    import pytest as _pytest

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    os.makedirs(os.path.join(repo, "docs"), exist_ok=True)
    with _pytest.raises(PublishError, match="origin"):
        git_publish(repo_dir=repo)


def test_publish_reports_when_nothing_changed(tmp_path):
    """Republishing an unchanged list shouldn't make an empty commit."""
    import subprocess
    from export_static import git_publish

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                    "https://example.invalid/x.git"], check=True)
    os.makedirs(os.path.join(repo, "docs"))
    assert "No changes" in git_publish(repo_dir=repo)


def test_publish_only_stages_docs(tmp_path):
    """A half-finished code edit must not ride along with the shopping list."""
    import subprocess
    from export_static import PublishError, git_publish

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                    "https://example.invalid/x.git"], check=True)

    os.makedirs(os.path.join(repo, "docs"))
    with open(os.path.join(repo, "docs", "index.html"), "w") as fh:
        fh.write("<p>list</p>")
    with open(os.path.join(repo, "wip.py"), "w") as fh:
        fh.write("broken = (")

    # The push fails (the remote is bogus), but the commit should have happened.
    try:
        git_publish(repo_dir=repo)
    except PublishError:
        pass

    committed = subprocess.run(
        ["git", "-C", repo, "show", "--name-only", "--format=", "HEAD"],
        capture_output=True, text=True,
    ).stdout.split()
    assert committed == ["docs/index.html"]
    assert "wip.py" not in committed


def test_publish_error_says_the_commit_is_safe(tmp_path):
    import subprocess
    from export_static import PublishError, git_publish
    import pytest as _pytest

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                    "https://example.invalid/x.git"], check=True)
    os.makedirs(os.path.join(repo, "docs"))
    with open(os.path.join(repo, "docs", "index.html"), "w") as fh:
        fh.write("<p>list</p>")

    with _pytest.raises(PublishError, match="local commit is safe"):
        git_publish(repo_dir=repo)


def test_publish_route_reports_a_push_failure(client, tmp_path, monkeypatch):
    """A failed push must say so, not claim the phone was updated."""
    import export_static

    original = export_static.write_site
    monkeypatch.setattr(
        export_static, "write_site",
        lambda lines, names=(), out_dir=None, recipes=():
            original(lines, names, str(tmp_path), recipes),
    )

    def boom(*a, **k):
        raise export_static.PublishError("no network")
    monkeypatch.setattr(export_static, "git_publish", boom)

    resp = client.post("/publish", follow_redirects=True)
    body = resp.get_data(as_text=True)
    # Jinja escapes the apostrophe, so match either form.
    assert "couldn&#39;t publish" in body or "couldn't publish" in body
    assert "no network" in body
    assert "flash error" in body


def test_publish_route_reports_success_with_url(client, tmp_path, monkeypatch):
    import export_static

    original = export_static.write_site
    monkeypatch.setattr(
        export_static, "write_site",
        lambda lines, names=(), out_dir=None, recipes=():
            original(lines, names, str(tmp_path), recipes),
    )
    monkeypatch.setattr(export_static, "git_publish", lambda *a, **k: "Pushed.")
    monkeypatch.setattr(export_static, "pages_url", lambda *a, **k: "https://x.github.io/y/")

    body = client.post("/publish", follow_redirects=True).get_data(as_text=True)
    assert "Pushed." in body
    assert "https://x.github.io/y/" in body


def test_git_calls_are_windowless_on_windows(monkeypatch):
    """Under pythonw each git call would otherwise flash up a cmd window."""
    import subprocess
    import export_static

    monkeypatch.setattr(export_static.sys, "platform", "win32")
    kwargs = export_static._no_window_kwargs()
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    assert kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_no_window_kwargs_empty_off_windows(monkeypatch):
    import export_static

    monkeypatch.setattr(export_static.sys, "platform", "linux")
    assert export_static._no_window_kwargs() == {}


def test_git_still_works_with_the_hidden_window_flags(tmp_path):
    """The flags must not break the call itself."""
    import subprocess
    from export_static import _git

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    result = _git(["rev-parse", "--is-inside-work-tree"], repo)
    assert result.returncode == 0
    assert result.stdout.strip() == "true"


def test_chooser_visible_before_javascript_runs():
    """Otherwise the page is blank until the routing script executes."""
    page = build_cook_page([RECIPE, dict(RECIPE, name="Second")])
    assert "#chooser{display:block" in page
    assert "body.in-recipe #chooser{display:none}" in page


def test_single_recipe_shows_the_step_nav():
    """With no chooser the footer must still appear."""
    page = build_cook_page([RECIPE])
    assert "body.no-chooser footer" in page
    assert "no-chooser" in page
