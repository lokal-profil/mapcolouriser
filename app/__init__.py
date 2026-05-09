"""Flask app factory.

Performs defence-in-depth marker validation on every registered base map at
startup. The CI step is the primary guard against shipping a broken SVG;
this catch is for cases where CI was bypassed or the on-disk file changed
between CI and runtime.

The session secret defaults to a per-process random value. The session is
purely a UX convenience (back-to-form repopulation and ``/download``
lookup); no privileged action is gated by it, so cookies invalidating on
process restart is acceptable. Pass ``secret_key=`` (or wire the deployment
to do so) if you need cookies to survive across worker restarts or be
shared across load-balanced workers.
"""

from __future__ import annotations

import secrets

from flask import Flask

from app.maps import prime_caches


def create_app(secret_key: str | None = None) -> Flask:
    app = Flask(__name__, static_folder="../static", static_url_path="/static")
    app.config["SECRET_KEY"] = secret_key or secrets.token_urlsafe(32)

    # Primes the per-map cache and raises if a marker is missing.
    prime_caches()

    from app.routes import bp

    app.register_blueprint(bp)
    return app
