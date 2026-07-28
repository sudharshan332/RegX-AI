# Investigation Methodology

Reference file for `triage-cdp-test-failure`. Mode-agnostic — applies
whether you are working from an archived log bundle or a live cluster.
Read this when you have extracted raw fatals / stack traces / activity
traces (see [extract-reference.md](extract-reference.md)) and now need
to reason about *why* the product behaved the way it did.

This file covers three independent investigation tools (they are not
sequential — apply whichever is relevant):

- **Investigate Test Validation Failures** — keep-asking-why when
  there is no service fatal.
- **Background Job Activity Timeline** — correlating EI / snapshot /
  migration events with failures.
- **Generic Cross-Cutting Patterns** — greenlet death, ECONNRESET ↔
  peer FATAL, UI / zeus classification divergence.

For subsystem-specific investigation flows (stargate, curator,
genesis, ...), see
[failure-patterns-reference.md](failure-patterns-reference.md) and the
`flows/` directory.

---

## Investigate Test Validation Failures (Keep Asking Why)

Not every test failure presents as a service fatal. Many failures come
from **test validation steps** — assertions in the test harness or
workflow code that detect unexpected product state. When you encounter
one of these, do NOT stop at the surface assertion and classify it as
a "test bug." Instead, apply the same backward causal chain analysis
from [extract-reference.md](extract-reference.md) § 7 to understand
*why* the product state was wrong.

**The pattern to follow:**

```
Surface:    Test assertion failed (e.g., CHECK_EQ, find returned empty)
  Ask:      Why did this check fail? What was the actual vs expected state?
  Ask:      Why was the product in that state? (Check service health, mounts,
            processes, cluster events around that time)
  Ask:      What caused the product to enter that state? (Check for upgrades,
            restarts, EI kills, service crashes, provisioning steps)
  Ask:      Was the cause intentional (EI, test action) or a product defect?
```

**Stop only when you reach one of these endpoints:**
- An **intentional test action** that explains the state (EI kill, etc.)
  AND the product should have recovered but didn't → **product bug**
  (recovery failure).
- An **intentional test action** that explains the state AND the product
  recovered correctly but the test checked too early → **test timing
  bug**.
- A **product lifecycle gap** (service not restarted, mount not
  restored, config not persisted) → **product bug**.
- A **test assertion that is genuinely wrong** (checking the wrong
  thing, wrong path, wrong expected value) → **test bug**.

**Concrete example — aesdb validation failure on blockstore cluster:**

```
Surface:    verify_aesdb_path CHECK_EQ failed — find returned empty for
            some SSD mount paths.
  Why?      The find command ran correctly but the disk mount path had no
            aesdb_* directory.
  Why?      Those specific disks are FUSE-mounted by xmount (blockstore).
            The FUSE mount was stale — xmount was not running.
  Why?      xmount was killed during a NOS rolling upgrade (the finish
            script explicitly stops xmount). After CVM reboot, genesis
            restarted all managed services but xmount is NOT in genesis's
            service list.
  Why?      xmount is started by service_monitor (not genesis). After the
            upgrade killed service_monitor + xmount, neither was relaunched.
  Endpoint: Product lifecycle gap — xmount not restarted after upgrade.
            This is a PRODUCT BUG, not a test bug.
```

**Key investigation techniques for validation failures:**

1. **Understand what the validation actually checks.** Read the source
   code of the failing function. In the example above,
   `verify_aesdb_path` runs `find <disk_mount_path> -name 'aesdb_*'`
   via SSH on each CVM.

2. **Check whether the find / query ran correctly.** Look at the SSH
   stdout in `nutest_test.log`. Did it return empty, return an error,
   or timeout? An empty result is different from a connection failure.

3. **Determine the scope of the failure.** Did ALL disks fail, or only
   some? If only some, find the distinguishing characteristic (e.g.,
   blockstore-managed vs raw-mounted, specific CVM, specific disk
   tier).

4. **Check the infrastructure behind the validation target:**
   - For disk mount paths: Is the mount active? (`mountpoint -q`,
     check `/proc/mounts`, check xmount / FUSE status)
   - For service queries: Is the queried service running?
     (`genesis status`)
   - For API calls: Is the endpoint reachable? Check service logs
     around the validation timestamp.

5. **Check for cluster lifecycle events** in the time window before
   the validation: NOS upgrades (`finish.out`, genesis rolling
   restart), service crashes, EI kills, node reboots. These can leave
   services or mounts in a broken state that the test later discovers.

6. **When you identify a product state problem (service not running,
   mount stale, config missing), trace WHY the state is wrong.** This
   is where you may need to read product source code (genesis service
   definitions, upgrade scripts, service_monitor configs) to determine
   whether the state gap is a known limitation or a bug. If the causal
   chain reaches into product code, proceed to the Sourcegraph
   Deep-Dive (Step 5 in `SKILL.md`) — this is exactly the "unexplained
   failure" criterion that triggers an auto-dive.

**How to distinguish product bug from test bug:**

| Signal | Likely product bug | Likely test bug |
|--------|-------------------|-----------------|
| Product service / process not running when it should be | yes | |
| FUSE mount stale after cluster lifecycle event | yes | |
| Service killed by upgrade / EI and not recovered | yes | |
| Test checks state too early (before recovery completes) | | yes |
| Test assertion uses wrong path or wrong expected value | | yes |
| Test doesn't account for blockstore vs raw disk difference | | yes |
| Test runs on cluster where prerequisite was never met | | yes (setup bug) |

**CRITICAL**: Do not classify a failure as a "test bug" merely because
the failing code is in the test framework or workflow code. The test
may be correctly detecting a real product deficiency. Always investigate
the underlying product state before making the disposition.

---

## Background Job Activity Timeline

**When**: A log URL is available (archived mode), OR background-job
logs exist on the CVM that ran the test.

**Path**: `{base_url}/background_job_logs/` (archived) or
`~/data/logs/background_job_logs/` (live, on the test CVM).

### a. Identify which background jobs to review

List `background_job_logs/` and categorize every `*FULL.log`:

**Action-oriented jobs — ALWAYS review these** (they change cluster
state and can correlate with failures):
- `ErrorInjectionManager` / `MixedErrorInjection` — component kills,
  burst kills
- `Snapshot_Process_Manager` — snapshot create / delete / restore /
  clone
- `VMotion` — VM live migration
- `Node_Power_Cycle` / `SVM_Power_Cycle` — node / CVM power cycling
- `Network_Partition` / `Network_Blocking` — network fault injection
- `IntegrityTesterShellWorkload` — IO workload run / verify status
- Any other job that *mutates* cluster state (disk removal, node
  removal, etc.)

**Information-gathering jobs — SKIP these** (they only collect stats /
info and do not affect cluster state). Use **pattern matching**, not
exact names — the list below gives known examples, but any job
matching these patterns is safe to skip:
- `*StatsCollector` — e.g. `ScanStatsCollector`,
  `ClusterStatsCollector`, `ChronosStatsCollector` (any name ending
  in `StatsCollector`)
- `*EventsCollector` — e.g. `ClusterEventsCollector`
- `Dump*Stats` — e.g. `DumpStargateHtmlStats`
- `Get*Info` — e.g. `GetLeadersInfo`
- `Periodic*Dumper` — e.g. `PeriodicCmdDumper`,
  `PeriodicTimeDiffDumper`

**IMPORTANT — do NOT over-filter on single keywords like "Stats".**
Some legitimate test workflows contain the word "Stats" but are
action-oriented (e.g. `Logical_Stats` is a real workload that
exercises the data path). The skip patterns above are *compound*
patterns (prefix + suffix) that reliably identify passive collectors.

**Handling unfamiliar job names (default: review):**

When a job name does not match any known action-oriented or skip
pattern, **default to reviewing it** — it is safer to scan a passive
job than to miss a state-mutating one. To quickly classify:
1. Check the `*FULL.log` header for the class path / import — if it
   comes from a stats / collector / dumper module, it is safe to skip.
2. If the job name suggests an action verb (create, delete, migrate,
   inject, kill, cycle, block, resize, clone, restore, failover,
   etc.), treat it as action-oriented.
3. If still unclear after a quick header check, include it in the
   timeline — a few extra lines in the timeline are better than
   missing a correlated action.

### b. Extract Error Injection events

Grep **all** action-oriented `*FULL.log` files in a single command
rather than running separate greps per file. This collapses N tool
calls (one per background job) into a single call.

**EI Grep** (run once across all action-oriented FULL logs):
```
grep -E "Killing Component|Killing component|Killing .* on VM|using pkill|Aborting|Starting killing|Killing component.*once|Killing component.*burst|Killing component.*burst mode|Killing components|Completed slaughtering|Crashing .* services|Delaying .* killing|Selecting random node|Based on kill master|Killing Zookeeper|Killing Hades|Restarting Genesis|Restarting .* on|Restarting .* to start|Stopping hades|Starting hades|Stopping stargate|Starting stargate|Stopping component|Stopping error injection|Shutting down|Taking down|Keep .* down|Power cycling|Powering off|Powering on|Power OFF|Power ON|Powering Node|Powering off hypervisor|Powering on hypervisor|Triggering kernel panic|Triggering system crash|Rebooting NOS VM|Successfully power cycled|Successfully finished node power cycle|Powered off svm|Blocking IPs|Blocking .* data IPs|Blocking all .* management IPs|Successfully blocked|Unblocking IPs|Unblocking targets|Successfully unblocked|In Network Partition|Duration completed|Starting .* Network blocking|Stopping .* Network blocking|modify_firewall -b|modify_firewall -u|Network blocking iteration|Injecting the following errors|Bringing down interface|Bringing up interface|SIGTERM|Force Terminate|kill -9|Terminating|tearing down|Marking Disk|Removing Disk|Adding Disk|Removing Node|Adding Node|Starting Egroup|Starting episodes|Crash SVM|Choosing new random SVM to kill|Starting EI scenario|Finished EI scenario|Start .*_EI::|END .*_EI::|Finished mixed error injection|Running these scenarios|Starting SVM power cycle job|Performing SVM power cycle|Node power cycle iteration|Power cycling SVM|Blocking KMS IP|Unblocking KMS IP" *.log
```

### c. Extract Snapshot Process Manager events

Grep `Snapshot_Process_Manager_FULL.log` (if present) for snapshot
lifecycle actions within ±10 min of each fatal / core / SIGSEGV, and
include a summary of the overall cadence:
```
grep -E "STEP|Creating snapshot|Deleting snapshot|Restoring snapshot|Cloning|protect_entities|snapshot_interval|SnapshotProcess|ERROR|FAIL|exception|CHECK failed" Snapshot_Process_Manager_FULL.log
```

### d. Extract VMotion / VM Migration events

Grep `VMotion_FULL.log` (if present) for migration actions within ±10
min of each fatal / core / SIGSEGV, and summarize overall migration
activity:
```
grep -E "STEP|Migrating VM|migrate|VMotion|migration.*complete|migration.*fail|ERROR|Moving VM|Live migrat" VMotion_FULL.log
```

### e. Extract Node / SVM Power Cycle events

If `Node_Power_Cycle_FULL.log` or similar exists, grep for power-cycle
iterations and correlate with failure times.

### f. Build the combined timeline

Merge events from *all* action-oriented background jobs into a single
chronological timeline. Per line: **StartTime** = timestamp;
**EndTime** = paired event when possible (else `-`); **Source** =
background job name; **Component** = exact message.

**When too many events**: Include all events within ±5–10 min of each
fatal / core / SIGSEGV for correlation. For distant events, summarize
cadence (e.g. "VMotion migrated VMs every ~360s throughout the
test"). Never omit events around failure times.

Output in `{code}` block: columns StartTime, EndTime, Source,
Component.

*Pattern refs*: `workflows/error_injection/`, `workflows/network/`,
`workflows/cdp/io_integrity/`,
`workflows/cdp/common/background_jobs/mixed_ei/`,
`workflows/cdp/stargate/*power_cycle*`,
`workflows/cdp/cassandra_medusa/error_injection/`,
`workflows/cdp/common/background_jobs/vm_migrate.py`,
`workflows/cdp/snapshot/`

---

## Generic Cross-Cutting Patterns

These heuristics are not tied to any single subsystem flow. They apply
whenever the triage is tracing a chain across Python / greenlet-based
services, config publishers, or UI-reported product state that
disagrees with zeus / IDF. Check these early — they frequently
short-circuit a long chain search.

### Fire-and-forget greenlet exception handling divergence

Many management-plane Python loops (e.g.
`publish_genesis_config_to_idf`, ergon task loops, periodic sync
workers) are started as greenlets and rely on `(ret, err)` return
values for retry logic. If a callee raises a Python **exception**
rather than returning `(False, err)`, the retry loop is bypassed
entirely and the greenlet dies silently. The parent service keeps
running, so `genesis status` / `service status` look healthy, but the
feature that greenlet was driving (attribute publish, stats sync,
alert dispatch) never runs again for the life of that process.

**How to spot it:**
- Search `genesis.out*` (or the relevant service's `.out*` file) for
  `Greenlet at 0x... failed with <ExceptionType>` followed by a
  Python traceback. That marker alone confirms a publisher died.
- Grep the service log for the *last* successful operation the
  greenlet performed, then note the gap until the restart — the
  absence of the expected periodic log lines (e.g.
  `Successfully published <attr>`, `Successfully synced Genesis
  config to IDF`) is the primary symptom.
- Read the caller's retry loop (`grep -n "while True" ...`). If the
  loop only handles `(ret, err)` return values and has no bare
  `except Exception`, it is vulnerable to this pattern.

**Defensive wrapping pattern (code review / fix proposal):**

```python
while True:
  try:
    ret, err = do_work()
    if ret:
      break
    log.ERROR("do_work returned err=%s; retrying" % err)
  except Exception as exc:
    log.ERROR("do_work raised %r; retrying" % exc)
  time.sleep(30)
```

### ConnectionResetError ↔ peer service FATAL pairing

A Python client raising
`ConnectionResetError: [Errno 104] Connection reset by peer` almost
always means the peer process crashed mid-RPC. Before chasing the
client side, check the peer service's `.FATAL` and `.INFO` logs in
the ±60s window around the reset:

```bash
# Client saw ECONNRESET at 20:40:53
xzgrep -l "F[0-9]\{8\}" <peer_cvm_log_dir>/<peer_service>.FATAL* 2>/dev/null
xzgrep "init_nutanix.cc.*Started child\|Number of unclean restarts" \
  <peer_cvm_log_dir>/<peer_service>.INFO* 2>/dev/null
```

If the peer service has a FATAL timestamped a few seconds before the
client's reset and an unclean restart counter > 0, the client side is
almost certainly a symptom — the root cause is why the peer crashed.
Common triggers: malformed RPC payload that trips a server-side
DCHECK, protobuf decoding failures, OOM, or an assertion in a
callback.

Note: when the peer is an Arithmos / IDF / Stats process, a DCHECK on
the payload (e.g. missing required fields in a `GenericAttribute`) is
the usual culprit rather than a logic bug — check
`ntnxdb_client/stats/arithmos/base/source_converter.cc` and similar
validators.

### UI / API vs. zeus classification divergence

When PE / PC UI (or the `v1/cluster` / `v2/cluster` REST response)
reports a different cluster classification than zeus indicates, the
UI is almost never reading zeus directly. Prism-side code typically
reads from IDF / Arithmos generic attributes via PrismGateway, and
defaults null / missing values to the most common class (usually
HYPER_CONVERGED). The causal chain is:

```
UI classification wrong
  └─► v1/cluster (PrismGateway) response has null / missing field
        └─► Arithmos generic_attribute_list is missing that attribute
              └─► genesis publisher greenlet failed to publish it
                    └─► (root cause — see greenlet pattern above)
```

**Triage pattern:**

```bash
# Confirm UI-reported value vs PrismGateway vs Arithmos vs zeus
curl -k -u admin:... https://<pe_ip>:9440/PrismGateway/services/rest/v1/cluster \
  | jq '.clusterType, .externalStorageProviderInfo'

ssh nutanix@<cvm> "arithmos_cli master_get_entities entity_type=cluster" \
  | grep -E "attribute_name|cluster_type|ncc_version|external_storage"

ssh nutanix@<cvm> "zeus_config_printer" | grep -E \
  "cluster_functions|cluster_type|provisioned_from_host_boot_disk"
```

If zeus state is correct but Arithmos is missing the attribute, the
problem is NOT cluster state — it is the genesis → Arithmos publish
chain. Start by grepping the genesis leader's log for
`publish_genesis_config_to_idf`, `sync_config_to_idf`, and
`Successfully published <attr>` lines. Absence of the expected
publishes (or a greenlet death trace) explains the divergence.
