"""Tests for the CI SVG-validation script.

Covers all three exit paths: real map (exit 0), malformed SVG (exit 1),
file not found (exit 1).
"""

from __future__ import annotations

import pytest

import app.maps as maps_module
from scripts import check_svg


@pytest.fixture(autouse=True)
def _clear_prepared_cache():
    maps_module._prepared.cache_clear()
    yield
    maps_module._prepared.cache_clear()


def test_real_map_exits_zero(capsys):
    rc = check_svg.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert captured.err == ""


def test_malformed_svg_exits_nonzero(monkeypatch, tmp_path, capsys):
    bad = tmp_path / "bad.svg"
    bad.write_text("<svg><unclosed></svg>")  # malformed XML

    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    monkeypatch.setattr(maps_module, "MAPS", {"bad": "bad.svg"})
    monkeypatch.setattr(check_svg, "MAPS", {"bad": "bad.svg"})

    rc = check_svg.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err
    assert "well-formed SVG" in captured.err


def test_missing_file_exits_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    monkeypatch.setattr(maps_module, "MAPS", {"absent": "missing.svg"})
    monkeypatch.setattr(check_svg, "MAPS", {"absent": "missing.svg"})

    rc = check_svg.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err
