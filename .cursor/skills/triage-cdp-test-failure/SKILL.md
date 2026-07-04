# Owner: sam.gaver@nutanix.com
# Copyright: Nutanix 2026
---
name: triage-cdp-test-failure
description: Analyzes test failure logs from internal log servers or a live cluster (SSH to any CVM, svmips for all SVMs, scan ~/data/logs), extracts unique fatal errors, signal errors (SIGSEGV etc.), and cores with stack traces and correlated activity traces, and generates JIRA-ready bug reports. Also accepts a JITA task / results URL (jita.eng.nutanix.com/results?task_ids=...) and loops through every test result in the task — triaging in-test failures with this skill, delegating Skipped-due-to-deployment-failure tests to the triage-rdm-deployment-failure skill, and returning a per-test summary at the end. After the user files ENG-XXXXXX, can back up logs/cores/binary_logs to shrek JITALOGS, add backed_up_to_shrek, and post the backup path comment via JIRA MCP (when available). Use when triaging test failures, analyzing error_patterns JSON files, live cluster CVM IPs, log URLs from internal test infrastructure, or JITA task/results URLs.
---

# Test Failure Triage

Analyzes test failure logs to generate comprehensive JIRA bug reports with
fatal errors, signal errors (SIGSEGV etc.), cores, IO Integrity, Error
Injection timeline, stack traces, and correlated activity traces. When JIRA
MCP is available, checks for existing similar issues and helps decide whether
to file a new bug or update an existing one.

---

## Reporting Discipline (READ FIRST — applies to every phase)

Triage output must be **factual and evidence-backed**. A confidently-wrong
report is worse than an honest "I'm not sure" — it sends engineers down the
wrong path and erodes trust in the skill. These rules apply to **every**
phase (ingest, extract, investigate, report, post-triage Q&A) and to **every**
mode (Archived Logs, Live Cluster, JIRA Ticket, JITA Task).

### Three claim categories

Classify every statement in the triage output as exactly one of:

1. **Observed** — directly visible in a log, file, JIRA field, or command
   output you fetched. Cite the source (`file:line`, log path, JIRA key,
   ticket field). Examples:
   - "stargate FATAL at `block_store.cc:718` on CVM 10.102.51.99 at
     2026-03-12 00:45:15 (errors.json)."
   - "EI killed cassandra on CVM .47 at 00:00:42 (background_job_logs)."
2. **Inferred** — a conclusion drawn by combining multiple observations
   (timing correlation, dependency map, ID matching). Mark with a hedge
   word ("appears to", "is consistent with", "suggests") and state the
   evidence the inference rests on. Examples:
   - "Pithos unavailability appears to have caused the stargate retry on
     the wrong node (pithos exited at 00:00:43, stargate retry observed
     at 00:00:44 with no other pithos instance available)."
   - "The two FATALs are likely the same root cause — they share
     `op_id=-1557234` and occur within 200 ms."
3. **Unknown / Unverified** — you cannot determine the answer from the
   evidence available. **Say so explicitly.** Do not paper over gaps with
   plausible-sounding language. Examples:
   - "The logs do not show why xmount was not restarted after the upgrade
     — service_monitor logs are not present in this bundle."
   - "I cannot determine from the available logs whether this is a
     product bug or a test bug; both hypotheses are consistent with the
     evidence. See 'Open questions' below."

### Hard rules

- **Never present an inference as an observation.** If you did not see
  it in a log, do not write it as if you did.
- **Cite sources for every observation.** A causal chain like
  "A failed → caused B → caused C" must have a log citation for each
  link. If a link cannot be cited, label it `inferred` or `unknown`
  and state the gap.
- **Never invent log content, error messages, file paths, line
  numbers, JIRA keys, commit hashes, gflag names, or service names.**
  If you don't have it, say so. Verify with a fresh read or grep
  before quoting.
- **Co-occurrence is not causation.** Two events at adjacent timestamps
  are correlated, not causally linked, until you find a shared ID, a
  documented dependency, or a code path connecting them.
- **One CVM's behavior is not all CVMs' behavior.** Do not generalize
  from a sample of one without checking the other CVMs.
- **The first fatal is not automatically the root cause.** Walk the
  chain backward (extract-reference.md § 7) — but only as far as the
  evidence supports. Stop and label "unknown" rather than fabricating
  an upstream cause.
- **Hedge appropriately.** Use "observed", "logs show", "errors.json
  reports" for facts; use "appears to", "is consistent with",
  "suggests", "likely" for inferences; use "I cannot determine",
  "unknown from these logs", "needs verification" for gaps. Do not use
  unhedged absolute language ("X caused Y", "this is a product bug")
  unless the evidence is direct and complete.

### When you're unsure — escalate, don't guess

If the evidence is ambiguous, contradictory, or insufficient at any
point during triage:

1. **Stop and surface the gap to the user.** A short message like:
   *"I see the stargate FATAL at 00:45:15, but the upstream pithos
   logs from that window are missing. I can't determine from the
   bundle alone whether pithos was unhealthy. Two possibilities: (a)
   pithos crashed first and triggered the retry storm, (b) the
   storage backend itself was unreachable and pithos was a victim. Do
   you want me to (i) try to fetch the archived pithos logs, (ii)
   check the live cluster, or (iii) report both hypotheses in the
   ticket?"*
2. **Ask the user for direction** when the next step requires a
   judgment call (e.g., which hypothesis to pursue first, whether to
   open a ticket vs. continue investigating, whether to attempt a
   live-cluster follow-up).
3. **Offer to verify.** When you propose an inference, suggest the
   concrete check that would confirm or refute it (a specific grep, a
   specific service log, a Sourcegraph query, a question for the
   on-call engineer). Let the user decide whether to spend the cost.

It is **always acceptable** to say:

- "I don't know."
- "I can't determine that from these logs."
- "I have two hypotheses and the evidence doesn't distinguish them."
- "Could you confirm X before I continue?"
- "Would you like me to do a deeper check on Y?"

Honest uncertainty is correct triage output. Confident-sounding
fabrication is not.

### Common failure modes to actively avoid

Watch for these specific assumption traps that have produced wrong
triages in the past:

- **Pattern-matching to a flow that doesn't quite fit.** Just because
  a fatal *looks* like a known flow does not mean it *is* that flow.
  Verify the dependency chain with actual log evidence before quoting
  the flow's root cause.
- **Re-using a JIRA dup's root cause as your own.** A similar JIRA
  ticket is a hypothesis, not a conclusion. State it as
  *"ENG-XXXXX described a similar signature — its root cause was Y;
  this triage's evidence is consistent with Y but I have not verified
  link Z of the chain in this bundle."*
- **Inferring product state from test code only (or vice versa).**
  A test assertion failure does not by itself prove the product is
  buggy or the test is wrong; check both sides.
- **Assuming a gflag, config value, or build version without
  reading it.** If you reference a specific value, you must have read
  it from `build_info.yml`, the gflag dump, the config file, or
  source code in this triage.
- **Inferring "fixed" or "won't reproduce" without checking the
  build.** Don't claim a JIRA dup is already fixed in the failing
  build's commit unless you've compared the fix commit to the build's
  commit.

### Apply this discipline in every output

Every chat response, every JIRA `Failure Summary`, every causal chain
diagram, every recommendation must follow these rules. The downstream
files (`extract-reference.md` § 7, `investigate-reference.md`,
`report-template-reference.md` Failure Summary) reinforce this for
their specific phases — but the rules above are the master version
and override anything inconsistent in the reference files.

---

## Reference Files

Detailed instructions are split into reference files in this directory. Read
them **on demand** based on the triage mode and workflow step — do not read
all of them upfront.

| File | When to read |
|------|-------------|
| [archived-logs-reference.md](archived-logs-reference.md) | Mode entry — triage mode is **Archived Logs** (user provides log URL); numbered workflow of pointers + scavenger / `filesv3` archive discovery |
| [live-cluster-reference.md](live-cluster-reference.md) | Mode entry — triage mode is **Live Cluster** (user provides CVM IP); numbered workflow of pointers + post-ticket shrek backup + logbay |
| [jita-task-mode-reference.md](jita-task-mode-reference.md) | Mode entry — triage mode is **JITA Task** (user provides a `jita.eng.nutanix.com/results?task_ids=...` URL); per-test loop, RDM-skip detection, cross-skill handoff to `triage-rdm-deployment-failure`, final per-test summary |
| [ingest-reference.md](ingest-reference.md) | Phase — fetching inputs (`errors.json`, build info, SSH + `svmips`) and producing the initial per-CVM fatal inventory. Mode-agnostic with parallel Archived / Live sub-sections. |
| [extract-reference.md](extract-reference.md) | Phase — per-fatal context extraction (stack traces, activity traces, correlation, surrounding context), root-cause chain analysis, and `steps.log` / IntegrityTester signals |
| [investigate-reference.md](investigate-reference.md) | Phase — methodology: validation-failure "keep asking why" loops, background-job activity timeline, generic cross-cutting heuristics (greenlet death, ECONNRESET ↔ peer FATAL, UI / zeus divergence) |
| [failure-patterns-reference.md](failure-patterns-reference.md) | **Index file** — service dependency map, Flow Directory table, primary vs. cascading failure ID. Read this first to identify which service subsystem is involved, then read the specific flow file from `flows/` for detailed triage steps. |
| [jira-reference.md](jira-reference.md) | Phase — JIRA operations (search, create, update, duplicates, labels, backup) |
| [report-template-reference.md](report-template-reference.md) | Phase — generating the JIRA wiki markup report (mandatory output) |
| [sourcegraph-reference.md](sourcegraph-reference.md) | Phase — source code deep-dive (local code lookup first, Sourcegraph MCP fallback; auto for novel failures, skip for known flows) |
| [telemetry-reference.md](telemetry-reference.md) | Phase — after report generation, log triage flow enrichments to MongoDB |
| [setup-guide.md](setup-guide.md) | First-time setup of JIRA or Sourcegraph MCP servers |

## When to Use

- User provides a log URL (e.g., `http://10.41.24.49/logs/.../test_name/`)
- User provides a live cluster **CVM IP** (any node)
- User provides a **JITA task / results URL**
  (e.g., `https://jita.eng.nutanix.com/results?task_ids=<task_id>`) and
  wants every test in the task triaged with a final summary. The task
  may contain a mix of in-test failures, deployment-skipped tests, and
  passes; this skill loops over them all and delegates deployment
  failures to `triage-rdm-deployment-failure` (see Step 1.5 and
  [jita-task-mode-reference.md](jita-task-mode-reference.md))
- User asks to "triage" or "analyze" test failures
- User mentions error_patterns.json or CVM logs
- User wants JIRA bug reports from test failures
- User provides a JIRA ticket key (`ENG-XXXXXX`) to triage from

---

## JIRA Helper Module

JIRA operations use `jira_helper.py` (in this directory) instead of the
Atlassian MCP server. The helper calls the JIRA REST API directly, returns
compact JSON (stripped of verbose JIRA metadata), and supports batched
workflows (e.g., multi-query search, full duplicate merge) in a single Shell
call. See [jira-reference.md](jira-reference.md) for full usage.

| Command | Purpose |
|---------|---------|
| `verify` | Check JIRA connectivity |
| `search --jql ... [--jql ...]` | Batch search with deduplication |
| `get --issue ENG-XXXXX` | Get full issue details (compact) |
| `get-dev-info --issue ENG-XXXXX` | Get linked Gerrit changes, commits |
| `create --project ENG ...` | Create a new JIRA ticket |
| `comment --issue ENG-XXXXX ...` | Post a comment (wiki markup, no conversion needed) |
| `update --issue ENG-XXXXX ...` | Update issue fields |
| `add-labels --issue ENG-XXXXX ...` | Add labels (preserves existing) |
| `link --type Duplicate ...` | Link two issues |
| `merge-duplicate --dup ... --orig ...` | Full duplicate workflow (single call) |
| `update-existing --issue ENG-XXXXX ...` | Update ticket with new evidence (single call) |
| `field-options --field-id ...` | Get allowed values for custom fields |

**MCP fallback**: The `user-atlassian` MCP server is only needed for
`jira_get_issue_images` (image attachments for LLM vision analysis). All
other JIRA operations go through `jira_helper.py`.

## MCP Servers

The following MCP servers are optionally available. Check availability before
use (see [sourcegraph-reference.md](sourcegraph-reference.md) for Sourcegraph
setup).

### Atlassian (JIRA) — server: `user-atlassian` (fallback only)
| Tool | Purpose |
|------|---------|
| `jira_get_issue_images` | Get image attachments (LLM vision) — only operation requiring MCP |

### Sourcegraph — server: `user-sourcegraph`
| Tool | Purpose |
|------|---------|
| `keyword_search` | Search code patterns; supports `repo:`, `file:`, `rev:` filters |
| `nls_search` | Semantic/flexible code search |
| `read_file` | Read file contents at a specific repo, path, and optional revision |
| `list_files` | List files/directories in a repo |
| `list_repos` | Find repositories by name substring — **rarely needed**; use the Component Mapping table in `sourcegraph-reference.md` to skip this call |

### JITA — server: `user-jita` (log access fallback only)

Provides remote shell access to JITA log bundles via the Panacea host's
pre-mounted filers at `/home/nutanix/jita_mount/<server_type>/`. Use
**only** when the local NFS mount on this workstation is unavailable
(see "Fetching Logs" below for the access ladder). Local FS access is
always preferred — JITA MCP adds a network round-trip per command, so
it does not save tokens vs. local `Shell`, only vs. HTTP `curl`.

| Tool | Purpose |
|------|---------|
| `jita_list_servers` | Enumerate the 6 JITA server types and their mount status on the MCP host |
| `jita_bundle_exists` | Check whether a bundle path exists on each of the 6 servers (one call) |
| `jita_search_files` | Glob+metadata search inside a bundle (no content) |
| `jita_exec` | Arbitrary shell (`grep`/`tail`/`head`/`awk`/pipes) with the cwd pre-set to the bundle |

Setup: see [setup-guide.md](setup-guide.md) → "JITA MCP Server".

---

## Workflow Overview

### Step 1: Mode Detection

Determine the triage mode based on user input:

- **Archived Logs Mode**: URL like `http://10.41.24.49/logs/.../test_name/`
  → Read [archived-logs-reference.md](archived-logs-reference.md)
- **Live Cluster Mode**: One CVM IP (SSH user `nutanix`). Agent runs `svmips`
  to enumerate all CVMs, then inspects `~/data/logs/`.
  → Read [live-cluster-reference.md](live-cluster-reference.md)
- **JIRA Ticket Mode**: User provides `ENG-XXXXXX`. Fetch ticket details +
  image attachments to extract CVM IPs / log URLs, then proceed with
  Archived Logs or Live Cluster mode. See
  [jira-reference.md](jira-reference.md) → **Fetching JIRA Ticket Context**.
- **JITA Task Mode**: URL like
  `https://jita.eng.nutanix.com/results?task_ids=<task_id>` (with or
  without `&active_tab=...&merge_tests=...`).
  → Read [jita-task-mode-reference.md](jita-task-mode-reference.md).
  This mode is an **orchestrator over the other modes** — it enumerates
  every test result in the task, classifies each one, and per result
  routes to either the Archived Logs sub-flow (in-test failure) or the
  `triage-rdm-deployment-failure` skill (Skipped due to RDM deployment
  failure). See Step 1.5 below for the loop and the cross-skill
  handoff protocol.

### Step 1.5: JITA Task Mode — Two-Phase Orchestration

When the input is a JITA task URL, this skill acts as an
**orchestrator** rather than triaging a single failure. The full
procedure (JITA discovery, per-test classification, signature grouping,
per-signature deep dive, final layout) lives in
[jita-task-mode-reference.md](jita-task-mode-reference.md). JITA Task
Mode is **always two phases** — do not skip Phase 2, and do not
collapse Phase 1 into Phase 2.

**Phase 1 — High-level pre-classification (cheap):**

1. Resolve the `task_id` from the URL and fetch the JITA task object
   via `https://jita.eng.nutanix.com/api/v2/agave_tasks/<task_id>`.
2. Enumerate **every** entry in `data.AgaveTestResults` and fetch each
   `agave_test_results/<id>` document. For each test, capture
   `name`, `status`, `stage`, `failure_analysis.category`, and the
   archived `log_url` (when present).
3. Classify the test (cheap signals only — do not open service logs
   yet):
   - `Passed` / `Succeeded` → record in summary, do **not** triage.
   - `Failed` / `Errored` with logs → record as **in-test failure**;
     compute a 1-line **cheap signature** (framework exception class
     + key noun, or top fatal `file:line` from `errors.json`).
   - `Skipped` with `failure_analysis.category: DEVPROD_SERVICE:RDM`
     → record as **RDM deployment failure** with its
     `scheduled_deployment_id`.
   - `Skipped` for any other reason → record reason and skip triage.
4. **Detect cascades**: if N+1, N+2, ... tests share a cluster,
   adjacent timestamps, and the same cheap signature, they are one
   cluster-state cascade — collapse them under a single signature
   (the trigger test is usually test N which Passed or Failed in
   test_body).
5. **Build the unique-signature set** (one entry per unique in-test
   signature with cascades collapsed, plus one per unique RDM
   `sd_id`).
6. **Render the high-level summary table** in chat (the table from
   `jita-task-mode-reference.md` § 5b). This is the cheap pre-pass
   the user sees first; it tells them how many wiki blocks Phase 2
   will produce.

**Phase 2 — Deep-dive per unique signature (expensive):**

7. For each unique in-test signature, pick the earliest-failing
   representative test and run the **Archived Logs sub-flow** on
   that test's `log_url` (Steps 2–6 of this skill: ingest →
   extract → investigate → JIRA dup search → wiki markup report).
8. For each unique RDM `sd_id`, **delegate to
   `triage-rdm-deployment-failure`** once (not once per Skipped
   test). See "Cross-Skill Handoff Protocol" below.
9. **JIRA duplicate search is mandatory** before producing each wiki
   block (skip only if `jira_helper.py verify` fails).
10. **One JIRA-ready wiki block per signature**, embedded under
    `#signature-<n>-report` anchors below the summary table. The
    wiki block's `h3. Test Information` section lists all N tests
    sharing the signature; the summary table's N rows all link to
    the same wiki block.

**Cascading failures collapse to one wiki block, not N.** Do not
re-triage each cascaded test.

#### Cross-Skill Handoff Protocol

A skill can invoke another skill by **reading that skill's
`SKILL.md` and following its workflow** for the duration of the
sub-task, then returning to the calling skill. Cursor's skill system
does not provide a programmatic "call" primitive — the agent simply
loads the other skill's instructions and executes them.

When this skill needs to delegate to
`triage-rdm-deployment-failure` (Skipped + `DEVPROD_SERVICE:RDM`):

1. **Announce** in chat that the test is deployment-failed and that
   you are handing the deployment investigation off to
   `triage-rdm-deployment-failure`.
2. **Read**
   `${WORKSPACE}/.cursor/skills/triage-rdm-deployment-failure/SKILL.md`
   **and**
   `${WORKSPACE}/.cursor/skills/triage-rdm-deployment-failure/sub-skill-mode-reference.md`
   (substitute `${WORKSPACE}` with the absolute path to this repo's
   root — see that skill's `setup-guide.md` for the convention).
   Then read the reference files those two instruct you to read on
   demand (`failure-patterns-reference.md`, the matching flow file,
   `jita-discovery-reference.md` if discovery is needed, etc.).
3. **Pass the JITA task ID** as the input — the RDM skill's
   `jita-discovery-reference.md` (formerly Step 1a) explains how to
   discover the `scheduled_deployment_id` from a JITA task. If you
   have already discovered the `scheduled_deployment_id` in this
   orchestration loop (e.g., from a previous Skipped test in the
   same task), pass that directly so the inner skill can skip
   `jita-discovery-reference.md`.
4. **Run the RDM skill in sub-skill mode** — see "Sub-Skill Mode
   Adjustments" below (mirrors the RDM skill's
   `sub-skill-mode-reference.md`).
5. **Capture the RDM triage findings** (root cause, suggested
   resolution, RDM deployment URL, deployment type) for the per-
   test summary row(s). All tests Skipped because of the same
   `scheduled_deployment_id` share the same root cause and link to
   the same RDM triage block in the final summary.
6. **Return** to the JITA task loop and continue with the next test.

#### Sub-Skill Mode Adjustments

When `triage-cdp-test-failure` invokes
`triage-rdm-deployment-failure` (or vice versa) as part of a
multi-test loop, the inner skill must suppress its standalone-only
side effects so the orchestrator can produce a single coherent
output. Apply the following adjustments to the inner skill:

- **Do not generate a standalone JIRA ticket** for the inner triage.
  The orchestrator decides whether to file tickets, and only after
  the per-test summary is complete (the user may want one umbrella
  ticket for the deployment failure rather than one per Skipped
  test).
- **Do not log a separate telemetry document** per inner triage when
  the same `scheduled_deployment_id` has already been triaged in this
  loop. Log telemetry **once** for the deployment, with a `notes`
  field naming the JITA `task_id` and the count of Skipped tests
  that referenced it. The orchestrator passes a session-scoped
  `triage_id` and `parent_skill: "triage-cdp-test-failure"` into
  the inner telemetry record so cross-skill sessions are correlated.
- **Produce the inner skill's report in markdown only** (no
  copy-paste-to-JIRA wiki block needed) — the orchestrator embeds it
  inline under the failing test row in the final summary.
- **Skip post-ticket backup / shrek workflows** — those are
  standalone-only and do not apply when the user is reviewing a
  multi-test run summary.

The same adjustments apply if the user invokes
`triage-rdm-deployment-failure` first and that skill needs to drop
into `triage-cdp-test-failure` to triage one of the tests that *did*
run on a successful subset of deployments in the same task — see
the equivalent section in the RDM skill's `SKILL.md`.

### Step 2: Two-Tier Triage

The **vast majority** of triages use only the log bundle (Archived Logs Mode).
This is the primary workflow — analyze logs, generate a JIRA-ready report,
and search JIRA for duplicates. Most users will stop here.

In rare cases, the log bundle analysis reveals that **live debugging** would
be valuable (e.g., an AHV host that failed to come back up). When this happens:

1. **Complete the log-bundle triage first** — generate the JIRA report.
2. **Ask the user** if the cluster is still available for live investigation.
3. If confirmed, switch to **Live Cluster Mode** for additional investigation.
4. Update the JIRA report with new findings.

Never skip or delay the log-bundle triage in favor of live debugging.

### Step 3: Archived Logs Mode (most common)

[archived-logs-reference.md](archived-logs-reference.md) has the full
numbered workflow table. Summary of the phase files the workflow
visits:

1. **Ingest** — fetch `errors.json`, dedupe fatals, fetch build info,
   extract test-level failure signature and runtime
   ([ingest-reference.md](ingest-reference.md) § "Archived Logs Mode" +
   "Shared").
2. **Extract** — per-fatal stack traces, activity traces, correlation,
   ±50 lines of context, root-cause chain analysis, `steps.log` /
   IntegrityTester signals
   ([extract-reference.md](extract-reference.md) §§ 2-8). Use the
   service dependency map and flow directory from
   [failure-patterns-reference.md](failure-patterns-reference.md) to
   know which upstream / downstream services to check, then read the
   matching flow file from `flows/`.
3. **Investigate** — validation-failure "keep asking why" loops,
   background-job activity timeline (EI / snapshots / VMotion / power
   cycles), generic cross-cutting heuristics
   ([investigate-reference.md](investigate-reference.md) —
   "Investigate Test Validation Failures", "Background Job Activity
   Timeline", "Generic Cross-Cutting Patterns").
   When the failure is a test assertion (not a service fatal), keep
   asking "why" until you reach a confirmed product bug or a confirmed
   test bug — do NOT stop at the assertion.
4. **JIRA search** — duplicate hunt
   ([jira-reference.md](jira-reference.md)).
5. **Report** — generate the JIRA wiki markup report
   ([report-template-reference.md](report-template-reference.md)),
   optionally create the ticket
   ([jira-reference.md](jira-reference.md)).
6. **Archive discovery** — for long-running tests with
   `archive_logs: True`, access the continuous CVM log stream via
   `filesv3` (archived-logs-reference.md § 1).
7. **Telemetry** — log flow enrichments
   ([telemetry-reference.md](telemetry-reference.md)).

### Step 4: Live Cluster Mode

[live-cluster-reference.md](live-cluster-reference.md) has the full
numbered workflow table. The phase files visited are the same as
Archived Logs mode, with these live-specific differences:

1. **Ingest** — SSH setup, `svmips`, per-CVM `~/data/logs/` scan
   ([ingest-reference.md](ingest-reference.md) § "Live Cluster Mode").
2. **Extract / Investigate** — same phase files as archived mode
   ([extract-reference.md](extract-reference.md),
   [investigate-reference.md](investigate-reference.md)).
3. **JIRA search + Report** — use plain-text placeholders in the
   **Links** section until logs are backed up; include the
   `backup_to_shrek` label on creation.
4. **Post-ticket backup** — `scp -rp` logs / cores / binary_logs per
   CVM to shrek, post a comment with the backup path, add
   `backed_up_to_shrek` label (live-cluster-reference.md § 1).
5. **Logbay** (optional) — collect a bundle to supplement the original
   test logs (live-cluster-reference.md § 2).

### Step 5: Sourcegraph Deep-Dive (Conditional)

After completing the standard triage (log analysis + JIRA search + report
generation), determine whether a source code deep-dive is warranted:

**Auto-dive (proceed without asking):**
- The failure traversed a subsystem not covered by any existing flow in
  the `flows/` directory (see flow directory in
  `failure-patterns-reference.md`).
- The causal chain ended at an unexplained failure (you could not determine
  *why* something failed from logs alone).
- A new `entry_type: "new_flow_candidate"` telemetry entry is being logged
  — source code context will produce a much richer flow proposal.
- **The causal chain identified a product state problem** (e.g., a service
  not running, a mount stale, a config not persisted after a lifecycle
  event) and you need to understand the product code to determine whether
  this is a known limitation or a bug. For example: if you traced a test
  validation failure back to "xmount not running after upgrade," a
  deep-dive into genesis service definitions, upgrade scripts, or
  service_monitor code would reveal *why* xmount was not restarted and
  whether this is an oversight.

**Skip (no deep-dive needed):**
- The failure matched a well-documented investigation flow and the root
  cause is clear from logs (e.g., a known JIRA duplicate).
- The failure was a simple test bug where the test code itself is wrong
  (wrong expected value, wrong path, timing issue) AND you have confirmed
  the underlying product state is correct.

**Ask the user (borderline cases):**
- The failure partially matches an existing flow but the causal chain
  diverged at an unexpected point — a deep-dive might reveal a new fork
  in the flow, but may not be worth the cost.

**IMPORTANT — disposition before deep-dive decision:** Before deciding to
skip the deep-dive as a "test bug," you MUST have completed the validation
failure investigation ([investigate-reference.md](investigate-reference.md)
— "Investigate Test Validation Failures (Keep Asking Why)"). A test
assertion failure is NOT automatically a test bug — it may be correctly
detecting a product deficiency. Only skip the deep-dive when you have
confirmed the product state is correct and the test is wrong.

When proceeding with a deep-dive, read
[sourcegraph-reference.md](sourcegraph-reference.md) and follow the
lookup strategy (local code first, Sourcegraph MCP fallback). Capture any
new subsystem knowledge (operation flows, service dependencies, failure
propagation paths) in the telemetry entry.

### Step 6: Post-Triage Follow-Up Tracking

After the JIRA report is delivered, the user may ask clarifying questions
or request further investigation. If this follow-up conversation reveals
**new domain knowledge** — a previously unknown service dependency, a
different fork in an operation flow, or a failure propagation path not
covered by the existing flow — log a **supplemental telemetry entry**
using the same `triage_id` as the original session.

**Recognizing user-guided investigation (mid-triage or post-triage):**

User guidance can happen at any point in the triage, not just after the
report is delivered. Any of these signals mean the session is
user-guided and the telemetry entry (initial or supplemental) must set
`user_guided: true`:

- The user **challenges or questions** a conclusion (e.g., "are we sure
  it's hitting that gflag limit?" or "can we verify that?").
- The user **directs the investigation** to a specific source (e.g.,
  "check the logs on the cluster," "look at the source code for X,"
  "SSH to the CVMs").
- The user **corrects** the root cause assessment or suggests an
  alternative hypothesis.
- The user **asks for deeper analysis** beyond what the standard triage
  produced (e.g., "which code path is actually being taken?").
- The user provides **domain context** that changes the investigation
  direction (e.g., "on external storage, Curator doesn't shorten
  chains").

When any of these occur, immediately flag the session internally as
user-guided. This affects the `user_guided` field on ALL telemetry
entries for the session (both the initial entry and any supplemental
entries). Do not wait until the telemetry logging step to make this
determination — track it as soon as it happens.

**When to log a supplemental entry:**
- A follow-up question led to discovering a new cross-service dependency
  (e.g., "curator also reaches out to insights_server for stats" — not
  currently in the dependency map).
- Deeper investigation revealed a branch in an operation flow not
  documented in the existing flow section.
- The user corrected the root cause assessment, and the correction reveals
  new triage knowledge.

**When NOT to log:**
- The follow-up was a red herring or dead end.
- The user asked for clarification on something already in the report.
- No new reusable investigation knowledge was gained.

Use `entry_type: "flow_used"` with `flow_enrichment` for enriching an
existing flow. Use `entry_type: "new_flow_candidate"` if the follow-up
revealed an entirely new subsystem. Set `notes` to indicate this is a
supplemental entry from post-triage follow-up.

**Automatic evaluation:** After every follow-up response in a triage
session, evaluate whether the response produced new domain knowledge
(a dependency, grep pattern, failure mode, or flow fork not already in
the matched flow file in `flows/`). If it did, log the supplemental
telemetry entry immediately in the same response — do not wait for the
user to ask. This makes telemetry logging automatic rather than
something the agent must remember to do later.

**Re-evaluation after user-guided investigation:** If the session was
flagged as user-guided (see signals above) and the initial telemetry
entry was logged with `flow_enrichment: None` (or was skipped), you MUST
re-evaluate using the enrichment checklist in the Telemetry section
before finalizing. The user-guided investigation likely produced new
knowledge that the initial evaluation missed. Run through the checklist
again, comparing what was learned during the full session (including
user-guided steps) against the flow documentation.

### Setting `user_guided`

The `user_guided` field controls promotion speed in the curation pipeline:

- **Set `user_guided: true`** when:
  - The session was flagged as user-guided at any point (see "Recognizing
    user-guided investigation" in Step 6 for the full list of signals).
  - This applies to ALL telemetry entries for the session — both the
    initial entry and any supplemental entries.
  - These entries are promoted **immediately** on the next curation run.

- **Set `user_guided: false`** when:
  - The entire triage was fully autonomous — the user provided the initial
    input and did not challenge, redirect, or extend the investigation at
    any point.
  - These entries require **3 occurrences from different test runs** before
    promotion.

When logging the initial telemetry entry after the JIRA report, check
whether any user-guided signal occurred during the session. If it did,
set `user_guided: true` on the initial entry — do not default to `false`
and wait for a supplemental entry. If the user subsequently engages in
additional follow-up that produces new knowledge, log a supplemental
entry with the same `triage_id` and `user_guided: true`. The curation
pipeline treats the entire session as user-guided if any entry in the
session has `user_guided: true`.

---

## Fetching Logs

Use the log location the user provides (URL, local path, or CVM IP).

When the user provides an **HTTP log URL**, work down this access ladder
in order. Each tier is materially cheaper than the next — do not skip
ahead.

| Tier | Access path | When to use | Cost |
|------|------------|-------------|------|
| 1 | **Local NFS mount** on this workstation, via `Shell` | Default. Always try first. | Best — zero network hops, full pipe/redirect freedom in one Shell call |
| 2 | **JITA MCP** `jita_exec` (server-side `grep`/`tail`/etc. on the Panacea host's pre-mounted filers) | Local mount is missing **and** this bundle lives on a filer the workstation does not mount, **or** modifying `/etc/fstab` is not viable (laptop / CI / no sudo) | One MCP round-trip per command. Same token cost as a Shell call (output is what you `grep`-ed) but adds network latency. Beats HTTP. |
| 3 | **HTTP `curl`** | Last resort — local mount missing **and** JITA MCP unavailable | Worst — per-file fetches return whole files unless Range-requested |

**Local mount is preferred for token efficiency.** JITA MCP and local
mount cost roughly the same in tokens (both run targeted commands and
return only matched bytes), but MCP adds a network hop. HTTP is the
expensive one to avoid — it pulls whole files. Keep all three tiers in
mind, but always start at Tier 1.

### Tier 1 — Detect Local Mount for Log URL

Given a URL like `http://10.41.24.49/logs/69c2f7b38e79ced92977466e/...`,
extract the path portion after `/logs/` and check if it exists under any
currently mounted NFS share:

```bash
URL_PATH=$(echo "$LOG_URL" | sed -E 's|^https?://[^/]+/logs/||')
for MNT in $(mount -t nfs,nfs4 | awk '{print $3}'); do
  if [ -d "$MNT/$URL_PATH" ]; then
    LOCAL_LOG_PATH="$MNT/$URL_PATH"
    break
  fi
done
```

If found, use `LOCAL_LOG_PATH` for all subsequent file reads (direct
filesystem access instead of HTTP).

### Tier 1 — Try Mounting an Unmounted Filer

If no match, check `/etc/fstab` for known but unmounted shares:

```bash
grep -E "jita-tester-afs|jita-tester-precommit-afs|cdplogs.*jitalogs" /etc/fstab \
  | while read -r line; do
    FSTAB_MNT=$(echo "$line" | awk '{print $2}')
    if ! mountpoint -q "$FSTAB_MNT" 2>/dev/null; then
      echo "In fstab but not mounted: $FSTAB_MNT"
    fi
  done
```

If a share is in fstab but not mounted and passwordless sudo is available:
`sudo mount "$FSTAB_MNT"`, then re-check.

### Tier 1 — Auto-Add Filer to fstab

If the share is not in fstab at all and sudo is available, **ask the user**
before modifying `/etc/fstab`. Use these mount options:
`nfs soft,sec=none,rw,_netdev,intr,tcp,vers=3,noatime,nodiratime,defaults 0 0`

**Known filer shares:**

| NFS Filer Share | Suggested Mount Point |
|---|---|
| `phx-labs-afs-01.corp.nutanix.com:/jita-tester-afs` | `/mnt/jitalogs` |
| `phx-labs-afs-01.corp.nutanix.com:/jita-tester-precommit-afs` | `/mnt/precommit` |
| `cdplogs.cdp.nutanix.com:/jitalogs` | `/mnt/216_logs` |
| `filesv3.cdp.nutanix.com:/volume1` | `/mnt/filesv3` |

Always check existing mounts/fstab entries before adding new ones.

The four server types `ahv_jita`, `cdp_jita`, `jita-dog-food-afs`, and
`sys-test-afs` are not in this table — they are not routinely mounted
on engineering workstations. If a bundle lives on one of these,
**escalate to Tier 2 (JITA MCP)** rather than adding a new fstab entry,
unless the user explicitly wants a permanent local mount.

### Mounting the filesv3 Filer (Archived CVM Logs)

Long-running tests with `archive_logs: True` archive CVM service logs to
`filesv3.cdp.nutanix.com:/volume1`. This filer must be mounted to access
archived logs locally. Check if it is already mounted:

```bash
mount -t nfs,nfs4 | grep filesv3
```

If not mounted, check `/etc/fstab`:
```bash
grep filesv3 /etc/fstab
```

If in fstab but not mounted: `sudo mount /mnt/filesv3`

If not in fstab, add it (with user confirmation):
```
filesv3.cdp.nutanix.com:/volume1  /mnt/filesv3  nfs  nfsvers=3  0 1
```
Then: `sudo mkdir -p /mnt/filesv3 && sudo mount /mnt/filesv3`

Once mounted, archived logs are at `/mnt/filesv3/<dir_name>/` where
`<dir_name>` is extracted from `nutest_test.log` (see
[archived-logs-reference.md](archived-logs-reference.md) § 1b).

### Tier 2 — JITA MCP Fallback

If Tier 1 fails (local mount missing, the bundle lives on an
unmounted filer such as `ahv_jita` / `cdp_jita` / `jita-dog-food-afs`
/ `sys-test-afs`, or fstab modification is not viable), check whether
the `user-jita` MCP is available before falling back to HTTP. JITA
MCP runs server-side `grep` / `tail` / `find` on the Panacea host's
pre-mounted filers and returns only the matched output — this is far
cheaper than `curl`-ing whole files.

**Step 1: Verify the MCP is available.** If `user-jita` tools are not
listed in the agent's tool inventory, the MCP server entry may be
missing from the workspace config. Check and add it per
[setup-guide.md](setup-guide.md) → "JITA MCP Server" before
proceeding (the user must reload Cursor for the new server to load).

**Step 2: Resolve the bundle path.** From a URL like
`http://10.41.24.49/logs/69c2f7b38e79ced92977466e/abcdef.../...`,
the bundle path is the segment after `/logs/` (typically
`<hex_id>/<hex_id>/...`).

**Step 3: Find which JITA server hosts the bundle.** Call
`jita_bundle_exists` with the bundle path — it returns a boolean for
each of the 6 server types in one call. Use the first server that
returns `true` as `jita_server_type` for all subsequent calls.

**Step 4: Use `jita_exec` for all reads.** Treat it as a remote
`Shell` — pass targeted commands (`grep -m 1 -A 5 'pattern' file`,
`tail -200 service.FATAL`, `find . -name 'errors.json'`) and use the
returned `stdout`. Use `jita_search_files` only when you need a file
inventory (sizes, paths) before deciding which file to grep.

Report to the user that triage is using JITA MCP and which
`jita_server_type` was selected. **Do not silently fall through to
Tier 3.**

### Tier 3 — Fall Back to HTTP

If both Tier 1 and Tier 2 fail (no local mount, JITA MCP not
configured / not reachable):
```bash
curl -s "http://10.41.24.49/logs/.../errors.json"
```

Report to the user which access method is being used (Tier 1 / 2 / 3)
and, if Tier 3, why Tier 2 was unavailable.

---

## Tips

- **Multiple CVMs**: If same fatal hits multiple CVMs, list all in "CVMs
  Affected"
- **Missing Activity Traces**: Note in report if no matching activities found
- **Complex Chains**: Include all linked operations for long activity chains
- **Timing**: Include timestamps to show operation sequence
- **Context**: If fatal mentions specific IDs, ensure they appear in activity
  traces
- **JIRA Search Strategy**: Start specific (file:line + error text), then
  broaden. Use multiple queries with different specificity levels.
- **Build Info**: Always include `Commit Id` and `GBN` from `build_info.yml`
- **Error Injection Timeline**: Prioritize EI within ±5–10 min of each
  fatal/core/SIGSEGV for correlation; summarize distant events

---

## Telemetry

After generating the JIRA report, log triage learnings to a shared MongoDB
collection. This data feeds a weekly curation pipeline that enriches
existing service investigation flows and surfaces when new flows are needed.

Read [telemetry-reference.md](telemetry-reference.md) for the insert
procedure, schema, and guidance.

**Quick summary:**
- If you followed an existing investigation flow from the `flows/`
  directory: log it as `entry_type: "flow_used"`.
  Include `flow_enrichment` if you discovered new grep patterns, failure
  modes, cross-service checks, or service dependencies not yet in the flow.
- If you traced a root cause through a subsystem not covered by any
  existing flow: log it as `entry_type: "new_flow_candidate"` with the
  subsystem description and investigation steps.
- Set `user_guided: false` for entries logged during standard automated
  triage. When post-triage user conversation produces new learnings,
  update the existing record in-place with `user_guided: true`
  (fast-path promotion). Never create a second document for the same
  triage session.
- Log **investigation knowledge** (how subsystems work and fail), not
  individual fatal signatures.
- **Keep all enrichments generic and flow-focused.** Never put specific
  JIRA tickets, commit hashes, vendor-specific class names (use the
  generic interface), or hardcoded source code line numbers into
  enrichment fields. These details belong in the `notes` field only.
  See the "Keep enrichments generic" section in
  `telemetry-reference.md` for detailed rules and examples.
- This step is **best-effort** — never block triage on telemetry failures.

**Enrichment checklist (mandatory before deciding "no enrichments"):**

Before concluding that a triage session produced no new enrichments, you
MUST read the matched flow section in the relevant `flows/` file and
explicitly check each of the following against what the flow already
documents. Answer each question — do not skip any.

1. **Grep patterns**: Did you use any grep/search patterns during this
   triage that are NOT already listed in the flow's "Key log files and grep
   patterns" section? (Include patterns from CVM log analysis, Sourcegraph
   searches, or JIRA searches that proved diagnostic.)
2. **Failure modes**: Did you discover a failure propagation path (A fails
   → causes B → causes C) that is NOT already in the flow's "Failure
   propagation" section? (Include paths learned from source code, log
   correlation, or cross-CVM investigation.)
3. **Cross-service checks**: Did you need to check a service, a different
   CVM, or a cross-component correlation that is NOT already in the flow's
   "Cross-service checks" section?
4. **Triage steps**: Did the investigation require a non-obvious step (e.g.,
   checking a specific CVM role, correlating timestamps across nodes,
   distinguishing between two code paths) that would help future triages
   but is NOT documented in the flow?
5. **JIRA keywords**: Did you find JIRA search terms that proved useful but
   are NOT in the flow's "JIRA search keywords" list?

If ANY answer is "yes," log a `flow_enrichment` dict with the new
knowledge. The default assumption should be that enrichments exist — most
deep-dives produce at least one new grep pattern or triage step.

**User communication:** Always inform the user when logging telemetry,
especially for significant discoveries:

- **New flow candidate**: Tell the user explicitly, e.g., *"This failure
  traversed a subsystem (Cerebro replication pipeline) not covered by our
  existing investigation flows. I've logged it as a new flow candidate —
  the curation pipeline will add it to the skill's knowledge base
  [immediately / after 3 independent validations]."*
- **Flow enrichment with new dependencies or failure modes**: Briefly
  note what was learned, e.g., *"During this triage I discovered that
  curator depends on insights_server for stats collection — this
  dependency wasn't in our service map. I've logged it as an enrichment."*
- **Routine flow_used with no enrichment**: A brief note is sufficient,
  e.g., *"Logged telemetry for this triage session (used the Stargate
  External Storage flow, no new enrichments)."*
- **Post-triage enrichment**: When follow-up conversation produces new
  knowledge, **update the existing telemetry document in-place** (never
  insert a second document). Tell the user what was captured, e.g.,
  *"That's a new finding — I've updated the telemetry record with
  `user_guided: true` so it gets fast-tracked into the skill."*
