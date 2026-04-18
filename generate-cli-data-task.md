# Task: Add CLI data bundle generation script

## Background

`accc-mergers-cli` is a companion CLI tool that downloads merger data from this
repo and indexes it locally in SQLite. Currently it makes ~200+ individual HTTP
requests on every sync (one per merger file, plus stats, industries, and
questionnaires). This task adds a script that pre-bundles all that data into two
files the CLI can consume with 1–2 requests instead.

## Files to create

### `scripts/generate-cli-data.sh`

Place the script below at that path. Make it executable (`chmod +x`).

It reads from the existing data layout at
`merger-tracker/frontend/public/data/` and writes two new files there:

- **`cli-manifest.json`** — lightweight version file (~KB), fetched first by
  the CLI to decide whether a full download is needed
- **`cli-bundle.json`** — complete dataset in a single file, only downloaded
  when `bundle_sha256` in the manifest differs from the client's cached copy

### `cli-manifest.json` shape

```json
{
  "version": 42,
  "generated_at": "2025-01-15T10:30:00Z",
  "merger_count": 318,
  "bundle_sha256": "abc123...",
  "merger_checksums": {
    "MN-01016": "def456...",
    "WA-00123": "789abc..."
  }
}
```

`merger_checksums` is a `{merger_id: sha256}` map of every individual merger
file. It's included so a future CLI version can do true incremental sync —
compare hashes against its local cache and re-fetch only changed records —
without downloading the full bundle.

### `cli-bundle.json` shape

```json
{
  "mergers": [ ...all merger records... ],
  "questionnaires": { "MN-01016": { ... }, "WA-00123": { ... } },
  "stats": { ... },
  "industries": { ... }
}
```

## How the CLI uses these files

1. Fetch `cli-manifest.json` (always, fast)
2. Compare `bundle_sha256` to locally cached hash
3. If match → cache is current, skip download
4. If mismatch → download `cli-bundle.json`, verify SHA-256, re-index into SQLite

Reduces a full sync from ~200 HTTP requests to 1 (cache hit) or 2 (cache miss).

## Script

```bash
#!/usr/bin/env bash
# scripts/generate-cli-data.sh
#
# Generates two files consumed by accc-mergers-cli:
#
#   merger-tracker/frontend/public/data/cli-manifest.json
#     Lightweight version file. The CLI fetches this first to check if its
#     cached bundle is still current, without committing to a full download.
#
#   merger-tracker/frontend/public/data/cli-bundle.json
#     Complete dataset (all mergers + questionnaires + stats + industries)
#     bundled into a single file. Only downloaded when the manifest's
#     bundle_sha256 differs from the client's cached copy.
#
# Usage:
#   ./scripts/generate-cli-data.sh          # no-op if data unchanged
#   ./scripts/generate-cli-data.sh --force  # always regenerate + bump version
#
# Dependencies: jq (>=1.6), python3, sha256sum (Linux) or shasum (macOS)
#
# Typical CI usage after data is updated:
#   ./scripts/generate-cli-data.sh
#   git add merger-tracker/frontend/public/data/cli-bundle.json \
#           merger-tracker/frontend/public/data/cli-manifest.json
#   git diff --staged --quiet || git commit -m "chore: regenerate CLI data bundle"

set -euo pipefail

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$REPO_ROOT/merger-tracker/frontend/public/data"
MERGERS_DIR="$DATA_DIR/mergers"
QUESTIONNAIRES_DIR="$DATA_DIR/questionnaires"
STATS_FILE="$DATA_DIR/stats.json"
INDUSTRIES_FILE="$DATA_DIR/industries.json"
BUNDLE_PATH="$DATA_DIR/cli-bundle.json"
MANIFEST_PATH="$DATA_DIR/cli-manifest.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
die() { echo "ERROR: $*" >&2; exit 1; }

sha256_file() {
    if command -v sha256sum &>/dev/null; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

command -v jq      &>/dev/null || die "jq is required (brew install jq / apt install jq)"
command -v python3 &>/dev/null || die "python3 is required"

# ---------------------------------------------------------------------------
# Collect source files
# ---------------------------------------------------------------------------
[[ -d "$MERGERS_DIR" ]] || die "Mergers directory not found: $MERGERS_DIR"

MERGER_FILES=()
for f in "$MERGERS_DIR"/MN-*.json "$MERGERS_DIR"/WA-*.json; do
    [[ -f "$f" ]] && MERGER_FILES+=("$f")
done
MERGER_COUNT=${#MERGER_FILES[@]}
[[ $MERGER_COUNT -gt 0 ]] || die "No merger files found in $MERGERS_DIR"
echo "Found $MERGER_COUNT merger files"

QUESTIONNAIRE_FILES=()
if [[ -d "$QUESTIONNAIRES_DIR" ]]; then
    for f in "$QUESTIONNAIRES_DIR"/*.json; do
        [[ -f "$f" ]] && QUESTIONNAIRE_FILES+=("$f")
    done
fi
echo "Found ${#QUESTIONNAIRE_FILES[@]} questionnaire files"

# ---------------------------------------------------------------------------
# Build bundle into a temp file
# ---------------------------------------------------------------------------
BUNDLE_TMP="$(mktemp)"
trap 'rm -f "$BUNDLE_TMP"' EXIT

echo "Building bundle..."

# Mergers: slurp all individual files into a JSON array
MERGERS_JSON=$(jq -s '.' "${MERGER_FILES[@]}")

# Questionnaires: {merger_id: data} — use Python to handle dynamic keys cleanly
if [[ ${#QUESTIONNAIRE_FILES[@]} -gt 0 ]]; then
    QUESTIONNAIRES_JSON=$(python3 - "${QUESTIONNAIRE_FILES[@]}" <<'PYEOF'
import json, os, sys
result = {}
for path in sys.argv[1:]:
    merger_id = os.path.splitext(os.path.basename(path))[0]
    with open(path) as f:
        result[merger_id] = json.load(f)
print(json.dumps(result, separators=(',', ':')))
PYEOF
    )
else
    QUESTIONNAIRES_JSON="{}"
fi

STATS_JSON="null"
[[ -f "$STATS_FILE" ]] && STATS_JSON=$(cat "$STATS_FILE")

INDUSTRIES_JSON="null"
[[ -f "$INDUSTRIES_FILE" ]] && INDUSTRIES_JSON=$(cat "$INDUSTRIES_FILE")

jq -n \
    --argjson mergers        "$MERGERS_JSON" \
    --argjson questionnaires "$QUESTIONNAIRES_JSON" \
    --argjson stats          "$STATS_JSON" \
    --argjson industries     "$INDUSTRIES_JSON" \
    '{
        mergers:        $mergers,
        questionnaires: $questionnaires,
        stats:          $stats,
        industries:     $industries
    }' > "$BUNDLE_TMP"

# ---------------------------------------------------------------------------
# Check whether content actually changed
# ---------------------------------------------------------------------------
BUNDLE_SHA256=$(sha256_file "$BUNDLE_TMP")

PREV_SHA256=""
PREV_VERSION=0
if [[ -f "$MANIFEST_PATH" ]]; then
    PREV_SHA256=$(jq -r '.bundle_sha256 // ""' "$MANIFEST_PATH")
    PREV_VERSION=$(jq -r '.version // 0' "$MANIFEST_PATH")
fi

if [[ "$BUNDLE_SHA256" == "$PREV_SHA256" && "$FORCE" -eq 0 ]]; then
    echo "Bundle unchanged (sha256 matches v${PREV_VERSION}). Nothing to do."
    exit 0
fi

NEW_VERSION=$((PREV_VERSION + 1))
mv "$BUNDLE_TMP" "$BUNDLE_PATH"
echo "Bundle updated: v${PREV_VERSION} -> v${NEW_VERSION}"

# ---------------------------------------------------------------------------
# Per-merger checksums — stored in manifest to support incremental sync.
#
# A future CLI version can fetch only the manifest, compare these hashes
# against its local cache, and re-download only the changed merger files
# rather than the full bundle.
# ---------------------------------------------------------------------------
echo "Computing per-merger checksums..."
MERGER_CHECKSUMS=$(python3 - "${MERGER_FILES[@]}" <<'PYEOF'
import hashlib, json, os, sys
result = {}
for path in sys.argv[1:]:
    merger_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, 'rb') as f:
        result[merger_id] = hashlib.sha256(f.read()).hexdigest()
print(json.dumps(result, separators=(',', ':')))
PYEOF
)

# ---------------------------------------------------------------------------
# Write manifest
# ---------------------------------------------------------------------------
GENERATED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

jq -n \
    --argjson version          "$NEW_VERSION" \
    --arg     generated_at     "$GENERATED_AT" \
    --argjson merger_count     "$MERGER_COUNT" \
    --arg     bundle_sha256    "$BUNDLE_SHA256" \
    --argjson merger_checksums "$MERGER_CHECKSUMS" \
    '{
        version:          $version,
        generated_at:     $generated_at,
        merger_count:     $merger_count,
        bundle_sha256:    $bundle_sha256,
        merger_checksums: $merger_checksums
    }' > "$MANIFEST_PATH"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
BUNDLE_KB=$(( $(wc -c < "$BUNDLE_PATH") / 1024 ))
echo ""
echo "CLI data generated"
echo "  Version:   $NEW_VERSION"
echo "  Generated: $GENERATED_AT"
echo "  Mergers:   $MERGER_COUNT"
echo "  Bundle:    $BUNDLE_PATH (${BUNDLE_KB} KB)"
echo "  Manifest:  $MANIFEST_PATH"
echo "  SHA256:    $BUNDLE_SHA256"
echo ""
echo "Stage for commit:"
echo "  git add '$BUNDLE_PATH' '$MANIFEST_PATH'"
```

## CI integration (optional)

If there's a GitHub Actions workflow that runs when merger data is updated, add
a step after the data update:

```yaml
- name: Regenerate CLI data bundle
  run: |
    ./scripts/generate-cli-data.sh
    git add merger-tracker/frontend/public/data/cli-bundle.json \
            merger-tracker/frontend/public/data/cli-manifest.json
    git diff --staged --quiet || git commit -m "chore: regenerate CLI data bundle"
```

## Notes

- Script is idempotent — safe to run on every commit; only writes files when
  content changes, keeping git history clean
- `--force` bumps the version even if content is identical (useful after fixing
  a bug in the generator)
- Auto-detects `sha256sum` (Linux/CI) vs `shasum` (macOS)
- Uses Python only for building the `{merger_id: data}` questionnaire object
  where `jq` doesn't handle dynamic keys across many files cleanly; everything
  else is pure bash + jq
