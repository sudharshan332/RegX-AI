# Service Investigation Flows & Failure Analysis

Reference file for `triage-cdp-test-failure`. Read this when tracing causal
chains, identifying primary vs. cascading failures, or investigating service
subsystem behavior during triage.

## Organization Principles

This file is organized by **service subsystem**, not by individual fatal
signatures. Each investigation flow describes how a subsystem works
internally, what to check when it fails, and how failures propagate.

**Guard rails:**
- Never add a new top-level section for a single fatal signature — instead,
  enrich the relevant service investigation flow with new grep patterns,
  downstream effects, or cross-service checks.
- The bar for a new flow section is "a fundamentally different subsystem or
  operation pipeline," not "a new error message."
- Keep flow sections stable over time; they grow by accumulating triage
  knowledge (new log patterns, failure modes, cross-service correlations),
  not by cataloging every fatal ever seen.

---

## Generic Triage Utilities

Fatal signature extraction, activity-trace parsing, and activity
correlation utilities live in
[extract-reference.md](extract-reference.md) (§§ 1, 4, 5). Read that
file when you need the canonical signature format, section markers,
or correlation ID list.

---

## Entity-Based Timeline Investigation

When a FATAL message references specific entity IDs, extract those IDs and
grep all relevant service logs to build a chronological timeline. This
technique is critical for metadata corruption bugs and data path failures
where the root cause happened minutes or hours before the FATAL.

### Step 1 — Extract entity IDs from the FATAL message

Common entity types in FATAL/DFATAL messages:

| Entity       | Log patterns                          | Example                    |
|--------------|---------------------------------------|----------------------------|
| Extent group | `extent_group_id=`, `egroup=`, `egid=` | `2548105`                 |
| Extent ID    | `extent_id=`, `oid=X:vb=Y:emap=Z`    | `oid=4303:vb=19956:emap=1` |
| VDisk        | `vdisk_id=`, `owner_vdisk_id=`        | `4303`                     |
| Disk         | `disk_id=`, `disk=`                   | `56`                       |
| Operation    | `op_id=`, `operation_id=`, `opid=`    | `3381956043`               |
| Container    | `container_id=`, `owner_container_id=` | `2244`                    |
| DBS instance | `id=<N>:`, `block store dbs_<N>`      | `id=984`                   |
| DBS entity   | `entity_id=<N>`, `dbs_<id>_<entity>`  | `entity_id=1`, `dbs_984_1` |
| Grove        | `grove_<N>`, `scid: <N>`              | `grove_48066`, `scid: 48066` |
| Grove alloc  | `grove_<N>_allocator`                 | `grove_5539_allocator`     |
| Grove WAL    | `grove_<N>_wal`, `dbs_internal_wal_grove_<N>_wal` | `grove_48066_wal` |
| Grove FS     | `dbs_internal_fs_grove_<N>_wal`       | `dbs_internal_fs_grove_48066_wal` |

Extract ALL entity IDs from the FATAL line — they will be used as grep
patterns in subsequent steps.

### Step 2 — Grep product logs for entity IDs

Use the Service Dependency Map (below) to determine which services to grep.
For the failing service, grep its logs AND all services it depends on. Grep
all CVMs. This is important - Missing CVM may cause missing results.

| Failing Service | Also grep                              |
|-----------------|----------------------------------------|
| curator         | stargate, cassandra, zookeeper         |
| stargate        | pithos, cassandra, hades, zookeeper    |
| stargate (DBS)  | stargate on ALL CVMs (DBS RPCs cross CVM boundaries) |
| pithos          | cassandra, zookeeper                   |
| cerebro         | cassandra, zookeeper                   |

**Grep pattern guidelines:**

- Use field-level patterns to avoid false positives: `egroup=2548105` or
  `extent_group_id=2548105`, not bare `2548105` (which matches checksums,
  timestamps, etc.)
- For extent IDs with components, grep the most specific part:
  `vb=19956` or `oid=4303:vb=19956`
- Combine entity patterns when needed: grep for the egroup ID first to
  find all operations, then narrow by extent ID for the specific entity

**Where to grep** (two-tier approach — see
`archived-logs-reference.md` Step 4b):

- **Always:** HTTP bundle product logs (`nos_cluster_logs_*/`)
- **If available:** Shrek archive (discovered in Step 3c) for full
  log rotation coverage

### Step 3 — Build a chronological timeline

Sort all grep results by timestamp and organize into a timeline:

- **Timestamp** — exact time from the log line
- **Source** — CVM IP, service name, log file
- **Event** — what happened (write, migration, SV update, checkpoint, etc.)
- **Raw log evidence** — the actual log line(s)

The timeline should start from the earliest operation on the entity and end
at the FATAL. Look for state transitions, metadata updates, and any
operation that could have introduced the inconsistency.

### Example: Curator DFATAL with extent group mismatch

```
FATAL: extent_group_id=2548105, oid=4303:vb=19956:emap=1,
       mismatch_detected_in_map4=1

Extracted entities:
  egroup=2548105, vb=19956, vdisk_id=4303

Grep targets:
  All CVMs stargate logs: "egroup=2548105", "vb=19956"
  All CVMs curator logs: "extent_group_id=2548105"

Timeline discovered:
  18:05:14 — First write to egroup 2548105 (stargate, CVM 104)
  18:05:15 — Write vb=19956:emap=0 to extent_index=3
  18:05:15 — vdisk_micro_migrate_extents_op migrates vb=19956:emap=1
  18:14:04 — SV bulk update shows corrupted bitset
  18:16:08 — Curator FATAL detects mismatch (CVM 106)
```


## Service Dependency Map

When tracing a causal chain, use this dependency map to know which upstream
services to check. An arrow means "depends on."

```
                    ┌──────────────────────────────────┐
                    │          zookeeper (ZK)           │
                    │  (universal dependency — all      │
                    │   services depend on ZK for       │
                    │   configuration and coordination) │
                    └──────────┬───────────────────────┘
                               │
                    ┌──────────▼───────────┐
                    │     cassandra         │
                    │  (metadata store,     │
                    │   Medusa backend)     │
                    └──┬───┬───┬───┬───┬───┘
                       │   │   │   │   │
          ┌────────────┘   │   │   │   └──────────────┐
          ▼                ▼   │   ▼                  ▼
       pithos          cerebro │  alert_manager    insights
          ▲                    │  ergon
          │                    │
          │            ┌───────▼───────┐
          └────────────┤   stargate    ├──► hades
                       │ (also depends │   (disk mgmt, external
                       │  on cassandra │    storage volume mapping)
                       │  directly)    │
                       └───────┬───────┘
                               │
                    ┌──────────▼──────────┐
                    │      curator        │
                    │  (MapReduce scans   │
                    │   via Medusa/Forest │
                    │   + ZK index store) │
                    └─────────────────────┘
```

**Management / UI plane (cluster classification, config publish):**

```
      pe_ui  ──HTTP──►  prism_gateway  ──reads──►  arithmos  ◄──publishes── genesis
    (React UI,       (v1/cluster,              (generic         (cluster_type,
   PageActionView)  ClusterDTOAssembler)     attribute list)   ntp_server_ip_list,
                                                                snmp_status, ncc_version,
                                                                external_storage_provider_info)
```

**How to use during triage:**
- `stargate` fatal → check `pithos`, `cassandra`, `hades`, `zookeeper`
- `pithos` fatal → check `cassandra`, `zookeeper`
- `curator` fatal / `kMapReduceError` → check `cassandra`, `zookeeper`, `stargate`
- `cassandra` unavailable → check `zookeeper`
- `zookeeper_monitor` QFATAL → check ZK Java process logs, peer ZK nodes
- Cascading cluster-wide FATALs → almost always ZK or Cassandra quorum loss
- Disk mount path empty / stale → check `xmount` (blockstore-enabled
  clusters), `hades` (disk state), and whether a NOS upgrade or service
  restart occurred
- `genesis` greenlet / publisher death (e.g.
  `publish_genesis_config_to_idf`, `sync_config_to_idf`) → check
  `arithmos` FATAL in the same ±60s window (ConnectionResetError seen in
  genesis usually pairs with an arithmos DCHECK/FATAL + restart)
- `prism_gateway` `v1/cluster` returning `clusterType: null` or missing
  generic attributes → check `arithmos` master entities
  (`arithmos_cli master_get_entities entity_type=cluster`) and the
  genesis publish chain (`cluster_config.py` `update_*` methods)
- `pe_ui` misclassifies cluster type or greys out Attach External Storage
  → check `prism_gateway` `v1/cluster` response, then `arithmos`
  generic_attribute_list for `cluster_type`, then the `genesis` publisher
  greenlet for an exception trace

**Blockstore/FUSE additional dependencies:**
- `stargate` → `xmount` (FUSE-based block store disk mounts). xmount is
  NOT managed by genesis — it is started by `service_monitor`. When
  blockstore is enabled, a subset of disks are FUSE-mounted by xmount.
  If xmount dies (e.g., killed by `finish` during NOS upgrade), those
  FUSE mounts become stale and filesystem operations (find, ls, cat)
  return empty or fail. Stargate itself may still function internally
  (it accesses disks via block_store, not the FUSE mount), but anything
  that validates disk state via the filesystem (test assertions, hades
  disk checks) will see broken state.
- To check xmount status: look for `xmount.INFO` / `xmount.out` in CVM
  service logs. Check the last log entry timestamp — if it stopped hours
  before the test failure, xmount was likely killed and not restarted.
  Also check `finish.out` for "Stop service requested for xmount" if a
  NOS upgrade occurred.

**External storage additional dependencies:**
- `stargate` → `hades` (NVMe-oF volume mapping, multipath)
- `hades` → external storage array (NVMe-oF transport layer)
- `zookeeper` → external storage disk (when ZK data is on external storage)
- If external storage has an I/O disruption, it can cascade through
  `hades` → `stargate` and/or `zookeeper` → everything

**DBS (Distributed Block Store) additional dependencies:**
- `stargate` grove storage → DBS entity leader (all block allocations
  route to the leader entity via RPC, typically entity_id=1)
- DBS entity → backing store volume (SPDK block device on external
  storage array)
- DBS kNoSpace cascading pattern: DBS entity full → grove allocators
  fail across ALL CVMs → WAL log writes fail → internal WAL checkpoint
  overflow → grove hosting failures → vdisk writes hang
- **How to use during DBS failures:** find `dbs_fb_rpc_svc_impl.cc`
  logs to identify the leader CVM; all kNoSpace is server-side on that
  CVM. Read [flows/meta-dbs-flows.md](flows/meta-dbs-flows.md) for the full
  investigation flow.

---

## Flow Directory

Investigation flows are in the `flows/` directory. Read the specific flow
file **on demand** when the causal chain reaches that subsystem — do not
read all flows upfront.

| Flow Name | File |
|---|---|
| External Storage Volume Lifecycle | [flows/stargate-flows.md](flows/stargate-flows.md) |
| VDisk Controller & Forest Operations | [flows/stargate-flows.md](flows/stargate-flows.md) |
| BackingStoreRouter SIGSEGV — Use-After-Free | [flows/meta-dbs-flows.md](flows/meta-dbs-flows.md) |
| DBS Entity Investigation — Step-by-Step | [flows/meta-dbs-flows.md](flows/meta-dbs-flows.md) |
| MapReduce Scan Pipeline | [flows/curator-flows.md](flows/curator-flows.md) |
| AHV Host Network Troubleshooting (Live Debug) | [flows/ahv-network-flows.md](flows/ahv-network-flows.md) |
| PC Placement Solver: External Storage Capacity Check | [flows/pc-placement-flows.md](flows/pc-placement-flows.md) |
| Stargate: External Storage SCSI Unmap / fstrim Pipeline | [flows/stargate-flows.md](flows/stargate-flows.md) |
| Genesis: Cluster Configuration Publish to Arithmos Generic Attributes | [flows/genesis-flows.md](flows/genesis-flows.md) |

---

## Primary vs. Cascading Failure Identification

**1. Map EI targets at the failure time:**

```
CVM            EI Target?     Fatal?     Fatal Service
10.125.4.157   YES (stargate) YES        stargate      ← expected, EI caused this
10.125.4.212   NO             YES        stargate      ← INTERESTING — spontaneous
10.125.4.162   NO             YES        stargate      ← INTERESTING — spontaneous
10.125.4.182   NO             NO         —             ← clean
```

**2. Identify crash loops vs. one-time fatals:**
If same signature repeating multiple times over minutes, report as
**crash loop** and focus on the *first* occurrence.

**3. Check for cascading patterns:**
- Cassandra killed → pithos unavailable → stargate `kHostingFailed`
- ZK quorum loss → every ZK-dependent service FATALs within seconds
- External storage I/O error → hades disk errors → stargate grove failures
- Stargate crash loop on CVM A → persistent reservation contention →
  stargate failures on CVM B
- DBS backing store kNoSpace → grove allocator FATALs across all CVMs →
  WAL checkpoint overflow → stargate cores → hung IO (see
  [flows/meta-dbs-flows.md](flows/meta-dbs-flows.md))
- DBS kNoSpace + BackingStoreRouter SIGSEGV → entity churn causes
  use-after-free in Write path (secondary bug, not root cause)

Report the **root** of the chain as primary; note downstream failures as
"cascading from [root cause]."

**4. In the JIRA report:**
- Title after the *primary* (non-cascading, non-EI) failure
- Describe the full chain in Failure Summary
- Link cascading fatals that match existing JIRAs as Related
