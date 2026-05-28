"""HTTP routes for the colouriser."""

from __future__ import annotations

import re
from typing import Any

from flask import (
    Blueprint,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.colouriser import (
    COLOUR_PATTERN,
    DEFAULT_GROUP_COLOURS,
    DEFAULT_LAND_COLOUR,
    DEFAULT_OCEAN_COLOUR,
    TITLE_PATTERN,
    Group,
    build_css,
    build_legend,
)
from app.countries import all_countries
from app.maps import DEFAULT_MAP, MAPS, prepared_svg, render_map

bp = Blueprint("main", __name__)

_COLOUR_RE = re.compile(f"^{COLOUR_PATTERN}$")
_TITLE_RE = re.compile(f"^{TITLE_PATTERN}$")
_GROUP_KEY_RE = re.compile(r"^group\[(\d+)\]")

# Domain-level allowlist for country codes — the route layer owns the pycountry
# coupling so app.colouriser stays a pure leaf module. Computed once at import.
_VALID_CODES = frozenset(code for _, code in all_countries())

_SESSION_MAP_KEY = "map_key"
_SESSION_LAST_GROUPS = "last_groups"
_SESSION_INCLUDE_CIRCLES = "include_circles"
_SESSION_LAND_COLOUR = "land_colour"
_SESSION_OCEAN_COLOUR = "ocean_colour"


@bp.get("/")
def index() -> str:
    session_map_key = session.get(_SESSION_MAP_KEY, DEFAULT_MAP)
    map_key = session_map_key if session_map_key in MAPS else DEFAULT_MAP
    return render_template(
        "index.html",
        countries=all_countries(),
        groups=session.get(_SESSION_LAST_GROUPS) or _default_form_state(),
        errors=[],
        title_pattern=TITLE_PATTERN,
        colour_pattern=COLOUR_PATTERN,
        default_colours=DEFAULT_GROUP_COLOURS,
        default_land_colour=DEFAULT_LAND_COLOUR,
        default_ocean_colour=DEFAULT_OCEAN_COLOUR,
        land_colour=session.get(_SESSION_LAND_COLOUR, DEFAULT_LAND_COLOUR),
        ocean_colour=session.get(_SESSION_OCEAN_COLOUR, DEFAULT_OCEAN_COLOUR),
        map_key=map_key,
        current_map=MAPS[map_key],
        maps=MAPS,
        include_circles=bool(session.get(_SESSION_INCLUDE_CIRCLES, False)),
    )


@bp.post("/generate")
def generate() -> Response | str:
    raw_groups = _parse_groups(request.form)
    map_key = request.form.get("map") or DEFAULT_MAP
    include_circles = request.form.get("circles") == "1"
    land_colour, ocean_colour, base_errors = _resolve_base_colours(request.form)
    errors = _validate(raw_groups, map_key) + base_errors

    if errors:
        safe_key = map_key if map_key in MAPS else DEFAULT_MAP
        return render_template(
            "index.html",
            countries=all_countries(),
            groups=raw_groups or _default_form_state(),
            errors=errors,
            title_pattern=TITLE_PATTERN,
            colour_pattern=COLOUR_PATTERN,
            default_colours=DEFAULT_GROUP_COLOURS,
            default_land_colour=DEFAULT_LAND_COLOUR,
            default_ocean_colour=DEFAULT_OCEAN_COLOUR,
            land_colour=land_colour,
            ocean_colour=ocean_colour,
            map_key=safe_key,
            current_map=MAPS[safe_key],
            maps=MAPS,
            include_circles=include_circles,
        )

    groups = _build_groups(raw_groups)
    current_map = MAPS[map_key]
    svg = render_map(
        map_key,
        build_css(
            groups,
            include_small_country_circles=include_circles,
            land=land_colour,
            ocean=ocean_colour,
            land_classes=current_map.land_classes,
            ocean_classes=current_map.ocean_classes,
        ),
    )
    legend = build_legend(groups)

    session[_SESSION_MAP_KEY] = map_key
    session[_SESSION_LAST_GROUPS] = raw_groups
    session[_SESSION_INCLUDE_CIRCLES] = include_circles
    session[_SESSION_LAND_COLOUR] = land_colour
    session[_SESSION_OCEAN_COLOUR] = ocean_colour

    return render_template("result.html", svg=svg, legend=legend)


@bp.post("/reset")
def reset() -> Response:
    """Clear stored form state and send the user back to a fresh form."""
    session.pop(_SESSION_LAST_GROUPS, None)
    session.pop(_SESSION_MAP_KEY, None)
    session.pop(_SESSION_INCLUDE_CIRCLES, None)
    session.pop(_SESSION_LAND_COLOUR, None)
    session.pop(_SESSION_OCEAN_COLOUR, None)
    return redirect(url_for("main.index"))


@bp.get("/maps/<key>.svg")
def base_map(key: str) -> Response:
    if key not in MAPS:
        return Response("Unknown map.", status=404)
    return Response(
        prepared_svg(key),
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@bp.get("/download")
def download() -> Response:
    raw_groups = session.get(_SESSION_LAST_GROUPS)
    map_key = session.get(_SESSION_MAP_KEY, DEFAULT_MAP)
    include_circles = bool(session.get(_SESSION_INCLUDE_CIRCLES, False))
    land_colour = session.get(_SESSION_LAND_COLOUR, DEFAULT_LAND_COLOUR)
    ocean_colour = session.get(_SESSION_OCEAN_COLOUR, DEFAULT_OCEAN_COLOUR)
    if not raw_groups:
        return Response("No generated map in session.", status=400)

    if map_key not in MAPS:
        current_app.logger.warning("download: unknown map_key in session: %r", map_key)
        map_key = DEFAULT_MAP

    try:
        groups = _build_groups(raw_groups)
        current_map = MAPS[map_key]
        svg = render_map(
            map_key,
            build_css(
                groups,
                include_small_country_circles=include_circles,
                land=land_colour,
                ocean=ocean_colour,
                land_classes=current_map.land_classes,
                ocean_classes=current_map.ocean_classes,
            ),
        )
    except (KeyError, ValueError, TypeError):
        current_app.logger.exception("download: invalid session data")
        return Response("Stored map data is invalid; please regenerate.", status=400)

    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="map.svg"'},
    )


def _build_groups(raw_groups: list[dict[str, Any]]) -> list[Group]:
    return [
        Group(
            title=g["title"],
            colour=g["colour"],
            country_codes=tuple(g["countries"]),
        )
        for g in raw_groups
    ]


def _default_form_state() -> list[dict[str, Any]]:
    return [{"index": i, "title": "", "colour": "", "countries": []} for i in range(2)]


def _resolve_base_colours(form) -> tuple[str, str, list[str]]:
    """Read land/ocean colour from ``form``, falling back to the global defaults.

    Missing fields silently use the defaults; present-but-malformed values
    accumulate in the returned errors list so the form re-renders with the
    user's invalid input intact.
    """
    land = (form.get("land_colour") or "").strip() or DEFAULT_LAND_COLOUR
    ocean = (form.get("ocean_colour") or "").strip() or DEFAULT_OCEAN_COLOUR
    errors: list[str] = []
    if not _COLOUR_RE.match(land):
        errors.append("Land fill: colour must be in the form #rrggbb.")
    if not _COLOUR_RE.match(ocean):
        errors.append("Ocean fill: colour must be in the form #rrggbb.")
    return land, ocean, errors


def _parse_groups(form) -> list[dict[str, Any]]:
    indices: set[int] = set()
    for key in form:
        match = _GROUP_KEY_RE.match(key)
        if match:
            indices.add(int(match.group(1)))

    return [
        {
            "index": idx,
            "title": form.get(f"group[{idx}][title]", "").strip(),
            "colour": form.get(f"group[{idx}][colour]", "").strip(),
            "countries": form.getlist(f"group[{idx}][countries][]"),
        }
        for idx in sorted(indices)
    ]


def _validate(groups: list[dict[str, Any]], map_key: str) -> list[str]:
    errors: list[str] = []

    if map_key not in MAPS:
        errors.append(f"Unknown map: {map_key!r}.")

    if not groups:
        errors.append("At least one group is required.")
        return errors

    for g in groups:
        label = g["title"] or f"Group {g['index'] + 1}"
        if not g["title"]:
            errors.append(f"{label}: title is required.")
        elif not _TITLE_RE.match(g["title"]):
            errors.append(f"{label}: title may not contain `<`, `>`, `/`, `*` or `\\`.")
        if not _COLOUR_RE.match(g["colour"]):
            errors.append(f"{label}: colour must be in the form #rrggbb.")
        if not g["countries"]:
            errors.append(f"{label}: select at least one country.")
        else:
            unknown = [c for c in g["countries"] if c not in _VALID_CODES]
            if unknown:
                errors.append(f"{label}: unknown country code(s): {', '.join(sorted(unknown))}.")

    return errors
