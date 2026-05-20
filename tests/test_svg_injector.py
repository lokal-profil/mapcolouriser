import logging

from app.svg_injector import add_viewbox_if_missing, validate_svg


class TestValidateSvg:
    def test_returns_true_for_minimal_svg_with_close_tag(self):
        assert validate_svg('<svg xmlns="http://www.w3.org/2000/svg"></svg>') is True

    def test_returns_true_for_svg_with_children(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><path/><style></style></svg>'
        assert validate_svg(svg) is True

    def test_returns_true_without_namespace(self):
        # ElementTree accepts <svg> without xmlns; the root tag matches.
        assert validate_svg("<svg></svg>") is True

    def test_returns_false_for_self_closing_root(self):
        # Parses fine as XML, but there's no </svg> for the CSS-injection
        # split to anchor on, so we reject it here rather than later.
        assert validate_svg('<svg xmlns="http://www.w3.org/2000/svg"/>') is False

    def test_returns_false_for_empty_string(self):
        assert validate_svg("") is False

    def test_returns_false_for_arbitrary_text(self):
        assert validate_svg("not an svg") is False

    def test_returns_false_for_non_svg_root(self):
        assert validate_svg("<html><body/></html>") is False

    def test_returns_false_for_truncated_svg(self):
        assert validate_svg('<svg xmlns="http://www.w3.org/2000/svg"><path') is False

    def test_returns_false_for_malformed_xml(self):
        assert validate_svg("<svg><unclosed></svg>") is False

    def test_logs_parse_error_message(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.svg_injector"):
            validate_svg("<svg><unclosed></svg>")
        assert any("failed to parse" in rec.message for rec in caplog.records)


class TestAddViewboxIfMissing:
    def test_adds_viewbox_when_only_width_height_present(self):
        out = add_viewbox_if_missing('<svg width="2754" height="1398"></svg>')
        assert 'viewBox="0 0 2754 1398"' in out

    def test_unchanged_when_viewbox_already_present(self):
        svg = '<svg width="100" height="100" viewBox="0 0 100 100"></svg>'
        assert add_viewbox_if_missing(svg) == svg

    def test_unchanged_when_no_dimensions(self):
        svg = "<svg></svg>"
        assert add_viewbox_if_missing(svg) == svg

    def test_unchanged_when_no_root_svg(self):
        text = "not an svg"
        assert add_viewbox_if_missing(text) == text

    def test_preserves_other_attributes(self):
        out = add_viewbox_if_missing(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20"></svg>'
        )
        assert 'xmlns="http://www.w3.org/2000/svg"' in out
        assert 'viewBox="0 0 10 20"' in out

    def test_only_modifies_root_svg(self):
        # A nested <svg> inside content should not be touched.
        svg = '<svg width="100" height="50"><g><svg width="9" height="9"></svg></g></svg>'
        out = add_viewbox_if_missing(svg)
        assert out.count("viewBox=") == 1

    def test_handles_float_dimensions(self):
        out = add_viewbox_if_missing('<svg width="100.5" height="50.25"></svg>')
        assert 'viewBox="0 0 100.5 50.25"' in out

    def test_strips_px_unit_suffix(self):
        out = add_viewbox_if_missing('<svg width="2754px" height="1398px"></svg>')
        assert 'viewBox="0 0 2754 1398"' in out

    def test_strips_pt_unit_suffix(self):
        out = add_viewbox_if_missing('<svg width="100pt" height="50pt"></svg>')
        assert 'viewBox="0 0 100 50"' in out

    def test_skips_for_percentage_dimensions(self, caplog):
        svg = '<svg width="100%" height="100%"></svg>'
        with caplog.at_level(logging.WARNING, logger="app.svg_injector"):
            out = add_viewbox_if_missing(svg)
        assert out == svg
        assert any("non-absolute" in rec.message for rec in caplog.records)

    def test_skips_for_unparseable_dimensions(self, caplog):
        svg = '<svg width="abc" height="xyz"></svg>'
        with caplog.at_level(logging.WARNING, logger="app.svg_injector"):
            out = add_viewbox_if_missing(svg)
        assert out == svg
        assert any("non-absolute" in rec.message for rec in caplog.records)
