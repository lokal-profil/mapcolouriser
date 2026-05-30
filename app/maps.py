"""Registry mapping internal map keys to on-disk filenames in ``static/``.

Keeping the original filename on disk lets us swap in upstream updates
without rewriting code; the internal key is what the rest of the app uses.

``render_map`` is the request-handler entry point: each registered map is
read once, viewBox-enriched once, and split around its closing ``</svg>``
tag, so request handlers do no I/O and no scanning of the ~1 MB SVG. User
CSS is appended as a fresh ``<style id="map-colouriser-style">`` element
just before the close, matching the client-side preview's approach.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.svg_injector import add_viewbox_if_missing, validate_svg

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_CLASS_NAME_RE = re.compile(r"^[a-zA-Z_][\w-]*$")


@dataclass(frozen=True, slots=True, kw_only=True)
class MapInfo:
    """Per-registered-map metadata.

    ``filename`` is the on-disk SVG name in ``static/``; ``label`` is the
    selector option text; ``description`` (when set) renders as a ``title``
    tooltip on the option.

    ``land_classes`` / ``ocean_classes`` drive the Advanced-panel base-colour
    pickers: each is a tuple of CSS class names (no leading ``.``) joined into
    a selector at build time. Both default to ``None`` — a map opts *in* to a
    picker by declaring the class names it should fill; leaving a side unset
    hides that picker (the UI omits the row and no rule is emitted). Class
    names are not inherited, so each map states the classes its own SVG uses.
    """

    filename: str
    label: str
    description: str = ""
    land_classes: tuple[str, ...] | None = None
    ocean_classes: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        for field_name in ("land_classes", "ocean_classes"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not value:
                raise ValueError(f"{field_name} must be None or a non-empty tuple")
            for name in value:
                if not _CLASS_NAME_RE.match(name):
                    raise ValueError(f"{field_name} entry {name!r} is not a valid CSS class name")


MAPS: dict[str, MapInfo] = {
    "world": MapInfo(
        filename="BlankMap-World.svg",
        label="World",
        land_classes=("landxx", "circlexx"),
        ocean_classes=("oceanxx",),
        description="A Robinson projection centered on the 0th meridian.",
    ),
    "world-compact": MapInfo(
        filename="BlankMap-World-Compact.svg",
        label="World (compact)",
        land_classes=("landxx", "circlexx", "limitxx"),
        ocean_classes=("oceanxx",),
        description=(
            "A compact Robinson projection centered on the 0th meridian with Antarctica removed."
        ),
    ),
}

DEFAULT_MAP = "world"


def map_path(key: str = DEFAULT_MAP) -> Path:
    """Return the on-disk path for a registered map. Raises KeyError if unknown."""
    if key not in MAPS:
        raise KeyError(f"unknown map key: {key!r}")
    return STATIC_DIR / MAPS[key].filename


def load_map(key: str = DEFAULT_MAP) -> str:
    """Read and return the SVG text for a registered map."""
    return map_path(key).read_text(encoding="utf-8")


@cache
def _prepared(key: str) -> tuple[str, str]:
    """Return ``(prefix, suffix)`` split immediately before the final ``</svg>``.

    The closing tag is included in ``suffix``; callers concatenate
    ``prefix + new_content + suffix`` without re-adding it. ``validate_svg``
    guarantees ``</svg>`` is present, so the ``rfind`` cannot return ``-1``.
    """
    svg = add_viewbox_if_missing(load_map(key))
    if not validate_svg(svg):
        raise RuntimeError(f"base map {key!r} is not a well-formed SVG")
    idx = svg.rfind("</svg>")
    return svg[:idx], svg[idx:]


def render_map(key: str, css: str) -> str:
    """Return the registered map with ``css`` injected as a ``<style>`` element.

    Caller must ensure ``css`` contains no ``</style>`` or ``</svg>`` substring;
    ``app.colouriser.build_css`` satisfies this because ``Group`` validation
    rejects ``<``, ``>``, ``/``, ``*`` and ``\\`` in titles.
    """
    prefix, suffix = _prepared(key)
    return f'{prefix}<style id="map-colouriser-style">{css}</style>{suffix}'


def prepared_svg(key: str = DEFAULT_MAP) -> str:
    """Return the prepared (viewBox-enriched) SVG with no user CSS.

    Served by the ``/maps/<key>.svg`` endpoint so the client-side live
    preview can fetch the base map and append its own ``<style>`` element.
    """
    prefix, suffix = _prepared(key)
    return prefix + suffix


def prime_caches() -> None:
    """Force a one-time read+validate+split of every registered base map.

    Called by the app factory at startup so request handlers do no I/O on
    the first request, and so a malformed SVG fails fast (defence in depth
    against a CI bypass).
    """
    for key in MAPS:
        _prepared(key)
