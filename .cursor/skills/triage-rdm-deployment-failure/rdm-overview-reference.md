# RDM Overview Reference

## What is RDM?

RDM (Resource Deployment Manager) is the internal service that
orchestrates cluster deployments for test infrastructure. It handles
resource allocation, imaging, cluster creation, and release. Deployments
are triggered by NuCloud/JITA and managed through a pipeline of
microservices.

## Architecture

RDM consists of several cooperating services, each producing its own
log stream:

| Service | Role |
|---|---|
| **Validator** | Validates the deployment spec (resource specs, QMS quotas, static IP limits, build URLs) before processing |
| **RM Worker** | Requests and provisions resources from the resource pool (e.g., `lcc_nested_ahv_2`) |
| **Dispatcher** | Creates Docker containers on the deployer swarm to execute the deployment |
| **Deployer** | Top-level orchestration — coordinates plugin deployments, manages lifecycle transitions |
| **Plugin (per-deployment)** | Executes the actual cluster deployment (e.g., Nested AHV 2.0 plugin creates VMs, images, creates cluster) |
| **Poller** | Polls deployment status during plugin execution |
| **Release Dispatcher** | Handles resource cleanup/release after deployment completion or failure |

## Deployment Lifecycle Stages

A scheduled deployment progresses through these stages in order. The
`stages` array in the API response shows which stages were reached.

| Stage | Description |
|---|---|
| `PENDING` | Request submitted; being validated by RDM (payload correctness, user permissions, pool access) |
| `REQUESTING_SOFTWARE_RESOURCES` | (Only for QMS credit / ESXi license deployments) Waiting in queue for credit/license allocation. If insufficient credits, marked FAILED |
| `REQUESTING_RESOURCES` | Waiting in queue for hardware resources from the pool. When picked up, transitions to PROVISIONING_RESOURCES. If pool lacks free nodes, stays here or fails |
| `PROVISIONING_RESOURCES` | Resources being provisioned/allocated from the pool |
| `UPDATING_DEPLOYMENTS_WITH_ALLOCATED_RESOURCES` | Writing allocated resource info to deployment records |
| `UPDATED_DEPLOYMENTS_WITH_ALLOCATED_RESOURCES` | Resource info written |
| `RESOURCES_ALLOCATED` | All resources allocated, ready to deploy |
| `PROCESSING` | Deployer Docker container being created by the Dispatcher. Messages: "Deployer container created", then "Orchestrating plugin deployments" |
| `DEPLOYER_CONTAINER_CREATED` | Docker container running, plugin about to execute |
| `ORCHESTRATING_PLUGIN_DEPLOYMENTS` | Plugin deploying clusters (longest phase — VM creation, imaging, cluster create) |
| `WAITING_FOR_DEPLOYMENT_ABORTION` | Failure detected, waiting for deployments to abort |
| `ALL_DEPLOYMENTS_ABORTED` | All deployments aborted |
| `ABORTING` | User-initiated abort (message: "User sent an abort request") |
| `ABORTED` | Terminal state from user abort; all resources released |
| `FAILED` | Deployment has failed |
| `RELEASING` | Resources being released/cleaned up |
| `SCHEDULED_FOR_RELEASE` | Pool doesn't have auto-release; nodes marked free for reuse but not formally released. User can force-release via UI |
| `RELEASED` | All resources released, terminal state |
| `SUCCESS` / `COMPLETED` | Deployment succeeded (happy path terminal state) |

**Common REQUESTING_RESOURCES messages:**
- "No free nodes exist in the pool" — pool nodes are all in use,
  disabled, or part of static clusters.
- "Could not get lock on the pool" — internal concurrency; not an
  error. RM workers compete for pool locks; the losing worker retries.
- "Could not find clusters with min_nodes X" — not enough matching
  nodes after applying all constraints.

## Deployment Types

### Single NOS Cluster (most common)
One `$NOS_CLUSTER` deployment. The scheduled deployment has one entry
in the `deployments` array.

### Multi-Cluster
Multiple `$NOS_CLUSTER` deployments. Each gets its own deployment ID
and log directory under `deployments/`.

### Prism Central (PC)
A `$PRISM_CENTRAL` deployment, often alongside one or more
`$NOS_CLUSTER` deployments. PC registration happens after cluster
creation.

### External Storage
A `$NOS_CLUSTER` with an attached external storage entity. Additional
configuration for storage targets.

## Nested AHV 2.0

Most test deployments use Nested AHV 2.0, which creates virtual
clusters on top of physical "base clusters." Key concepts:

- **Base Cluster**: Physical AHV cluster hosting nested VMs (e.g.,
  `Nested2-BaseCluster-X71`)
- **Nested Host VM**: A VM on the base cluster that acts as a
  hypervisor for the nested cluster
- **Nested CVM**: A VM inside the nested host that runs AOS services
- **Node Pool**: Resource pool managing base cluster capacity (e.g.,
  `lcc_nested_ahv_2`)

The deployment plugin:
1. Allocates resources from the node pool
2. Creates nested host VMs on the base cluster via Prism API
3. Boots nested hosts with AHV ISO
4. Creates nested CVM VMs inside each nested host
5. Images CVMs with AOS build
6. Runs `cluster create` to form the NOS cluster
7. Performs post-cluster-create configuration

## RDM API

### Scheduled Deployment
```
GET https://rdm.eng.nutanix.com/api/v1/scheduled_deployments/<sd_id>
```

Key response fields:
- `data.status` — current status
- `data.message` — human-readable status message
- `data.failure_analysis` — structured failure info (when failed)
  - `.category` — `PRODUCT`, `INFRA`, `PLUGIN`, `CONFIG`
  - `.error_metadata.RDM.reason` — failure reason code
  - `.error_metadata.RDM.source` — which component failed
  - `.message` — detailed failure message
  - `.resolution` — suggested resolution text
- `data.stages` — ordered list of stages traversed
- `data.log_link` — URL to service-level logs
- `data.deployments` — list of deployment ObjectIDs
- `data.payload.resource_specs` — cluster specifications
- `data.payload.client.jita_task_id` — originating JITA task
- `data.allocated_pool` — which resource pool was used
- `data.deploy_time` — deployment duration in minutes

### Individual Deployment
```
GET https://rdm.eng.nutanix.com/api/v1/deployments/<dep_id>
```

Key response fields:
- `data.status`, `data.message`, `data.failure_analysis` — same as SD
- `data.params` — full deployment parameters after spec translation
- `data.params.nested_params` — nested cluster configuration
  - `.version` — nested AHV version (e.g., `2.0`)
  - `.nos.commit` — AOS commit hash
  - `.nos.installer_url` — AOS build URL
  - `.hypervisor.url` — AHV image URL
  - `.constraints` — node/CVM/host resource constraints
- `data.params.credentials` — cluster credentials
- `data.nested_run_statistics.resource_details` — per-node base
  cluster assignment and resource consumption
- `data.log_link` — deployment-specific log URL
- `data.percentage_complete` — deployment progress (0-100)
- `data.started_at`, `data.completed_at` — timestamps
