# Contributing

Bug reports and ideas go into [issues](https://github.com/MichaelPrutkow/anki-mcp/issues). For a bug,
the output of "check my Anki setup" helps most.

## Development

```bash
uv sync
uv run pytest                                       # against a fake AnkiConnect, no Anki needed
ANKI_LIVE=1 uv run pytest tests/test_live_anki.py   # read-only smoke test against your real Anki
uvx ruff check src tests && uvx ruff format --check src tests
claude --plugin-dir .                               # try the plugin in Claude Code
claude plugin eval .                                # with vs. without the plugin, mocked tools
```

The evals in `evals/` run against mocked tools in `evals/mocks/anki`. `_tools.json` there is the
server's tool list; regenerate it when a tool's name, description or parameters change.

## Dependencies

After changing dependencies, regenerate `requirements.txt`. The launcher installs from it when uv
is missing and only Anki's own Python is there:

```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt --quiet > requirements.txt
```

`tests/test_packaging.py` fails when it is out of date.

## Releases

1. Raise the version in `.claude-plugin/plugin.json` and `pyproject.toml` (a test checks that they
   agree), then run `uv lock`.
2. Add the version to `CHANGELOG.md`.
3. Commit, tag it as `anki--v<version>` and push the tag.
