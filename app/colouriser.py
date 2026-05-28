"""Pure helpers that turn ``Group`` definitions into a CSS snippet.

No Flask dependency — fully unit-testable in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Hex colour pattern for server-side validation. ``<input type="color">``
# always emits ``#rrggbb``, but we re-validate to catch non-browser clients.
COLOUR_PATTERN = "#[0-9a-fA-F]{6}"

# Title pattern shared the same way. Rejects characters that could break out
# of the surrounding CSS comment (``*/``) or the SVG ``<style>`` element.
# ``/`` is escaped because HTML5 ``pattern=`` regex uses JS's ``v`` flag,
# which reserves ``/`` as a syntax character inside character classes.
TITLE_PATTERN = r"[^<>\/*\\]+"

# Paul Tol's "muted" qualitative palette — colour-blind safe and designed for
# categorical data. Tol's 10th colour (#DDDDDD, pale grey) is reserved for
# "missing/bad data" and intentionally omitted here so groups never default
# to the same neutral the SVG uses for un-coloured land.
DEFAULT_GROUP_COLOURS = (
    "#332288",  # indigo
    "#88CCEE",  # cyan
    "#44AA99",  # teal
    "#117733",  # green
    "#999933",  # olive
    "#DDCC77",  # sand
    "#CC6677",  # rose
    "#882255",  # wine
    "#AA4499",  # purple
)

# Global fallback colours for the base land/ocean fills (#dddddd is Tol-Muted's
# reserved "missing/bad data" neutral). When a map declares land/ocean classes,
# build_css always emits a base-fill rule for that side — using the user's
# chosen colour, or these defaults when none was supplied — so the base map is
# normalised regardless of its native fills.
DEFAULT_LAND_COLOUR = "#dddddd"
DEFAULT_OCEAN_COLOUR = "#ffffff"

_TITLE_RE = re.compile(f"^{TITLE_PATTERN}$")
_COLOUR_RE = re.compile(f"^{COLOUR_PATTERN}$")
_CODE_RE = re.compile(r"^[a-z]{2}$")


def _selector_from_classes(classes: tuple[str, ...]) -> str:
    return ", ".join(f".{c}" for c in classes)


@dataclass(frozen=True, slots=True)
class Group:
    title: str
    colour: str  # pre-validated #rrggbb
    country_codes: tuple[str, ...]  # pre-resolved lowercase alpha-2 codes

    def __post_init__(self) -> None:
        if not _TITLE_RE.match(self.title):
            raise ValueError(f"title {self.title!r} contains forbidden characters")
        if not _COLOUR_RE.match(self.colour):
            raise ValueError(f"colour {self.colour!r} must match {COLOUR_PATTERN}")
        if not self.country_codes:
            raise ValueError(f"group {self.title!r} has empty country list")
        for code in self.country_codes:
            if not _CODE_RE.match(code):
                raise ValueError(f"country code {code!r} must be lowercase alpha-2")
        if len(set(self.country_codes)) != len(self.country_codes):
            raise ValueError(f"group {self.title!r} has duplicate country codes")


def build_css(
    groups: list[Group],
    include_small_country_circles: bool = False,
    *,
    land: str | None = None,
    ocean: str | None = None,
    land_classes: tuple[str, ...] | None = None,
    ocean_classes: tuple[str, ...] | None = None,
) -> str:
    """Render groups as a CSS snippet matching the SVG's class names.

    Each group becomes one ``/* title */`` comment followed by a single rule
    selecting all of its countries. Each block is wrapped in newlines so the
    snippet sits cleanly on its own lines inside a ``<style>`` element.

    When ``include_small_country_circles`` is True, each rule also sets
    ``opacity: 1`` so the small-country circles in compatible base maps
    become visible alongside their country fills.

    ``land`` / ``ocean`` (hex strings) plus ``land_classes`` / ``ocean_classes``
    (tuples of CSS class names) prepend base-layer fill rules above the group
    blocks. A side is emitted iff both its colour and its class tuple are
    supplied; pass ``None`` for either to skip that side.
    """
    blocks: list[str] = []

    if land and land_classes:
        if not _COLOUR_RE.match(land):
            raise ValueError(f"land colour {land!r} must match {COLOUR_PATTERN}")
        land_selector = _selector_from_classes(land_classes)
        blocks.append(f"\n/* Land and small circles */\n{land_selector} {{ fill: {land}; }}\n")
    if ocean and ocean_classes:
        if not _COLOUR_RE.match(ocean):
            raise ValueError(f"ocean colour {ocean!r} must match {COLOUR_PATTERN}")
        ocean_selector = _selector_from_classes(ocean_classes)
        blocks.append(
            f"\n/* Oceans, seas, and large lakes */\n{ocean_selector} {{ fill: {ocean}; }}\n"
        )

    extra = " opacity: 1;" if include_small_country_circles else ""
    for group in groups:
        selector = ", ".join(f".{code}" for code in group.country_codes)
        blocks.append(f"\n/* {group.title} */\n{selector} {{ fill: {group.colour};{extra} }}\n")
    return "".join(blocks)


def build_legend(groups: list[Group]) -> str:
    """Render groups as Wikitext ``{{Legend|colour|title}}`` lines, one per group.

    Group validation already enforces non-empty title and country codes, so
    no per-group filtering is needed here (unlike the JS counterpart, which
    works on raw form state).
    """
    return "\n".join(f"{{{{Legend|{group.colour}|{group.title}}}}}" for group in groups)
