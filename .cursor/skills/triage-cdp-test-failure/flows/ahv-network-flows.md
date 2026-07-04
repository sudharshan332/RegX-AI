# AHV Host Investigation Flows

## AHV Host Network Troubleshooting (Live Debug)

**What it does:** AHV hosts run Open vSwitch (OVS) for network bridging,
with uplinks bonded to physical NICs. Network issues on AHV hosts can cause
CVM unreachability, UVM connectivity loss, or test harness communication
failures. This flow applies when triage indicates an AHV host has a
networking issue and the user confirms live access.

**Connecting to the AHV host:**
```bash
# From the paired CVM:
ssh root@192.168.5.1
```

**Key checks and grep patterns:**

```bash
# Boot history (multiple boots may indicate kernel panic / watchdog):
journalctl --list-boots

# System-level errors during last boot:
journalctl -b -1 --no-pager | grep -E \
  "panic|OOM|oom-kill|error|fail|br0|NetworkManager|ahv-setup-network|sshd|ip.*addr|ovs"

# Kernel-level hardware/driver errors:
journalctl -b -1 -k --no-pager | grep -E \
  "error|fail|link|eth|bond|mlx|nvme"

# Network activation and IP assignment:
journalctl -b -1 | grep "10.x.x.x"  # the AHV's external IP
journalctl -b -1 | grep -E "ovs|br0|bond|uplink"
journalctl -b -1 | grep "chrono\|chrony\|selectable"
```

**Failure propagation:**
- NM reports activation success but IP never reachable → possible causes:
  OVS datapath not forwarding, physical NIC / bond member didn't establish
  link, kernel networking stack silent failure
- AHV host unreachable → paired CVM cannot reach cluster services → test
  harness reports communication failures

**Distinguish kernel panic / OOM from false positives:** The test harness may
flag `kernel panic` or `oom-killer` from matching against `panic=30` in the
kernel command-line. Always verify via `journalctl` and `/var/crash/`.
