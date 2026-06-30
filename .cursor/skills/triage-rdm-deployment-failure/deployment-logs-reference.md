# Deployment Logs Reference

## Log Server Access

Deployment logs are served via an HTTP file server (typically on port
9000). The base URL is stored in the scheduled deployment's `log_link`
field.

**Access methods (in order of preference):**

1. **curl from the tester VM** — the log server IPs are accessible
   from tester VMs on the internal network. The exact IP is
   environment-specific and is published on each scheduled-deployment
   object as `data.log_link`; never hardcode one.
2. **Browser on VPN** — if the user can access the IP directly.

Example (substitute `<log_server_ip>` and `<sd_id>` from the RDM
scheduled-deployment object's `data.log_link`):
```bash
curl -s "http://<log_server_ip>:9000/scheduled_deployments/<YYYY-MM-DD>/<sd_id>/"
```

The server returns HTML directory listings that can be parsed to
discover available log files and subdirectories.

## Log Directory Structure

Below is the full directory tree for a scheduled deployment. Each
level is documented with its purpose and the log files found there.

```
<sd_id>/
├── deployer/
│   ├── DEPLOY/
│   │   └── <sd_id>_1.txt            # Top-level deployer orchestration log
│   └── RELEASE/
│       └── <sd_id>_1.txt            # Release phase orchestration log
├── deployments/
│   └── <dep_id>/                    # One directory per cluster deployment
│       ├── DEPLOY/
│       │   ├── <dep_id>_1.txt       # Primary deployment log (plugin execution)
│       │   ├── INFO_logs/
│       │   │   └── <dep_id>_1.txt   # INFO-only filtered log
│       │   └── nutest_vault_setup.log  # Vault/secrets setup log
│       ├── RELEASE/
│       │   ├── <dep_id>_1.txt       # Release log for this deployment
│       │   └── INFO_logs/
│       │       └── <dep_id>_1.txt
│       ├── entity_logs/
│       │   └── retry_<n>/           # Logs collected from cluster entities
│       │       ├── <cluster_name>/
│       │       │   ├── logbay_<cvm_ip>_<ts>/  # Logbay bundle from CVM
│       │       │   ├── svm_log_<cvm_ip>/      # Direct CVM log copies
│       │       │   └── nested_host_log_<host_ip>/  # Host-level logs
│       │       ├── nested_cluster_collated_logs/   # Collated logs (may be empty)
│       │       ├── pe_log_collector.log        # PE log collection output
│       │       └── nested_host_log_collector.log   # Host log collection output
│       ├── poller/
│       │   └── <dep_id>_1.txt       # Deployment state polling log
│       └── runtime/
│           └── retry_<n>/
│               └── Nested-AHV-<dep_id>-<node_idx>/  # Per-node runtime config
│                   ├── hardware_config.json
│                   ├── instance-metadata.json
│                   ├── instance-metadata-v2.json
│                   └── <uuid>                  # VM UUID file
├── dispatcher/
│   └── <sd_id>_1.txt                # Dispatcher log (container creation)
├── rm_worker/
│   └── <sd_id>_1.txt                # Resource manager log (allocation)
└── validator/
    └── <sd_id>_1.txt                # Validation log (spec checking)
```

## Log Analysis Priority

When triaging a failure, read logs in this order:

### 1. RDM API (first)

Query the API for `failure_analysis` to get the high-level failure
category and message. This tells you where to focus.

### 2. Deployment DEPLOY Log (primary investigation)

**File:** `deployments/<dep_id>/DEPLOY/<dep_id>_1.txt`

This is the most important log. It shows the full plugin execution
including VM creation, imaging, cluster creation, and failure details.

**Reading strategy (from Confluence debugging guide):**
1. Read the **end** of the log first (last 200 lines) — failures and
   tracebacks appear at the end.
2. **Search for `Traceback` with context** — this is mandatory for
   every deployment failure:
   `grep -A20 -B20 Traceback <deployment-log-file>`
3. Copy the `Exception` message shown under the Traceback.
4. Search for `ERROR`, `CRITICAL`, `WARN`, `fail`, `exception`.
5. For cluster create failures, look for the `cluster create` command
   output, which is embedded as a quoted string in the log.

**Key patterns in this log:**

| Pattern | Meaning |
|---|---|
| `STEP ... Setting up log file` | Log section boundary |
| `cluster ... create` | Cluster creation command being executed |
| `Cluster create workflow in progress. Current state:` | Cluster create progress polling |
| `CRITICAL ... RPC to acquire node lock ... timed out` | Node lock timeout during cluster create |
| `Failed to create cluster` | Cluster creation failed |
| `NuTestEntityOperationError` | Framework-level operation failure |
| `failure_analysis` | Structured failure info being reported |
| `COPYING_PE_LOGS` | Post-failure log collection starting |
| `Fix the problem and start again` | Genesis found a service that won't start |
| `No metadata disks on the local node` | Cassandra/Hades disk issue |
| `Starting ... service` | Genesis service startup sequence |
| `acli ... image.create` | Image creation on base cluster |
| `No host has enough available memory` | Base cluster RAM exhaustion |

### 3. Entity Logs (deep-dive)

**Directory:** `deployments/<dep_id>/entity_logs/retry_<n>/`

Contains logs collected from the actual cluster entities after a
failure. Structure:

- `<cluster_name>/logbay_<cvm_ip>_<ts>/` — Full logbay bundle from
  a CVM. Contains genesis.out, stargate logs, etc.
- `<cluster_name>/svm_log_<cvm_ip>/` — Direct SVM log copies
- `<cluster_name>/nested_host_log_<host_ip>/` — AHV host logs
- `pe_log_collector.log` — Log of the PE log collection process itself
- `nested_host_log_collector.log` — Log of the host log collection

**For cluster creation failures**, the genesis logs in the logbay
bundle are the most valuable:
- `genesis.out` — Genesis service output
- Look for `FATAL`, `ERROR`, `WARNING` in genesis logs
- Cross-reference CVM IPs from the cluster create command
- Find the problematic service:
  `grep "Fix the problem and start again" genesis.out`
- Check service startup sequence:
  `zgrep "Starting ... service" genesis*`
- Check for Cassandra disk issues:
  `grep -m5 "No metadata disks on the local node" cassandra_monitor.*`
  If matches found, file an issue on Hades.
- Check acropolis health:
  `allssh cat ~/data/logs/acropolis.FATAL`

### 4. Poller Log

**File:** `deployments/<dep_id>/poller/<dep_id>_1.txt`

Shows deployment state transitions over time. Useful for understanding
timeline and which phase took too long or got stuck.

### 5. Runtime Configuration

**Directory:** `deployments/<dep_id>/runtime/retry_<n>/`

Contains per-node VM configuration files. Useful for verifying that
VMs were created with correct specs (CPU, RAM, disk, network).

### 6. Deployer DEPLOY Log

**File:** `deployer/DEPLOY/<sd_id>_1.txt`

Top-level orchestration log. Shows the deployer creating plugin
containers and coordinating multi-deployment workflows. Usually less
detailed than the deployment-level log but useful for multi-cluster
failures to see which deployment failed first.

### 7. Dispatcher Log

**File:** `dispatcher/<sd_id>_1.txt`

Shows the deployer Docker container creation. Useful for infrastructure
issues (Docker swarm problems, container creation failures).

### 8. Validator Log

**File:** `validator/<sd_id>_1.txt`

Shows pre-deployment validation: QMS quota checks, static IP limits,
build URL validation, spec translation. If the deployment fails before
reaching `PROCESSING`, check this log.

### 9. RM Worker Log

**File:** `rm_worker/<sd_id>_1.txt`

Shows resource allocation from the node pool. Useful for resource
exhaustion failures or allocation errors.

### 10. Release Logs

**Files:**
- `deployer/RELEASE/<sd_id>_1.txt`
- `deployments/<dep_id>/RELEASE/<dep_id>_1.txt`

Show the cleanup/release process. Rarely relevant for triaging the
original failure but useful if the release itself failed (e.g.,
leaked resources).

## Reading Logs via curl

**List a directory:**
```bash
curl -s "http://<log_server>/scheduled_deployments/<date>/<sd_id>/"
```
Returns an HTML directory listing. Parse `<a href="...">` tags to find
files and subdirectories.

**Read a log file (end of file):**
```bash
curl -s "http://<log_server>/.../file.txt" | tail -200
```

**Search for errors:**
```bash
curl -s "http://<log_server>/.../file.txt" | grep -i "error\|fail\|exception\|traceback\|critical"
```

**Read a specific byte range (for large files):**
```bash
curl -s -r "-50000" "http://<log_server>/.../file.txt"
```
This reads the last 50KB of the file.
