# Suggested enhancements to the mergers CLI

These are based on friction encountered during a real research task: finding and
analysing all ACCC mergers that discuss conglomerate effects.

---

## 1. Show match snippets in search results

**Problem:** `mergers search "conglomerate effects"` returned a list of merger
IDs and metadata but no excerpt showing *where* or *how* the term appears in the
text. To see the context I had to pipe the JSON output through a custom Python
script.

**Enhancement:** Add a `--snippets` flag (or make it the default for terminal
output) that prints a short excerpt around each match, similar to `grep -C`.

```
mergers search "conglomerate effects" --snippets

  WA-45011  Signant – ActiGraph  Approved
  "...there appears to be a low risk of foreclosure or other conglomerate
   effects resulting from exclusionary conduct, bundling or tying..."
```

For `--json`, add a `snippets: [...]` array to each result object.

---

## 2. Fix FTS ranking for legal-domain phrases

**Problem:** `mergers search "conglomerate effects"` (FTS mode) returned largely
irrelevant results — the top hits bore no obvious relation to conglomerate
theory. Switching to `--regex` found the correct 10 mergers, but returning
different results for the same phrase depending on search mode is confusing and
undermines trust in FTS results.

**Enhancement:** Investigate why BM25 ranking deprioritises the phrase in this
case (likely because both tokens are common in the corpus). Options:

- Phrase boost: treat quoted strings as phrase queries in FTS5 (`"conglomerate
  effects"` → `MATCH '"conglomerate effects"'`).
- Fall back to regex automatically when FTS returns zero exact-phrase matches.
- Surface a warning when FTS and regex results diverge significantly.

---

## 3. `show` should expose all text fields in `--json`

**Problem:** `mergers show MN-85006 --json` returned a record with
`merger_description` but an empty `determination_reasons` field, even though
`mergers search --regex --json` returned the same merger with a populated
`all_determination_text` field containing the full ACCC statement of reasons.
The two commands return inconsistent schemas for the same record.

**Enhancement:** Make `mergers show --json` return every available text field,
including `all_determination_text`. If the structured `determination_reasons`
field is empty but `all_determination_text` is not, either populate the former
from the latter or at minimum include the raw field so callers aren't silently
missing data.

---

## 4. `--section reasons` should fail loudly when no reasons text exists

**Problem:** `mergers show MN-85006 --section reasons` returned just the header
panel with no content and no message explaining why. The determination reasons
*were* available in another field (`all_determination_text`) — the section
filter just didn't know to look there.

**Enhancement:** When `--section reasons` finds nothing, either:
- Fall back to `all_determination_text` and note the fallback, or
- Print an explicit message: "No structured reasons text available for this
  merger. Try `mergers show MN-85006` to see the full determination text."

Silent empty output is worse than a clear "not found" message.

---

## 5. Surface result counts and truncation warnings

**Problem:** The default `--limit` for search is 10. There is no indication in
the output whether 10 results means "these are all of them" or "there were 47
but I stopped at 10." For a completeness-sensitive research task (find *all*
mergers discussing X) this ambiguity is a real problem.

**Enhancement:** Always print a result count footer, e.g.:

```
Showing 10 of 23 results. Use --limit to see more.
```

In `--json` mode, add a top-level `total_matches` field alongside the
`results` array so callers can detect truncation without re-running the query.

---

## 6. Add a `--section` flag to `search`

**Problem:** There is no way to restrict a search to a specific part of the
determination — e.g., only search within the ACCC's stated reasons, ignoring
party descriptions. This matters when a term like "conglomerate" might appear
in the party description (Apollo's portfolio) without any actual conglomerate
effects analysis.

**Enhancement:** Extend the `--section` concept from `show` to `search`:

```
mergers search "conglomerate" --section reasons
```

This would search only within `determination_reasons` / `all_determination_text`,
filtering out incidental mentions in party descriptions or overlap summaries.
