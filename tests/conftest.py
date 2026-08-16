import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def client(monkeypatch):
    """A test client backed by a throwaway database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # let the app create it from scratch

    monkeypatch.setenv("RECIPES_DB", path)
    for mod in ("db", "app", "store"):
        sys.modules.pop(mod, None)

    import db as db_mod
    db_mod.DB_PATH = path
    import app as app_mod

    app_mod.app.config["TESTING"] = True
    with app_mod.app.test_client() as c:
        c.application = app_mod.app
        yield c

    try:
        os.unlink(path)
    except OSError:
        pass
