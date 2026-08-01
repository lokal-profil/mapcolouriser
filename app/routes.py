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

from app import svg_import
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

# Upper bound for the no-JS add-group route. Groups live in the ~4 KB session
# cookie, and an oversized cookie is dropped silently, so the route that can be
# POSTed in a loop needs a ceiling. Measured against the submitted list length,
# never a high-water mark: removing groups frees the allowance again.
_MAX_GROUPS = 30

_SESSION_MAP_KEY = "map_key"
_SESSION_LAST_GROUPS = "last_groups"
_SESSION_INCLUDE_CIRCLES = "include_circles"
_SESSION_LAND_COLOUR = "land_colour"
_SESSION_OCEAN_COLOUR = "ocean_colour"
_SESSION_IMPORT_WARNINGS = "import_warnings"
# Transient like the warnings above: set by /add-group, popped by the next
# GET / so the new group's title field takes focus once and not on a refresh.
_SESSION_FOCUS_GROUP = "focus_group"
# Also transient: which <details> panel to re-open after a round-trip started
# from inside one. The panels are an exclusive accordion (shared `name`), so a
# single value says it all. Only reachable for actions whose button lives in the
# panel — <details> open state isn't submitted, so nothing else can know.
_SESSION_OPEN_PANEL = "open_panel"


@bp.get("/")
def index() -> str:
    return render_template(
        "index.html",
        **_index_context(
            groups=session.get(_SESSION_LAST_GROUPS) or _default_form_state(),
            errors=[],
            map_key=session.get(_SESSION_MAP_KEY, DEFAULT_MAP),
            land_colour=session.get(_SESSION_LAND_COLOUR, DEFAULT_LAND_COLOUR),
            ocean_colour=session.get(_SESSION_OCEAN_COLOUR, DEFAULT_OCEAN_COLOUR),
            include_circles=bool(session.get(_SESSION_INCLUDE_CIRCLES, False)),
            warnings=session.pop(_SESSION_IMPORT_WARNINGS, []),
            focus_group=session.pop(_SESSION_FOCUS_GROUP, None),
            open_panel=session.pop(_SESSION_OPEN_PANEL, None),
        ),
    )


@bp.post("/generate")
def generate() -> Response | str:
    raw_groups = _parse_groups(request.form)
    map_key = request.form.get("map") or DEFAULT_MAP
    include_circles = request.form.get("circles") == "1"
    land_colour, ocean_colour, base_errors = _resolve_base_colours(request.form)
    errors = _validate(raw_groups, map_key) + base_errors

    if errors:
        return render_template(
            "index.html",
            **_index_context(
                groups=raw_groups or _default_form_state(),
                errors=errors,
                map_key=map_key,
                land_colour=land_colour,
                ocean_colour=ocean_colour,
                include_circles=include_circles,
            ),
        )

    groups = _build_groups(raw_groups)
    svg = _render_with_base(map_key, groups, include_circles, land_colour, ocean_colour)
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


@bp.post("/add-group")
def add_group() -> Response:
    """Append a blank group and send the user back to the form (no-JS path).

    With JS the button's click handler cancels the submit and clones the group
    template client-side; this is the fallback that does the same thing over a
    round-trip. Not a submit attempt, so nothing is validated or rendered.
    The new group's title field is autofocused, which also scrolls it into
    view; when the cap meant nothing was added, a ``#groups`` anchor stands in.
    """
    raw_groups = _parse_groups(request.form)
    # No fragment on the success path: a URL fragment suppresses autofocus
    # (the HTML spec treats it as user input outranking the document's default),
    # and focusing the new title field scrolls it into view anyway. The capped
    # path sets no autofocus, so it still needs the anchor to land usefully.
    anchor = "groups"
    if len(raw_groups) < _MAX_GROUPS:
        # max + 1, matching nextIndex() in main.js: indices are never reused, so
        # a new group can't inherit the palette default of a group that is still
        # on the form (see the `default_colours[index % len]` fallback).
        next_index = max((g["index"] for g in raw_groups), default=-1) + 1
        raw_groups.append({"index": next_index, "title": "", "colour": "", "countries": []})
        # Put the cursor in the new group's title field the way the JS path
        # does; that also scrolls it into view, so no anchor is wanted.
        anchor = None
        session[_SESSION_FOCUS_GROUP] = next_index
    _persist_form_state(raw_groups)
    return redirect(url_for("main.index", _anchor=anchor))


@bp.post("/remove-group")
def remove_group() -> Response:
    """Drop the posted group index and send the user back to the form (no-JS path).

    Redirects to the group above the removed one (``#group-<index>``), or the
    top of the list when there isn't one.

    Removing the only group leaves one blank group rather than none: ``GET /``
    falls back to ``_default_form_state()`` for an empty list, so an empty
    session would reappear as *two* groups. The JS path can hold zero groups
    (Generate and Download disable themselves) — a deliberate divergence.
    """
    raw_groups = _parse_groups(request.form)
    try:
        target = int(request.form.get("remove", ""))
    except ValueError:
        target = None

    # Land on the group above the one removed, so a deletion low in a long list
    # doesn't throw the user back to the top. Removing the first group (or
    # anything unrecognized) falls back to the head of the list, which is where
    # they were looking anyway.
    anchor = "groups"
    if target is not None:
        position = next((i for i, g in enumerate(raw_groups) if g["index"] == target), None)
        if position is not None:
            if position > 0:
                anchor = f"group-{raw_groups[position - 1]['index']}"
            raw_groups = [g for g in raw_groups if g["index"] != target]

    _persist_form_state(raw_groups or _default_form_state(1))
    return redirect(url_for("main.index", _anchor=anchor))


@bp.post("/reset-land-colour")
def reset_land_colour() -> Response:
    """Clear the land-colour override (no-JS path)."""
    return _reset_base_colour(_SESSION_LAND_COLOUR)


@bp.post("/reset-ocean-colour")
def reset_ocean_colour() -> Response:
    """Clear the ocean-colour override (no-JS path)."""
    return _reset_base_colour(_SESSION_OCEAN_COLOUR)


def _reset_base_colour(session_key: str) -> Response:
    """Drop one base-colour override and send the user back to the form.

    Land and ocean get a route each, so which colour is reset comes from the
    URL and there is no request value to validate. The key is *removed* rather
    than set to the default: ``GET /``
    reads these with ``session.get(key, DEFAULT_…)``, so absence is how "not
    overridden" is spelled — the same thing ``/reset`` does wholesale.

    The pop has to follow ``_persist_form_state``, which writes both colours
    from the submitted form. Re-opens the Advanced panel, since that is where
    the button the user clicked lives.
    """
    _persist_form_state(_parse_groups(request.form))
    session.pop(session_key, None)
    session[_SESSION_OPEN_PANEL] = "advanced"
    return redirect(url_for("main.index"))


@bp.post("/import")
def import_svg_route() -> Response:
    """Recover form state from an uploaded, previously generated SVG.

    Persists what was recovered to the session and redirects to ``GET /`` so
    the form repopulates. Warnings (non-blocking) are stashed for that render.
    """
    file = request.files.get("svg")
    if not file:
        session[_SESSION_IMPORT_WARNINGS] = ["No file was uploaded."]
        return redirect(url_for("main.index"))

    result = svg_import.import_svg(
        file.read().decode("utf-8", errors="replace"),
        valid_codes=_VALID_CODES,
    )

    if result.groups:
        session[_SESSION_LAST_GROUPS] = result.groups
        session[_SESSION_MAP_KEY] = result.map_key
        # Only overwrite land/ocean when a colour was actually recovered, so a
        # fallback import doesn't clobber the user's current Advanced settings.
        if result.land_colour:
            session[_SESSION_LAND_COLOUR] = result.land_colour
        if result.ocean_colour:
            session[_SESSION_OCEAN_COLOUR] = result.ocean_colour
        # Circles is CSS-intrinsic (independent of the base map), so restore it
        # whenever any groups were recovered.
        session[_SESSION_INCLUDE_CIRCLES] = result.include_circles

    session[_SESSION_IMPORT_WARNINGS] = result.warnings
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
        svg = _render_with_base(map_key, groups, include_circles, land_colour, ocean_colour)
    except (KeyError, ValueError, TypeError):
        current_app.logger.exception("download: invalid session data")
        return Response("Stored map data is invalid; please regenerate.", status=400)

    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="map.svg"'},
    )


def _render_with_base(
    map_key: str,
    groups: list[Group],
    include_circles: bool,
    land: str,
    ocean: str,
) -> str:
    """Render ``map_key`` with the group + base-layer CSS injected.

    Shared by ``/generate`` and ``/download`` so the two paths can't drift on
    which CSS the base-colour pickers contribute.
    """
    current_map = MAPS[map_key]
    return render_map(
        map_key,
        build_css(
            groups,
            include_small_country_circles=include_circles,
            land=land,
            ocean=ocean,
            land_classes=current_map.land_classes,
            ocean_classes=current_map.ocean_classes,
        ),
    )


def _index_context(
    *,
    groups: list[dict[str, Any]],
    errors: list[str],
    map_key: str,
    land_colour: str,
    ocean_colour: str,
    include_circles: bool,
    warnings: list[str] | None = None,
    focus_group: int | None = None,
    open_panel: str | None = None,
) -> dict[str, Any]:
    """Build the shared template context for the index form.

    Used by ``GET /`` and the ``POST /generate`` error re-render so the
    (growing) kwarg set lives in one place. ``map_key`` is clamped to a known
    map here, so callers may pass a raw session/form value. ``warnings`` is a
    real key (default empty) so the ``/generate`` path never leaves the
    template iterating an undefined value; ``focus_group`` likewise defaults to
    ``None`` so only the render right after a no-JS add carries an autofocus.
    """
    safe_key = map_key if map_key in MAPS else DEFAULT_MAP
    return {
        "countries": all_countries(),
        "groups": groups,
        "errors": errors,
        "warnings": warnings or [],
        "title_pattern": TITLE_PATTERN,
        "colour_pattern": COLOUR_PATTERN,
        "default_colours": DEFAULT_GROUP_COLOURS,
        "default_land_colour": DEFAULT_LAND_COLOUR,
        "default_ocean_colour": DEFAULT_OCEAN_COLOUR,
        "land_colour": land_colour,
        "ocean_colour": ocean_colour,
        "map_key": safe_key,
        "current_map": MAPS[safe_key],
        "maps": MAPS,
        "include_circles": include_circles,
        "focus_group": focus_group,
        "open_panel": open_panel,
    }


def _build_groups(raw_groups: list[dict[str, Any]]) -> list[Group]:
    return [
        Group(
            title=g["title"],
            colour=g["colour"],
            country_codes=tuple(g["countries"]),
        )
        for g in raw_groups
    ]


def _default_form_state(count: int = 2) -> list[dict[str, Any]]:
    return [{"index": i, "title": "", "colour": "", "countries": []} for i in range(count)]


def _persist_form_state(raw_groups: list[dict[str, Any]]) -> None:
    """Store groups plus the form's Advanced settings for the next ``GET /``.

    Used by the add/remove-group routes, which round-trip the whole form so the
    user's typed values survive. Unlike ``/generate`` these routes don't
    validate, so the base map and land/ocean colours are only written when they
    are usable, leaving the previous session value in place otherwise (the rule
    ``/import`` follows too). Nothing downstream trusts them blindly —
    ``/download`` normalises an unknown map key and answers 400 on a colour
    ``build_css`` rejects — but a session poisoned from here would break the
    user's next download until they submitted the form again.
    """
    session[_SESSION_LAST_GROUPS] = raw_groups
    session[_SESSION_INCLUDE_CIRCLES] = request.form.get("circles") == "1"
    map_key = request.form.get("map") or DEFAULT_MAP
    if map_key in MAPS:
        session[_SESSION_MAP_KEY] = map_key
    land_colour, ocean_colour, base_errors = _resolve_base_colours(request.form)
    if not base_errors:
        session[_SESSION_LAND_COLOUR] = land_colour
        session[_SESSION_OCEAN_COLOUR] = ocean_colour


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
