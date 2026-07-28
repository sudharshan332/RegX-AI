# Curator Investigation Flows

## MapReduce Scan Pipeline

**What it does:** Curator runs periodic background scans (Selective, Partial,
Full) as distributed MapReduce jobs. Each scan type has map tasks that read
vdisk metadata via Medusa (backed by Cassandra) and Forest (backed by
Stargate groves). Scan results are aggregated and written to the index store
(backed by ZooKeeper znodes). Curator uses these scans to enforce garbage
collection, data placement policies, and cluster health checks.

**Internal operation flow:**
```
scan scheduled (by curator master based on timer / trigger)
  → map tasks distributed to curator workers across CVMs
    → each map task:
        → queries Medusa (Cassandra) for vdisk/extent metadata
        → requests vdisk hosting on Stargate (kForestHostOp) if needed
        → reads Forest B-tree block maps
        → produces intermediate results
  → reduce phase aggregates results
  → index store controller writes results to ZK znodes
  → scan marked complete
```

**Key log files and grep patterns:**

```bash
# Scan completion status (success or failure):
grep -a "completed with status" curator.out* | tail -20

# Map task failures (trace which downstream service failed):
grep -a "kBackendUnavailable\|kMapReduceError\|kNoNode\|kZeusError" curator.out*

# Index store controller issues (ZK-related):
grep -a "index_store_controller_ops.cc.*failed with error" curator.out*

# Medusa/Cassandra lookup failures:
grep -a "get_range_slices.*Failed\|basic_medusa_op.cc.*error" curator.out*

# Identify the curator master:
grep -a "I am the curator master" curator.out*

# Count failure frequency across CVMs:
grep -ac "kMapReduceError\|kBackendUnavailable\|kNoNode" curator.out*
```

**Failure propagation (common causal chains):**
- **Cassandra unavailable** → Medusa `get_range_slices` fails → map tasks
  retry → retries exhausted → `kBackendUnavailable` → scan fails with
  `kMapReduceError`
- **ZK session loss / znode corruption** → index store controller cannot read
  or write scan metadata → `kNoNode` / `kZeusError` → scan fails
- **Stargate unavailable** (crash loop, EI kill) → vdisk hosting for block
  map scan fails → map task cannot read Forest B-tree → task fails
- **External storage (when Forest/Medusa data is on external storage)** →
  higher latency → more fragile access patterns → timeouts cascade to scan
  failures
- **External storage PR failure** → grove init fails with `kHostingFailed`
  → Forest returns `kBackendUnavailable` → VDiskBlockMapTask retries
  exhaust → scan fails. Root cause is on the Stargate/storage side.
  See [External Storage Volume Lifecycle](stargate-flows.md) for stargate
  triage.
- **Curator hosting destroyed B-trees** → Forest returns
  `kAlreadyDestroyed` ("B-Tree is destroyed") → Medusa returns
  `kBackendUnavailable` → VDiskBlockMapTask retries exhaust → scan fails.
  Root cause is on the Curator side (stale vdisk references, incorrect
  metadata). Do NOT confuse this with PR/storage failures — see the
  "Distinguishing kHostingFailed vs kAlreadyDestroyed" section in the
  [VDisk Controller & Forest Operations](stargate-flows.md#vdisk-controller--forest-operations)
  flow.
- **Cassandra ring change** (AddNode / RemoveNode / disk replacement) →
  temporary unavailability → scan failures during the transition

**Cross-service checks:**
- **cassandra_monitor.out**: Ring changes, kills, restarts that correlate
  with scan failure timestamps
  ```bash
  grep -a "ring_change\|AddNode\|RemoveNode\|boot.*disk\|replacing" cassandra_monitor.out*
  ```
- **stargate.out**: Forest/grove failures that would cause map task failures.
  See [stargate-flows.md](stargate-flows.md) for detailed stargate triage.
- **zookeeper_monitor.out**: ZK session loss, peer connectivity issues
- **hades.out**: Disk errors that may affect Cassandra or ZK data stores

**JIRA search keywords:**
`"kMapReduceError"`, `"kSelectiveVDiskSevering"`, `"index_store_controller"`,
`"kNoNode"`, `"kZeusError"`, `"VDiskBlockMapTask"`,
`"kBackendUnavailable"`, `"get_range_slices"`, `"basic_medusa_op.cc"`
