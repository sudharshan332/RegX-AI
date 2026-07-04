# Orchestration & Validation Flows

Investigation flows for failures during resource allocation and
spec validation — stages that occur before any VMs are created.

---

## 11. Resource Allocation Failure

**Signature in API:**
- `status: FAILED`, stages ends at `REQUESTING_RESOURCES`
- Messages: "No free nodes exist in the pool", "Could not find
  clusters with min_nodes X"

**Root cause:** Resource pool has insufficient capacity for the
requested deployment.

**Common messages and meanings:**
- "No free nodes exist in the pool" — pool nodes are all in use,
  disabled, or part of static clusters.
- "Could not find clusters with min_nodes X" — after applying all
  constraints (hardware model, etc.), not enough matching nodes.
- "Could not get lock on the pool" — internal RM concurrency; not
  an error, just retry.

**Investigation steps:**
1. Check `rm_worker/` log for allocation errors.
2. Verify the requested resources (`resource_usage_request.overall`)
   against pool capacity.
3. Check if the pool is paused or has pending releases.
4. For nested 2.0: verify base clusters have available capacity.

## 12. Validation Failure

**Signature in API:**
- `status: FAILED`, stages ends at `PENDING`
- Messages: "HYP URL does not exist", "Adding new request failed"

**Root cause:** Deployment spec failed validation.

**Common validation failures:**
- Build URL 404 / not accessible from all DCs
- QMS credit limit exceeded
- Static IP limit exceeded
- `Reached timeout[15 minutes] while trying to find the number of
  static IPs required` — nodes missing static VLAN tags in Jarvis,
  or IPs exhausted in the VLAN
- `Got all pingable IPs from IPAM` — IPs marked as free in IPAM are
  actually in use (reserved outside IPAM)

**Investigation steps:**
1. Check `validator/` log for specific validation error.
2. For build URL issues: verify the URL is accessible.
3. For static IP issues: check Jarvis node VLAN tags and IPAM
   availability.
