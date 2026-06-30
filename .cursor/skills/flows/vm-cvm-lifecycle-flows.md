# VM & CVM Lifecycle Flows

Investigation flows for failures during nested host VM creation,
CVM boot, and host resource exhaustion. These patterns share base
cluster Prism API and CVM boot pipelines as their common subsystems.

---

## 4. Nested Host VM Creation Failure

**Signature in logs:**
```
Failed to create VM ... on base cluster
```
or:
```
No host has enough available memory for VM <name> that uses
<N> vCPUs and <RAM> MB of memory
```
or Prism API errors during VM creation.

**Root cause:** Base cluster Prism API failure, resource exhaustion
on the base cluster, or networking issues.

**Investigation steps:**
1. Check which base cluster was used (from
   `nested_run_statistics.resource_details`).
2. Check the deployment DEPLOY log for Prism API error responses.
3. Verify base cluster has sufficient resources (CPU, RAM, storage).
4. If RAM exhaustion: delete unused UVMs on the base cluster, or
   specify nodes with more RAM in the resource spec.

## 6. Nested CVM Not Responding / Boot Failure

**Signature in logs:**
```
Nested CVM is not responding
```
or:
```
Timeout waiting for CVM: <ip> to be accessible
```
or SSH timeout to nested CVM IPs.

**Investigation steps:**

1. **Identify the correct host log.** For multi-node deployments,
   map the failed CVM IP to its host IP (search for `HOST IP` in
   the DEPLOY log). Access the L1 AHV host logs at:
   `entity_logs/retry_0/<cluster>/nested_host_log_<host-ip>/
   var_log.tar.gz`.
2. **Check CVM serial console output.** Look for
   `/var/log/NTNX.serial.out.0` in the L1 AHV host logs. If this
   file is missing, the CVM installation likely failed completely.
3. **Check CVM installation on L1 AHV host.** In the host's
   `/var/log/messages`:
   - Installation: `grep "ahv-install-cvm" /var/log/messages` —
     look for `svm_rescue is successful`.
   - Configuration: `grep "ahv-configure-cvm" /var/log/messages`.
   - Definition: `grep "ahv-define-cvm" /var/log/messages`.
4. **Verify build compatibility.** Ensure the AHV build is
   bundled/compatible with the AOS version (e.g., deploying AOS 6.8
   with an older AHV 9.0 build will fail).
5. **Check CVM RAM.** If CVM is stuck at grub or failing to boot,
   increase the RAM assigned to the CVM. Check CPU passthrough
   settings in the nested VM definition.
6. **Live console check** (if cluster not yet released). Login to
   base PE Prism, open console of the nested CVM:
   - `ifconfig eth0` (IP assignment)
   - Ping default gateway
   - `route -n` (routing table)
7. Check if acropolis is crashing:
   `allssh cat ~/data/logs/acropolis.FATAL`
8. Ping nested AHV host IP (192.168.5.1) — if not responding, check
   if nested AHV VM has an IP (`ifconfig tun0` on host).

**Note:** If the failed deployment has already been released/cleaned
up, the nested host is deleted — you must rely on the collected
entity logs rather than live ping/SSH tests.

## 16. General Plugin — Insufficient Host RAM

**Signature in logs:**
```
No host has enough available memory for VM <name> that uses
<N> vCPUs and <RAM> MB of memory
```

**Applies to:** Prism Central, IAM Cluster, Selenium VM, Atlas VM,
AGS Cluster, Nested AHV.

**Resolution:**
1. Delete unused UVMs/entities on the base cluster.
2. Specify nodes with more RAM via "Preferred Nodes" in RDM UI.
3. For nested deployments: increase nested host RAM in the resource
   spec to accommodate all co-deployed entities.
