"""Display-name + ISO 3166-1 alpha-2 listing, backed by pycountry.

Swapping pycountry for any other source only requires changing this module;
the rest of the app consumes ``all_countries``.
"""

from __future__ import annotations

from functools import cache

import pycountry

# A friendlier display name to use for entries whose ISO official name is
# awkward in a UI dropdown. Keys are lowercase alpha-2 codes.
_FRIENDLY_NAMES: dict[str, str] = {
    "gb": "United Kingdom",
    "ru": "Russia",
    "kr": "South Korea",
    "kp": "North Korea",
    "ir": "Iran",
    "tw": "Taiwan",
    "bo": "Bolivia",
    "ve": "Venezuela",
    "tz": "Tanzania",
    "sy": "Syria",
    "la": "Laos",
    "vn": "Vietnam",
    "md": "Moldova",
    "ps": "Palestine",
    "fm": "Micronesia",
    "fk": "Falkland Islands",
    "mk": "North Macedonia",
    "cd": "Democratic Republic of the Congo",
    "cg": "Republic of the Congo",
}


def _display_name(country) -> str:
    code = country.alpha_2.lower()
    if code in _FRIENDLY_NAMES:
        return _FRIENDLY_NAMES[code]
    return getattr(country, "common_name", None) or country.name


@cache
def all_countries() -> list[tuple[str, str]]:
    """Return ``(display_name, alpha2)`` pairs sorted by display name."""
    pairs = [(_display_name(c), c.alpha_2.lower()) for c in pycountry.countries]
    pairs.sort(key=lambda item: item[0])
    return pairs
