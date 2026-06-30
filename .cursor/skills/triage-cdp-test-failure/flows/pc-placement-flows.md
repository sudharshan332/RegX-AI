# PC Placement Investigation Flows

## PC Placement Solver: External Storage Capacity Check

*Auto-promoted from telemetry (user-guided). Needs human review.*

**What it does:** The PC go_lazan placement solver evaluates storage capacity on PE
clusters during VM scheduling. On external storage clusters (Dell
PowerStore, Pure, etc.), the PE has small NFS cache disks but actual
storage resides on the external array. Storage capacity flows from the
external storage interface through Curator and IDF to the placement
solver.

**Internal operation flow:**
```
ExternalStorageInterface::GetContainerStats()
  -> Curator ExternalStorageUsageCollector (publishes to IDF via AddGenericStat)
    -> IDF cluster table [storage.capacity_bytes, storage.usage_bytes]
      -> GoLazan cluster_stats_collector (queries IDF, populates Cluster.storage_capacity/usage)
        -> PlacementSolver ClusterStorageFilter (checks usageMB + vmStorageMB <= capaMB)
          -> Metropolis go_lazan_task (translates solver error to API error code)
```

**Key log files and grep patterns:**

```bash
Missing stats for container.*in arithmos response
storage.capacity_bytes
storage.usage_bytes
Missing cluster storage stats for cluster
suspicious zero storage capacity
Cluster capacity from bulk stats
```

**Triage steps:**
1. Check PC metropolis.out for go_lazan_task ScheduleVm acquire errors
   (error 34402 = storage shortage)
2. Check PE stargate.out for missing storage stats in arithmos response
   for external storage containers
3. Check PE zeus_config for external_storage_id/external_storage_uuid on
   containers to confirm external storage is in use
4. Check PE castor log for external storage array capacity values —
   anomalous values (zero, sentinel, or missing) indicate stats
   reporting failure
5. Check PE dependencies.yml to determine if the build includes known
   external storage stats reporting fixes
6. Verify VM deployment works via PE/ACLI — success confirms the issue
   is in PC placement solver path, not actual storage shortage
7. Trace GoLazan cluster_stats_collector to understand storage stats
   fallback behavior when IDF stats are missing
8. Trace PlacementSolver ClusterStorageFilter to understand the storage
   capacity check logic
9. Search JIRA for known external storage stats reporting bugs
   applicable to the target AOS version
10. Trace Curator ExternalStorageUsageCollector to understand how
   container stats flow to IDF

**Failure propagation:**
- ExternalStorageInterface::GetContainerStats returns invalid capacity
  (sentinel or zero) -> Curator ExternalStorageUsageCollector cannot
  publish valid stats -> IDF cluster table missing
  storage.capacity_bytes/usage_bytes -> GoLazan cluster_stats_collector
  fallback sets capacity to pending VM aggregate only -> PlacementSolver
  ClusterStorageFilter rejects all clusters -> error 34402
- When IDF has no storage stats for a cluster, GoLazan sets
  StorageCapacity=StorageUsage=pending_vm_aggregate, leaving zero
  headroom for new VMs

**Cross-service checks:**
- When PC placement solver returns 34402, check PE stargate.out for
  missing storage stats in arithmos response to confirm stats are not
  being published
- Cross-reference PE external_storage_report.txt for errors indicating
  external storage reporting is broken on the build
- Check PE castor log for external storage array capacity values —
  anomalous values (zero, sentinel, or missing) indicate stats reporting
  failure
- Check PE dependencies.yml to determine if the build includes known
  external storage stats reporting fixes

**Service dependencies** *(review for dependency map update):*
- externalstorageinterface -> curator: GetContainerStats provides external storage capacity and usage to ExternalStorageUsageCollector
- curator -> idf: ExternalStorageUsageCollector publishes storage.capacity_bytes and storage.usage_bytes to IDF cluster table
- golazan -> idf: Queries IDF cluster table for storage stats to populate solver Cluster spec
- golazan -> placementsolver: Passes Cluster.storage_capacity/usage to placement solver
- placementsolver -> metropolis: Returns placement result with kNotEnoughStorage error if storage check fails
- metropolis -> golazan: Calls ScheduleVmAcquire via GoLazan client for VM placement

**JIRA search keywords:**
`"go_lazan_task"`, `"Not enough storage available for VM"`, `"ScheduleVm
acquire"`, `"placement failed"`, `"external storage"`, `"34402"`,
`"GetContainerStats"`, `"ClusterStorageFilter"`,
`"storage.capacity_bytes"`, `"Missing stats for container"`,
`"ExternalStorageUsageCollector"`
