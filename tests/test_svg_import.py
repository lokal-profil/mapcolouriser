"""Tests for app.svg_import — recovering form state from a generated SVG."""

from __future__ import annotations

import pytest

from app.colouriser import Group, build_css
from app.maps import DEFAULT_MAP, MAPS, render_map
from app.svg_import import import_svg

_CODES = frozenset({"se", "no", "de", "at"})


def _render(map_key, groups, *, circles=False, land=None, ocean=None):
    """Build the CSS for ``groups`` and inject it into ``map_key``'s SVG."""
    info = MAPS[map_key]
    css = build_css(
        groups,
        include_small_country_circles=circles,
        land=land,
        ocean=ocean,
        land_classes=info.land_classes,
        ocean_classes=info.ocean_classes,
    )
    return render_map(map_key, css)


class TestRoundTrip:
    @pytest.mark.parametrize("map_key", list(MAPS))
    def test_recovers_every_field(self, map_key):
        groups = [
            Group("Nordics", "#332288", ("se", "no")),
            Group("DACH", "#88ccee", ("de", "at")),
        ]
        svg = _render(map_key, groups, circles=True, land="#abcdef", ocean="#123456")

        result = import_svg(svg, valid_codes=_CODES)

        assert result.warnings == []
        assert result.map_key == map_key
        assert result.land_colour == "#abcdef"
        assert result.ocean_colour == "#123456"
        assert result.include_circles is True
        assert result.groups == [
            {"index": 0, "title": "Nordics", "colour": "#332288", "countries": ["se", "no"]},
            {"index": 1, "title": "DACH", "colour": "#88ccee", "countries": ["de", "at"]},
        ]

    def test_circles_off_is_recovered_as_false(self):
        svg = _render("world", [Group("A", "#332288", ("se",))], circles=False)
        assert import_svg(svg, valid_codes=_CODES).include_circles is False


class TestBaseMapFallback:
    def test_missing_data_map_falls_back_to_default(self):
        svg = _render("world", [Group("A", "#332288", ("se",))], circles=True, land="#abcdef")
        stripped = svg.replace(' data-map="world"', "")

        result = import_svg(stripped, valid_codes=_CODES)

        assert result.map_key == DEFAULT_MAP
        # Land/ocean and circles are still recovered on the fallback path: the
        # block classes overlap the fallback map's declared classes, and
        # circles is CSS-intrinsic.
        assert result.land_colour == "#abcdef"
        assert result.include_circles is True
        assert [g["countries"] for g in result.groups] == [["se"]]
        # Exactly one warning — the base-map one; the land/ocean blocks must
        # not be flagged as unrecognized.
        assert len(result.warnings) == 1
        assert "data-map" in result.warnings[0]

    def test_unrecognized_data_map_falls_back_to_default(self):
        svg = _render("world", [Group("A", "#332288", ("se",))], land="#abcdef")
        renamed = svg.replace('data-map="world"', 'data-map="future-map-key"')

        result = import_svg(renamed, valid_codes=_CODES)

        assert result.map_key == DEFAULT_MAP
        assert result.land_colour == "#abcdef"
        assert [g["countries"] for g in result.groups] == [["se"]]
        assert result.warnings == ["Unrecognized base map 'future-map-key' — defaulting to World."]

    def test_sibling_map_fallback_restores_base_colours(self):
        # world-compact declares a land class (limitxx) the fallback map
        # doesn't; overlap-based classification still recovers both colours.
        svg = _render(
            "world-compact", [Group("A", "#332288", ("se",))], land="#abcdef", ocean="#123456"
        )
        stripped = svg.replace(' data-map="world-compact"', "")

        result = import_svg(stripped, valid_codes=_CODES)

        assert result.map_key == DEFAULT_MAP
        assert result.land_colour == "#abcdef"
        assert result.ocean_colour == "#123456"


class TestCodeValidation:
    def test_group_with_only_unknown_codes_is_skipped(self):
        svg = _render("world", [Group("Bogus", "#332288", ("zz",))])
        result = import_svg(svg, valid_codes=_CODES)

        assert result.groups == []
        assert "Skipped group 'Bogus': no recognized country codes." in result.warnings

    def test_mixed_codes_keep_valid_and_discard_unknown(self):
        # 'alsaf' can't be built via Group (it enforces alpha-2), so inject the
        # hand-edited selector directly.
        svg = render_map("world", "\n/* Mix */\n.alsaf, .se { fill: #332288; }\n")
        result = import_svg(svg, valid_codes=_CODES)

        assert [g["countries"] for g in result.groups] == [["se"]]
        assert result.groups[0]["title"] == "Mix"
        assert "Group 'Mix': discarded unrecognized country code(s): alsaf." in result.warnings

    def test_unknown_code_accepted_under_shape_only_mode(self):
        svg = _render("world", [Group("Bogus", "#332288", ("zz",))])
        result = import_svg(svg)  # valid_codes=None → shape check only

        assert [g["countries"] for g in result.groups] == [["zz"]]


class TestOptionalSemicolons:
    def test_block_without_trailing_semicolon(self):
        svg = render_map("world", "\n/* A */\n.se { fill: #332288 }\n")
        result = import_svg(svg, valid_codes=_CODES)

        assert result.groups[0]["colour"] == "#332288"
        assert result.warnings == []

    def test_minified_block_with_opacity_recovers_circles(self):
        svg = render_map("world", "/* A */.se{fill:#332288;opacity:1}")
        result = import_svg(svg, valid_codes=_CODES)

        assert result.include_circles is True
        assert result.groups[0]["colour"] == "#332288"
        assert result.warnings == []

    def test_svgo_shaped_round_trip(self):
        # A generated file after an optimizer pass: whitespace collapsed,
        # trailing semicolons stripped, colours shortened to #rgb.
        css = (
            "/* Land and small circles */.landxx,.circlexx{fill:#ddd}"
            "/* Oceans, seas, and large lakes */.oceanxx{fill:#fff}"
            "/* A */.se,.no{fill:#332288;opacity:1}"
            "/* B */.de{fill:#4a9;opacity:1}"
        )
        result = import_svg(render_map("world", css), valid_codes=_CODES)

        assert result.warnings == []
        assert result.land_colour == "#dddddd"
        assert result.ocean_colour == "#ffffff"
        assert result.include_circles is True
        assert result.groups == [
            {"index": 0, "title": "A", "colour": "#332288", "countries": ["se", "no"]},
            {"index": 1, "title": "B", "colour": "#44aa99", "countries": ["de"]},
        ]


class TestColourValidation:
    def test_short_hex_is_expanded(self):
        svg = render_map("world", "\n/* A */\n.se { fill: #000; }\n")
        result = import_svg(svg, valid_codes=_CODES)

        assert result.groups[0]["colour"] == "#000000"
        assert result.warnings == []

    def test_short_hex_land_and_ocean_are_expanded(self):
        css = (
            "\n/* Land and small circles */\n.landxx, .circlexx { fill: #ddd; }\n"
            "\n/* Oceans, seas, and large lakes */\n.oceanxx { fill: #fff; }\n"
            "\n/* A */\n.se { fill: #332288; }\n"
        )
        result = import_svg(render_map("world", css), valid_codes=_CODES)

        assert result.land_colour == "#dddddd"
        assert result.ocean_colour == "#ffffff"
        assert result.warnings == []

    def test_invalid_colour_keeps_group_with_default(self):
        svg = render_map("world", "\n/* Broken */\n.se { fill: #88csscee; }\n")
        result = import_svg(svg, valid_codes=_CODES)

        # The group survives with an empty colour (the form assigns a palette
        # default); the warning names the group and the bad value.
        assert result.groups == [{"index": 0, "title": "Broken", "colour": "", "countries": ["se"]}]
        assert result.warnings == [
            "Group 'Broken': colour '#88csscee' isn't a #rrggbb colour — "
            "a default colour will be used."
        ]

    def test_invalid_land_colour_is_ignored_with_warning(self):
        css = "\n/* Land and small circles */\n.landxx, .circlexx { fill: bogus; }\n"
        result = import_svg(render_map("world", css), valid_codes=_CODES)

        assert result.land_colour is None
        assert any("land colour" in w and "bogus" in w for w in result.warnings)

    def test_unparsable_block_warning_includes_the_ignored_styling(self):
        # No fill rule at all — the block regex can't match it, so the
        # leftover-span safety net has to speak up and show what was dropped.
        css = "\n/* Ghost */\n.se { stroke: #000000; }\n\n/* A */\n.no { fill: #332288; }\n"
        result = import_svg(render_map("world", css), valid_codes=_CODES)

        assert [g["title"] for g in result.groups] == ["A"]
        warning = next(w for w in result.warnings if "couldn't be understood" in w)
        assert "/* Ghost */ .se { stroke: #000000; }" in warning

    def test_unparsable_styling_snippet_is_truncated(self):
        css = "\n/* Ghost */\n.se { stroke: #000000; }\n" + "junk " * 200
        result = import_svg(render_map("world", css), valid_codes=_CODES)

        warning = next(w for w in result.warnings if "couldn't be understood" in w)
        assert "…" in warning
        assert len(warning) < 300

    def test_mixed_validity_example_recovers_all_three_groups(self):
        # The reported edge case: #000 shorthand, an invalid colour, and a
        # valid colour — all three groups must survive.
        css = (
            "\n/* Land and small circles */\n.landxx, .circlexx { fill: #dddddd; }\n"
            "\n/* Oceans, seas, and large lakes */\n.oceanxx { fill: #ffffff; }\n"
            "\n/* Map 1 */\n.af, .ao { fill: #000; }\n"
            "\n/* Map 2 */\n.al, .dz { fill: #88csscee; }\n"
            "\n/* map 3 */\n.br { fill: #44aa99; }\n"
        )
        codes = frozenset({"af", "ao", "al", "dz", "br"})
        result = import_svg(render_map("world", css), valid_codes=codes)

        assert [g["colour"] for g in result.groups] == ["#000000", "", "#44aa99"]
        assert [g["countries"] for g in result.groups] == [["af", "ao"], ["al", "dz"], ["br"]]


class TestRejectedInput:
    def test_non_svg_returns_not_valid_warning(self):
        result = import_svg("not xml at all <<<")
        assert result.map_key == DEFAULT_MAP
        assert result.groups == []
        assert result.warnings == ["Not a valid SVG file."]

    def test_billion_laughs_is_rejected_not_raised(self):
        bomb = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;">]>'
            "<svg>&lol2;</svg>"
        )
        result = import_svg(bomb)
        assert result.warnings == ["Not a valid SVG file."]

    def test_valid_svg_without_marker_reports_no_data(self):
        result = import_svg('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        assert result.groups == []
        assert result.warnings == ["No map-colouriser data found in this file."]

    def test_marker_present_but_no_groups(self):
        svg = render_map("world", "")
        result = import_svg(svg, valid_codes=_CODES)
        assert result.groups == []
        assert any("No groups could be recovered" in w for w in result.warnings)
