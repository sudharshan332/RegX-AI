# Live Cluster Mode — Workflow Summary

Reference file for `triage-cdp-test-failure`. Read this when the triage
mode is **Live Cluster** (user provides a CVM IP).

This file captures the live-mode-specific orchestration: the numbered
workflow sequence, post-ticket shrek backup, and logbay collection.
The actual fetch / extract / investigate / report procedures live in
the phase-based reference files.

---

## Workflow Sequence

| Step | What | Reference |
|------|------|-----------|
| 1 | SSH setup, enumerate all CVMs (`svmips`), fetch build / config | [ingest-reference.md](ingest-reference.md) § "Live Cluster Mode" |
| 2 | Discover failures in `~/data/logs/` across all CVMs | [ingest-reference.md](ingest-reference.md) § "Live Cluster Mode" § 4 |
| 3 | Per-fatal context: stack traces, activity traces, correlation | [extract-reference.md](extract-reference.md) § 2-6 |
| 4 | Root-cause chain analysis | [extract-reference.md](extract-reference.md) § 7 |
| 4b | Validation-failure "keep asking why" (when there is no service fatal) | [investigate-reference.md](investigate-reference.md) — "Investigate Test Validation Failures" |
| 5 | Generic cross-cutting heuristics (greenlet death, ECONNRESET ↔ peer FATAL, UI / zeus divergence) | [investigate-reference.md](investigate-reference.md) — "Generic Cross-Cutting Patterns" |
| 6 | JIRA duplicate search (only after a crisp signature exists) | [jira-reference.md](jira-reference.md) — **Searching JIRA for Similar Issues** |
| 7 | Generate JIRA wiki report (mandatory) — use plain text placeholders in **Links** until logs are backed up | [report-template-reference.md](report-template-reference.md) |
| 7b | Optionally create JIRA ticket (include `backup_to_shrek` label) | [jira-reference.md](jira-reference.md) — **Creating a New JIRA Ticket** |
| 8 | Post-ticket backup + JIRA updates (user supplies `ENG-XXXXXX`) | § 1 below — live-mode specific |
| 9 | Optional: logbay bundle collection | § 2 below — live-mode specific |
| 10 | Log telemetry | [telemetry-reference.md](telemetry-reference.md) |

If the test ran via the NuTest framework on a dev VM that is still
reachable, the shared test-level context extraction patterns in
[ingest-reference.md](ingest-reference.md) (`nutest_test.log`,
`steps.log`, `code_active_state.log`, `background_job_logs/`) still
apply — use them to surface harness-level failure signatures and
background-job correlation.

---

## 1. Post-Ticket Backup + JIRA Updates (User Provides `ENG-XXXXXX`)

When the user has **created** the ticket and supplies the key:

### a. Paths on shrek

```bash
JIRA_KEY="ENG-12345"
SHREK="nutanix@shrek-v2.eng.nutanix.com"

for CVM_IP in "${CVM_IPS[@]}"; do
  ssh "$SHREK" \
    "mkdir -p /jita/www/html/JITALOGS/$JIRA_KEY/$CVM_IP/{logs,cores,binary_logs}"
  scp -rp "$USER@$CVM_IP:~/data/logs/." \
    "$SHREK:/jita/www/html/JITALOGS/$JIRA_KEY/$CVM_IP/logs/"
  scp -rp "$USER@$CVM_IP:~/data/cores/." \
    "$SHREK:/jita/www/html/JITALOGS/$JIRA_KEY/$CVM_IP/cores/" || true
  scp -rp "$USER@$CVM_IP:~/data/binary_logs/." \
    "$SHREK:/jita/www/html/JITALOGS/$JIRA_KEY/$CVM_IP/binary_logs/" || true
done
```

### b. JIRA comment (backup location)

Post via `jira_helper.py` (if JIRA available):
```bash
python3 "$JIRA_HELPER" comment --issue ENG-12345 --body 'Test logs and diagnostics have been backed up to nutanix@shrek-v2.eng.nutanix.com.

Absolute path prefix: /jita/www/html/JITALOGS/ENG-12345/
Per-CVM layout: .../ENG-12345/<cvm_ip>/\{logs,cores,binary_logs\}
Web URL: http://shrek-v2.eng.nutanix.com/JITALOGS/ENG-12345'
```

### c. JIRA label `backed_up_to_shrek`

```bash
python3 "$JIRA_HELPER" add-labels --issue ENG-12345 --labels backed_up_to_shrek
```

### d. Optional: Pre-JIRA Staging to `stgaver/`

Copy to `/jita/www/html/stgaver/triage_<timestamp>/` before having a
JIRA key, then `mv` to `JITALOGS/<JIRA_KEY>/` once the user creates
the ticket. When the user already has a ticket key, prefer copying
directly to `JITALOGS/<JIRA_KEY>/`.

---

## 2. Collecting a Logbay Bundle

During live debugging, if you discover relevant evidence outside the
scope of the original test logs:
```bash
ssh nutanix@<any_cvm_ip> "logbay collect --duration=<hours_since_failure>"
```
The bundle is written to `~/data/logbay/` on the CVM that runs the
command. Back up the bundle to shrek alongside the test's original
log bundle.
