# MCP Server Setup Guide

One-time setup instructions for the optional MCP servers used by
`triage-rdm-deployment-failure`. You only need to do this once per
workstation.

---

## Path Convention: `${WORKSPACE}`

This skill's reference files use `${WORKSPACE}` to mean the absolute
path to this repo's root on the agent's workstation. When the agent
encounters `${WORKSPACE}/.cursor/skills/...` in any skill file (e.g.
sub-skill `Read` instructions, `cd` commands in shell snippets), it
must substitute the actual repo root before executing.

Resolution rules, in order:

1. If the `WORKSPACE` environment variable is set (Cursor exports it
   for the active workspace), use it directly.
2. Otherwise, resolve via `git rev-parse --show-toplevel` from any
   path inside the repo.
3. As a last resort, use `$(pwd)` if the agent is already at the
   repo root.

This convention applies to **every** skill under `.cursor/skills/`.
Never hardcode an absolute user path (e.g. `/home/<user>/...`) when
referencing skill files or repo-relative scripts.

---

## Sourcegraph MCP Server

The Sourcegraph MCP requires no authentication — it connects to an
internal server. It should be configured in the **workspace-level**
Cursor MCP config at `{workspace}/.cursor/mcp.json` so it is available
to anyone who opens the repo. The workspace-level config for this repo
already includes it.

If the `user-sourcegraph` MCP is not available during a triage session
(e.g., tools not listed, connection error), check whether the workspace
config exists:

```bash
cat "${WORKSPACE}/.cursor/mcp.json"
```

If the file is missing or does not contain the `sourcegraph` entry,
create or update it:

```json
{
  "mcpServers": {
    "sourcegraph": {
      "url": "http://10.113.24.33:3002/mcp",
      "description": "Sourcegraph MCP - Search product source code, read files at specific revisions, and cross-reference error signatures with code."
    }
  }
}
```

After writing the file, the user must reload Cursor for the new server
to take effect. The workspace-level config merges with the user-level
`~/.cursor/mcp.json`.

---

## When Sourcegraph Is Needed

The Sourcegraph MCP is used for deployment failure deep-dives that
involve product-side services (genesis, cluster create, foundation,
acropolis). It is **not needed** for:

- Resource allocation / pool exhaustion failures
- Validation / config failures
- RDM infrastructure issues (dispatcher, rm_worker)

See [sourcegraph-reference.md](sourcegraph-reference.md) for the full
lookup strategy and when to use code deep-dives.

---

## Verifying the Setup

After configuring the MCP, verify it is working by checking the
available tools:

1. Open a new Cursor chat session.
2. The `user-sourcegraph` MCP should appear in the available MCP servers.
3. Try a simple search to confirm connectivity:

```
keyword_search: "cluster_create" repo:cdp-master
```

If the search returns results, the setup is complete.

---

## Troubleshooting

- **MCP not appearing in tools list**: Restart Cursor after updating
  `mcp.json`. The MCP server list is loaded at startup.
- **Connection refused**: The Sourcegraph MCP server at
  `10.113.24.33:3002` must be reachable from your workstation. Check
  VPN/network connectivity.
- **Search returns no results**: The repo may not be indexed yet. Try
  `list_repos` to see available repositories.
