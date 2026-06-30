# DBS (Distributed Block Store) Investigation Flows

> **Scope**: This document covers `external_storage_dbs_mode=1` (DBS for
> **metadata only**). In mode=1, grove B-trees, WAL, allocator, TUPageManager,
> and oplog structures are stored in DBS. Vdisk data continues to reside on
> per-snapshot-chain data volumes provisioned on the external storage array.
> Mode=2 (`data and metadata`) additionally stores vdisk data on DBS — that
> mode is **not** covered here.
>
> The flag is defined in `external_storage_util.cc`:
> ```
> DEFINE_int32(external_storage_dbs_mode, 0,
>   "Distributed block store usage mode for external storage: "
>   "0: disabled, 1: metadata, 2: data and metadata.");
> ```
> The helper `ExternalStorageUtil::DbsEnabled(bool for_data)` returns `true`
> for metadata when mode >= 1, and `true` for data only when mode == 2.

## DBS Architecture Overview

DBS is a distributed block store that provides persistent named block allocation
for grove filesystems (WAL, B-tree, oplog backends) on external storage. Each
DBS instance maps to an external storage volume group and is identified by
`id=<N>` (e.g., `id=984`).

### Grove-to-Snapshot-Chain Mapping

A **Grove** is the unit of metadata management in the Forest subsystem. Each
Grove maps **1:1 to a snapshot chain** — not to a single vdisk. A snapshot
chain may contain multiple vdisks (a base vdisk and its snapshot children),
and all vdisks in the same chain share a single Grove.

The Grove manages all the B-trees belonging to those vdisks. Each vdisk
becomes a **backend** within the Grove, keyed by `vdisk_id` in
`backend_map_`. The oplog map backend uses the negative snapshot chain id
(`-1 * snapshot_chain_id_`) as its key within the same Grove.

When Stargate needs to host a vdisk's B-tree, `ForestHostOp` looks up the
grove by `snapshot_chain_id` from the vdisk config. If no Grove exists for
that chain, one is created and initialized. Subsequent vdisks in the same
chain reuse the existing Grove.

**Source code:**
- Grove class definition: `ntnxdb_client/forest/grove.h` — header comment
  states: "Class that manages multiple b-trees belonging to VDisks of a
  single snapshot chain."
- Grove constructor takes `snapshot_chain_id` and `container_id`:
  `ntnxdb_client/forest/grove.cc` (`Grove::Grove`)
- ForestHostOp grove lookup/creation:
  `ntnxdb_client/forest/forest_ops/forest_host_op.cc`
  (`ForestHostOp::BackendLockAcquired`) — calls
  `grove_map->find(snapshot_chain_id_)`, creates new `Grove` if not found.
- Naming convention: `ntnxdb_client/forest/forest_util.h`
  (`ForestUtils::GenerateDefaultStorageId`) — generates IDs like
  `grove_<snapshot_chain_id>_<storage_type>`.

**Log evidence (grove creation for snapshot chain 2147527338):**
```
forest_host_op.cc:403] [vdisk_id: 2147527337, scid: 2147527338]
  Grove 2147527338 does not exist, creating

grove.cc:114] [scid: 2147527338] Creating Grove with the following options:
  snapshot_chain_id: 2147527338, container_id: 203,
  forest_mode: kHybrid, service_handle: 10.102.113.126:2009
```

**Grep patterns:**
```bash
# Grove creation events:
grep -a "Creating Grove with the following options" stargate.INFO*

# Which vdisks are in which grove:
grep -a "Grove.*does not exist, creating\|Going to host backend in Grove" stargate.INFO*

# Grove leadership changes:
grep -a "grove_.*ReleaseLeadershipOp\|grove_.*LeaderChanged" stargate.INFO*
```

---

### Architecture in Layers

The DBS architecture has two distinct layers. Understanding which layer is
involved is critical for triage — errors at the physical entity layer vs
the logical per-grove layer have very different root causes.

#### Layer 1: DBS BlockStore Entities (Physical Backing)

At the bottom, the Distributed Block Store is backed by external storage
volumes (e.g. NVMe volumes from a PowerStore or Pure array). These volumes
are partitioned into **BlockStore entities**. Each entity is a self-contained
`BlockStore` instance with its own:

- **Global header** — contains offsets for the internal WAL, component table,
  and region allocator metadata.
- **Internal WAL** — two incarnations (double-buffered for crash-consistent
  checkpointing), stored at fixed offsets immediately after the global header.
- **Region allocator** — manages allocation of fixed-size regions within the
  entity's backing store.
- **Internal filesystem** — a minimal filesystem used for WAL files and
  configuration.
- **Component** — the named-block manager that tracks all logical blocks.

The physical layout of a single BlockStore entity:
```
| Global Header | Internal WAL 0 | Internal WAL 1 | Component Table | Region Allocator Pages | Data Regions... |
```

All DBS entities in a cluster form a distributed pool. The
`BackingStoreRouter` in DBS maps entity IDs to their physical backing stores.
Block IDs returned by DBS encode the entity ID so that reads/writes are
routed to the correct entity.

**Entity hierarchy:**
```
DBS instance (id=984)
  ├── entity_id=1 (leader entity — one CVM hosts the leader)
  │     └── backing store: dbs_984_1 (volume-backed block device)
  ├── entity_id=2 (replica entity — may be hosted on different CVM)
  │     └── backing store: dbs_984_2
  └── ...
      └── (up to kMaxBlockStoreEntities entities)
```

**Source code:**
- BlockStore class: `util/util/block_store/block_store.{h,cc}`
- Global header schema: `util/util/block_store/global_header.fbs` — defines
  `wal0_offsets`, `wal1_offsets`, `component_table_offsets`,
  `region_allocator_heap_offsets`.
- Backing store: `util/util/block_store/backing_store.h`
- Entity initialization:
  `util/util/distributed_block_store/distributed_block_store.cc`
  (`DistributedBlockStore::InitializeBlockStoreEntity`,
  `DistributedBlockStore::StartBlockStoreEntity`)
- DBS config proto: `util/util/distributed_block_store/dbs_config.proto`
  (`BlockStoreEntity` message — defines `id`, `volume_id`,
  `start_offset_bytes`, `size_bytes`).
- BackingStoreRouter:
  `util/util/distributed_block_store/backing_store_router.cc`

**Grep patterns:**
```bash
# DBS entity start/initialization:
grep -a "Initializing block store entity\|Starting block store entity\|block store entity.*started" stargate.INFO*

# DBS capacity and entity status:
grep -a "total_capacity_bytes\|entity_status" stargate.INFO*

# Entity-level errors:
grep -a "Failed to start block store entity\|block_store.*kCorrupt" stargate.INFO*

# DBS entity hosting failures:
grep -a "Entity.*not hosted\|kNotLeader.*entity_id" stargate.INFO*

# Volume configuration issues:
grep -a "No volumes found in the distributed block store config" stargate.INFO*
```

#### Layer 2: Per-Grove DBS Client Resources (Logical Layer)

When a Grove is initialized with DBS storage (`DbsGroveStorage`), it creates
**DBS client resources** — a set of logical structures allocated as **named
blocks** within the DBS entity pool. These resources are per-snapshot-chain
and include:

1. **Allocator** (`grove_<scid>_allocator`) — manages block allocation for
   all B-trees in this grove. Tracks free/used blocks via a transaction log.
2. **WAL** (`grove_<scid>_wal`) — write-ahead log used by the B-tree backends
   for crash consistency. Stored as named blocks in DBS (not as a separate
   partition).
3. **TUPageManager** (`grove_<scid>_tu_page_mgr`) — manages transaction-update
   pages for the grove's B-trees.
4. **IOPageCache** (`grove_<scid>_allocator_iopage_cache`) — caches I/O pages
   for the allocator.

**Per-grove entity hierarchy within DBS:**
```
Each entity hosts grove allocators:
  grove_XXXX_allocator   — block allocator for grove XXXX
  grove_XXXX_wal         — WAL for grove XXXX
    └── dbs_internal_wal_grove_XXXX_wal  — internal WAL (16KB, 4 pages)
    └── dbs_internal_fs_grove_XXXX_wal   — internal filesystem for WAL
```

The client resources initialization sequence is:
```
DbsGroveStorage::Initialize
  → GetDbsClientResources (client_name = "grove_<scid>")
    → CreateAllocator (grove_<scid>_allocator)
      → fetch/create allocator transaction log
      → start IOPageCache
      → run transaction recovery
    → CreateTUPageManager
      → lookup client resources config
      → initialize TUPageManager
    → CreateWAL (grove_<scid>_wal)
      → lookup WAL config (/dbs/wals/grove_<scid>_wal)
      → create internal WAL (dbs_internal_wal_grove_<scid>_wal)
      → start internal WAL → recover
      → create internal filesystem (dbs_internal_fs_grove_<scid>_wal)
    → RecoverTUPage tentative updates
    → Finish TUPageManager recovery
    → Client resources ready
```

All groves share the same DBS entity pool. The named blocks for different
groves (WAL blocks, allocator txn logs, B-tree data) are interleaved in
the same regions, but each is tracked independently by the DBS named block
manager.

**Source code:**
- DBS allocator: `util/util/distributed_block_store/allocator.cc`
- DBS core: `util/util/distributed_block_store/distributed_block_store.cc`
- DbsGroveStorage: `ntnxdb_client/forest/dbs_grove_storage.{h,cc}`
- Client resources management:
  `util/util/distributed_block_store/client_resources_mgmt_op.cc`
- Allocator management:
  `util/util/distributed_block_store/allocator_mgmt_op.cc`
- WAL management: `util/util/distributed_block_store/wal_mgmt_op.cc`
- Stargate's DBS client resources creation:
  `cdp/server/stargate/stargate.cc` (`Stargate::GetDbsClientResources`)

**Log evidence (client resources for grove 2147527338):**
```
dbs_grove_storage.cc:80] [scid: 2147527338, storage_type: kDbs,
  storage_id: grove_2147527338_kDbs] Initializing DBS client resources

client_resources_mgmt_op.cc:108] client=grove_2147527338: Creating allocator
client_resources_mgmt_op.cc:138] client=grove_2147527338: Creating TUPageManager
client_resources_mgmt_op.cc:346] client=grove_2147527338: Creating WAL
client_resources_mgmt_op.cc:381] client=grove_2147527338: Recovering TUPage tentative updates
client_resources_mgmt_op.cc:411] client=grove_2147527338: Finishing TUPageManager recovery
```

**Grep patterns:**
```bash
# DBS client resources lifecycle:
grep -a "Initializing DBS client resources\|Relinquishing DBS client resources" stargate.INFO*

# Client resources creation steps:
grep -a "client_resources_mgmt_op.cc" stargate.INFO*

# Allocator activity for a specific grove:
grep -a "grove_<SCID>_allocator" stargate.INFO*

# WAL activity for a specific grove:
grep -a "grove_<SCID>_wal" stargate.INFO*

# DBS client resource failures:
grep -a "dbs_grove_storage.cc.*Failed to get DBS client resources" stargate.INFO*
```

---

### How the Grove WAL is Stored

The per-grove WAL (`grove_<scid>_wal`) is **not** a separate region or
partition in the block store. It is a set of **named blocks** allocated from
the shared DBS entity pool.

The grove WAL uses a double-buffered design with two incarnations (0 and 1).
Each incarnation consists of a fixed number of blocks (typically 4, totaling
16KB at 4KB per page). During normal operation, records are appended to the
active incarnation. During checkpointing, records are written to the inactive
incarnation and then the active incarnation pointer is flipped — this makes
the WAL crash-consistent.

```
Internal WAL layout (16KB total, 2 incarnations):
  ┌───────────────┬───────────────┐
  │ Incarnation 0 │ Incarnation 1 │  (active alternates on checkpoint)
  │ 4 pages × 4KB │ 4 pages × 4KB │
  └───────────────┴───────────────┘

Normal flow:
  1. Delta records (WAL updates) appended to active incarnation
  2. When active incarnation fills all pages → Checkpoint()
  3. Checkpoint writes all FS metadata to inactive incarnation
  4. Global header flips active incarnation ID
  5. Continue with new deltas in the now-active incarnation
```

The WAL configuration is persisted in the DBS config map at
`/dbs/wals/grove_<scid>_wal` and contains the block IDs and active
incarnation offset. The WAL also has an internal filesystem superblock stored
as a named block (`dbs_internal_fs_grove_<scid>_walSuperBlock`).

The data layout in the DBS entity is:
```
DBS Entity (shared by all groves)
├── grove_2147527338_wal         (8 named blocks: 4 per incarnation, fixed at creation)
├── grove_2147527338_allocator   (transaction log as named blocks)
├── grove_2147527338 B-tree data (named blocks, grows/shrinks with B-tree)
├── grove_2147534069_wal         (another grove's WAL, same pool)
├── grove_2147534069 B-tree data (another grove's data)
└── ... (all interleaved in shared regions)
```

**Source code:**
- Internal WAL: `util/util/block_store/wal.cc` — large comment block
  starting at line 54 documents the internal WAL design.
- WAL schema: `util/util/block_store/wal.fbs`
- BlockStore component WAL schema:
  `util/util/block_store/block_store_component_wal.fbs`
- WAL management op (creates/recovers per-grove WAL):
  `util/util/distributed_block_store/wal_mgmt_op.cc`

**Log evidence (WAL creation for grove 2147527338):**
```
wal_mgmt_op.cc:218] name=grove_2147527338_wal:
  Existing WAL config found: wal_config_key_=/dbs/wals/grove_2147527338_wal,
  config={ "internal_wal_block_ids": [ { "block_id": 4503623753576448, "num_blocks": 8 } ],
           "internal_wal_num_blocks": 4, "name": "grove_2147527338_wal" }

wal_mgmt_op.cc:305] Creating internal WAL: dbs_internal_wal_grove_2147527338_wal
  wal_offsets[0]=[(4503623753576448,-1)(4503623753580544,-1)(4503623753584640,-1)(4503623753588736,-1)]
  wal_offsets[1]=[(4503623753592832,-1)(4503623753596928,-1)(4503623753601024,-1)(4503623753605120,-1)]

wal.cc:1268] dbs_internal_wal_grove_2147527338_wal internal=true Created WAL

wal.cc:323] dbs_internal_wal_grove_2147527338_wal incarnation_offset_=0
  Creating internal WAL, current incarnation: 0, pages per incarnation: 4
```

**Grep patterns:**
```bash
# WAL creation / recovery:
grep -a "wal_mgmt_op.cc.*Creating internal WAL\|wal_mgmt_op.cc.*WAL config found" stargate.INFO*

# WAL checkpoint activity:
grep -a "dbs_internal_wal.*Checkpoint finalized\|dbs_internal_wal.*recovery records" stargate.INFO*
grep -a "Checkpointing from incarnation" stargate.INFO*

# WAL config map lookups and updates:
grep -a "key_str=/dbs/wals/grove_" stargate.INFO*

# Internal filesystem for WAL:
grep -a "dbs_internal_fs_grove.*SuperBlock\|Creating internal filesystem\|Formatting internal filesystem\|Starting internal filesystem" stargate.INFO*

# WAL log file writes (activity traces):
grep -a "log\.[0-9]\.ckpt\.tmp\|log\.[0-9]\.delta" stargate.INFO*
```

---

### Source Code Locations (xgear)

| Component | Path |
|-----------|------|
| Internal WAL | `util/util/block_store/wal.cc` |
| Block store core | `util/util/block_store/block_store.{h,cc}` |
| Global header schema | `util/util/block_store/global_header.fbs` |
| Backing store | `util/util/block_store/backing_store.h` |
| WAL flatbuffer schema | `util/util/block_store/wal.fbs` |
| Component WAL schema | `util/util/block_store/block_store_component_wal.fbs` |
| DBS allocator | `util/util/distributed_block_store/allocator.cc` |
| DBS core | `util/util/distributed_block_store/distributed_block_store.cc` |
| DBS config proto | `util/util/distributed_block_store/dbs_config.proto` |
| Backing store router | `util/util/distributed_block_store/backing_store_router.cc` |
| Client resources mgmt | `util/util/distributed_block_store/client_resources_mgmt_op.cc` |
| Allocator mgmt | `util/util/distributed_block_store/allocator_mgmt_op.cc` |
| WAL mgmt | `util/util/distributed_block_store/wal_mgmt_op.cc` |
| DBS RPC service | `util/util/distributed_block_store/dbs_fb_rpc_svc_impl.cc` |
| Grove class | `ntnxdb_client/forest/grove.{h,cc}` |
| Grove storage interface | `ntnxdb_client/forest/grove_storage_interface.h` |
| DBS grove storage | `ntnxdb_client/forest/dbs_grove_storage.{h,cc}` |
| Block store volume storage | `ntnxdb_client/forest/block_store_volume_grove_storage.{h,cc}` |
| Multi grove storage | `ntnxdb_client/forest/multi_grove_storage.cc` |
| Forest utilities | `ntnxdb_client/forest/forest_util.h` |
| Forest host op | `ntnxdb_client/forest/forest_ops/forest_host_op.cc` |
| Grove host op | `ntnxdb_client/forest/grove_ops/grove_host_op.cc` |
| Grove initialize op | `ntnxdb_client/forest/grove_ops/grove_initialize_op.cc` |
| B-tree grove backend | `ntnxdb_client/forest/btree_grove_backend_host_op.cc` |
| B-tree mgmt op | `util/util/distributed_block_store/btree_mgmt_op.cc` |
| Stargate DBS integration | `cdp/server/stargate/stargate.cc` (`GetDbsClientResources`) |
| Oplog backend host op | `ntnxdb_client/forest/grove_ops/grove_host_oplog_backend_op.cc` |
| Forest host oplog backend op | `ntnxdb_client/forest/forest_ops/forest_host_oplog_backend_op.cc` |
| DBS filesystem mgmt op | `util/util/distributed_block_store/file_system_mgmt_op.cc` |
| Forest typedefs (oplog names) | `ntnxdb_client/forest/forest_typedefs.h` |
| DistributedOplog class | `cdp/server/stargate/distributed_oplog/distributed_oplog.{h,cc}` |
| Distributed oplog store write | `cdp/server/stargate/distributed_oplog/distributed_oplog_store_write_op.cc` |
| OplogStore (dual DiskManager) | `cdp/server/stargate/oplog_store/oplog_store.{h,cc}` |
| OplogStore DiskManager | `cdp/server/stargate/oplog_store/disk_manager.{h,cc}` |

---

## DBS Client Resources Lifecycle

**What it does:** Each grove with DBS-backed storage has a set of DBS client
resources (allocator, WAL, TUPageManager) that must be initialized before
any B-tree operations can proceed, and properly relinquished during unhost
or shutdown. Problems in this lifecycle (initialization failures, recovery
errors, relinquish failures) propagate upward as grove hosting failures.

**Internal operation flow:**
```
Grove initialization (DbsGroveStorage::Initialize)
  → GetDbsClientResources
    → allocator create → txn log fetch → IOPageCache start → txn recovery
    → TUPageManager create → config lookup → initialize
    → WAL create → config lookup → internal WAL create → recover → FS create
    → TUPage recovery → finish
  → Grove storage ready → backend hosting can proceed

Grove shutdown (DbsGroveStorage::Shutdown)
  → RelinquishDbsClientResources
    → flush WAL → stop allocator → stop TUPageManager
    → release all named block references
  → Client resources released
```

**Key log files and grep patterns:**

```bash
# Full client resources lifecycle for a specific grove:
grep -a "grove_<SCID>" stargate.INFO* | grep -a "client_resources_mgmt_op\|dbs_grove_storage\|allocator\|wal_mgmt_op\|tu_page"

# Initialization failures:
grep -a "client_resources_mgmt_op.*Failed\|client_resources_mgmt_op.*error" stargate.INFO*

# Transaction recovery issues:
grep -a "txn_recovery_op.cc\|Transaction created during recovery not finalized" stargate.INFO*

# DBS config map operations (allocator, WAL, client resources configs):
grep -a "key_str=/dbs/" stargate.INFO*

# Relinquish operations:
grep -a "Relinquishing DBS client resources\|DbsClientResourcesRelinquished" stargate.INFO*
```

**Failure propagation:**
- Allocator transaction recovery failure → client resources init fails →
  grove storage init fails → ForestHostOp fails → vdisk unavailable
- WAL recovery failure (corrupt WAL blocks, missing named blocks) →
  same cascade as above
- TUPageManager recovery failure → same cascade
- Relinquish failure during shutdown → stale named block references may
  persist in DBS → next grove initialization for the same snapshot chain
  may encounter conflicts
- DBS entity unavailable (backing volume offline) → all groves using that
  entity are affected → multiple vdisks across multiple snapshot chains
  may fail simultaneously

**Cross-service checks:**
- **stargate (DBS server side)**: The DBS server runs within the same
  stargate process. Check for entity-level errors, named block allocation
  failures, and RPC timeouts between the DBS client and server.
  (`stargate.INFO` — grep for `dbs_fb_rpc_svc_impl.cc`)
- **external storage**: Volume health, NVMe-oF transport status.
  See [External Storage Volume Lifecycle](stargate-flows.md).
- **zeus/zookeeper**: DBS leadership election, grove leadership changes.
  (`stargate.INFO` — grep for `zeus_leadership_ops.cc.*grove_`)

**JIRA search keywords:**
`"client_resources_mgmt_op"`, `"dbs_grove_storage"`,
`"grove_.*_allocator"`, `"grove_.*_wal"`, `"txn_recovery_op"`,
`"Transaction created during recovery not finalized"`,
`"Relinquishing DBS client"`, `"tu_page_mgr"`,
`"dbs_internal_wal"`, `"wal_mgmt_op"`

---

## DBS Named Block Operations

**What it does:** The DBS uses a named block abstraction to provide
persistent, addressable storage blocks to its clients (groves). Named blocks
are identified by a string name and are tracked per-entity in the DBS. All
grove metadata (allocator txn logs, WAL blocks, B-tree nodes, filesystem
superblocks) are stored as named blocks.

**Internal operation flow:**
```
client request (e.g. allocator needs txn log block)
  → GetNamedBlockIds RPC to DBS server
    → DBS server routes to correct entity based on leader_entity_id
    → entity's BlockStore::Component looks up / allocates block
    → returns block_id (encodes entity_id + offset)
  → client uses block_id for subsequent I/O

named block link/unlink (e.g. transaction commit):
  → LinkNamedBlockIds RPC (associates name → block_id)
  → DeallocateNamedBlockIds RPC (removes association)

named block scan (e.g. transaction recovery):
  → ScanNamedBlockIds RPC (prefix scan for all txn IDs of a client)
    → scans all entities in parallel
    → returns matching entries
```

**Key log files and grep patterns:**

```bash
# Named block operations:
grep -a "GetNamedBlockIdsRpcHandler\|LinkNamedBlockIdsRpcHandler\|DeallocateNamedBlockIdsRpcHandler\|ScanNamedBlockIdsRpcHandler" stargate.INFO*

# Named block operations for a specific grove:
grep -a "grove_<SCID>" stargate.INFO* | grep -a "block_name="

# Config map operations (allocator configs, WAL configs, client resource configs):
grep -a "Looking up config map.*key_str=/dbs/\|Updating config map.*key_str=/dbs/" stargate.INFO*

# Block allocation failures:
grep -a "dbs_fb_rpc_svc_impl.*error\|dbs_fb_rpc_svc_impl.*Failed" stargate.INFO*
```

**Failure propagation:**
- Named block allocation failure → allocator cannot allocate blocks for
  B-tree nodes → B-tree write fails → vdisk I/O fails
- Named block scan timeout → transaction recovery stalls → client resources
  init stalls → grove hosting times out
- Config map lookup failure → WAL or allocator config not found → client
  resources init fails

**Cross-service checks:**
- **DBS entity health**: If a specific entity is unhealthy, all named blocks
  on that entity are inaccessible.
  (`stargate.INFO` — grep for `block store entity.*error`)
- **Network**: RPC failures between DBS client and server (may be local or
  cross-CVM).
  (`stargate.INFO` — grep for `RpcConnInfo.*Connection info`)

**JIRA search keywords:**
`"GetNamedBlockIdsRpcHandler"`, `"ScanNamedBlockIdsRpcHandler"`,
`"LinkNamedBlockIdsRpcHandler"`, `"DeallocateNamedBlockIdsRpcHandler"`,
`"dbs_fb_rpc_svc_impl"`, `"config map"`, `"/dbs/wals/"`,
`"/dbs/allocators/"`, `"/dbs/client_resources/"`

---

## DBS B-Tree Backend Operations

**What it does:** Each vdisk in a grove has a B-tree backend
(`BTreeGroveBackend`) that manages the vdisk's block map as a B-tree stored
in DBS. The backend uses the grove's shared allocator, WAL, and IOPageCache
to perform B-tree operations (insert, lookup, delete, split, merge).

**Internal operation flow:**
```
vdisk host in grove
  → GroveHostOp creates BTreeGroveBackend for vdisk_id
    → backend uses grove's allocator for block allocation
    → backend uses grove's WAL for crash consistency
    → backend uses grove's IOPageCache for caching
  → B-tree ready for read/write operations

B-tree write (e.g. block map update):
  → allocate block from grove allocator
  → log WAL delta record
  → write data to allocated block
  → WAL checkpoint (periodic)

B-tree destroy:
  → TerminateBTree API (removes DBS state for the B-tree)
  → deallocate all named blocks belonging to this B-tree
```

**Key log files and grep patterns:**

```bash
# Backend hosting:
grep -a "btree_grove_backend_host_op.cc\|Starting to host the b-tree\|Setting host state" stargate.INFO*

# B-tree creation / destruction:
grep -a "BTreeMgmtOp\|TerminateBTree\|btree_mgmt_op.cc" stargate.INFO*

# B-tree operations for a specific vdisk:
grep -a "vdisk_id: <VDISK_ID>" stargate.INFO* | grep -a "grove\|backend\|btree"
```

**Failure propagation:**
- Allocator exhaustion → B-tree cannot allocate new nodes → write fails
- WAL full or WAL write failure → B-tree cannot log operations → operations
  stall until WAL checkpoint completes
- IOPageCache errors → stale or corrupt cached pages → B-tree may read
  incorrect data

**Cross-service checks:**
- **grove storage**: Is the grove's storage healthy? Check DBS client
  resources status.
- **allocator**: Is the allocator running low on capacity? Check DBS entity
  usage stats.

**JIRA search keywords:**
`"btree_grove_backend"`, `"BTreeMgmtOp"`, `"TerminateBTree"`,
`"grove_host_op"`, `"btree_grove_backend_host_op"`,
`"kGroveHostOp"`, `"kGroveBackendHostOp"`

---

## DBS Oplog Structures

**What it does:** When `external_storage_dbs_mode=1`, the oplog (operation log)
for each grove is stored in DBS using a dedicated filesystem, VFS wrapper, and
optionally a B-tree backend. The oplog structures are created during the grove's
oplog backend hosting flow (`GroveHostOplogBackendOp`). They share the grove's
existing DBS client resources (allocator and WAL) — no additional allocator or
WAL is created for the oplog.

### Oplog DBS Data Structures

For each grove (snapshot chain) with DBS storage, the following oplog-specific
structures are created:

1. **Oplog DBS FileSystem** (`oplog_dbs_fs_<scid>`) — A `BlockStore::FileSystem`
   instance backed by DBS named blocks. This filesystem stores oplog episode
   files. Created via `DistributedBlockStore::CreateFileSystem()` using the
   grove's allocator and WAL:
   - Allocator: `storage->dbs_client_resources()->allocator()`
   - WAL: `storage->dbs_client_resources()->wal()`
   - SuperBlock stored as named block `oplog_dbs_fs_<scid>SuperBlock`
   - Config persisted in DBS config map at
     `/dbs/file_systems/oplog_dbs_fs_<scid>` (FlatBuffer containing name,
     WAL reference, superblock name, terminate_in_progress flag)

2. **Oplog DBS VFS** (`grove_->oplog_dbs_vfs_`) — A
   `BlockStore::FileSystem::VFS` wrapper over the DBS filesystem. This is the
   VFS pointer passed to the oplog store's DBS DiskManager for episode I/O.

3. **Oplog map B-tree backend** (optional) — A `BTreeGroveBackend` created with
   `vdisk_id = -1 * snapshot_chain_id`. This B-tree stores the oplog map when
   `FLAGS_forest_oplog_skip_btree_hosting` is false. Only one storage type can
   back the oplog B-tree at a time — the code FATALs if both BlockStore and DBS
   storages are available simultaneously.

**The Grove holds these as private members:**
```
grove_->oplog_dbs_file_system_  (shared_ptr<BlockStore::FileSystem>)
grove_->oplog_dbs_vfs_          (UniquePtr<BlockStore::FileSystem::VFS>)
```

The Grove also has legacy BlockStore-based oplog members for the 1:1 metadata
volume case:
```
grove_->oplog_file_system_      (shared_ptr<BlockStore::FileSystem>)
grove_->oplog_vfs_              (UniquePtr<BlockStore::FileSystem::VFS>)
```

`Grove::IsOplogFileSystemHosted()` returns true if either VFS pointer is set.
`Grove::IsOplogUsingStorage(type)` checks which storage type backs the oplog.

### Oplog DBS Filesystem Naming

The filesystem name follows the pattern `oplog_dbs_fs_<snapshot_chain_id>`:
```
ForestUtils::OplogFileSystemName(snapshot_chain_id)
  → StringJoin("oplog_dbs_fs_", snapshot_chain_id)
```

**Source code:** `ntnxdb_client/forest/forest_util.h`
(`ForestUtils::OplogFileSystemName`)

### Oplog Backend Hosting Flow

The oplog DBS structures are created within `GroveHostOplogBackendOp`:

```
GroveHostOplogBackendOp::MaybeStartDbsFileSystem
  → check has_dbs_storage_
    → if false: skip to MaybeCreateBTreeBackend()
    → if true:
      → look up DbsGroveStorage for grove_<scid>_kDbs
      → build CreateFileSystemOptions:
          .allocator = storage->dbs_client_resources()->allocator()
          .external_wal = storage->dbs_client_resources()->wal()
          .description = "Oplog file system for Grove <scid>"
      → call dbs->CreateFileSystem("oplog_dbs_fs_<scid>", options, cb)
        → FileSystemMgmtOp:
          → lookup /dbs/file_systems/oplog_dbs_fs_<scid> in config map
          → if not found: format filesystem, write config to config map
          → if found: start filesystem from existing config
          → create BlockStore::FileSystem instance
      → DbsFileSystemCreated callback:
          → store grove_->oplog_dbs_file_system_
          → create grove_->oplog_dbs_vfs_ (VFS wrapper)
      → DbsOplogFileSystemStartDone
        → MaybeCreateBTreeBackend()

MaybeCreateBTreeBackend
  → if FLAGS_forest_oplog_skip_btree_hosting: finish (no B-tree)
  → CHECK: not both BlockStore and DBS storages available
  → select backend storage type (kDbs if has_dbs_storage_)
  → create BTreeGroveBackend with vdisk_id = -1 * snapshot_chain_id
  → HostOplogMap (B-tree hosting)
```

**Source code:**
- Oplog backend hosting op:
  `ntnxdb_client/forest/grove_ops/grove_host_oplog_backend_op.cc`
  (`MaybeStartDbsFileSystem`, `DbsFileSystemCreated`,
  `MaybeCreateBTreeBackend`)
- Filesystem mgmt op:
  `util/util/distributed_block_store/file_system_mgmt_op.cc`
  (`StartImpl`, `LookupConfigMapDone`, `FormatFileSystemDone`)
- Grove members:
  `ntnxdb_client/forest/grove.h` (`oplog_dbs_file_system_`,
  `oplog_dbs_vfs_`, `IsOplogFileSystemHosted`,
  `IsOplogUsingStorage`)

### Dual DiskManager Architecture (OplogStore)

When external storage is enabled, the `OplogStore` creates **two DiskManager
instances** — one for metadata-volume-backed episodes and one for DBS-backed
episodes:

```cpp
disk_manager_external_storage_ =
  make_shared<DiskManager>(globals_, false /* using_dbs */);
disk_manager_dbs_ =
  make_shared<DiskManager>(globals_, true /* using_dbs */);
```

Each DiskManager gets a distinct placeholder disk ID from
`StargateUtil::GetExternalStorageOplogDiskId(using_dbs)`. This ID is embedded
in the episode's Medusa metadata (`primary_disk` field) so that subsequent
reads and flushes route to the correct DiskManager and VFS.

**Routing:** `OplogStore::GetExternalStorageDiskManager(disk_id)` inspects
the disk_id to determine `using_dbs`, then returns the appropriate
DiskManager.

**Source code:**
- OplogStore dual DiskManager creation:
  `cdp/server/stargate/oplog_store/oplog_store.cc` (constructor)
- DiskManager external-storage constructor:
  `cdp/server/stargate/oplog_store/disk_manager.cc` (second constructor)
- Disk routing:
  `cdp/server/stargate/oplog_store/oplog_store.cc`
  (`GetExternalStorageDiskManager`)

### Dual VFS in DistributedOplog

The `DistributedOplog` class receives both VFS pointers from the Grove via
`ExternalStorageVFS`:

```
struct ExternalStorageVFS {
  BlockStore::FileSystem::VFS *vfs;      // metadata volume VFS (may be null)
  BlockStore::FileSystem::VFS *dbs_vfs;  // DBS VFS (may be null)
};
```

On oplog backend hosting completion:
- `using_dbs_` is set to `true` if `dbs_vfs != nullptr`
- During **transition** to DBS (both VFS pointers set), two recovery ops
  run in parallel — one per VFS. Old episodes remain readable via the
  metadata-volume VFS; new episodes are created on the DBS VFS.
- New episodes always embed the DBS placeholder disk ID when `using_dbs_`
  is true.

**Source code:**
- ExternalStorageVFS struct:
  `cdp/server/stargate/distributed_oplog/distributed_oplog.h`
- Recovery with dual VFS:
  `cdp/server/stargate/distributed_oplog/distributed_oplog.cc`
  (`RecoverOplogStore`)
- Episode creation with disk ID:
  `cdp/server/stargate/distributed_oplog/distributed_oplog_store_write_op.cc`
  (calls `StargateUtil::GetExternalStorageOplogDiskId(using_dbs_)`)

### Per-Grove Named Block Layout (Including Oplog)

When oplog DBS is active, the per-entity named block map includes the oplog
filesystem superblock alongside the regular grove resources:

```
DBS Entity (shared by all groves)
├── grove_<scid>_wal               (8 named blocks, WAL incarnations)
├── grove_<scid>_allocator         (transaction log blocks)
├── grove_<scid> B-tree data       (vdisk block map nodes)
├── oplog_dbs_fs_<scid>SuperBlock  (oplog filesystem superblock, 2 blocks)
├── oplog_dbs_fs_<scid> data       (oplog episode data blocks)
├── grove_<scid2>_wal              (another grove)
├── oplog_dbs_fs_<scid2>SuperBlock
└── ... (all interleaved in shared regions)
```

**Log evidence (named block map with oplog superblocks):**
```
block_store.cc:1059] block store dbs_987_1: Named block map entry of component dbs_component:
  oplog_dbs_fs_104SuperBlock -> [ (793731072, 2) ]
  oplog_dbs_fs_106SuperBlock -> [ (705089536, 2) ]
  oplog_dbs_fs_108SuperBlock -> [ (666558464, 2) ]
  oplog_dbs_fs_110SuperBlock -> [ (666566656, 2) ]
```

Numbers like `(793731072, 2)` represent `(offset, num_blocks)` in 4KB units.

**Key log files and grep patterns:**

```bash
# Oplog DBS filesystem creation:
grep -a "Creating DBS oplog file system\|Successfully created DBS oplog file system" stargate.INFO*

# Oplog DBS filesystem creation failures:
grep -a "Failed to create DBS oplog file system" stargate.INFO*

# Oplog filesystem superblock named blocks:
grep -a "oplog_dbs_fs_.*SuperBlock" stargate.INFO*

# Oplog backend hosting overall:
grep -a "grove_host_oplog_backend_op.cc" stargate.INFO*

# Oplog map B-tree creation:
grep -a "Creating oplog_map backend on storage\|Starting to host the oplog_map backend" stargate.INFO*

# B-tree hosting skipped (flag set):
grep -a "Skipping oplog_map backend hosting" stargate.INFO*

# DBS filesystem config map operations:
grep -a "key_str=/dbs/file_systems/oplog_dbs_fs_" stargate.INFO*

# DBS filesystem format/start:
grep -a "File system not formatted\|File system already formatted\|Starting file system\|File system format failed" stargate.INFO*

# Dual DiskManager routing:
grep -a "GetExternalStorageDiskManager\|disk_manager_dbs\|disk_manager_external_storage" stargate.INFO*

# using_dbs_ flag in distributed oplog:
grep -a "using_dbs_.*transitioning_to_dbs\|Hosted distributed oplog backend" stargate.INFO*
```

**Failure propagation:**
- Oplog DBS filesystem creation failure → `GroveHostOplogBackendOp` fails
  with `kBlockStoreError` → oplog backend not hosted → DistributedOplog
  cannot be initialized → vdisk I/O fails
- Allocator or WAL failure in the grove's shared DBS client resources →
  affects both B-tree and oplog filesystem simultaneously
- DBS entity unavailable → oplog filesystem cannot read/write episodes →
  oplog writes fail → vdisk quiesces
- Filesystem config map lookup failure → filesystem cannot start on
  re-host → oplog unavailable until DBS config map is accessible

**Cross-service checks:**
- **DBS client resources**: The oplog filesystem shares the grove's allocator
  and WAL. If these are unhealthy, check the "DBS Client Resources Lifecycle"
  section above.
- **Oplog store DiskManager**: Verify the correct DiskManager is receiving
  I/O — check the placeholder disk ID in episode Medusa metadata.
- **Forest oplog hosting**: The oplog backend is hosted via Forest, so
  relinquish/leadership changes in the grove affect oplog availability.

**JIRA search keywords:**
`"grove_host_oplog_backend_op"`, `"oplog_dbs_fs_"`,
`"Creating DBS oplog file system"`, `"Failed to create DBS oplog file system"`,
`"oplog_map backend"`, `"File system format failed"`,
`"disk_manager_dbs"`, `"disk_manager_external_storage"`,
`"using_dbs_"`, `"ExternalStorageVFS"`,
`"oplog_dbs_file_system_"`, `"oplog_dbs_vfs_"`

---

## DBS Grove Storage Types

**What it does:** A Grove can use different storage backends depending on the
deployment configuration. The storage type determines how the grove's B-tree
data and metadata are persisted.

**Storage types:**
- `kDbs` — Uses the Distributed Block Store (external storage array volumes).
  Data stored as named blocks in DBS entities.
- `kBlockStoreOnExternalVolume` — Uses a dedicated metadata volume on the
  external storage array. Each grove gets a separate `BlockStore` instance
  backed by its own volume.
- `kRemote` — The grove does not host B-trees locally; it forwards requests
  to a remote Stargate that is the leader for this grove.
- `kMultiStorage` — Container for multiple child storages (used during
  transitions, e.g. migrating from metadata volume to DBS).

**Grep patterns:**
```bash
# Which storage type a grove is using:
grep -a "storage_type: k\|storage_id: grove_" stargate.INFO*

# Storage initialization:
grep -a "Initializing DBS storage\|Initializing block store on external volume\|Initializing remote storage" stargate.INFO*

# Storage transitions (multi-storage add/shutdown):
grep -a "AddStorage\|MaybeShutdownStorage\|MultiGroveStorage" stargate.INFO*
```

**JIRA search keywords:**
`"GroveStorageType"`, `"kDbs"`, `"kBlockStoreOnExternalVolume"`,
`"kRemote"`, `"kMultiStorage"`, `"DbsGroveStorage"`,
`"BlockStoreVolumeGroveStorage"`, `"RemoteGroveStorage"`,
`"MultiGroveStorage"`

---

## DBS Error Handling

**What it does:** DBS classifies errors into resumable (retried
automatically) and non-resumable (propagated to the caller or triggering a
FATAL). Understanding this classification helps triage whether a DBS error
is transient or terminal.

**Error classification (`HandleResumableError` in
`distributed_block_store.cc`):**
- **Resumable** (retried with delay): `kNotLeader`, `kRetry`, `kTimeout`
- **Non-resumable** (causes FATAL or propagates): everything else, including
  `kNoSpace`, `kCorrupt`, `kNotFound`

When a non-resumable error is returned from a DBS RPC, the allocator's
`HandleResumableError` returns `false`, and the caller FATALs with
"Unexpected error from [RPC name]".

**Key log patterns for DBS errors:**

```bash
# kNoSpace from the DBS entity leader (backing store exhausted):
grep -a "dbs_fb_rpc_svc_impl.cc.*kNoSpace" stargate.INFO*

# kNoSpace received by remote clients (grove allocators):
grep -a "remote_interface.cc.*kNoSpace\|allocator.cc.*kNoSpace" stargate.INFO*

# kNotLeader errors (entity migration in progress):
grep -a "kNotLeader.*entity_id" stargate.INFO*

# Backing store I/O errors:
grep -a "backing_store.*Terminating\|backing_store.*error" stargate.INFO*

# Unexpected errors (non-resumable, leads to FATAL):
grep -a "Unexpected error from" stargate.INFO*

# Count DBS errors per minute (for rate analysis):
grep -a "kNoSpace\|kCorrupt\|kNotLeader" stargate.INFO* | grep -oP "^[EIFW]\d{8} \d{2}:\d{2}" | sort | uniq -c
```

**Failure propagation (generic):**
```
DBS entity error (Layer 1)
  → Named block RPCs return error
    → grove allocators / WAL cannot proceed
      → WAL log writes fail
      → WAL internal filesystem format fails (new groves can't start)
      → B-tree operations fail
      → VDisk writes hang or fail
```

---

## DBS Entity Investigation — Step-by-Step

### Step 1 — Extract entities from error logs

From each DBS-related error or FATAL, extract:
- `id=<N>` — DBS instance ID
- `grove_<N>` — grove ID (= snapshot chain ID, scid)
- `entity_id=<E>` — DBS entity number
- `dbs_internal_wal_grove_<N>_wal` — internal WAL name
- `dbs_internal_fs_grove_<N>_wal` — internal filesystem name

### Step 2 — Identify the DBS leader

```bash
# The CVM running dbs_fb_rpc_svc_impl.cc is the entity leader:
grep -a "dbs_fb_rpc_svc_impl.cc.*id=<DBS_ID>" stargate.INFO*
```

All allocations go through the leader. If the leader CVM has resource
issues (OOM, disk full, volume offline), all groves across all CVMs are
affected.

### Step 3 — Build error timeline

```bash
# Aggregate DBS errors from ALL CVMs, sorted by time:
(grep -ah "kNoSpace\|kCorrupt\|kNotLeader\|Unexpected error" CVM1/stargate.INFO*; \
 grep -ah "kNoSpace\|kCorrupt\|kNotLeader\|Unexpected error" CVM2/stargate.INFO*; \
 grep -ah "kNoSpace\|kCorrupt\|kNotLeader\|Unexpected error" CVM3/stargate.INFO*) | sort | head -100

# Count per-minute rate:
... | grep -oP "^[EIFW]\d{8} \d{2}:\d{2}" | sort | uniq -c

# Count unique affected groves:
... | grep -oP "grove_\d+" | sort -u | wc -l
```

### Step 4 — Check for DBS init/volume issues

```bash
# Volume configuration issues:
grep -a "No volumes found in the distributed block store config" stargate.INFO*

# DBS entity hosting failures:
grep -a "Entity.*not hosted\|kNotLeader.*entity_id" stargate.INFO*

# DBS client resource failures:
grep -a "Failed to get DBS client resources" stargate.INFO*
```

### Step 5 — Distinguish new grove vs re-hosted grove

Check the archived stargate INFO logs for the grove's allocator init:

- **New grove** (never existed before):
  ```
  format_txn_log_=1   ← txn log being formatted fresh
  ```

- **Re-hosted grove** (existed, being recovered):
  ```
  format_txn_log_=0   ← txn log already exists, recovering
  Recovering transactions from txn log: txn_id_set->NumObjects()=N
  ```
  The `txn_id_set->NumObjects()` count shows pending transactions.
  Higher counts mean more recovery work and more internal WAL pressure.

### Step 6 — Correlate with workload and external storage

- Check background job logs for external storage space consumers
- Check NVMe-oF transport health
  (see [External Storage Volume Lifecycle](stargate-flows.md))
- Note any concurrent stargate crash-restart cycles — entity churn during
  restarts can cause transient DBS errors
