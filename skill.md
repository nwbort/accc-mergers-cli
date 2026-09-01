---
name: accc-mergers
description: Query the ACCC merger register — past determinations, industry precedents, ACCC reasoning, and questionnaire questions — via the `mergers` CLI. Use when the user asks about historical Australian merger decisions, how the ACCC has treated a particular industry or competition issue, or which deals have gone to Phase 2.
---

# ACCC Mergers CLI

## What the tool does

`mergers` is a local CLI that queries a pre-built SQLite database of the
ACCC merger register, sourced from the public `nwbort/accc-mergers` GitHub
repository (the `cli-dist` branch). It covers every notified merger and
waiver with full determination text, questionnaire questions, ANZSIC
industry classifications, and editorial commentary. Full-text search uses
SQLite FTS5 with BM25 ranking.

## When to use it

Use this tool when the user asks any of:

- Has the ACCC reviewed mergers in a particular industry or sub-market?
- What did the ACCC say about a specific competition issue (geographic
  markets, vertical integration, foreclosure, efficiencies, etc.)?
- How long does a typical Phase 1 or Phase 2 review take?
- What questions does the ACCC tend to ask in its questionnaires?
- What are the most-scrutinised industries?
- Details of a particular merger (by `MN-XXXXX` ID or party name).

## Installation

Before running the first `mergers` command in a session, check whether the CLI is available:

```bash
mergers --version
```

If the command is not found, install it with uv:

```bash
uv tool install git+https://github.com/nwbort/accc-mergers-cli
```

After installing, run `mergers sync` to populate the local cache before querying.

If `mergers sync` fails because you can't access `raw.githubusercontent.com`,
you can try cloning the `nwbort/accc-mergers` repo (checking out the
`cli-dist` branch, which holds `cli-manifest.json` and `cli.sqlite`) and
pointing `mergers sync --source` at that directory.

## Command reference

All commands accept `--json` for machine-readable output — use this when you
need to parse results programmatically.  `search`, `list`, `party`, and
`new` additionally accept `--csv` and `--md` to emit a CSV or Markdown
table (handy when the user wants something they can paste into a sheet
or document).

| Command | Purpose |
|---|---|
| `mergers sync` | Refresh the local database from GitHub |
| `mergers sync --force` | Force a full re-download |
| `mergers sync --source <path>` | Sync from a local directory or URL instead of GitHub |
| `mergers status` | Show the local cache's data version, generation time, and age |
| `mergers search <query>` | Full-text search (prints snippets by default) |
| `mergers search <pattern> --regex` | Python regex search instead of FTS |
| `mergers search <query> --no-snippets` | Suppress inline match excerpts |
| `mergers show <id>` | Full detail on one merger |
| `mergers show <id> --section reasons` | Only the ACCC's reasoning |
| `mergers timeline <id>` | Chronological timeline (notification → determination) with durations |
| `mergers related <id>` | Mergers linked via the `related merger` field |
| `mergers party <name>` | All mergers involving a given acquirer or target |
| `mergers party <name> --role acquirer` | Restrict to acquirer (or `target`) |
| `mergers list` | Browse by filters |
| `mergers list --sort duration` | Sort by review duration (also `date-asc`, `date-desc`, `name`) |
| `mergers new` | Mergers added to the register in the last N days (default 7) |
| `mergers new --days <n>` | Look back a custom number of days instead of the default 7 |
| `mergers new --by determined` | Filter on determination date instead of notification |
| `mergers open <id>` | Open the merger in a browser at mergers.fyi |
| `mergers open <id> --accc` | Open the original ACCC register page |
| `mergers open <id> --print` | Print the URL instead of launching a browser |
| `mergers questions` | List mergers with questionnaires |
| `mergers questions <id>` | Questions for a specific merger (latest questionnaire version) |
| `mergers questions <id> <version>` | A specific questionnaire version (`1` = latest) when a matter had more than one round |
| `mergers questions <id> --all` | Show every questionnaire version for a matter |
| `mergers questions --search "<text>"` | Search question text across all mergers |
| `mergers noccs` | List Notices of Competition Concerns (Phase 2) |
| `mergers noccs <id>` | NOCC for a specific merger |
| `mergers noccs --search "<text>"` | Search NOCC paragraph text |
| `mergers industries` | Activity breakdown by ANZSIC industry |
| `mergers industries --show <name>` | Mergers within an industry |
| `mergers stats` | Aggregate statistics |
| `mergers stats --by year` | Grouped counts (also `industry`, `acquirer`, `outcome`, `phase`) |
| `mergers browse` | Launch an interactive TUI browser (requires the CLI's optional `[browse]` extra) |
| `mergers cache path` | Print the local cache directory |
| `mergers cache clear` | Delete the local cache so the next command re-syncs |
| `mergers --install-completion` | Install shell completion for the current shell |

### Filters shared by `search`, `list`, and `party`

| Flag | Values |
|---|---|
| `--outcome` | `approved`, `denied`, `phase2`, `pending` |
| `--industry` | Partial name match, case-insensitive |
| `--phase` | `0` (waivers), `1`, or `2` |
| `--waiver` / `--no-waiver` | Filter to waivers or notifications only |
| `--year` | Notification year (e.g. `2025`) |
| `--since` | Notified on or after this date (`YYYY-MM-DD`) |
| `--until` | Notified on or before this date (`YYYY-MM-DD`) |
| `--limit` | Integer result cap (default 10 for search, 50 for list/party) |
| `--has-related` / `--no-related` | Filter to mergers that do (or do not) have a linked related merger |
| `--acquirer <name>` | Acquirer name contains this string (case-insensitive) |
| `--target <name>` | Target name contains this string (case-insensitive) |

`list` additionally accepts `--sort date-desc|date-asc|name|duration`
(default `date-desc`).

`search` additionally supports:
- `--regex`: interprets the query as a Python regular expression
  (case-insensitive, dotall) and scans the indexed merger text directly.
  Useful when FTS tokenisation can't express the pattern (e.g.
  `--regex "acqui(re|sition)s?\s+of\s+shares"`).
- `--snippets` / `--no-snippets`: inline match excerpts are printed by
  default. Pass `--no-snippets` for a compact table.
- `--section`: restricts the search to a specific content section —
  `all` (default), `reasons`, `overlap`, `description`, `parties`. Useful
  when you want to find mergers where a term appears in the ACCC's reasoning
  specifically, filtering out incidental mentions in party descriptions.

### `show` sections

`--section` accepts one of: `all` (default), `determination`, `reasons`,
`overlap`, `parties`, `description`, `industries`, `questionnaire`, `nocc`.
Narrowing the section is the fastest way to pull up the ACCC's reasoning on
a given case. If no structured reasons text exists, the CLI falls back to the
full determination text and notes the fallback explicitly.

## Output format

- Default output is a human-readable terminal table / panel layout using
  `rich`.
- `--json` emits structured JSON — use this whenever you need to read the
  results rather than display them. Search results include a `total_matches`
  field alongside the `results` array so you can detect when results have
  been truncated by `--limit`.
- Colour is automatically stripped when stdout is piped.

### `related_merger` field

`mergers show <id> --json` includes a `related_merger` object when a linked
matter exists (e.g. a waiver that was refiled as a notification, or vice
versa):

```json
"related_merger": {
  "merger_id": "WA-65003",
  "relationship": "refiled_from",
  "merger_name": "Henkel – ATP adhesive systems group"
}
```

Relationship values: `refiled_from` (this notification was refiled from that
waiver), `refiled_as` (that waiver was refiled as this notification). Use
`--has-related` in `search` or `list` to surface only mergers that have a
linked matter.

### Tribunal appeal and judicial review fields

`mergers show <id> --json` can also carry two optional objects, present
only for matters that have one (unlike `related_merger`, these are not
surfaced as columns on `search`/`list`/`party` results — only `show`
returns the full record):

- `appeal` — Australian Competition Tribunal appeal details (tribunal
  number, tribunal URL, appeal type, appellant, lifecycle status, outcome,
  filed date, documents). `under_appeal` is `true` only while the appeal is
  still current; a concluded or withdrawn appeal keeps the `appeal` record
  but `under_appeal` is `false`.
- `judicial_review` — a Federal Court judicial review record (applicant,
  filed date, case number, case URL), where one has been filed.

There is no dedicated filter for these yet — check the field directly in
`--json` output, or use `mergers search "<term>" --regex` against the raw
text if the user is trying to find appealed or judicially-reviewed matters.

## Typical query patterns

| User question | Command |
|---|---|
| Has the ACCC reviewed mergers in grocery retail before? | `mergers search "grocery retail"` |
| What did the ACCC say about geographic markets in fuel? | `mergers search "geographic fuel"` then `mergers show <id> --section reasons` |
| Show me all Phase 2 cases. | `mergers list --phase 2 --json` |
| Mergers notified in the first half of 2025? | `mergers list --since 2025-01-01 --until 2025-06-30 --json` |
| Fuel-sector waivers in 2024? | `mergers list --industry fuel --waiver --year 2024 --json` |
| What's been added to the register in the last week? | `mergers new --json` |
| What's been determined in the last month? | `mergers new --by determined --days 30 --json` |
| Longest-running reviews on the register. | `mergers list --sort duration --limit 20` |
| How long did a specific merger take? | `mergers timeline MN-01016 --json` |
| Has a particular company been acquiring other businesses? | `mergers list --acquirer "Asahi" --json` or `mergers party "Asahi" --json` |
| Mergers where a given company was the target. | `mergers list --target "<name>" --json` or `mergers party "<name>" --role target --json` |
| Find references to a very specific phrase FTS can't tokenise well. | `mergers search "<regex>" --regex` |
| Find mergers where the ACCC's reasoning specifically discusses an issue. | `mergers search "<issue>" --section reasons` |
| What questions did the ACCC ask in the Ampol merger? | `mergers questions MN-01019` |
| Which mergers had questionnaires asking about geographic markets? | `mergers questions --search "geographic market" --json` |
| Which NOCCs raise efficiency concerns? | `mergers noccs --search "efficiencies" --json` |
| What industries see the most merger scrutiny? | `mergers industries --json` |
| How long does a typical Phase 1 review take? | `mergers stats --json` |
| Notifications and approvals by year. | `mergers stats --by year --json` |
| Which acquirers appear most often? | `mergers stats --by acquirer --json` |
| Pull up everything on a specific merger. | `mergers show MN-01016 --json` |
| Just the reasoning on a specific merger. | `mergers show MN-01016 --section reasons` |
| Give the user a link to share. | `mergers open MN-01016 --print` (or `--accc --print` for the ACCC page) |
| Was this waiver refiled as a full notification? | `mergers show <waiver-id> --json` and check `related_merger` |
| Find all mergers that were refiled from a waiver denial. | `mergers list --has-related --waiver --outcome denied --json` |
| Was this merger appealed to the Tribunal, or is it still under appeal? | `mergers show <id> --json` and check `appeal` / `under_appeal` |
| Has this merger been challenged by judicial review? | `mergers show <id> --json` and check `judicial_review` |
| Did the ACCC waive this notification? | `mergers show <id> --json` and check `phase` for `0` (waivers) |
| Export results to paste into a spreadsheet. | Add `--csv` to `search`, `list`, `party`, or `new` |
| Export results as a Markdown table for a doc. | Add `--md` to the same commands |

## Workflow tips

1. If `mergers sync` fails because you can't access `raw.githubusercontent.com`,
   try cloning the `nwbort/accc-mergers` repo, checking out the `cli-dist`
   branch, and using that directory as the `--source` for `mergers sync`.
2. Start broad with `mergers search "<keywords>"` — snippets are printed by
   default, so a single call gives you candidate IDs with inline context.
   Pass `--no-snippets` only when you specifically want a compact table.
3. If the result count footer says results were truncated, re-run with
   `--limit <n>` to see the full set.
4. For each candidate of interest, call `mergers show <id> --section reasons`
   to pull only the ACCC's reasoning. If no structured reasons exist the CLI
   falls back to the full determination text automatically.
5. Use `--section reasons` on `search` to restrict matches to the ACCC's
   reasoning specifically, filtering out incidental mentions in party
   descriptions: `mergers search "<issue>" --section reasons`.
6. Combine with `mergers industries --show "<name>"` when you want every
   deal in a narrow sub-market.
7. Use `mergers questions --search "<issue>"` to discover which past matters
   raised the same question the user is asking about.
8. To follow a waiver→notification chain, check the `related_merger` field
   in `mergers show <id> --json`. Use `--has-related` to filter search or
   list results to only mergers with a linked matter.
9. When the user wants a link to share or open in their browser, prefer
   `mergers open <id> --print` (mergers.fyi page) — add `--accc` for the
   original ACCC register URL.
10. For "what's happened recently?" questions, `mergers new` is faster
    than constructing date filters by hand. Pair with `--by determined`
    when the user cares about decisions rather than new filings.
11. For spreadsheet- or doc-ready output, add `--csv` or `--md` to
    `search`, `list`, `party`, or `new` instead of munging `--json`.
12. `mergers stats --by year|industry|acquirer|outcome|phase` answers
    "how is activity distributed across X?" without needing to aggregate
    `--json` output yourself.

## Limitations

- Search is keyword-based (FTS5 / BM25). There is no semantic similarity —
  synonyms are not automatically expanded. Try multiple phrasings if the
  first search returns nothing.
- In-progress Phase 2 matters do not yet have full reasoning text published.
  Expect `determination_reasons` to be empty for those cases.
- The data source is updated periodically. Run `mergers sync` if the cache
  appears stale; the CLI warns when the local copy is more than 7 days old.
- Only public ACCC register data is covered — no confidential submissions,
  no redacted material.
