# Source Code Deep-Dive — Local Code + Sourcegraph MCP

Reference file for `triage-rdm-deployment-failure`. Read this when performing
a deep-dive source code investigation for a deployment failure.

---

## When to Use

This step runs **after** the standard triage (log analysis, failure
pattern matching, report generation). The standard triage remains the
primary deliverable — always complete and output the report first.

**When to proceed automatically (no user prompt needed):**
- Cluster creation failures involving genesis, node_manager, or
  foundation code paths — these benefit from understanding the
  product-side logic.
- Foundation/imaging failures where the logs show a step-level failure
  but not the underlying cause.
- The failure traversed a subsystem not covered by any existing pattern
  in `failure-patterns-reference.md`.
- A `new_flow_candidate` telemetry entry is being logged — source code
  context produces a much richer pattern proposal.

**When to skip:**
- Resource allocation or pool exhaustion failures (`INFRA` category) —
  these are infrastructure issues, not code bugs.
- Validation failures (`CONFIG` category) — these are deployment spec
  errors.
- Well-documented failure patterns where the root cause is clear from
  logs alone.
- Plugin-level failures in RDM deployer code that are clearly
  operational (timeouts waiting for external services, transient
  network errors).

**When to ask the user (borderline):**
- The failure partially matches an existing pattern but diverged at an
  unexpected point — a deep-dive might reveal a new fork, but may not
  be worth the additional time.

Any new subsystem knowledge discovered (operation flows, service
dependencies, failure propagation paths) should be captured in the
telemetry entry's `flow_enrichment` or `new_flow_detail` fields.

---

## Lookup Strategy — Local First, Sourcegraph Fallback

**Always try local code first** before reaching for Sourcegraph MCP.
Local reads use the Read/Grep tools (no MCP call overhead) and are
significantly faster.

### Decision flow for each file read:

```
1. Check for xgear views: ls ~/main/views/
   Any views available?
   YES → Run "cd ~/main/views && xgear view ls" (if xgear is available)
         to see release branches and githashes. Pick the closest view
         to the build under test. Use Read/Grep tools on the local path.
         This covers cdp, ntnxdb, and util — the majority of deep-dives.
   NO  → Continue to step 2

2. Is the file in ~/main/ top level? (PC-side code: prism/, stats/)
   YES → Use Read/Grep tools directly
   NO  → Continue to step 3

3. Is the repo + file path known from the Component Mapping table?
   YES → Skip list_repos, go directly to Sourcegraph read_file
   NO  → Use keyword_search with file: filter to locate the file,
         then read_file. Use list_repos only as a last resort.
```

### Local Repo Availability

Many developers have product code available locally via xgear views.
These can be read with Read/Grep tools (zero MCP calls). Check for local
code before falling back to Sourcegraph.

**Xgear views (`~/main/views/<view_name>/`):**

Xgear views contain the full PE-side product repos — `cdp`, `ntnxdb`,
`util` — which are the repos most frequently needed for deployment
failure deep-dives (genesis, cluster create, foundation).

**Selecting the best view:**

If `xgear` is available and `~/main/views/` exists, run `xgear view ls`
from that directory to list all views with their release branch, githash,
and GBN:

```bash
cd ~/main/views && xgear view ls
```

Compare the `Release` and `Githash` columns against the deployment's
build info to pick the closest match. For example:
- Deployment built on `master` → use a view with `origin/master`
- Deployment built on `ganges-7.6.0.98` → use a view with
  `origin/ganges-7.6.0.98-stable`

If `xgear` is not available, fall back to `ls ~/main/views/` and pick by
name (e.g., a view named `master_*` for a master build).

```bash
# Each view contains the repos with full directory structure:
# ~/main/views/<view>/cdp/cdp/server/genesis/...
# ~/main/views/<view>/util/util/genesis/...
# ~/main/views/<view>/ntnxdb/ntnxdb_client/forest/...
```

---

## Component Mapping — Deployment Failure Deep-Dives

Use this table to **skip `list_repos`** — go directly to a local
Read/Grep or Sourcegraph `read_file` with the known repo name and path
prefix. Only call `list_repos` when the file is not covered by this
table.

### Infrastructure Services (most relevant for deployment failures)

| Service / Component | Repo | Local path (xgear view) | Sourcegraph path |
|---|---|---|---|
| Genesis (cluster create) | `cdp` | `~/main/views/<view>/cdp/cdp/server/genesis/` | `cdp/server/genesis/` |
| Genesis (utilities) | `util` | `~/main/views/<view>/util/util/genesis/` | `util/genesis/` |
| Node Manager | `cdp` | `~/main/views/<view>/cdp/cdp/server/genesis/node_manager/` | `cdp/server/genesis/node_manager/` |
| Foundation (imaging) | `foundation` | N/A (use Sourcegraph) | Sourcegraph `keyword_search repo:foundation` |
| Zeus / Zookeeper client | `util` | `~/main/views/<view>/util/util/zeus/` | `util/zeus/` |
| Acropolis (VM management) | varies | N/A | Sourcegraph `keyword_search repo:acropolis` |
| Prism (cluster management) | `main` | `~/main/prism/` | — |

### RDM Plugin Code

| Service / Component | Repo | Sourcegraph search |
|---|---|---|
| Nested AHV 2.0 plugin | `nucloud-services` | `keyword_search repo:nucloud-services file:nested_ahv` |
| NOS cluster plugin | `nucloud-services` | `keyword_search repo:nucloud-services file:nos_cluster` |
| RDM deployer framework | `nucloud-services` | `keyword_search repo:nucloud-services file:deployer` |
| RDM dispatcher | `nucloud-services` | `keyword_search repo:nucloud-services file:dispatcher` |

### Data Path Services (less common for deployment failures)

| Service / Component | Repo | Local path (xgear view) | Sourcegraph path |
|---|---|---|---|
| Stargate | `cdp` | `~/main/views/<view>/cdp/cdp/server/stargate/` | `cdp/server/stargate/` |
| Curator | `cdp` | `~/main/views/<view>/cdp/cdp/server/curator/` | `cdp/server/curator/` |
| Cassandra / Medusa | `ntnxdb` | `~/main/views/<view>/ntnxdb/ntnxdb_client/medusa/` | `ntnxdb_client/medusa/` |

---

## Sourcegraph MCP (for repos not available locally)

### MCP Tool Reference

| Tool | Purpose |
|------|---------|
| `keyword_search` | Search for exact code patterns across repos; supports `repo:`, `file:`, `rev:` filters |
| `nls_search` | Semantic/flexible code search when exact terms are unknown |
| `read_file` | Read file contents from a specific repo, path, and optional `revision` (githash) |
| `list_files` | List files/directories in a repo at a given path |
| `list_repos` | Find repositories by name substring — **only use when the Component Mapping table above does not cover the file** |

### Resolving the Correct Repository and Revision

Product source is split across multiple repos. The repo naming convention
is `{repo}-{branch}`:

| Branch style | Repo name example |
|---|---|
| `master` | `cdp-master`, `ntnxdb-master`, `util-master` |
| Release (e.g., `ganges-7.6`) | `cdp-ganges-7.6`, `ntnxdb-ganges-7.6` |
| Patch (e.g., `ganges-7.6.0.98`) | `cdp-ganges-7.6.0.98` |

**Step 1 — Get build info from the deployment:**

The build commit and branch are available from the RDM API response at
`data.payload.resource_specs[0].software` or from entity logs at
`<cluster>/svm_log_<ip>/config/dependencies.yml`.

**Step 2 — Construct the Sourcegraph repo name and revision:**

- Repo name: `{repo}-{branch}` → e.g., `cdp-master`
- Revision: the githash from the build info

**Step 3 — Read the file at the exact revision:**

```
CallMcpTool: user-sourcegraph / read_file
  repo: "cdp-master"
  path: "cdp/server/genesis/cluster_manager.py"
  revision: "<githash>"
```

Using the `revision` parameter ensures you see the **exact code running
on the cluster**, not HEAD which may have diverged.

**Step 4 — Search at a specific revision:**

```
repo:^cdp-master$ rev:<githash> file:cluster_manager.py create_cluster
```

---

## Workflow for Deployment Failure Source Analysis

1. **Identify the error signature** from deployment logs: the error
   message, function name, or file reference from genesis.out, genesis
   logs, or cluster creation output.

2. **Determine the service and repo**: Use the failure context to
   identify which service produced the error:
   - Genesis cluster create → `cdp` repo (`cdp/server/genesis/`)
   - Genesis utilities → `util` repo (`util/genesis/`)
   - Foundation imaging → `foundation` repo
   - RDM plugin → `nucloud-services` repo

3. **Check for local code** using the decision flow above:
   - **Xgear view available**: Use Read/Grep tools directly — zero
     MCP calls.
   - **No local code**: Use the Component Mapping table to go directly
     to Sourcegraph `read_file`.

4. **Read the code** at the relevant location — Read tool for local, or
   Sourcegraph `read_file` with `revision` for exact-commit reads.

5. **Trace the causal chain** — read callers, callees, callbacks, and
   error propagation paths to determine root cause vs. symptom.

6. **Include source references** in the triage report under the
   `## Source Code References` section. For Sourcegraph, the URL format
   is:
   `https://sourcegraph.ntnxdpro.com/{repo}@{githash}/-/blob/{path}?L{line}`
   For local code, note the view/branch being referenced.

---

## Sourcegraph MCP Setup

For first-time setup instructions (workspace `mcp.json` config), see
[setup-guide.md](setup-guide.md).

---

## Important Notes

- **Lines change frequently on `master`** — for Sourcegraph lookups,
  always use the githash from the deployment's build info rather than
  reading HEAD. For local code, note the caveat that the branch may
  differ.
- **Sourcegraph short hashes work** — the MCP resolves short githashes
  automatically.
- **Always complete the triage report first** — do not block the
  standard triage on source code availability. The deep-dive happens
  after the report is delivered.
- **Not all repos may be indexed** — if a repo is not found in
  Sourcegraph, note this and proceed with log-only analysis.
- **Capture learnings in telemetry** — any new dependencies, operation
  flows, or failure modes discovered via source code should be included
  in the `flow_enrichment` or `new_flow_detail` of the telemetry entry.
- **Prefer local over Sourcegraph** — every file read from a local repo
  saves one MCP tool call.
