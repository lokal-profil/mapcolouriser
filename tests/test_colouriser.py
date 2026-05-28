import pytest

from app.colouriser import (
    DEFAULT_LAND_COLOUR,
    DEFAULT_OCEAN_COLOUR,
    Group,
    _selector_from_classes,
    build_css,
    build_legend,
)


class TestGroup:
    def test_constructs_with_required_fields(self):
        g = Group(title="Members", colour="#ff0000", country_codes=("se", "de"))
        assert g.title == "Members"
        assert g.colour == "#ff0000"
        assert g.country_codes == ("se", "de")


class TestGroupValidation:
    def test_rejects_dangerous_title_with_angle_bracket(self):
        with pytest.raises(ValueError, match="forbidden"):
            Group(title="evil </style>", colour="#ff0000", country_codes=("se",))

    def test_rejects_dangerous_title_with_comment_terminator(self):
        with pytest.raises(ValueError, match="forbidden"):
            Group(title="*/ ouch", colour="#ff0000", country_codes=("se",))

    def test_rejects_title_with_backslash(self):
        with pytest.raises(ValueError, match="forbidden"):
            Group(title="back\\slash", colour="#ff0000", country_codes=("se",))

    def test_accepts_title_with_unicode_and_punctuation(self):
        # Should accept reasonable label content.
        Group(title="EU members (2024) — Schengen", colour="#003399", country_codes=("se",))

    def test_rejects_invalid_colour(self):
        with pytest.raises(ValueError, match="colour"):
            Group(title="OK", colour="red", country_codes=("se",))

    def test_rejects_short_country_code(self):
        with pytest.raises(ValueError, match="alpha-2"):
            Group(title="OK", colour="#ff0000", country_codes=("s",))

    def test_rejects_uppercase_country_code(self):
        with pytest.raises(ValueError, match="alpha-2"):
            Group(title="OK", colour="#ff0000", country_codes=("SE",))

    def test_rejects_non_alpha_country_code(self):
        with pytest.raises(ValueError, match="alpha-2"):
            Group(title="OK", colour="#ff0000", country_codes=("s1",))

    def test_rejects_duplicate_country_codes(self):
        with pytest.raises(ValueError, match="duplicate"):
            Group(title="OK", colour="#ff0000", country_codes=("se", "se"))

    def test_rejects_empty_country_codes(self):
        with pytest.raises(ValueError, match="empty"):
            Group(title="OK", colour="#ff0000", country_codes=())


class TestBuildCss:
    def test_single_group_produces_comment_and_rule(self):
        css = build_css([Group(title="Members", colour="#ff0000", country_codes=["se"])])
        assert "/* Members */" in css
        assert ".se { fill: #ff0000; }" in css

    def test_multiple_countries_are_comma_separated(self):
        css = build_css([Group(title="EU", colour="#003399", country_codes=["se", "de", "fr"])])
        assert ".se, .de, .fr { fill: #003399; }" in css

    def test_multiple_groups_produce_multiple_rules(self):
        css = build_css(
            [
                Group(title="Members", colour="#ff0000", country_codes=["se", "de"]),
                Group(title="Former members", colour="#cccccc", country_codes=["dk"]),
            ]
        )
        assert "/* Members */" in css
        assert ".se, .de { fill: #ff0000; }" in css
        assert "/* Former members */" in css
        assert ".dk { fill: #cccccc; }" in css

    def test_colour_is_passed_through_unchanged(self):
        css = build_css([Group(title="X", colour="#AbC123", country_codes=["se"])])
        assert "#AbC123" in css

    def test_empty_country_list_raises_valueerror(self):
        with pytest.raises(ValueError, match="empty"):
            build_css([Group(title="X", colour="#ff0000", country_codes=[])])

    def test_empty_groups_list_returns_empty_string(self):
        # A defensible alternative to raising; pin behaviour with a test.
        assert build_css([]) == ""

    def test_non_empty_output_is_wrapped_in_newlines(self):
        # The wrap lets render_map place the snippet on its own lines inside
        # <style>...</style> without each call site re-adding the padding.
        css = build_css([Group(title="X", colour="#ff0000", country_codes=["se"])])
        assert css.startswith("\n")
        assert css.endswith("\n")

    def test_group_order_is_preserved(self):
        css = build_css(
            [
                Group(title="Alpha", colour="#111111", country_codes=["se"]),
                Group(title="Beta", colour="#222222", country_codes=["de"]),
            ]
        )
        assert css.index("/* Alpha */") < css.index("/* Beta */")

    def test_default_omits_opacity_declaration(self):
        groups = [Group(title="X", colour="#ff0000", country_codes=["se"])]
        css = build_css(groups)
        assert "opacity" not in css

    def test_include_small_country_circles_false_omits_opacity_declaration(self):
        groups = [Group(title="X", colour="#ff0000", country_codes=["se"])]
        css = build_css(groups, include_small_country_circles=False)
        assert "opacity" not in css

    def test_include_small_country_circles_true_adds_opacity_declaration(self):
        groups = [Group(title="X", colour="#ff0000", country_codes=["se"])]
        css = build_css(groups, include_small_country_circles=True)
        assert ".se { fill: #ff0000; opacity: 1; }" in css


class TestBuildCssBaseLayers:
    def test_land_emits_comment_and_rule(self):
        css = build_css([], land="#dddddd", land_classes=("landxx", "circlexx"))
        assert "/* Land and small circles */" in css
        assert ".landxx, .circlexx { fill: #dddddd; }" in css

    def test_ocean_emits_comment_and_rule(self):
        css = build_css([], ocean="#0099ff", ocean_classes=("oceanxx",))
        assert "/* Oceans, seas, and large lakes */" in css
        assert ".oceanxx { fill: #0099ff; }" in css

    def test_land_skipped_when_classes_none(self):
        css = build_css([], land="#dddddd", land_classes=None)
        assert "landxx" not in css

    def test_ocean_skipped_when_classes_none(self):
        css = build_css([], ocean="#ffffff", ocean_classes=None)
        assert "oceanxx" not in css

    def test_land_skipped_when_colour_missing(self):
        # Pure routing safety net: build_css is robust if the caller passes
        # classes without a colour (shouldn't happen in practice, but the
        # function shouldn't emit `.landxx { fill: None; }`).
        css = build_css([], land=None, land_classes=("landxx",))
        assert "landxx" not in css

    def test_invalid_land_colour_raises(self):
        with pytest.raises(ValueError, match="land colour"):
            build_css([], land="red", land_classes=("landxx",))

    def test_invalid_ocean_colour_raises(self):
        with pytest.raises(ValueError, match="ocean colour"):
            build_css([], ocean="not-a-hex", ocean_classes=("oceanxx",))

    def test_base_layers_precede_group_blocks(self):
        css = build_css(
            [Group(title="Members", colour="#ff0000", country_codes=["se"])],
            land=DEFAULT_LAND_COLOUR,
            ocean=DEFAULT_OCEAN_COLOUR,
            land_classes=("landxx", "circlexx"),
            ocean_classes=("oceanxx",),
        )
        assert css.index("/* Land and small circles */") < css.index("/* Members */")
        assert css.index("/* Oceans, seas, and large lakes */") < css.index("/* Members */")

    def test_base_layers_omit_opacity_even_with_circles_toggle(self):
        # The circles toggle adds `opacity: 1` to per-group rules so circles
        # for the user's selected countries become visible. The base land/
        # ocean rules don't need opacity — they target the broad strata.
        css = build_css(
            [],
            include_small_country_circles=True,
            land=DEFAULT_LAND_COLOUR,
            land_classes=("landxx", "circlexx"),
        )
        assert "opacity" not in css


class TestSelectorFromClasses:
    def test_single_class(self):
        assert _selector_from_classes(("oceanxx",)) == ".oceanxx"

    def test_multiple_classes(self):
        assert _selector_from_classes(("landxx", "circlexx")) == ".landxx, .circlexx"


class TestBuildLegend:
    def test_single_group_renders_one_legend_line(self):
        legend = build_legend([Group(title="Members", colour="#ff0000", country_codes=["se"])])
        assert legend == "{{Legend|#ff0000|Members}}"

    def test_multiple_groups_are_newline_separated(self):
        legend = build_legend(
            [
                Group(title="A", colour="#ff0000", country_codes=["se"]),
                Group(title="B", colour="#00ff00", country_codes=["de"]),
            ]
        )
        assert legend == "{{Legend|#ff0000|A}}\n{{Legend|#00ff00|B}}"

    def test_empty_groups_list_returns_empty_string(self):
        assert build_legend([]) == ""
