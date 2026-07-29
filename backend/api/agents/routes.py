"""
REST API endpoints for RegX-AI agent management and analysis.

Provides comprehensive API for agent operations, cost tracking, pattern management,
and analysis execution with proper authentication and error handling.
"""

import logging
import time
from flask import Blueprint, request, jsonify, g
from typing import Dict, List, Optional, Any
import asyncio

# Import agent framework components
from ...agents.registry import agent_registry
from ...agents.handoff import handoff_manager
from ...agents.services.pattern_cache import PatternCache
from ...agents.services.cost_tracker import CostTracker
from ...agents.integration.mcp_bridge import MCPBridgeAgent
from ...agents.base import AgentConfig

# Import existing auth decorator
from ...auth import jwt_required

logger = logging.getLogger(__name__)

# Create blueprint
agents_bp = Blueprint('agents', __name__, url_prefix='/api/agents')

# Initialize services
pattern_cache = PatternCache()
cost_tracker = CostTracker()


def async_route(f):
    """Decorator to run async functions in Flask routes."""
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(f(*args, **kwargs))
        finally:
            loop.close()
    wrapper.__name__ = f.__name__
    return wrapper


@agents_bp.route('/status', methods=['GET'])
@jwt_required
def get_agent_status():
    """Get overall agent system status."""
    try:
        registry_status = agent_registry.get_registry_status()
        handoff_stats = handoff_manager.get_handoff_statistics(7)
        pattern_stats = pattern_cache.get_pattern_stats()
        
        return jsonify({
            "success": True,
            "timestamp": time.time(),
            "registry": registry_status,
            "handoffs": handoff_stats,
            "patterns": pattern_stats,
            "system_health": {
                "agents_healthy": registry_status["healthy_agents"] / max(1, registry_status["total_agents"]),
                "handoff_success_rate": handoff_stats["success_rate"],
                "pattern_hit_rate": pattern_stats["cache_hit_rate"]
            }
        })
    except Exception as e:
        logger.error(f"Failed to get agent status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/analyze', methods=['POST'])
@jwt_required
@async_route
async def analyze_test_failure():
    """Analyze test failure using the agent framework."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        test_result = data.get('test_result')
        if not test_result:
            return jsonify({"success": False, "error": "test_result is required"}), 400
        
        # Optional parameters
        preferred_agent_type = data.get('preferred_agent_type')
        user_id = data.get('user_id', 'api_user')
        team_id = data.get('team_id', 'regx_team')
        user_requested_ai = data.get('deep_ai_analysis', False)  # User explicitly requests AI analysis
        
        # Add user context to test result
        test_result['_analysis_context'] = {
            'user_id': user_id,
            'team_id': team_id,
            'api_request': True,
            'user_requested_ai': user_requested_ai,
            'timestamp': time.time()
        }
        
        # Use handoff manager for orchestrated analysis
        result = await handoff_manager.orchestrate_analysis(
            test_result,
            preferred_agent_type,
            user_requested_ai
        )
        
        if result:
            return jsonify({
                "success": True,
                "analysis": {
                    "analysis_type": result.analysis_type,
                    "confidence": result.confidence,
                    "pattern_matched": result.pattern_matched,
                    "pattern_description": result.pattern_description,
                    "rdm_category": result.rdm_category,
                    "credits_used": result.credits_used,
                    "execution_time_ms": result.execution_time_ms,
                    "source": result.source,
                    "data": result.data,
                    "errors": result.errors
                },
                "timestamp": time.time()
            })
        else:
            return jsonify({
                "success": False,
                "error": "No analysis result obtained"
            }), 500
            
    except Exception as e:
        logger.error(f"Analysis API failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/intelligent-triage', methods=['POST'])
@jwt_required
@async_route
async def intelligent_triage_analysis():
    """
    Perform intelligent triage analysis with history-based logic.
    
    Implements the enhanced analysis flow:
    - Failed tests: History check → Intermittent detection → First Level AI
    - Skipped tests: Pattern match → First Level AI → Glean search
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        test_result = data.get('test_result')
        if not test_result:
            return jsonify({"success": False, "error": "test_result is required"}), 400
        
        # Get intelligent triage agent
        triage_agents = agent_registry.get_agents_by_type("intelligent_triage")
        if not triage_agents:
            return jsonify({
                "success": False,
                "error": "Intelligent triage agent not available"
            }), 404
        
        triage_agent = triage_agents[0]
        
        # Perform intelligent analysis
        result = await triage_agent.analyze(test_result)
        
        return jsonify({
            "success": True,
            "intelligent_triage": {
                "analysis_type": result.analysis_type,
                "confidence": result.confidence,
                "pattern_matched": result.pattern_matched,
                "pattern_description": result.pattern_description,
                "rdm_category": result.rdm_category,
                "credits_used": result.credits_used,
                "execution_time_ms": result.execution_time_ms,
                "source": result.source,
                "data": result.data,
                "errors": result.errors
            },
            "timestamp": time.time()
        })
        
    except Exception as e:
        logger.error(f"Intelligent triage failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/agents', methods=['GET'])
@jwt_required
def list_agents():
    """List all registered agents with their capabilities."""
    try:
        agents_info = []
        
        for agent in agent_registry.agents.values():
            agent_info = agent.get_status()
            
            # Add capability information if available
            if hasattr(agent, 'get_agent_capabilities'):
                capabilities = agent.get_agent_capabilities()
                agent_info['capabilities'] = capabilities
            
            agents_info.append(agent_info)
        
        return jsonify({
            "success": True,
            "agents": agents_info,
            "total_agents": len(agents_info)
        })
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/agents/<agent_name>', methods=['GET'])
@jwt_required
def get_agent_details(agent_name: str):
    """Get detailed information about a specific agent."""
    try:
        agent = agent_registry.get_agent(agent_name)
        if not agent:
            return jsonify({"success": False, "error": f"Agent {agent_name} not found"}), 404
        
        agent_info = agent.get_status()
        
        # Add detailed capability information
        if hasattr(agent, 'get_agent_capabilities'):
            agent_info['capabilities'] = agent.get_agent_capabilities()
        
        # Add configuration information
        agent_info['configuration'] = {
            'name': agent.config.name,
            'type': agent.config.type,
            'skill_wrapper': agent.config.skill_wrapper,
            'cost_optimization': agent.config.cost_optimization,
            'triggers': agent.config.triggers,
            'mcp_dependencies': agent.config.mcp_dependencies
        }
        
        return jsonify({
            "success": True,
            "agent": agent_info
        })
    except Exception as e:
        logger.error(f"Failed to get agent details: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/agents/<agent_name>/analyze', methods=['POST'])
@jwt_required
@async_route
async def analyze_with_specific_agent(agent_name: str):
    """Analyze test failure using a specific agent."""
    try:
        agent = agent_registry.get_agent(agent_name)
        if not agent:
            return jsonify({"success": False, "error": f"Agent {agent_name} not found"}), 404
        
        data = request.get_json()
        if not data or 'test_result' not in data:
            return jsonify({"success": False, "error": "test_result is required"}), 400
        
        test_result = data['test_result']
        user_requested_ai = data.get('deep_ai_analysis', False)
        
        # Check if agent can handle this test result
        if not agent.can_handle(test_result):
            return jsonify({
                "success": False,
                "error": f"Agent {agent_name} cannot handle this test result"
            }), 400
        
        # Perform analysis
        result = await agent.analyze(test_result, user_requested_ai)
        
        return jsonify({
            "success": True,
            "agent": agent_name,
            "analysis": {
                "analysis_type": result.analysis_type,
                "confidence": result.confidence,
                "pattern_matched": result.pattern_matched,
                "pattern_description": result.pattern_description,
                "rdm_category": result.rdm_category,
                "credits_used": result.credits_used,
                "execution_time_ms": result.execution_time_ms,
                "source": result.source,
                "data": result.data,
                "errors": result.errors
            }
        })
        
    except Exception as e:
        logger.error(f"Specific agent analysis failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/cost/status', methods=['GET'])
@jwt_required
def get_cost_status():
    """Get cost tracking status and budget information."""
    try:
        # Get query parameters
        entity_id = request.args.get('entity_id', 'regx_team')
        days = int(request.args.get('days', 7))
        
        # Get cost analytics
        analytics = cost_tracker.get_cost_analytics(days)
        
        # Get budget status
        budget_status = cost_tracker.get_budget_status(entity_id)
        
        # Get optimization recommendations
        recommendations = cost_tracker.optimize_recommendations()
        
        return jsonify({
            "success": True,
            "entity_id": entity_id,
            "period_days": days,
            "analytics": analytics,
            "budget_status": budget_status,
            "recommendations": recommendations,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"Failed to get cost status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/cost/budget', methods=['POST'])
@jwt_required
def set_budget():
    """Set or update credit budget for an entity."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        required_fields = ['entity_id', 'entity_type', 'daily_limit', 'weekly_limit', 'monthly_limit']
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"{field} is required"}), 400
        
        cost_tracker.set_budget(
            entity_id=data['entity_id'],
            entity_type=data['entity_type'],
            daily_limit=data['daily_limit'],
            weekly_limit=data['weekly_limit'],
            monthly_limit=data['monthly_limit'],
            priority=data.get('priority', 1),
            allow_overrun=data.get('allow_overrun', False),
            overrun_limit=data.get('overrun_limit', 0)
        )
        
        return jsonify({
            "success": True,
            "message": f"Budget set for {data['entity_id']}",
            "budget": cost_tracker.get_budget_status(data['entity_id'])
        })
        
    except Exception as e:
        logger.error(f"Failed to set budget: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/patterns/stats', methods=['GET'])
@jwt_required
def get_pattern_stats():
    """Get pattern matching statistics."""
    try:
        stats = pattern_cache.get_pattern_stats()
        
        return jsonify({
            "success": True,
            "statistics": stats,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"Failed to get pattern stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/patterns/search', methods=['POST'])
@jwt_required
def search_patterns():
    """Search for patterns matching criteria."""
    try:
        data = request.get_json()
        if not data or 'test_result' not in data:
            return jsonify({"success": False, "error": "test_result is required"}), 400
        
        test_result = data['test_result']
        min_confidence = data.get('min_confidence', 0.5)
        
        # Find best pattern match
        pattern_match = pattern_cache.find_best_pattern_match(test_result, min_confidence)
        
        if pattern_match:
            return jsonify({
                "success": True,
                "pattern_found": True,
                "pattern": pattern_match.to_dict()
            })
        else:
            return jsonify({
                "success": True,
                "pattern_found": False,
                "message": "No matching pattern found"
            })
            
    except Exception as e:
        logger.error(f"Pattern search failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/patterns/cache/clear', methods=['POST'])
@jwt_required
def clear_pattern_cache():
    """Clear the pattern analysis cache."""
    try:
        pattern_cache.clear_cache()
        
        return jsonify({
            "success": True,
            "message": "Pattern cache cleared"
        })
    except Exception as e:
        logger.error(f"Failed to clear pattern cache: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/handoffs/stats', methods=['GET'])
@jwt_required
def get_handoff_stats():
    """Get cross-skill handoff statistics."""
    try:
        days = int(request.args.get('days', 7))
        stats = handoff_manager.get_handoff_statistics(days)
        
        return jsonify({
            "success": True,
            "period_days": days,
            "statistics": stats,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"Failed to get handoff stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/handoffs/active', methods=['GET'])
@jwt_required
def get_active_handoffs():
    """Get currently active handoff operations."""
    try:
        active_handoffs = handoff_manager.get_active_handoffs()
        
        return jsonify({
            "success": True,
            "active_handoffs": active_handoffs,
            "count": len(active_handoffs)
        })
    except Exception as e:
        logger.error(f"Failed to get active handoffs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/handoffs/rules', methods=['GET'])
@jwt_required
def get_handoff_rules():
    """Get configured handoff rules."""
    try:
        rules = handoff_manager.get_handoff_rules()
        
        return jsonify({
            "success": True,
            "handoff_rules": rules,
            "count": len(rules)
        })
    except Exception as e:
        logger.error(f"Failed to get handoff rules: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/mcp/status', methods=['GET'])
@jwt_required
def get_mcp_status():
    """Get MCP bridge status and server information."""
    try:
        # Find MCP bridge agent
        mcp_agents = agent_registry.get_agents_by_type("mcp_bridge")
        if not mcp_agents:
            return jsonify({
                "success": False,
                "error": "No MCP bridge agent found"
            }), 404
        
        mcp_agent = mcp_agents[0]
        if hasattr(mcp_agent, 'get_server_status'):
            status = mcp_agent.get_server_status()
            return jsonify({
                "success": True,
                "mcp_status": status,
                "timestamp": time.time()
            })
        else:
            return jsonify({
                "success": False,
                "error": "MCP bridge agent does not support status reporting"
            }), 500
            
    except Exception as e:
        logger.error(f"Failed to get MCP status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/mcp/call', methods=['POST'])
@jwt_required
@async_route
async def call_mcp_tool():
    """Call an MCP tool directly."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        required_fields = ['server_id', 'tool_name']
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"{field} is required"}), 400
        
        # Find MCP bridge agent
        mcp_agents = agent_registry.get_agents_by_type("mcp_bridge")
        if not mcp_agents:
            return jsonify({
                "success": False,
                "error": "No MCP bridge agent available"
            }), 404
        
        mcp_agent = mcp_agents[0]
        
        # Make MCP call
        result = await mcp_agent.call_mcp_tool(
            server_id=data['server_id'],
            tool_name=data['tool_name'],
            arguments=data.get('arguments', {}),
            bypass_cache=data.get('bypass_cache', False),
            user_id=data.get('user_id', 'api_user'),
            team_id=data.get('team_id', 'regx_team')
        )
        
        return jsonify({
            "success": True,
            "mcp_result": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"MCP call failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/config/load', methods=['POST'])
@jwt_required
def load_agent_configs():
    """Load agent configurations from files."""
    try:
        loaded_count = agent_registry.load_agents_from_config()
        
        return jsonify({
            "success": True,
            "message": f"Loaded {loaded_count} agent configurations",
            "loaded_count": loaded_count
        })
    except Exception as e:
        logger.error(f"Failed to load agent configs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@agents_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint (no auth required)."""
    try:
        return jsonify({
            "success": True,
            "status": "healthy",
            "timestamp": time.time(),
            "version": "1.0.0",
            "components": {
                "agent_registry": len(agent_registry.agents) > 0,
                "pattern_cache": True,
                "cost_tracker": True,
                "handoff_manager": True
            }
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "status": "unhealthy",
            "error": str(e)
        }), 500


@agents_bp.route('/triage/auto-analyze', methods=['POST'])
async def auto_triage_analysis():
    """Perform automatic pattern-based triage analysis."""
    try:
        request_data = request.get_json()
        test_result = request_data.get("test_result", {})
        
        if not test_result:
            return jsonify({
                "success": False,
                "error": "test_result is required"
            }), 400
        
        # Get intelligent triage agent
        agent_registry = AgentRegistry()
        agent = agent_registry.get_agent("intelligent_triage")
        
        if not agent:
            return jsonify({
                "success": False,
                "error": "Intelligent triage agent not available"
            }), 503
        
        # Perform analysis (automatic, not user-requested)
        analysis_result = await agent.analyze(test_result, user_requested_ai=False)
        
        response_data = {
            "success": True,
            "analysis": analysis_result.__dict__ if hasattr(analysis_result, '__dict__') else analysis_result,
            "auto_triaged": analysis_result.confidence >= 0.9,
            "requires_manual_analysis": analysis_result.metadata.get("requires_manual_analysis", False)
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in auto triage analysis: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/triage/first-level-ai', methods=['POST'])
@jwt_required
@async_route
async def first_level_ai_analysis():
    """Trigger First Level AI analysis using JITA and Glean."""
    try:
        request_data = request.get_json()
        test_result = request_data.get("test_result", {})
        
        if not test_result:
            return jsonify({
                "success": False,
                "error": "test_result is required"
            }), 400
        
        # Initialize intelligent triage agent directly
        from ...agents.analysis.intelligent_triage_agent import IntelligentTriageAgent
        from ...agents.base import AgentConfig
        
        agent_config = AgentConfig(
            name="intelligent_triage",
            type="intelligent_triage"
        )
        agent = IntelligentTriageAgent(agent_config)
        
        # Perform First Level AI analysis (user-requested)
        analysis_result = await agent.analyze(test_result, user_requested_ai=True)
        
        # Handle different response formats
        if hasattr(analysis_result, '__dict__'):
            result_dict = analysis_result.__dict__
        else:
            result_dict = analysis_result
        
        response_data = {
            "success": True,
            "analysis_result": result_dict,
            "analysis_type": "first_level_ai", 
            "user_requested": True
        }
        
        # Add metadata if available
        if hasattr(analysis_result, 'data') and analysis_result.data:
            response_data.update(analysis_result.data)
        
        if hasattr(analysis_result, 'metadata') and analysis_result.metadata:
            response_data.update({
                "pattern_suggestion": analysis_result.metadata.get("pattern_suggestion"),
                "jita_analysis": analysis_result.metadata.get("jita_analysis"),
                "glean_results": analysis_result.metadata.get("glean_results")
            })
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in first level AI analysis: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/patterns/suggest', methods=['POST'])
async def suggest_pattern():
    """Suggest new pattern based on AI analysis results."""
    try:
        from ...agents.services.pattern_learning import PatternLearningService
        
        request_data = request.get_json()
        test_result = request_data.get("test_result", {})
        jita_analysis = request_data.get("jita_analysis", {})
        glean_results = request_data.get("glean_results", {})
        ai_analysis = request_data.get("ai_analysis", {})
        
        if not test_result:
            return jsonify({
                "success": False,
                "error": "test_result is required"
            }), 400
        
        # Create pattern learning service
        pattern_service = PatternLearningService()
        
        # Suggest pattern
        pattern_candidate = await pattern_service.suggest_pattern(
            test_result, jita_analysis, glean_results, ai_analysis
        )
        
        if not pattern_candidate:
            return jsonify({
                "success": False,
                "message": "No pattern could be suggested from the analysis"
            })
        
        response_data = {
            "success": True,
            "pattern_candidate": pattern_candidate.to_dict(),
            "suggestion_id": pattern_candidate.id
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error suggesting pattern: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/patterns/approve', methods=['POST'])
async def approve_pattern():
    """Approve, reject, or modify a suggested pattern."""
    try:
        from ...agents.services.pattern_learning import PatternLearningService
        
        request_data = request.get_json()
        request_id = request_data.get("request_id")
        pattern_id = request_data.get("pattern_id") 
        action = request_data.get("action", "").lower()
        user_response = request_data.get("user_response", {})
        
        if not (request_id or pattern_id):
            return jsonify({
                "success": False,
                "error": "request_id or pattern_id is required"
            }), 400
        
        if action not in ["approve", "reject", "modify"]:
            return jsonify({
                "success": False,
                "error": "action must be 'approve', 'reject', or 'modify'"
            }), 400
        
        # Create pattern learning service
        pattern_service = PatternLearningService()
        
        # Process user approval
        if request_id:
            result = await pattern_service.process_user_approval(request_id, {
                "action": action,
                **user_response
            })
        else:
            # For direct pattern ID approval (fallback)
            result = {
                "success": True,
                "action": f"pattern_{action}d",
                "pattern_id": pattern_id
            }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error processing pattern approval: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/triage/retrigger', methods=['POST'])
async def retrigger_analysis():
    """Retrigger analysis after pattern addition."""
    try:
        request_data = request.get_json()
        test_result = request_data.get("test_result", {})
        force_refresh = request_data.get("force_refresh", True)
        
        if not test_result:
            return jsonify({
                "success": False,
                "error": "test_result is required"
            }), 400
        
        # Get intelligent triage agent
        agent_registry = AgentRegistry()
        agent = agent_registry.get_agent("intelligent_triage")
        
        if not agent:
            return jsonify({
                "success": False,
                "error": "Intelligent triage agent not available"
            }), 503
        
        # Force refresh patterns if requested
        if force_refresh:
            # Reload patterns
            agent.intermittent_patterns = agent._load_intermittent_patterns()
            agent.rdm_patterns = agent._load_rdm_patterns()
        
        # Re-run analysis
        analysis_result = await agent.analyze(test_result, user_requested_ai=False)
        
        response_data = {
            "success": True,
            "analysis": analysis_result.__dict__ if hasattr(analysis_result, '__dict__') else analysis_result,
            "retriggered": True,
            "patterns_refreshed": force_refresh
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error retriggering analysis: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/patterns/pending', methods=['GET'])
async def get_pending_patterns():
    """Get patterns awaiting user approval."""
    try:
        from ...agents.services.pattern_learning import PatternLearningService
        
        pattern_service = PatternLearningService()
        
        # Get pending pattern candidates
        pending_patterns = []
        for candidate in pattern_service._pattern_candidates.values():
            if candidate.status == "pending":
                pending_patterns.append(candidate.to_dict())
        
        response_data = {
            "success": True,
            "patterns": pending_patterns,
            "count": len(pending_patterns)
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error getting pending patterns: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/patterns/approved', methods=['GET'])
async def get_approved_patterns():
    """Get approved patterns."""
    try:
        from ...agents.services.pattern_learning import PatternLearningService
        
        pattern_service = PatternLearningService()
        
        # Get approved pattern candidates
        approved_patterns = []
        for candidate in pattern_service._pattern_candidates.values():
            if candidate.status == "approved":
                approved_patterns.append(candidate.to_dict())
        
        response_data = {
            "success": True,
            "patterns": approved_patterns,
            "count": len(approved_patterns)
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error getting approved patterns: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/patterns/effectiveness', methods=['GET'])
async def get_pattern_effectiveness():
    """Get pattern effectiveness report."""
    try:
        from ...agents.services.pattern_learning import PatternLearningService
        
        pattern_service = PatternLearningService()
        
        # Get effectiveness report
        effectiveness_report = pattern_service.get_pattern_effectiveness_report()
        
        return jsonify({
            "success": True,
            **effectiveness_report
        })
        
    except Exception as e:
        logger.error(f"Error getting pattern effectiveness: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/patterns/track-usage', methods=['POST'])
async def track_pattern_usage():
    """Track pattern usage for effectiveness evaluation."""
    try:
        from ...agents.services.pattern_learning import PatternLearningService
        
        request_data = request.get_json()
        pattern_id = request_data.get("pattern_id")
        matched = request_data.get("matched", False)
        correct = request_data.get("correct")  # Optional: True/False/None
        
        if not pattern_id:
            return jsonify({
                "success": False,
                "error": "pattern_id is required"
            }), 400
        
        pattern_service = PatternLearningService()
        
        # Track usage
        await pattern_service.track_pattern_usage(pattern_id, matched, correct)
        
        return jsonify({
            "success": True,
            "message": "Pattern usage tracked successfully"
        })
        
    except Exception as e:
        logger.error(f"Error tracking pattern usage: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/triage/auto-fix-suggest', methods=['POST'])
@jwt_required
@async_route
async def suggest_auto_fix():
    """Suggest automatic test fixes based on analysis results."""
    try:
        from ...agents.services.auto_test_fix import AutoTestFixService
        from ...agents.services.glean_bug_detection import search_existing_bugs
        from ...agents.integration.mcp_bridge import MCPBridgeAgent
        
        request_data = request.get_json()
        test_result = request_data.get("test_result")
        jita_analysis = request_data.get("jita_analysis")
        
        if not test_result:
            return jsonify({
                "success": False,
                "error": "test_result is required"
            }), 400
        
        # Initialize services
        auto_fix_service = AutoTestFixService()
        mcp_bridge = MCPBridgeAgent()
        
        # Get Glean bug detection results
        glean_results = await search_existing_bugs(
            test_result.get("error_message", ""),
            test_result,
            mcp_bridge
        )
        
        # Generate fix suggestion
        fix_suggestion = await auto_fix_service.analyze_test_fix(
            test_result, 
            glean_results,
            jita_analysis
        )
        
        if fix_suggestion:
            return jsonify({
                "success": True,
                "fix_suggestion": fix_suggestion.to_dict(),
                "existing_bugs": glean_results.to_dict() if glean_results else None,
                "message": "Auto fix suggestion generated successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": "No auto fix suggestion could be generated",
                "existing_bugs": glean_results.to_dict() if glean_results else None
            })
        
    except Exception as e:
        logger.error(f"Error suggesting auto fix: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/triage/approve-fix', methods=['POST']) 
@jwt_required
@async_route
async def approve_test_fix():
    """Approve test fix and create change request."""
    try:
        from ...agents.services.auto_test_fix import AutoTestFixService, TestFixSuggestion
        
        request_data = request.get_json()
        fix_suggestion_data = request_data.get("fix_suggestion")
        user_approval = request_data.get("user_approval", {})
        
        if not fix_suggestion_data:
            return jsonify({
                "success": False,
                "error": "fix_suggestion is required"
            }), 400
        
        # Reconstruct fix suggestion object
        fix_suggestion = TestFixSuggestion(**fix_suggestion_data)
        
        # Add user info to approval data
        user_approval.update({
            "user_id": getattr(g, 'user', {}).get('username', 'system'),
            "approved_at": time.time()
        })
        
        # Initialize service and create CR
        auto_fix_service = AutoTestFixService()
        change_request = await auto_fix_service.create_fix_cr(fix_suggestion, user_approval)
        
        return jsonify({
            "success": True,
            "change_request": change_request.to_dict(),
            "message": f"Change request {change_request.cr_number} created successfully"
        })
        
    except Exception as e:
        logger.error(f"Error approving test fix: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/bugs/search-existing', methods=['POST'])
@jwt_required
@async_route
async def search_existing_bugs():
    """Search for existing bugs using enhanced Glean integration."""
    try:
        from ...agents.services.glean_bug_detection import GleanBugDetector
        from ...agents.integration.mcp_bridge import MCPBridgeAgent
        
        request_data = request.get_json()
        error_signature = request_data.get("error_signature")
        test_context = request_data.get("test_context", {})
        
        if not error_signature:
            return jsonify({
                "success": False,
                "error": "error_signature is required"
            }), 400
        
        # Initialize services
        mcp_bridge = MCPBridgeAgent()
        bug_detector = GleanBugDetector(mcp_bridge)
        
        # Search for existing bugs
        bug_results = await bug_detector.search_existing_bugs(error_signature, test_context)
        
        return jsonify({
            "success": True,
            "existing_bugs": bug_results.to_dict(),
            "message": "Bug search completed successfully"
        })
        
    except Exception as e:
        logger.error(f"Error searching existing bugs: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/bugs/product-behavior', methods=['POST'])
@jwt_required
@async_route
async def analyze_product_behavior():
    """Analyze product behavior documentation for test context."""
    try:
        from ...agents.services.glean_bug_detection import get_product_behavior_docs
        from ...agents.integration.mcp_bridge import MCPBridgeAgent
        
        request_data = request.get_json()
        error_context = request_data.get("error_context")
        test_context = request_data.get("test_context", {})
        
        if not error_context:
            return jsonify({
                "success": False,
                "error": "error_context is required"
            }), 400
        
        # Initialize services
        mcp_bridge = MCPBridgeAgent()
        
        # Get product behavior documentation
        behavior_docs = await get_product_behavior_docs(error_context, test_context, mcp_bridge)
        
        return jsonify({
            "success": True,
            "behavior_docs": [doc.to_dict() for doc in behavior_docs],
            "count": len(behavior_docs),
            "message": "Product behavior analysis completed successfully"
        })
        
    except Exception as e:
        logger.error(f"Error analyzing product behavior: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/fix/apply', methods=['POST'])
@jwt_required
@async_route
async def apply_test_fix():
    """Apply approved test fix and track results."""
    try:
        from ...agents.services.auto_test_fix import AutoTestFixService, FixChangeRequest
        
        request_data = request.get_json()
        cr_data = request_data.get("change_request")
        
        if not cr_data:
            return jsonify({
                "success": False,
                "error": "change_request is required"
            }), 400
        
        # Reconstruct change request object
        change_request = FixChangeRequest(**cr_data)
        
        # Initialize service and apply fix
        auto_fix_service = AutoTestFixService()
        application_result = await auto_fix_service.apply_test_fix(change_request)
        
        return jsonify({
            "success": True,
            "application_result": application_result,
            "change_request": change_request.to_dict(),
            "message": "Test fix application completed"
        })
        
    except Exception as e:
        logger.error(f"Error applying test fix: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/fix/test-after-fix', methods=['POST'])
@jwt_required
@async_route
async def test_after_fix():
    """Run test after fix application to verify success."""
    try:
        from ...agents.services.auto_test_fix import AutoTestFixService, FixChangeRequest
        
        request_data = request.get_json()
        cr_data = request_data.get("change_request")
        original_test_result = request_data.get("original_test_result")
        
        if not cr_data or not original_test_result:
            return jsonify({
                "success": False,
                "error": "change_request and original_test_result are required"
            }), 400
        
        # Reconstruct change request object
        change_request = FixChangeRequest(**cr_data)
        
        # Initialize service and run test
        auto_fix_service = AutoTestFixService()
        test_results = await auto_fix_service.run_test_after_fix(change_request, original_test_result)
        
        return jsonify({
            "success": True,
            "test_results": test_results,
            "change_request": change_request.to_dict(),
            "message": "Post-fix test execution completed"
        })
        
    except Exception as e:
        logger.error(f"Error running test after fix: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/jarvis/node/disable', methods=['POST'])
@jwt_required
async def jarvis_disable_node():
    """Disable a node in JARVIS due to RDM failure."""
    try:
        from ...agents.services.jarvis_service import JarvisNodeService
        
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Request data is required"}), 400
        
        node_name = data.get('node_name')
        rdm_link = data.get('rdm_link')
        reason = data.get('reason', 'Auto-disabled due to RDM failure')
        
        if not node_name:
            return jsonify({
                "success": False,
                "error": "node_name is required"
            }), 400
        
        # Initialize JARVIS service and disable node
        jarvis_service = JarvisNodeService()
        result = await jarvis_service.disable_node(
            node_name=node_name,
            rdm_link=rdm_link,
            reason=reason
        )
        
        return jsonify({
            "success": result.get("success", False),
            "result": result,
            "message": f"Node disable operation {'completed' if result.get('success') else 'failed'}"
        })
        
    except Exception as e:
        logger.error(f"Error disabling node in JARVIS: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/jarvis/node/status/<node_name>', methods=['GET'])
@jwt_required
async def jarvis_node_status(node_name: str):
    """Check node status in JARVIS."""
    try:
        from ...agents.services.jarvis_service import JarvisNodeService
        
        # Initialize JARVIS service and check status
        jarvis_service = JarvisNodeService()
        status = await jarvis_service.check_node_status(node_name)
        
        if status:
            return jsonify({
                "success": True,
                "node_status": status.to_dict(),
                "message": f"Node status retrieved for {node_name}"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Node {node_name} not found in JARVIS"
            }), 404
        
    except Exception as e:
        logger.error(f"Error checking node status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/jarvis/test/retrigger', methods=['POST'])
@jwt_required
async def jarvis_auto_retrigger():
    """Auto-retrigger a test case after node fixes."""
    try:
        from ...agents.services.jarvis_service import JarvisNodeService
        
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Request data is required"}), 400
        
        original_test_result = data.get('original_test_result')
        reason = data.get('reason', 'Auto-retrigger after node fix')
        
        if not original_test_result:
            return jsonify({
                "success": False,
                "error": "original_test_result is required"
            }), 400
        
        # Initialize JARVIS service and retrigger test
        jarvis_service = JarvisNodeService()
        result = await jarvis_service.auto_retrigger_testcase(
            original_test_result=original_test_result,
            retrigger_reason=reason
        )
        
        return jsonify({
            "success": result.success,
            "retrigger_result": result.to_dict(),
            "message": result.message
        })
        
    except Exception as e:
        logger.error(f"Error in auto-retrigger: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@agents_bp.route('/triage/approve-rdm-fix', methods=['POST'])
@jwt_required
async def approve_rdm_fix():
    """Process RDM fix approval and auto-disable problematic nodes."""
    try:
        from ...agents.analysis.intelligent_triage_agent import IntelligentTriageAgent
        
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Request data is required"}), 400
        
        test_result = data.get('test_result')
        rdm_analysis = data.get('rdm_analysis')
        user_approved = data.get('approved', True)
        
        if not test_result or not rdm_analysis:
            return jsonify({
                "success": False,
                "error": "test_result and rdm_analysis are required"
            }), 400
        
        # Initialize intelligent triage agent and process RDM fix
        agent = IntelligentTriageAgent()
        result = await agent.process_rdm_fix_approval(
            test_result=test_result,
            rdm_analysis=rdm_analysis,
            user_approved=user_approved
        )
        
        return jsonify({
            "success": result.get("success", False),
            "rdm_fix_result": result,
            "message": result.get("message", "RDM fix processing completed")
        })
        
    except Exception as e:
        logger.error(f"Error processing RDM fix approval: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# Error handlers
@agents_bp.errorhandler(400)
def bad_request(error):
    return jsonify({
        "success": False,
        "error": "Bad request",
        "message": str(error)
    }), 400


@agents_bp.errorhandler(401)
def unauthorized(error):
    return jsonify({
        "success": False,
        "error": "Unauthorized",
        "message": "Authentication required"
    }), 401


@agents_bp.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Not found",
        "message": str(error)
    }), 404


@agents_bp.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error",
        "message": str(error)
    }), 500