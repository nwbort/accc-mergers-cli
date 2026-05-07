---
name: accc-mergers
description: Query the ACCC merger register — past determinations, industry precedents, ACCC reasoning, and questionnaire questions — via the `mergers` CLI. Use when the user asks about historical Australian merger decisions, how the ACCC has treated a particular industry or competition issue, or which deals have gone to Phase 2.
---

# ACCC Mergers CLI

## What the tool does

`mergers` is a local CLI that queries a SQLite cache of the ACCC merger
register, sourced from the public `nwbort/accc-mergers` GitHub repository. It
covers every notified merger and waiver with full determination text,
questionnaire questions, ANZSIC industry classifications, and editorial
commentary. Full-text search uses SQLite FTS5 with BM25 ranking.

## When to use it

Use this tool when the user asks any of:

- Has the ACCC reviewed mergers in a particular industry or sub-market?
- What did the ACCC say about a specific competition issue (geographic
  markets, vertical integration, foreclosure, efficiencies, etc.)?
- How long does a typical Phase 1 or Phase 2 review take?
- What questions does the ACCC tend to ask in its questionnaires?
- What are the most-scrutinised industries?
- Details of a particular merger (by `MN-XXXXX` ID or party name).

## Command reference

All commands accept `--json` for machine-readable output — use this when you
need to parse results programmatically.

| Command | Purpose |
|---|---|
| `mergers sync` | Refresh the local cache from GitHub |
| `mergers sync --force` | Force a full re-download |
| `mergers search <query>` | Full-text search |
| `mergers search <pattern> --regex` | Python regex search instead of FTS |
| `mergers search <query> --snippets` | Search with inline match excerpts (recommended for first-pass research) |
| `mergers show <id>` | Full detail on one merger |
| `mergers show <id> --section reasons` | Only the ACCC's reasoning |
| `mergers timeline <id>` | Chronological timeline (notification → determination) with durations |
| `mergers party <name>` | All mergers involving a given acquirer or target |
| `mergers party <name> --role acquirer` | Restrict to acquirer (or `target`) |
| `mergers list` | Browse by filters |
| `mergers questions` | List mergers with questionnaires |
| `mergers questions <id>` | Questions for a specific merger |
| `mergers questions --search "<text>"` | Search question text |
| `mergers industries` | Activity breakdown by ANZSIC industry |
| `mergers industries --show <name>` | Mergers within an industry |
| `mergers stats` | Aggregate statistics |
| `mergers --install-completion` | Install shell completion for the current shell |

### Filters shared by `search`, `list`, and `party`

| Flag | Values |
|---|---|
| `--outcome` | `approved`, `denied`, `phase2`, `pending` |
| `--industry` | Partial name match, case-insensitive |
| `--phase` | `1` or `2` |
| `--waiver` / `--no-waiver` | Filter to waivers or notifications only |
| `--year` | Notification year (e.g. `2025`) |
| `--since` | Notified on or after this date (`YYYY-MM-DD`) |
| `--until` | Notified on or before this date (`YYYY-MM-DD`) |
| `--limit` | Integer result cap (default 10 for search, 50 for list/party) |
| `--has-related` / `--no-related` | Filter to mergers that do (or do not) have a linked related merger |

`search` additionally supports:
- `--regex`: interprets the query as a Python regular expression
  (case-insensitive, dotall) and scans the indexed merger text directly.
  Useful when FTS tokenisation can't express the pattern (e.g.
  `--regex "acqui(re|sition)s?\s+of\s+shares"`).
- `--snippets`: prints a short excerpt around each match inline. Recommended
  as the default approach for first-pass research — avoids needing to open
  each result individually.
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

## Typical query patterns

| User question | Command |
|---|---|
| Has the ACCC reviewed mergers in grocery retail before? | `mergers search "grocery retail" --snippets` |
| What did the ACCC say about geographic markets in fuel? | `mergers search "geographic fuel" --snippets` then `mergers show <id> --section reasons` |
| Show me all Phase 2 cases. | `mergers list --phase 2 --json` |
| Mergers notified in the first half of 2025? | `mergers list --since 2025-01-01 --until 2025-06-30 --json` |
| Fuel-sector waivers in 2024? | `mergers list --industry fuel --waiver --year 2024 --json` |
| How long did a specific merger take? | `mergers timeline MN-01016 --json` |
| Has a particular company been acquiring other businesses? | `mergers party "Asahi" --json` |
| Has the ACCC reviewed any deal where a given company was the target? | `mergers party "<name>" --role target --json` |
| Find references to a very specific phrase FTS can't tokenise well. | `mergers search "<regex>" --regex --snippets` |
| Find mergers where the ACCC's reasoning specifically discusses an issue. | `mergers search "<issue>" --section reasons --snippets` |
| What questions did the ACCC ask in the Ampol merger? | `mergers questions MN-01019` |
| Which mergers had questionnaires asking about geographic markets? | `mergers questions --search "geographic market" --json` |
| What industries see the most merger scrutiny? | `mergers industries --json` |
| How long does a typical Phase 1 review take? | `mergers stats --json` |
| Pull up everything on a specific merger. | `mergers show MN-01016 --json` |
| Just the reasoning on a specific merger. | `mergers show MN-01016 --section reasons` |
| Was this waiver refiled as a full notification? | `mergers show <waiver-id> --json` and check `related_merger` |
| Find all mergers that were refiled from a waiver denial. | `mergers list --has-related --waiver --outcome denied --json` |

## Workflow tips

1. Start broad with `mergers search "<keywords>" --snippets` to get a short
   list of candidate IDs with inline context — this replaces the need to open
   each result individually.
2. If the result count footer says results were truncated, re-run with
   `--limit <n>` to see the full set.
3. For each candidate of interest, call `mergers show <id> --section reasons`
   to pull only the ACCC's reasoning. If no structured reasons exist the CLI
   falls back to the full determination text automatically.
4. Use `--section reasons` on `search` to restrict matches to the ACCC's
   reasoning specifically, filtering out incidental mentions in party
   descriptions: `mergers search "<issue>" --section reasons --snippets`.
5. Combine with `mergers industries --show "<name>"` when you want every
   deal in a narrow sub-market.
6. Use `mergers questions --search "<issue>"` to discover which past matters
   raised the same question the user is asking about.
7. To follow a waiver→notification chain, check the `related_merger` field
   in `mergers show <id> --json`. Use `--has-related` to filter search or
   list results to only mergers with a linked matter.

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
