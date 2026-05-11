"""Startup defence-in-depth: ``create_app()`` must reject base maps that
are missing the injection marker."""

from __future__ import annotations

import pytest

import app.maps as maps_module
from app import create_app


@pytest.fixture(autouse=True)
def _clear_prepared_cache():
    # ``_prepared`` is module-level @cache; invalid entries from one test
    # would otherwise poison subsequent tests.
    maps_module._prepared.cache_clear()
    yield
    maps_module._prepared.cache_clear()


def test_raises_when_base_map_missing_marker(monkeypatch, tmp_path):
    bad = tmp_path / "bad.svg"
    bad.write_text("<svg><style>/* no marker here */</style></svg>")

    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    monkeypatch.setattr(maps_module, "MAPS", {"bad": "bad.svg"})

    with pytest.raises(RuntimeError, match="injection marker"):
        create_app(secret_key="test-secret")


def test_raises_when_base_map_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    monkeypatch.setattr(maps_module, "MAPS", {"absent": "missing.svg"})

    with pytest.raises(FileNotFoundError):
        create_app(secret_key="test-secret")


def test_real_world_map_starts_cleanly():
    # Sanity: the registered base map validates and create_app succeeds.
    app = create_app(secret_key="test-secret")
    assert app is not None


class TestSecretKey:
    def test_uses_explicit_secret_key_when_provided(self, monkeypatch):
        # Explicit arg wins over env var.
        monkeypatch.setenv("FLASK_SECRET_KEY", "env-secret")
        app = create_app(secret_key="explicit-secret")
        assert app.config["SECRET_KEY"] == "explicit-secret"

    def test_reads_secret_key_from_env(self, monkeypatch):
        monkeypatch.setenv("FLASK_SECRET_KEY", "env-secret")
        app = create_app()
        assert app.config["SECRET_KEY"] == "env-secret"

    def test_generates_random_key_when_no_arg_or_env(self, monkeypatch):
        monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
        app1 = create_app()
        app2 = create_app()
        # Both apps have a usable key, and each gets its own.
        assert isinstance(app1.config["SECRET_KEY"], str)
        assert len(app1.config["SECRET_KEY"]) >= 32
        assert app1.config["SECRET_KEY"] != app2.config["SECRET_KEY"]
