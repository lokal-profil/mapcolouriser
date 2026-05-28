"""Direct tests for app.maps — the SVG prep/render pipeline."""

from __future__ import annotations

import dataclasses

import pytest

import app.maps as maps_module
from app.maps import (
    MAPS,
    MapInfo,
    load_map,
    map_path,
    prepared_svg,
    prime_caches,
    render_map,
)


@pytest.fixture(autouse=True)
def _clear_prepared_cache():
    maps_module._prepared.cache_clear()
    yield
    maps_module._prepared.cache_clear()


class TestMapPath:
    def test_known_key_returns_static_dir_path(self):
        assert map_path("world").name == "BlankMap-World.svg"

    def test_unknown_key_raises_keyerror(self):
        with pytest.raises(KeyError, match="atlantis"):
            map_path("atlantis")

    def test_default_argument_resolves_to_default_map(self):
        assert map_path() == map_path("world")


class TestLoadMap:
    def test_returns_svg_text(self):
        text = load_map("world")
        assert text.startswith("<?xml")
        assert "<svg" in text
        assert "</svg>" in text


class TestPreparedSvg:
    def test_contains_viewbox(self):
        assert "viewBox=" in prepared_svg("world")

    def test_contains_no_user_style_element(self):
        assert '<style id="map-colouriser-style">' not in prepared_svg("world")

    def test_ends_with_svg_close_tag(self):
        assert prepared_svg("world").rstrip().endswith("</svg>")


class TestRenderMap:
    def test_inserts_user_style_element(self):
        out = render_map("world", ".se { fill: #ff0000; }")
        assert '<style id="map-colouriser-style">.se { fill: #ff0000; }</style>' in out

    def test_style_element_appears_before_closing_svg(self):
        out = render_map("world", ".se { fill: red; }")
        style_idx = out.index('<style id="map-colouriser-style">')
        close_idx = out.rindex("</svg>")
        assert style_idx < close_idx

    def test_empty_css_still_produces_valid_element(self):
        out = render_map("world", "")
        assert '<style id="map-colouriser-style"></style>' in out

    def test_passes_through_multi_rule_css(self):
        css = ".se { fill: red; }\n\n.de { fill: blue; }"
        out = render_map("world", css)
        assert css in out

    def test_render_is_deterministic_for_same_input(self):
        a = render_map("world", ".se { fill: red; }")
        b = render_map("world", ".se { fill: red; }")
        assert a == b

    def test_render_reflects_new_css_on_subsequent_call(self):
        a = render_map("world", ".se { fill: red; }")
        b = render_map("world", ".de { fill: blue; }")
        assert a != b
        assert ".de { fill: blue; }" in b
        assert ".se { fill: red; }" not in b

    def test_unknown_key_raises_keyerror(self):
        with pytest.raises(KeyError, match="atlantis"):
            render_map("atlantis", "")


class TestPrimeCaches:
    def test_populates_prepared_cache_for_every_registered_map(self):
        maps_module._prepared.cache_clear()
        assert maps_module._prepared.cache_info().currsize == 0
        prime_caches()
        assert maps_module._prepared.cache_info().currsize == len(MAPS)


class TestMapsRegistry:
    def test_world_entry_has_expected_filename_and_label(self):
        info = MAPS["world"]
        assert isinstance(info, MapInfo)
        assert info.filename == "BlankMap-World.svg"
        assert info.label == "World"

    def test_world_compact_entry_present(self):
        info = MAPS["world-compact"]
        assert info.filename == "BlankMap-World-Compact.svg"
        assert info.label == "World (compact)"

    def test_map_info_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            MAPS["world"].filename = "tampered.svg"

    def test_map_info_rejects_positional_args(self):
        # kw_only=True — positional construction must fail so a future field
        # addition can't silently rebind argument positions.
        with pytest.raises(TypeError):
            MapInfo("x.svg", "X")  # type: ignore[misc]


class TestMapInfoBaseClassFields:
    def test_default_land_classes(self):
        info = MapInfo(filename="x.svg", label="X")
        assert info.land_classes == ("landxx", "circlexx")

    def test_default_ocean_classes(self):
        info = MapInfo(filename="x.svg", label="X")
        assert info.ocean_classes == ("oceanxx",)

    def test_opt_out_with_none(self):
        # A future map with no ocean equivalent declares ocean_classes=None;
        # the picker hides and build_css skips the rule.
        info = MapInfo(filename="x.svg", label="X", ocean_classes=None)
        assert info.ocean_classes is None

    def test_empty_tuple_rejected(self):
        with pytest.raises(ValueError, match="non-empty tuple"):
            MapInfo(filename="x.svg", label="X", land_classes=())

    def test_invalid_class_name_rejected(self):
        with pytest.raises(ValueError, match="valid CSS class name"):
            MapInfo(filename="x.svg", label="X", land_classes=("9bad",))

    def test_class_name_with_leading_dot_rejected(self):
        # Field stores bare class names; the leading "." is added by
        # _selector_from_classes at build time.
        with pytest.raises(ValueError, match="valid CSS class name"):
            MapInfo(filename="x.svg", label="X", land_classes=(".landxx",))

    def test_world_compact_keeps_defaults(self):
        # Both shipped maps share the canonical SVG class names today; the
        # base-colour pickers must apply to either.
        assert MAPS["world-compact"].land_classes == ("landxx", "circlexx")
        assert MAPS["world-compact"].ocean_classes == ("oceanxx",)
