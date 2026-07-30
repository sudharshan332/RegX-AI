#!/usr/bin/env node
/**
 * Test script to validate Cursor API key
 * Usage: CURSOR_API_KEY=crsr_xxx node test-api-key.js
 */

const API_KEY = process.env.CURSOR_API_KEY;

if (!API_KEY) {
  console.error("❌ CURSOR_API_KEY environment variable not set");
  console.log("\nUsage: CURSOR_API_KEY=crsr_xxx node test-api-key.js");
  process.exit(1);
}

console.log("🔑 Testing API key:", API_KEY.substring(0, 10) + "...");
console.log("");

// Test 1: Check /v1/me endpoint
async function testMe() {
  console.log("Test 1: Checking API key validity with /v1/me endpoint...");
  try {
    const response = await fetch("https://api.cursor.com/v1/me", {
      headers: {
        "Authorization": `Bearer ${API_KEY}`,
      },
    });

    console.log("  Status:", response.status, response.statusText);
    
    if (response.ok) {
      const data = await response.json();
      console.log("  ✅ API key is valid!");
      console.log("  User info:", JSON.stringify(data, null, 2));
      return true;
    } else {
      const errorText = await response.text();
      console.log("  ❌ API key validation failed");
      console.log("  Response:", errorText);
      return false;
    }
  } catch (error) {
    console.log("  ❌ Network error:", error.message);
    return false;
  }
}

// Test 2: Try to create an agent with the SDK
async function testAgent() {
  console.log("\nTest 2: Testing agent creation with @cursor/sdk...");
  try {
    const { Agent } = await import("@cursor/sdk");
    
    console.log("  Creating agent...");
    const agent = await Agent.create({
      apiKey: API_KEY,
      model: { id: "claude-sonnet-4-6" },
    });
    
    console.log("  ✅ Agent created successfully!");
    console.log("  Agent ID:", agent.agentId);
    
    // Clean up
    await agent[Symbol.asyncDispose]();
    return true;
  } catch (error) {
    console.log("  ❌ Agent creation failed");
    console.log("  Error:", error.message);
    if (error.cause) {
      console.log("  Cause:", error.cause);
    }
    return false;
  }
}

// Run tests
(async () => {
  const meValid = await testMe();
  
  if (meValid) {
    await testAgent();
  } else {
    console.log("\n⚠️  Skipping agent test because API key validation failed");
    console.log("\nPossible issues:");
    console.log("  1. API key might be expired or invalid");
    console.log("  2. API key might not be activated yet");
    console.log("  3. You might need to create the key at: https://cursor.com/dashboard/api");
    console.log("  4. Your account might not have Cloud Agents access");
  }
  
  console.log("\n" + "=".repeat(60));
})();
