import io
import re
from html.parser import HTMLParser

import pytest
from markupsafe import escape

from app import routes
from app.colouriser import Group, build_css
from app.maps import MAPS, render_map

# The injected user-CSS <style> element, capturing its body. The opening tag
# carries attributes (id + data-map), so match up to the first '>'.
_USER_STYLE_RE = re.compile(r'<style id="map-colouriser-style"[^>]*>(.*?)</style>', re.DOTALL)


def _generated_svg(map_key="world", *, groups=None, circles=False, land=None, ocean=None):
    """Build a downloadable SVG the way /generate does, for import round-trips."""
    info = MAPS[map_key]
    css = build_css(
        groups or [Group("Members", "#ff0000", ("se",))],
        include_small_country_circles=circles,
        land=land,
        ocean=ocean,
        land_classes=info.land_classes,
        ocean_classes=info.ocean_classes,
    )
    return render_map(map_key, css)


def _selected_options(html: str, select_name: str) -> set[str]:
    """Return the set of option values marked ``selected`` inside the named ``<select>``."""

    class _Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_target = False
            self.selected: set[str] = set()
            self._current_value: str | None = None
            self._current_selected = False

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            if tag == "select" and d.get("name") == select_name:
                self.in_target = True
            elif tag == "option" and self.in_target:
                self._current_value = d.get("value")
                self._current_selected = "selected" in d

        def handle_endtag(self, tag):
            if tag == "option" and self.in_target:
                if self._current_selected and self._current_value is not None:
                    self.selected.add(self._current_value)
                self._current_value = None
                self._current_selected = False
            elif tag == "select" and self.in_target:
                self.in_target = False

    p = _Parser()
    p.feed(html)
    return p.selected


def _group_title(html: str, index: int) -> str | None:
    """Return the ``value`` of the title input for group ``index``, or None."""
    m = re.search(rf'name="group\[{index}\]\[title\]".*?value="([^"]*)"', html, re.DOTALL)
    return m.group(1) if m else None


class TestIndex:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_contains_select_element(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "<select" in body

    def test_select_is_populated_with_country_options(self, client):
        body = client.get("/").get_data(as_text=True)
        assert 'value="se"' in body
        assert 'value="de"' in body
        assert "Sweden" in body

    def test_default_colours_are_applied_to_initial_groups(self, client):
        # The two default groups should pre-fill the colour input with the
        # first two colours of the Tol Muted palette.
        body = client.get("/").get_data(as_text=True)
        assert 'value="#332288"' in body  # group 0 — indigo
        assert 'value="#88CCEE"' in body  # group 1 — cyan

    def test_palette_is_embedded_in_form_dataset(self, client):
        # main.js reads ``data-default-colours`` to assign defaults to groups
        # added at runtime.
        body = client.get("/").get_data(as_text=True)
        assert "data-default-colours=" in body
        assert "#332288" in body
        assert "#AA4499" in body  # last colour, sanity check the full list ships

    def test_advanced_settings_renders_map_selector(self, client):
        body = client.get("/").get_data(as_text=True)
        assert '<details class="advanced-settings"' in body
        assert '<select name="map"' in body
        assert 'form="colouriser-form"' in body
        # Both registered maps appear by label.
        assert ">World</option>" in body
        assert ">World (compact)</option>" in body
        # Default key marked selected.
        assert 'value="world" selected' in body

    def test_option_with_description_renders_title_tooltip(self, client, monkeypatch):
        import app.maps as maps_module
        from app.maps import MapInfo

        sentinel = "TOOLTIP-SENTINEL-12345"
        monkeypatch.setitem(
            maps_module.MAPS,
            "world",
            MapInfo(
                filename="BlankMap-World.svg",
                label="World",
                description=sentinel,
            ),
        )

        body = client.get("/").get_data(as_text=True)
        assert f'title="{sentinel}"' in body

    def test_advanced_settings_present_even_with_single_map(self, client, monkeypatch):
        import app.maps as maps_module

        # Mutate the shared dict in place — routes.py aliases the same
        # object via `from app.maps import MAPS`, so setattr won't reach it
        # but delitem does (and monkeypatch restores).
        monkeypatch.delitem(maps_module.MAPS, "world-compact")
        body = client.get("/").get_data(as_text=True)
        assert '<details class="advanced-settings"' in body
        assert 'id="toggle-circles"' in body
        # No base-map selector when only one map is registered.
        assert 'id="base-map-select"' not in body

    def test_circles_toggle_renders_in_advanced_settings(self, client):
        body = client.get("/").get_data(as_text=True)
        assert 'id="toggle-circles"' in body
        assert 'name="circles"' in body
        assert "Show small-country circles" in body
        assert 'form="colouriser-form"' in body
        # Default state: unchecked.
        m = re.search(r'<input[^>]*id="toggle-circles"[^>]*>', body)
        assert m and "checked" not in m.group(0)

    def test_circles_toggle_reflects_session_value(self, client):
        with client.session_transaction() as s:
            s["include_circles"] = True
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<input[^>]*id="toggle-circles"[^>]*>', body)
        assert m and "checked" in m.group(0)

    def test_option_without_description_has_no_title_attr(self, client, monkeypatch):
        import app.maps as maps_module
        from app.maps import MapInfo

        monkeypatch.setitem(
            maps_module.MAPS,
            "world-compact",
            MapInfo(
                filename="BlankMap-World-Compact.svg",
                label="World (compact)",
                description="",
            ),
        )

        body = client.get("/").get_data(as_text=True)
        match = re.search(r'<option value="world-compact"[^>]*>', body)
        assert match is not None, "world-compact option missing from rendered page"
        assert "title=" not in match.group(0), (
            f"expected no title attr on description-less option, got: {match.group(0)!r}"
        )

    def test_advanced_settings_reflects_session_map_key(self, client):
        with client.session_transaction() as s:
            s["map_key"] = "world-compact"
        body = client.get("/").get_data(as_text=True)
        assert 'value="world-compact" selected' in body


class TestTestDeploymentBanner:
    def test_absent_by_default(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "test-deployment-banner" not in body

    def test_shown_when_enabled(self, app, client):
        app.config["TEST_DEPLOYMENT"] = True
        body = client.get("/").get_data(as_text=True)
        assert 'class="test-deployment-banner"' in body
        assert "This is a test deployment" in body

    def test_shown_on_result_page(self, app, client):
        # base.html carries the banner, so the /generate result page gets it too.
        app.config["TEST_DEPLOYMENT"] = True
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        assert 'class="test-deployment-banner"' in resp.get_data(as_text=True)


class TestGenerate:
    def test_valid_post_renders_inline_svg(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se", "de"],
            },
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "<svg" in body
        assert "#ff0000" in body
        # User CSS appended as a <style id="map-colouriser-style"> element.
        assert '<style id="map-colouriser-style"' in body

    def test_renders_wikitext_legend_below_map(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        body = resp.get_data(as_text=True)
        assert "{{Legend|#ff0000|Members}}" in body
        assert '<details class="result-legend" open>' in body

    def test_post_with_compact_map_succeeds_and_persists_in_session(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
                "map": "world-compact",
            },
        )
        assert resp.status_code == 200
        with client.session_transaction() as s:
            assert s["map_key"] == "world-compact"

    def test_post_with_unknown_map_rerenders_with_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
                "map": "atlantis",
            },
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Unknown map" in body

    def test_post_with_empty_map_falls_back_to_default(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
                "map": "",
            },
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Unknown map" not in body
        with client.session_transaction() as s:
            assert s["map_key"] == "world"

    def test_post_with_circles_checked_persists_and_adds_opacity(self, client):

        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
                "circles": "1",
            },
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Inspect the injected user CSS specifically — the base SVG itself
        # contains example `opacity: 1` text in its source comments.
        m = _USER_STYLE_RE.search(body)
        assert m, "user CSS style element missing from response"
        assert "opacity: 1" in m.group(1)
        with client.session_transaction() as s:
            assert s["include_circles"] is True

    def test_post_with_circles_falsy_value_does_not_enable_circles(self, client):
        # Programmatic clients sending `circles=0` (or any value other than
        # "1") must NOT enable circles.
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
                "circles": "0",
            },
        )
        assert resp.status_code == 200
        with client.session_transaction() as s:
            assert s["include_circles"] is False

    def test_post_without_circles_field_omits_opacity(self, client):

        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        body = resp.get_data(as_text=True)
        m = _USER_STYLE_RE.search(body)
        assert m, "user CSS style element missing from response"
        assert "opacity" not in m.group(1)
        with client.session_transaction() as s:
            assert s["include_circles"] is False

    def test_invalid_colour_rerenders_form_with_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "red",
                "group[0][countries][]": ["se"],
            },
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "colour" in body.lower()
        assert "<select" in body

    def test_no_countries_rerenders_form_with_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
            },
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "country" in body.lower() or "countries" in body.lower()

    def test_missing_title_is_an_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        body = resp.get_data(as_text=True)
        assert "title" in body.lower()

    def test_form_data_preserved_on_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "My Title",
                "group[0][colour]": "not-a-colour",
                "group[0][countries][]": ["se"],
            },
        )
        body = resp.get_data(as_text=True)
        assert "My Title" in body

    def test_collects_all_errors_not_fail_fast(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "",
                "group[0][colour]": "bad",
            },
        )
        body = resp.get_data(as_text=True).lower()
        assert "title" in body
        assert "colour" in body
        assert "countr" in body  # countries / country


class TestBaseColours:
    """Land / ocean base-colour pickers in the Advanced panel."""

    # The shipped global defaults (app.colouriser.DEFAULT_LAND/OCEAN_COLOUR).
    # Pinned here as literals so a change to the constant is a deliberate,
    # one-line update with a failing test to confirm intent.
    DEFAULT_LAND = "#dddddd"
    DEFAULT_OCEAN = "#ffffff"

    # A synthetic base map with test-owned class names ("landzz"/"circlezz" for
    # land, "oceanzz" for ocean), injected by the autouse fixture and made the
    # session's map, so assertions pin to values this class controls rather than
    # the shipped maps' live class lists. Expected selectors/attributes are
    # written as literals at each assertion.
    MAP_KEY = "test-base-colours"

    @pytest.fixture(autouse=True)
    def _synthetic_map(self, client, monkeypatch):
        """Register the synthetic map and make it the session's map for all
        tests in this class.

        Reuses world's on-disk SVG so render_map can prepare it; the declared
        classes need not exist in that SVG (check_svg isn't run here). Opt-out
        tests re-inject MAP_KEY with ocean_classes=None.
        """
        self._inject_map(client, monkeypatch)

    def _inject_map(self, client, monkeypatch, *, ocean_classes=("oceanzz",)):
        import app.maps as maps_module
        from app.maps import MapInfo

        monkeypatch.setitem(
            maps_module.MAPS,
            self.MAP_KEY,
            MapInfo(
                filename="BlankMap-World.svg",
                label="Test base colours",
                land_classes=("landzz", "circlezz"),
                ocean_classes=ocean_classes,
            ),
        )
        with client.session_transaction() as s:
            s["map_key"] = self.MAP_KEY

    def _post_min(self, **extra):
        data = {
            "map": self.MAP_KEY,
            "group[0][title]": "Members",
            "group[0][colour]": "#ff0000",
            "group[0][countries][]": ["se"],
        }
        data.update(extra)
        return data

    def test_defaults_emitted_when_form_omits_picker_values(self, client):

        resp = client.post("/generate", data=self._post_min())
        body = resp.get_data(as_text=True)
        m = _USER_STYLE_RE.search(body)
        assert m, "user CSS style element missing"
        css = m.group(1)
        assert "/* Land and small circles */" in css
        assert f".landzz, .circlezz {{ fill: {self.DEFAULT_LAND}; }}" in css
        assert "/* Oceans, seas, and large lakes */" in css
        assert f".oceanzz {{ fill: {self.DEFAULT_OCEAN}; }}" in css
        # Omitted picker fields resolve to the defaults and persist as such.
        with client.session_transaction() as s:
            assert s["land_colour"] == self.DEFAULT_LAND
            assert s["ocean_colour"] == self.DEFAULT_OCEAN

    def test_custom_land_persists_in_session_and_rendered_svg(self, client):

        resp = client.post("/generate", data=self._post_min(land_colour="#112233"))
        body = resp.get_data(as_text=True)
        m = _USER_STYLE_RE.search(body)
        assert m and ".landzz, .circlezz { fill: #112233; }" in m.group(1)
        with client.session_transaction() as s:
            assert s["land_colour"] == "#112233"

    def test_custom_ocean_persists_in_session_and_rendered_svg(self, client):

        resp = client.post("/generate", data=self._post_min(ocean_colour="#abcdef"))
        body = resp.get_data(as_text=True)
        m = _USER_STYLE_RE.search(body)
        assert m and ".oceanzz { fill: #abcdef; }" in m.group(1)
        with client.session_transaction() as s:
            assert s["ocean_colour"] == "#abcdef"

    def test_uppercase_hex_colour_round_trips(self, client):

        # _COLOUR_RE accepts A-F; the value must survive case-intact into both
        # the rendered CSS and the session.
        resp = client.post("/generate", data=self._post_min(land_colour="#ABCDEF"))
        body = resp.get_data(as_text=True)
        m = _USER_STYLE_RE.search(body)
        assert m and ".landzz, .circlezz { fill: #ABCDEF; }" in m.group(1)
        with client.session_transaction() as s:
            assert s["land_colour"] == "#ABCDEF"

    def test_whitespace_colour_resolves_to_default(self, client):

        resp = client.post("/generate", data=self._post_min(land_colour="   "))
        body = resp.get_data(as_text=True)
        m = _USER_STYLE_RE.search(body)
        assert m and f".landzz, .circlezz {{ fill: {self.DEFAULT_LAND}; }}" in m.group(1)

    def test_invalid_land_colour_rerenders_with_error(self, client):
        resp = client.post("/generate", data=self._post_min(land_colour="red"))
        assert resp.status_code == 200
        body = resp.get_data(as_text=True).lower()
        # Re-rendered form (not the result page).
        assert 'id="colouriser-form"' in body
        assert "land fill" in body and "#rrggbb" in body

    def test_invalid_ocean_colour_rerenders_with_error(self, client):
        resp = client.post("/generate", data=self._post_min(ocean_colour="blueish"))
        assert resp.status_code == 200
        body = resp.get_data(as_text=True).lower()
        assert 'id="colouriser-form"' in body
        assert "ocean fill" in body and "#rrggbb" in body

    def test_index_reflects_session_land_colour_in_picker_value(self, client):
        with client.session_transaction() as s:
            s["land_colour"] = "#112233"
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<input[^>]*id="land-colour"[^>]*>', body)
        assert m and 'value="#112233"' in m.group(0)

    def test_index_reflects_session_ocean_colour_in_picker_value(self, client):
        with client.session_transaction() as s:
            s["ocean_colour"] = "#abcdef"
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<input[^>]*id="ocean-colour"[^>]*>', body)
        assert m and 'value="#abcdef"' in m.group(0)

    def test_reset_button_disabled_when_picker_at_default(self, client):
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<button[^>]*id="reset-land"[^>]*>', body)
        assert m and "disabled" in m.group(0)

    def test_reset_button_disabled_for_uppercase_default(self, client):
        # The template compares via `| lower`, so #DDDDDD must count as the
        # default and leave Reset disabled.
        with client.session_transaction() as s:
            s["land_colour"] = self.DEFAULT_LAND.upper()
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<button[^>]*id="reset-land"[^>]*>', body)
        assert m and "disabled" in m.group(0)

    def test_reset_button_enabled_when_picker_overridden(self, client):
        with client.session_transaction() as s:
            s["land_colour"] = "#112233"
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<button[^>]*id="reset-land"[^>]*>', body)
        assert m and "disabled" not in m.group(0)

    def test_option_data_attributes_carry_classes(self, client):
        body = client.get("/").get_data(as_text=True)
        # The synthetic map's <option> carries its declared classes, joined.
        assert 'data-land-classes="landzz,circlezz"' in body
        assert 'data-ocean-classes="oceanzz"' in body

    def test_form_data_attributes_expose_defaults_and_current_classes(self, client):
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<form[^>]*id="colouriser-form"[^>]*>', body)
        assert m
        assert f'data-default-land-colour="{self.DEFAULT_LAND}"' in m.group(0)
        assert f'data-default-ocean-colour="{self.DEFAULT_OCEAN}"' in m.group(0)
        assert 'data-land-classes="landzz,circlezz"' in m.group(0)
        assert 'data-ocean-classes="oceanzz"' in m.group(0)

    def test_picker_row_hidden_server_side_when_map_opts_out(self, client, monkeypatch):
        # Re-inject the synthetic map with no ocean classes; the Jinja gate
        # should then render the land row but not the ocean row.
        self._inject_map(client, monkeypatch, ocean_classes=None)
        body = client.get("/").get_data(as_text=True)
        assert 'id="land-colour-row"' in body
        assert 'id="ocean-colour-row"' not in body

    def test_generate_skips_ocean_rule_when_map_opts_out(self, client, monkeypatch):

        self._inject_map(client, monkeypatch, ocean_classes=None)
        resp = client.post("/generate", data=self._post_min(ocean_colour="#abcdef"))
        body = resp.get_data(as_text=True)
        m = _USER_STYLE_RE.search(body)
        assert m and "oceanzz" not in m.group(1)
        # The opted-out side's colour is still persisted — session storage is
        # independent of whether a rule was emitted.
        with client.session_transaction() as s:
            assert s["ocean_colour"] == "#abcdef"


class TestBackToForm:
    def test_index_after_generate_repopulates_form(self, client):
        client.post(
            "/generate",
            data={
                "group[0][title]": "EU members",
                "group[0][colour]": "#003399",
                "group[0][countries][]": ["de", "fr"],
                "group[1][title]": "Nordics",
                "group[1][colour]": "#ffcc00",
                "group[1][countries][]": ["se", "no"],
            },
        )
        body = client.get("/").get_data(as_text=True)
        assert 'value="EU members"' in body
        assert 'value="#003399"' in body
        assert 'value="Nordics"' in body
        assert 'value="#ffcc00"' in body
        assert _selected_options(body, "group[0][countries][]") == {"de", "fr"}
        assert _selected_options(body, "group[1][countries][]") == {"se", "no"}

    def test_fresh_session_shows_default_empty_form(self, client):
        body = client.get("/").get_data(as_text=True)
        # Default state: two group blocks (indices 0 and 1) with no countries
        # selected. The hidden <template> uses ``__INDEX__`` and so is excluded.
        assert 'data-index="0"' in body
        assert 'data-index="1"' in body
        assert 'data-index="2"' not in body
        assert _selected_options(body, "group[0][countries][]") == set()
        assert _selected_options(body, "group[1][countries][]") == set()


class TestBaseMapEndpoint:
    def test_returns_prepared_svg_for_known_key(self, client):
        resp = client.get("/maps/world.svg")
        assert resp.status_code == 200
        assert resp.mimetype == "image/svg+xml"
        body = resp.get_data(as_text=True)
        assert "<svg" in body
        # viewBox enrichment is applied; the prepared SVG carries no user CSS
        # (the client-side preview appends its own <style id="map-colouriser-style">).
        assert "viewBox=" in body
        assert '<style id="map-colouriser-style"' not in body

    def test_returns_404_for_unknown_key(self, client):
        resp = client.get("/maps/atlantis.svg")
        assert resp.status_code == 404

    def test_sets_cache_control_header(self, client):
        resp = client.get("/maps/world.svg")
        assert "max-age" in resp.headers.get("Cache-Control", "")


_SAMPLE_SESSION_GROUPS = [
    {"index": 0, "title": "Members", "colour": "#ff0000", "countries": ["se"]},
]


class TestReset:
    def test_clears_session_and_redirects_to_index(self, client):
        with client.session_transaction() as s:
            s["last_groups"] = _SAMPLE_SESSION_GROUPS
            s["map_key"] = "world"
            s["include_circles"] = True
            s["land_colour"] = "#112233"
            s["ocean_colour"] = "#abcdef"

        resp = client.post("/reset")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

        with client.session_transaction() as s:
            assert "last_groups" not in s
            assert "map_key" not in s
            assert "include_circles" not in s
            assert "land_colour" not in s
            assert "ocean_colour" not in s

    def test_index_after_reset_shows_default_form_state(self, client):
        with client.session_transaction() as s:
            s["last_groups"] = _SAMPLE_SESSION_GROUPS

        client.post("/reset")
        body = client.get("/").get_data(as_text=True)
        # No carryover of the prior title.
        assert "Members" not in body
        # Two empty default groups present.
        assert body.count('name="group[0][title]"') == 1
        assert body.count('name="group[1][title]"') == 1

    def test_reset_is_idempotent_when_session_empty(self, client):
        # No session set up — reset should still succeed.
        resp = client.post("/reset")
        assert resp.status_code == 302


class TestGroupActions:
    """The no-JS add/remove-group fallbacks (with JS, the click is cancelled)."""

    def _form(self, count=2, **extra):
        """A submitted form body with ``count`` filled-in groups."""
        data = {}
        for i in range(count):
            data[f"group[{i}][title]"] = f"G{i}"
            data[f"group[{i}][colour]"] = "#ff0000"
            data[f"group[{i}][countries][]"] = ["se"]
        data.update(extra)
        return data

    def test_add_appends_a_blank_group_and_redirects_to_the_group_list(self, client):
        resp = client.post("/add-group", data=self._form(2))

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/#groups")
        with client.session_transaction() as s:
            assert [g["index"] for g in s["last_groups"]] == [0, 1, 2]
            assert s["last_groups"][2] == {
                "index": 2,
                "title": "",
                "colour": "",
                "countries": [],
            }

    def test_add_preserves_typed_values(self, client):
        client.post("/add-group", data=self._form(2))

        body = client.get("/").get_data(as_text=True)
        assert 'value="G0"' in body
        assert 'value="G1"' in body
        assert body.count('name="group[2][title]"') == 1

    def test_add_uses_max_index_plus_one_so_palette_defaults_never_collide(self, client):
        # Sparse indices (0, 2) are what a JS-side removal leaves behind. The new
        # group must be 3, not 2: index 2's palette colour is still on the form,
        # carried as a concrete value by the surviving group.
        data = {
            "group[0][title]": "G0",
            "group[0][colour]": "#ff0000",
            "group[0][countries][]": ["se"],
            "group[2][title]": "G2",
            "group[2][colour]": "#00ff00",
            "group[2][countries][]": ["de"],
        }
        client.post("/add-group", data=data)

        with client.session_transaction() as s:
            assert [g["index"] for g in s["last_groups"]] == [0, 2, 3]

    def test_remove_drops_the_posted_index_only(self, client):
        client.post("/remove-group", data=self._form(3, remove="1"))

        with client.session_transaction() as s:
            assert [g["index"] for g in s["last_groups"]] == [0, 2]
            assert [g["title"] for g in s["last_groups"]] == ["G0", "G2"]

    def test_removing_the_only_group_leaves_one_blank_group(self, client):
        # Not a no-op (a dead button reads as broken) and not zero: GET / renders
        # _default_form_state() for an empty list, which would be *two* groups.
        client.post("/remove-group", data=self._form(1, remove="0"))

        with client.session_transaction() as s:
            assert s["last_groups"] == [{"index": 0, "title": "", "colour": "", "countries": []}]
        body = client.get("/").get_data(as_text=True)
        assert body.count('name="group[0][title]"') == 1
        assert body.count('name="group[1][title]"') == 0

    @pytest.mark.parametrize("value", ["", "abc", "__INDEX__", "99"])
    def test_remove_with_unusable_index_changes_nothing(self, client, value):
        client.post("/remove-group", data=self._form(2, remove=value))

        with client.session_transaction() as s:
            assert [g["index"] for g in s["last_groups"]] == [0, 1]

    def test_remove_without_the_field_changes_nothing(self, client):
        client.post("/remove-group", data=self._form(2))

        with client.session_transaction() as s:
            assert [g["index"] for g in s["last_groups"]] == [0, 1]

    @pytest.mark.parametrize(
        ("path", "extra"),
        [("/add-group", {}), ("/remove-group", {"remove": "1"})],
    )
    def test_advanced_settings_survive_the_round_trip(self, client, path, extra):
        data = self._form(
            2,
            map="world-compact",
            circles="1",
            land_colour="#112233",
            ocean_colour="#abcdef",
            **extra,
        )
        client.post(path, data=data)

        with client.session_transaction() as s:
            assert s["map_key"] == "world-compact"
            assert s["include_circles"] is True
            assert s["land_colour"] == "#112233"
            assert s["ocean_colour"] == "#abcdef"

    def test_advanced_settings_survive_removing_the_only_group(self, client):
        # The blank-group branch throws the posted groups away; it must not throw
        # the Advanced settings out with them.
        data = self._form(
            1,
            remove="0",
            map="world-compact",
            circles="1",
            land_colour="#112233",
            ocean_colour="#abcdef",
        )
        client.post("/remove-group", data=data)

        with client.session_transaction() as s:
            assert s["last_groups"] == [{"index": 0, "title": "", "colour": "", "countries": []}]
            assert s["map_key"] == "world-compact"
            assert s["include_circles"] is True
            assert s["land_colour"] == "#112233"
            assert s["ocean_colour"] == "#abcdef"

    @pytest.mark.parametrize(
        ("field", "value", "key"),
        [("map", "no-such-map", "map_key"), ("land_colour", "bogus", "land_colour")],
    )
    def test_unusable_advanced_value_leaves_the_session_untouched(self, client, field, value, key):
        # These routes don't validate. /download normalises an unknown map key
        # and answers 400 on a colour build_css rejects, so a poisoned session
        # would break the next download rather than crash the request.
        with client.session_transaction() as s:
            s["map_key"] = "world"
            s["land_colour"] = "#112233"
        before = {"map_key": "world", "land_colour": "#112233"}[key]

        client.post("/add-group", data=self._form(1, **{field: value}))

        with client.session_transaction() as s:
            assert s[key] == before

    def test_add_is_capped(self, client):
        client.post("/add-group", data=self._form(routes._MAX_GROUPS))

        with client.session_transaction() as s:
            assert len(s["last_groups"]) == routes._MAX_GROUPS

    def test_cap_measures_the_current_list_not_a_high_water_mark(self, client):
        # Filling up then removing has to free the allowance again.
        client.post("/remove-group", data=self._form(routes._MAX_GROUPS, remove="0"))
        with client.session_transaction() as s:
            assert len(s["last_groups"]) == routes._MAX_GROUPS - 1

        client.post("/add-group", data=self._form(routes._MAX_GROUPS - 1))
        with client.session_transaction() as s:
            assert len(s["last_groups"]) == routes._MAX_GROUPS


class TestImport:
    def _post(self, client, svg_bytes, filename="map.svg"):
        return client.post(
            "/import",
            data={"svg": (io.BytesIO(svg_bytes), filename)},
            content_type="multipart/form-data",
        )

    def test_round_trips_state_into_session_and_form(self, client):
        groups = [
            Group("Nordics", "#ff0000", ("se", "no")),
            Group("DACH", "#00ff00", ("de", "at")),
        ]
        svg = _generated_svg("world", groups=groups, circles=True, land="#abcdef", ocean="#123456")
        resp = self._post(client, svg.encode("utf-8"))

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

        with client.session_transaction() as s:
            assert s["map_key"] == "world"
            assert s["include_circles"] is True
            assert s["land_colour"] == "#abcdef"
            assert s["ocean_colour"] == "#123456"
            # Full dicts, so title↔colour↔countries coupling is asserted, not
            # just that each value appears somewhere.
            assert s["last_groups"] == [
                {"index": 0, "title": "Nordics", "colour": "#ff0000", "countries": ["se", "no"]},
                {"index": 1, "title": "DACH", "colour": "#00ff00", "countries": ["de", "at"]},
            ]

        body = client.get("/").get_data(as_text=True)
        # Coupling survives into the rendered form: each group's title input and
        # its selected countries share the same group index.
        assert _group_title(body, 0) == "Nordics"
        assert _selected_options(body, "group[0][countries][]") == {"se", "no"}
        assert _group_title(body, 1) == "DACH"
        assert _selected_options(body, "group[1][countries][]") == {"de", "at"}

    def test_missing_data_map_surfaces_warning_and_defaults(self, client):
        svg = _generated_svg("world", land="#abcdef").replace(' data-map="world"', "")
        self._post(client, svg.encode("utf-8"))

        body = client.get("/").get_data(as_text=True)
        assert 'class="warnings"' in body
        assert "data-map" in body
        # Groups still recovered despite the base-map fallback.
        assert 'value="Members"' in body

    def test_no_file_reports_warning(self, client):
        resp = client.post("/import", data={}, content_type="multipart/form-data")
        assert resp.status_code == 302
        body = client.get("/").get_data(as_text=True)
        assert "No file was uploaded." in body

    def test_warnings_are_cleared_after_one_render(self, client):
        self._post(client, b"not an svg")
        first = client.get("/").get_data(as_text=True)
        assert 'class="warnings"' in first
        # Warnings are popped, so a second GET is clean.
        second = client.get("/").get_data(as_text=True)
        assert 'class="warnings"' not in second

    def test_oversized_upload_rejected_with_413(self, client):
        oversized = b"<svg>" + b"a" * (2 * 1024 * 1024) + b"</svg>"
        resp = self._post(client, oversized)
        assert resp.status_code == 413

    # Unknown country codes are absent here by construction: the selector
    # regex only matches [\w-]+, so a "code" can never carry HTML
    # metacharacters into a warning. Payloads must be well-formed XML to get
    # past validate_svg — which is exactly the shape that would execute if it
    # ever rendered unescaped.
    @pytest.mark.parametrize(
        ("css", "payload"),
        [
            pytest.param(
                "\n/* <script>alert(1)</script> */\n.zz { fill: #332288; }\n",
                "<script>alert(1)</script>",
                id="title",
            ),
            pytest.param(
                '\n/* T */\n.se { fill: <img src="x" onerror="alert(1)"/>; }\n',
                '<img src="x" onerror="alert(1)"/>',
                id="colour",
            ),
            pytest.param(
                "\n/* T */\n.se { fill: #332288; }\n<script>alert(1)</script>\n",
                "<script>alert(1)</script>",
                id="unparsed-styling",
            ),
        ],
    )
    def test_warning_content_from_the_file_is_html_escaped(self, client, css, payload):
        svg = render_map("world", css)
        self._post(client, svg.encode("utf-8"))

        body = client.get("/").get_data(as_text=True)
        assert payload not in body
        assert str(escape(payload)) in body

    def test_index_renders_import_form(self, client):
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<form[^>]*action="/import"[^>]*>', body)
        assert m is not None
        assert 'enctype="multipart/form-data"' in m.group(0)
        assert 'method="post"' in m.group(0)
        assert re.search(r'<input[^>]*type="file"[^>]*name="svg"', body)


class TestDownload:
    def test_returns_400_when_no_session(self, client):
        resp = client.get("/download")
        assert resp.status_code == 400

    def test_returns_svg_after_generate(self, client):
        client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        resp = client.get("/download")
        assert resp.status_code == 200
        assert resp.mimetype == "image/svg+xml"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert "map.svg" in resp.headers.get("Content-Disposition", "")
        assert b"<svg" in resp.data
        # Verify session state actually drives the rendered SVG.
        assert b".se" in resp.data
        assert b"#ff0000" in resp.data

    def test_returns_400_when_session_data_is_corrupted(self, client):
        with client.session_transaction() as sess:
            sess["last_groups"] = [
                {
                    "index": 0,
                    "title": "OK",
                    "colour": "not-a-colour",
                    "countries": ["se"],
                }
            ]
            sess["map_key"] = "world"
        resp = client.get("/download")
        assert resp.status_code == 400
        assert b"invalid" in resp.data.lower() or b"regenerate" in resp.data.lower()

    def test_honours_session_base_colours(self, client, monkeypatch):

        import app.maps as maps_module
        from app.maps import MapInfo

        # Synthetic map with test-owned classes so the assertion isn't coupled
        # to a shipped map's live class list.
        monkeypatch.setitem(
            maps_module.MAPS,
            "dl-base-colours",
            MapInfo(
                filename="BlankMap-World.svg",
                label="DL base colours",
                land_classes=("landzz", "circlezz"),
                ocean_classes=("oceanzz",),
            ),
        )
        with client.session_transaction() as sess:
            sess["last_groups"] = [
                {
                    "index": 0,
                    "title": "OK",
                    "colour": "#ff0000",
                    "countries": ["se"],
                }
            ]
            sess["map_key"] = "dl-base-colours"
            sess["land_colour"] = "#112233"
            sess["ocean_colour"] = "#abcdef"
        resp = client.get("/download")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        m = _USER_STYLE_RE.search(body)
        assert m
        assert ".landzz, .circlezz { fill: #112233; }" in m.group(1)
        assert ".oceanzz { fill: #abcdef; }" in m.group(1)

    def test_returns_400_when_session_colour_is_malformed(self, client):
        # build_css re-validates the colour and raises ValueError, which the
        # download handler must catch and surface as a 400 rather than a 500.
        with client.session_transaction() as sess:
            sess["last_groups"] = [
                {
                    "index": 0,
                    "title": "OK",
                    "colour": "#ff0000",
                    "countries": ["se"],
                }
            ]
            sess["map_key"] = "world"
            sess["land_colour"] = "red"  # not #rrggbb
        resp = client.get("/download")
        assert resp.status_code == 400
        assert b"invalid" in resp.data.lower() or b"regenerate" in resp.data.lower()

    def test_falls_back_to_default_map_when_session_map_key_unknown(self, client):
        with client.session_transaction() as sess:
            sess["last_groups"] = [
                {
                    "index": 0,
                    "title": "OK",
                    "colour": "#ff0000",
                    "countries": ["se"],
                }
            ]
            sess["map_key"] = "atlantis"
        resp = client.get("/download")
        assert resp.status_code == 200
        assert b"<svg" in resp.data


class TestSecurityValidation:
    def test_post_with_unknown_map_returns_form_with_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "map": "atlantis",
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        body = resp.get_data(as_text=True).lower()
        assert "unknown map" in body
        assert "<select" in body  # form re-rendered, not the result page

    def test_post_with_unknown_country_code_returns_form_with_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["zz", "qq", "se"],
            },
        )
        body = resp.get_data(as_text=True).lower()
        assert "unknown country code" in body
        assert "zz" in body
        assert "qq" in body

    def test_post_with_dangerous_title_returns_form_with_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "evil */ </style><script>alert(1)</script>",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Form re-renders with an error; payload is not echoed into the response
        # outside of the (Jinja-autoescaped) form input.
        assert "<script>alert(1)</script>" not in body
        assert "may not contain" in body.lower()

    def test_post_with_dangerous_country_code_returns_form_with_error(self, client):
        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": [
                    "x}</style><script>alert(1)</script><style>{",
                ],
            },
        )
        body = resp.get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body
        assert "unknown country code" in body.lower()
