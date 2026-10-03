# PoartaContabila — session loader

This repo is the Poarta Primară pack (source of truth) plus the `poarta_contabila` package.

1. Read `INDEX.md`, `00_LAW.md` (incl. §8 amendments) and `AGENTS.md` before any code.
2. Take the next WP from `BUILD.md`; one WP per commit; mark it `done` in the same commit, and
   move its details to `docs/BUILD_DONE.md` (BUILD.md keeps open work only).
3. No client data in this repo: invented CUIs must pass the check digit (`poarta_contabila.types.cui_is_valid`).

```bash
uv sync                                   # install
uv run pytest -q                          # tests (DB tests need POARTA_TEST_DSN; cloud sessions get it from .claude/hooks/session-start.sh)
uv run ruff check . && uv run ruff format --check .
```
