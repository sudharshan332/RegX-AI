# Base Cluster Diagnostics Reference

## Architecture

Nested AHV 2.0 base clusters are bare-metal servers running the AHV
hypervisor directly. They do **not** have CVMs or a full Nutanix cluster
stack. Instead, each base cluster host runs:

- **AHV hypervisor** (root@192.168.5.1 from the CPVM's internal bridge)
- **CPVM** (Cluster Prism VM) — a lightweight management VM used by
  RDM to create/manage nested VMs via Prism Element APIs

The CPVM is reachable at the `base_cpvm_ip` from the deployment
network. The AHV host is reachable via the internal bridge
(`192.168.5.1`) from the CPVM.

## When to Perform Base Cluster Diagnostics

The decision is made by the **Step 5b diagnostic-value gate** in
`SKILL.md` — this file describes *how* to run the investigation
once the gate has triggered, not whether to. Read `SKILL.md` Step
5b for the gate rules. In summary:

**Run** when any of these hold:

- The literal error mentions timeouts, hangs, slow I/O, RPC
  unreachable, connectivity drops, "service not responding," or
  "node lock"
- Failure occurred during VM creation, AOS imaging, CVM boot,
  genesis startup, or the cluster create RPC
- The deployment failed before the cluster reached a healthy steady
  state

**Skip** (and record a "skipped: <reason>" line in the report's
Base Cluster Diagnostics section header) when all of these hold:

- KISS 1–3 already produced a confident root cause in `CONFIG` or
  `INFRA-pool` (allocation failed before any VM existed)
- Cluster create succeeded with `metadata_store_status: kNormalMode`
  and the failure is a *post-cluster* product behavior (Flow #4 is
  the canonical example)
- The deployment is not Nested AHV 2.0 (bare-metal / Phoenix /
  ESXi)
- The CPVM is unreachable

## Identifying the Base Cluster

### From RDM API

Query the individual deployment:

```bash
curl -s "https://rdm.eng.nutanix.com/api/v1/deployments/<dep_id>"
```

The `nested_run_statistics.resource_details` field maps each nested
node to its base cluster:

```
Nested_AHV_<id>_0: base_pe_name=<base_cluster_name>, base_cpvm_ip=<ip>
```

### From Deployment DEPLOY Log

Search the deployment log for `nested_run_statistics`:

```bash
grep "nested_run_statistics" <deploy_log_file>
```

This reveals `base_pe_name`, `base_cpvm_ip`, vCPU count, and RAM
allocation for each nested node.

**Key detail:** Note which base cluster hosted the problematic nodes.
If multiple nodes failed and they were all on the same base cluster,
resource exhaustion or host-level issues on that base cluster are the
likely cause.

## SSH Access

### To the CPVM

```bash
sshpass -p 'nutanix/4u' ssh -o StrictHostKeyChecking=no \
  nutanix@<base_cpvm_ip>
```

Default credentials: `nutanix` / `nutanix/4u`

### From the CPVM to the AHV Host

```bash
ssh -o StrictHostKeyChecking=no root@192.168.5.1
```

The AHV host is always at `192.168.5.1` on the internal bridge
(`ens4` / `virbr0` interface on the CPVM side, bridged to `br0` on
the host side).

### Convenience One-Liner (from workstation)

```bash
sshpass -p 'nutanix/4u' ssh -o StrictHostKeyChecking=no \
  nutanix@<base_cpvm_ip> \
  "ssh -o StrictHostKeyChecking=no root@192.168.5.1 '<command>'"
```

## Available Diagnostic Data on the AHV Host

### 1. sar (System Activity Reporter) — `/var/log/sa/`

sar data is collected every 10 seconds and stored in
`/var/log/sa/saDD` (where DD is the day of month). This is the
**primary diagnostic tool** for retroactive resource analysis.

Available sar reports:

| Flag | Report | Use Case |
|------|--------|----------|
| `-u` | CPU utilization | Detect CPU saturation on the host |
| `-r` | Memory utilization | Detect memory pressure / exhaustion |
| `-q` | Load average and run queue | Correlate load spikes with failures |
| `-W` | Swap activity | Detect swapping (should be zero — no swap configured) |
| `-dp` | Block device I/O | Detect storage contention on NVMe/disks |
| `-n DEV` | Network interface stats | Detect network throughput issues |
| `-n EDEV` | Network errors | Detect dropped packets, errors |
| `-B` | Paging statistics | Detect memory reclaim pressure |
| `-b` | I/O transfer rate | Overall I/O activity |

**Standard query pattern** — when the Step 5b gate has triggered the
investigation, run **all six** queries below. Replace `saDD` with the
failure day and adjust `-s`/`-e` to bracket the failure window. Start
the window ~10 minutes before the failure timestamp — resource
contention during genesis startup often precedes the actual cluster
create timeout by several minutes.

If any sar category is unavailable (file rotated past retention, host
just rebooted, permission denied), record `<not available — <reason>>`
for that category in the report's Base Cluster Diagnostics table
rather than fabricating values.

```bash
# CPU utilization around the failure window
sar -u -f /var/log/sa/sa30 -s 02:30:00 -e 02:50:00

# Memory utilization
sar -r -f /var/log/sa/sa30 -s 02:30:00 -e 02:50:00

# Load average
sar -q -f /var/log/sa/sa30 -s 02:30:00 -e 02:50:00

# Disk I/O (named devices)
sar -dp -f /var/log/sa/sa30 -s 02:30:00 -e 02:50:00

# Network throughput (filter to br0, eth0, virbr0, vnet interfaces)
sar -n DEV -f /var/log/sa/sa30 -s 02:30:00 -e 02:50:00

# Network errors (drops, collisions, carrier errors)
sar -n EDEV -f /var/log/sa/sa30 -s 02:30:00 -e 02:50:00
```

**Interpreting results:**

- **CPU**: On a 64-CPU host, aggregate `%user + %system` above 50%
  across all cores indicates significant contention. Per-VM CPU
  scheduling delays may occur even below this threshold.
- **Memory**: `%memused` above 95% means the host is running near
  capacity. AHV hosts running many nested deployments commonly sit at
  99%+. Look for `kbmemfree` dropping below ~500MB for critical
  pressure.
- **Load average**: `ldavg-1` exceeding 2x the CPU count (e.g., >128
  on 64 CPUs) indicates severe contention. Rising load that correlates
  with the failure window is a strong signal.
- **I/O**: `await` (average I/O wait time in ms) above 10ms on NVMe
  devices suggests storage bottleneck. Check `%util` approaching 100%.
- **Network throughput**: On `eth0` or `br0`, throughput above 80% of
  link speed indicates saturation. For nested deployments, inter-CVM
  RPC traffic traverses `virbr0`/`vnet*` interfaces — check these for
  unusual spikes that correlate with the failure.
- **Network errors**: Any non-zero `rxdrop/s`, `txdrop/s`, or
  `rxerr/s`/`txerr/s` on `eth0`, `br0`, or `virbr0` during the
  failure window is significant. Drops on `vnet*` interfaces indicate
  VM-level network issues.

### 2. System Logs — `/var/log/messages`

Contains kernel messages, AHV agent logs, and hardware events. Useful
for OOM kills, hardware errors, and kernel warnings.

```bash
# Check for OOM kills
dmesg -T | grep -i "oom\|out of memory\|killed process"

# Check messages around the failure window (adjust date pattern)
grep "Mar 30 02:3[7-9]\|Mar 30 02:4[0-1]" /var/log/messages
```

Older messages may be compressed in `/var/log/messages.1.gz` — use
`zgrep` for those.

### 3. VM Information — `virsh`

List VMs running on the host:

```bash
virsh list
```

Each nested VM (CVM, AHV host) appears by its UUID. The CPVM appears
as `NTNX-CPVM-CVM`.

For current resource consumption of each VM:

```bash
virsh domstats --cpu-total --balloon
```

### 4. Current System State

```bash
# Current memory
free -g

# Current CPU count
nproc

# Uptime and load
uptime
```

### 5. AHV-Specific Logs

| Log Path | Contents |
|----------|----------|
| `/var/log/ahv-host-agent.log` | AHV host agent (collectors, monitors, health checks) |
| `/var/log/ahv-gateway/ahv-gateway.log` | AHV gateway operations |
| `/var/log/ahv/frodo_iscsi_logs/` | iSCSI-related logs |
| `/var/log/ahv/hwinfo/` | Hardware information |
| `/var/log/journal/` | systemd journal (use `journalctl`) |

### 6. Network Diagnostics

```bash
# Check bridge and interface status
ip link show
ovs-vsctl show

# Check ARP table for nested VMs
ip neigh show
```

## Triage Procedure

When performing base cluster diagnostics during a deployment triage,
run **all** of the steps below. Do not skip any sar category — all
four resource dimensions (CPU, memory, disk I/O, network) must be
checked to produce a complete picture.

### Step 1: Identify the Failure Window

From the deployment DEPLOY log, extract the UTC timestamps for:
- When the failing operation started (e.g., `cluster create` command)
- When the timeout/failure was detected
- Use a window starting ~10 minutes **before** the failure and
  ending ~5 minutes **after**. Resource contention during genesis
  startup or AOS imaging can precede the actual cluster create
  timeout by several minutes — the causal window is often earlier
  than the failure itself.

### Step 2: Determine the Day-of-Month sar File

The failure timestamp gives you the day of month. The sar file is at
`/var/log/sa/saDD` (e.g., `sa30` for March 30).

### Step 3: Check CPU and Load

```bash
sar -u -f /var/log/sa/sa<DD> -s <start> -e <end>
sar -q -f /var/log/sa/sa<DD> -s <start> -e <end>
```

Look for:
- CPU utilization spikes correlating with the failure window
- Load average climbing steadily (indicates VM startup pressure)
- Run queue depth increasing

### Step 4: Check Memory

```bash
sar -r -f /var/log/sa/sa<DD> -s <start> -e <end>
```

Look for:
- `kbmemfree` dropping below 1GB
- `%memused` at 99%+ (common but still worth noting as contributing
  factor)
- Sudden memory drops (VMs being destroyed after failure)

### Step 5: Check Disk I/O

```bash
sar -dp -f /var/log/sa/sa<DD> -s <start> -e <end>
```

Look for:
- High `await` times on NVMe or pool devices
- `%util` approaching 100% on any device

### Step 6: Check Network

```bash
sar -n DEV -f /var/log/sa/sa<DD> -s <start> -e <end>
sar -n EDEV -f /var/log/sa/sa<DD> -s <start> -e <end>
```

Look for:
- Throughput spikes on `eth0`/`br0` approaching link capacity
- Any non-zero `rxdrop/s`, `txdrop/s`, `rxerr/s`, `txerr/s` on
  `eth0`, `br0`, `virbr0`, or `vnet*` interfaces
- Unusual traffic patterns on `virbr0`/`vnet*` (inter-CVM bridge
  traffic) that correlate with the failure window

### Step 7: Check for OOM / Kernel Events

```bash
dmesg -T | grep -i "oom\|killed\|error\|warn" | tail -20
grep "<Mon> <DD> <HH>:<MM>" /var/log/messages | \
  grep -iv "DHCP\|systemd\|sshd\|chronyd\|pam_unix" | head -20
```

### Step 8: Summarize Findings

Include in the triage report under a **Base Cluster Diagnostics**
section:
- Base cluster name and CPVM IP
- Host CPU count and total RAM
- Key sar metrics during the failure window for **all four**
  categories: CPU%, load avg, memory free, disk await/util,
  network throughput/errors
- Whether resource pressure was a contributing factor
- Whether the host was shared with other active deployments

## Correlation Guidance

### Base Cluster Overload → Nested CVM Issues

When a base cluster host is under resource pressure:

1. **CPU contention** → Nested CVMs may experience scheduling delays.
   Genesis service startup takes longer, and RPC timeouts during
   `cluster create` become more likely.

2. **Memory pressure** → KVM/QEMU may not be able to allocate
   balloon memory for new VMs. Existing VMs may experience ballooning
   pressure, causing internal OOM conditions.

3. **I/O contention** → Nested CVM disk operations (Cassandra startup,
   genesis log writes) slow down. This can cause service startup
   timeouts.

4. **Network contention** → Bridge/OVS throughput limits. If many VMs
   are performing imaging or large data transfers simultaneously,
   nested CVM network RPCs may time out.

### Typical Pattern: Load Spike During Deployment

When multiple nested deployments run concurrently on the same base
cluster host:

- Pre-deployment: host at ~5% CPU, load avg ~2
- During VM boot and AOS imaging: CPU rises to 10-15%, load climbs
  to 7-9 as VMs start competing for resources
- During cluster create: load may peak if genesis on all CVMs is
  starting services simultaneously
- After failure/cleanup: load drops sharply as VMs are destroyed

A steadily climbing load average that correlates with the deployment
window is a strong indicator that host resource contention contributed
to the failure, even if no single metric shows critical exhaustion.
