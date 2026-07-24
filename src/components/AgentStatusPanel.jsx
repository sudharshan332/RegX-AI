/**
 * Agent Status Panel Component
 * 
 * Displays real-time status of the RegX-AI agent framework including:
 * - Agent health and performance metrics
 * - Cost tracking and budget status
 * - Pattern matching statistics
 * - MCP server status
 */

import React, { useState, useEffect, useCallback } from 'react';
import api from '../api';
import './AgentStatusPanel.css';

const AgentStatusPanel = ({ onClose, minimized = false }) => {
  const [agentStatus, setAgentStatus] = useState(null);
  const [costStatus, setCostStatus] = useState(null);
  const [patternStats, setPatternStats] = useState(null);
  const [mcpStatus, setMcpStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshInterval, setRefreshInterval] = useState(null);
  const [selectedTab, setSelectedTab] = useState('overview');

  const fetchAgentStatus = useCallback(async () => {
    try {
      const response = await api.get('/api/agents/status');
      if (response.data.success) {
        setAgentStatus(response.data);
        setError(null);
      } else {
        setError(response.data.error || 'Failed to fetch agent status');
      }
    } catch (err) {
      console.error('Failed to fetch agent status:', err);
      setError('Failed to connect to agent system');
    }
  }, []);

  const fetchCostStatus = useCallback(async () => {
    try {
      const response = await api.get('/api/agents/cost/status?entity_id=regx_team&days=7');
      if (response.data.success) {
        setCostStatus(response.data);
      }
    } catch (err) {
      console.error('Failed to fetch cost status:', err);
    }
  }, []);

  const fetchPatternStats = useCallback(async () => {
    try {
      const response = await api.get('/api/agents/patterns/stats');
      if (response.data.success) {
        setPatternStats(response.data.statistics);
      }
    } catch (err) {
      console.error('Failed to fetch pattern stats:', err);
    }
  }, []);

  const fetchMcpStatus = useCallback(async () => {
    try {
      const response = await api.get('/api/agents/mcp/status');
      if (response.data.success) {
        setMcpStatus(response.data.mcp_status);
      }
    } catch (err) {
      console.error('Failed to fetch MCP status:', err);
    }
  }, []);

  const fetchAllData = useCallback(async () => {
    setLoading(true);
    await Promise.all([
      fetchAgentStatus(),
      fetchCostStatus(),
      fetchPatternStats(),
      fetchMcpStatus()
    ]);
    setLoading(false);
  }, [fetchAgentStatus, fetchCostStatus, fetchPatternStats, fetchMcpStatus]);

  useEffect(() => {
    fetchAllData();

    // Set up auto-refresh every 30 seconds
    const interval = setInterval(fetchAllData, 30000);
    setRefreshInterval(interval);

    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [fetchAllData]);

  const handleRefresh = () => {
    fetchAllData();
  };

  const formatCredits = (credits) => {
    return credits?.toLocaleString() || '0';
  };

  const formatPercentage = (value) => {
    return `${(value * 100).toFixed(1)}%`;
  };

  const getHealthColor = (health) => {
    if (health >= 0.8) return '#4CAF50'; // Green
    if (health >= 0.6) return '#FF9800'; // Orange
    return '#f44336'; // Red
  };

  const renderOverviewTab = () => (
    <div className="agent-overview">
      <div className="metrics-grid">
        {/* System Health */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">System Health</span>
            <span 
              className="metric-value"
              style={{ color: agentStatus ? getHealthColor(agentStatus.system_health.agents_healthy) : '#666' }}
            >
              {agentStatus ? formatPercentage(agentStatus.system_health.agents_healthy) : 'N/A'}
            </span>
          </div>
          <div className="metric-details">
            <div className="detail-row">
              <span>Active Agents:</span>
              <span>{agentStatus?.registry.healthy_agents || 0}/{agentStatus?.registry.total_agents || 0}</span>
            </div>
            <div className="detail-row">
              <span>Handoff Success:</span>
              <span>{agentStatus ? formatPercentage(agentStatus.system_health.handoff_success_rate) : 'N/A'}</span>
            </div>
          </div>
        </div>

        {/* Cost Status */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">Credit Usage (7 days)</span>
            <span className="metric-value">{formatCredits(costStatus?.analytics.total_credits)}</span>
          </div>
          <div className="metric-details">
            <div className="detail-row">
              <span>Success Rate:</span>
              <span>{costStatus ? formatPercentage(costStatus.analytics.success_rate) : 'N/A'}</span>
            </div>
            <div className="detail-row">
              <span>Cost/Success:</span>
              <span>{costStatus?.analytics.cost_per_success?.toFixed(1) || 'N/A'} credits</span>
            </div>
          </div>
        </div>

        {/* Pattern Matching */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">Pattern Matching</span>
            <span className="metric-value">{formatPercentage(patternStats?.cache_hit_rate || 0)}</span>
          </div>
          <div className="metric-details">
            <div className="detail-row">
              <span>Total Patterns:</span>
              <span>{patternStats?.total_patterns || 0}</span>
            </div>
            <div className="detail-row">
              <span>Cache Size:</span>
              <span>{patternStats?.cache_stats.size || 0}</span>
            </div>
          </div>
        </div>

        {/* MCP Servers */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">MCP Servers</span>
            <span className="metric-value">
              {mcpStatus ? `${Object.keys(mcpStatus.servers).filter(s => mcpStatus.servers[s].config.enabled).length}/${mcpStatus.total_servers}` : 'N/A'}
            </span>
          </div>
          <div className="metric-details">
            <div className="detail-row">
              <span>Active Sessions:</span>
              <span>{mcpStatus?.active_sessions || 0}</span>
            </div>
            <div className="detail-row">
              <span>Cache Hit Rate:</span>
              <span>{mcpStatus ? formatPercentage(mcpStatus.cache_stats.hit_rate) : 'N/A'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Recommendations */}
      {costStatus?.recommendations && costStatus.recommendations.length > 0 && (
        <div className="recommendations-section">
          <h4>Optimization Recommendations</h4>
          {costStatus.recommendations.map((rec, index) => (
            <div key={index} className={`recommendation ${rec.priority}`}>
              <div className="rec-header">
                <span className="rec-title">{rec.title}</span>
                <span className={`rec-priority ${rec.priority}`}>{rec.priority}</span>
              </div>
              <p className="rec-description">{rec.description}</p>
              {rec.actions && (
                <ul className="rec-actions">
                  {rec.actions.map((action, i) => (
                    <li key={i}>{action}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderAgentsTab = () => (
    <div className="agents-list">
      {agentStatus?.registry.agents?.map(agent => (
        <div key={agent.name} className="agent-card">
          <div className="agent-header">
            <span className="agent-name">{agent.name}</span>
            <span className={`agent-status ${agent.healthy ? 'healthy' : 'unhealthy'}`}>
              {agent.healthy ? 'Healthy' : 'Unhealthy'}
            </span>
          </div>
          <div className="agent-details">
            <div className="detail-row">
              <span>Type:</span>
              <span>{agent.type}</span>
            </div>
            <div className="detail-row">
              <span>Analyses:</span>
              <span>{agent.metrics.total_analyses}</span>
            </div>
            <div className="detail-row">
              <span>Success Rate:</span>
              <span>{formatPercentage(agent.metrics.success_rate)}</span>
            </div>
            <div className="detail-row">
              <span>Credits Used:</span>
              <span>{formatCredits(agent.metrics.credits_used)}</span>
            </div>
            <div className="detail-row">
              <span>Avg Time:</span>
              <span>{agent.metrics.avg_execution_time_ms?.toFixed(0) || '0'}ms</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );

  const renderCostTab = () => (
    <div className="cost-details">
      {costStatus && (
        <>
          {/* Budget Status */}
          {costStatus.budget_status.has_budget && (
            <div className="budget-section">
              <h4>Budget Status - {costStatus.budget_status.entity_id}</h4>
              <div className="budget-grid">
                <div className="budget-period">
                  <span className="period-label">Daily</span>
                  <div className="budget-bar">
                    <div 
                      className="budget-used" 
                      style={{ 
                        width: `${Math.min(100, costStatus.budget_status.utilization.daily * 100)}%`,
                        backgroundColor: costStatus.budget_status.utilization.daily > 0.8 ? '#f44336' : '#4CAF50'
                      }}
                    ></div>
                  </div>
                  <span className="budget-text">
                    {costStatus.budget_status.usage.daily}/{costStatus.budget_status.budget.daily_limit}
                  </span>
                </div>
                <div className="budget-period">
                  <span className="period-label">Weekly</span>
                  <div className="budget-bar">
                    <div 
                      className="budget-used" 
                      style={{ 
                        width: `${Math.min(100, costStatus.budget_status.utilization.weekly * 100)}%`,
                        backgroundColor: costStatus.budget_status.utilization.weekly > 0.8 ? '#f44336' : '#4CAF50'
                      }}
                    ></div>
                  </div>
                  <span className="budget-text">
                    {costStatus.budget_status.usage.weekly}/{costStatus.budget_status.budget.weekly_limit}
                  </span>
                </div>
                <div className="budget-period">
                  <span className="period-label">Monthly</span>
                  <div className="budget-bar">
                    <div 
                      className="budget-used" 
                      style={{ 
                        width: `${Math.min(100, costStatus.budget_status.utilization.monthly * 100)}%`,
                        backgroundColor: costStatus.budget_status.utilization.monthly > 0.8 ? '#f44336' : '#4CAF50'
                      }}
                    ></div>
                  </div>
                  <span className="budget-text">
                    {costStatus.budget_status.usage.monthly}/{costStatus.budget_status.budget.monthly_limit}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Analysis Breakdown */}
          <div className="analysis-breakdown">
            <h4>Analysis Type Breakdown</h4>
            <div className="breakdown-grid">
              {Object.entries(costStatus.analytics.analysis_breakdown).map(([type, credits]) => (
                <div key={type} className="breakdown-item">
                  <span className="breakdown-type">{type.replace(/_/g, ' ')}</span>
                  <span className="breakdown-credits">{formatCredits(credits)}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );

  if (minimized) {
    return (
      <div className="agent-status-minimized" onClick={() => setSelectedTab('overview')}>
        <div className="minimized-content">
          <span className="minimized-title">Agents</span>
          <div className="minimized-indicators">
            <div 
              className="health-indicator"
              style={{ backgroundColor: agentStatus ? getHealthColor(agentStatus.system_health.agents_healthy) : '#666' }}
            ></div>
            <span className="minimized-text">
              {agentStatus ? `${agentStatus.registry.healthy_agents}/${agentStatus.registry.total_agents}` : 'N/A'}
            </span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="agent-status-panel">
      <div className="panel-header">
        <h3>Agent Framework Status</h3>
        <div className="panel-controls">
          <button onClick={handleRefresh} className="refresh-btn" disabled={loading}>
            {loading ? '⟳' : '↻'} Refresh
          </button>
          {onClose && (
            <button onClick={onClose} className="close-btn">×</button>
          )}
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️ {error}</span>
        </div>
      )}

      <div className="panel-tabs">
        <button 
          className={`tab-btn ${selectedTab === 'overview' ? 'active' : ''}`}
          onClick={() => setSelectedTab('overview')}
        >
          Overview
        </button>
        <button 
          className={`tab-btn ${selectedTab === 'agents' ? 'active' : ''}`}
          onClick={() => setSelectedTab('agents')}
        >
          Agents ({agentStatus?.registry.total_agents || 0})
        </button>
        <button 
          className={`tab-btn ${selectedTab === 'cost' ? 'active' : ''}`}
          onClick={() => setSelectedTab('cost')}
        >
          Cost Tracking
        </button>
      </div>

      <div className="panel-content">
        {loading && (
          <div className="loading-overlay">
            <div className="loading-spinner">Loading...</div>
          </div>
        )}

        {selectedTab === 'overview' && renderOverviewTab()}
        {selectedTab === 'agents' && renderAgentsTab()}
        {selectedTab === 'cost' && renderCostTab()}
      </div>
    </div>
  );
};

export default AgentStatusPanel;