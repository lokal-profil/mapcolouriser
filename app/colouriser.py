"""Pure helpers that turn ``Group`` definitions into a CSS snippet.

No Flask dependency — fully unit-testable in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Hex colour pattern shared between server-side validation and the form's
# ``pattern=`` attribute, so the rule lives in exactly one place.
COLOUR_PATTERN = "#[0-9a-fA-F]{6}"

# Title pattern shared the same way. Rejects characters that could break out
# of the surrounding CSS comment (``*/``) or the SVG ``<style>`` element.
TITLE_PATTERN = r"[^<>/*\\]+"

_TITLE_RE = re.compile(f"^{TITLE_PATTERN}$")
_COLOUR_RE = re.compile(f"^{COLOUR_PATTERN}$")
_CODE_RE = re.compile(r"^[a-z]{2}$")


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


def build_css(groups: list[Group]) -> str:
    """Render groups as a CSS snippet matching the SVG's class names.

    Each group becomes one ``/* title */`` comment followed by a single rule
    selecting all of its countries.
    """
    blocks: list[str] = []
    for group in groups:
        selector = ", ".join(f".{code}" for code in group.country_codes)
        blocks.append(f"/* {group.title} */\n{selector} {{ fill: {group.colour}; }}")
    return "\n\n".join(blocks)
