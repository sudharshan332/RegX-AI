# Cursor Bridge - API Key Testing Guide

## The Issue

The `.env.example` had incorrect information. According to official Cursor documentation:

- ✅ **Correct format**: `crsr_...` (what you have)
- ❌ **Wrong**: `cursor_...` (what the example said)

Your API key format is **correct**! The HTTP 401 error is coming from something else.

## Test Your API Key

Run this command with your actual API key:

```bash
cd cursor-bridge
CURSOR_API_KEY=crsr_9exxx node test-api-key.js
```

Replace `crsr_9exxx` with your full API key.

## Expected Results

The test will:
1. Validate your API key against Cursor's `/v1/me` endpoint
2. Try to create an agent with the Cursor SDK
3. Show you the exact error if something fails

## Common Issues & Solutions

### If you get HTTP 401:

**Issue 1: API Key Not Activated**
- Some API keys need a few minutes to activate after creation
- Wait 5 minutes and try again

**Issue 2: Wrong Dashboard**
- Make sure you created the key at: https://cursor.com/dashboard/api
- NOT at model settings or other places

**Issue 3: Account Access**
- Verify your Cursor account has access to Cloud Agents API
- Check if your plan supports programmatic access

**Issue 4: Key Already Used**
- The key is shown only once during creation
- If you didn't copy the full key, you'll need to create a new one

### If you get HTTP 403:

- Your key works but lacks permissions for Cloud Agents
- You may need to upgrade your Cursor plan

### If you get Connection Errors:

- Check if you can reach: https://api.cursor.com
- You might be behind a firewall or proxy

## Next Steps

1. Run the test script above
2. Share the output with me if it fails
3. I'll help debug based on the actual error message

## Once Working

When your key works, restart the cursor-bridge:

```bash
cd cursor-bridge
CURSOR_API_KEY=crsr_your_actual_key npm start
```

Or create a `.env` file:

```bash
# cursor-bridge/.env
CURSOR_API_KEY=crsr_your_actual_key
CURSOR_BRIDGE_PORT=5002
CURSOR_MODEL_ID=claude-sonnet-4-6
```

Then just run: `npm start`
