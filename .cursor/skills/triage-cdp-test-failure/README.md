# triage-cdp-test-failure — Skill Overview

Owner: sam.gaver@nutanix.com

An AI agent skill that analyzes CDP test failure logs (from archived log
servers or live clusters), extracts root causes via service investigation
flows, and generates JIRA-ready bug reports. After each triage, the skill
logs telemetry to MongoDB so a weekly curation pipeline can continuously
improve the skill's domain knowledge.

---

## Architecture

```
                         ┌──────────────┐
                         │   SKILL.md   │  Orchestrator (~440 lines)
                         │  (entry pt)  │  Determines mode, drives workflow
                         └──────┬───────┘
                                │
           ┌────────────────────┼────────────────────┐
           │                    │                     │
           ▼                    ▼                     ▼
  ┌─────────────────┐ ┌─────────────────┐  ┌──────────────────┐
  │ archived-logs-  │ │ live-cluster-   │  │ jira-            │
  │ reference.md    │ │ reference.md    │  │ reference.md     │
  │ (Archived Logs) │ │ (Live Cluster)  │  │ (JIRA ops)       │
  └─────────────────┘ └─────────────────┘  └──────────────────┘
           │                    │
           ▼                    ▼
  ┌──────────────────────────────────────┐
  │ failure-patterns-reference.md        │  Index file (~130 lines)
  │ (dependency map, Flow Directory      │
  │  table, generic utilities,           │
  │  failure ID — NO duplicated flows)   │
  └──────────────────┬───────────────────┘
                     │ Flow Directory table
                     ▼
  ┌──────────────────────────────────────┐
  │ flows/                               │  Per-domain flow files
  │   stargate-flows.md                  │
  │   curator-flows.md                   │
  │   ahv-network-flows.md               │
  │   pc-placement-flows.md              │
  │   (new files auto-created)           │
  └──────────────────────────────────────┘
           │
           ▼
  ┌─────────────────┐ ┌──────────────────┐ ┌─────────────────┐
  │ sourcegraph-    │ │ report-template- │ │ telemetry-      │
  │ reference.md    │ │ reference.md     │ │ reference.md    │
  │ (code dive)     │ │ (JIRA report)    │ │ (MongoDB log)   │
  └─────────────────┘ └──────────────────┘ └─────────────────┘
                                                    │
  ┌─────────────────┐                               │
  │ setup-guide.md  │                               ▼
  │ (one-time MCP   │              ┌────────────────────────────┐
  │  server setup)  │              │ MongoDB                    │
  └─────────────────┘              │ skill_telemetry.            │
                                   │   pattern_encounters       │
                                   └────────────┬───────────────┘
                                                │ weekly Jenkins
                                                ▼
                                   ┌────────────────────────────┐
                                   │ curate_skill_patterns.py   │
                                   │ curation_helpers.py        │
                                   │ (aggregate, promote,       │
                                   │  push to Gerrit)           │
                                   └────────────────────────────┘
```

---

## Triage Workflow (Step by Step)

### Step 1 — Mode Detection

The user provides one of:
- **Log URL** → Archived Logs mode
- **CVM IP** → Live Cluster mode
- **JIRA ticket** (`ENG-XXXXXX`) → fetch ticket context, then route
  to Archived Logs or Live Cluster
- **JITA task URL** (`jita.eng.nutanix.com/results?task_ids=<id>`)
  → JITA Task Mode (orchestrator). The skill enumerates every test
  result in the task, classifies each one, and per result:
  - runs the Archived Logs sub-flow for in-test failures;
  - **delegates to `triage-rdm-deployment-failure`** (cross-skill
    handoff — read that skill's `SKILL.md` and follow it) for tests
    Skipped with `failure_analysis.category: DEVPROD_SERVICE:RDM`,
    deduping by `scheduled_deployment_id` so each unique RDM
    deployment is triaged exactly once even if many tests were
    skipped because of it;
  - records Passed and other-skip rows without triage.

  After the loop, JITA Task Mode produces a **per-test summary
  table** as the top-level output, with per-test JIRA-ready reports
  embedded below. Reference: `jita-task-mode-reference.md`.

Reference files are loaded lazily — only the file for the active mode
is read.

### Step 2 — Two-Tier Triage

Most triages use only the log bundle (Archived Logs). In rare cases
where live debugging adds value, the log-bundle triage completes
first, then the user is asked if the cluster is still available.

### Step 3 — Log Analysis (Archived Logs / Live Cluster)

1. Parse `errors.json` for fatals, signal errors (SIGSEGV), cores
2. Deduplicate by unique signature
3. Fetch build info and base config
4. Extract error context from CVM logs (stack traces, activity traces,
   ±50 lines)
5. **Root cause chain analysis** — trace backward through the causal
   chain using the service dependency map and investigation flows from
   `failure-patterns-reference.md` and `flows/`
6. Integrity tester / test failure analysis
7. Background job timeline (EI, snapshots, VMotion, power cycles)
8. JIRA duplicate search
9. Generate JIRA wiki markup report

### Step 4 — Sourcegraph Deep-Dive (Conditional)

Automatically triggered when:
- The failure traverses a subsystem not covered by existing flows
- The causal chain ends at an unexplained failure
- A new flow candidate is being logged

Skipped when the failure matches a known flow with a clear root cause.

### Step 5 — Telemetry Logging

After the report, the skill logs one document per triage session to
MongoDB (`skill_telemetry.pattern_encounters`):

| entry_type | When |
|---|---|
| `flow_used` | Followed an existing investigation flow. Optionally includes `flow_enrichment` with new patterns/steps discovered. |
| `new_flow_candidate` | Root cause traversed a subsystem with no existing flow. Includes proposed flow name, triage steps, dependencies. |

Key fields: `user_guided` (controls promotion speed), `triage_id`
(dedup key), `investigation_flow` (flow section name),
`promotion_status` (lifecycle tracking).

### Step 6 — Post-Triage Follow-Up

If user conversation after the report reveals new domain knowledge
(dependencies, flow forks, failure modes), the existing telemetry
document is updated in-place with `user_guided: true` for fast-track
promotion.

---

## Investigation Flows

Flows describe how service subsystems work internally and how failures
propagate across service boundaries. They are organized by **domain**
(not by individual error message) and grow by accumulating triage
knowledge.

### File Structure

| File | Contents |
|---|---|
| `failure-patterns-reference.md` | **Index** — organization principles, generic triage utilities, service dependency map (ASCII diagram + triage bullets), Flow Directory table, primary vs. cascading failure identification |
| `flows/stargate-flows.md` | External Storage Volume Lifecycle, VDisk Controller & Forest Operations |
| `flows/curator-flows.md` | MapReduce Scan Pipeline |
| `flows/ahv-network-flows.md` | AHV Host Network Troubleshooting (Live Debug) |
| `flows/pc-placement-flows.md` | PC Placement Solver: External Storage Capacity Check |

### Flow Directory

The index file contains a markdown table mapping flow names to file
paths. The curation script reads this table to determine where to
write new flows. When a promoted flow doesn't fit any existing domain
file, a new file is auto-created and the directory table is
auto-updated.

### Flow Section Template

Each flow section documents:
- **What it does** — subsystem description
- **Internal operation flow** — step-by-step code path
- **Key log files and grep patterns** — diagnostic commands
- **Failure propagation** — how failures cascade
- **Cross-service checks** — what to verify in other services
- **JIRA search keywords** — terms for duplicate search

---

## Curation Pipeline

A weekly Jenkins job promotes telemetry data into the skill's
reference files.

### Components

| File | Purpose |
|---|---|
| `curation_scripts/curate_skill_patterns.py` | Main script — aggregates enrichments, clusters candidates, drives promotion, pushes to Gerrit |
| `curation_scripts/curation_helpers.py` | Helpers — text utilities, promotion status management, Flow Directory I/O, ServiceDependencyMap class |

### Two-Tier Promotion Model

| Tier | Condition | Promotion |
|---|---|---|
| User-guided | Any `user_guided: true` entry in session | Immediate on next curation run |
| Skill-generated | `user_guided: false` | Requires 3 occurrences from different test runs |

### Promotion Lifecycle

```
  pending ──┬── promoted  (written to flow file)
            ├── skipped   (threshold not met, re-evaluated next run)
            └── no_enrichment  (flow_used with no enrichment data)
```

### What Gets Promoted

1. **New flow candidates** — clustered by name similarity, mature
   clusters generate a new flow section in the appropriate domain file
   (existing or auto-created).
2. **Flow enrichments** — new grep patterns, failure modes,
   cross-service checks, triage steps, and JIRA keywords are surfaced
   for manual application to existing flow sections.
3. **Service dependencies** — new edges are auto-appended to the
   Service Dependency Map bullet sections in the index file.

### Usage

```bash
# Report only (read-only, no changes)
python curate_skill_patterns.py --report

# Promote graduated candidates
python curate_skill_patterns.py --promote

# Promote and push to Gerrit for code review
python curate_skill_patterns.py --promote --push
```

---

## File Inventory

### Skill Reference Files (`.cursor/skills/triage-cdp-test-failure/`)

| File | Lines | Purpose |
|---|---|---|
| `SKILL.md` | ~440 | Orchestrator — mode detection, workflow steps, telemetry guidance, cross-skill handoff protocol |
| `archived-logs-reference.md` | ~420 | Log extraction, CVM analysis, error parsing |
| `live-cluster-reference.md` | — | SSH-based live cluster investigation |
| `jita-task-mode-reference.md` | ~330 | JITA Task Mode — per-test loop, RDM-skip dedup, cross-skill handoff to `triage-rdm-deployment-failure`, per-test summary table format |
| `jira-reference.md` | — | JIRA search, create, update, duplicate detection |
| `failure-patterns-reference.md` | ~130 | Index — dependency map, Flow Directory table (no duplicated flow content), generic utilities |
| `report-template-reference.md` | — | JIRA wiki markup report template |
| `sourcegraph-reference.md` | ~310 | Source code deep-dive — local xgear views + Sourcegraph MCP fallback |
| `telemetry-reference.md` | ~430 | MongoDB insert schema, enrichment guidelines |
| `setup-guide.md` | — | One-time MCP server configuration |

### Flow Files (`flows/`)

| File | Lines | Flows |
|---|---|---|
| `stargate-flows.md` | ~180 | External Storage Volume Lifecycle; VDisk Controller & Forest Operations |
| `curator-flows.md` | ~90 | MapReduce Scan Pipeline |
| `ahv-network-flows.md` | ~50 | AHV Host Network Troubleshooting |
| `pc-placement-flows.md` | ~95 | PC Placement Solver: External Storage Capacity Check |

### Curation Pipeline (`curation_scripts/`)

| File | Lines | Purpose |
|---|---|---|
| `curate_skill_patterns.py` | ~1090 | Aggregation, clustering, promotion, Gerrit push |
| `curation_helpers.py` | ~870 | Text utilities, DB status helpers, file I/O, ServiceDependencyMap |
