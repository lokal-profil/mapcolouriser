#!/usr/bin/env python3
"""CI SVG validation for every registered base map.

Imports ``validate_svg`` from ``app.svg_injector`` and ``MAPS`` from
``app.maps`` so this script and the runtime cannot disagree on the rule.
Exits 0 if all maps validate, 1 otherwise — print one line per failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running this script directly from a checkout (no install required).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.maps import MAPS, load_map  # noqa: E402
from app.svg_injector import validate_svg  # noqa: E402


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
        print(f"OK   {key} ({info.filename})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
