"""Flask app factory.

Performs defence-in-depth marker validation on every registered base map at
startup. The CI step is the primary guard against shipping a broken SVG;
this catch is for cases where CI was bypassed or the on-disk file changed
between CI and runtime.

The session secret is resolved as: explicit ``secret_key=`` argument
(tests), then ``FLASK_SECRET_KEY`` env var (production deploys with
multiple workers), then a per-process random value (local single-process
dev). The session is purely a UX convenience and no privileged action is
gated by it; load-balanced deploys must set the env var so worker sessions
are interoperable.
"""

from __future__ import annotations

import os
import secrets

from flask import Flask

from app.maps import prime_caches


def create_app(secret_key: str | None = None) -> Flask:
    app = Flask(__name__, static_folder="../static", static_url_path="/static")
    app.config["SECRET_KEY"] = (
        secret_key or os.environ.get("FLASK_SECRET_KEY") or secrets.token_urlsafe(32)
    )

    # Primes the per-map cache and raises if a marker is missing.
    prime_caches()

    from app.routes import bp

    app.register_blueprint(bp)
    return app
