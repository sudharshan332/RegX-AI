# Source Code Deep-Dive — Local Code + Sourcegraph MCP

Reference file for `triage-cdp-test-failure`. Read this when performing a
deep-dive source code investigation.

---

## When to Use

This step runs **after** the standard triage (log analysis, JIRA search,
report generation). The standard triage remains the primary deliverable —
always complete and output the JIRA report first.

**When to proceed automatically (no user prompt needed):**
- The failure traversed a subsystem not covered by any existing flow in
  the `flows/` directory (see Flow Directory in
  `failure-patterns-reference.md`).
- The causal chain ended at an unexplained failure — logs alone could not
  determine *why* something failed.
- A `new_flow_candidate` telemetry entry is being logged — source code
  context produces a much richer flow proposal.
- The causal chain identified a product state problem (e.g., a service not
  running, a mount stale, a config not persisted) and product code must be
  examined to determine whether this is a known limitation or a bug (see
  `investigate-reference.md` — "Investigate Test Validation Failures
  (Keep Asking Why)").

**When to skip:**
- The failure matched a well-documented flow and the root cause is clear
  (e.g., a known JIRA duplicate with an established causal chain).
- The failure was a confirmed test bug (wrong assertion, timing issue, etc.)
  AND you have verified that the underlying product state is correct.
  **IMPORTANT**: A test assertion failure is NOT automatically a test bug.
  You must complete the validation-failure investigation
  (`investigate-reference.md` — "Investigate Test Validation Failures")
  before classifying it as such.

**When to ask the user (borderline):**
- The failure partially matches an existing flow but diverged at an
  unexpected point — a deep-dive might reveal a new fork, but may not be
  worth the additional cost.

Any new subsystem knowledge discovered (operation flows, service
dependencies, failure propagation paths) should be captured in the
telemetry entry's `flow_enrichment` or `new_flow_detail` fields.

---

## Lookup Strategy — Local First, Sourcegraph Fallback

**Always try local code first** before reaching for Sourcegraph MCP. Local
reads use the Read/Grep tools (no MCP call overhead) and are significantly
faster.

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

Many developers have product code available locally via xgear views. These
can be read with Read/Grep tools (zero MCP calls). Check for local code
before falling back to Sourcegraph.

**Xgear views (`~/main/views/<view_name>/`):**

Xgear views contain the full PE-side product repos — `cdp`, `ntnxdb`,
`util` — which are the repos most frequently needed for deep-dives.

**Selecting the best view:**

If `xgear` is available and `~/main/views/` exists, run `xgear view ls`
from that directory to list all views with their release branch, githash,
and GBN:

```bash
cd ~/main/views && xgear view ls
```

Example output:
```
+----------------------------------------------------------------------------------------------+
|Name            |Release                      |Githash       |Gbn       |Locked|Partial|Linked|
+----------------------------------------------------------------------------------------------+
|76098_0318      |origin/ganges-7.6.0.98-stable|d04e5c3abe2c74|1773715667|No    |No     |No    |
|master_0310     |origin/master                |510feedcdeaf25|N/A       |No    |No     |No    |
+----------------------------------------------------------------------------------------------+
```

Compare the `Release` and `Githash` columns against the build's
`dependencies.yml` (branch and githash fields) to pick the closest
match. For example:
- Test built on `master` → use a view with `origin/master`
- Test built on `ganges-7.6.0.98` → use a view with
  `origin/ganges-7.6.0.98-stable`
- If the GBN matches the build's GBN, the code is very close or exact

If `xgear` is not available, fall back to `ls ~/main/views/` and pick by
name (e.g., a view named `master_*` for a master build).

```bash
# Each view contains the repos with full directory structure:
# ~/main/views/<view>/cdp/cdp/server/stargate/...
# ~/main/views/<view>/ntnxdb/ntnxdb_client/forest/...
# ~/main/views/<view>/util/util/block_store/...
```

| Repo | Local Path (xgear view) | Contents |
|---|---|---|
| `cdp` | `~/main/views/<view>/cdp/` | Stargate, Curator, Castor, Hades, Cassandra monitor |
| `ntnxdb` | `~/main/views/<view>/ntnxdb/` | Forest, Grove, BlockStore, Medusa |
| `util` | `~/main/views/<view>/util/` | Zeus, block_store, external_storage utils |

**PC-side code (`~/main/` top level):**

| Repo | Local Path | Contents |
|---|---|---|
| `main` | `~/main/prism/` | GoLazan, Placement Solver, Metropolis |
| `main` | `~/main/stats_controller/` | Stats controller |
| `main` | `~/main/stats/` | IDF/Stats queries |

**Caveat**: Local code may not match the exact commit from the test's
`dependencies.yml`. Use `xgear view ls` to check how close the view's
githash is to the build's githash — if they match or are very close (same
GBN), line numbers will be reliable. If the view is on a different branch
or significantly older, the code is still useful for understanding code
paths and error propagation logic, but note the discrepancy in the report:
*"Source reference is from local xgear view (<view_name>, githash
<short_hash>); the test build used <build_hash>."*

### Example — Local lookups:

```
# PE-side: Stargate source from an xgear view
Read: ~/main/views/master_0310/cdp/cdp/server/stargate/external_storage/external_storage_utils.cc
Grep: pattern="kHostingFailed" path="~/main/views/master_0310/cdp/cdp/server/stargate/"

# PE-side: Forest/Grove from an xgear view
Read: ~/main/views/master_0310/ntnxdb/ntnxdb_client/forest/forest_host_op.cc

# PC-side: GoLazan from top-level main
Read: ~/main/prism/go_lazan/cluster_stats_collector.go
Grep: pattern="ClusterStorageFilter" path="~/main/prism/"
```

This saves most or all Sourcegraph MCP calls when a view is available.

---

## Sourcegraph MCP (for repos not available locally)

### MCP Tool Reference

| Tool | Purpose |
|------|---------|
| `keyword_search` | Search for exact code patterns across repos; supports `repo:`, `file:`, `rev:` filters |
| `nls_search` | Semantic/flexible code search when exact terms are unknown |
| `read_file` | Read file contents from a specific repo, path, and optional `revision` (githash) |
| `list_files` | List files/directories in a repo at a given path |
| `list_repos` | Find repositories by name substring — **only use when the Component Mapping table below does not cover the file** |

### Resolving the Correct Repository and Revision

Product source is split across multiple repos. The repo naming convention is
`{repo}-{branch}`:

| Branch style | Repo name example |
|---|---|
| `master` | `cdp-master`, `ntnxdb-master`, `util-master` |
| Release (e.g., `ganges-7.6`) | `cdp-ganges-7.6`, `ntnxdb-ganges-7.6` |
| Patch (e.g., `ganges-7.6.0.98`) | `cdp-ganges-7.6.0.98` |

**Step 1 — Read `dependencies.yml`:**

This file lists every component with its `repo`, `branch`, and `githash`.
It can be found in two places depending on triage mode:

- **Archived Logs Mode**: In the log bundle at
  `{base_url}/nos_cluster_logs_*/<any_cvm_ip>/config/dependencies.yml`
  (same directory as `build_info.yml`). Use the local NFS mount or HTTP
  fetch, whichever is active for the session.
- **Live Cluster Mode**: On any CVM at `~/config/dependencies.yml`:
  ```bash
  ssh nutanix@<cvm_ip> "cat ~/config/dependencies.yml"
  ```

Example entry:

```yaml
  cdp-server:
    retrieve:
      branch: master
      gbn: '1774288245'
      githash: 'b32fc614d0c974'
      repo: cdp
      version: 108
```

**Step 2 — Construct the Sourcegraph repo name and revision:**

- Repo name: `{repo}-{branch}` → `cdp-master`
- Revision: the `githash` value → `b32fc614d0c974`

**Step 3 — Read the file at the exact revision:**

```
CallMcpTool: user-sourcegraph / read_file
  repo: "cdp-master"
  path: "cdp/server/curator/index_store/index_store_controller_ops.cc"
  startLine: 328
  endLine: 336
  revision: "b32fc614d0c974"
```

Using the `revision` parameter ensures you see the **exact code running on
the cluster**, not HEAD which may have diverged (especially on `master`).

**Step 4 — Search at a specific revision (keyword_search / nls_search):**

Use the `rev:` filter together with `repo:`:

```
repo:^cdp-master$ rev:b32fc614d0c974 file:index_store_controller_ops.cc kNoNode
```

---

## Common Repo-to-Component Mapping

Use this table to **skip `list_repos`** — go directly to a local Read/Grep
or Sourcegraph `read_file` with the known repo name and path prefix. Only
call `list_repos` when the file is not covered by this table.

| Service / Component | Repo | Local path (xgear view) | Sourcegraph path |
|---|---|---|---|
| Curator | `cdp` | `~/main/views/<view>/cdp/cdp/server/curator/` | `cdp/server/curator/` |
| Stargate (service binary) | `cdp` | `~/main/views/<view>/cdp/cdp/server/stargate/` | `cdp/server/stargate/` |
| Stargate (Forest, Grove, BlockStore) | `ntnxdb` | `~/main/views/<view>/ntnxdb/ntnxdb_client/forest/` | `ntnxdb_client/forest/` |
| Castor | `cdp` | `~/main/views/<view>/cdp/cdp/server/castor/` | `cdp/server/castor/` |
| External Storage (cdp-side) | `cdp` | `~/main/views/<view>/cdp/cdp/server/stargate/external_storage/` | `cdp/server/stargate/external_storage/` |
| External Storage (util-side) | `util` | `~/main/views/<view>/util/util/external_storage/` | `util/external_storage/` |
| Medusa | `ntnxdb` | `~/main/views/<view>/ntnxdb/ntnxdb_client/medusa/` | `ntnxdb_client/medusa/` |
| Util libraries | `util` | `~/main/views/<view>/util/util/base/`, `.../block_store/` | `util/base/`, `util/block_store/` |
| Hades | `cdp` | `~/main/views/<view>/cdp/cdp/server/hades/` | `cdp/server/hades/` |
| Cassandra monitor | `cdp` | `~/main/views/<view>/cdp/cdp/server/cassandra/` | `cdp/server/cassandra/` |
| Zeus / Zookeeper client | `util` | `~/main/views/<view>/util/util/zeus/` | `util/zeus/` |
| GoLazan / Placement Solver | `main` | `~/main/prism/` | — |
| Metropolis | `main` | `~/main/prism/` | — |
| Stats controller | `main` | `~/main/stats_controller/` | — |
| Genesis (service orchestrator, leader, config publisher) | `infra` | `~/main/views/<view>/infra/cluster/genesis/` | `cluster/genesis/` |
| Cluster DB Config / sync_config chain (genesis publisher) | `infra` | `~/main/views/<view>/infra/cluster/db_config/cluster_config.py` | `cluster/db_config/cluster_config.py` |
| Cluster management REST API utils (sync_config_to_idf) | `infra` | `~/main/views/<view>/infra/cluster/clustermgmt_rest_api_utils.py` | `cluster/clustermgmt_rest_api_utils.py` |
| Arithmos client / RPC / generic attributes | `ntnxdb` | `~/main/views/<view>/ntnxdb/ntnxdb_client/stats/arithmos/` | `ntnxdb_client/stats/arithmos/` |
| Arithmos source converter (DCHECKs on generic attrs) | `ntnxdb` | `~/main/views/<view>/ntnxdb/ntnxdb_client/stats/arithmos/base/source_converter.cc` | `ntnxdb_client/stats/arithmos/base/source_converter.cc` |
| PrismGateway (`v1/cluster`, ClusterDTOAssembler) | `prism_gateway` (Java) | usually not checked out locally — use Sourcegraph `keyword_search` | `prism_gateway/` |
| PE UI (ResourceGroupModel, PageActionView, cluster classification) | `prism` (TypeScript/React) | usually not checked out locally — use Sourcegraph `keyword_search` | `prism/` |

When a stack trace shows a build path like
`/src/bigtop/util/util/block_store/block_store.cc`, strip the
`/src/bigtop/` prefix and the first repo-name segment to get the file path
within the repo (e.g., `util/block_store/block_store.cc` in the `util` repo).

---

## Disambiguating Files with the Same Name Across Repos

Some files exist in multiple repos (e.g., `external_storage_utils.cc` lives
in both `cdp` and `util`). Use these heuristics:

1. **Check the build path**: Stack traces include the full build path, e.g.,
   `/src/bigtop/cdp/cdp/server/stargate/external_storage/external_storage_utils.cc`
   vs. `/src/bigtop/util/util/external_storage/external_storage_utils.cc`.
   The second path component (`cdp` or `util`) identifies the repo.

2. **Check the namespace / class**: `nutanix::stargate::external_storage::`
   → `cdp` repo. `nutanix::external_storage::` (no service prefix) → `util`.

3. **Use `keyword_search` across repos**: Search for the specific function:
   ```
   file:external_storage_utils.cc <function_name_or_error_string>
   ```
   Then check which repo's version contains the matching line number.

4. **When in doubt, check both**: Read the relevant line from each repo's
   copy. One will match; the other will not.

---

## Workflow for Deep-Dive Source Analysis

1. **Identify the error signature** from logs: `file.cc:LINE] error message`.
2. **Look up `dependencies.yml`** to get the repo, branch, and githash.
3. **Check for local code** using the decision flow above:
   - **Xgear view available** (`~/main/views/<view>/cdp/`, etc.): use
     Read/Grep tools directly — zero MCP calls. This covers `cdp`,
     `ntnxdb`, and `util` (the vast majority of deep-dives).
   - **PC-side code** (`~/main/prism/`, etc.): use Read/Grep directly.
   - **No local code**: use the Component Mapping table to go directly
     to Sourcegraph `read_file` — **skip `list_repos`**. Fall back to
     `keyword_search` or `list_repos` only if the file is not in the
     table.
4. **Read the code** at the relevant line — Read tool for local, or
   Sourcegraph `read_file` with `revision` for exact-commit reads.
5. **Trace the causal chain** — read callers, callees, callbacks, and error
   propagation paths to determine root cause vs. symptom.
6. **Include source references** in the JIRA report under a
   `h4. Source References` section. For Sourcegraph, the URL format is:
   `https://sourcegraph.ntnxdpro.com/{repo}@{githash}/-/blob/{path}?L{line}`
   For local code, note the view/branch being referenced.

---

## Sourcegraph MCP Setup

For first-time setup instructions (workspace `mcp.json` config), see
[setup-guide.md](setup-guide.md).

---

## Important Notes

- **Lines change frequently on `master`** — for Sourcegraph lookups, always
  use the githash from `dependencies.yml` rather than reading HEAD. For
  local code, note the caveat that the branch may differ.
- **Sourcegraph short hashes work** — the MCP resolves short githashes
  (e.g., `b32fc614d0c974`) to the full commit automatically.
- **Always complete the JIRA report first** — do not block the standard
  triage on source code availability. The deep-dive happens after the
  report is delivered.
- **Not all repos may be indexed** — if a repo is not found in Sourcegraph,
  note this and proceed with log-only analysis.
- **Capture learnings in telemetry** — any new dependencies, operation
  flows, or failure modes discovered via source code should be included in
  the `flow_enrichment` or `new_flow_detail` of the telemetry entry.
- **Prefer local over Sourcegraph** — every file read from a local repo
  saves one MCP tool call. Use the decision flow at the top of this file.
