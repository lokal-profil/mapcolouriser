"""SVG validation and viewBox enrichment for base maps.

``validate_svg`` is the single rule used by both the Flask app's startup
check and the CI script, so the two cannot drift.
"""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_SVG_OPEN_RE = re.compile(r"<svg\b([^>]*)>", re.IGNORECASE)
_VIEWBOX_RE = re.compile(r"\bviewBox\s*=", re.IGNORECASE)
_WIDTH_RE = re.compile(r'\bwidth\s*=\s*"([^"]+)"', re.IGNORECASE)
_HEIGHT_RE = re.compile(r'\bheight\s*=\s*"([^"]+)"', re.IGNORECASE)
_DIMENSION_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)(px|pt|pc|mm|cm|in|em|rem|ex)?$")

_SVG_NS = "http://www.w3.org/2000/svg"


def validate_svg(svg_text: str) -> bool:
    """Return True iff ``svg_text`` is a well-formed SVG with a ``</svg>`` close tag.

    The close-tag requirement excludes self-closing roots (``<svg/>``) so
    downstream callers like ``app.maps._prepared`` can safely locate the
    final ``</svg>`` for CSS injection. Catches truncated, malformed, or
    non-SVG files before they reach request handling or the JS preview.
    """
    try:
        root = ElementTree.fromstring(svg_text)
    except ElementTree.ParseError as exc:
        logger.warning("SVG failed to parse as XML: %s", exc)
        return False
    if root.tag not in ("svg", f"{{{_SVG_NS}}}svg"):
        return False
    return "</svg>" in svg_text


def add_viewbox_if_missing(svg_text: str) -> str:
    """Ensure the root ``<svg>`` carries a ``viewBox``.

    Without a ``viewBox``, browsers can't scale the SVG content to fit a
    smaller container — they only resize the box and clip. If the root
    element has fixed ``width``/``height`` attributes but no ``viewBox``,
    derive one from those values. If a ``viewBox`` already exists, return
    the input unchanged. If width/height are non-absolute (e.g. ``100%``)
    or missing, log a warning and return unchanged.
    """
    open_match = _SVG_OPEN_RE.search(svg_text)
    if open_match is None:
        return svg_text

    attrs = open_match.group(1)
    if _VIEWBOX_RE.search(attrs):
        return svg_text

    width_match = _WIDTH_RE.search(attrs)
    height_match = _HEIGHT_RE.search(attrs)
    if not width_match or not height_match:
        return svg_text

    width = _parse_dimension(width_match.group(1))
    height = _parse_dimension(height_match.group(1))
    if width is None or height is None:
        logger.warning(
            "viewBox not added: non-absolute dimensions width=%r height=%r",
            width_match.group(1),
            height_match.group(1),
        )
        return svg_text

    new_attrs = f'{attrs} viewBox="0 0 {_fmt(width)} {_fmt(height)}"'
    return svg_text[: open_match.start(1)] + new_attrs + svg_text[open_match.end(1) :]


def _parse_dimension(s: str) -> float | None:
    m = _DIMENSION_RE.match(s)
    return float(m.group(1)) if m else None


def _fmt(n: float) -> str:
    return f"{int(n)}" if n.is_integer() else f"{n}"
