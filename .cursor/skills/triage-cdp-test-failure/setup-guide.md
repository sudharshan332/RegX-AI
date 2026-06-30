# MCP Server Setup Guide

One-time setup instructions for the optional MCP servers used by
`triage-cdp-test-failure`. You only need to do this once per workstation.

---

## Path Convention: `${WORKSPACE}`

Every skill file under `.cursor/skills/` uses `${WORKSPACE}` to mean
the absolute path to this repo's root on the agent's workstation.
When the agent encounters `${WORKSPACE}/.cursor/skills/...` in any
skill file (sub-skill `Read` instructions, `cd` commands in shell
snippets, helper-script paths), it must substitute the actual repo
root before executing.

Resolution rules, in order:

1. If the `WORKSPACE` environment variable is set (Cursor exports it
   for the active workspace), use it directly.
2. Otherwise, resolve via `git rev-parse --show-toplevel` from any
   path inside the repo.
3. As a last resort, use `$(pwd)` if the agent is already at the
   repo root.

Never hardcode an absolute user path (e.g. `/home/<user>/...`) when
referencing skill files or repo-relative scripts.

---

## Atlassian (JIRA) MCP Server

### Step 1: Create a JIRA Personal Access Token (PAT)

1. Log in to JIRA at `https://jira.nutanix.com`.
2. Click your **profile avatar** (top-right) and select **Profile**.
3. Navigate to **Personal Access Tokens** (left sidebar).
4. Click **Create token**, give it a name (e.g., `cursor-mcp`), and click
   **Create**.
5. **Copy the token immediately** — it will not be shown again.

### Step 2: Add the Atlassian MCP server to Cursor

1. Open your Cursor MCP config file at `~/.cursor/mcp.json`.
2. Add the following entry inside `"mcpServers"` (replace `<YOUR_JIRA_PAT>`):

```json
"atlassian": {
  "command": "docker",
  "args": [
    "run",
    "-i",
    "--rm",
    "-e", "JIRA_URL=https://jira.nutanix.com",
    "-e", "JIRA_PERSONAL_TOKEN=<YOUR_JIRA_PAT>",
    "ghcr.io/sooperset/mcp-atlassian:latest"
  ]
}
```

3. Save and restart Cursor.

**Prerequisites:** Docker must be installed and running.

**Troubleshooting:**
- Auth errors → PAT may have expired. Regenerate and update `mcp.json`.
- Docker unavailable → ask team lead about alternative MCP setups.

---

## Sourcegraph MCP Server

The Sourcegraph MCP requires no authentication — it connects to an internal
server. It should be configured in the **workspace-level** Cursor MCP config
at `{workspace}/.cursor/mcp.json` so it is available to anyone who opens the
repo. The workspace-level config for this repo already includes it.

If the `user-sourcegraph` MCP is not available during a triage session
(e.g., tools not listed, connection error), check whether the workspace
config exists:

```bash
cat "${WORKSPACE}/.cursor/mcp.json"
```

If the file is missing or does not contain the `sourcegraph` entry, create
or update it:

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

After writing the file, the user must reload Cursor for the new server to
take effect. The workspace-level config merges with the user-level
`~/.cursor/mcp.json`.

---

## JITA MCP Server

The JITA MCP requires no authentication — it is the Panacea-hosted JITA
server with all six JITA filers (`ahv_jita`, `cdp_jita`, `jita-dog-food-afs`,
`jita-tester-afs`, `jita-tester-precommit-afs`, `sys-test-afs`) pre-mounted
under `/home/nutanix/jita_mount/`. It exposes `jita_list_servers`,
`jita_bundle_exists`, `jita_search_files`, and `jita_exec` (arbitrary
shell against the bundle directory).

**This is a fallback only.** Always prefer the local NFS mount on the
agent's workstation — it avoids a network round-trip per command. Use
JITA MCP when the local mount is missing, the bundle lives on a filer
this workstation does not mount, or fstab modification is not viable
(e.g., laptop / Mac, CI). See "Fetching Logs" in `SKILL.md` for the
access ladder.

It should be configured in the **workspace-level** Cursor MCP config at
`{workspace}/.cursor/mcp.json` so it is available to anyone who opens
the repo. The workspace-level config for this repo already includes it.

If the `user-jita` MCP is not available during a triage session
(e.g., tools not listed, connection error), check whether the workspace
config exists:

```bash
cat "${WORKSPACE}/.cursor/mcp.json"
```

If the file is missing or does not contain the `jita` entry, create or
update it (merge with any existing `mcpServers` entries — do not
overwrite Sourcegraph):

```json
{
  "mcpServers": {
    "jita": {
      "url": "http://10.113.24.33:3003/mcp",
      "description": "JITA MCP - Remote shell access to JITA log bundles via the Panacea host's pre-mounted filers (/home/nutanix/jita_mount/*). Fallback for log triage when the local NFS mount on this workstation is unavailable. Prefer local mount when available — MCP adds a network round-trip per command."
    }
  }
}
```

After writing the file, the user must reload Cursor for the new server
to take effect.
