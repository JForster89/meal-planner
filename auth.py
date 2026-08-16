"""Single shared password protecting the whole app.

This is a one-person app, so there are no accounts — just one password held in
the APP_PASSWORD environment variable (a Fly secret in production). Logging in
sets a long-lived signed session cookie so a phone stays logged in between shops.
"""

import os
import secrets
import time
from functools import wraps

from flask import (
    current_app, flash, redirect, render_template, request, session, url_for
)

# Endpoints reachable without logging in.
PUBLIC_ENDPOINTS = {"login", "static", "healthz"}

SESSION_KEY = "authed"
SESSION_DAYS = 90

# Crude in-memory throttle. Enough to make online guessing impractical without
# dragging in a dependency; it resets on restart, which is fine for one user.
_FAILURES = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300


def password():
    return os.environ.get("APP_PASSWORD", "")


def auth_enabled():
    """Auth is off when no password is configured, which keeps local dev simple."""
    return bool(password())


def _client_id():
    # Fly puts the real client IP here; fall back to the socket address.
    return request.headers.get("Fly-Client-IP") or request.remote_addr or "unknown"


def _locked_out(client):
    attempts, first_at = _FAILURES.get(client, (0, 0.0))
    if attempts < _MAX_ATTEMPTS:
        return 0
    remaining = _LOCKOUT_SECONDS - (time.time() - first_at)
    if remaining <= 0:
        _FAILURES.pop(client, None)
        return 0
    return int(remaining)


def _record_failure(client):
    attempts, first_at = _FAILURES.get(client, (0, 0.0))
    if attempts == 0 or time.time() - first_at > _LOCKOUT_SECONDS:
        _FAILURES[client] = (1, time.time())
    else:
        _FAILURES[client] = (attempts + 1, first_at)


def is_logged_in():
    return not auth_enabled() or session.get(SESSION_KEY) is True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def init_auth(app):
    """Require a login for every endpoint except the few public ones."""
    app.permanent_session_lifetime = SESSION_DAYS * 24 * 3600
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Fly terminates TLS and forces HTTPS, so the cookie can be secure there.
        SESSION_COOKIE_SECURE=bool(os.environ.get("FLY_APP_NAME")),
    )

    # Refuse to run unprotected in production. Fly sets FLY_APP_NAME for us, so
    # a deploy that forgets `fly secrets set APP_PASSWORD` fails loudly here
    # rather than quietly serving the data to anyone who finds the URL.
    if os.environ.get("FLY_APP_NAME") and not auth_enabled():
        raise RuntimeError(
            "APP_PASSWORD is not set. Refusing to start unprotected in production. "
            "Run: fly secrets set APP_PASSWORD='...'"
        )

    if not auth_enabled():
        app.logger.warning(
            "APP_PASSWORD not set - the app is running WITHOUT a login. "
            "Fine locally, never on a public URL."
        )

    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if not is_logged_in():
            return redirect(url_for("login", next=request.path))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if is_logged_in():
            return redirect(url_for("index"))

        if request.method == "POST":
            client = _client_id()
            locked = _locked_out(client)
            if locked:
                flash(f"Too many attempts. Try again in {locked // 60 + 1} minutes.", "error")
                return render_template("login.html"), 429

            supplied = request.form.get("password", "")
            if secrets.compare_digest(supplied, password()):
                _FAILURES.pop(client, None)
                session.clear()
                session.permanent = True
                session[SESSION_KEY] = True

                # Only follow same-site relative paths, so a crafted ?next=
                # can't bounce you to another domain after logging in.
                target = request.args.get("next", "")
                if not target.startswith("/") or target.startswith("//"):
                    target = url_for("index")
                return redirect(target)

            _record_failure(client)
            current_app.logger.warning("Failed login from %s", client)
            flash("Wrong password.", "error")

        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Logged out.", "success")
        return redirect(url_for("login"))

    @app.route("/healthz")
    def healthz():
        """Unauthenticated liveness check for Fly."""
        return {"ok": True}
