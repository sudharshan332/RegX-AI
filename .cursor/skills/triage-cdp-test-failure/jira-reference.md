# JIRA Integration Reference

Reference file for `triage-cdp-test-failure`. Read this when performing JIRA
operations (search, create, update, duplicate handling, label management).

---

## JIRA Helper Module

All JIRA operations use `jira_helper.py` (located in this directory). The
helper calls the JIRA REST API directly, returns compact JSON output (stripped
of verbose JIRA metadata), and supports batched workflows that combine
multiple API calls into a single Shell invocation.

**Auth**: Reads credentials from environment variables (`JIRA_URL`,
`JIRA_PERSONAL_TOKEN`) or falls back to parsing `~/.cursor/mcp.json`
Docker args for the `atlassian` MCP server config.

**Markup format**: The JIRA REST API v2 accepts **wiki markup** natively.
Descriptions, comments, and all text fields are posted as-is in JIRA wiki
markup — **no Markdown conversion is needed**. This eliminates the conversion
step and pitfalls that existed with the MCP approach.

The helper path (relative to this file):
```
JIRA_HELPER="$(dirname "$0")/jira_helper.py"
```
Or using the workspace-relative path (substitute `${WORKSPACE}` with
the absolute path to this repo's root — see
`triage-rdm-deployment-failure/setup-guide.md` for the convention):
```
JIRA_HELPER="${WORKSPACE}/.cursor/skills/triage-cdp-test-failure/jira_helper.py"
```

---

## JIRA Availability

Before using any JIRA operations, **verify** connectivity:

```bash
python3 "$JIRA_HELPER" verify
```

If it returns `"status": "ok"`, proceed with all JIRA steps.
If it fails, treat JIRA as unavailable:
- **Skip** all JIRA search / duplicate-check steps.
- **Still output** the full JIRA-ready wiki markup for manual copy-paste.
- **Still perform** log backup to shrek if requested.
- **Offer setup instructions** (see [setup-guide.md](setup-guide.md)).

**NEVER skip JIRA steps without first running verify.**

---

## Searching JIRA for Similar Issues

Only search JIRA *after* you have a crisp failure signature and context.

### Required JQL Recency/Status Filter

All searches must include this filter fragment:
```
(created >= -60d OR (created >= -180d AND status in ("Open","In Progress","Need Info","Pending Review","Pending Merge")))
```

### Build JQL Queries from Fatal Signatures

Extract key identifiers from each unique fatal:
- Source file and line: e.g., `spdk_nvmf_client.cc:1824`
- Error message keywords: e.g., `"Failed to acquire Persistent Reservation"`
- Service name: e.g., `stargate`
- Component: e.g., `block_store`, `forest`, `grove`

### Execute Batch Search

Pass **all JQL queries in a single call** — the helper runs them all,
deduplicates results by issue key, and returns compact summaries with
per-query match counts:

```bash
python3 "$JIRA_HELPER" search \
  --jql 'project = ENG AND (created >= -60d OR (created >= -180d AND status in ("Open","In Progress","Need Info","Pending Review","Pending Merge"))) AND text ~ "spdk_nvmf_client.cc" AND text ~ "Persistent Reservation" ORDER BY created DESC' \
  --jql 'project = ENG AND (created >= -60d OR (created >= -180d AND status in ("Open","In Progress","Need Info","Pending Review","Pending Merge"))) AND text ~ "kBlockStoreError" AND text ~ "external storage" ORDER BY created DESC' \
  --jql 'project = ENG AND (created >= -60d OR (created >= -180d AND status in ("Open","In Progress","Need Info","Pending Review","Pending Merge"))) AND text ~ "Failed to acquire Persistent Reservation" ORDER BY created DESC' \
  --limit 10
```

**Output structure:**
```json
{
  "queries": [
    {"jql": "...", "total_matches": 5, "returned": 5, "keys": ["ENG-111", ...]},
    {"jql": "...", "total_matches": 12, "returned": 10, "keys": ["ENG-222", ...]}
  ],
  "issues": [
    {
      "key": "ENG-111",
      "summary": "...",
      "status": "Open",
      "issue_type": "Bug",
      "priority": "Critical - P1",
      "resolution": null,
      "assignee": "Name",
      "reporter": "Name",
      "components": ["Stargate"],
      "labels": ["backup_to_shrek"],
      "created": "2026-03-15",
      "updated": "2026-03-20",
      "environment": "http://...",
      "primary_component": "Stargate > Stargate-Extent Store",
      "test_case_name": ["cdp.external_storage..."],
      "feat_numbers": ["FEAT-12345"],
      "versions": ["master"]
    }
  ],
  "unique_count": 15
}
```

Each issue in the search results includes: key, summary, status, issue_type,
priority, resolution, assignee, reporter, components, labels, created,
updated, environment, primary_component, test_case_name, feat_numbers,
and versions.

### Analyze Matching Issues

For promising matches from the search results, fetch full details
(including description and comments):

```bash
python3 "$JIRA_HELPER" get --issue ENG-898635 --comment-limit 20
```

This returns the same fields as the search results **plus** the full
`description` text, `comments` array (with author, date, body), and
`linked_issues`.

To check for linked Gerrit changes / commits:
```bash
python3 "$JIRA_HELPER" get-dev-info --issue ENG-898635
```

Record: issue key, summary, status, fix commit SHA, Gerrit change number.

### Determine Disposition

- **Duplicate (same signature + same context)**: Update existing JIRA with
  new evidence.
- **Similar (partial match)**: Record as *related* and link in report.
- **No match**: New issue — proceed to create a fresh bug report.

---

## Creating a New JIRA Ticket

**Prerequisite:** JIRA available AND no duplicate found.

1. **Ask the user** for confirmation before creating.

2. **Propose field values** (user can override):
   - **Issue Type**: `Bug` (product defect) or `Test` (test infrastructure)
   - **Component**: Service name(s), comma-separated
   - **Affects Version**: From `build_info.yml` `Version` field
   - **Summary**: Concise failure sentence

3. **Write the report to a temp file**, then create the ticket:

```bash
# Write the wiki markup report to a temp file
cat > /tmp/jira_report.txt << 'REPORT_EOF'
h2. Bug Report: ...
... full wiki markup report ...
REPORT_EOF

# Create the ticket
python3 "$JIRA_HELPER" create \
  --project ENG \
  --summary "Stargate FATAL: allocator.cc:1930 kNoSpace in DBS LinkNamedBlockIds" \
  --type Bug \
  --description-file /tmp/jira_report.txt \
  --components "Stargate" \
  --fields '{
    "customfield_15160": {"value": "Stargate", "child": {"value": "Stargate-Other"}},
    "customfield_18060": ["cdp.external_storage...test_name"],
    "customfield_13260": {"value": "No"},
    "customfield_10011": [{"value": "Functional"}],
    "versions": [{"name": "master"}],
    "fixVersions": [{"name": "Triage"}],
    "environment": "http://10.41.24.49/logs/...",
    "labels": ["backup_to_shrek"]
  }'
```

### JIRA Ticket Creation Field Reference

**Standard fields:**

| Parameter | Value | Source |
|-----------|-------|--------|
| `--project` | `ENG` | Fixed |
| `--summary` | Brief failure sentence | Triage output |
| `--type` | `Bug` or `Test` | Triage classification |
| `--description-file` | Path to wiki markup report | Report output |
| `--components` | Service name(s), comma-separated | e.g., `Stargate` |

**Custom fields (via `--fields` JSON):**

| Field ID | Field Name | Type | Value |
|----------|-----------|------|-------|
| `customfield_15160` | Primary Component | Cascading select | `{"value": "Stargate"}` |
| `customfield_18060` | Test Case Name | Labels (array) | `["cdp.external_storage...test_name"]` |
| `customfield_13260` | Regression? | Radio button | `{"value": "No"}` |
| `customfield_10011` | Impact | Multi-select | `[{"value": "Functional"}]` |
| `versions` | Affects Version/s | Version array | `[{"name": "master"}]` |
| `fixVersions` | Fix Version/s | Version array | `[{"name": "Triage"}]` (always default to "Triage") |
| `environment` | Environment | Text | Log bundle URL or CVM IPs |
| `labels` | Labels | String array | `["backup_to_shrek"]` |

**Primary Component child selection (`customfield_15160`):**

Cascading select with parent (service name) and optional child. To find a
context-specific child:
```bash
python3 "$JIRA_HELPER" field-options \
  --field-id customfield_15160 \
  --project ENG \
  --issue-type Bug \
  --contains "keyword"
```

If a matching child exists:
`{"value": "Stargate", "child": {"value": "MatchingChild"}}`

If no child matches: `{"value": "Stargate"}`

Common parent values: `Stargate`, `Curator`, `Cassandra`, `External Storage`,
`Cerebro`, `Hades`

**Issue Type guidance:**
- **Bug**: Product code defect (service fatal, SIGSEGV, data corruption)
- **Test**: Test infrastructure issue (framework bug, resource misconfig, flaky assertion)

---

## JIRA Label Management

Use the `add-labels` command which **automatically preserves existing labels**:
```bash
python3 "$JIRA_HELPER" add-labels \
  --issue ENG-12345 \
  --labels backup_to_shrek \
  --remove backed_up_to_shrek
```

The command fetches current labels, applies additions/removals, and updates
atomically. No risk of accidentally overwriting existing labels.

---

## Updating an Existing JIRA (Duplicate/Repro) with New Evidence

Use the `update-existing` command — it atomically fetches current state,
appends to environment (never overwrites), merges test case names, preserves
labels, and posts the triage report as a comment:

```bash
# Write the report to a temp file first
cat > /tmp/jira_report.txt << 'REPORT_EOF'
... wiki markup report ...
REPORT_EOF

python3 "$JIRA_HELPER" update-existing \
  --issue ENG-12345 \
  --report-file /tmp/jira_report.txt \
  --append-environment "http://10.41.24.49/logs/..." \
  --add-labels backup_to_shrek \
  --remove-labels backed_up_to_shrek \
  --add-test-case-name "cdp.external_storage...test_name"
```

**Output** includes `previous_environment` and `previous_labels` so the agent
can report to the user what changed. Always show the user the before/after
state.

**Always pass `--add-test-case-name`** with the full testcase name when
updating an existing ticket. The command merges it with existing values
(deduplicates, sorts) so there is no risk of overwriting.

Note: A periodic automation job looks for `backup_to_shrek`, backs up logs,
then swaps it for `backed_up_to_shrek`. When the backup completes, the
automation posts a comment containing the shrek path **and** the archived
CVM logs path (if the test used log archival). The comment format is:
```
AUTOMATION: Completed backup of log idx 0 to http://shrek-v2.../JITALOGS/<ENG-ID>/0

If logs are missing, make sure to check the archive!
  To access archive, 'nssh shrek-v2' and go to:   /mnt/filesv3/corruptions_<ENG-ID>_<dir_name>
```
The `<dir_name>` suffix (e.g., `310326-200941_41AA90`) matches the
archive directory name extractable from `nutest_test.log`. When triaging
a ticket that already has `backed_up_to_shrek`, parse this comment to
find the archived logs path on `/mnt/filesv3/` locally.

---

## Handling Duplicate Tickets (Full Workflow)

Use the `merge-duplicate` command — it executes the entire duplicate workflow
in a single call:

```bash
# Write the report to a temp file first
cat > /tmp/jira_report.txt << 'REPORT_EOF'
... wiki markup triage report ...
REPORT_EOF

python3 "$JIRA_HELPER" merge-duplicate \
  --dup ENG-12345 \
  --orig ENG-67890 \
  --report-file /tmp/jira_report.txt \
  --add-labels backup_to_shrek \
  --remove-labels backed_up_to_shrek
```

**What it does (all in one call):**
1. Fetches both tickets (labels, environment, test_case_name, feat_numbers,
   reporter)
2. Creates Duplicate issue link (`ENG-67890` ← `ENG-12345`)
3. Comments on `ENG-12345` tagging the reporter, noting it's a duplicate
4. Posts the triage report as a comment on `ENG-67890`
5. Merges fields into `ENG-67890`: union labels, merge FEAT numbers,
   merge test case names, append environment
6. Returns a summary of all actions taken

**Important:** The command does **NOT** resolve `ENG-12345` — inform the user
to resolve it manually in the JIRA UI (API limitation: the "Resolve as
Duplicate" transition requires a custom screen field).

**Output** includes an `actions` list showing each step completed, and `note`
reminding about manual resolution.

---

## Individual Operations

For ad-hoc JIRA operations outside the standard workflows:

### Add Comment
```bash
python3 "$JIRA_HELPER" comment \
  --issue ENG-12345 \
  --body-file /tmp/comment.txt
```
Or inline:
```bash
python3 "$JIRA_HELPER" comment \
  --issue ENG-12345 \
  --body "Comment text in wiki markup"
```

### Update Fields
```bash
python3 "$JIRA_HELPER" update \
  --issue ENG-12345 \
  --fields '{"environment": "new value", "labels": ["label1", "label2"]}'
```

### Create Issue Link
```bash
python3 "$JIRA_HELPER" link \
  --type "Relates to" \
  --inward ENG-111 \
  --outward ENG-222
```

---

## Backing Up Local/Archived Test Logs

### Log index / subdirectory naming (`0` vs `manual_*`)

- **JITA / in-job automation** uses numeric indices: comments like
  `AUTOMATION: Completed backup of log idx 0` point under
  `/jita/www/html/JITALOGS/<ENG-XXXXXX>/0/` (and `1/`, … for additional
  indices). Treat **`0`, `1`, …** as reserved for that pipeline.
- **Local-only or manual repro** (no JITA log URL to put in Environment,
  nutest bundle on a workstation): **do not** default to `/0/` if the
  ticket may already use `0` for automation or future JITA reruns.
  Prefer a dedicated subdirectory, for example:
  - `/jita/www/html/JITALOGS/<ENG-XXXXXX>/manual_0/` for the first manual
    drop, or
  - `/jita/www/html/JITALOGS/<ENG-XXXXXX>/manual_<YYYYMMDD>_<brief>/`
    (e.g. `manual_20260423_mp_pstore_vgclone_ei`) when multiple manual
    backups should stay ordered and self-describing.
- **Live-cluster backup** (per-CVM `scp` from CVMs) uses
  `.../JITALOGS/<JIRA_KEY>/<CVM_IP>/{logs,cores,binary_logs}/` — see
  [live-cluster-reference.md](live-cluster-reference.md) § 8; that layout
  does not compete with numeric JITA indices.

Post the **exact** subdirectory you used in the JIRA comment so triagers
can `nssh shrek-v2` and `cd` to it without guessing.

### scp example (local bundle → shrek)

```bash
# Example: manual local repro — pick a non-reserved directory name
MANUAL_SUBDIR="manual_0"   # or manual_<date>_<run_hint>
scp -rp -o StrictHostKeyChecking=no \
  /path/to/logs/<timestamp>/* \
  nutanix@shrek-v2.eng.nutanix.com:/jita/www/html/JITALOGS/<JIRA_ID>/${MANUAL_SUBDIR}/
```

**JIRA Comment Format** (adjust path to match `MANUAL_SUBDIR`):
```
Test logs have been backed up to nutanix@shrek-v2.eng.nutanix.com.

Absolute path: /jita/www/html/JITALOGS/<JIRA_ID>/manual_0/
Web URL: http://shrek-v2.eng.nutanix.com/JITALOGS/<JIRA_ID>/manual_0/
```

If you intentionally mirror the JITA single-index layout (e.g. only
ever manual, no automation for this ticket), `.../<JIRA_ID>/0/` is still
valid — but prefer `manual_*` when the ticket might receive automated
`0/` backups later.

After backing up, update labels:
```bash
python3 "$JIRA_HELPER" add-labels \
  --issue ENG-12345 \
  --labels backed_up_to_shrek
```

---

## Fetching JIRA Ticket Context (when user provides ENG-XXXXXX)

When the user provides a JIRA ticket key instead of a log URL or CVM IP:

1. **Fetch ticket details**:
```bash
python3 "$JIRA_HELPER" get --issue ENG-XXXXXX --comment-limit 20
```

2. **Extract triage inputs** from the response: CVM IPs (from environment
   or description), log URLs, build info, error signatures.

3. **Proceed with the appropriate mode**: Archived Logs or Live Cluster.

**Note**: Image attachment fetching is not supported by the helper module.
If image analysis is needed (screenshots in ticket), use the JIRA MCP
`jira_get_issue_images` tool as a fallback:
```
CallMcpTool: user-atlassian / jira_get_issue_images
  issue_key: "ENG-XXXXXX"
```
