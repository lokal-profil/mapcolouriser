import logging

import pytest

from app.svg_injector import MARKER, add_viewbox_if_missing, inject_css, validate_svg


class TestValidateSvg:
    def test_returns_true_when_marker_present_exactly_once(self):
        svg = f"<svg><style>{MARKER}</style></svg>"
        assert validate_svg(svg) is True

    def test_returns_false_when_marker_absent(self):
        assert validate_svg("<svg><style></style></svg>") is False

    def test_returns_false_when_marker_present_more_than_once(self):
        svg = f"<svg><style>{MARKER}\n{MARKER}</style></svg>"
        assert validate_svg(svg) is False


class TestInjectCss:
    def test_replaces_marker_with_css(self):
        svg = f"<svg><style>{MARKER}</style></svg>"
        out = inject_css(svg, ".se { fill: red; }")
        assert ".se { fill: red; }" in out
        assert MARKER not in out

    def test_preserves_surrounding_content(self):
        svg = f"<svg><style>before\n{MARKER}\nafter</style><path/></svg>"
        out = inject_css(svg, ".se { fill: red; }")
        assert "before" in out
        assert "after" in out
        assert "<path/>" in out

    def test_raises_valueerror_when_marker_absent(self):
        with pytest.raises(ValueError, match="marker"):
            inject_css("<svg></svg>", ".se { fill: red; }")

    def test_replaces_all_occurrences_when_multiple_present(self):
        # If a malformed file has two markers, validate_svg already rejected
        # it; inject still replaces all for robustness rather than partially.
        svg = f"<svg>{MARKER} A {MARKER}</svg>"
        out = inject_css(svg, "X")
        assert MARKER not in out


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
