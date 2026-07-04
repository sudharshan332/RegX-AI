# Telemetry — Deployment Failure Pattern Logging

Reference file for `triage-rdm-deployment-failure`. Read this after generating
the triage report to log learnings to MongoDB.

---

## Purpose

Every triage session optionally records what was learned during root cause
analysis to a shared MongoDB collection. A periodic curation script
(`curation_scripts/curate_deployment_patterns.py` in this skill
directory) aggregates this data to:

- Track which failure patterns from `failure-patterns-reference.md` are
  most frequently encountered.
- Surface new domain knowledge (grep patterns, triage steps, failure
  modes) that should be added to existing pattern sections.
- Identify when a fundamentally new failure pattern is needed (rare —
  only when triage repeatedly encounters a failure class not covered by
  any existing pattern).

**This step is best-effort.** If MongoDB is unreachable, print a warning
and move on. Never block the triage report on telemetry.

---

## When to Log

After completing the triage report (Step 6), log **exactly one document
per triage session**. If follow-up conversation produces new learnings,
update the existing document in-place (see "Update Procedure") — never
insert a second document with the same `triage_id`.

1. **Existing pattern used**: You followed a failure pattern from
   `failure-patterns-reference.md` during root cause analysis. Log it
   as `entry_type: "flow_used"`. If you learned something new that
   isn't in the pattern documentation, include it in `flow_enrichment`.

2. **New pattern needed**: You traced a root cause through a failure
   class NOT covered by any existing pattern in
   `failure-patterns-reference.md`, and the investigation path is
   general enough to be reusable. Log it as
   `entry_type: "new_flow_candidate"`.

3. **No pattern relevant**: If the failure was a one-off environment
   issue, user configuration error, or a trivially obvious problem,
   skip the telemetry step entirely.

**Key principle:** Log *investigation knowledge*, not individual error
messages. The question is "what did I learn about how this deployment
subsystem works or fails that would help future triages?"

---

## MongoDB Connection

- **Database**: `skill_telemetry`
- **Collection**: `deployment_pattern_encounters`
- **Client**: `workflows.cdp.common.mongodb_client.MongoDBClient`

---

## Document Schema

```python
{
  "triage_id": "<uuid4>",
  "timestamp": <epoch_seconds>,
  "user": "<$USER>",
  "entry_type": "flow_used" | "new_flow_candidate",
  "investigation_flow": "<failure pattern name from failure-patterns-reference.md>",
  "service": "<primary service>",
  "scheduled_deployment_id": "<RDM scheduled deployment ID>",
  "deployment_id": "<individual deployment ID or empty string>",
  "build_commit": "<AOS commit hash from deployment spec>",
  "deployment_type": "<deployment type>",
  "failure_category": "<RDM failure_analysis.category>",
  "user_guided": false,
  "promotion_status": "pending",
  "notes": "<optional free-text context>",
  "flow_enrichment": None | {
    "new_grep_patterns": ["<grep pattern not yet in the pattern>", ...],
    "new_failure_modes": ["<failure propagation path not yet documented>", ...],
    "new_cross_service_checks": ["<cross-service check not yet documented>", ...],
    "triage_steps": [
      "<investigation step that should be added to the pattern>"
    ],
    "jira_keywords": ["<useful JIRA search keyword>", ...]
  },
  "new_flow_detail": None | {
    "proposed_flow_name": "<short name for the new failure pattern>",
    "subsystem_description": "<what the subsystem does — 1-2 sentences>",
    "log_signatures": ["<log signature for this failure class>", ...],
    "related_services": ["<service1>", "<service2>"],
    "triage_steps": [
      "<investigation step for the proposed pattern>"
    ],
    "jira_keywords": ["<keyword>", ...]
  }
}
```

### Field Descriptions

| Field | Required | Description |
|-------|----------|-------------|
| `triage_id` | Yes | UUID4, same for all operations in one triage session |
| `timestamp` | Yes | `int(time.time())` at insert time |
| `user` | Yes | `$USER` environment variable |
| `entry_type` | Yes | `"flow_used"` or `"new_flow_candidate"` |
| `investigation_flow` | Yes | For `flow_used`: the pattern name (e.g., `"Cluster Create — Node Lock Timeout"`). For `new_flow_candidate`: `"none"` |
| `service` | Yes | Primary service (e.g., `genesis`, `nested_ahv_plugin`, `rm_worker`, `foundation`, `prism_central`) |
| `scheduled_deployment_id` | Yes | The RDM scheduled deployment ID being triaged |
| `deployment_id` | No | Individual deployment ID if applicable, else `""` |
| `build_commit` | Yes | AOS commit hash from the deployment spec. Must be the actual SHA-1 hash. If unavailable, use `"unknown"` |
| `deployment_type` | Yes | Deployment type: `nested_ahv_2`, `nos_cluster`, `prism_central`, `external_storage`, or `multi_cluster` |
| `failure_category` | Yes | From RDM's `failure_analysis.category`: `PRODUCT`, `INFRA`, `PLUGIN`, `CONFIG`, or `unknown` |
| `user_guided` | Yes | `true` only when a **human user** directly intervened — directed, corrected, or extended the investigation in this specific session. `false` for fully autonomous triage. Under sub-skill orchestration, the calling skill (`triage-cdp-test-failure`) is **not** a "user" for this field; routine orchestrator-driven invocations are autonomous (`false`). See "User Communication" below for how this interacts with the promotion thresholds. |
| `promotion_status` | Yes | Always set to `"pending"` on insert. Managed by the curation script |
| `notes` | No | Free-text context, empty string if none |
| `flow_enrichment` | Conditional | `None` if no new knowledge. Dict with new learnings for the existing pattern |
| `new_flow_detail` | Conditional | `None` for `flow_used`. Required dict for `new_flow_candidate` |

### flow_enrichment Fields

| Field | Description |
|-------|-------------|
| `new_grep_patterns` | Grep/search patterns useful during triage but not yet in the pattern's investigation steps |
| `new_failure_modes` | Failure propagation paths discovered but not yet documented in the pattern |
| `new_cross_service_checks` | Cross-service or cross-log correlations not yet documented |
| `triage_steps` | Generic investigation steps that should be added. Must be reusable — never reference specific deployment IDs or one-off details |
| `jira_keywords` | Generic search keywords for finding similar failures. Error messages and function names, not specific ticket numbers |

### new_flow_detail Fields

| Field | Description |
|-------|-------------|
| `proposed_flow_name` | Short name for the new failure pattern (e.g., `"Nested Host DHCP Exhaustion"`) |
| `subsystem_description` | What the subsystem does — 1-2 sentences |
| `log_signatures` | Log patterns that identify this failure class |
| `related_services` | Services involved in this failure class |
| `triage_steps` | Generic investigation steps for the proposed pattern |
| `jira_keywords` | Keywords for JIRA search |

---

## Insert Procedure

Generate a `triage_id` once per session. Execute from the workspace root:

```bash
cd "${WORKSPACE}"   # absolute path to this repo's root
source my_nutest_virtual_env/bin/activate
python3 -c "
import time, os
from workflows.cdp.common.mongodb_client import MongoDBClient
db = MongoDBClient(collection='deployment_pattern_encounters',
                   db_name='skill_telemetry')
db.insert({
  'triage_id': '<TRIAGE_UUID>',
  'timestamp': int(time.time()),
  'user': os.environ.get('USER', 'unknown'),
  'entry_type': '<flow_used_or_new_flow_candidate>',
  'investigation_flow': '<PATTERN_NAME>',
  'service': '<SERVICE>',
  'scheduled_deployment_id': '<SD_ID>',
  'deployment_id': '<DEP_ID_OR_EMPTY>',
  'build_commit': '<COMMIT_HASH>',
  'deployment_type': '<TYPE>',
  'failure_category': '<CATEGORY>',
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
for all operations in one triage session.

**Error handling**: Wrap the entire insert in a try/except. If it fails,
print the error and continue — telemetry must never block triage.

---

## Update Procedure (Post-Triage Enrichment)

When a triage session continues with user follow-up and produces new
learnings, **update the existing document in-place** rather than
inserting a second document.

**Rule: One triage session = one document.**

```bash
python3 -c "
import time
from workflows.cdp.common.mongodb_client import MongoDBClient
db = MongoDBClient(collection='deployment_pattern_encounters',
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

Do NOT change `triage_id`, `entry_type`, `investigation_flow`,
`scheduled_deployment_id`, `deployment_id`, or `build_commit` — these
identify the session and should remain as originally set.

---

## Promotion Criteria

This skill uses **more rigorous promotion criteria** than the CDP test
failure triage skill, because deployment failures of the same nature
tend to occur in bursts (e.g., a bad build, a pool issue):

### User-guided entries (`user_guided: true`)

Promoted **immediately** on the next curation run (threshold of 1).
The rationale: a human validated the findings.

### Skill-generated entries (`user_guided: false`)

Require **5 unique instances** (distinct `scheduled_deployment_id`
values) **spanning at least 7 days** (earliest-to-latest timestamp
gap >= 604800 seconds). This ensures:

1. The pattern is not a one-off burst from a single bad build or
   pool outage.
2. The pattern recurs across different deployments over time.
3. The auto-triage consistently identifies the same failure class.

### Promotion Status Lifecycle

| Status | Set by | Meaning |
|--------|--------|---------|
| `pending` | Triage skill (on insert) | Not yet processed by curation |
| `promoted` | Curation script | Enrichment or new pattern written to `failure-patterns-reference.md` |
| `skipped` | Curation script | Threshold not met — will be re-evaluated next run |
| `no_enrichment` | Curation script | `flow_used` with `flow_enrichment: None` — kept for usage tracking |

---

## Curation Pipeline

The curation pipeline lives in `curation_scripts/` next to this
skill:

- `curation_scripts/curate_deployment_patterns.py` — main entry
  point. Reads `deployment_pattern_encounters` from MongoDB,
  aggregates flow enrichments and new-pattern candidates, applies
  the two-tier promotion thresholds described above, and appends
  promoted patterns to `failure-patterns-reference.md` for human
  review.
- `curation_scripts/curation_helpers.py` — local copy of the
  generic markdown / promotion-status helpers shared in spirit
  with the `triage-cdp-test-failure` skill. The helpers are kept
  local to this skill so the two curation pipelines can evolve
  independently.

Run it from the repo root with the nutest virtual environment
activated:

```bash
cd "${WORKSPACE}"   # absolute path to this repo's root
source my_nutest_virtual_env/bin/activate

# Read-only report
python3 .cursor/skills/triage-rdm-deployment-failure/\
curation_scripts/curate_deployment_patterns.py --report

# Promote graduated candidates and surface mature enrichments
python3 .cursor/skills/triage-rdm-deployment-failure/\
curation_scripts/curate_deployment_patterns.py --promote

# Promote and push the resulting patterns-file edits to Gerrit
python3 .cursor/skills/triage-rdm-deployment-failure/\
curation_scripts/curate_deployment_patterns.py --promote --push
```

---

## What to Log vs. What to Skip

**Log a `flow_used` when:**
- You followed an existing failure pattern during triage.
- Optionally include `flow_enrichment` if you discovered new grep
  patterns, triage steps, or failure modes not yet in the pattern.

**Log a `new_flow_candidate` when ALL of these are true:**
1. The triage encountered a failure class not covered by any
   existing pattern in `failure-patterns-reference.md`.
2. The investigation path is general (not specific to one deployment)
   and would be reusable for future triages.
3. You can describe log signatures and triage steps.

**Keep enrichments generic:** All enrichment fields must describe the
reusable investigation pattern, not specifics of this one deployment.
Before writing each entry, ask: "Would this still make sense for a
completely different deployment with the same failure class?"

**Do NOT log telemetry for:**
- One-off environment issues (network blip, transient pool issue).
- User configuration errors that are self-evident from the spec.
- Individual error messages without reusable investigation context.

---

## User Communication

How loud telemetry should be in the chat depends on the invocation
mode.

### Direct (Standalone) Invocation

When the user invoked this skill directly with a single deployment,
inform them on every telemetry insert:

- **New flow candidate**: *"This failure class (DHCP exhaustion on
  nested host VLAN) isn't covered by our existing patterns. I've
  logged it as a new pattern candidate — the curation script will
  add it to the skill after 5 independent validations."*
- **Flow enrichment**: *"During this triage I found a new grep
  pattern for genesis disk issues. I've logged it as an enrichment
  to the Node Lock Timeout pattern."*
- **Routine flow_used with no enrichment**: *"Logged telemetry for
  this triage (used the Cluster Create — Node Lock Timeout pattern,
  no new enrichments)."*

### Sub-Skill / Orchestration Mode

When this skill is running as a sub-skill (see
[sub-skill-mode-reference.md](sub-skill-mode-reference.md)), do
**not** announce telemetry inserts per `sd_id`. A JITA-Task-Mode
run with 20 deployments would otherwise produce 20 telemetry
notifications and bury the actual triage findings.

Instead:

1. Each sub-skill iteration logs silently.
2. At end-of-run (when control returns to the orchestrator), the
   **orchestrator** emits a single summary line:
   *"Telemetry: logged N flow_used and M new_flow_candidate
   entries across K deployments."*
   (The orchestrator owns this rendering — see
   `triage-cdp-test-failure/jita-task-mode-reference.md`.)

If the orchestrator forgets to emit the summary, do not retroactively
emit per-`sd_id` chatter from inside this skill. The sub-skill stays
quiet and trusts the orchestrator.

### Promotion-Threshold Interaction

Because sub-skill iterations are autonomous (`user_guided: false`),
they go through the standard 5-instances-over-7-days threshold for
`new_flow_candidate` promotion. The "user-guided → promote
immediately" path is reserved for explicit human intervention in
**this** session — not orchestration handoffs. This is intentional:
high-volume orchestrated runs should not auto-promote unvetted
patterns.
