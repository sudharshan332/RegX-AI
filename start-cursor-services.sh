#!/bin/bash
# Start both RegX Cursor services
# Run this from the regx/ directory

echo "Starting RegX Cursor Bridge services..."
echo ""

# Terminal 1: Cursor Bridge (port 5002) - Main AI chat server
echo "Starting Cursor Bridge on port 5002..."
cd cursor-bridge
CURSOR_API_KEY=crsr_44ac6d4c67cb40aec7c3cc052becff81b9148910efb84ffc367fabcacda36575 npm start &
BRIDGE_PID=$!

sleep 3

# Terminal 2: RegX MCP Server (port 5003) - MCP tools provider
echo "Starting RegX MCP Server on port 5003..."
cd cursor-bridge
REGX_BACKEND_URL="http://10.111.52.90:5001" npm run start:mcp &
MCP_PID=$!

sleep 2

echo ""
echo "✅ Both services started!"
echo "   - Cursor Bridge (AI chat): http://localhost:5002"
echo "   - RegX MCP Server (tools):  http://localhost:5003"
echo ""
echo "To stop: kill $BRIDGE_PID $MCP_PID"
echo ""
echo "Press Ctrl+C to stop both services"

# Wait for Ctrl+C
trap "kill $BRIDGE_PID $MCP_PID; exit" INT
wait
