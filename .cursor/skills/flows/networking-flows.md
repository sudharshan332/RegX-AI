# Networking & Connectivity Flows

Investigation flows for IP assignment, VLAN configuration, trunking,
and network compatibility failures. These patterns share the nested
network stack (DHCP, VLAN, AHV networking) as their common subsystem.

---

## 5. Nested VM IP Assignment Failure

**Signature in logs:**
```
Nested VMs are not getting IPs
```
or CVM/host VMs have no IP assigned (127.0.0.1 or empty).

**Root cause:** DHCP not enabled for the VLAN used to create the
nested VM network.

**VLAN resolution priority (highest to lowest):**
1. RDM tags: `rdm__nest_network_vlan_<VLAN_ID>` and
   `rdm__nest_network_name_<NETWORK_NAME>`
2. RDM UI payload
3. Static VLAN info from Jarvis (node tags on the base cluster)
4. Default: vlan.0

**Investigation steps:**
1. Identify which VLAN was used from the deployment log.
2. Verify DHCP is enabled on that VLAN.
3. If no DHCP: contact IT to enable DHCP on the static VLAN, or
   specify an alternate VLAN via RDM tags.
4. Check CVM console: `ifconfig eth0` — if no IP, check DHCP offers
   with `journalctl | grep DHCP`.
5. If CVM has IP but is not pingable: check routing with `route -n`
   on the CVM console. A `0.0.0.0` gateway or missing default route
   indicates the physical network switch configuration may not allow
   the VLAN. If using VLAN trunking, verify the specific VLAN is
   allowed on the upstream physical switch ports.

## 10. Failed to Create Marker File

**Signature in logs:**
```
Failed to create marker file
```

**Root cause:** VM-related issue — VM may not have received an IP.
Check VLAN details on the underlying cluster.

## 19. VLAN Trunking / Multi-VLAN Connectivity Failure

**Signature in logs:**
User VMs (UVMs) cannot communicate on VLANs other than the
management VLAN. Only the default network passes traffic; tagged
VLANs fail.

**Root cause:** The nested host (L1 AHV) virtual NIC is not
configured in trunk mode, so tagged VLAN traffic is dropped.

**Category:** `CONFIG`

**Investigation steps:**
1. Check if `Trunk` was enabled in the RDM deployment settings.
2. SSH to the L0 host and inspect the nested VM config file:
   `/home/nutanix/nested_ahv/vms/<NESTED_VM_UUID>` — look for
   `"mode": "trunk"`.

**Resolution:**
- **During deployment:** Enable the "Trunk" option in RDM
  deployment settings.
- **Post-deployment fix:**
  1. SSH to L0 host (Physical AHV).
  2. Stop nested VM: `~/cpvm/vm.py off <NESTED_VM_UUID>`
  3. Edit config: `/home/nutanix/nested_ahv/vms/<NESTED_VM_UUID>`
     — set `"mode": "trunk"`.
  4. Start nested VM: `~/cpvm/vm.py on <NESTED_VM_UUID>`

## 20. AHV 10.0+ NetworkManager Incompatibility (Nested 1.0)

**Signature in logs:**
Nested 1.0 cluster deployment fails on AHV 10.0+ base hosts.

**Root cause:** AHV 10.0 deprecated `network-scripts` in favor of
`NetworkManager`. Nested 1.0 relies on the legacy network-scripts.

**Jira reference:** PI-14306

**Category:** `CONFIG`

**Resolution:**
1. **Preferred:** Upgrade to Nested 2.0 — Nested 1.0 is deprecated
   on AHV 10.0+.
2. **Workaround:** Manually configure IP tunnels using `nmcli`.

## 21. SMSP / Managed Network UUID Missing

**Signature in logs:**
```
Managed network UUID is not present on the Nested AHV cluster
```

**Root cause:** SMSP (Self-Managed Service Platform) cluster
creation requires a managed network UUID from the nested PE, but
no matching network was configured.

**Category:** `CONFIG`

**Resolution:**
1. Reserve static IPs during RDM deployment.
2. Configure VLAN 0 on the nested PE with the reserved IPs.
3. Use the VLAN 0 UUID for the SMSP cluster creation.
