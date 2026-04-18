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
| `mergers show <id>` | Full detail on one merger |
| `mergers show <id> --section reasons` | Only the ACCC's reasoning |
| `mergers list` | Browse by filters |
| `mergers questions` | List mergers with questionnaires |
| `mergers questions <id>` | Questions for a specific merger |
| `mergers questions --search "<text>"` | Search question text |
| `mergers industries` | Activity breakdown by ANZSIC industry |
| `mergers industries --show <name>` | Mergers within an industry |
| `mergers stats` | Aggregate statistics |

### Filters shared by `search` and `list`

| Flag | Values |
|---|---|
| `--outcome` | `approved`, `denied`, `phase2`, `pending` |
| `--industry` | Partial name match, case-insensitive |
| `--phase` | `1` or `2` |
| `--waiver` / `--no-waiver` | Filter to waivers or notifications only |
| `--year` | Notification year (e.g. `2025`) |
| `--limit` | Integer result cap (default 10 for search, 50 for list) |

### `show` sections

`--section` accepts one of: `all` (default), `reasons`, `overlap`, `parties`,
`determination`. Narrowing the section is the fastest way to pull up the
ACCC's reasoning on a given case.

## Output format

- Default output is a human-readable terminal table / panel layout using
  `rich`.
- `--json` emits structured JSON — use this whenever you need to read the
  results rather than display them.
- Colour is automatically stripped when stdout is piped.

## Typical query patterns

| User question | Command |
|---|---|
| Has the ACCC reviewed mergers in grocery retail before? | `mergers search "grocery retail" --json` |
| What did the ACCC say about geographic markets in fuel? | `mergers search "geographic fuel" --json` then `mergers show <id> --section reasons` |
| Show me all Phase 2 cases. | `mergers list --phase 2 --json` |
| Fuel-sector waivers in 2024? | `mergers list --industry fuel --waiver --year 2024 --json` |
| What questions did the ACCC ask in the Ampol merger? | `mergers questions MN-01019` |
| Which mergers had questionnaires asking about geographic markets? | `mergers questions --search "geographic market" --json` |
| What industries see the most merger scrutiny? | `mergers industries --json` |
| How long does a typical Phase 1 review take? | `mergers stats --json` |
| Pull up everything on a specific merger. | `mergers show MN-01016 --json` |
| Just the reasoning on a specific merger. | `mergers show MN-01016 --section reasons` |

## Workflow tips

1. Start broad with `mergers search "<keywords>" --json` to get a short list
   of candidate IDs.
2. For each candidate of interest, call `mergers show <id> --section reasons
   --json` to pull only the ACCC's reasoning.
3. Combine with `mergers industries --show "<name>"` when you want every
   deal in a narrow sub-market.
4. Use `mergers questions --search "<issue>"` to discover which past matters
   raised the same question the user is asking about.

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
