# Fatal / Signal Error Extraction

Reference file for `triage-cdp-test-failure`. Mode-agnostic — the procedures
here apply whether you are working from an archived log bundle or a live
cluster. Read this when you need to extract fatals, stack traces, activity
traces, or steps.log test failures from CVM service logs and correlate
them.

For the **input-gathering** side of triage (fetching `errors.json`,
`build_info.yml`, archive URLs, SSH setup, logbay), see
[ingest-reference.md](ingest-reference.md). For the **methodology** side
(keep-asking-why chains, background-job timeline correlation, generic
cross-cutting heuristics), see
[investigate-reference.md](investigate-reference.md).

---

## 1. Fatal Signature Extraction

A fatal signature collapses log-line variance (timestamps, PIDs, specific
values) into a stable identifier suitable for dedup, JIRA search, and
telemetry. Use **file + line + CHECK/assertion text**, not the raw log
line.

```python
# Example: "block_store.cc:718] Check failed: size >= expected"
# Signature: "block_store.cc:718:Check failed: size >= expected"
```

**Grep by log message text and file name, never by source line number**:
product code line numbers can change with every commit. A pattern like
`spdk_nvmf_client.cc:1880` will silently miss the same error in a
different build where the line shifted. Always construct grep patterns
from:

- The **source file name** (e.g., `spdk_nvmf_client.cc`), and
- The **log message text** (e.g., `"Failed to acquire Persistent
  Reservation"`).

Correct: `grep -a "spdk_nvmf_client.cc.*Failed to acquire Persistent Reservation" stargate.out*`
Wrong:   `grep -a "spdk_nvmf_client.cc:1880" stargate.out*`

The `file:line` notation from `errors.json` signatures (e.g.,
`block_store.cc:718`) is fine for locating the *first occurrence* in a
specific log file (context extraction), because you are searching the
same build's logs. But for cross-build searches, JIRA queries,
Sourcegraph lookups, and any grep pattern stored in investigation
flows, always use file name + message text.

---

## 2. Fatal / Signal Error Context Extraction

**URL Pattern (archived)**:
`{base_url}/nos_cluster_logs_*/[cvm_ip]/service_logs/[service].out*`

**Live path**: `~/data/logs/[service].out*` on each CVM.

### Batched extraction (preferred — single command per CVM)

When logs are on a local NFS mount (or you are SSH-ed into a CVM),
combine the surrounding context, stack trace, and activity trace
extractions into a single shell command per CVM rather than making
separate tool calls for each piece. This collapses 3-5 tool calls per
CVM into one.

Build the command dynamically from the error signature and service name
extracted from `errors.json` — the example below shows the structure:

```bash
LOG_DIR="$LOCAL_LOG_PATH/nos_cluster_logs_*/$CVM_IP/service_logs"
SERVICE="stargate"  # from errors.json
FATAL_SIG="block_store.cc:718"  # file:line from errors.json

(
  echo "=== SURROUNDING CONTEXT ==="
  xzgrep -ahn "$FATAL_SIG" "$LOG_DIR/${SERVICE}".out* 2>/dev/null | head -1 \
    | while IFS=: read -r file lineno _rest; do
        sed -n "$((lineno > 50 ? lineno - 50 : 1)),$((lineno + 50))p" "$file"
      done

  echo "=== STACK TRACE ==="
  xzgrep -A 200 "Obtained stack traces of threads responding to SIGPROF" \
    "$LOG_DIR/${SERVICE}".out* 2>/dev/null | head -100

  echo "=== ACTIVITY TRACES ==="
  xzgrep -A 500 "^Live Activity Traces" \
    "$LOG_DIR/${SERVICE}".out* 2>/dev/null | head -200
) 2>/dev/null
```

**Important — use `xzgrep`, not `grep`**: CVM service logs rotate and
get xz-compressed (e.g., `stargate.out.20260312-002450Z.xz`). Plain
`grep` cannot read `.xz` files. `xzgrep` transparently handles both
compressed and uncompressed files.

**Important — always pass `-a` to grep on glog files**: CVM `.out` /
`.INFO` / `.WARNING` / `.ERROR` / `.FATAL` files may contain embedded
binary data that causes grep to suppress output without `-a`. The `-a`
flag forces text-mode processing.

When running over HTTP (no local mount), fall back to individual
fetches for each piece as described in the sub-sections below.

---

## 3. Stack Trace

Look for the `Obtained stack traces of threads responding to SIGPROF`
section. Extract the first thread's stack trace (starts with
`===== thread_name/tid =====`):

```
Obtained stack traces of threads responding to SIGPROF
===== control_1/215378 =====
#0    Object "/usr/local/nutanix/lib/libutil_net.so", at 0x7f682639aec4, in nutanix::net::GetStackTracesOfAllThreads(...)
#1    Object "/usr/local/nutanix/lib/libutil_misc.so", at 0x7f68269c64e3, in nutanix::DumpStackTracesOfAllThreads()
#2    Object "/usr/local/nutanix/lib/libutil_base.so", at 0x7f6823169fb9, in nutanix::DumpStackTracesAndTerminate()
#3    Source "/buildstream/.../glog-0.3.1.bst/src/logging.cc", line 1332, in google::LogMessage::Fail() [0x7f68237f42d8]
#7    Source "/src/bigtop/util/util/block_store/block_store.cc", line 718, in nutanix::block_store::BlockStore::GlobalHeaderReadDone(...) [0x7f6826c70566]
...
```

The stack trace ends at the next `===== thread_name/tid =====` line or
blank line.

---

## 4. Activity Traces

Find the `Live Activity Traces` section (further down in the log):

```
Live Activity Traces
====================
Component: forest
Num live activities: 3
2026/03/12-00:51:42.919381 236.908341 kForestUnhostOp Attributes: op_id=-1557234 ...
           00:51:42.919381    .     0 Start
           00:51:42.919388    .     7 Acquired read id lock
```

**Section markers:**
- Start marker: `Live Activity Traces\n=+`
- End markers: `Collected stack traces from /proc`,
  `Stack traces are generated at`, lines matching `E[0-9]{8}`
- Component sections: `Component: [name]`
- Activity format:
  `YYYY/MM/DD-HH:MM:SS.microsec duration operation Attributes: key=value ...`

---

## 5. Activity Correlation

Activities link via shared identifiers:

- `op_id`: Primary operation identifier
- `scid`: Storage container ID
- `internal_op_id`: Internal operation reference
- `vdisk_id`: Virtual disk identifier

Follow chains by matching these IDs across activities.

**Procedure:**
1. Extract identifiers from the fatal: `op_id`, `vdisk_id`, `scid`,
   `internal_op_id`
2. Search activity traces for matching identifiers
3. Follow activity chains (activities link via shared IDs)
4. Extract all related activity entries

---

## 6. Surrounding Context

Extract ±50 lines around the fatal / signal_error for additional
context. For cores: use the log file from the same service around the
crash time to find the stack trace.

---

## 7. Root Cause Chain Analysis (Dig Deeper)

**Do NOT stop at the first error.** The first fatal or QFATAL you find
is often a *symptom*, not the root cause. You must trace backward
through the causal chain until you reach either an intentional action
(e.g., EI kill) or a genuinely unexplained failure.

### Step 1 — Start from `errors.json`, then filter expected fatals

Begin with the fatals reported in `errors.json` / `errors.txt`. These
are the errors the test harness flagged as significant — the test
framework already filters out known / expected patterns, so what
appears in `errors.json` has already passed that filter.

**QFATALs — general rule of thumb:** QFATALs are typically ignored by
the test framework and will NOT appear in `errors.json`. As a general
rule, if a QFATAL is absent from `errors.json`, it is usually safe to
skip it.

**However**, if you later see a QFATAL signature repeating in a
**crash loop** (same service crashing and restarting with the same or
similar signature dozens of times), that IS worth investigating even
if QFATALs are normally ignored. A single QFATAL is noise; a crash
loop of the same signature means the service cannot recover, which
points to a deeper problem. Trace backward from the crash loop to
find why the service keeps hitting that state.

**Always check `config.json` / `test_config.json`** for
`expected_fatals` or `expected_error_patterns` entries that explicitly
declare certain fatals as acceptable for that test variant. Fatals
matching those patterns are noise — note them and move on to the next
error that is NOT expected.

### Step 2 — Trace the causal chain backward

For each non-expected fatal, ask: *"Why did this service crash?"* Then
check the logs of the service it depends on. Repeat until you reach
the root.

Example chain (from real triage):
```
Surface error:  Curator QFATAL — disk_id mismatch (EXPECTED, skip)
Next error:     Stargate fatal — kBlockStoreError, grove init failed
  Why?          Failed to acquire persistent reservation on bdev
  Why?          Another stargate instance already held the reservation
  Why?          Pithos was unavailable → vdisk controller retried on wrong node
  Why?          Pithos crashed because Cassandra was unavailable
  Why?          EI killed Cassandra at 00:00:42 on CVM .47
  ROOT CAUSE:   Persistent reservation race when pithos goes down during EI
```

Another example (ZK crash loop):
```
Surface error:  zookeeper_monitor QFATAL — "Could not get Zeus session"
  Why?          ZK Java process exiting with status 11 (SIGSEGV)
  Why?          java.io.IOException at FileTxnLog.commit() → force0()
  Why?          External storage disk returned I/O error on fsync
  Why?          NVMe-oF device paths disappeared at 14:44:03
  ROOT CAUSE:   External storage array had 26-second connectivity disruption
```

### Step 3 — Check upstream / downstream services around the failure

For each fatal, check the logs of related services within ±2 minutes of
the failure. Use the service dependency map and flow directory in
[failure-patterns-reference.md](failure-patterns-reference.md) to know
which services to check, then read the relevant flow file from `flows/`
for detailed triage steps.

**Batched cross-service scan (preferred — single command per CVM):**

When logs are on a local NFS mount, scan all services on a CVM in one
command. **Be selective** — grep only the active (uncompressed) `.out`
files around the failure timestamp rather than all rotated logs, since
scanning every compressed rotation across all CVMs simultaneously can be
very slow.

```bash
LOG_BASE="$LOCAL_LOG_PATH/nos_cluster_logs_*"
TIMESTAMP_PREFIX="YYYYMMDD HH:MM"  # adjust to failure time

for cvm_dir in $LOG_BASE/*/service_logs; do
  cvm_ip=$(basename $(dirname "$cvm_dir"))
  echo "=== CVM: $cvm_ip ==="
  # Start with uncompressed .out files (active logs — fast):
  grep -ah "F[0-9]\{8\}" "$cvm_dir"/{stargate,curator,cassandra_monitor,pithos,cerebro,zookeeper_monitor,hades,genesis}.out 2>/dev/null \
    | sort | grep "$TIMESTAMP_PREFIX"
  # If the failure timestamp falls in a rotated log, use xzgrep on the
  # specific rotation file identified from errors.json timestamps:
  # xzgrep -ah "F[0-9]\{8\}" "$cvm_dir/stargate.out.20260312-002450Z.xz" | grep "$TIMESTAMP_PREFIX"
done
```

**Notes:**
- The `-a` flag is essential — CVM `.out` files may contain embedded
  binary data that causes grep to suppress output without it.
- Use `xzgrep` (not `grep`) when searching compressed `.xz` rotated
  logs. Plain `grep` cannot read xz-compressed files.
- Avoid grepping all `.out*` (including compressed rotations) across
  all CVMs in one invocation — this can take a very long time. Target
  the specific rotation files relevant to the failure timestamp.

For archived logs over HTTP (no local mount), fetch the service log
index from `{base_url}/nos_cluster_logs_*/[cvm_ip]/service_logs/` and
check `.out` files for services in the dependency chain.

### Step 4 — Correlate with EI / background job timeline

Cross-reference the causal chain with the background-job activity
timeline (see [investigate-reference.md](investigate-reference.md) —
**Background Job Activity Timeline**). For each link in the chain,
check:

- Was the upstream service intentionally killed by EI at that time?
- Was a snapshot / clone / migration happening that could trigger the
  code path?
- Was a node power cycle in progress?

If an EI kill explains a link in the chain, note it (e.g., "Cassandra
was killed by EI at 00:00:42, causing pithos unavailability"). The
*interesting* failure is whatever happened that was NOT explained by
an intentional action.

### Step 5 — Determine primary vs. cascading failures

When multiple fatals appear across CVMs, determine which is primary:

- **Check EI targets**: If EI was killing stargate on CVM A at the
  failure time, then fatals on CVM A are expected consequences of EI.
  Fatals on CVMs B / C that were NOT EI targets are the interesting
  ones — they indicate a product bug triggered by the disruption.
- **Check timestamps**: The earliest non-EI-related fatal is usually
  primary. Later fatals on other nodes are likely cascading failures.
- **Check crash loops**: If a service on one CVM enters a crash loop
  (same fatal repeating every 30-90s), that node's repeated fatals are
  all the same issue. Focus on what caused the *first* instance.

See [failure-patterns-reference.md](failure-patterns-reference.md) —
**Primary vs. Cascading Failure Identification** for the report table
format.

**Deliverable**: In the JIRA report's Failure Summary section, describe
the full causal chain — not just the surface-level error. State which
errors are expected / noise, which are cascading, and what the actual
root cause is.

### Step 6 — Verify every link before writing the chain

Before publishing a causal chain (in chat or in the JIRA report), audit
each `Why?` step against the **Reporting Discipline** in `SKILL.md`:

- For every "A → caused → B" link, you must be able to point to one of:
  a shared ID across both events (op_id, vdisk_id, request_id, sd_id),
  a documented dependency from a `flows/` file, a code-level call path
  you read in this triage, or adjacent timestamps + an explicit log
  message naming the upstream service.
- If a link rests only on **timing correlation** with no shared ID and
  no dependency reference, mark it as inferred ("appears to", "is
  consistent with") and note what would confirm it.
- If a link cannot be supported at all from the available logs, **stop
  the chain at the last verified step** and label the gap explicitly:
  "Beyond this point the logs do not show why X happened — possible
  upstream causes are A, B, or C; needs verification."

A short, honest chain with a labeled gap is correct triage. A long,
fully-asserted chain where some links are guesses is not — even if the
guesses turn out to be right, the user cannot tell which links to
trust.

---

## 8. Integrity Tester / Test Failures from steps.log

**Archived URL**: `{base_url}/steps.log`,
`{base_url}/non_corruption_errors.json` (if present)

**Live path**: `~/data/logs/steps.log` on the CVM that ran the test.

1. Fetch `steps.log`; grep
   `IntegrityTester|Non-Corruption errors found|Stacktrace check|worker_pool\.cc|Input/output error|Workload failed on|mismatch|corruption|AssertionError`
2. If present, fetch `non_corruption_errors.json` — has `stacktraces`
   (thread → device → fatal) and `corruptions`.
3. **Deduplicate by signature** (file:line + error type). Ignore device
   / offset when grouping; keep thread, timestamp for timeline.
4. **Report**: For each unique IO Integrity issue (by signature), use
   a `{code}` block with Time, VM, Disk columns. Pad Time to 19 chars.
   One example per type + timeline table. Check `test_exit_details.log`
   for failure reason.

---

## Quick-Reference Extraction Patterns

```bash
# Stack trace: find the marker, then extract the first thread block
grep -n "Obtained stack traces of threads responding to SIGPROF" <logfile>
# From that line, extract until the next ===== thread block or blank line

# Activity traces: find section, extract until end markers
grep -n "Live Activity Traces" <logfile>
# Section ends at "Collected stack traces" or lines matching E[0-9]{8}

# Correlated activities: search by op_id, vdisk_id, scid, grove ID
grep -B 2 -A 30 "op_id=<ID>" <logfile>
grep -A 50 "<grove_or_vdisk_id>" <logfile>
```

See sections 3-5 above for full extraction procedures.
