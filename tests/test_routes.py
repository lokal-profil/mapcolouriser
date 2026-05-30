from html.parser import HTMLParser

import pytest


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
        import re

        m = re.search(r'<input[^>]*id="toggle-circles"[^>]*>', body)
        assert m and "checked" not in m.group(0)

    def test_circles_toggle_reflects_session_value(self, client):
        with client.session_transaction() as s:
            s["include_circles"] = True
        body = client.get("/").get_data(as_text=True)
        import re

        m = re.search(r'<input[^>]*id="toggle-circles"[^>]*>', body)
        assert m and "checked" in m.group(0)

    def test_option_without_description_has_no_title_attr(self, client, monkeypatch):
        import re

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
        assert '<style id="map-colouriser-style">' in body

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
        import re

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
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
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
        import re

        resp = client.post(
            "/generate",
            data={
                "group[0][title]": "Members",
                "group[0][colour]": "#ff0000",
                "group[0][countries][]": ["se"],
            },
        )
        body = resp.get_data(as_text=True)
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
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
        import re

        resp = client.post("/generate", data=self._post_min())
        body = resp.get_data(as_text=True)
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
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
        import re

        resp = client.post("/generate", data=self._post_min(land_colour="#112233"))
        body = resp.get_data(as_text=True)
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
        assert m and ".landzz, .circlezz { fill: #112233; }" in m.group(1)
        with client.session_transaction() as s:
            assert s["land_colour"] == "#112233"

    def test_custom_ocean_persists_in_session_and_rendered_svg(self, client):
        import re

        resp = client.post("/generate", data=self._post_min(ocean_colour="#abcdef"))
        body = resp.get_data(as_text=True)
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
        assert m and ".oceanzz { fill: #abcdef; }" in m.group(1)
        with client.session_transaction() as s:
            assert s["ocean_colour"] == "#abcdef"

    def test_uppercase_hex_colour_round_trips(self, client):
        import re

        # _COLOUR_RE accepts A-F; the value must survive case-intact into both
        # the rendered CSS and the session.
        resp = client.post("/generate", data=self._post_min(land_colour="#ABCDEF"))
        body = resp.get_data(as_text=True)
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
        assert m and ".landzz, .circlezz { fill: #ABCDEF; }" in m.group(1)
        with client.session_transaction() as s:
            assert s["land_colour"] == "#ABCDEF"

    def test_whitespace_colour_resolves_to_default(self, client):
        import re

        resp = client.post("/generate", data=self._post_min(land_colour="   "))
        body = resp.get_data(as_text=True)
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
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
        import re

        with client.session_transaction() as s:
            s["land_colour"] = "#112233"
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<input[^>]*id="land-colour"[^>]*>', body)
        assert m and 'value="#112233"' in m.group(0)

    def test_index_reflects_session_ocean_colour_in_picker_value(self, client):
        import re

        with client.session_transaction() as s:
            s["ocean_colour"] = "#abcdef"
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<input[^>]*id="ocean-colour"[^>]*>', body)
        assert m and 'value="#abcdef"' in m.group(0)

    def test_reset_button_disabled_when_picker_at_default(self, client):
        import re

        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<button[^>]*id="reset-land"[^>]*>', body)
        assert m and "disabled" in m.group(0)

    def test_reset_button_disabled_for_uppercase_default(self, client):
        import re

        # The template compares via `| lower`, so #DDDDDD must count as the
        # default and leave Reset disabled.
        with client.session_transaction() as s:
            s["land_colour"] = self.DEFAULT_LAND.upper()
        body = client.get("/").get_data(as_text=True)
        m = re.search(r'<button[^>]*id="reset-land"[^>]*>', body)
        assert m and "disabled" in m.group(0)

    def test_reset_button_enabled_when_picker_overridden(self, client):
        import re

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
        import re

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
        import re

        self._inject_map(client, monkeypatch, ocean_classes=None)
        resp = client.post("/generate", data=self._post_min(ocean_colour="#abcdef"))
        body = resp.get_data(as_text=True)
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
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
        assert '<style id="map-colouriser-style">' not in body

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
        import re

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
        m = re.search(r'<style id="map-colouriser-style">(.*?)</style>', body, re.DOTALL)
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
