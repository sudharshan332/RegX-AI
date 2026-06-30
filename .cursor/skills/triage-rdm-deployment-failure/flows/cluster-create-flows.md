# Cluster Create Flows

Investigation flows for failures during the `cluster create` phase.
These patterns share genesis, node_manager, and CVM service startup
as their common subsystems.

---

## 1. Cluster Create — Node Lock Timeout

**Signature in logs:**
```
CRITICAL ... RPC to acquire node lock on SVM <ip> timed out
```
followed by:
```
Failed to create cluster... retrying in 60 seconds.
Attempts to create cluster failed.
```

**Root cause:** Genesis on one or more CVMs is not responsive. The
`cluster create` workflow polls `sm_lock_nodes` state and times out
after ~3 minutes.

**Investigation steps:**
1. Identify which CVM IP timed out from the `CRITICAL` message.
2. Check entity logs for that CVM: look in
   `entity_logs/retry_<n>/<cluster>/svm_log_<ip>/` or the logbay
   bundle for genesis.out.
3. Look for genesis crash, OOM, or connectivity issues.
4. Check if the CVM was reachable (the deployment log often shows
   nmap port scans before cluster create — verify all nodes show
   `22/tcp open ssh`).
5. Check which service is stuck: `grep "Starting ... service"
   genesis*` in entity logs.
6. Check for Cassandra/disk issues: `grep -m5 "No metadata disks on
   the local node" cassandra_monitor.*` — if found, file on Hades.

**Common sub-causes:**
- Genesis crash/restart loop on the CVM
- CVM ran out of memory during early startup
- Network partition between CVMs
- Base cluster host resource exhaustion affecting CVM performance
- Cassandra not starting due to disk issues (file on Hades)

**Base cluster investigation (Nested AHV 2.0 — Step 5b runs by
default for this pattern):**

This pattern triggers the Step 5b diagnostic-value gate (the
literal error mentions "node lock timeout"; cluster never reached
a healthy steady state). See
[base-cluster-diagnostics-reference.md](../base-cluster-diagnostics-reference.md)
for the full procedure. Key points for this failure pattern:
1. Start the sar window ~10 minutes **before** the cluster create
   failure — resource contention during genesis startup can cause a
   genesis hang that persists even after the host settles down. The
   causal window is often earlier than the `sm_lock_nodes` timeout.
2. Check all four resource dimensions: CPU (`sar -u`), memory
   (`sar -r`), load (`sar -q`), disk I/O (`sar -dp`), network
   throughput (`sar -n DEV`), and network errors (`sar -n EDEV`).
3. Check `dmesg -T | grep -i oom` for OOM kills on the host.
4. If multiple failed nodes were on the same base cluster, host-level
   resource exhaustion is the likely contributing factor.

## 2. Cluster Create — Genesis Not Running

**Signature in logs:**
```
Failed to reach Genesis on the node <ip> with ret: RPCError:
Client transport error: httplib send exception
```
```
socket.timeout: timed out
```

**Root cause:** Genesis service is not running or not reachable on
one or more CVMs during cluster creation.

**Investigation steps:**
1. Check if CVM is pingable/SSHable from deployment logs.
2. Look at genesis.out in entity logs for crash/startup issues.
3. Check if AOS imaging completed successfully on all CVMs.
4. Find the stuck service:
   `grep "Fix the problem and start again" genesis.out`
5. Check service startup sequence:
   `zgrep "Starting ... service" genesis*`
6. For nested deployments: this pattern triggers the Step 5b
   diagnostic-value gate ("genesis not reachable" overlaps with
   host-pressure symptoms). Run base-cluster diagnostics (CPU,
   memory, disk I/O, network, OOM) to check if host contention
   slowed genesis startup.

## 3. Cluster Create — Timeout on ACLI/Command

**Signature in logs:**
```
Timedout executing command source /etc/profile; for i in {1..10};
do echo 'yes'; done | cluster ... create in 900 secs with error:
timeout()
```

**Root cause:** Cluster creation command itself timed out. This is a
different pattern from the node lock timeout — the entire command
exceeded its timeout.

**Investigation:** Contact Infra team; provide genesis logs from
entity logs.

---

## 4. Post-Cluster-Create — NOSCluster Instantiation Fails (Acropolis Disconnected)

**RDM failure_analysis signature:**
```
category: PRODUCT
error_metadata.RDM:
  source: PLUGIN::NESTED_AHV
  reason:  NESTED_CLUSTER
message: "Failed to create cluster on the nested SVMs. ...
          'Unable to instantiate the NOSCluster object with cluster
          name. Please check the Prism API responses in the log'"
resolution: "Please check whether Nested AHV and CVM builds are
             compatible"
```

**Stage signature:** Deployment reaches `INSTANTIATE_NOS_CLUSTER`
then transitions to `COPYING_PE_LOGS` → `FAILED`. All earlier
stages (`Cluster creation`, `Cluster_Parameters_Setup`, `UPDATE
DB`) succeeded — the `cluster create` command itself did not fail.

**Deployer log signature:**
```
ERROR nos_metadata_helper.py:640  Failed while transforming nested
                                  cluster metadata.
ERROR nested_ahv_2.py:1102  Traceback (most recent call last):
   ... InvalidValueError: Failed while fetching valid value for
       'memory_capacity_in_bytes'
ERROR nested_ahv_2.py:1130  Failed to create Nested cluster
   {... 'reason': 'NESTED_CLUSTER',
        'source': 'PLUGIN::NESTED_AHV' ...}
```

**Prism `/PrismGateway/services/rest/v2.0/hosts` signature** (every
host in the freshly created cluster):
```
acropolis_connection_state: 'kDisconnected'
hypervisor_state:           'kAcropolisNormal'
state:                      'NORMAL'
metadata_store_status:      'kNormalMode'  (or kDataDeletedNowInPreLimbo)
memory_capacity_in_bytes:   None
num_cpu_cores / num_cpu_threads / num_cpu_sockets: None
cpu_capacity_in_hz / cpu_frequency_in_hz:          None
hypervisor_full_name / num_vms / boot_time_in_usecs: None
```

**Root cause:** The `cluster create` command succeeded — Cassandra
ring formed, every node is `state: NORMAL`. But the AHV-side
`acropolis` service has not yet connected to the cluster manager
when `nutest`'s `NOSCluster.__init__` issues its first
`/v2.0/hosts` poll. Prism returns the host records with
`acropolis_connection_state: kDisconnected` and the
hypervisor-derived capacity fields populated as `None`. The
framework's `nos_metadata_helper._fetch_hosts_data` strict-
validates `memory_capacity_in_bytes` and raises
`InvalidValueError`, which the `nested_ahv_2` plugin re-wraps as
`PLUGIN::NESTED_AHV / NESTED_CLUSTER`.

This is a **product issue amplified by a framework strict-check.**
The product side (acropolis on the nested AHV image not connecting
within the framework's first poll window) is the actual root
cause — but the framework's intolerance of `None` capacity fields
is what turns a transient warmup delay into a hard FAIL.

**Common sub-causes:**
- AHV image (e.g., `installed-nestedahv-X.Y-NNN.qcow2`) and AOS
  build are not compatible; acropolis fails to register with the
  cluster manager. The RDM resolution string flags this directly
  ("Nested AHV and CVM builds are compatible").
- Acropolis on the nested hosts is genuinely crashed/hung. Check
  `acropolis.out` and `acropolis.FATAL` in the AHV host log
  tarballs (`nested_host_log_<ip>/var_log.tar.gz`) and any CVM
  logbay bundle (`logbay_<cvm_ip>_<ts>.zip`).
- Acropolis just needs more time. Poll
  `/PrismGateway/services/rest/v2.0/hosts` manually a few minutes
  later to see whether `acropolis_connection_state` flips to
  `kConnected` and the capacity fields populate. If yes, the
  symptom is a framework-poll-too-early bug, not a product bug.

**Investigation steps:**

1. Confirm the failure shape: pull the deployment-level DEPLOY
   log and grep:
   ```bash
   grep -nE "nos_metadata_helper.py:640|nested_ahv_2.py:1[01][023][02]|Unable to instantiate the NOSCluster|memory_capacity_in_bytes" \
     <DEPLOY_LOG>
   ```

2. Find the offending `/v2.0/hosts` response. Just before the
   first `nos_metadata_helper.py:640` ERROR, the deployer logs
   `<<200:{...metadata...}` from
   `https://<cvm_vip>:9440/PrismGateway/services/rest/v2.0/hosts`.
   Grep `acropolis_connection_state` in that JSON — if it is
   `kDisconnected` for every host, the Acropolis-warmup theory
   is confirmed.

3. From the per-host log tarballs in
   `entity_logs/retry_<n>/<cluster>/nested_host_log_<host_ip>/`:
   - `var_log.tar.gz` — `messages`, `dmesg`, `acropolis.*`,
     `genesis.out`. Look for `acropolis.FATAL`, kernel OOM,
     IDF/Cassandra connection refused.
   - `etc_nutanix_config.tar.gz` — confirms which AHV build was
     installed (cross-check `nestedahv-X.Y-NNN`).

4. From the per-CVM logbay bundle in
   `entity_logs/retry_<n>/<cluster>/logbay_<cvm_ip>_<ts>.zip`:
   - `genesis.out` — service startup ordering.
   - `cassandra*.out` — confirm Cassandra came up.
   - `prism_gateway.log` — confirm Prism actually has the
     hardware capacity records (or that they are still null).
   - `insights_server.out` — the source-of-truth for
     `memory_capacity_in_bytes`; if IDF still has nulls,
     acropolis hasn't pushed host hardware facts yet.

5. Cross-reference the AHV image and AOS build pair against
   known compatibility issues. The deployment payload carries
   both:
   ```
   payload.resource_specs[].software.hypervisor.build_url
       (e.g. installed-nestedahv-11.2-691.qcow2)
   payload.resource_specs[].software.nos.commit / .version / .build_url
       (e.g. ganges-7.6-stable / e0f3d3acdcf...)
   ```
   Search JIRA / Confluence for known acropolis-disconnect bugs
   on this build pair.

**Useful grep patterns (deployer DEPLOY log):**
```
nos_metadata_helper.py:640
nested_ahv_2.py:11(02|12|30)
Unable to instantiate the NOSCluster
memory_capacity_in_bytes
acropolis_connection_state.*kDisconnected
PLUGIN::NESTED_AHV.*NESTED_CLUSTER
```

**Useful grep patterns (per-AHV-host `var_log/messages`,
`acropolis.*`):**
```
acropolis.*FATAL
acropolis.*Check failed
acropolis.*could not connect
out of memory|Killed process .*acropolis
```

**Useful grep patterns (per-CVM logbay bundle):**
```
insights_server.*memory_capacity_in_bytes
prism_gateway.*acropolis_connection_state
genesis.out: Starting acropolis service
```

**JIRA search keywords:**
- `"Unable to instantiate the NOSCluster object with cluster name"`
- `"Failed while transforming nested cluster metadata"`
- `"PLUGIN::NESTED_AHV" "NESTED_CLUSTER"`
- `"acropolis_connection_state" "kDisconnected"` plus the AHV
  build label (e.g. `"nestedahv-11.2-691"`) and the AOS branch
  (e.g. `"ganges-7.6"`)

**Distinguishing this from flow #1 (Node Lock Timeout):**

| Signal | Flow #1 (Node Lock) | Flow #4 (Acropolis Disconnected) |
|---|---|---|
| `cluster create` returns success | No (RPC times out) | **Yes** |
| Cassandra ring formed | No | **Yes** (`metadata_store_status: kNormalMode`) |
| Last reached stage | `Cluster creation` | `INSTANTIATE_NOS_CLUSTER` |
| Symptom in deployer log | `RPC to acquire node lock ... timed out` | `Failed while fetching valid value for 'memory_capacity_in_bytes'` |
| Where to dig | Genesis on the timing-out CVM | Acropolis on every AHV host |

**Base cluster diagnostics (Step 5b applicability):**

This failure happens *after* nested VMs are created and *after*
cluster create succeeds — Cassandra ring is formed and Prism is
serving requests. The Step 5b diagnostic-value gate triggers the
**post-cluster-healthy carve-out** (`SKILL.md` Step 5b "Skip"
rules): host CPU/memory/IO pressure cannot plausibly cause an
acropolis-warmup race after the cluster is steady. Skip Step 5b
for this pattern.

The report still includes a `## Base Cluster Diagnostics` section
header with a one-line "skipped: post-cluster-healthy carve-out;
cluster create succeeded with `metadata_store_status:
kNormalMode` and Prism serving requests; base-cluster sar cannot
inform an acropolis warmup race." Silent omission is forbidden
per the Anti-Hallucination rule.
