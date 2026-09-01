# accc-mergers-cli

A local command-line tool for querying the ACCC merger register. Search past
determinations, find similar cases by industry or issue, read the ACCC's
reasoning, and browse questionnaire questions — all from your terminal.

Data is pulled from the public
[`nwbort/accc-mergers`](https://github.com/nwbort/accc-mergers) repository as
a pre-built SQLite + FTS5 database, so no client-side indexing is required.

## Installation

### Recommended: uv

```bash
uv tool install git+https://github.com/nwbort/accc-mergers-cli
```

[uv](https://docs.astral.sh/uv/) installs the tool in an isolated environment
and puts the `mergers` command on your PATH. If you don't have uv yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Alternative: pipx

```bash
pipx install git+https://github.com/nwbort/accc-mergers-cli
```

### From source

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
| `mergers sync` | Download the latest pre-built database |
| `mergers sync --force` | Re-download even if the database hash matches |
| `mergers sync --source <path>` | Sync from a local directory (or URL) instead of GitHub |
| `mergers status` | Version, generation time, and age of the local cache |
| `mergers search <query>` | Full-text search of descriptions and determinations |
| `mergers show <id>` | Full detail on a single merger |
| `mergers timeline <id>` | Chronological event timeline for one merger, with durations |
| `mergers related <id>` | Mergers linked via the 'related merger' field (e.g. waiver refiled as a notification) |
| `mergers party <name>` | All mergers involving a given acquirer or target |
| `mergers list` | Browse with filters, no query required |
| `mergers browse` | Interactive TUI browser (requires the `[browse]` extra) |
| `mergers new` | Mergers added to the register in the last N days (`--days N` to override the default 7, `--by determined` to filter on determination date instead) |
| `mergers open <id>` | Open a merger in the browser (mergers.fyi by default, `--accc` for the original page) |
| `mergers questions [id] [version]` | Browse questionnaire questions (`--search <q>` to grep across all, `<version>` or `--all` for matters with more than one questionnaire round — `1` is always the latest) |
| `mergers noccs [id]` | Browse Notices of Competition Concerns issued in Phase 2 |
| `mergers industries` | Breakdown of activity by ANZSIC industry |
| `mergers stats` | Summary statistics (`--by year\|industry\|acquirer\|outcome\|phase` for grouped counts) |
| `mergers cache path` | Print the local cache directory |
| `mergers cache clear` | Delete the local cache so the next command re-syncs |

Every command supports `--json` for machine-readable output.  `search`,
`list`, `party` and `new` also support `--csv` and `--md` to print a CSV
or Markdown table — handy for pasting into spreadsheets or docs.

## Filters

`search` and `list` share the same filter flags:

| Flag | Description |
|---|---|
| `--outcome` | `approved`, `denied`, `phase2`, `pending` |
| `--industry` | Partial ANZSIC name match (case-insensitive) |
| `--phase` | `0` (waivers), `1`, or `2` |
| `--waiver` / `--no-waiver` | Waivers only / notifications only |
| `--year` | Notification year, e.g. `2025` |
| `--since` | Notified on or after this date (`YYYY-MM-DD`) |
| `--until` | Notified on or before this date (`YYYY-MM-DD`) |
| `--has-related` / `--no-related` | Only mergers that have (or do not have) a related merger |
| `--acquirer <name>` | Acquirer name contains this string (case-insensitive) |
| `--target <name>` | Target name contains this string (case-insensitive) |
| `--limit N` | Max results |

`list` additionally accepts `--sort date-desc|date-asc|name|duration`
(default `date-desc`).

`search` also accepts `--regex` to interpret the query as a Python
regular expression instead of an FTS query. Useful for patterns FTS
can't express (e.g. `--regex "acqui(re|sition)s?\s+of\s+shares"`).
By default `search` prints a short matching snippet under each result;
pass `--no-snippets` to suppress it.  `--section reasons|overlap|description|parties`
restricts the search (and any `--regex` scan) to a single content section.

`show` accepts `--section determination|reasons|overlap|parties|industries|description|questionnaire|nocc`
to render only one block of a merger record instead of the full report.

`party` accepts `--role acquirer|target` to restrict to one side of the deal.

## Additional record fields

`related_merger` is set on any result (from `search`, `list`, `party`, or
`show`) when a linked matter exists — e.g. a waiver refiled as a
notification. Use `--has-related`/`--no-related` to filter on it.

`mergers show <id> --json` additionally returns the merger's full record,
which can include two optional objects not exposed anywhere else:

- `appeal` / `under_appeal` — Australian Competition Tribunal appeal details,
  present only for matters that have been appealed. `under_appeal` is `true`
  only while the appeal is still current.
- `judicial_review` — Federal Court judicial review details (applicant,
  filed date, case number, case URL), present only for matters that have
  been judicially reviewed.

## Interactive browser

For repeated exploration, install with the optional `[browse]` extra to get
the `mergers browse` TUI:

```bash
uv tool install --with textual git+https://github.com/nwbort/accc-mergers-cli
# or
pip install 'accc-mergers-cli[browse]'
```

Then run:

```bash
mergers browse
```

The browser shows a filterable result list on the left and the full merger
detail on the right. Type into the filter input to combine free-text
search with structured filters, e.g. `outcome:approved industry:beverage
warehouse`. Recognised filter keys are `outcome`, `industry`, `acquirer`,
`target`, `phase`, `year`, `since`, `until`, `waiver`, `section`.

| Key | Action |
|---|---|
| `↑` / `↓` | Move through the list |
| `/` | Focus the filter input |
| `Esc` | Return focus to the list |
| `o` | Open the highlighted merger on mergers.fyi |
| `Shift+O` | Open the original ACCC register page |
| `?` | Toggle the help overlay |
| `q` | Quit |

## Shell completion

```bash
mergers --install-completion   # install for your current shell
mergers --show-completion      # print the completion script
```

Supports bash, zsh, fish and PowerShell via Typer.

## Cache

The first run of any command populates `~/.accc-mergers/db.sqlite`. After 7
days the CLI warns that the cache is stale — run `mergers sync` to refresh.

Sync fetches `cli-manifest.json` from the upstream repo's `cli-dist` branch
(a few hundred bytes) and only downloads the full SQLite database
(`cli.sqlite`) when its SHA-256 has changed. A no-op sync is therefore a
single HTTP request.

The manifest also carries a `schema_version`; the CLI refuses to install a
database whose schema it doesn't know how to read, and prompts you to upgrade.

To sync from a local directory (useful on servers without access to GitHub),
pass `--source` directly:

```bash
mergers sync --source /path/to/cli-dist
```

`--source` accepts a local directory path, a `file://` URI, or any
`http(s)://` URL.  It takes precedence over the `ACCC_MERGERS_BASE_URL`
environment variable, which can also be used to redirect all sync calls
globally.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## License

See [LICENSE](LICENSE).
