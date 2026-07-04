import React, { useState, useRef, useEffect } from 'react';
import api, { syncCursorAiSkills } from '../api';
import { API_BASE_URL } from '../config';
import AiMarkdown from '../components/AiMarkdown';
import './CursorAI.css';

const API_BASE = `${API_BASE_URL}/mcp/regression/cursor-ai`;

const MODES = [
  { id: 'agent', label: 'Agent', description: 'Full implementation mode with tool access' },
  { id: 'plan', label: 'Plan', description: 'Read-only collaborative planning' },
  { id: 'debug', label: 'Debug', description: 'Systematic troubleshooting' },
  { id: 'ask', label: 'Ask', description: 'Explore code and answer questions' },
];

const MODELS = [
  { id: 'claude-sonnet-4.6-high', label: 'Claude Sonnet 4.6 (High)' },
  { id: 'claude-sonnet-4.6', label: 'Claude Sonnet 4.6' },
];

const MCP_SERVERS = [
  { id: 'regx-data', name: 'RegX Data', description: 'Regression data (failed testcases, details, push analysis)' },
  { id: 'atlassian', name: 'Atlassian', description: 'Jira & Confluence integration' },
  { id: 'gw-sourcegraph', name: 'Sourcegraph', description: 'Code search across all repos' },
  { id: 'gw-jita', name: 'JITA', description: 'JITA log bundle access' },
  { id: 'gw-diamond', name: 'Diamond', description: 'Remote SSH access to Diamond storage' },
  { id: 'gw-glean', name: 'Glean', description: 'Internal knowledge search' },
  { id: 'gw-supportgpt', name: 'SupportGPT', description: 'RAG-based support knowledge base' },
  { id: 'gw-nurag', name: 'NuRAG', description: 'Advanced RAG with Knowledge Graph' },
  { id: 'gw-slack', name: 'Slack', description: 'Slack workspace integration' },
  { id: 'gw-panacea', name: 'Panacea', description: 'Automated RCA and Agentic Triage' },
  { id: 'gw-live-debug', name: 'Live Debug', description: 'Live debugging sessions' },
  { id: 'auto-handoff', name: 'Auto Handoff', description: 'Automated CR creation and handoff' },
];

const SYNCABLE_SKILLS = [
  { id: 'triage-rdm-deployment-failure', label: 'triage-rdm-deployment-failure' },
  { id: 'triage-cdp-test-failure', label: 'triage-cdp-test-failure' },
  { id: 'glean-search', label: 'glean-search' },
  { id: 'gerrit-comment-resolver', label: 'gerrit-comment-resolver' },
];

export default function CursorAI() {
  const [mode, setMode] = useState('agent');
  const [model, setModel] = useState('claude-sonnet-4.6-high');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showMcpPanel, setShowMcpPanel] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [syncingSkills, setSyncingSkills] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [enabledServers, setEnabledServers] = useState(
    MCP_SERVERS.reduce((acc, s) => ({ ...acc, [s.id]: true }), {})
  );
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleOpenSettings = () => {
      setShowSettings(true);
    };
    window.addEventListener('openCursorAiSettings', handleOpenSettings);
    return () => window.removeEventListener('openCursorAiSettings', handleOpenSettings);
  }, []);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    const userMsg = { role: 'user', content: trimmed, timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const activeServers = Object.entries(enabledServers)
        .filter(([, v]) => v)
        .map(([k]) => k);

      const response = await api.post(`${API_BASE}/chat`, {
        messages: [...messages, userMsg].map(m => ({ role: m.role, content: m.content })),
        mode,
        model,
        mcp_servers: activeServers,
      });

      if (response.data.success) {
        const assistantMsg = {
          role: 'assistant',
          content: response.data.reply,
          timestamp: Date.now(),
          mode: response.data.mode,
          model: response.data.model,
          tools_used: response.data.tools_used || [],
        };
        setMessages(prev => [...prev, assistantMsg]);
      } else {
        setMessages(prev => [...prev, {
          role: 'error',
          content: response.data.error || 'Unknown error occurred',
          timestamp: Date.now(),
        }]);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'error',
        content: err.response?.data?.error || err.message || 'Request failed',
        timestamp: Date.now(),
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const clearChat = () => {
    setMessages([]);
  };

  const handleSyncSkills = async () => {
    if (syncingSkills) return;
    setSyncingSkills(true);
    setSyncResult(null);
    try {
      const response = await syncCursorAiSkills(SYNCABLE_SKILLS.map(skill => skill.id));
      if (response.data.success) {
        setSyncResult({
          status: 'success',
          message: `Synced ${response.data.summary?.success_count || 0} skill(s).`,
          details: response.data.results || [],
        });
      } else {
        setSyncResult({
          status: 'error',
          message: response.data.error || 'Skill sync failed.',
          details: [],
        });
      }
    } catch (err) {
      setSyncResult({
        status: 'error',
        message: err.response?.data?.error || err.message || 'Skill sync failed.',
        details: [],
      });
    } finally {
      setSyncingSkills(false);
    }
  };

  const toggleServer = (serverId) => {
    setEnabledServers(prev => ({ ...prev, [serverId]: !prev[serverId] }));
  };

  const activeServerCount = Object.values(enabledServers).filter(Boolean).length;

  return (
    <div className="cursor-ai-container">
      {/* Header Controls */}
      <div className="cursor-ai-header">
        <div className="cursor-ai-title-row">
          <h1 className="cursor-ai-title">Cursor AI</h1>
          <div className="cursor-ai-controls">
            <div className="control-group">
              <label className="control-label">Mode</label>
              <div className="mode-selector">
                {MODES.map(m => (
                  <button
                    key={m.id}
                    className={`mode-btn ${mode === m.id ? 'active' : ''}`}
                    onClick={() => setMode(m.id)}
                    title={m.description}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="control-group">
              <label className="control-label">Model</label>
              <select
                className="model-select"
                value={model}
                onChange={e => setModel(e.target.value)}
              >
                {MODELS.map(m => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            </div>
            <button
              className={`mcp-toggle-btn ${showMcpPanel ? 'active' : ''}`}
              onClick={() => setShowMcpPanel(!showMcpPanel)}
              title="Toggle MCP Servers panel"
            >
              MCP ({activeServerCount}/{MCP_SERVERS.length})
            </button>
            <button className="clear-chat-btn" onClick={clearChat} title="Clear chat">
              Clear
            </button>
            <button
              className="settings-btn"
              onClick={() => setShowSettings(true)}
              title="Open user settings"
            >
              Settings
            </button>
          </div>
        </div>
      </div>

      <div className="cursor-ai-body">
        {/* MCP Servers Panel */}
        {showMcpPanel && (
          <div className="mcp-panel">
            <div className="mcp-panel-header">
              <h3>MCP Servers</h3>
              <span className="mcp-panel-count">{activeServerCount} active</span>
            </div>
            <div className="mcp-server-list">
              {MCP_SERVERS.map(server => (
                <label key={server.id} className="mcp-server-item">
                  <input
                    type="checkbox"
                    checked={enabledServers[server.id]}
                    onChange={() => toggleServer(server.id)}
                  />
                  <div className="mcp-server-info">
                    <span className="mcp-server-name">{server.name}</span>
                    <span className="mcp-server-desc">{server.description}</span>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Chat Messages */}
        <div className="cursor-ai-messages">
          {messages.length === 0 && (
            <div className="chat-empty-state">
              <div className="empty-icon">AI</div>
              <h2>Cursor AI Assistant</h2>
              <p>Ask questions, debug issues, plan implementations, or get help with regression analysis.</p>
              <div className="empty-hints">
                <div className="hint-item" onClick={() => setInput('Analyze the latest regression failures and suggest root causes')}>
                  Analyze regression failures
                </div>
                <div className="hint-item" onClick={() => setInput('Search Sourcegraph for recent changes to CDP test infrastructure')}>
                  Search code changes
                </div>
                <div className="hint-item" onClick={() => setInput('Check JITA logs for task ID and identify the failure pattern')}>
                  Check JITA logs
                </div>
                <div className="hint-item" onClick={() => setInput('Create a triage summary for the current regression run')}>
                  Create triage summary
                </div>
              </div>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div key={idx} className={`chat-message ${msg.role}`}>
              <div className="message-avatar">
                {msg.role === 'user' ? 'U' : msg.role === 'error' ? '!' : 'AI'}
              </div>
              <div className="message-body">
                {msg.role === 'assistant' && msg.tools_used?.length > 0 && (
                  <div className="message-tools">
                    {msg.tools_used.map((tool, i) => (
                      <span key={i} className="tool-badge">{tool}</span>
                    ))}
                  </div>
                )}
                <div className="message-content">
                  {msg.role === 'assistant' ? (
                    <AiMarkdown content={msg.content} />
                  ) : (
                    <pre className="user-message-text">{msg.content}</pre>
                  )}
                </div>
                {msg.role === 'assistant' && (
                  <div className="message-meta">
                    <span className="meta-mode">{msg.mode}</span>
                    <span className="meta-model">{msg.model}</span>
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="chat-message assistant loading">
              <div className="message-avatar">AI</div>
              <div className="message-body">
                <div className="typing-indicator">
                  <span></span><span></span><span></span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area */}
      <div className="cursor-ai-input-area">
        <div className="input-wrapper">
          <textarea
            ref={inputRef}
            className="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Ask Cursor AI (${MODES.find(m => m.id === mode)?.label} mode)...`}
            rows={1}
            disabled={loading}
          />
          <button
            className="send-btn"
            onClick={handleSend}
            disabled={!input.trim() || loading}
            title="Send message (Enter)"
          >
            {loading ? '...' : 'Send'}
          </button>
        </div>
        <div className="input-footer">
          <span className="input-hint">Enter to send, Shift+Enter for new line</span>
          <span className="active-context">
            {activeServerCount} MCP servers active
          </span>
        </div>
      </div>

      {showSettings && (
        <div className="settings-modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="settings-modal-content" onClick={e => e.stopPropagation()}>
            <div className="settings-modal-header">
              <h3>User Settings</h3>
              <button
                type="button"
                className="settings-modal-close"
                onClick={() => setShowSettings(false)}
              >
                ×
              </button>
            </div>
            <div className="settings-modal-body">
              <section className="settings-section">
                <h4>Skill Sync</h4>
                <p>Sync predefined analysis skills from Sourcegraph into RegX local skills.</p>
                <div className="settings-skill-list">
                  {SYNCABLE_SKILLS.map(skill => (
                    <span key={skill.id} className="settings-skill-chip">
                      {skill.label}
                    </span>
                  ))}
                </div>
                <button
                  className="sync-skills-btn"
                  onClick={handleSyncSkills}
                  disabled={syncingSkills}
                >
                  {syncingSkills ? 'Syncing...' : 'Sync Skills'}
                </button>
                {syncResult && (
                  <div className={`sync-status ${syncResult.status}`}>
                    <div className="sync-status-message">{syncResult.message}</div>
                    {syncResult.details?.length > 0 && (
                      <ul className="sync-status-list">
                        {syncResult.details.map(detail => (
                          <li key={detail.skill_id || detail.target_file}>
                            {detail.skill_id}: {detail.success ? 'synced' : `failed (${detail.error || 'unknown error'})`}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </section>

              <section className="settings-section">
                <h4>Future Integrations</h4>
                <p>
                  This area is reserved for user-specific integration settings (for example, external tool tokens).
                </p>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
