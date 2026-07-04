# Failure Patterns Reference

**Index file** — failure categories, reason codes, flow directory,
and shared triage utilities. Read this first to identify which
subsystem is involved, then read the specific flow file from `flows/`
for detailed investigation steps.

## Organization Principles

This file is the index. Detailed investigation flows live in
`flows/*.md`, organized by deployment subsystem. Each flow file
describes how that subsystem fails, what to check, and how failures
propagate.

**Guard rails:**
- Never add a new pattern directly to this file — add it to the
  relevant flow file in `flows/`.
- The bar for a new flow file is "a fundamentally different
  deployment subsystem," not "a new error message."
- Flow files grow by accumulating triage knowledge (new log patterns,
  failure modes, investigation steps), not by cataloging every error
  ever seen.

---

## Failure Categories

RDM classifies deployment failures into categories via the
`failure_analysis.category` field. Understanding the category helps
direct the investigation.

| Category | Meaning | Who to Engage |
|---|---|---|
| `PRODUCT` | AOS, hypervisor, or genesis bug | Component team (Genesis, Stargate, etc.) |
| `INFRA` | Infrastructure issue (pool exhaustion, network, base cluster) | DIAL Infra / Pool admin |
| `PLUGIN` | RDM deployer plugin bug | RDM / NuCloud team |
| `CONFIG` | Invalid deployment spec or configuration | Requestor / test framework |

## Failure Reason Codes

The `failure_analysis.error_metadata.RDM.reason` field provides a
more specific failure classification:

| Reason | Source | Description |
|---|---|---|
| `NESTED_CLUSTER` | `PLUGIN::NESTED_AHV` | Cluster creation failed on nested SVMs |
| `NESTED_IMAGING` | `PLUGIN::NESTED_AHV` | AOS imaging failed on nested CVMs |
| `NESTED_HOST_CREATION` | `PLUGIN::NESTED_AHV` | Failed to create nested host VMs on base cluster |
| `NESTED_CVM_CREATION` | `PLUGIN::NESTED_AHV` | Failed to create nested CVM VMs |
| `NESTED_HOST_BOOT` | `PLUGIN::NESTED_AHV` | Nested host failed to boot |
| `FOUNDATION` | `PLUGIN::PHOENIX` | Foundation imaging failure |
| `CLUSTER_CREATE` | `PLUGIN::NOS_CLUSTER` | Cluster create command failure |
| `POST_CLUSTER` | `PLUGIN::NOS_CLUSTER` | Post-cluster-create config failure |
| `RESOURCE_ALLOCATION` | `RM_WORKER` | Resource pool allocation failure |
| `VALIDATION` | `VALIDATOR` | Spec validation failure |
| `EXTERNAL_STORAGE_REGISTER` | `PLUGIN::EXTERNAL_STORAGE` | External storage (Pure / array) register failure against a freshly created PE |

---

## Flow Directory

Investigation flows are in the `flows/` directory. Read the specific
flow file **on demand** when the failure matches that subsystem — do
not read all flows upfront. The Pattern # → flow-file mapping is in
the Quick Pattern Lookup table below; this directory just names the
files and their scope.

| Flow Name | File |
|---|---|
| Cluster Create (genesis, node lock, timeouts, NOSCluster instantiation) | [flows/cluster-create-flows.md](flows/cluster-create-flows.md) |
| VM & CVM Lifecycle (host VM creation, CVM boot, RAM) | [flows/vm-cvm-lifecycle-flows.md](flows/vm-cvm-lifecycle-flows.md) |
| Networking & Connectivity (IP, VLAN, trunking, SMSP) | [flows/networking-flows.md](flows/networking-flows.md) |
| Imaging & Storage (AOS imaging, LVM, Jarvis, boot disk) | [flows/imaging-storage-flows.md](flows/imaging-storage-flows.md) |
| Orchestration & Validation (resource allocation, spec) | [flows/orchestration-validation-flows.md](flows/orchestration-validation-flows.md) |
| Post-Cluster & Prism Central (config, PC deploy, PE-PC) | [flows/post-cluster-pc-flows.md](flows/post-cluster-pc-flows.md) |
| External Storage Register (Pure / array, post-cluster) | [flows/external-storage-flows.md](flows/external-storage-flows.md) |

### Quick Pattern Lookup (Canonical Signature Index)

This table is the **canonical** signature → flow mapping. Flow files
may have richer multi-line signature blocks for matching ambiguous
failures, but the routing decision is made here. When a new pattern
is added, this table is the source of truth — flow-file headers and
this table must agree on Pattern # and Flow File.

Use this table to jump from a log signature to the right flow file:

| Signature | Pattern # | Flow File |
|---|---|---|
| `RPC to acquire node lock on SVM ... timed out` | 1 | cluster-create-flows |
| `Failed to reach Genesis on the node` | 2 | cluster-create-flows |
| `Timedout executing command ... cluster ... create` | 3 | cluster-create-flows |
| `Unable to instantiate the NOSCluster object with cluster name` / `Failed while fetching valid value for 'memory_capacity_in_bytes'` / `acropolis_connection_state: 'kDisconnected'` after cluster create | 4 | cluster-create-flows |
| `Failed to create VM ... on base cluster` | 4 | vm-cvm-lifecycle-flows |
| `Nested VMs are not getting IPs` | 5 | networking-flows |
| `Timeout waiting for CVM: ... to be accessible` | 6 | vm-cvm-lifecycle-flows |
| `Failed to image ... with AOS build` | 7 | imaging-storage-flows |
| `Timedout executing ... acli ... image.create` | 8 | imaging-storage-flows |
| `Failed in pre deployment` | 9 | imaging-storage-flows |
| `Failed to create marker file` | 10 | networking-flows |
| `No free nodes exist in the pool` | 11 | orchestration-validation-flows |
| `HYP URL does not exist` | 12 | orchestration-validation-flows |
| `Cluster created successfully` (then later errors) | 13 | post-cluster-pc-flows |
| PC failure signatures (see flow file) | 14 | post-cluster-pc-flows |
| PE-PC registration signatures (see flow file) | 15 | post-cluster-pc-flows |
| `No host has enough available memory` | 16 | vm-cvm-lifecycle-flows |
| `No space left on device` / `lvcreate` | 17 | imaging-storage-flows |
| `Failed to create disk in NVME pool` / `NoneType` | 18 | imaging-storage-flows |
| Tagged VLANs fail / trunk mode | 19 | networking-flows |
| Nested 1.0 fails on AHV 10.0+ | 20 | networking-flows |
| `Managed network UUID is not present` | 21 | networking-flows |
| Missing separate boot/data disks | 22 | imaging-storage-flows |
| `External storage creation not allowed in HCI mode` (HTTP 400 from `/api/nutanix/v3/external_storage/create`) — spec missing `diskless_cvm: true` | 23 | external-storage-flows |

---

## General Maintenance Commands

Quick reference for common maintenance operations on nested
deployments:

| Action | Command / Location |
|---|---|
| Fix host SSH | `fix_host_ssh` (run on CVM to fix passwordless SSH) |
| Reset nested VM | `acli vm.reset *Nested-AHV-VM-Name*` (run on base AHV) |
| Check foundation log | `/home/nutanix/foundation/log/foundation.log` |
| Check genesis log | `/home/nutanix/data/logs/genesis.out` |
| Check base cluster storage | `allssh "df -h"` and `curator_cli get_storage_summary` |
| Stop nested VM on L0 | `~/cpvm/vm.py off <NESTED_VM_UUID>` |
| Start nested VM on L0 | `~/cpvm/vm.py on <NESTED_VM_UUID>` |
| Nested VM config path | `/home/nutanix/nested_ahv/vms/<NESTED_VM_UUID>` |

---

## Deployment Phases (Nested AHV 2.0)

The Nested AHV 2.0 plugin executes these phases in order. When reading
the deployment DEPLOY log, these phases appear as log sections:

1. **Setup** — Log file setup, spec parsing
2. **Resource Allocation** — Get resources from pool via RM Worker
3. **VM Creation** — Create nested host and CVM VMs on base cluster
4. **AHV Boot** — Boot nested hosts with AHV ISO
5. **CVM Boot** — Boot nested CVMs
6. **AOS Imaging** — Image CVMs with AOS build
7. **Pre-Cluster-Create** — SSH verification, network checks
8. **Cluster Create** — Run `cluster create` command on a CVM
9. **Post-Cluster-Create** — DNS, NTP, passwords, virtual IP config
10. **PC Registration** — Register with Prism Central (if configured)
11. **Completion** — Mark deployment as successful

## Correlating Logs Across Services

When investigating a failure, cross-reference timestamps across
multiple log files:

1. Start with the **deployment DEPLOY log** to find the failure
   timestamp.
2. Check the **poller log** at the same timestamp to see what state
   the deployment was in.
3. Check the **deployer log** to see if the orchestrator detected
   the failure.
4. Check **entity logs** for CVM/host-level details around the same
   time.

## Common grep Patterns

| What to find | Pattern |
|---|---|
| Errors | `ERROR\|CRITICAL\|FATAL` |
| Tracebacks | `Traceback\|raise\|Exception` |
| Cluster create | `cluster.*create\|sm_lock_nodes\|cluster create workflow` |
| Failure analysis | `failure_analysis\|FAILED` |
| SSH issues | `ssh\|Connection refused\|timed out\|unreachable` |
| Genesis issues | `genesis\|Genesis\|genesis_utils` |
| Foundation | `foundation\|imaging\|phoenix` |
| VM creation | `create_vm\|vm.*create\|Prism` |
| Network issues | `network\|VLAN\|subnet\|IP address` |
| Resource issues | `resource\|capacity\|exhausted\|allocation` |
| LVM / disk space | `No space left on device\|lvcreate\|lvm` |
| CVM boot stages | `ahv-install-cvm\|ahv-configure-cvm\|ahv-define-cvm\|svm_rescue` |
| CVM serial output | `NTNX.serial.out` |
| Jarvis metadata | `total_ssd\|NoneType\|NVME pool` |
| VLAN trunk mode | `trunk\|mode.*trunk` |
| Managed network | `Managed network UUID` |
| Boot disk | `sda4\|boot.*disk\|storage pool` |
| Host IP mapping | `HOST IP` |
