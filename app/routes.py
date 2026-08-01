"""HTTP routes for the colouriser."""

from __future__ import annotations

import json
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

# Bounds on what may be stored in the ~4 KB session cookie, enforced in
# _persist_form_state (the shared writer) rather than at any one route: an
# oversized cookie is dropped silently, and a large group list also makes every
# later GET / re-render a ~250-option select per group. Measured against the
# submitted list length, never a high-water mark, so removing groups frees the
# allowance again. Neither is a hard size guarantee — a group can select every
# country — but together they bound what one request can persist.
_MAX_GROUPS = 30
_MAX_TITLE_LEN = 100
# Budget for the JSON form of the group list. The signed cookie must stay under
# the browsers' ~4093-byte ceiling once the other session keys and the signature
# are added, and base64 inflates the payload by a third, so the raw JSON gets a
# deliberately conservative slice of it.
_MAX_SESSION_GROUP_BYTES = 2500

_SESSION_MAP_KEY = "map_key"
# What the *form* shows. Written by every route that edits the form, so it holds
# in-progress state that need not be renderable (a blank group, a half-typed
# title). `GET /` repopulates from it.
_SESSION_LAST_GROUPS = "last_groups"
# What `/download` re-renders. Written only where the groups are known to build
# — `/generate` after validation — so an edit to the form can't break the
# download of a map that already generated. Never read by `GET /`.
_SESSION_GENERATED_GROUPS = "generated_groups"
_SESSION_INCLUDE_CIRCLES = "include_circles"
_SESSION_LAND_COLOUR = "land_colour"
_SESSION_OCEAN_COLOUR = "ocean_colour"
# Non-blocking messages for the next render, popped by `GET /`. Deliberately
# not import-specific: /import, /add-group and _persist_form_state all report
# through it, so each message must be a self-contained sentence rather than
# relying on a heading to supply the context.
_SESSION_WARNINGS = "warnings"
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
            warnings=session.pop(_SESSION_WARNINGS, []),
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
    # The one place both keys agree: these groups just rendered, so they are
    # both what the form shows and what `/download` may re-render.
    session[_SESSION_GENERATED_GROUPS] = raw_groups
    session[_SESSION_INCLUDE_CIRCLES] = include_circles
    session[_SESSION_LAND_COLOUR] = land_colour
    session[_SESSION_OCEAN_COLOUR] = ocean_colour

    return render_template("result.html", svg=svg, legend=legend)


@bp.post("/reset")
def reset() -> Response:
    """Clear stored form state and send the user back to a fresh form."""
    session.pop(_SESSION_LAST_GROUPS, None)
    session.pop(_SESSION_GENERATED_GROUPS, None)
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
    if not raw_groups or len(raw_groups) >= _MAX_GROUPS:
        # Nothing to append to, or the ceiling is reached. Either way no group
        # was added, so there is no autofocus to scroll the page and the list
        # anchor stands in. Say so — a full reload with nothing added and no
        # message reads as a broken button.
        if raw_groups:
            _warn(f"You can have at most {_MAX_GROUPS} groups. Remove one to add another.")
        _persist_form_state(raw_groups)
        return redirect(url_for("main.index", _anchor="groups"))

    # max + 1, matching nextIndex() in main.js: indices are never reused, so a
    # new group can't inherit the palette default of a group that is still on
    # the form (see the `default_colours[index % len]` fallback).
    next_index = max(g["index"] for g in raw_groups) + 1
    raw_groups.append({"index": next_index, "title": "", "colour": "", "countries": []})
    # Put the cursor in the new group's title field the way the JS path does.
    # That also scrolls it into view, so this redirect must carry no fragment:
    # a URL fragment suppresses autofocus, the HTML spec ranking it above the
    # document's default.
    session[_SESSION_FOCUS_GROUP] = next_index
    _persist_form_state(raw_groups)
    return redirect(url_for("main.index"))


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
    # they were looking anyway. An unparseable index leaves `target` None, which
    # matches no group, so the lookup below covers that case too.
    anchor = "groups"
    position = next((i for i, g in enumerate(raw_groups) if g["index"] == target), None)
    if position is not None:
        if position > 0:
            anchor = f"group-{raw_groups[position - 1]['index']}"
        # Removing the only group leaves one blank group rather than none, but
        # only once something was actually removed — a request carrying no
        # groups at all must not overwrite the stored ones with a blank.
        raw_groups = [g for g in raw_groups if g["index"] != target] or _default_form_state(1)

    _persist_form_state(raw_groups)
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

    Land and ocean get a route each, so no request value decides *which* colour
    is reset (the rest of the submitted form still goes through
    ``_persist_form_state``, which validates it). The key is *removed* rather
    than set to the default: ``GET /``
    reads these with ``session.get(key, DEFAULT_…)``, so absence is how "not
    overridden" is spelled — the same thing ``/reset`` does wholesale.

    The pop has to follow ``_persist_form_state``, which writes back whichever
    colours the form submitted. Re-opens the Advanced panel, since that is
    where the button the user clicked lives.
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
        session[_SESSION_WARNINGS] = ["No file was uploaded."]
        return redirect(url_for("main.index"))

    result = svg_import.import_svg(
        file.read().decode("utf-8", errors="replace"),
        valid_codes=_VALID_CODES,
    )

    if result.groups:
        session[_SESSION_LAST_GROUPS] = result.groups
        # The form no longer matches whatever was generated before, and an
        # import can legitimately yield a group with an empty colour (a
        # malformed one becomes a palette default at render time), which
        # `_build_groups` would reject. Drop the download rather than serve a
        # stale map or a 400.
        session.pop(_SESSION_GENERATED_GROUPS, None)
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

    if result.warnings:
        # The message box is shared, so each source states its own context.
        _warn("The import failed or was only partially successful.")
        for warning in result.warnings:
            _warn(warning)
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
    # Deliberately the generated key, not the form key: editing the form (adding
    # a blank group, say) must not break the download of a map that already
    # rendered.
    raw_groups = session.get(_SESSION_GENERATED_GROUPS)
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
        "max_title_len": _MAX_TITLE_LEN,
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


def _warn(message: str) -> None:
    """Queue a non-blocking message for the next ``GET /`` to show and pop.

    Appends rather than replaces: one request can hit more than one of these
    (a cap message and an oversized-state message, say).
    """
    session[_SESSION_WARNINGS] = [*session.get(_SESSION_WARNINGS, []), message]


def _default_form_state(count: int = 2) -> list[dict[str, Any]]:
    return [{"index": i, "title": "", "colour": "", "countries": []} for i in range(count)]


def _persist_form_state(raw_groups: list[dict[str, Any]]) -> None:
    """Store in-progress form state for the next ``GET /``.

    Called by the add/remove-group routes and both base-colour reset routes,
    which round-trip the whole form so the user's typed values survive. Unlike
    ``/generate`` none of them validate, so this is the chokepoint that keeps
    the session sane, and every rule below exists because one of these routes
    can be POSTed directly:

    * groups are clamped to ``_MAX_GROUPS`` and titles to ``_MAX_TITLE_LEN``.
      The cap on ``/add-group`` only stops the button growing the list; without
      a clamp here a single hand-made POST persists any number of groups, and
      each one re-renders a ~250-option select on every later ``GET /``.
    * an empty list is not written at all. A request carrying no ``group[…]``
      fields means "no group data in this request", not "delete their groups".
    * the base map and each colour are written independently, and only when the
      field is present and usable. One malformed colour must not discard the
      other, and a map that doesn't render the ocean row posts no ocean field —
      that is silence, not a request to reset the stored value.
    """
    if raw_groups:
        clamped = [{**g, "title": g["title"][:_MAX_TITLE_LEN]} for g in raw_groups[:_MAX_GROUPS]]
        # Even clamped, a full form can outgrow the cookie: 30 groups each
        # selecting many countries serialises past the ~4 KB limit, at which
        # point the browser drops the whole cookie and the user loses every
        # value they typed with nothing on screen to explain it. Refuse the
        # write instead, keeping the last state that did fit, and say so.
        if len(json.dumps(clamped)) > _MAX_SESSION_GROUP_BYTES:
            current_app.logger.warning(
                "persist_form_state: group state too large to store (%d groups)", len(clamped)
            )
            _warn(
                "That's too much to remember between page loads — your last saved groups "
                "were kept. Remove a group or some countries, then try again."
            )
        else:
            session[_SESSION_LAST_GROUPS] = clamped
    session[_SESSION_INCLUDE_CIRCLES] = request.form.get("circles") == "1"

    map_key = request.form.get("map")
    if map_key in MAPS:
        session[_SESSION_MAP_KEY] = map_key
    elif map_key:
        current_app.logger.warning("persist_form_state: unknown map key %r", map_key)

    for field, key in (
        ("land_colour", _SESSION_LAND_COLOUR),
        ("ocean_colour", _SESSION_OCEAN_COLOUR),
    ):
        value = (request.form.get(field) or "").strip()
        if not value:
            continue
        if _COLOUR_RE.match(value):
            session[key] = value
        else:
            current_app.logger.info("persist_form_state: rejected %s %r", field, value)


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

    # The only route that writes group state without going through
    # _persist_form_state, so the ceiling has to be repeated here or /generate
    # stays an open door: a 16 KB POST of 100 valid groups persists all of them
    # and makes every later GET / render ~6 MB (each group repeats a ~250-option
    # select). Rejected rather than clamped — this is a real submit, and
    # silently dropping groups 31+ would hand back a map missing data the user
    # deliberately built.
    if len(groups) > _MAX_GROUPS:
        errors.append(f"You can have at most {_MAX_GROUPS} groups.")
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
