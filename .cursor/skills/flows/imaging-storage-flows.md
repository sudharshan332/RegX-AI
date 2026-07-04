# Imaging & Storage Flows

Investigation flows for AOS imaging, image creation, disk space,
Jarvis metadata, and boot disk configuration failures. These patterns
share foundation, image management, and storage subsystems.

---

## 7. AOS Imaging Failure

**Signature in logs:**
```
Failed to image ... with AOS build
```
or:
```
HYP URL/NOS URL does not exist
```
or foundation/imaging errors.

**Root cause:** AOS build URL inaccessible, corrupted build artifact,
hostname not resolved, filer down, partial download, or foundation
service issues.

**Investigation steps:**
1. Verify the `build_url` from `payload.resource_specs[].build` is
   accessible from the deployment network.
2. Check for HTTP errors when downloading the build.
3. Look for foundation logs in the deployment DEPLOY log.
4. For hostname resolution failures — file ticket to Network team.
5. Check image creation tasks for nested CVM and AHV images on the
   base cluster.

## 8. Image Creation Failure on Base Cluster

**Signature in logs:**
```
Timedout executing command ... acli ... image.create
```

**Root cause:** Image creation via acli timed out on the base cluster.
Can happen when the base PE is already registered with another PC, or
the source URL is unreachable.

**Investigation:** Try running the image create command on the base
cluster locally to reproduce.

## 9. Pre-Deployment Failure

**Signature in logs:**
```
Failed in pre deployment
```

**Root cause:** Not enough space on the base cluster for the
requested number of nested nodes.

**Investigation:** Check base cluster available space and retry with
fewer nodes or after freeing resources.

## 17. LVM / Root Partition Full on Base Host

**Signature in logs:**
```
LVM: No space left on device
```
or `lvcreate` commands fail during disk creation.

**Root cause:** LVM archives metadata updates in
`/etc/lvm/archive` on the base AHV host (L0), which can fill
the root partition. Also caused by unauthorized third-party tools
(Prometheus, Grafana, etc.) installed on the L0 host.

**Category:** `INFRA`

**Investigation steps:**
1. Check base AHV host root partition usage: `df -h /`.
2. Check LVM archive directory size:
   `du -sh /etc/lvm/archive/`.
3. Look for unauthorized software consuming space.

**Resolution:**
1. Clean up LVM archives on the L0 AHV host:
   ```
   vi /etc/lvm/lvm.conf
   # Set: retain_min = 0, retain_days = 0
   rm -f /etc/lvm/archive/*
   ```
2. Remove any unauthorized third-party tools from the L0 host.

## 18. Jarvis Metadata Out of Sync (NoneType / total_ssd: 0)

**Signature in logs:**
```
Failed to create disk in NVME pool
```
or:
```
NoneType object has no attribute 'keys'
```
Jarvis API shows `total_ssd: 0` for the base cluster even though
physical disks exist.

**Root cause:** Base cluster metadata in Jarvis is out of sync,
often occurring when a node was reimaged directly to a nested base
image without a proper Jarvis sync.

**Category:** `INFRA`

**Resolution:**
1. Reimage the node as a regular AOS cluster (Physical).
2. Perform a node refresh/sync in Jarvis to update hardware
   metadata.
3. Reimage the node back to the Nested AHV Base image.

## 22. Missing Separate Boot Disk (Nested 2.0)

**Signature in logs:**
Tests fail due to missing separate boot/data disks. Boot partition
(`sda4`) ends up on a disk intended for data.

**Root cause:** Nested AHV 2.0 does not default to a separate boot
disk. The boot partition shares a disk with the data partition.

**Jira reference:** ENG-842428

**Category:** `CONFIG`

**Resolution:**
1. **Post-deployment:** Use a Jita pre-run hook to remove the boot
   disk from the storage pool.
2. **Provisioning:** Request larger SSD sizes in the test config to
   prevent the boot disk from being selected as a data disk.
