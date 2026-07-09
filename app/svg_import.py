"""Recover form state from a previously generated map SVG.

Pure leaf module (no Flask), mirroring ``app.colouriser``. ``import_svg`` reads
back the ``<style id="map-colouriser-style" data-map="…">`` element that
``app.maps.render_map`` injects and reconstructs the map key, group definitions,
land/ocean base colours, and the small-country-circles flag.

Country-code validation is injected via ``valid_codes`` so the pycountry
coupling stays in the route layer (same rule that keeps ``app.colouriser`` a
pure leaf), and so a future per-map code set needs no change here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.colouriser import COLOUR_PATTERN, Group
from app.maps import DEFAULT_MAP, MAPS

# The injected user-CSS element. ``id`` is required; ``data-map`` is optional so
# pre-marker or optimizer-stripped files still match (map_key stays None).
_STYLE_OPEN_RE = re.compile(
    r'<style\b(?=[^>]*\bid="map-colouriser-style")'
    r'(?:(?=[^>]*\bdata-map="(?P<map>[\w-]+)"))?[^>]*>'
    r"(?P<css>.*?)</style>",
    re.DOTALL,
)
# One ``build_css`` block: a ``/* title */`` comment, a class selector, and a
# ``fill`` rule optionally followed by the ``opacity: 1`` circles marker. The
# colour is captured loosely (anything up to the ``;`` or ``}``) and validated
# in code, so a malformed colour produces a warning instead of the block
# silently failing to match. Trailing semicolons are optional throughout — CSS
# treats ``;`` as a separator, not a terminator.
_BLOCK_RE = re.compile(
    r"/\*\s*(?P<title>[^*]*?)\s*\*/\s*"
    r"(?P<selector>\.[\w-]+(?:\s*,\s*\.[\w-]+)*)\s*"
    r"\{\s*fill:\s*(?P<colour>[^;}]+?)\s*"
    r"(?:;\s*(?P<opacity>opacity:\s*1\s*;?)?\s*)?\}",
)
_CODE_RE = re.compile(r"^[a-z]{2}$")  # fallback shape check when no allowlist is given
_COLOUR_RE = re.compile(f"^{COLOUR_PATTERN}$")
_SHORT_COLOUR_RE = re.compile(r"^#([0-9a-fA-F]{3})$")


def _normalise_colour(raw: str) -> str | None:
    """Return ``raw`` as ``#rrggbb``, expanding ``#rgb`` shorthand; None if neither."""
    if _COLOUR_RE.match(raw):
        return raw
    m = _SHORT_COLOUR_RE.match(raw)
    if m:
        return "#" + "".join(c + c for c in m.group(1))
    return None


@dataclass(frozen=True, slots=True)
class ImportResult:
    map_key: str
    groups: list[dict[str, Any]]
    land_colour: str | None = None
    ocean_colour: str | None = None
    include_circles: bool = False
    warnings: list[str] = field(default_factory=list)


def import_svg(svg_text: str, valid_codes: frozenset[str] | None = None) -> ImportResult:
    """Recover map key, groups, base colours, and circles from a generated SVG.

    ``valid_codes`` is the allowlist a group's country codes are checked
    against, injected by the route layer (which owns the pycountry coupling).
    When ``None``, codes are only shape-checked (``^[a-z]{2}$``) — the mode pure
    unit tests use to avoid the country dependency.

    On failure to identify the base map (missing or unrecognized ``data-map``),
    the result falls back to ``DEFAULT_MAP``; land/ocean colours are still
    recovered when their block's classes overlap the fallback map's declared
    classes, and the circles flag (CSS-intrinsic) is recovered regardless.
    Unrecognized country codes are discarded per-code; a group is only skipped
    outright when no recognized codes remain. Colours accept ``#rrggbb`` or
    ``#rgb`` shorthand (expanded); a group with any other colour value is kept
    with an empty colour so the form assigns a palette default. Everything
    discarded or skipped adds a warning rather than aborting the whole import.
    """
    # Imported here (not at module load) to keep this a pure leaf and localize
    # the defusedxml dependency to the parse call.
    from app.svg_injector import validate_svg

    if not validate_svg(svg_text):
        return ImportResult(map_key=DEFAULT_MAP, groups=[], warnings=["Not a valid SVG file."])

    style_match = _STYLE_OPEN_RE.search(svg_text)
    if style_match is None:
        return ImportResult(
            map_key=DEFAULT_MAP,
            groups=[],
            warnings=["No map-colouriser data found in this file."],
        )

    warnings: list[str] = []
    map_key = style_match.group("map")
    if map_key is None:
        warnings.append(
            "Couldn't detect the base map (no data-map attribute found) — "
            f"defaulting to {MAPS[DEFAULT_MAP].label}."
        )
        map_key = DEFAULT_MAP
    elif map_key not in MAPS:
        warnings.append(
            f"Unrecognized base map {map_key!r} — defaulting to {MAPS[DEFAULT_MAP].label}."
        )
        map_key = DEFAULT_MAP

    info = MAPS[map_key]
    land_classes = set(info.land_classes or ())
    ocean_classes = set(info.ocean_classes or ())

    def code_ok(code: str) -> bool:
        return code in valid_codes if valid_codes is not None else bool(_CODE_RE.match(code))

    groups: list[dict[str, Any]] = []
    land_colour = ocean_colour = None
    include_circles = False
    idx = 0

    css = style_match.group("css")
    unparsed: list[str] = []
    pos = 0
    for m in _BLOCK_RE.finditer(css):
        if css[pos : m.start()].strip():
            unparsed.append(css[pos : m.start()].strip())
        pos = m.end()
        classes = [c.strip().lstrip(".") for c in m.group("selector").split(",")]
        raw_colour = m.group("colour").strip()
        # Shared by land, ocean, and group blocks: accepts #rrggbb, expands
        # #rgb shorthand, and returns None for anything else.
        colour = _normalise_colour(raw_colour)
        title = m.group("title")
        label = title or m.group("selector")

        # Land/ocean blocks are recognized by class *overlap* with the
        # effective map's declared classes (not exact match), so a file whose
        # real map fell back to the default — or a sibling map like
        # world-compact landing on world — still restores its base colours.
        # No registered map declares two-letter land/ocean classes, so a
        # country group can't be misclassified by the overlap check.
        if set(classes) & land_classes:
            if colour is None:
                warnings.append(f"Ignored the land colour {raw_colour!r}: not a #rrggbb colour.")
            else:
                land_colour = colour
            continue
        if set(classes) & ocean_classes:
            if colour is None:
                warnings.append(f"Ignored the ocean colour {raw_colour!r}: not a #rrggbb colour.")
            else:
                ocean_colour = colour
            continue

        codes = [c for c in classes if code_ok(c)]
        unknown = [c for c in classes if not code_ok(c)]
        if unknown:
            if not codes:
                warnings.append(f"Skipped group {label!r}: no recognized country codes.")
                continue
            warnings.append(
                f"Group {label!r}: discarded unrecognized country code(s): {', '.join(unknown)}."
            )
        if colour is None:
            # The group's real value is its title and countries — keep it and
            # let the form assign a palette default (the template falls back
            # when colour is empty).
            warnings.append(
                f"Group {label!r}: colour {raw_colour!r} isn't a #rrggbb colour — "
                "a default colour will be used."
            )
            colour = ""

        try:
            # The stand-in colour keeps Group usable as the title/code
            # validator when the original colour was discarded above.
            Group(title=title, colour=colour or "#000000", country_codes=tuple(codes))
        except ValueError as exc:
            warnings.append(f"Skipped a group: {exc}")
            continue

        # opacity: 1 is stamped uniformly on every group block when circles are
        # on; it is CSS-intrinsic and independent of the base map, so it is
        # recovered even on the fallback path.
        if m.group("opacity"):
            include_circles = True
        groups.append({"index": idx, "title": title, "colour": colour, "countries": codes})
        idx += 1

    # Safety net for blocks that don't parse at all (e.g. a hand-edit removed
    # the fill rule): anything the block regex didn't consume is reported back
    # verbatim — whitespace-collapsed and truncated so a garbage file can't
    # bloat the warning (which travels via the session cookie).
    if css[pos:].strip():
        unparsed.append(css[pos:].strip())
    if unparsed:
        ignored = re.sub(r"\s+", " ", " ".join(unparsed))
        if len(ignored) > 200:
            ignored = ignored[:200] + "…"
        warnings.append(
            f"Some styling in the file couldn't be understood and was ignored: {ignored!r}"
        )

    if not groups:
        warnings.append("No groups could be recovered from this file.")

    return ImportResult(
        map_key=map_key,
        groups=groups,
        land_colour=land_colour,
        ocean_colour=ocean_colour,
        include_circles=include_circles,
        warnings=warnings,
    )
