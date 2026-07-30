# Starting RegX Cursor Services

## The Problem

You started only the **MCP server** (port 5003), but the **Cursor AI Interactive chat** needs the **cursor-bridge** (port 5002).

## Quick Fix - Start Both Services

### Terminal 1: Cursor Bridge (Required for AI Chat)

```bash
cd cursor-bridge
CURSOR_API_KEY=crsr_44ac6d4c67cb40aec7c3cc052becff81b9148910efb84ffc367fabcacda36575 npm start
```

**Expected output:**
```
[cursor-bridge] listening on :5002
[cursor-bridge] API key configured = true
```

### Terminal 2: RegX MCP Server (Optional, for MCP tools)

```bash
cd cursor-bridge
REGX_BACKEND_URL="http://10.111.52.90:5001" npm run start:mcp
```

**Expected output:**
```
[regx-mcp-server] listening on :5003
[regx-mcp-server] RegX backend = http://10.111.52.90:5001
```

## Or Use the Helper Script (Recommended)

I created a script to start both:

```bash
./start-cursor-services.sh
```

Press Ctrl+C to stop both services.

## How to Verify It's Working

### Test 1: Cursor Bridge Health (port 5002)

```bash
curl http://localhost:5002/health
```

Should return: `{"status":"ok","jobs":0,"sessions":0}`

### Test 2: MCP Server Health (port 5003)

```bash
curl http://localhost:5003/health
```

Should return: `{"status":"ok"}`

### Test 3: Flask Backend Can Reach Bridge

From your Flask backend, check the logs when using Cursor AI chat. It should show:
- ✅ Connected to cursor-bridge at http://localhost:5002
- ❌ **NOT**: "Cursor AI bridge is not running" error

## Architecture Diagram

```
RegX Web UI (React)
       ↓
Flask Backend (port 5001)
       ↓
       ├→ Cursor Bridge (port 5002) ← **YOU NEED THIS FOR AI CHAT**
       │     ↓
       │     Cursor Cloud API (crsr_44ac6... key)
       │
       └→ MCP Server (port 5003) ← Optional, for MCP tools
             ↓
             Flask Backend (port 5001)
```

## Still Having Issues?

Check if another process is using port 5002:

```bash
lsof -i :5002
# or
netstat -tulpn | grep 5002
```

If something is blocking port 5002, kill it:

```bash
kill -9 <PID>
```

Then restart the cursor-bridge.
