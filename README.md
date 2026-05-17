# mapcolouriser

A small Flask web app that colours regions on a hardcoded SVG world map by user-defined groups, then offers an inline preview and download. Targets Wikimedia Toolforge (Python 3.11).

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
uv run python scripts/check_svg_marker.py
```

## Layout

- `app/` — Flask app (factory, routes, pure helpers)
- `static/` — base map(s); see `app/maps.py` for the registry
- `scripts/check_svg_marker.py` — CI-side marker validation
- `tests/` — pytest suite

## Adding a new base map

1. Drop the SVG in `static/`. It must contain exactly one `/* INJECT_CSS_HERE */` marker inside a `<style>` block.
2. Add an entry to `MAPS` in `app/maps.py` (internal key → on-disk filename).
3. Country paths must carry the lowercase ISO 3166-1 alpha-2 code as a CSS class.
4. If the SVG lacks a `viewBox`, one is derived from its `width`/`height` at render time so the preview scales on small screens. To control the crop yourself, set `viewBox` explicitly in the source.

## Credits

- [`BlankMap-World.svg`](https://commons.wikimedia.org/wiki/File:BlankMap-World.svg) by Canuckguy, et al. — public domain.
- Default group colours from the [Tol "Muted" qualitative palette](https://sronpersonalpages.nl/~pault/) by Paul Tol (SRON) — colour-blind safe.

## AI assistance disclosure

This project was built in pair-programming with [Claude Code](https://www.anthropic.com/claude-code) (Anthropic, Opus 4.x) over a single interactive session in May 2026.

- **Direction, decisions, and accountability — human.** Library and dependency choices, module layout, naming, what to accept or reject from review feedback, and final approval of every change and commit message.
- **Code, tests, comments, and most documentation — AI.** Drafted by the assistant; reviewed and edited by the maintainer before being written and verified afterwards.

The maintainer takes full responsibility for the code in this repository. If you find a bug, security issue, or licence concern, please file an issue or a PR — this disclosure does not alter normal expectations of correctness or licence terms.

## Licence

MIT No Attribution (MIT-0) — see [LICENSE](LICENSE).
