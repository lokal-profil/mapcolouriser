#!/usr/bin/env python3
"""CI SVG validation for every registered base map.

Imports ``validate_svg`` from ``app.svg_injector`` and ``MAPS`` from
``app.maps`` so this script and the runtime cannot disagree on the rule.
Exits 0 if all maps validate, 1 otherwise — print one line per failure.

Also checks each map's ``land_classes`` / ``ocean_classes`` actually appear
as element classes in the SVG. ``MapInfo`` only validates that the names are
syntactically valid CSS identifiers; a typo'd-but-valid name (e.g. ``lnadxx``)
would otherwise pass silently and leave the base-colour picker a no-op.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow running this script directly from a checkout (no install required).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.maps import MAPS, load_map  # noqa: E402
from app.svg_injector import validate_svg  # noqa: E402

# Match both quote styles — XML permits class='…' as well as class="…".
_CLASS_ATTR_RE = re.compile(r"""class=(["'])([^"']*)\1""")


def _svg_class_tokens(svg_text: str) -> set[str]:
    """Return the set of every class token used in any ``class="…"`` attribute."""
    tokens: set[str] = set()
    for _quote, value in _CLASS_ATTR_RE.findall(svg_text):
        tokens.update(value.split())
    return tokens


def _missing_base_classes(svg_text: str, info) -> list[str]:
    """Return declared land/ocean class names absent from the SVG, in order."""
    present = _svg_class_tokens(svg_text)
    declared: list[str] = []
    for classes in (info.land_classes, info.ocean_classes):
        if classes:
            declared.extend(classes)
    return [name for name in declared if name not in present]


def main() -> int:
    failed = False
    for key, info in MAPS.items():
        try:
            svg_text = load_map(key)
        except (OSError, UnicodeDecodeError) as e:
            print(f"FAIL {key} ({info.filename}): {e}", file=sys.stderr)
            failed = True
            continue
        if not validate_svg(svg_text):
            print(
                f"FAIL {key} ({info.filename}): not a well-formed SVG",
                file=sys.stderr,
            )
            failed = True
            continue
        missing = _missing_base_classes(svg_text, info)
        if missing:
            print(
                f"FAIL {key} ({info.filename}): "
                f"land/ocean class(es) not found in SVG: {', '.join(missing)}",
                file=sys.stderr,
            )
            failed = True
            continue
        print(f"OK   {key} ({info.filename})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
