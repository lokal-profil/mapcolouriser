from html.parser import HTMLParser


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

        resp = client.post("/reset")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

        with client.session_transaction() as s:
            assert "last_groups" not in s
            assert "map_key" not in s

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
