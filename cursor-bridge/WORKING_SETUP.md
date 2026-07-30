# RegX Cursor Bridge - Working Configuration

## ✅ Your API Key is Valid!

Test results confirm your key works:
- **Key**: `crsr_44ac6d4c67cb40aec7c3cc052becff81b9148910efb84ffc367fabcacda36575`
- **Status**: Active and working
- **User**: sudharshan.musali@nutanix.com
- **Created**: May 21, 2026

## Start the Cursor Bridge (Correct Method)

### Option 1: Using .env file (Recommended)

Create `cursor-bridge/.env`:

```bash
CURSOR_API_KEY=crsr_44ac6d4c67cb40aec7c3cc052becff81b9148910efb84ffc367fabcacda36575
CURSOR_BRIDGE_PORT=5002
CURSOR_MODEL_ID=claude-sonnet-4-6
REGX_MCP_URL=http://localhost:5003
```

Then start:
```bash
cd cursor-bridge
npm start
```

### Option 2: Environment variable (Current method)

```bash
cd cursor-bridge
CURSOR_API_KEY=crsr_44ac6d4c67cb40aec7c3cc052becff81b9148910efb84ffc367fabcacda36575 npm start
```

## Verify It's Working

Test the health endpoint:
```bash
curl http://localhost:5002/health
```

Expected response:
```json
{"status":"ok","jobs":0,"sessions":0}
```

## Test Analysis Endpoint

Create a test file `test-analyze.sh`:

```bash
#!/bin/bash
curl -X POST http://localhost:5002/analyze-testcase \
  -H "Content-Type: application/json" \
  -d '{
    "testcase_name": "test_example",
    "exception_summary": "Connection timeout",
    "exception": "TimeoutError: Connection timed out after 30s",
    "analysis_type": "failed"
  }'
```

If this returns a session_id and analysis, your bridge is working!

## If You Still Get 401 Errors

1. **Check which key the Flask backend is using**:
   - The Flask backend might be calling a different API endpoint
   - Check `/home/sudharshan.musali/internal_project/regx/backend/test_flask.py` line 168

2. **The 401 might be from a DIFFERENT API**:
   - Not the Cursor bridge, but the Nutanix AI endpoint
   - Check `AI_BASE` and `AI_API_KEY` in test_flask.py

Let me know if you need help with any of these steps!
