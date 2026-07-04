# JITA Discovery Reference

Reference file for `triage-rdm-deployment-failure`. Read this **only**
when the user provides a JITA task/results URL and you need to
resolve the underlying RDM `scheduled_deployment_id`. If the user
provided an RDM URL or a service-level log link directly, skip this
file and start at Step 2 of the workflow.

---

## Why This Step Exists

The RDM `scheduled_deployment_id` is **not** in the JITA task or
test-result objects directly — it is printed in the **task-level
scheduler log** that the JITA scheduler writes while waiting for RDM
to provision the resources.

---

## Procedure

1. **Extract the JITA `task_id`** from the URL's `task_ids` query
   param (e.g. `69f53222d24d82c7fe989175`).

2. **Sanity-check that the failure is RDM-side.** Fetch any one of
   the test results listed under `data.AgaveTestResults` on the task
   and look at `data.failure_analysis.category`:

   ```bash
   curl -sS \
     "https://jita.eng.nutanix.com/api/v2/agave_tasks/<task_id>" \
     | python3 -c "import sys,json; \
       j=json.load(sys.stdin)['data']; \
       print(j['AgaveTestResults'][0]['\$oid'])"

   curl -sS \
     "https://jita.eng.nutanix.com/api/v2/agave_test_results/<test_result_id>" \
     | python3 -c "import sys,json; \
       d=json.load(sys.stdin)['data']; \
       print(d.get('status'), d.get('stage'), \
             d.get('failure_analysis'))"
   ```

   For an RDM deployment failure, expect:
   - `status: "Skipped"`
   - `stage: "PreparingResources"` (or similar pre-test stage)
   - `failure_analysis.category: "DEVPROD_SERVICE:RDM"`

   If `failure_analysis.category` is anything other than
   `DEVPROD_SERVICE:RDM`, this is **not** an RDM deployment failure
   and you should hand off to a different skill (e.g.
   `triage-cdp-test-failure` for an in-test fatal).

3. **Fetch the JITA task's scheduler log** and grep for the
   JITA → RDM linkage table that the scheduler prints repeatedly
   while the deployment is in flight:

   ```bash
   SCHED_URL=$(curl -sS \
     "https://jita.eng.nutanix.com/api/v2/agave_tasks/<task_id>" \
     | python3 -c "import sys,json; \
         print(json.load(sys.stdin)['data']['scheduler_logs'])")

   curl -sSL "$SCHED_URL" -o /tmp/jita_sched.log
   grep -E "JITA DEPLOYMENT ID|RDM DEPLOYMENT ID" /tmp/jita_sched.log \
     | head -5
   ```

   The scheduler log contains a periodic block that looks like:

   ```
   #  JITA DEPLOYMENT ID        STATUS     RDM DEPLOYMENT ID         LOG URL
   1  <jita_dep_id>             deploying  <rdm_sd_id>               <jita_log_url>
   ```

   The fourth column (`RDM DEPLOYMENT ID`) is the
   `scheduled_deployment_id` you need. From here, proceed with Step 2
   of the main workflow against
   `https://rdm.eng.nutanix.com/api/v1/scheduled_deployments/<rdm_sd_id>`.

4. **(Optional, useful for the report)** Capture the JITA-side
   metadata while you have it: `data.label`, `data.created_by`, the
   list of tests in `data.test_sets[].tests[].name`, the
   `requested_hardware.nested_params`, and `resource_manager_json`
   (which carries the build/commit/external-storage spec). Including
   these in the report lets the user click straight from the report
   back to the test that originally tripped the failure.

---

## Failure Modes for Discovery

If JITA discovery fails, do **not** fabricate an `sd_id`. Apply the
fallback rules in the "Fallback & Recovery" section of `SKILL.md`:

| Symptom | Action |
|---|---|
| JITA API returns 5xx | Retry once after 30s; if still 5xx, abort triage and report "JITA API unavailable; cannot resolve RDM `sd_id`. Ask the user to provide the RDM URL directly." |
| `scheduler_logs` field is empty/missing on the task | Task aborted before RDM picked it up. Report "JITA task aborted before RDM allocation; no deployment to triage." |
| Scheduler log fetched but contains no `RDM DEPLOYMENT ID` row | Same root cause as above, or task is still in flight. Report what you saw and stop. |
| `failure_analysis.category` != `DEVPROD_SERVICE:RDM` | Not an RDM failure. Hand off to `triage-cdp-test-failure` (or whichever skill matches the category). |

---

## Notes / Gotchas

- The JITA `_id`, the `AgaveTestResults._id`s, and the JITA
  `deployments._id` (visible in the scheduler log under "JITA
  DEPLOYMENT ID") are **not** the RDM `scheduled_deployment_id`.
  Don't curl
  `https://rdm.eng.nutanix.com/api/v1/scheduled_deployments/<jita_id>`
  with a JITA id — it will not resolve.
- The JITA REST endpoint `/api/v2/deployments/<id>` exists but
  returns `{"message": "The page doesn't exist"}` for RDM-style
  lookups. Don't rely on it for the JITA → RDM linkage. Always read
  the JITA → RDM linkage out of the **task-level scheduler log**.
