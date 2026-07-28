# Sub-Skill Invocation Mode

Reference file for `triage-rdm-deployment-failure`. Read this **only**
when the skill is being invoked from another skill (today: only from
`triage-cdp-test-failure` JITA Task Mode). When the user invokes this
skill directly, skip this file entirely.

Cursor skills do not have a programmatic "call" primitive — a calling
skill invokes this one by **reading
`${WORKSPACE}/.cursor/skills/triage-rdm-deployment-failure/SKILL.md`**
(where `${WORKSPACE}` is the absolute path to this repo's root — see
[setup-guide.md](setup-guide.md)) and following the workflow inline.
When that happens, the agent must suppress this skill's standalone-
only side effects so the calling skill can produce a single coherent
output.

---

## Detection — Are You a Sub-Skill?

You are running as a sub-skill if **any** of these are true:

- The agent is already inside a `triage-cdp-test-failure` JITA Task
  Mode loop and is iterating over a Skipped test result with
  `failure_analysis.category: DEVPROD_SERVICE:RDM`.
- The calling skill explicitly tells you "running RDM triage in
  sub-skill mode for sd `<sd_id>` as part of JITA task `<task_id>`".
- The calling skill passes you a `parent_skill` and `parent_triage_id`.

If none of these are true, treat the invocation as standalone and
ignore the rest of this file.

---

## Adjustments When Invoked as a Sub-Skill

1. **Skip Step 1a (JITA discovery)** — the calling skill already
   resolved the `scheduled_deployment_id` for you. Start at Step 2
   (`Fetch Deployment Metadata from RDM API`) using the `sd_id`
   passed in.

2. **Do not produce a separate, standalone JIRA ticket.** The
   calling skill handles ticketing decisions after the per-test
   summary is complete. Generate the markdown triage report only.

3. **Use the brevity rule** from the "Triage Discipline (KISS
   First)" section in `SKILL.md` — Deployment Summary, Failure
   Stage, Root Cause Analysis, Suggested Resolution, Links. Skip
   Source Code References and Base Cluster Diagnostics unless
   they are needed to explain the failure (the inline embedding
   under a summary row should be tight).

4. **Output the report in plain markdown** so the orchestrator can
   embed it under a `#rdm-deployment-<sd_id>` anchor in the JITA
   Task summary. No JIRA wiki markup conversion needed.

5. **Telemetry**: log **once** per `sd_id` to
   `skill_telemetry.deployment_pattern_encounters` with
   `parent_skill: "triage-cdp-test-failure"` and the
   `parent_triage_id` provided by the calling skill. Add a `notes`
   field naming the JITA `task_id` and the count of Skipped tests
   that referenced this deployment. Never log per-Skipped-test —
   one document per `sd_id`.

   **Sub-skill telemetry chatter:** do not announce telemetry
   inserts to the user mid-loop. The orchestrator will summarize
   telemetry once at end-of-run (see
   [telemetry-reference.md](telemetry-reference.md), "User
   Communication Under Orchestration").

   **`user_guided` semantics under orchestration:** the orchestrator
   is **not** a "user" for this field. Set `user_guided: false`
   unless the human user directly intervened in this specific
   sub-skill iteration (e.g., they corrected a finding or extended
   the investigation in a comment that reached this sub-skill).
   Routine orchestrator-driven invocations are autonomous.

6. **Do not request follow-up actions from the user mid-loop**
   (e.g., "do you want me to SSH to the base cluster?"). If
   base-cluster diagnostics are needed for a confident root cause,
   either run them silently per Step 5b (when the deployment is
   Nested AHV 2.0 and qualifies) or note in the report that
   deeper investigation is recommended and let the orchestrator
   surface that to the user with the rest of the summary.

7. **Return** to the calling skill. Hand back: one-line root cause,
   one-line suggested resolution, RDM deployment URL, deployment
   type, failure category — these populate the per-test summary
   table in the calling skill's output.

---

## Direct Invocation — When the User Comes In Through This Skill

When the user invokes this skill **directly** (RDM URL, service-
level log link, or JITA URL with a single deployment) and is **not**
inside a JITA Task Mode orchestration, behave normally — generate
the full standalone report and log telemetry as usual. None of the
sub-skill adjustments above apply.

When the user invokes this skill directly with a JITA task URL that
turns out to contain **multiple deployments and a mix of Passed /
Failed / Skipped tests**, it is appropriate to recommend the user
re-invoke via `triage-cdp-test-failure` for the per-test summary, or
to perform the same orchestration loop here (the loop logic in
`triage-cdp-test-failure/jita-task-mode-reference.md` works
symmetrically — read that file, do the per-test classification, and
delegate Failed/Errored test rows back to `triage-cdp-test-failure`
using the same Sub-Skill Invocation Mode protocol in reverse). Pick
whichever feels less surprising for the user; default to recommending
the CDP entry point unless the user explicitly asked for an RDM-only
view.
