# mapcolouriser

A small Flask web app that colours regions on a hardcoded SVG world map by user-defined groups, with a live in-browser preview and SVG download. JavaScript-disabled clients get a server-rendered result page as a fallback. Targets Wikimedia Toolforge (Python 3.11).

## Features

- Live in-browser preview that updates as you edit (debounced).
- Native HTML5 colour picker with a colour-blind-safe default palette.
- Client-side SVG download via Blob — no round-trip to the server.
- JavaScript-disabled fallback: server-rendered result page with the same download.
- Toggle live preview on/off (accessibility / weak-device opt-out).

## Quick start

```bash
uv sync
uv run flask --app app run --debug
```

Open <http://127.0.0.1:5000>.

## Tests, lint, marker check

```bash
uv run pytest
uv run ruff check
uv run python scripts/check_svg.py
```

JS tests for the live-preview / download / legend pipeline use Vitest + jsdom.
Managed via pnpm (pinned in `package.json`'s `packageManager` field; `corepack
enable` lets your Node install run it transparently):

```bash
pnpm install   # one-time, dev-only — the Flask app itself has no Node dep
pnpm test
```

## Layout

- `app/` — Flask app (factory, routes, pure helpers)
- `static/` — base map(s); see `app/maps.py` for the registry
- `scripts/check_svg.py` — CI-side SVG validation
- `tests/` — pytest suite

## Adding a new base map

1. Drop a well-formed SVG in `static/`.
2. Add an entry to `MAPS` in `app/maps.py` — internal key → `MapInfo(filename, label)`. The label is shown in the "Advanced" base-map selector.
3. Country paths must carry the lowercase ISO 3166-1 alpha-2 code as a CSS class.
4. If the SVG lacks a `viewBox`, one is derived from its `width`/`height` at render time so the preview scales on small screens. To control the crop yourself, set `viewBox` explicitly in the source.

When two or more maps are registered, the index page renders an "Advanced" `<details>` in the page header containing a `<select name="map">`. With a single map registered, the selector is omitted from the rendered page entirely.

User CSS is appended as a `<style id="map-colouriser-style">` element just before the closing `</svg>`; the original file isn't modified at request time.

## Credits

- [`BlankMap-World.svg`](https://commons.wikimedia.org/wiki/File:BlankMap-World.svg) by Canuckguy, et al. — public domain.
- [`BlankMap-World-Compact.svg`](https://commons.wikimedia.org/wiki/File:BlankMap-World-Compact.svg) by Canuckguy, et al. — public domain.
- Default group colours from the [Tol "Muted" qualitative palette](https://sronpersonalpages.nl/~pault/) by Paul Tol (SRON) — colour-blind safe.

## AI assistance disclosure

This project was built in pair-programming with [Claude Code](https://www.anthropic.com/claude-code) (Anthropic, Opus 4.x) over a single interactive session in May 2026.

- **Direction, decisions, and accountability — human.** Library and dependency choices, module layout, naming, what to accept or reject from review feedback, and final approval of every change and commit message.
- **Code, tests, comments, and most documentation — AI.** Drafted by the assistant; reviewed and edited by the maintainer before being written and verified afterwards.

The maintainer takes full responsibility for the code in this repository. If you find a bug, security issue, or licence concern, please file an issue or a PR — this disclosure does not alter normal expectations of correctness or licence terms.

## Licence

MIT No Attribution (MIT-0) — see [LICENSE](LICENSE).
