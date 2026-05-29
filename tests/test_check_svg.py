"""Tests for the CI SVG-validation script.

Covers the exit paths: real map (exit 0), malformed SVG (exit 1),
file not found (exit 1), and a declared land/ocean class that is absent
from the SVG (exit 1).
"""

from __future__ import annotations

import pytest

import app.maps as maps_module
from app.maps import MapInfo
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
    bad_map = {"bad": MapInfo(filename="bad.svg", label="bad")}
    monkeypatch.setattr(maps_module, "MAPS", bad_map)
    monkeypatch.setattr(check_svg, "MAPS", bad_map)

    rc = check_svg.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err
    assert "well-formed SVG" in captured.err


def test_missing_file_exits_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    absent_map = {"absent": MapInfo(filename="missing.svg", label="absent")}
    monkeypatch.setattr(maps_module, "MAPS", absent_map)
    monkeypatch.setattr(check_svg, "MAPS", absent_map)

    rc = check_svg.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err


def test_declared_class_absent_from_svg_exits_nonzero(monkeypatch, tmp_path, capsys):
    # Well-formed SVG that uses `.landxx` but NOT the declared `oceanxx` —
    # a typo'd-but-valid class name MapInfo can't catch.
    good = tmp_path / "typo.svg"
    good.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path class="landxx se"/></svg>')

    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    typo_map = {
        "typo": MapInfo(
            filename="typo.svg",
            label="typo",
            land_classes=("landxx",),
            ocean_classes=("oceanxx",),  # not present in the SVG
        )
    }
    monkeypatch.setattr(maps_module, "MAPS", typo_map)
    monkeypatch.setattr(check_svg, "MAPS", typo_map)

    rc = check_svg.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err
    assert "oceanxx" in captured.err
    # The class that IS present must not be reported.
    assert "landxx" not in captured.err


def test_single_quoted_class_attribute_is_recognised(monkeypatch, tmp_path, capsys):
    # XML permits class='…'; the token scan must accept it, else a legitimate
    # single-quoted SVG would FAIL with a spurious "class not found".
    good = tmp_path / "single.svg"
    good.write_text("<svg xmlns='http://www.w3.org/2000/svg'><path class='landxx oceanxx'/></svg>")

    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    sq_map = {
        "sq": MapInfo(
            filename="single.svg",
            label="sq",
            land_classes=("landxx",),
            ocean_classes=("oceanxx",),
        )
    }
    monkeypatch.setattr(maps_module, "MAPS", sq_map)
    monkeypatch.setattr(check_svg, "MAPS", sq_map)

    rc = check_svg.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert captured.err == ""


def test_partial_missing_reports_only_absent_class(monkeypatch, tmp_path, capsys):
    # One declared class present, one absent — only the absent one is reported.
    good = tmp_path / "partial.svg"
    good.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path class="landxx se"/></svg>')

    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    partial_map = {
        "partial": MapInfo(
            filename="partial.svg",
            label="partial",
            land_classes=("landxx", "lnadxx"),  # second is a typo, absent
            ocean_classes=None,
        )
    }
    monkeypatch.setattr(maps_module, "MAPS", partial_map)
    monkeypatch.setattr(check_svg, "MAPS", partial_map)

    rc = check_svg.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "lnadxx" in captured.err
    assert "landxx" not in captured.err  # the present class is not reported


def test_opted_out_class_none_is_not_required(monkeypatch, tmp_path, capsys):
    # A map with ocean_classes=None must not be failed for lacking an ocean.
    good = tmp_path / "land-only.svg"
    good.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path class="landxx se"/></svg>')

    monkeypatch.setattr(maps_module, "STATIC_DIR", tmp_path)
    land_only = {
        "land-only": MapInfo(
            filename="land-only.svg",
            label="land-only",
            land_classes=("landxx",),
            ocean_classes=None,
        )
    }
    monkeypatch.setattr(maps_module, "MAPS", land_only)
    monkeypatch.setattr(check_svg, "MAPS", land_only)

    rc = check_svg.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert captured.err == ""
