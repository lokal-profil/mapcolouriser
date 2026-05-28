# Map Colouriser

A small Flask web app that colours regions on a hardcoded SVG world map by user-defined groups, with a live in-browser preview and SVG download. JavaScript-disabled clients get a server-rendered result page as a fallback. Targets Wikimedia Toolforge (Python 3.11).

## Features

- Live in-browser preview that updates as you edit (debounced).
- Native HTML5 colour picker with a colour-blind-safe default palette.
- Client-side SVG download via Blob — no round-trip to the server.
- JavaScript-disabled fallback: server-rendered result page with the same download.
- Multiple base maps with a selector behind the "Advanced" disclosure.
- Optional land and ocean base-colour pickers behind the "Advanced" disclosure, overriding the corresponding fills baked into each base SVG.
- Optional small-country circles toggle (visible effect on compatible base maps).
- Reset button to clear all groups and stored preferences.
- Preferences persisted across sessions — live-preview toggle in localStorage; last-used map and groups in the Flask session.

## Quick start

```bash
uv sync
uv run flask --app app run --debug
```

Open <http://127.0.0.1:5000>.

## Tests, lint, SVG validation

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run python scripts/check_svg.py
```

JS tests for the live-preview / download / legend pipeline use Vitest + jsdom. Managed via pnpm (pinned in `package.json`'s `packageManager` field; `corepack enable` lets your Node install run it transparently):

```bash
pnpm install   # one-time, dev-only — the Flask app itself has no Node dep
pnpm test
```

## Layout

- `app/` — Flask app (factory, routes, pure helpers, Jinja templates)
- `static/` — base map SVGs (see `app/maps.py` for the registry), `main.js`, `main.css`
- `scripts/check_svg.py` — CI-side SVG validation
- `tests/` — pytest suite (Python); `tests/js/` for the Vitest suite
- `package.json`, `vitest.config.js` — dev-only Node toolchain for JS tests

## Adding a new base map

1. Drop a well-formed SVG in `static/`. Country paths must carry the lowercase ISO 3166-1 alpha-2 code as a CSS class. If the SVG lacks a `viewBox` but has `width`/`height` attributes, one is derived at request time — no manual `viewBox` needed.
2. Add an entry to `MAPS` in `app/maps.py` — internal key → `MapInfo(filename=..., label=..., description=...)`. The `label` is shown in the "Advanced" base-map selector; the optional `description` becomes the option's hover tooltip.

   Two optional fields control the base-colour pickers in the Advanced panel — each a tuple of CSS class names (no leading `.`), joined into a selector at render time:

   - `land_classes` — class names targeted by the "Land fill" picker. Default: `("landxx", "circlexx")` → emits `.landxx, .circlexx { fill: …; }`. Set to `None` if the SVG has no land-equivalent class; the picker is hidden for that map.
   - `ocean_classes` — class names targeted by the "Ocean fill" picker. Default: `("oceanxx",)`. Set to `None` if the SVG has no ocean; the picker is hidden for that map.

   When the picker is visible, the chosen colour is **always** emitted as a CSS rule, overriding whatever fill the SVG ships natively. The shipped global defaults are `#dddddd` for land (the Tol "Muted" palette's "bad data" neutral) and `#ffffff` for ocean.

## Implementation notes

- User CSS is appended as a `<style id="map-colouriser-style">` element just before the closing `</svg>`; the on-disk SVG file is never modified.
- User CSS wins the cascade because it's appended after the SVG's native `<style id="style_css_sheet">` block. In particular, the Advanced "Land fill" / "Ocean fill" pickers always override the base SVG's own land / ocean fills whenever the pickers are visible.
- When only one map is registered, the "Advanced" disclosure shows just the small-country circles toggle and the base-colour pickers (the base-map selector is omitted entirely).

## Credits

- [`BlankMap-World.svg`](https://commons.wikimedia.org/wiki/File:BlankMap-World.svg) by Canuckguy, et al. — public domain.
- [`BlankMap-World-Compact.svg`](https://commons.wikimedia.org/wiki/File:BlankMap-World-Compact.svg) by Canuckguy, et al. — public domain.
- Default group colours from the [Tol "Muted" qualitative palette](https://sronpersonalpages.nl/~pault/) by Paul Tol (SRON) — colour-blind safe.

## AI assistance disclosure

This project was built in pair-programming with [Claude Code](https://www.anthropic.com/claude-code) (Anthropic, Opus 4.x) over interactive sessions.

- **Direction, decisions, and accountability — human.** Library and dependency choices, module layout, naming, what to accept or reject from review feedback, and final approval of every change and commit message.
- **Code, tests, comments, and most documentation — AI.** Drafted by the assistant; reviewed and edited by the maintainer before being written and verified afterwards.

The maintainer takes full responsibility for the code in this repository. If you find a bug, security issue, or licence concern, please file an issue or a PR — this disclosure does not alter normal expectations of correctness or licence terms.

## Licence

MIT No Attribution (MIT-0) — see [LICENSE](LICENSE).
