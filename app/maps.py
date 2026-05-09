"""Registry mapping internal map keys to on-disk filenames in ``static/``.

Keeping the original filename on disk lets us swap in upstream updates
without rewriting code; the internal key is what the rest of the app uses.

``render_map`` is the request-handler entry point: each registered map is
read once, viewBox-enriched once, and split around the injection marker,
so request handlers do no I/O and no scanning of the ~1 MB SVG.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from app.svg_injector import MARKER, add_viewbox_if_missing, validate_svg

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

MAPS: dict[str, str] = {
    "world": "BlankMap-World.svg",
}

DEFAULT_MAP = "world"


def map_path(key: str = DEFAULT_MAP) -> Path:
    """Return the on-disk path for a registered map. Raises KeyError if unknown."""
    if key not in MAPS:
        raise KeyError(f"unknown map key: {key!r}")
    return STATIC_DIR / MAPS[key]


def load_map(key: str = DEFAULT_MAP) -> str:
    """Read and return the SVG text for a registered map."""
    return map_path(key).read_text(encoding="utf-8")


@cache
def _prepared(key: str) -> tuple[str, str]:
    """Return ``(prefix, suffix)`` of the prepared SVG, split around the marker."""
    svg = add_viewbox_if_missing(load_map(key))
    if not validate_svg(svg):
        raise RuntimeError(f"base map {key!r} is missing the injection marker")
    prefix, suffix = svg.split(MARKER, 1)
    return prefix, suffix


def render_map(key: str, css: str) -> str:
    """Return the registered map with ``css`` injected at the marker."""
    prefix, suffix = _prepared(key)
    return prefix + css + suffix


def prime_caches() -> None:
    """Force a one-time read+validate+split of every registered base map.

    Called by the app factory at startup so request handlers do no I/O on
    the first request, and so a missing marker fails fast (defence in depth
    against a CI bypass).
    """
    for key in MAPS:
        _prepared(key)
