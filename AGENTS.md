# AGENTS.md

Guidance for AI coding agents working in this repository.

## What belongs here

`README.md` is for people using or deploying the tool: features, setup, running it, Toolforge. This file is for people changing it — the invariants, couplings and traps that make a change go wrong.

The dividing line inside this file matters just as much: **don't restate what a module's own docstrings say — point at them.** Record something here only when it spans files, contradicts an obvious assumption, or can't be seen by reading the one file you're editing. Bullets that duplicate a docstring go stale silently, because nothing fails when the code moves on.

## Pre-commit verification

CI runs `ruff format --check` as a separate gate from `ruff check`. If you only run the latter locally, you'll pass-then-fail CI on formatting-only diffs. After any Python edit, run all of:

- `uv run pytest -q`
- `uv run ruff check`
- `uv run ruff format --check`
- `pnpm test` (if you touched JS, templates, or static assets the JS suite cares about)

`uv run python scripts/check_svg.py` validates the registered base SVGs — only needed if you've added or modified a map.

## Running a single test

- Python: `uv run pytest tests/test_routes.py::TestClass::test_name -q`
- JS: `pnpm test -- -t "substring of test name"` (Vitest `-t` filter)

## Architecture

### Server

Flask app factory in `app/__init__.py`. Routes in `app/routes.py` are thin (parse / validate / persist to session); all rendering logic lives in pure leaf modules so it stays testable without a Flask context:

- `app/colouriser.py` — `Group` dataclass (form validation), `build_css(groups, include_small_country_circles=False)`, `build_legend(groups)`. No Flask imports. **`Group`'s title validation is what makes CSS injection safe**: `render_map` splices `build_css` output straight into the SVG and relies on titles never containing `<`, `>`, `/`, `*` or `\`, so a group title can't close the `<style>` element or the CSS comment around it. Relaxing `TITLE_PATTERN` breaks a guarantee enforced two modules away.
- `app/maps.py` — the `MAPS` registry (frozen `MapInfo`, `kw_only=True`) and `render_map(key, css)`, which injects the user CSS just before `</svg>`. `_prepared(key)` is `@cache`-decorated and `prime_caches()` runs at startup, so request handlers do no I/O; see the module and `render_map` docstrings for why.
- `app/svg_injector.py` — `validate_svg` (XML well-formedness + literal `</svg>` close-tag) and `add_viewbox_if_missing`. `validate_svg` parses via `defusedxml` because it also vets **untrusted uploads** on the import path, not just the trusted `static/` base maps; it catches both `ParseError` and `DefusedXmlException` (the latter does not subclass the former).
- `app/svg_import.py` — pure leaf (no Flask), mirrors `colouriser.py`; reads back the injected `<style ... data-map="…">` element to reconstruct form state. The recovery rules (per-code discards, repeated-code merging, `DEFAULT_MAP` fallback, land/ocean classification by class overlap) are all in `import_svg`'s docstring — read it before changing the parser.

  Import-warning conventions: end-user language (say "group" and "country code", never parser jargon like "style block"); name the affected group; truncate any file content echoed back (warnings travel via the ~4 KB session cookie); warnings must only render through `{{ warning }}` (autoescaped) — never `|safe`. The parser is deliberately tolerant of what browsers/optimizers accept (trailing `;` optional, `#rgb` expanded, duplicate code merged rather than fatal, broken group colour → keep the group with an empty colour so the form assigns a palette default) — don't tighten it back; there's an SVGO-shaped round-trip test guarding this.

### Client

- `static/main.js` — ES module. Pure helpers `buildCss(state, {includeCircles})` and `buildLegend(state)` are named exports. `createApp(doc = document)` is a factory: looks up DOM elements, returns an object with `{init, addGroup, removeGroup, downloadSvg, initMap, setLivePreviewEnabled, getGroupState}` so tests can drive behaviour without dispatching synthetic events. The page entry is an inline `<script type="module">` in `index.html` calling `createApp()?.init()`.
- `static/country_multiselect.js` — Codex MultiselectLookup-style enhancement of each group's country `<select multiple>`, applied by a private `enhanceCountrySelects()` in `createApp`. What matters when touching it:
  - **The select stays in the DOM (hidden) as the source of truth.** The widget writes `option.selected` and dispatches a bubbling `change`, which is why form POST, `getGroupState()`, live preview, import and the no-JS baseline all keep working untouched.
  - **`required` moves to the visible input.** A hidden `required` select aborts submits invisibly, so enhancement drops the attribute and mirrors it as a `setCustomValidity` customError on the search input.
  - Deliberate deviations from Codex, don't "fix" them: selected countries leave the menu (chips are the removal affordance), chips are plain buttons, no query highlighting, and selection keeps the menu open with the query preselected so typing starts a fresh one.
- `static/main.css` — single external stylesheet (extracted from a former inline `<style>` block); rules grouped by section with blank lines.
- **Button and form-control styling follows the Codex style guide** (doc.wikimedia.org/codex). Text inputs, the base-map select, textarea, Message boxes and toggle switches use Codex component colours; the toggles' compact size is a deliberate deviation. When adding a control:
  - **Semantic** — progressive (blue) produces or advances output (Generate, Download, Import); destructive (red) discards user input (Reset, Remove group, base-colour resets); neutral is additive or utility (+ Add group, Copy).
  - **Weight** — `.btn-primary.btn-progressive` (filled) for THE main action, only one visible per view (Generate is `.js-fallback`, Download `.js-live`, so they swap); plain classes for framed normal; `.btn-quiet` for tertiary or repeated actions.
  - **Order** — most important last, destructive first.
  - **Colours** — Codex design tokens only, commented in `main.css`; don't invent new ones.
  - `.btn` styles a *link* as a button — the Codex exception used by result.html's Download. It is a link on purpose; don't "fix" it into a nested `<a><button>`.
- `app/templates/base.html` — shell with FOUC-prevention inline script in `<head>`, h1 + `header_actions` block, the `config.TEST_DEPLOYMENT` banner (set from the env var of the same name in the app factory; README documents the Toolforge side), page footer, and `<link rel="stylesheet" href="...main.css">`.
- `index.html` and `result.html` extend `base.html`.

### Cross-cutting patterns

- **Progressive enhancement** — JS-off posts to the server; JS-on cancels the submission and does the work client-side. CSS hides the submit button in live-preview mode (`.js-fallback`) and hides the toggle / live-only controls in JS-off mode (`.js-only`).

#### Every no-JS control has the same shape

A button that works without JS is a real `type="submit"` with `formaction` + `formnovalidate`, and `main.js` cancels its click so JS users never reload. Four rules, each with teeth:

- **`formnovalidate` is required.** Without it the form's empty `required` fields block the submit outright.
- **`form="colouriser-form"` is required for anything in the header**, which is outside the `<form>` element. Without it the button submits nothing.
- **`preventDefault()` in the JS handler is required.** Drop one and that action silently becomes a page load for every JS user, which no server-side test can catch — only the `defaultPrevented` JS tests do.
- **A control cloned from `<template id="group-template">` exists twice in markup** and both copies must carry the same attributes. `patchPlaceholders` rewrites `name`/`id`/`for`/`value`, which is why `value="__INDEX__"` on the clone's Remove button resolves.

| Control | Route | Where it lands afterwards |
| --- | --- | --- |
| + Add group | `/add-group` | autofocuses the new title — **and therefore sends no fragment** |
| Remove group | `/remove-group` | `#group-<index>` of the group *above* the removed one |
| Reset land / ocean | `/reset-{land,ocean}-colour` | reopens the Advanced panel; no anchor needed, it's in the header |
| Reset (all groups) | `/reset` | top of the page |

- **Anchor and autofocus are mutually exclusive.** A URL fragment suppresses autofocus — the HTML spec ranks it above the document's default — so a route uses one or the other, never both. `/add-group` falls back to `#groups` only when the cap meant nothing was added.
- **Enter must keep meaning "Generate".** `.header-actions` opens with a `visually-hidden` form-owned submit and it must stay first: implicit submission activates the first form-owned submit in tree order, and the header renders before the form. Without it a header Reset claims the role — Enter while typing a group title reverts a base colour, or on a map declaring no land/ocean classes deletes the first group. Visually hidden, not `hidden`, which engines have skipped for implicit submission. `test_the_forms_default_button_generates` pins the ordering, since no test client can press Enter.
- **JS owns the reset buttons' `disabled` state** (`syncResetState`, established in `init()` rather than inherited from the markup). The server renders them enabled unconditionally: it can't keep "is this overridden?" truthful as the picker changes, and a disabled button would strand a JS-off user.
- **The server keeps a minimum of one group.** `GET /` renders `_default_form_state()` for an empty list, so zero groups would come back as *two*.
- **Group indices are `max + 1` in both paths, never renumbered.** Reusing an index that is still on the form collapses two groups into one, since `_parse_groups` keys by index.

#### Session state

- **Two group keys, deliberately** — `last_groups` is what the *form* shows and may hold un-renderable in-progress state (a blank group, a half-typed title); `generated_groups` is what `/download` re-renders, written only by `/generate` after validation. That separation is why editing the form can't 400 the download of a map that already generated. `GET /` never reads `generated_groups`; `/download` never reads `last_groups`; `/import` pops it.
- **`_persist_form_state` is the chokepoint for unvalidated writes** — the four no-JS routes don't validate, so it clamps to `_MAX_GROUPS` and `_MAX_TITLE_LEN`, refuses a write over `_MAX_SESSION_GROUP_BYTES` (an oversized cookie is dropped by the browser, losing everything silently — warn instead), skips the groups write for an empty list ("no group data in this request" ≠ "delete their groups"), and writes the map key and each colour independently and only when present and usable. Keep the bounds here, not per-route: three of the four routes never touch `/add-group`'s cap. `/generate` bypasses this helper entirely, so `_validate` repeats the group ceiling.
- **Transient keys use a pop-once idiom** — `GET /` reads and clears them, so a refresh doesn't repeat the effect: `warnings` (messages above the form; written by several routes, so each message carries its own context rather than leaning on the heading), `focus_group`, `open_panel`.
- **`<details>` panels come back collapsed after any no-JS round-trip** — their open state isn't submitted, which is what `open_panel` exists for. Only a route whose button lives *inside* a panel can know to set it, so add/remove group can't.
- **Other persistence** — live-preview toggle in `localStorage` (`mapcolouriser:live-preview`), untouched by `POST /reset`, which clears the session keys.

#### Two-place invariants

- **`data-map` is stamped in `render_map` and in `initMap`** — server-rendered/`/download` files, and the client `<style>` that `downloadSvg` serializes via `XMLSerializer`. The default JS-on download ships the *client* copy, so dropping the `main.js` stamp silently breaks re-import for most users while every server-side test stays green. If the format changes, change both and check `_STYLE_OPEN_RE` in `app/svg_import.py`.
- **Race guard in `initMap`** — `mapRequestSeq` is a monotonic counter; rapid map-selector switches issue overlapping fetches and the `.then`/`.catch` handlers bail when `myReq !== mapRequestSeq`, so an older fetch resolving second can't overwrite the newer preview. Don't remove these guards without reading commit `f21ac18`'s history.

### Gotcha: `MAPS` is imported by reference

`app/routes.py` and `scripts/check_svg.py` both do `from app.maps import MAPS`, capturing a reference to the dict object. `monkeypatch.setattr(maps_module, "MAPS", ...)` does NOT propagate to those importers — they still see the original. Use one of:

- `monkeypatch.setitem(maps_module.MAPS, key, MapInfo(...))` / `monkeypatch.delitem(...)` — mutate the shared dict in place (auto-restored by monkeypatch).
- `monkeypatch.setattr(maps_module, "MAPS", {...})` AND `monkeypatch.setattr(other_module, "MAPS", {...})` for each importer (the pattern used in `tests/test_check_svg.py`).

### Test fixture conventions

- **JS** — committed code never assigns `innerHTML`, so the suites build their DOM with `DOMParser + document.documentElement.replaceWith(...)` instead. Follow the same pattern when adding JS tests. (Under Claude Code a project hook enforces this; on other tooling treat it as convention.)
- **Import edge cases** — `tests/test_svg_import.py` has a `_lenient_group` helper that builds a `Group` with validation bypassed, so fixtures carrying values `Group` rejects (non-alpha-2 codes, repeated codes, non-`#rrggbb` colours) still render through `build_css` and stay coupled to its block format. Use it whenever the invalid thing is a *value*. Keep literal CSS strings when the invalid thing is the block *shape* — optional semicolons, minified/SVGO input, a block with no `fill` rule — since generating those from our own formatter would test it against itself. Land/ocean colour shorthand also has to stay literal: `build_css` re-validates those two colours and would reject `#ddd` before it reached the output.

---

Using Claude Code? It reads `CLAUDE.md`, not `AGENTS.md`. Run `ln -s AGENTS.md CLAUDE.md` once per clone — the symlink is gitignored.
