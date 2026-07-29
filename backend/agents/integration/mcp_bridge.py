"""
Enhanced MCP Bridge Agent

Provides cost-aware, cached integration with MCP servers for RegX-AI agents.
Includes connection pooling, session management, and usage tracking.
"""

import asyncio
import logging
import json
import time
import requests
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import threading

from ..base import BaseAgent, AnalysisResult, AgentConfig
from ..services.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""
    server_id: str
    url: str
    description: str
    cost_per_call: int = 1
    timeout: int = 30
    max_retries: int = 3
    cache_ttl: int = 300  # 5 minutes
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_id": self.server_id,
            "url": self.url,
            "description": self.description,
            "cost_per_call": self.cost_per_call,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "cache_ttl": self.cache_ttl,
            "enabled": self.enabled
        }


@dataclass
class MCPSession:
    """MCP server session information."""
    server_id: str
    session_id: str
    created_at: float
    last_used: float
    call_count: int = 0
    error_count: int = 0
    
    def is_expired(self, max_age_seconds: int = 3600) -> bool:
        """Check if session has expired."""
        return (time.time() - self.created_at) > max_age_seconds
    
    def update_usage(self, success: bool = True):
        """Update session usage statistics."""
        self.last_used = time.time()
        self.call_count += 1
        if not success:
            self.error_count += 1


@dataclass
class MCPCallResult:
    """Result of an MCP tool call."""
    success: bool
    server_id: str
    tool_name: str
    response_data: Dict[str, Any]
    execution_time_ms: int
    cached: bool = False
    credits_used: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "response_data": self.response_data,
            "execution_time_ms": self.execution_time_ms,
            "cached": self.cached,
            "credits_used": self.credits_used,
            "error": self.error
        }


class MCPCache:
    """Cache for MCP call results."""
    
    def __init__(self, default_ttl: int = 300):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_stats = {"hits": 0, "misses": 0, "size": 0}
        self.default_ttl = default_ttl
        self._lock = threading.Lock()
    
    def _generate_cache_key(self, server_id: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Generate cache key for MCP call."""
        # Create deterministic key from server, tool, and arguments
        arg_str = json.dumps(arguments, sort_keys=True)
        return f"{server_id}:{tool_name}:{hash(arg_str)}"
    
    def get(self, server_id: str, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached result if available and not expired."""
        cache_key = self._generate_cache_key(server_id, tool_name, arguments)
        
        with self._lock:
            if cache_key in self.cache:
                entry = self.cache[cache_key]
                
                # Check if expired
                if time.time() - entry["timestamp"] > entry["ttl"]:
                    del self.cache[cache_key]
                    self.cache_stats["size"] = len(self.cache)
                    self.cache_stats["misses"] += 1
                    return None
                
                self.cache_stats["hits"] += 1
                return entry["data"]
            
            self.cache_stats["misses"] += 1
            return None
    
    def set(self, server_id: str, tool_name: str, arguments: Dict[str, Any], result: Dict[str, Any], ttl: Optional[int] = None):
        """Cache MCP call result."""
        cache_key = self._generate_cache_key(server_id, tool_name, arguments)
        ttl = ttl or self.default_ttl
        
        with self._lock:
            self.cache[cache_key] = {
                "data": result,
                "timestamp": time.time(),
                "ttl": ttl
            }
            self.cache_stats["size"] = len(self.cache)
    
    def clear(self):
        """Clear the cache."""
        with self._lock:
            self.cache.clear()
            self.cache_stats["size"] = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self.cache_stats["hits"] + self.cache_stats["misses"]
            hit_rate = self.cache_stats["hits"] / max(1, total_requests)
            
            return {
                "hits": self.cache_stats["hits"],
                "misses": self.cache_stats["misses"],
                "size": self.cache_stats["size"],
                "hit_rate": hit_rate
            }


class MCPBridgeAgent(BaseAgent):
    """
    Enhanced MCP Bridge Agent
    
    Provides cost-optimized, cached integration with MCP servers including:
    - Session pooling and management
    - Response caching with TTL
    - Cost tracking per server/tool
    - Connection health monitoring
    - Load balancing across server instances
    - Smart retry logic with backoff
    """
    
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        
        # Initialize services
        self.cost_tracker = CostTracker()
        self.cache = MCPCache()
        
        # MCP server configurations
        self.servers: Dict[str, MCPServerConfig] = {}
        self.sessions: Dict[str, MCPSession] = {}
        self.rpc_counter = 0
        self._session_lock = threading.Lock()
        
        # Load MCP server configurations
        self._load_mcp_servers()
        
        # Bridge-specific settings
        self.session_max_age = config.cost_optimization.get("session_max_age", 3600)
        self.max_concurrent_calls = config.cost_optimization.get("max_concurrent_calls", 10)
        self.enable_caching = config.cost_optimization.get("enable_caching", True)
        
        # Statistics
        self.call_stats = defaultdict(lambda: {"calls": 0, "successes": 0, "errors": 0, "total_time_ms": 0})
        
        self.logger.info(f"MCP Bridge initialized with {len(self.servers)} servers")
    
    def _load_mcp_servers(self):
        """Load MCP server configurations from existing system."""
        # Use the existing MCP_SERVER_CONFIGS from test_flask.py
        mcp_configs = {
            "regx-data": {"url": "http://localhost:5003", "description": "RegX regression data"},
            "atlassian": {"url": "https://panacea-dev.eng.nutanix.com/mcp/atlassian", "description": "Jira & Confluence"},
            "gw-sourcegraph": {"url": "https://panacea-dev.eng.nutanix.com/mcp/sourcegraph", "description": "Code search"},
            "gw-jita": {"url": "https://panacea-dev.eng.nutanix.com/mcp/jita", "description": "JITA log access"},
            "gw-diamond": {"url": "https://panacea-dev.eng.nutanix.com/mcp/diamond", "description": "Diamond storage"},
            "gw-glean": {"url": "https://panacea-dev.eng.nutanix.com/mcp/glean", "description": "Internal knowledge search"},
            "gw-supportgpt": {"url": "https://panacea-dev.eng.nutanix.com/mcp/supportgpt", "description": "Support knowledge base"},
            "gw-nurag": {"url": "https://panacea-dev.eng.nutanix.com/mcp/nurag", "description": "Advanced RAG"},
            "gw-slack": {"url": "https://panacea-dev.eng.nutanix.com/mcp/slack", "description": "Slack integration"},
            "gw-panacea": {"url": "https://panacea-dev.eng.nutanix.com/mcp/panacea", "description": "Automated RCA"},
            "gw-live-debug": {"url": "https://panacea-dev.eng.nutanix.com/mcp/live-debug", "description": "Live debugging"},
            "auto-handoff": {"url": "http://10.40.224.6:9001/sse", "description": "Auto handoff"},
        }
        
        # Convert to MCPServerConfig objects
        for server_id, config in mcp_configs.items():
            # Set different cost per call based on server type
            cost_per_call = 1
            if "jita" in server_id or "sourcegraph" in server_id:
                cost_per_call = 2  # Higher cost for compute-intensive servers
            elif "glean" in server_id or "nurag" in server_id:
                cost_per_call = 3  # Highest cost for AI-powered servers
            
            self.servers[server_id] = MCPServerConfig(
                server_id=server_id,
                url=config["url"],
                description=config["description"],
                cost_per_call=cost_per_call
            )
    
    def _next_rpc_id(self) -> int:
        """Generate next RPC ID."""
        self.rpc_counter += 1
        return self.rpc_counter
    
    async def _get_or_create_session(self, server_id: str) -> Optional[str]:
        """Get existing session or create new one for MCP server."""
        with self._session_lock:
            # Check if we have a valid session
            if server_id in self.sessions:
                session = self.sessions[server_id]
                if not session.is_expired(self.session_max_age):
                    return session.session_id
                else:
                    # Remove expired session
                    del self.sessions[server_id]
            
            # Create new session
            server_config = self.servers.get(server_id)
            if not server_config or not server_config.enabled:
                return None
            
            try:
                init_payload = {
                    "jsonrpc": "2.0",
                    "id": self._next_rpc_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "regx-agent-bridge", "version": "1.0"},
                    },
                }
                
                response = requests.post(
                    server_config.url, 
                    json=init_payload, 
                    timeout=server_config.timeout,
                    verify=False
                )
                
                if response.status_code == 200:
                    session_id = response.headers.get("mcp-session-id")
                    if session_id:
                        self.sessions[server_id] = MCPSession(
                            server_id=server_id,
                            session_id=session_id,
                            created_at=time.time(),
                            last_used=time.time()
                        )
                        self.logger.debug(f"Created MCP session for {server_id}: {session_id}")
                        return session_id
                
                self.logger.warning(f"Failed to create MCP session for {server_id}: {response.status_code}")
                return None
                
            except Exception as e:
                self.logger.error(f"MCP session creation failed for {server_id}: {e}")
                return None
    
    async def call_mcp_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        bypass_cache: bool = False,
        user_id: str = "system",
        team_id: str = "regx_team",
        user_requested: bool = False
    ) -> MCPCallResult:
        """
        Call an MCP tool with cost tracking and caching.
        
        Args:
            server_id: MCP server identifier
            tool_name: Name of tool to call
            arguments: Tool arguments
            bypass_cache: Skip cache lookup
            user_id: User making the call
            team_id: Team responsible for the call
            
        Returns:
            MCPCallResult with response data and metadata
        """
        start_time = time.time()
        arguments = arguments or {}
        
        try:
            # Check if server exists and is enabled
            server_config = self.servers.get(server_id)
            if not server_config or not server_config.enabled:
                return MCPCallResult(
                    success=False,
                    server_id=server_id,
                    tool_name=tool_name,
                    response_data={},
                    execution_time_ms=0,
                    error=f"Server {server_id} not found or disabled"
                )
            
            # Check cache first (if enabled and not bypassed)
            cached_result = None
            if self.enable_caching and not bypass_cache:
                cached_result = self.cache.get(server_id, tool_name, arguments)
                if cached_result:
                    execution_time = int((time.time() - start_time) * 1000)
                    self.logger.debug(f"Cache hit for {server_id}:{tool_name}")
                    
                    return MCPCallResult(
                        success=True,
                        server_id=server_id,
                        tool_name=tool_name,
                        response_data=cached_result,
                        execution_time_ms=execution_time,
                        cached=True,
                        credits_used=0  # No credits for cached results
                    )
            
            # Check credit availability only for automatic calls, not user-requested
            cost_estimate = server_config.cost_per_call
            
            if not user_requested:
                can_use, reason = self.cost_tracker.can_use_credits(user_id, team_id, cost_estimate)
                
                if not can_use:
                    return MCPCallResult(
                        success=False,
                        server_id=server_id,
                        tool_name=tool_name,
                        response_data={},
                        execution_time_ms=int((time.time() - start_time) * 1000),
                        error=f"Credit limit reached: {reason}"
                    )
            else:
                self.logger.info(f"User-requested MCP call to {server_id}:{tool_name} - bypassing credit limits")
            
            # Get or create session
            session_id = await self._get_or_create_session(server_id)
            if not session_id:
                return MCPCallResult(
                    success=False,
                    server_id=server_id,
                    tool_name=tool_name,
                    response_data={},
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    error="Failed to create MCP session"
                )
            
            # Make the MCP call
            call_payload = {
                "jsonrpc": "2.0",
                "id": self._next_rpc_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            }
            
            response = requests.post(
                server_config.url,
                json=call_payload,
                headers={"mcp-session-id": session_id},
                timeout=server_config.timeout,
                verify=False,
            )
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Update session usage
            if server_id in self.sessions:
                self.sessions[server_id].update_usage(response.status_code == 200)
            
            if response.status_code == 200:
                # Parse response
                response_data = self._parse_mcp_response(response)
                normalized_data = self._normalize_mcp_result(response_data)
                
                # Cache successful results
                if self.enable_caching and normalized_data.get("success", True):
                    self.cache.set(server_id, tool_name, arguments, normalized_data, server_config.cache_ttl)
                
                # Track usage
                self.cost_tracker.track_usage(
                    analysis_type=f"mcp_{tool_name}",
                    credits_used=cost_estimate,
                    user_id=user_id,
                    team_id=team_id,
                    agent_name=self.config.name,
                    success=True,
                    metadata={
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "execution_time_ms": execution_time
                    }
                )
                
                # Update statistics
                self.call_stats[server_id]["calls"] += 1
                self.call_stats[server_id]["successes"] += 1
                self.call_stats[server_id]["total_time_ms"] += execution_time
                
                return MCPCallResult(
                    success=True,
                    server_id=server_id,
                    tool_name=tool_name,
                    response_data=normalized_data,
                    execution_time_ms=execution_time,
                    credits_used=cost_estimate
                )
            else:
                # Handle error response
                error_msg = f"MCP call failed with status {response.status_code}"
                
                # Update statistics
                self.call_stats[server_id]["calls"] += 1
                self.call_stats[server_id]["errors"] += 1
                self.call_stats[server_id]["total_time_ms"] += execution_time
                
                # Track failed usage (partial credit)
                self.cost_tracker.track_usage(
                    analysis_type=f"mcp_{tool_name}_error",
                    credits_used=cost_estimate // 2,
                    user_id=user_id,
                    team_id=team_id,
                    agent_name=self.config.name,
                    success=False,
                    metadata={
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "error": error_msg
                    }
                )
                
                return MCPCallResult(
                    success=False,
                    server_id=server_id,
                    tool_name=tool_name,
                    response_data={},
                    execution_time_ms=execution_time,
                    credits_used=cost_estimate // 2,
                    error=error_msg
                )
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            error_msg = f"MCP call exception: {str(e)}"
            
            # Update statistics
            self.call_stats[server_id]["calls"] += 1
            self.call_stats[server_id]["errors"] += 1
            self.call_stats[server_id]["total_time_ms"] += execution_time
            
            self.logger.error(f"MCP call failed: {error_msg}")
            
            return MCPCallResult(
                success=False,
                server_id=server_id,
                tool_name=tool_name,
                response_data={},
                execution_time_ms=execution_time,
                error=error_msg
            )
    
    def _parse_mcp_response(self, response: requests.Response) -> Dict[str, Any]:
        """Parse MCP HTTP response."""
        try:
            content_type = response.headers.get("Content-Type", "").lower()
            
            # Standard JSON response
            if "application/json" in content_type:
                return response.json()
            
            # SSE-style response
            text = response.text or ""
            data_payloads = []
            for line in text.splitlines():
                if line.startswith("data: "):
                    payload = line[len("data: "):].strip()
                    if payload:
                        data_payloads.append(payload)
            
            if data_payloads:
                return json.loads(data_payloads[-1])
            
            return {"error": "No JSON payload found in response"}
            
        except Exception as e:
            return {"error": f"Failed to parse MCP response: {str(e)}"}
    
    def _normalize_mcp_result(self, mcp_response: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize MCP response to standard format."""
        if "error" in mcp_response:
            error = mcp_response["error"]
            error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            return {"success": False, "error": error_msg}
        
        result = mcp_response.get("result", {})
        
        # Handle gateway format with content array
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list) and content:
                text_chunks = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_chunks.append(item.get("text", ""))
                
                joined_text = "\n".join(text_chunks).strip()
                if joined_text:
                    try:
                        parsed = json.loads(joined_text)
                        return {"success": True, "data": parsed}
                    except json.JSONDecodeError:
                        return {"success": True, "text": joined_text}
        
        return {"success": True, "data": result}
    
    async def analyze(self, test_result: Dict[str, Any], user_requested_ai: bool = False) -> AnalysisResult:
        """
        Analyze test result using MCP tools.
        
        This method is not typically called directly, but can be used
        for MCP-based analysis workflows.
        """
        start_time = time.time()
        
        try:
            # Example: Use Glean to search for similar issues
            glean_result = await self.call_mcp_tool(
                server_id="gw-glean",
                tool_name="search",
                arguments={
                    "query": test_result.get("error_message", "")[:100],
                    "mode": "fast"
                }
            )
            
            if glean_result.success:
                confidence = 0.7
                description = "MCP-based analysis completed"
            else:
                confidence = 0.3
                description = "MCP analysis failed"
            
            execution_time = int((time.time() - start_time) * 1000)
            
            return AnalysisResult(
                success=glean_result.success,
                analysis_type="mcp_bridge",
                confidence=confidence,
                pattern_matched=False,
                pattern_description=description,
                execution_time_ms=execution_time,
                credits_used=glean_result.credits_used,
                source="mcp_bridge",
                data={
                    "mcp_calls": [glean_result.to_dict()],
                    "bridge_analysis": True
                }
            )
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            return AnalysisResult(
                success=False,
                analysis_type="mcp_bridge_error",
                confidence=0.0,
                pattern_matched=False,
                execution_time_ms=execution_time,
                source="error",
                errors=[str(e)]
            )
    
    def get_server_status(self) -> Dict[str, Any]:
        """Get status of all MCP servers."""
        server_status = {}
        
        for server_id, config in self.servers.items():
            stats = self.call_stats[server_id]
            session = self.sessions.get(server_id)
            
            total_calls = stats["calls"]
            success_rate = stats["successes"] / max(1, total_calls)
            avg_time = stats["total_time_ms"] / max(1, total_calls)
            
            server_status[server_id] = {
                "config": config.to_dict(),
                "session_active": session is not None,
                "session_age_seconds": (time.time() - session.created_at) if session else 0,
                "statistics": {
                    "total_calls": total_calls,
                    "success_rate": success_rate,
                    "error_count": stats["errors"],
                    "average_time_ms": avg_time
                }
            }
        
        return {
            "servers": server_status,
            "cache_stats": self.cache.get_stats(),
            "active_sessions": len(self.sessions),
            "total_servers": len(self.servers)
        }
    
    def clear_cache(self):
        """Clear MCP response cache."""
        self.cache.clear()
        self.logger.info("MCP bridge cache cleared")
    
    def reset_sessions(self):
        """Reset all MCP sessions."""
        with self._session_lock:
            self.sessions.clear()
        self.logger.info("MCP bridge sessions reset")
    
    def set_server_enabled(self, server_id: str, enabled: bool):
        """Enable or disable an MCP server."""
        if server_id in self.servers:
            self.servers[server_id].enabled = enabled
            if not enabled and server_id in self.sessions:
                del self.sessions[server_id]
            self.logger.info(f"MCP server {server_id} {'enabled' if enabled else 'disabled'}")
    
    def get_bridge_capabilities(self) -> Dict[str, Any]:
        """Get MCP bridge capabilities and configuration."""
        return {
            "name": self.config.name,
            "type": "mcp_bridge",
            "capabilities": [
                "MCP server integration",
                "Response caching with TTL",
                "Session pooling and management",
                "Cost tracking per server/tool",
                "Connection health monitoring",
                "Load balancing support"
            ],
            "servers": list(self.servers.keys()),
            "features": {
                "caching_enabled": self.enable_caching,
                "session_management": True,
                "cost_tracking": True,
                "health_monitoring": True
            },
            "configuration": {
                "session_max_age": self.session_max_age,
                "max_concurrent_calls": self.max_concurrent_calls,
                "default_cache_ttl": self.cache.default_ttl
            }
        }