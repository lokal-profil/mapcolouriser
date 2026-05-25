import pytest

from app.colouriser import Group, build_css


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
