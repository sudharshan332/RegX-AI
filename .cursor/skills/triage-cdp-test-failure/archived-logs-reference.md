# Archived Logs Mode — Workflow Summary

Reference file for `triage-cdp-test-failure`. Read this when the triage
mode is **Archived Logs** (user provides a log URL like
`http://10.41.24.49/logs/.../test_name/`).

This file captures the archived-logs-specific orchestration: the
numbered workflow sequence and the scavenger / `filesv3` archive
discovery that only applies to this mode. The actual extraction,
investigation, and reporting procedures live in the phase-based
reference files.

---

## Workflow Sequence

| Step | What | Reference |
|------|------|-----------|
| 1 | Fetch `errors.json`, dedupe fatals, fetch build_info, extract test-level failure | [ingest-reference.md](ingest-reference.md) § "Archived Logs Mode" + "Shared" |
| 2 | Per-fatal context: stack traces, activity traces, correlation, ±50 lines context | [extract-reference.md](extract-reference.md) § 2-6 |
| 3 | Root-cause chain analysis (dig deeper, filter expected fatals, upstream / downstream scan) | [extract-reference.md](extract-reference.md) § 7 |
| 3b | Validation-failure "keep asking why" (when there is no service fatal) | [investigate-reference.md](investigate-reference.md) — "Investigate Test Validation Failures" |
| 4 | `steps.log` / IntegrityTester signal extraction | [extract-reference.md](extract-reference.md) § 8 |
| 5 | Background-job timeline (EI, snapshot, VMotion, power cycle) | [investigate-reference.md](investigate-reference.md) — "Background Job Activity Timeline" |
| 6 | Generic cross-cutting heuristics (greenlet death, ECONNRESET ↔ peer FATAL, UI / zeus divergence) | [investigate-reference.md](investigate-reference.md) — "Generic Cross-Cutting Patterns" |
| 7 | JIRA duplicate search | [jira-reference.md](jira-reference.md) — **Searching JIRA for Similar Issues** |
| 8 | Generate JIRA wiki report (mandatory) | [report-template-reference.md](report-template-reference.md) |
| 8b | Optionally create JIRA ticket | [jira-reference.md](jira-reference.md) — **Creating a New JIRA Ticket** |
| 9 | Discover archived CVM logs (when test had `archive_logs: True`) | § 1 below — archived-mode specific |
| 10 | Log telemetry | [telemetry-reference.md](telemetry-reference.md) |

Search JIRA and generate the report only **after** you have parsed
`errors.json`, deduplicated fatals, extracted stack trace / activity
trace, and captured build + cluster config.

---

## 1. Discover and Access Archived CVM Logs

Long-running tests (those with `archive_logs: True` in `test_args`)
configure the CVM **scavenger** service to continuously archive
service logs (including binary logs) to an NFS filer during the test
run. These archived logs are essential for triage — they contain the
full history of service logs that may have been rotated out of
`~/data/logs/` on the CVM by the time the test ends.

### 1a. Check if the test has archival enabled

In `nutest_test.log`, check the test parameters near the top of the
file:
```
grep "'archive_logs': True" nutest_test.log
```
If present, the test configured log archival. Also look for:
```
grep "Setting up log archival\|_configure_log_archival" nutest_test.log
```

### 1b. Extract the archive directory name from nutest_test.log

The archival setup creates a unique directory on the NFS filer with
the format `DDMMYY-HHMMSS_RANDOM6` (e.g., `310326-200941_41AA90`).
Extract it with any of these patterns:

```bash
grep "Archival url for SVM\|Using NAS server\|archive_url.*local://" \
  nutest_test.log | head -5
```

**Key log lines to look for:**
- `configurator.py: Using NAS server: filesv3.cdp.nutanix.com:/volume1/<dir_name>`
- `configurator.py: Archival url for SVM <ip>: local:///mnt/archive/<dir_name>`
- Scavenger gflag: `--archive_url=local:///mnt/archive/<dir_name>`

The `<dir_name>` portion (e.g., `310326-200941_41AA90`) is what you
need.

### 1c. Access archived logs from the dev VM

The archive NFS filer `filesv3.cdp.nutanix.com:/volume1` is typically
mounted at `/mnt/filesv3` on the dev VM. The archived logs directory
is at:

```
/mnt/filesv3/<dir_name>/
```

For example: `/mnt/filesv3/310326-200941_41AA90/`

**Structure inside the archive directory:**
Each CVM IP has a subdirectory containing the archived service logs:
```
/mnt/filesv3/<dir_name>/
  <cvm_ip_1>/
    stargate.out.YYYYMMDD-HHMMSSZ.xz
    curator.ntnx-*.log.INFO.YYYYMMDD-*.xz
    binary_logs/
    ...
  <cvm_ip_2>/
    ...
```

**If the filer is not mounted**, see the "Mounting the filesv3 Filer"
section in `SKILL.md` → Fetching Logs.

### 1d. After shrek backup — finding the renamed archive

When logs are backed up to shrek (ticket has `backed_up_to_shrek`
label), the backup automation:

1. **Renames** the archive directory from `<dir_name>` to
   `corruptions_<ENG-XXXXXX>_<dir_name>` on the filer.
2. **Posts a JIRA comment** with the archive path. The comment format
   is:
   ```
   AUTOMATION: Completed backup of log idx 0 to http://shrek-v2.eng.nutanix.com/JITALOGS/<ENG-XXXXXX>/0

   To get log CLI access, 'nssh shrek-v2' and go to /jita/www/html/JITALOGS/<ENG-XXXXXX>

   If logs are missing, make sure to check the archive!
     To access archive, 'nssh shrek-v2' and go to:   /mnt/filesv3/corruptions_<ENG-XXXXXX>_<dir_name>
   ```

So after backup, the archive is at:
```
/mnt/filesv3/corruptions_<ENG-XXXXXX>_<dir_name>/
```
For example:
`/mnt/filesv3/corruptions_ENG-910282_310326-200941_41AA90/`

### 1e. Triage workflow for archived logs

When triaging with archived logs available:

1. **Check `archive_logs` in test params** — if `True`, log archival
   was configured.
2. **Extract `<dir_name>`** from `nutest_test.log` (see 1b).
3. **Check if the original directory exists**:
   ```bash
   ls -d /mnt/filesv3/<dir_name> 2>/dev/null
   ```
4. **If not found, check for the renamed (backed up) version**:
   ```bash
   ls -d /mnt/filesv3/corruptions_*_<dir_name> 2>/dev/null
   ```
5. **If a JIRA ticket exists**, check its comments for the automation
   comment that contains the explicit archive path.
6. **Use archived logs for deeper investigation** — they contain the
   complete log history including rotated logs, binary logs, and logs
   that may have been overwritten during the test run. This is
   especially important for long-running tests where many log
   rotations occur.

**Important**: Archived logs supplement (not replace) the Jita test
logs. The Jita logs contain the NuTest framework logs
(`nutest_test.log`, `steps.log`, `background_job_logs/`, etc.) plus a
snapshot of CVM logs collected at test end. The archived logs contain
the **continuous** CVM log stream throughout the entire test run.
