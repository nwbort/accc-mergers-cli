# accc-mergers-cli

A local command-line tool for querying the ACCC merger register. Search past
determinations, find similar cases by industry or issue, read the ACCC's
reasoning, and browse questionnaire questions — all from your terminal.

Data is pulled from the public
[`nwbort/accc-mergers`](https://github.com/nwbort/accc-mergers) repository and
indexed locally with SQLite FTS5.

## Installation

```bash
git clone https://github.com/nwbort/accc-mergers-cli
cd accc-mergers-cli
pip install -e .
```

Python 3.11+ is required. The only runtime dependencies are `typer`, `rich`,
and `httpx`.

## Quick start

```bash
# First run auto-syncs the local cache (~/.accc-mergers/).
mergers search "warehouse lease beverage"

# Full detail on a single merger.
mergers show MN-01016

# Browse by filter.
mergers list --outcome approved --industry beverage --year 2025

# Force-refresh the cache.
mergers sync --force
```

## Commands

| Command | Purpose |
|---|---|
| `mergers sync` | Download and index the latest data |
| `mergers search <query>` | Full-text search of descriptions and determinations |
| `mergers show <id>` | Full detail on a single merger |
| `mergers list` | Browse with filters, no query required |
| `mergers questions [id]` | Browse questionnaire questions |
| `mergers industries` | Breakdown of activity by ANZSIC industry |
| `mergers stats` | Summary statistics |

Every command supports `--json` for machine-readable output.

## Filters

`search` and `list` share the same filter flags:

| Flag | Description |
|---|---|
| `--outcome` | `approved`, `denied`, `phase2`, `pending` |
| `--industry` | Partial ANZSIC name match (case-insensitive) |
| `--phase` | `1` or `2` |
| `--waiver` / `--no-waiver` | Waivers only / notifications only |
| `--year` | Notification year, e.g. `2025` |
| `--limit N` | Max results |

## Cache

The first run of any command populates `~/.accc-mergers/db.sqlite`. After 7
days the CLI warns that the cache is stale — run `mergers sync` to refresh.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## License

See [LICENSE](LICENSE).
