# Ingest: Fetch Inputs and Survey Initial Failures

Reference file for `triage-cdp-test-failure`. The ingest phase covers
how to obtain the raw inputs for triage and produce a first-pass
inventory of candidate fatals / signal errors. Read this at the start
of every triage.

Regardless of mode, the deliverable before proceeding to
[extract-reference.md](extract-reference.md) is:
- A **per-CVM list of candidate fatals** (service + file:line +
  assertion text) with the specific log file and timestamp for each.
- **Build info** (`Commit Id`, `GBN`, `Branch`) for the JIRA report.
- **Test-level context** (runtime, harness failure signature,
  correlated background-job actions) when the test framework ran it
  — applies to both modes when `nutest_test.log` is available.

---

## Archived Logs Mode — URL-Based Ingest

Ingest from a user-supplied log URL
(e.g. `http://10.41.24.49/logs/.../test_name/`). Prefer local NFS
mount access over HTTP fetches when available — see `SKILL.md`
**Fetching Logs** for mount detection and fstab setup.

### 1. Fetch and Parse errors.json

**URL Pattern**: `{base_url}/error_patterns_*/PE/errors.json`

Extract per CVM: `fatal_errors`, `signal_errors`, `cores`:
```json
{
  "10.102.51.99": {
    "fatal_errors": [{
      "line": "block_store.cc:718] Check failed: ...",
      "time_location_tuples": [["2026-03-12 00:45:15", "/home/nutanix/data/logs/stargate.out.20260312-002450Z"]]
    }],
    "signal_errors": [{
      "line": "SIGSEGV received ...",
      "time": "2026-03-12 00:45:15",
      "file_path": "/home/nutanix/data/logs/stargate.out.20260312-002450Z"
    }],
    "cores": [{"name": "stargate", "pid": "12345", "time": "2026-03-12 00:45:15"}]
  }
}
```

### 2. Deduplicate Errors (Fatals, Signal Errors)

Group fatals and `signal_errors` by unique signature:
- Extract file:line (e.g., `block_store.cc:718`)
- Extract CHECK / assertion text (fatals) or signal type + context
  (signal_errors)
- Ignore timestamps, PIDs, specific values

Track which CVMs hit each unique fatal / signal_error. List cores per
CVM (name, pid, time).

See [extract-reference.md](extract-reference.md) § 1 for the canonical
signature format and the rule against grepping by source line number.

### 3. Fetch Base Config & Build Information

**Base Config URL Pattern**: `{base_url}/*_base_config.json`

Fetch the config and extract only the `summary` section. Format using
Python's `pformat` style (not JSON).

**Build Info URL Pattern**:
`{base_url}/nos_cluster_logs_*/[any_cvm_ip]/config/build_info.yml`
(or sibling `build_info.yaml` — only one exists on the CVM)

Fetch `build_info.yml` / `build_info.yaml` from any CVM's config
directory to extract the exact build details:
```yaml
Branch: master
BuildType: opt
Commit Id: d98e3484362b45eea773dbed5832f2dbb5d50056
GBN: '1773193895'
Parent Commit Id: 78bdb1aaa86d1520f2c54a29d9bb023970f9659d
Platform: el9
Version: master
```
Record the `Commit Id` (SHA-1 hash) and `GBN` — include them in the
bug report. The `Commit Id` is a 40-character hex string. Do not
confuse it with `Branch` (e.g., `master`, `ncm-2.1-release`) or
`Version` — these are separate fields. For telemetry, `build_commit`
must always be the `Commit Id` hash, never a branch or version name.

**External Storage Array Info** (when the test uses external
storage): Look for `zeus_config_printer` output to extract the
connected storage array details from the `external_storage_list`
section. Common locations (try in order):
1. `{base_url}/debug_dumps/zeus_config_printer*` or
   `{base_url}/debug_dumps/zk_config*`
2. `{base_url}/nutest_test.log` (sometimes zeus config is dumped
   inline)
3. `{base_url}/nos_cluster_logs_*/[any_cvm_ip]/config/`

From `external_storage_list`, extract:
- **Array Name**: the `external_storage_name` field (e.g.
  `phx-pstore-array03`)
- **Array IP**: the management IP (e.g. `10.49.114.41`). This may not
  appear in `zeus_config_printer` — if absent, search
  `nutest_test.log` for the `external_storage/login` REST call which
  contains `"mgmnt_ip": "<ip>"`.
- **Vendor/Type**: the provider field (e.g. `kDellPowerStore`,
  `kPureStorage`)

Include these in the Test Information section of the JIRA report as
`* *External Storage*: <vendor> — <array_name> (<array_ip>)`.

---

## Live Cluster Mode — CVM-Based Ingest

Ingest from a user-supplied CVM IP. SSH to that CVM as `nutanix`,
enumerate peers, and scan each CVM's `~/data/logs/`.

### 1. SSH Access Setup

```bash
USER="nutanix"
PASSWORD="RDMCluster.123"
CVM_IP="10.102.51.99"

sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$USER@$CVM_IP" "command"
```

### 2. Enumerate All CVM IPs (`svmips`)

On the **entry** CVM, collect every SVM / CVM IP:
```bash
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$USER@$CVM_IP" "svmips"
```
Parse the output into a unique list. **Re-run the same SSH + command
pattern on each CVM IP** when inspecting that node's `~/data/logs/`.

If `svmips` fails, fall back to the single user-provided IP and note
in the report that the triage may be **single-node only**.

### 3. Cluster Build / Config

Build metadata is in **`/home/nutanix/config/build_info.yml`** or
**`build_info.yaml`** (only one exists per image; try `.yml` first).
```bash
ssh $USER@$CVM_IP 'sh -c "for f in /home/nutanix/config/build_info.yml /home/nutanix/config/build_info.yaml; do test -f \"$f\" && cat \"$f\" && exit 0; done; echo \"no build_info.yml or build_info.yaml\"; exit 1"'
```
Extract `Commit Id`, `GBN`, `Version`, `Branch`, etc., for the JIRA
report. Same rules as archived-mode § 3 — `Commit Id` is always the
40-char hash, not a branch / version.

### 4. Discover Failures in `~/data/logs/` (All CVMs)

**Goal:** Summarize *what failed*, *where* (which CVM + service log),
*when* (timestamps / fatal ids), and *what to open next*. This is the
live-mode analogue of parsing `errors.json` in archived mode.

Per **each** `CVM_IP` from `svmips`:

1. **List recent activity**: `ls -lt ~/data/logs | head`
2. **Find glog fatals**:
   ```bash
   ssh $USER@$CVM_IP \
     "grep -ah -n 'F[0-9]\\{8\\}' ~/data/logs/*.out* 2>/dev/null | tail -50"
   ```
   **Important:** Always use `grep -a` (treat binary as text) when
   grepping CVM `.out` / `.INFO` / `.WARNING` / `.ERROR` / `.FATAL`
   log files. These glog files sometimes contain embedded binary data
   that causes `grep` to suppress output. The `-a` flag forces
   text-mode processing.
3. **Prioritize services**: `stargate`, `curator`, `cassandra_monit*`,
   `insights*`, `ergon`, `pithos`, etc., based on grep hits and
   mtimes.
4. If the user **named a specific log**, deep-dive that file first,
   then scan other CVMs for the same signature.

**Deliverable before moving to extract / JIRA search:** A short
**failure summary**:
- Suspected primary failure (service + first line / file:line if
  known)
- **UTC or cluster-time timestamps** and fatal ids
- **Which CVM IPs** show the same pattern
- Which log files to attach or quote in the ticket

---

## Shared: Extract Test-Level Failure, Timeline, and Workload Actions

Not all test failures present as a single service *fatal*. Many
failures are detected by the harness (MonitorUtil / workloads) and are
best explained via the NuTest logs + background jobs. These patterns
apply whenever the NuTest test framework ran the test — typically
available in archived mode; in live mode, available only when the dev
VM that invoked the test is still reachable.

**Primary test logs to consult:**
- `nutest_test.log`: top-level exception, monitor failures (e.g. UVM
  reboot), and the *first* time the harness noticed the issue.
- `steps.log`: high-level timeline with start / end timestamps (use
  this to compute how long the test ran).
- `code_active_state.log`: last active frame + locals (often contains
  the concise failure signature and request metadata).
- `test_exit_details.log`: teardown / shutdown details (usually not
  the root cause, but helpful for cleanup failures).

**Workload / context logs to consult:**
- `background_job_logs/`: what the test was doing *around* the failure
  (VMotion, snapshots, error injection, periodic dumpers, etc.). See
  [investigate-reference.md](investigate-reference.md) — "Background
  Job Activity Timeline" for the timeline build.
- `uvm_logs_*/`: guest-side evidence (reboots, kernel messages,
  filesystem IO issues) when the failure is in a UVM.

**What to extract for the bug report:**
- **Runtime**: compute duration using `steps.log` or first / last
  timestamps.
- **Failure signature**: the exact message from `nutest_test.log` /
  `code_active_state.log` (e.g. `"UVM ... rebooted unexpectedly"`).
- **Correlated actions**: from `background_job_logs/` (e.g. error
  injection active, snapshots being created / deleted, VM
  migrations, node restarts).
- **Precise event time when available**: some failures include epoch
  fields (e.g. `last_uvm_boot`). Convert to UTC and correlate with
  CVM service logs.

**Ops Tracker (Completed / Total Ops):**

When giving the conversational triage summary (not the JIRA report),
also report the final Completed / Total Ops count if present in
`nutest_test.log`. This is useful when the test was run locally or
not synced to TCMS and results need to be entered manually.

Search `nutest_test.log` for lines from `ops_tracker.py` matching:
```
grep "ops_tracker.py.*Current Completed/Total Ops" nutest_test.log | tail -1
```
Example line:
```
2026-03-22 12:30:12,202Z INFO  ops_tracker.py:69 (TT) Current Completed/Total Ops: 38/42
```
Report the **last** occurrence (final count) in the summary as:
`Completed/Total Ops: 38/42`

This is **not** included in the JIRA wiki markup report — only in the
conversational summary to the user.
