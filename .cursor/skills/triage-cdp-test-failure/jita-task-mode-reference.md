# JITA Task Mode — Per-Test Loop and Cross-Skill Orchestration

Reference file for `triage-cdp-test-failure`. Read this when the user
provides a JITA task / results URL such as
`https://jita.eng.nutanix.com/results?task_ids=<task_id>` (with or
without `&active_tab=...&merge_tests=...`) and wants the entire task
triaged.

JITA Task Mode is **not** a parallel triage mode like Archived Logs or
Live Cluster — it is an **orchestrator** that, for each test result in
the task, decides whether to run this skill's Archived Logs sub-flow,
delegate to `triage-rdm-deployment-failure`, or skip triage and just
record the result.

## Two-Phase Workflow (mandatory shape)

JITA Task Mode is **always** two phases. Do not skip Phase 2, and do not
collapse Phase 1 into Phase 2.

**Phase 1 — Pre-classify all tests, render the high-level summary table.**
Walk every `agave_test_results` in the task, capture status / stage /
`failure_analysis` / log location, and produce the per-test summary
table from § 5. At this point each row has a one-line "Failure Class"
and a one-line "Root Cause" derived from cheap signals only (the test's
own `failure_analysis.message`, framework exception in `nutest.log`,
top fatal in `errors.json` if obviously the same as a sibling test).
This phase establishes the **set of unique failure signatures** in the
task.

**Phase 2 — Deep-dive once per unique signature, produce a JIRA-ready
wiki block per signature.** For each unique signature in the table,
run the Archived Logs sub-flow on **one representative test** (the
earliest-failing one is a good default). Each signature gets:

- The full Archived Logs sub-flow (extract → investigate → JIRA dup
  search → wiki markup report).
- One JIRA-ready wiki block per signature embedded below the table,
  anchored as `#signature-<n>-report`.
- One JIRA duplicate search per signature (mandatory — never produce a
  wiki block without first searching JIRA).

Cascading failures (e.g., one cluster-recreate problem fails six
sequential tests) collapse to a **single signature** with **one wiki
block**. The summary table still shows all six rows, all linking to
the same `#signature-<n>-report`. Do **not** re-triage each cascaded
test.

This file covers:

1. JITA task discovery and per-test enumeration.
2. Per-test classification and routing rules (Phase 1).
3. Building the unique-signature set and dedup logic — including RDM
   deployments and in-test cascades (Phase 2 driver).
4. The cross-skill handoff to `triage-rdm-deployment-failure`.
5. The final summary table + per-signature wiki blocks (the
   user-facing output).

The cross-skill handoff *protocol* (how skills invoke each other in
Cursor) is documented in this skill's `SKILL.md` under "Step 1.5:
JITA Task Mode — Per-Test Loop and Cross-Skill Handoff". The
RDM-side *sub-skill adjustments* (suppressing standalone-only side
effects of the inner skill) live in the RDM skill at
`sub-skill-mode-reference.md`. This file focuses on the JITA-side
mechanics and the summary format.

---

## 1. JITA Task Discovery

### 1a. Resolve the task_id

The URL always carries `task_ids=<task_id>` (sometimes `task_ids` is
plural with multiple comma-separated values — treat each as an
independent task and run the loop once per task). Extract it:

```bash
TASK_ID=$(echo "$JITA_URL" \
  | sed -E 's|.*[?&]task_ids=([^&]+).*|\1|' \
  | cut -d, -f1)
```

### 1b. Fetch the task object

```bash
curl -sS "https://jita.eng.nutanix.com/api/v2/agave_tasks/${TASK_ID}" \
  -o /tmp/jita_task.json
```

Useful top-level fields under `data`:

- `label` — human-readable name of the task / job.
- `created_by` — the user who triggered the task.
- `status`, `stage` — task-level lifecycle.
- `AgaveTestResults` — array of `{ "$oid": "<test_result_id>" }`
  entries. **One per test in the task.**
- `test_sets[].tests[]` — declarative test list with `name`,
  `resource_specs`, etc. Use this to display the human-readable
  test name in the summary even when a test was Skipped.
- `requested_hardware`, `resource_manager_json` — deployment spec
  context (useful when handing off to the RDM skill).
- `scheduler_logs` — URL to the JITA scheduler log; this is the
  authoritative source for the JITA → RDM `scheduled_deployment_id`
  linkage table. The RDM skill's `jita-discovery-reference.md`
  (formerly Step 1a in its `SKILL.md`) explains how to read it.
- `deployments` — JITA-side deployment objects (one per cluster
  deployment requested by the task). **Do not** confuse the JITA
  deployment IDs here with RDM `scheduled_deployment_id`s — they are
  distinct. Always use the scheduler log to get the RDM IDs.

### 1c. Enumerate test results

For each entry in `data.AgaveTestResults`:

```bash
TR_ID=...   # the $oid value
curl -sS "https://jita.eng.nutanix.com/api/v2/agave_test_results/${TR_ID}" \
  -o "/tmp/tr_${TR_ID}.json"
```

Per-test fields under `data` worth capturing for the summary:

| Field | Why it matters |
|---|---|
| `name` (or fall back to `test_set` + `test`) | Human-readable test name shown in the summary. |
| `status` | `Passed`, `Failed`, `Errored`, `Skipped`, `Succeeded`. |
| `stage` | `Running`, `PreparingResources`, `Cleanup`, etc. — distinguishes pre-test (deployment) skips from post-test failures. |
| `failure_analysis.category` | The classifier that drives routing. `DEVPROD_SERVICE:RDM` means the underlying RDM deployment failed. Anything else with a non-`Passed` status is an in-test failure. |
| `failure_analysis.message` | Short human-readable failure reason — useful for the summary's "Root Cause" column when this skill does not need to triage further. |
| `log_url` (or equivalent — sometimes `log_link`, `archive_log_url`, or built from `task_id` + `name`) | Archived log bundle URL passed to this skill's Archived Logs sub-flow when the test ran. |
| `cluster_id` / `cluster_name` | The cluster the test ran on. Tests in the same task may have run on different clusters from different RDM deployments. |
| `scheduled_deployment_id` (when surfaced) | If JITA exposes the RDM ID directly on the test result, capture it. Otherwise resolve via the scheduler log (see RDM skill's `jita-discovery-reference.md`). |

If `log_url` is not present on the test result document but the test
clearly ran (status `Failed` / `Errored` / `Passed` and not Skipped),
construct it from the task / scheduler log. The Archived Logs
sub-flow (Step 1 of `archived-logs-reference.md`) only needs the
`base_url` to fetch `errors.json`.

---

## 2. Per-Test Classification

For each test result, choose **exactly one** action:

| Status + signal | Action | Notes |
|---|---|---|
| `Passed` / `Succeeded` | **Record only** — do not triage. | Add to the summary as "Passed". |
| `Failed` or `Errored` with `log_url` and `failure_analysis.category != DEVPROD_SERVICE:RDM` | **Run Archived Logs sub-flow** on this test's `log_url`. | Steps 2–6 of this skill: ingest → extract → investigate → JIRA search → report. Treat each test as a separate triage with its own ingest+report; do **not** combine fatals from different tests. |
| `Skipped` with `failure_analysis.category: DEVPROD_SERVICE:RDM` (typically `stage: PreparingResources`) | **Delegate to `triage-rdm-deployment-failure`** for the underlying deployment. | Dedupe by `scheduled_deployment_id` — see Section 3. |
| `Skipped` for any other reason (test selection rule, dependency on a previously-Skipped test, manual cancel, etc.) | **Record the reason, do not triage.** | The reason usually appears in `failure_analysis.message` or `skip_reason`. |
| `Failed` / `Errored` with **no** `log_url` and no fatal category | **Record as "no logs available"**. | Mention `failure_analysis.message` in the summary. Do not invent a triage. |

### Classification examples

- A test with `status: Failed`, `stage: Running`, and a service fatal
  in its `errors.json` → in-test failure → Archived Logs sub-flow.
- A test with `status: Skipped`, `stage: PreparingResources`,
  `failure_analysis.category: DEVPROD_SERVICE:RDM` → deployment
  failure → RDM skill handoff.
- A test with `status: Skipped`, `stage: Running`,
  `failure_analysis.message: "Skipped because dependent test
  test_setup failed"` → record as a *cascaded skip*; the root cause
  is whatever made the dependent test fail (usually a different row
  in the same summary).

---

## 3. Phase 1 — Pre-Classify and Group by Signature

A single JITA task often contains:

- Multiple RDM deployments — some may fail and Skip the tests that
  needed them.
- Multi-test test classes that share state (`recreate_cluster_in_teardown`,
  long-running jobs that leave the cluster in a particular state) where
  one failure cascades into the next 5 tests.
- Tests with genuinely independent failures.

Phase 1's job is to walk every test once, classify it, and build the
**unique-signature set** that drives Phase 2. Do **not** trigger any
deep triage during Phase 1 — only cheap classification.

### 3a. Build a per-test pre-classification map

Walk every test result and capture:

```
{
  test_id, name, status, stage,
  classification,            # passed / in_test_failure / rdm_skip / other_skip / no_logs
  sd_id_if_known,            # for rdm_skip tests
  cheap_signature,           # see § 3b below — used to group cascades
  log_url,                   # for in_test_failure tests
}
```

This avoids re-running any inner skill once per cascaded test, and
gives a single source of truth for the summary table and the unique
signature set.

### 3b. Compute a cheap signature for each non-Passed test

The signature is the **string used to decide whether two failures share
a root cause** without doing a full triage. Cheap signals only — do
not open service logs in this phase. Use the first available of:

1. **Framework exception class + key noun** from `nutest.log` /
   `nutest_class.log` / `nutest_resource_object_creation.log`
   (e.g., `NuTestError: Failed to create object for N resource/s |
   InvalidValueError: memory_capacity_in_bytes`,
   `NuTestInterfaceTransportError: HTTP GET ... timeout`,
   `Monitor Util detected errors in one or more processes:
   ['IO Clone'] | UVM doesn't have an IP`).
2. **Top fatal `file:line + key words`** from the test's
   `errors.json` if non-empty (e.g.,
   `block_store.cc:718 Check failed | size_bytes`).
3. **`failure_analysis.message`** as last resort (often too generic,
   but better than empty).

Keep it short — 1 line max. Two failures share a signature iff their
1-line strings normalize to the same root-cause class. Do not include
per-test variables (test names, timestamps, container IDs).

### 3c. Detect cascades explicitly

Two common cascade shapes show up across sequential tests in the same
task:

- **Cluster-state cascade**: Test N's teardown left the cluster in a
  bad state (Acropolis disconnected after `recreate_cluster_in_teardown`,
  Stargate FATAL during `master_down`, etc.) → tests N+1, N+2, …
  fail in `resource_object_creation` / `setup` with the same
  framework exception. Detect by:
    - Same shared cluster (compare `cluster_id` / SVM IPs across
      tests).
    - Adjacent or near-adjacent timestamps.
    - Same cheap signature in the framework error.
    - Test N (the trigger) usually Passed or Failed in test_body —
      the cascade starts on N+1.
- **Test-dependency cascade**: A test was Skipped because a sibling
  failed (`failure_analysis.message: "Skipped because dependent test
  X failed"`). Classify as `Cascaded skip (depends on #N)` — its
  signature is the trigger test's signature.

When a cascade is detected, **all cascaded tests share one
signature**, which means **one wiki block in Phase 2**. Note in the
table which test is the trigger.

### 3d. Resolve `scheduled_deployment_id` for each Skipped-RDM test

The RDM skill's `jita-discovery-reference.md` (formerly Step 1a in
its `SKILL.md`) fetches the JITA scheduler log (`scheduler_logs`
URL) and greps for the JITA→RDM linkage table:

```
#  JITA DEPLOYMENT ID        STATUS     RDM DEPLOYMENT ID         LOG URL
1  <jita_dep_id_a>           failed     <rdm_sd_id_a>             ...
2  <jita_dep_id_b>           deployed   <rdm_sd_id_b>             ...
```

Map each Skipped test's JITA deployment ID (visible on the test
result via `deployment_id` or via the cluster the test was assigned
to) to its `RDM DEPLOYMENT ID`. Tests without a clear JITA→RDM
mapping (rare, but happens for very early failures): pick the single
failed RDM deployment in the table, or report ambiguity in the
summary.

### 3e. Build the unique-signature set

After 3a–3d, group tests by signature:

```
signatures = { sig: [test_ids that share sig] for sig in pre_class_map }
```

The set's keys are exactly the deep-triage budget for Phase 2:

- One entry per unique in-test failure signature (cascades collapsed).
- One entry per unique RDM `sd_id`.
- Passed / cascaded-skip / other-skip / no-logs rows do **not** add
  signatures — they only show up as table rows linking to an existing
  signature (cascade) or to nothing (passed / other-skip).

Cache `signatures[sig]` on the orchestrator so the final summary can
list all member tests under one wiki block.

### 3f. Render the high-level summary table now

Before Phase 2 starts, output the **summary table from § 5** to chat.
This gives the user the high-level picture immediately:

- N tests, N passed / N failed / N skipped.
- Unique signatures: in-test fatals, RDM deployments, cascades,
  other-skips.
- Each row's Failure Class and Root Cause one-liner.

Then announce Phase 2 in chat:

> The task has N failing tests grouped into K unique failure
> signatures (1 in-test fatal, 1 cluster-recreate cascade affecting
> 6 tests, 1 deployment failure, …). I'll now do one deep-dive per
> signature and produce a JIRA-ready wiki block for each.

Do not skip this announcement — the user needs to know the table is
the cheap pre-pass and that wiki blocks are coming.

---

## 3.5. Phase 2 — Deep Dive Per Unique Signature

For each entry in `signatures`:

### 3.5a. Pick the representative test

Default: the **earliest-failing test** in the signature group (smallest
`start_time`). Rationale: for cluster-state cascades, the trigger
test holds the most context (its teardown caused the problem). For
deployment failures, any Skipped test will do — the deployment logs
are shared.

### 3.5b. Run the appropriate inner sub-flow

- **In-test failure signature** → run Archived Logs sub-flow (§ 3 of
  `SKILL.md`): ingest → extract → investigate → JIRA dup search →
  wiki markup report. Use the representative test's `log_url`.
- **RDM deployment signature** → run cross-skill handoff to
  `triage-rdm-deployment-failure` (§ 4 of this file). One handoff per
  unique `sd_id`.

### 3.5c. JIRA duplicate search is mandatory

**Before** producing the wiki block, search JIRA for similar issues
using `jira_helper.py search` (see `jira-reference.md`). Build at
least 2–3 JQL queries per signature using:

- The fatal `file:line` if any.
- Key error message phrases.
- The service component (Stargate, Aplos, Acropolis, Insights, …).

Record the top matches in the wiki block's "Related Tickets"
section. If JIRA is unavailable (verify failed), still produce the
wiki block but write `JIRA unavailable — search manually` in
"Related Tickets".

### 3.5d. Produce one JIRA-ready wiki block per signature

The block follows `report-template-reference.md` exactly, with two
JITA-Task-Mode adjustments:

1. **`h2.` title** names the signature class, not a single test:
   `h2. Bug Report: [Service] [Brief Class] (affects N tests in JITA task <task_id>)`.
2. **`h3. Test Information`** lists all N tests sharing the
   signature, not just the representative. Include each test's name
   and test result ID. Mark the representative explicitly.

Embed each block under an anchor `#signature-<n>-report` so the
summary table rows can link to it. Use a fenced code block with the
wiki markup verbatim so the user can copy-paste straight into JIRA.

### 3.5e. Bound the work for very large tasks

Even with signature grouping, very large tasks (>20 unique
signatures) are still expensive. If you hit that, tell the user
upfront and ask whether to continue all signatures or only the top-N
by affected-test-count.

### 3.5f. Dedupe deployments and run the RDM skill once per unique ID

Build the unique RDM set:

```
sd_ids_to_triage = { sd_id for (test, sd_id, classification)
                     in pre_class_map
                     if classification == "rdm_skip" }
```

For each `sd_id` in `sd_ids_to_triage`, perform exactly one cross-
skill handoff (see Section 4). Cache the result by `sd_id` so the
final summary can reference each RDM triage block from every
Skipped-RDM row.

---

## 4. Cross-Skill Handoff to `triage-rdm-deployment-failure`

The protocol is documented in this skill's `SKILL.md` §
"Cross-Skill Handoff Protocol" and "Sub-Skill Mode Adjustments".
The matching adjustments on the RDM side live at
`triage-rdm-deployment-failure/sub-skill-mode-reference.md`.
Concretely, for each unique `sd_id` to triage:

1. Tell the user, in chat, what is happening:

   > Test `<name>` was Skipped with `failure_analysis.category:
   > DEVPROD_SERVICE:RDM` (and N other tests in this task were
   > skipped for the same reason, all pointing at RDM
   > `<sd_id>`). Handing the deployment investigation off to the
   > `triage-rdm-deployment-failure` skill.

2. Read
   `${WORKSPACE}/.cursor/skills/triage-rdm-deployment-failure/SKILL.md`
   (substitute `${WORKSPACE}` with the absolute path to this repo's
   root — see that skill's `setup-guide.md` for the convention)
   **and**
   `${WORKSPACE}/.cursor/skills/triage-rdm-deployment-failure/sub-skill-mode-reference.md`
   (which holds the sub-skill adjustments that used to live in the
   RDM skill's `SKILL.md`). Then follow the RDM workflow starting at
   Step 2 — the `scheduled_deployment_id` is already known from
   Section 3b, so skip the RDM skill's Step 1a (now in
   `jita-discovery-reference.md`).

3. Honor the sub-skill adjustments
   (`sub-skill-mode-reference.md` in the RDM skill):
   - No standalone JIRA ticket creation from the inner skill.
   - Telemetry: log **once** per `sd_id` with `parent_skill:
     "triage-cdp-test-failure"` and a `notes` field naming the
     JITA `task_id` and the count of Skipped tests that referenced
     this deployment.
   - Output the RDM triage findings inline as a markdown block
     (Deployment Summary, Failure Stage, Root Cause Analysis,
     Suggested Resolution, Links). Skip optional sections per the
     RDM skill's "Brevity rule for the report".

4. Capture for the orchestrator:
   - One-line root cause (used in the summary "Root Cause" column).
   - Suggested resolution (one line).
   - RDM deployment URL (used in the "Link" column for every
     Skipped-RDM row that references this `sd_id`).

5. Return to the JITA task loop and continue.

---

## 5. Final Output Layout

JITA Task Mode produces a **single chat response** with three layers,
in this order:

1. **Per-test summary table** (top-level, always rendered first — also
   rendered at the end of Phase 1 as an interim output).
2. **One JIRA-ready wiki block per unique in-test signature**,
   anchored as `#signature-<n>-report`. Rows in the table whose
   signature is `<n>` link to this block.
3. **One RDM deployment triage block per unique `sd_id`**, anchored as
   `#rdm-deployment-<sd_id>`. Rows in the table that share an `sd_id`
   link to the corresponding block.

Wiki blocks are produced per **signature** (cascades collapsed), not
per test. A 9-test task with 1 in-test fatal + 1 cluster-recreate
cascade affecting 6 tests + 1 RDM deployment failure produces:

- 1 summary table with 9 rows.
- 2 in-test wiki blocks (one per signature).
- 1 RDM block.

NOT 8 wiki blocks (one per failed test).

### 5a. Header

```
# JITA Task Triage Summary

- **JITA Task**: <label> (<task_id>)
- **Job created by**: <created_by>
- **Total tests**: <n>  | Passed: <p>  | Failed/Errored: <f>  | Skipped: <s>
- **RDM deployments in task**: <total_deployments>
  - Successful: <ok>  | Failed: <bad>
- **Unique failure classes**:
  - In-test fatals: <count>  (<count of unique signatures>)
  - RDM deployment failures: <count>  (one row per unique sd_id below)
  - Other skips: <count>
- **JITA URL**: https://jita.eng.nutanix.com/results?task_ids=<task_id>
```

### 5b. Per-test table

A markdown table with **one row per test result in the task**, in
the same order JITA returns them (or grouped by status if it makes
the table more readable):

| # | Test Name | Status | Failure Class | Root Cause (one line) | Link |
|---|---|---|---|---|---|
| 1 | `cdp.foo.bar.test_smokes.TestSmokes~~~PowerStore.test_smokes___powerstore` | Passed | — | — | [logs](http://...) |
| 2 | `cdp.foo.bar.test_smokes.TestSmokes~~~Pure.test_smokes___pure` | Failed | In-test fatal: `block_store.cc:718 CHECK failed` | Stargate forest hit BG check during compaction | [report](#test-2-report) |
| 3 | `cdp.foo.bar.test_external_storage.TestExternalStorage.test_basic` | Skipped | RDM deployment failure (sd `<sd_id>`) | Cluster came up HCI but spec did not set `diskless_cvm: true` → `external_storage/create` rejected with HTTP 400 | [RDM triage](#rdm-deployment-sd-id) |
| 4 | `cdp.foo.bar.test_external_storage.TestExternalStorage.test_resize` | Skipped | RDM deployment failure (sd `<sd_id>`) (same as #3) | (same as #3) | (same as #3) |
| 5 | `...` | Skipped | Cascaded skip (depends on #2) | Test #2's failure aborted this test | — |

Rules for the table:

- **Failure Class column** must use one of: `In-test fatal: <sig>`,
  `Test failure (no fatal)`, `RDM deployment failure (sd <sd_id>)`,
  `Cascaded skip (depends on #N)`, `Other skip: <reason>`, `No logs
  available`, or `—` for Passed.
- **Root Cause** is at most one sentence. If unknown after triage,
  write `unknown — see report` and link the per-test report.
- **Link** points to `#test-<n>-report` for in-test failures (the
  per-test JIRA wiki block embedded later in the chat) or
  `#rdm-deployment-<sd_id>` for RDM-skipped tests.
- Multiple Skipped-RDM rows pointing at the same `sd_id` reuse the
  same Root Cause text and link — explicit duplication is fine; do
  not omit rows for tests that share an upstream cause.

### 5c. RDM deployment triage blocks

After the table, embed **one block per unique `scheduled_deployment_id`**
that was triaged. Use the markdown anchor `#rdm-deployment-<sd_id>`
the table linked to. Each block contains the inner RDM skill's report
sections (Deployment Summary, Failure Stage, Root Cause Analysis,
Suggested Resolution, Links) — produced when running the RDM skill in
sub-skill mode.

### 5d. Per-signature in-test failure reports

Below the RDM blocks, embed the per-signature JIRA wiki markup
reports generated by the Archived Logs sub-flow, **one per unique
signature** (not one per test). Each in a fenced code block, anchored
as `#signature-<n>-report`. The block's `h3. Test Information`
section lists all tests sharing that signature, with the
representative test marked.

Multiple summary table rows that share a signature all link to the
**same** `#signature-<n>-report`. This is intentional — explicit
duplication in the table is better than hiding cascaded tests, and
the wiki block reads cleanly as "this single bug affects N tests".

### 5e. JIRA ticket recommendation

After the reports, give the user a short, explicit recommendation:

> ## Suggested next steps
>
> - File 1 JIRA ticket **per unique signature** above (one ticket
>   covers all tests sharing that signature — list them in the
>   ticket's affected-tests field).
> - File 1 JIRA ticket per unique RDM deployment failure (sd
>   `<sd_id>`), referencing all <N> Skipped tests as affected.
>   Suggested category from the RDM triage:
>   `<PRODUCT|INFRA|PLUGIN|CONFIG>`.
> - No action needed for the cascaded skips and Passed tests.

The orchestrator never silently files tickets — the user confirms
which ones to file. Each suggested ticket maps 1:1 to a wiki block
above; the user can copy-paste the block straight into the new
ticket's description.

---

## 6. Telemetry

JITA Task Mode logs telemetry as follows:

- **One outer entry** in this skill's collection
  (`skill_telemetry.pattern_encounters`) with `entry_type:
  "jita_task_orchestration"`. Fields:
  - `triage_id` — UUID for the orchestration session.
  - `task_id` — JITA task ID.
  - `n_tests`, `n_passed`, `n_failed`, `n_skipped`,
    `n_rdm_skipped`, `n_unique_fatal_sigs`,
    `n_unique_rdm_sd_ids`.
  - `delegated_to`: list of `{ skill_name, count }` entries
    summarizing how many sub-skill handoffs were made.
  - `user_guided` — same semantics as the rest of this skill.

- **One inner entry per Failed/Errored test** that was triaged via
  the Archived Logs sub-flow (the existing `flow_used` /
  `new_flow_candidate` schema). Set `parent_triage_id` to the outer
  orchestration's `triage_id`.

- **One inner entry per unique `sd_id`** triaged by the RDM
  sub-skill, written by the RDM skill into its own collection
  (`deployment_pattern_encounters`). The orchestrator passes
  `parent_skill: "triage-cdp-test-failure"` and
  `parent_triage_id` so cross-skill sessions are correlatable.

- **Skip telemetry entirely** for Passed, cascaded-skip, other-skip,
  and no-logs rows.

---

## 7. Common pitfalls

- **Treating the JITA `deployments[]._id` as the RDM
  `scheduled_deployment_id`.** They are different objects in
  different services. Always resolve via the scheduler log.
- **Re-running the RDM skill once per Skipped test.** Dedupe by
  `sd_id` (Section 3c). A 20-test task that lost one deployment
  should produce 1 RDM triage, not 20.
- **Producing one giant merged JIRA report.** Each in-test failure
  gets its own report block. The summary table is the single top-
  level deliverable; reports are children of summary rows.
- **Filing tickets automatically.** Always recommend, never auto-
  file, in JITA Task Mode. The user picks which tickets to create
  after seeing the cross-test picture.
- **Forgetting cascaded skips.** If a test was Skipped because of a
  test-dependency on another failing test (not because of RDM),
  classify it as `Cascaded skip (depends on #N)` — the user needs
  to see that the upstream fix will unblock it.
