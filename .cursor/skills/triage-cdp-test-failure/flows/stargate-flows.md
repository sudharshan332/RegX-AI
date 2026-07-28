# Stargate Investigation Flows

## External Storage Volume Lifecycle

**What it does:** Stargate manages external storage volumes over NVMe-oF.
Each vdisk backed by external storage has metadata and data volumes on the
array, accessed via SPDK block devices. Stargate coordinates volume creation,
attachment, persistent reservation, resize, and teardown.

**Internal operation flow:**
```
volume create (PowerStore/Pure REST API)
  → SPDK bdev attach (NVMe-oF discovery + connect)
    → persistent reservation acquire (SCSI-3 PR via spdk_nvmf_client)
      → grove storage init (block_store_volume_grove_storage_initialize_op)
        → forest host (kForestHostOp — B-tree metadata hosted on volume)
          → vdisk controller ready (vdisk available for I/O)
```

**Key log files and grep patterns:**

```bash
# NVMe-oF transport health (SPDK layer — in stargate.out between [] brackets):
grep -a "nvme_tcp.c.*ERROR\|bdev_nvme.c.*timeout_cb\|nvme_ctrlr.*resetting\|nvme_qpair.*ABORTED\|Failed to flush tqpair\|Bad file descriptor\|Broken pipe" stargate.out*

# Persistent reservation failures:
grep -a "spdk_nvmf_client.cc.*Failed to acquire Persistent Reservation\|Failed to acquire persistent reservation" stargate.out*

# Grove / block store initialization failures:
grep -a "block_store_volume_grove_storage_initialize_op.cc.*Failed to create\|forest_host_op.cc.*Grove initialization failed\|forest_base_op.cc.*kHostingFailed" stargate.out*

# Volume resize activity (SPDK namespace resize notifications):
grep -a "nvme_ctrlr_populate_namespaces.*NSID.*is resized" stargate.out*

# External storage REST API errors:
grep -a "powerstore_manager.cc\|pure_storage_manager.cc\|Create volume failed\|Delete volume failed" stargate.out*
```

**Failure propagation:**
- NVMe-oF transport errors (flush failures, timeouts, controller resets) →
  block device unavailable → grove I/O fails → vdisk unavailable → UVM I/O
  stalls or reboots
- Persistent reservation failure → grove cannot initialize → forest host
  fails with `kBlockStoreError` / `kHostingFailed` → vdisk controller
  cleanup may trigger use-after-free if callbacks are still queued
- Volume resize during active I/O → namespace rescan → if stargate is in a
  crash-restart cycle, new instance may collide with stale reservations from
  the prior instance
- Stargate crash loop → orphaned volumes on external storage array (volumes
  created but never properly torn down) → volume validation failure at test
  end

**Cross-service checks:**
- **hades**: NVMe-oF multipath status, disk mapping, bdev health
  (`hades.out` — look for disk errors, path failures)
- **pithos**: vdisk ownership, vdisk controller lifecycle
  (`pithos.out` — look for ownership changes around the failure time)
- **zookeeper**: if ZK data lives on external storage, ZK I/O errors cascade
  to cluster-wide service failures (check `zookeeper_monitor.out` and ZK
  Java logs)
- **cassandra**: Medusa availability affects vdisk metadata lookups
  (`cassandra_monitor.out` — look for ring changes, kills)

**JIRA search keywords:**
`"nvme_tcp.c"`, `"Failed to flush tqpair"`, `"bdev_nvme.c"`, `"timeout_cb"`,
`"resetting controller"`, `"Persistent Reservation"`,
`"spdk_nvmf_client.cc"`, `"kBlockStoreError"`, `"kHostingFailed"`,
`"external_storage_vol_validator"`, `"aos_vols_missing_in_es"`

---

## VDisk Controller & Forest Operations

**What it does:** The VDisk Controller manages the lifecycle of individual
vdisks within Stargate. Forest is the B-tree metadata subsystem that backs
each vdisk; groves are the individual B-tree instances. When a vdisk is
hosted on a Stargate node, the controller initializes its forest/grove, and
when it is unhosted (e.g., due to migration, EI kill, or crash), the
controller tears down and cleans up resources.

**Internal operation flow:**
```
vdisk host request (from pithos ownership change, migration, or curator scan)
  → VDiskController created
    → FunctionExecutor (fe_) initialized for async callbacks
      → kForestHostOp begins:
        1. Check if already hosted → kAlreadyHosted (success)
        2. Check vdisk_config.metadata_btree_state:
           - if kMetadataBTreeDestroyed → kAlreadyDestroyed (short-circuit,
             never reaches grove init — indicates caller is requesting
             hosting for a vdisk whose B-tree was already destroyed)
        3. Acquire grove lock → acquire backend lock
        4. Grove storage init → block store create → backing store
           - if PR or storage failure here → kHostingFailed
        5. vdisk ready for I/O

vdisk unhost / controller destruction:
  → FunctionExecutor disabled (func_disabler_in_fe_)
    → pending callbacks in ThreadPool queue are popped but skipped
      → ScopedExecutor destructor runs on background worker thread
        → if callback captured raw `this` pointer → use-after-free risk
```

**Key log files and grep patterns:**

```bash
# Forest host/unhost operations:
grep -a "kForestHostOp\|kForestUnhostOp\|forest_host_op.cc\|forest_base_op.cc" stargate.out*

# VDisk controller lifecycle:
grep -a "vdisk_controller.*Hosting\|vdisk_controller.*Unhosting\|vdisk_controller.*Destroying" stargate.out*

# IdLocker issues (symptom of use-after-free in controller cleanup):
grep -a "id_locker.cc.*Check failed\|Lock state not found" stargate.out*

# Block store errors:
grep -a "block_store.*Error\|kBlockStoreError\|Failed to create block store\|Failed to create backing store" stargate.out*

# Crash loop detection (count stargate restarts):
grep -a "Stargate exited with status\|stargate_monitor.cc.*exited" stargate.out*
```

**Distinguishing kHostingFailed vs kAlreadyDestroyed:**

These are two fundamentally different Forest host errors with different
root causes. Do NOT conflate them during triage:

- **`kHostingFailed`** (message: "Failed to create block store"): Occurs
  during grove storage initialization (step 4 in the flow above). Caused
  by infrastructure failures such as persistent reservation contention,
  NVMe-oF transport errors, or storage unavailability. Triage via the
  External Storage Volume Lifecycle flow or block store investigation.

- **`kAlreadyDestroyed`** (message: "B-Tree is destroyed"): Occurs as an
  early short-circuit (step 2 in the flow above), **before** grove init
  even starts. The vdisk's `metadata_btree_state` is already set to
  `kMetadataBTreeDestroyed` in the Pithos vdisk config. This means the
  **caller** (typically Curator) is requesting hosting for a vdisk whose
  B-tree has already been torn down. This is a Curator-side issue — not
  a storage or PR issue. Triage from the Curator side to determine why
  it is attempting to host already-destroyed vdisks.

When both errors appear in the same log set, they are **independent
failures** that happen to produce the same downstream symptom
(`kBackendUnavailable` from Medusa). Trace each one separately.

**Failure propagation:**
- Forest host failure (`kHostingFailed`) → vdisk unavailable → I/O to that
  vdisk returns errors → UVM may see I/O failures or reboots
- Forest host failure (`kAlreadyDestroyed`) → Curator requested hosting for
  a destroyed B-tree → Medusa returns `kBackendUnavailable` for that
  vdisk's block map → VDiskBlockMapTask retries exhaust → scan fails.
  Root cause is on the Curator side (why is it requesting hosting for
  destroyed vdisks?), not on the Stargate/storage side.
- VDisk controller crash during cleanup → stargate restart → all vdisks on
  that node temporarily unavailable → other nodes may attempt to re-host
  those vdisks → persistent reservation contention if prior instance's
  reservations haven't expired
- Crash loop (same crash repeating every 30-90s) → the first instance is the
  interesting one; later restarts are symptoms of the same underlying issue

**Cross-service checks:**
- **pithos**: Who owned the vdisk? Was there an ownership change? For
  `kAlreadyDestroyed`, check the vdisk's `metadata_btree_state` in the
  vdisk config — if it is `kMetadataBTreeDestroyed`, the issue is on the
  caller side.
  (`pithos.out` — grep for the vdisk_id)
- **curator**: Was a curator scan triggering forest host operations? Curator
  map tasks request vdisk hosting for block map scans. For
  `kAlreadyDestroyed` errors, check why Curator is requesting hosting for
  vdisks with destroyed B-trees — this may indicate a stale vdisk
  reference in the scan's metadata or an issue with vdisk lifecycle
  tracking. (`curator.out` — look for the vdisk_id in scan task logs)
  See [MapReduce Scan Pipeline](curator-flows.md) for curator scan triage.
- **cassandra**: Was Medusa available for metadata lookups during the forest
  host attempt? (`cassandra_monitor.out` — look for availability around the
  failure timestamp)

**JIRA search keywords:**
`"kForestHostOp"`, `"kHostingFailed"`, `"kAlreadyDestroyed"`,
`"B-Tree is destroyed"`, `"kMetadataBTreeDestroyed"`, `"id_locker.cc"`,
`"IdLocker::Release"`, `"VDiskController"`, `"ScopedExecutor"`,
`"ThreadSafeBind"`, `"forest_host_op.cc"`, `"forest_base_op.cc"`
