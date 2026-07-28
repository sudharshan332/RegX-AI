# Telemetry — Flow Enrichment Logging

Reference file for `triage-cdp-test-failure`. Read this after generating the
JIRA report to log triage learnings to MongoDB.

---

## Purpose

Every triage session optionally records what was learned during root cause
analysis to a shared MongoDB collection. A weekly Jenkins job aggregates
this data to:

- Track which investigation flows (from flow files in the `flows/`
  directory) are most frequently used.
- Surface new domain knowledge (grep patterns, failure modes, cross-service
  correlations) that should be added to existing flow sections.
- Identify when a fundamentally new subsystem flow is needed (rare — only
  when triage repeatedly traverses a code path not covered by any existing
  flow).

**This step is best-effort.** If MongoDB is unreachable, print a warning
and move on. Never block the triage report on telemetry.

---

## When to Log

After completing the JIRA report (Step 8 / Step 7), log **exactly one
document per triage session**. If follow-up conversation produces new
learnings, update the existing document in-place (see "Update Procedure")
— never insert a second document with the same `triage_id`.

1. **Existing flow used**: You followed an investigation flow from
   a flow file in `flows/` (see flow directory in
   `failure-patterns-reference.md`) during root cause analysis. Log it
   as `entry_type: "flow_used"`. If you learned something new that
   isn't in the flow documentation (a new grep pattern, a failure
   mode, a cross-service correlation), include it in
   `flow_enrichment`.

2. **New flow needed**: You traced a root cause through a subsystem or
   operation pipeline that is NOT covered by any existing flow in the
   `flows/` directory, and the investigation path is general enough to
   be reusable. Log it as `entry_type: "new_flow_candidate"`.

3. **No flow relevant**: If the failure was straightforward (e.g., a simple
   test bug, resource issue, or a one-off crash with no reusable
   investigation path), skip the telemetry step entirely.

**Key principle:** Log *investigation knowledge*, not fatal signatures.
The question is "what did I learn about how this subsystem works or fails
that would help future triages?" — not "what error message did I see?"

---

## MongoDB Connection

- **Database**: `skill_telemetry`
- **Collection**: `pattern_encounters`
- **Client**: `workflows.cdp.common.mongodb_client.MongoDBClient`

---

## Document Schema

```python
{
  "triage_id": "<uuid4>",
  "timestamp": <epoch_seconds>,
  "user": "<$USER>",
  "entry_type": "flow_used" | "new_flow_candidate",
  "investigation_flow": "<flow section name from flows/ directory>",
  "service": "<primary service>",
  "jira_ticket": "<ENG-XXXXXX or empty string>",
  "test_name": "<full testcase name>",
  "build_commit": "<commit_hash from build_info.yml Commit Id field>",
  "user_guided": false,
  "promotion_status": "pending",
  "notes": "<optional free-text context>",
  "flow_enrichment": None | {
    "new_grep_patterns": ["<grep pattern not yet in the flow>", ...],
    "new_failure_modes": ["<failure propagation path not yet documented>", ...],
    "new_cross_service_checks": ["<cross-service check not yet in the flow>", ...],
    "new_service_dependencies": [
      {"from": "<service>", "to": "<service>", "context": "<why>"},
      ...
    ],
    "jira_keywords": ["<useful JIRA search keyword>", ...],
    "triage_steps": [
      "<investigation step that should be added to the flow>"
    ]
  },
  "new_flow_detail": None | {
    "proposed_flow_name": "<short name for the new subsystem flow>",
    "subsystem_description": "<what the subsystem does — 1-2 sentences>",
    "operation_flow": "<internal operation pipeline description>",
    "related_services": ["<service1>", "<service2>"],
    "service_dependencies": [
      {"from": "<service>", "to": "<service>", "context": "<why>"},
      ...
    ],
    "triage_steps": [
      "<investigation step for the proposed flow>"
    ],
    "jira_keywords": ["<keyword>", ...]
  },
  "skill_update": None | {
    "ascii_diagram_patches": [
      {
        "subsystem_header": "**Management / UI plane (...):**",
        "diagram": "<ASCII block, no surrounding ``` fences>",
        "description": "<optional free-text rationale>"
      },
      ...
    ],
    "component_mappings": [
      {
        "component": "<first-column label>",
        "repo": "<repo name>",
        "local_path": "<xgear / ~/main path or empty>",
        "sourcegraph_path": "<sourcegraph path or empty>"
      },
      ...
    ],
    "generic_patterns": [
      {
        "title": "<subsection heading>",
        "body": "<markdown body: paragraphs, bullets, code blocks>"
      },
      ...
    ]
  }
}
```

### Field Descriptions

| Field | Required | Description |
|-------|----------|-------------|
| `triage_id` | Yes | UUID4, same for all inserts in one triage session |
| `timestamp` | Yes | `int(time.time())` at insert time |
| `user` | Yes | `$USER` environment variable |
| `entry_type` | Yes | `"flow_used"` or `"new_flow_candidate"` |
| `investigation_flow` | Yes | For `flow_used`: the flow section name (e.g., `"Stargate: External Storage Volume Lifecycle"`). For `new_flow_candidate`: `"none"` |
| `service` | Yes | Primary service name (e.g., `stargate`, `curator`) |
| `jira_ticket` | No | JIRA key if filed/found, else `""` |
| `test_name` | Yes | Full testcase name from the log path |
| `build_commit` | Yes | Commit hash (hex string, 40 chars) from `build_info.yml` `Commit Id` field. Must be the actual SHA-1 hash — never a branch name, version string, or release label. If the commit hash is unavailable, use `"unknown"` |
| `user_guided` | Yes | `true` if the entry was created or updated during post-triage follow-up conversation with the user. `false` if generated autonomously by the skill during standard triage. User-guided entries are promoted immediately; skill-generated entries require 3 occurrences from different test runs |
| `promotion_status` | Yes | Lifecycle state for the curation pipeline. Set to `"pending"` on insert. See "Promotion Status Lifecycle" below for valid transitions |
| `notes` | No | Free-text context, empty string if none |
| `flow_enrichment` | Conditional | `None` if no new knowledge was gained. Dict with new learnings to add to the existing flow |
| `new_flow_detail` | Conditional | `None` for `flow_used`. Required dict for `new_flow_candidate` |
| `skill_update` | No | Optional top-level dict for cross-cutting skill updates that span multiple flows (ASCII sub-diagrams, Component Mapping rows, Generic Cross-Cutting Patterns). See "skill_update Fields" below. Leave `None` if the triage did not surface anything in this category |

### flow_enrichment Fields

| Field | Description |
|-------|-------------|
| `new_grep_patterns` | Grep patterns that were useful during triage but are not yet in the flow's "Key log files and grep patterns" section |
| `new_failure_modes` | Failure propagation paths discovered during triage that are not yet in the flow's "Failure propagation" section |
| `new_cross_service_checks` | Cross-service correlations used during triage that are not yet in the flow's "Cross-service checks" section |
| `new_service_dependencies` | Service dependencies discovered during triage that are not in the Service Dependency Map. Each entry is `{"from": "<service>", "to": "<service>", "context": "<why this dependency exists>"}`. These feed into updates to the dependency map diagram in `failure-patterns-reference.md` |
| `jira_keywords` | Generic JIRA search keywords that would help find *similar* failures (not this specific one). Use error messages, function names, error codes, service names — never specific ticket numbers (e.g., `ENG-XXXXXX`) or commit hashes |
| `triage_steps` | Generic investigation steps that should be added to the flow. Must be reusable for any future occurrence of this failure class — never reference specific JIRA tickets, commit hashes, or one-off details from this particular investigation |

### new_flow_detail Fields

| Field | Description |
|-------|-------------|
| `proposed_flow_name` | Short name for the subsystem flow (e.g., `"Cerebro: Replication Pipeline"`) |
| `subsystem_description` | What the subsystem does — 1-2 sentences of domain context |
| `operation_flow` | Internal operation pipeline (the `A -> B -> C` flow) |
| `related_services` | Services involved in the subsystem |
| `service_dependencies` | Service dependency edges discovered for this subsystem. Each entry is `{"from": "<service>", "to": "<service>", "context": "<why>"}`. Used to update the Service Dependency Map |
| `triage_steps` | Generic investigation steps for the proposed flow. Same rule: must be reusable, no specific ticket numbers or commit hashes |
| `jira_keywords` | Generic keywords for JIRA search. Same rule: error messages and function names, not specific ticket numbers or commit hashes |

### skill_update Fields

Use `skill_update` for learnings that do NOT belong to a single
investigation flow. These are cross-cutting updates to the skill's
reference files (`failure-patterns-reference.md`,
`sourcegraph-reference.md`, `investigate-reference.md`) that the
curation pipeline applies automatically. Leave `skill_update: None`
when none of the three categories applies.

| Field | Target file | Description |
|-------|-------------|-------------|
| `ascii_diagram_patches` | `failure-patterns-reference.md` | List of dicts, each with `subsystem_header` (bold markdown header, e.g. `**Management / UI plane (...):**`), `diagram` (raw ASCII block without code fences — fences are added on apply), and optional `description`. Inserted as a titled sub-diagram under the Service Dependency Map, before `**How to use during triage:**`. Idempotent on `subsystem_header` |
| `component_mappings` | `sourcegraph-reference.md` | List of dicts, each with `component`, `repo`, `local_path` (optional), `sourcegraph_path` (optional). Appended as rows in the Common Repo-to-Component Mapping table. Idempotent on `component` (case-insensitive) |
| `generic_patterns` | `investigate-reference.md` | List of dicts, each with `title` and `body` (pre-formatted markdown — paragraphs, bullets, and code fences all supported). Appended as `### <title>` subsections under `## Generic Cross-Cutting Patterns`. Idempotent on `title` |

**When to use each category:**

- **`ascii_diagram_patches`** — You discovered a service edge that
  doesn't fit the main data-plane diagram (e.g. a UI / management
  plane sub-graph, or a blockstore-specific subgraph). Provide the
  full ASCII block as a standalone sub-diagram rather than trying to
  patch the main diagram in place.
- **`component_mappings`** — The deep-dive required reading source
  in a repo or local path that is not yet in the Component Mapping
  table (e.g. `infra/cluster/genesis/`, `prism_gateway/`).
- **`generic_patterns`** — The root cause exposed a cross-cutting
  heuristic that applies to many subsystems (e.g. Python greenlet
  exception-handling divergence, UI/API-vs-zeus classification
  divergence, peer-service FATAL timing correlation).

**Promotion rules:**

`skill_update` items are promoted with the same two-tier logic as
flow enrichments: any occurrence with `user_guided: true` is
promoted immediately; skill-generated items need
`SKILL_GENERATED_THRESHOLD` (currently 3) unique test runs. Items
aggregate across records by content identity (`subsystem_header`,
`component`, or `title`), so repeated independent confirmation of
the same learning counts toward the threshold.

**Idempotency:** All three apply helpers check for the item's
presence before inserting, so re-runs never duplicate content. A
record whose `skill_update` items are all already present in the
target files is still marked `promoted` with
`promotion_source: 'skill_update'`.

---

## Insert Procedure

Generate a `triage_id` once per session. Execute from the workspace root
(using the nutest virtual environment):

```bash
cd "${WORKSPACE}"   # absolute path to this repo's root
source my_nutest_virtual_env/bin/activate
python3 -c "
import time, os
from workflows.cdp.common.mongodb_client import MongoDBClient
db = MongoDBClient(collection='pattern_encounters',
                   db_name='skill_telemetry')
db.insert({
  'triage_id': '<TRIAGE_UUID>',
  'timestamp': int(time.time()),
  'user': os.environ.get('USER', 'unknown'),
  'entry_type': '<flow_used_or_new_flow_candidate>',
  'investigation_flow': '<FLOW_SECTION_NAME>',
  'service': '<SERVICE>',
  'jira_ticket': '<JIRA_KEY_OR_EMPTY>',
  'test_name': '<TEST_NAME>',
  'build_commit': '<COMMIT_HASH>',  # must be hex SHA-1, not a branch name
  'user_guided': <TRUE_OR_FALSE>,
  'promotion_status': 'pending',
  'notes': '',
  'flow_enrichment': <NONE_OR_DICT>,
  'new_flow_detail': <NONE_OR_DICT>
})
"
```

Replace `<TRIAGE_UUID>` with a UUID4 generated once at the start (e.g.,
via `python3 -c "import uuid; print(uuid.uuid4())"`). Use the same UUID
for all inserts in one triage session.

**Error handling**: Wrap the entire insert in a try/except. If it fails,
print the error and continue — telemetry must never block triage.

**`build_commit` validation**: The `build_commit` field must contain the
SHA-1 commit hash (a 40-character hex string) from the `Commit Id` field
in `build_info.yml`. It must NOT be a branch name (e.g., `master`,
`ncm-2.1-release`), a version label (e.g., `ganges-7.6`), or a GBN
number. These are separate fields (`Branch`, `Version`, `GBN`) in
`build_info.yml` and must not be confused with the commit hash.

- **Correct**: `d98e3484362b45eea773dbed5832f2dbb5d50056`
- **Incorrect**: `ncm-2.1-release`, `master`, `ganges-7.6`, `1773193895`

If `build_info.yml` is not accessible (e.g., JIRA ticket mode with no log
bundle, or logs behind a 403), set `build_commit` to `"unknown"` rather
than substituting a branch name or other metadata.

---

## Update Procedure (Post-Triage Enrichment)

When a triage session continues with user follow-up (e.g., source code
deep-dive, root cause confirmation, additional JIRA correlation) and
produces new learnings, **update the existing document in-place** rather
than inserting a second document.

**Rule: One triage session = one document.** Never create multiple
documents with the same `triage_id`. If you need to enrich a record
after the initial insert, use `update_one` with `$set`.

```bash
python3 -c "
import time
from bson import ObjectId
from workflows.cdp.common.mongodb_client import MongoDBClient
db = MongoDBClient(collection='pattern_encounters',
                   db_name='skill_telemetry')
db.collection.update_one(
    {'triage_id': '<TRIAGE_UUID>'},
    {'\$set': {
        'user_guided': True,
        'timestamp': int(time.time()),
        'last_update_time': int(time.time()),
        'notes': '<UPDATED_NOTES>',
        'flow_enrichment': <ENRICHMENT_DICT>,
        'new_flow_detail': <UPDATED_FLOW_DETAIL_OR_NONE>,
    }}
)
"
```

Fields to update when enriching:

| Field | Update behavior |
|-------|----------------|
| `user_guided` | Set to `true` (user was in the loop) |
| `timestamp` | Update to current time |
| `last_update_time` | Update to current time |
| `notes` | Replace with expanded notes covering the full investigation |
| `flow_enrichment` | Replace with the complete enrichment dict (include all learnings, not just new ones) |
| `new_flow_detail` | Replace with the enriched version if applicable |

Do NOT change `triage_id`, `entry_type`, `investigation_flow`, `service`,
`jira_ticket`, `test_name`, or `build_commit` — these identify the
session and should remain as originally set.

---

## What to Log vs. What to Skip

**Log a `flow_used` when:**
- You followed an existing investigation flow during triage.
- Optionally include `flow_enrichment` if you discovered new grep patterns,
  failure modes, or cross-service checks not yet in the flow.

**Log a `new_flow_candidate` when ALL of these are true:**
1. The triage traversed a subsystem or operation pipeline not covered by
   any existing flow in the `flows/` directory.
2. The investigation path is general (not specific to one fatal signature)
   and would be reusable for future triages of the same subsystem.
3. You can describe the subsystem's internal operation flow and what to
   check when it fails.

**Keep enrichments generic and focused on the flow itself:**

All enrichment fields (`jira_keywords`, `triage_steps`,
`new_failure_modes`, `new_cross_service_checks`, and all
`new_flow_detail` fields) must describe the *reusable investigation
pattern*, not the specifics of this one investigation. Before writing
each entry, ask: "Would this still make sense if someone hit the same
failure class on a completely different JIRA ticket, a different build,
and possibly a different vendor/provider?" If the answer is no,
generalize it.

**What to avoid in enrichment fields:**

1. **Specific JIRA tickets or commit hashes** — these are one-off
   references that won't apply to future failures.
   - Wrong: `"Search JIRA for ENG-899967 to check if fix applies"`
   - Right: `"Search JIRA for known external storage stats reporting
     bugs to check if a fix exists for the target AOS version"`

2. **Vendor-specific class or function names** when a generic interface
   exists — use the interface name so the flow applies to all providers.
   - Wrong: `"PowerStoreManager::GetContainerStats returns sentinel"`
   - Right: `"ExternalStorageInterface::GetContainerStats returns
     invalid capacity (sentinel or zero)"`
   - Wrong: `"PowerStoreManager"` in `related_services` or
     `service_dependencies`
   - Right: `"ExternalStorageInterface"`

3. **Hardcoded source code line numbers** — these drift with every code
   change and become misleading. Describe what to trace, not where.
   - Wrong: `"Read ClusterStorageFilter.java L86: usageMB + vmMB <=
     capaMB"`
   - Right: `"Trace PlacementSolver ClusterStorageFilter to understand
     the storage capacity rejection logic"`

4. **Specific sentinel values, magic numbers, or error payloads** from
   one bug — describe the *category* of anomalous output instead.
   - Wrong: `"sentinel value 72057594037927935 confirms pre-fix
     behavior"`
   - Right: `"anomalous values (zero, sentinel, or missing) indicate
     stats reporting failure"`

**Where specifics DO belong:** The `notes` field (free-text context for
this session) and the `jira_ticket` field. These are session-level
metadata, not promoted into the skill's reusable knowledge base.

**Do NOT log telemetry for:**
- Simple test bugs or resource misconfigurations.
- One-off crashes with no reusable investigation path.
- Individual fatal signatures — the goal is subsystem knowledge, not a
  catalog of error messages.

---

## How Enrichments Get Applied

A weekly Jenkins job (`curate_skill_patterns.py`) reads all telemetry
documents and uses a **two-tier promotion model** based on the
`user_guided` flag:

### Fast path — user-guided entries (`user_guided: true`)

Entries created or updated during post-triage conversation with the user
are promoted **immediately** on the next curation run (threshold of 1).
The rationale: a human was in the loop, asked clarifying questions,
validated the findings, and corrected the agent's understanding. These
carry high confidence.

### Standard path — skill-generated entries (`user_guided: false`)

Entries generated autonomously during standard triage (no post-triage
user interaction) require **3 occurrences from different test runs**
before promotion. "Different test runs" means distinct `test_name` or
`build_commit` values — 3 triages of the same test failure do not count
as 3 independent validations. This builds confidence that the auto-triage
consistently reaches the same conclusion across different failure
scenarios.

### What gets promoted

- **For `flow_used` with `flow_enrichment`**: Aggregates new grep
  patterns, failure modes, cross-service checks, service
  dependencies, triage steps, and JIRA keywords. Service
  dependencies are auto-applied to the Service Dependency Map
  bullet sections (not the ASCII diagram — use `skill_update`
  `ascii_diagram_patches` for visual edges). The other text
  enrichments are surfaced to operators on every run with status
  `awaiting_manual_apply` until someone applies them to the
  relevant flow section.
- **For `new_flow_candidate`**: Clusters candidates by
  `proposed_flow_name` similarity. When the threshold is met,
  generates a new flow section and pushes it to Gerrit for human
  review. Service dependencies from the `new_flow_detail` are
  included in the promoted flow section and also flow through the
  dependency map bullet auto-update.
- **For `skill_update`**: Applied automatically and idempotently
  by the three apply helpers in `curation_helpers.py`. Records
  whose only mature content is `skill_update` move directly to
  `promoted` with `promotion_source: 'skill_update'`. Records
  that also have mature text enrichments stay in
  `awaiting_manual_apply` (the `skill_update` half is done; the
  text half is not).
- **Post-triage enrichments**: When follow-up conversation
  produces new learnings, the original document is updated
  in-place (see "Update Procedure" above). The `user_guided` flag
  is set to `true` on the existing record, which triggers
  fast-path promotion on the next curation run.

### Curator CLI flags

| Flag | Effect |
|------|--------|
| `--report` | Read-only; aggregates telemetry and prints what is ready. Never touches MongoDB or skill files. |
| `--promote` | Runs full promotion logic: writes new `promotion_status` values to MongoDB, applies mature `skill_update` items, auto-appends service dependency bullets, creates/updates flow files. |
| `--promote --dry-run` | Same aggregation/decision logic as `--promote`, but every MongoDB update is suppressed and every file write is captured in-memory. Prints a summary at the end showing which documents would change status (and to what) plus which skill files would be created/modified (with line-count deltas). Mutually exclusive with `--push`. Use this before a real promote run when you want to preview impact. |
| `--promote --push` | After a successful promote, stages the changed files and pushes to Gerrit (`HEAD:refs/for/master`). |

---

## Promotion Status Lifecycle

Each document has a `promotion_status` field that tracks where it is in
the curation pipeline. The triage skill always sets this to `"pending"`
on insert; the curation script manages all subsequent transitions.

### Valid states

| Status | Set by | Meaning |
|--------|--------|---------|
| `pending` | Triage skill (on insert) | Not yet processed by curation |
| `promoted` | Curation script | Enrichment or new flow section written to the appropriate flow file in `flows/` and committed (or all `skill_update` items applied to reference files) |
| `skipped` | Curation script | Threshold not met (`user_guided: false` and < 3 independent occurrences) — will be re-evaluated on the next run |
| `awaiting_manual_apply` | Curation script | Mature enrichment items exist (flow_enrichment text — grep patterns, triage steps, failure modes, cross-service checks, JIRA keywords) that the curator cannot yet auto-apply. Record stays in a promotable state so the surfaced items resurface on every run until an operator manually applies them |
| `no_enrichment` | Curation script | `flow_used` with `flow_enrichment: None` — nothing to promote, record kept for usage tracking only |

### State transitions

```
insert (triage skill)
  → pending
    → promoted              (threshold met, all applicable items written to file)
    → awaiting_manual_apply (mature text enrichments surfaced but no auto-apply path)
    → skipped               (threshold not met, re-evaluate next run)
    → no_enrichment         (flow_used with no enrichment data)

skipped (on next curation run)
  → promoted              (threshold now met with additional occurrences)
  → awaiting_manual_apply (threshold met but needs manual text apply)
  → skipped               (still below threshold)

awaiting_manual_apply (re-evaluated every run until operator applies)
  → promoted              (operator applied the text and marked record)
  → awaiting_manual_apply (still awaiting manual application)

pending (updated in-place by triage skill with user_guided: true)
  → pending               (status unchanged, but now fast-path eligible)
```

### Curation script behavior

1. **Query**: `promotion_status: "pending"` or `promotion_status:
   "skipped"` — these are the only records that need processing.
2. **Evaluate threshold**: Check `user_guided` flag and count
   independent occurrences (distinct `test_name` or `build_commit`).
3. **If threshold met**: Apply enrichment to the appropriate flow
   file in `flows/`, set `promotion_status: "promoted"` and
   `promoted_at: <epoch>`.
4. **If threshold not met**: Set `promotion_status: "skipped"`. The
   record will be re-evaluated on the next run.
5. **If no enrichment**: `flow_used` with `flow_enrichment: None` — set
   `promotion_status: "no_enrichment"`.
6. **Never delete records** — they serve as an audit trail and usage
   metrics source. Use `promotion_status` to filter them out of
   processing.

### Additional fields set by curation

| Field | Set when | Description |
|-------|----------|-------------|
| `promoted_at` | `promotion_status` → `"promoted"` | Epoch timestamp of when the enrichment was applied |
