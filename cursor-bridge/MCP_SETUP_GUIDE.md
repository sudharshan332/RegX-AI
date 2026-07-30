# RegX MCP Server Setup Guide

## Problem Solved

Your original MCP server wasn't using the standard MCP protocol (SSE). I've created a new version that implements the proper protocol that Cursor expects.

## Steps to Get It Working

### 1. Install the MCP SDK

```bash
cd cursor-bridge
npm install
```

This will install the new `@modelcontextprotocol/sdk` package.

### 2. Stop the Old MCP Server

Press `Ctrl+C` in the terminal where you ran the old server.

### 3. Start the New MCP Server (SSE Protocol)

```bash
cd cursor-bridge
REGX_BACKEND_URL="http://10.111.52.90:5001" npm run start:mcp
```

You should see:
```
[regx-mcp-server] SSE protocol listening on :5003
[regx-mcp-server] RegX backend = http://10.111.52.90:5001
[regx-mcp-server] SSE endpoint: http://localhost:5003/sse
```

### 4. Your mcp.json is Already Correct

Your `.cursor/mcp.json` already has the correct configuration:

```json
{
  "mcpServers": {
    "regx-data": {
      "url": "http://10.111.52.90:5003",
      "description": "RegX regression data (failed testcases, details, push analysis results back)"
    }
  }
}
```

### 5. Reload Cursor Window

**Important**: Cursor only loads MCP servers on startup. You need to reload:

1. Open Command Palette (`Cmd/Ctrl + Shift + P`)
2. Type "Reload Window" and select it
3. Or restart Cursor completely

### 6. Verify Connection

After reloading, I'll be able to see the `regx-data` MCP server and use these tools:

- **`get_failed_testcases`** - Fetch failed tests for a tag or task IDs
- **`get_testcase_details`** - Get full details for a specific testcase
- **`update_testcase_analysis`** - Write AI analysis back to RegX

## Example Queries You Can Use

Once connected, you can ask me:

1. **"Get all failed testcases for tag `cdp_master_full_reg`"**
   - I'll use the `get_failed_testcases` tool

2. **"Show me details for testcase ID `12345678`"**
   - I'll use the `get_testcase_details` tool

3. **"Analyze the failed tests and update RegX with the root cause"**
   - I'll fetch tests, analyze them, and use `update_testcase_analysis`

## Troubleshooting

### MCP Server Still Not Showing Up?

1. **Check the server is running:**
   ```bash
   curl http://10.111.52.90:5003/health
   ```
   Should return: `{"status":"ok","backend":"http://10.111.52.90:5001"}`

2. **Check SSE endpoint:**
   ```bash
   curl -N http://10.111.52.90:5003/sse
   ```
   Should keep connection open (press Ctrl+C to close)

3. **Restart Cursor completely** (not just reload window)

4. **Check Cursor's MCP logs** (if available in your Cursor version)

### Backend Connection Issues?

Make sure your Flask backend is running on port 5001:
```bash
curl http://10.111.52.90:5001/mcp/regression/health
```

## What Changed?

- **Old**: Simple HTTP REST endpoints (`/tools`, `/call-tool`)
- **New**: Standard MCP protocol with SSE transport (`/sse`, `/message`)
- **Why**: Cursor requires the official MCP protocol, not custom REST APIs

The old version is saved as `mcp-server.js` (run with `npm run start:mcp-old` if needed).
