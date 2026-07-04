# Post-Cluster & Prism Central Flows

Investigation flows for failures after cluster creation succeeds:
post-create configuration, Prism Central deployment, and PE-PC
registration.

---

## 13. Post-Cluster-Create Failure

**Signature in logs:**
```
Cluster created successfully
```
followed by later errors in configuration steps.

**Root cause:** Cluster was created but post-create configuration
failed (DNS, NTP, Prism password, PC registration, etc.).

**Investigation steps:**
1. Look past the cluster create success message for subsequent errors.
2. Check if the failure is in `set_cluster_external_ip`,
   `set_dns_servers`, `set_ntp_servers`, or similar operations.

## 14. Prism Central Deployment Failure

**Common PC failure signatures:**

| Signature | Likely Cause |
|---|---|
| `Upgrade failed: Command: ... upgrade_status` | Build issue; contact PC team |
| `HTTP Auth Failed get https://pc_ip:9440/...` | Prism not up on PC (502/503/403) |
| `Max attempts reached while creating boot image` | PE already registered with another PC |
| `Attempts to create NOS cluster failed` | PC VM IP unreachable or multicluster create failed |
| `PC VM didn't get a proper IP` | DHCP exhausted; VM got 127.0.0.1 |
| `Connection Error ... Unable to connect to port 22` | DHCP pool exhausted |
| `The Prism Central VM is not reachable` | IP not assigned, invalid VLAN, or ntpd not started |
| `PC Creation failed while polling on the task` | One-click deployment API failure |
| `Upgrade failed: Failed to run wget` | PC upgrade URL not accessible from node network |
| `Software ... already exists on the cluster` | Parallel PC deploys on same PE, or stale software |
| `Image creation failed` | Insufficient storage on base cluster for PC image |

**Image creation failure investigation:** If the PC deployment
aborts during image creation, check storage on the base cluster:
`allssh "df -h"` and `curator_cli get_storage_summary`. Ensure
there is sufficient space in the storage container for the PC image.

**PC resource requirements (1-node one-click):**

| Size | RAM (GB) | CPU | Disk (GB) |
|---|---|---|---|
| tiny | 16 | 4 | 200 |
| small | 26 | 6 | 500 |
| large | 44 | 10 | 2500 |

For 3-node PC: multiply by 3. Ensure the host PE has sufficient
resources before deploying.

## 15. PE-PC Registration Failure

**Common registration failure signatures:**

| Signature | Likely Cause |
|---|---|
| `Error: Remote connection missing` | Build issue; contact PC team |
| `The username or password entered is incorrect` | PC password reset failed |
| `Failed to register to Prism Central : Service Unavailable` | PC build issue |
| `NOS version ... is not compatible with the NOS version ... of the Prism Central` | PE version > PC version; provide compatible builds |
| `Prism Central is unreachable` | PC not reachable; check network/build |
| `Timedout executing ... stargate --version` | Stargate service issue on PC |
| `Zeus configuration cache is not created` | PC build issue |
