# Fix Summary: Cursor AI Chat HTTP 401 Error

## Problem
When asking questions in the Cursor AI Interactive chat, you were getting:
```
AI API error (HTTP 401)
```

## Root Cause
The Flask backend tries to call the **Nutanix Enterprise AI API** first, and only falls back to the Cursor Bridge if there's a **connection error**. 

HTTP errors (401, 403, 500, etc.) were **NOT triggering the fallback** - they were returned directly to the user as errors.

## The Fix
Changed the exception handling in `cursor_ai_chat()` function (line ~12348) to:
- **Before**: HTTPError → return error immediately (no fallback)
- **After**: HTTPError → fallback to Cursor Bridge

Now both connection errors AND HTTP errors trigger the Cursor Bridge fallback.

## What to Do Now

### 1. Restart Flask Backend
The Flask backend needs to be restarted to load the updated code:

```bash
# Stop the current Flask process (Ctrl+C or kill the PID)
# Then restart:
cd /home/sudharshan.musali/internal_project/regx
python backend/test_flask.py
```

### 2. Make Sure Cursor Bridge is Running
The cursor-bridge must be running on port 5002:

```bash
cd cursor-bridge
CURSOR_API_KEY=crsr_44ac6d4c67cb40aec7c3cc052becff81b9148910efb84ffc367fabcacda36575 npm start
```

### 3. Test Again
Go to the Cursor AI Interactive chat and ask: "what is Jita"

**Expected behavior now:**
1. ✅ Nutanix AI fails with HTTP 401 (invalid key)
2. ✅ System automatically falls back to Cursor Bridge
3. ✅ You get an answer from the Cursor Bridge!

## Check Flask Logs
When you test, the Flask logs should show:
```
[cursor-ai-chat] HTTP error: 401 - ...
[cursor-ai-chat] Nutanix AI returned HTTP 401, falling back to Cursor Bridge
```

Then the Cursor Bridge should provide the answer.

## Files Changed
- `/home/sudharshan.musali/internal_project/regx/backend/test_flask.py` (line ~12348-12395)

## Long-term Fix
To avoid the fallback and use Nutanix AI directly, you'll need to:
1. Get a valid Nutanix Enterprise AI API key
2. Update `AI_API_KEY` in `backend/test_flask.py` line 168
3. Restart Flask backend
