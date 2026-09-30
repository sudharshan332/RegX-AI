import React, { useEffect, useState } from 'react';
import api from '../api';
import './KeyManagementPanel.css';

const EMPTY_KEYS = {
  cursor_api_key: '',
  nai_api_key: '',
  nai_embed_api_key: '',
  ai_provider: 'cursor',
  atlassian_jira_token: '',
  atlassian_confluence_token: '',
  gerrit_http_password: '',
  sourcegraph_token: '',
  flux_username: '',
  flux_password: '',
};

export default function KeyManagementPanel({ onClose }) {
  const [keys, setKeys] = useState({ ...EMPTY_KEYS });
  const [originalKeys, setOriginalKeys] = useState({});
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResults, setValidationResults] = useState(null);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [showKeys, setShowKeys] = useState({
    cursor_api_key: false,
    nai_api_key: false,
    nai_embed_api_key: false,
    atlassian_jira_token: false,
    atlassian_confluence_token: false,
    gerrit_http_password: false,
    sourcegraph_token: false,
    flux_username: false,
    flux_password: false,
  });

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    try {
      const response = await api.get('/mcp/regression/user-keys');
      const loadedKeys = { ...EMPTY_KEYS, ...(response.data || {}) };
      if (!loadedKeys.ai_provider) loadedKeys.ai_provider = 'cursor';
      setKeys(loadedKeys);
      setOriginalKeys(loadedKeys);
      try {
        localStorage.setItem('regx_ai_provider', loadedKeys.ai_provider);
        window.dispatchEvent(
          new CustomEvent('regxAiProviderChanged', { detail: loadedKeys.ai_provider })
        );
      } catch (_) {
        /* ignore */
      }
    } catch (err) {
      console.error('Failed to load keys:', err);
      setError('Failed to load existing keys');
    }
  };

  const handleSave = async () => {
    setError(null);
    setSuccess(null);
    setSaving(true);
    try {
      const keysToSave = {};
      Object.keys(keys).forEach((key) => {
        if (key === 'ai_provider') {
          if ((keys.ai_provider || 'cursor') !== (originalKeys.ai_provider || 'cursor')) {
            keysToSave.ai_provider = keys.ai_provider || 'cursor';
          }
          return;
        }
        const value = (keys[key] || '').trim();
        if (value && !value.includes('****')) {
          keysToSave[key] = value;
        }
      });
      if (Object.keys(keysToSave).length === 0) {
        setError('No new keys to save. Enter a new value or change AI provider, then click Save.');
        return;
      }
      await api.put('/mcp/regression/user-keys', keysToSave);
      setSuccess('Settings saved successfully!');
      await loadKeys();
      setTimeout(() => {
        if (onClose) onClose();
      }, 2000);
    } catch (err) {
      console.error('Failed to save keys:', err);
      setError(err.response?.data?.error || 'Failed to save keys');
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    setError(null);
    setValidationResults(null);
    setValidating(true);
    try {
      // Send only fresh (non-masked) values; backend loads saved tokens itself.
      const keysToValidate = { ai_provider: keys.ai_provider || 'cursor' };
      Object.keys(keys).forEach((key) => {
        if (key === 'ai_provider') return;
        const value = keys[key];
        if (value && !value.includes('****')) {
          keysToValidate[key] = value;
        }
      });
      const response = await api.post('/mcp/regression/user-keys/validate', keysToValidate);
      setValidationResults(response.data);
    } catch (err) {
      console.error('Validation failed:', err);
      setError(
        (err.response?.data?.error || 'Test Keys could not complete') +
          '. You can still Save the Jira token — ticket data will use it.'
      );
    } finally {
      setValidating(false);
    }
  };

  const handleChange = (key, value) => {
    setKeys((prev) => ({ ...prev, [key]: value }));
    setError(null);
    setSuccess(null);
    setValidationResults(null);
  };

  const toggleShowKey = (key) => {
    setShowKeys((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const hasChanges = () => {
    if ((keys.ai_provider || 'cursor') !== (originalKeys.ai_provider || 'cursor')) {
      return true;
    }
    return Object.keys(keys).some((key) => {
      if (key === 'ai_provider') return false;
      const value = (keys[key] || '').trim();
      const original = (originalKeys[key] || '').trim();
      return value && value !== original && !value.includes('****');
    });
  };

  return (
    <div className="key-management-panel">
      <h2>API Key Configuration</h2>
      <p className="panel-description">
        Choose the AI backend for the complete tool (Deep AI, chat, RAG), then paste
        the matching access key and click <strong>Save</strong>.
        Dashboard Jira status / product-vs-test lookups use the Atlassian token.
      </p>

      {error && <div className="message-banner error-banner">{error}</div>}
      {success && <div className="message-banner success-banner">{success}</div>}

      <div className="key-section">
        <label>AI Provider</label>
        <div className="ai-provider-toggle" role="group" aria-label="AI Provider">
          <button
            type="button"
            className={`ai-provider-btn ${(keys.ai_provider || 'cursor') === 'cursor' ? 'active' : ''}`}
            onClick={() => handleChange('ai_provider', 'cursor')}
            disabled={saving || validating}
          >
            Cursor SDK
          </button>
          <button
            type="button"
            className={`ai-provider-btn ${(keys.ai_provider || 'cursor') === 'nai' ? 'active' : ''}`}
            onClick={() => handleChange('ai_provider', 'nai')}
            disabled={saving || validating}
          >
            NAI
          </button>
        </div>
        <p className="help-text">
          Applies across Cursor AI chat, Deep AI analysis, First Level synthesis, and RAG.
          NAI uses reasoning model <code>nemotron-3-fp4-04</code> and embedding{' '}
          <code>eng-embed-01</code>.
        </p>
      </div>

      <div className="key-section">
        <label htmlFor="cursor-api-key">Cursor API Key</label>
        <div className="input-with-toggle">
          <input
            id="cursor-api-key"
            type={showKeys.cursor_api_key ? 'text' : 'password'}
            value={keys.cursor_api_key}
            onChange={(e) => handleChange('cursor_api_key', e.target.value)}
            placeholder="crsr_..."
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('cursor_api_key')}
            title={showKeys.cursor_api_key ? 'Hide key' : 'Show key'}
          >
            {showKeys.cursor_api_key ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">
          Required when AI Provider is Cursor SDK. Get yours from{' '}
          <a href="https://cursor.com/settings" target="_blank" rel="noopener noreferrer">
            cursor.com/settings
          </a>
        </p>
      </div>

      <div className="key-section">
        <label htmlFor="nai-api-key">NAI Reasoning Access Key</label>
        <div className="input-with-toggle">
          <input
            id="nai-api-key"
            type={showKeys.nai_api_key ? 'text' : 'password'}
            value={keys.nai_api_key}
            onChange={(e) => handleChange('nai_api_key', e.target.value)}
            placeholder="UUID / token for chat/completions (no Bearer prefix)"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('nai_api_key')}
            title={showKeys.nai_api_key ? 'Hide key' : 'Show key'}
          >
            {showKeys.nai_api_key ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">
          Required for NAI AI ops. Must be authorized for Reasoning/chat on{' '}
          <code>nai-dre.corp.../enterpriseai/gateway/v1/chat/completions</code>{' '}
          (model <code>nemotron-3-fp4-04</code>). Paste only the token — not{' '}
          <code>Bearer ...</code> and not an embeddings Key Name.
        </p>
      </div>

      <div className="key-section">
        <label htmlFor="nai-embed-api-key">NAI Embedding Access Key</label>
        <div className="input-with-toggle">
          <input
            id="nai-embed-api-key"
            type={showKeys.nai_embed_api_key ? 'text' : 'password'}
            value={keys.nai_embed_api_key}
            onChange={(e) => handleChange('nai_embed_api_key', e.target.value)}
            placeholder="Optional if Reasoning key also covers embeddings"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('nai_embed_api_key')}
            title={showKeys.nai_embed_api_key ? 'Hide key' : 'Show key'}
          >
            {showKeys.nai_embed_api_key ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">
          Used for RAG re-rank on{' '}
          <code>nai-dre.beta.../enterpriseai/v1/embeddings</code> (model{' '}
          <code>eng-embed-01</code>). If omitted, the Reasoning key is tried.
          Embeddings-only keys will fail Reasoning Test Keys with
          &quot;multi-endpoint types&quot; — that is expected; put them here instead.
        </p>
      </div>

      <div className="key-section">
        <label htmlFor="jira-token">Atlassian Jira Personal Token</label>
        <div className="input-with-toggle">
          <input
            id="jira-token"
            type={showKeys.atlassian_jira_token ? 'text' : 'password'}
            value={keys.atlassian_jira_token}
            onChange={(e) => handleChange('atlassian_jira_token', e.target.value)}
            placeholder="Optional"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('atlassian_jira_token')}
            title={showKeys.atlassian_jira_token ? 'Hide token' : 'Show token'}
          >
            {showKeys.atlassian_jira_token ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">
          Used for Jira ticket status, product/test bug type, and related dashboard lookups.
        </p>
      </div>

      <div className="key-section">
        <label htmlFor="confluence-token">Atlassian Confluence Personal Token</label>
        <div className="input-with-toggle">
          <input
            id="confluence-token"
            type={showKeys.atlassian_confluence_token ? 'text' : 'password'}
            value={keys.atlassian_confluence_token}
            onChange={(e) => handleChange('atlassian_confluence_token', e.target.value)}
            placeholder="Optional"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('atlassian_confluence_token')}
            title={showKeys.atlassian_confluence_token ? 'Hide token' : 'Show token'}
          >
            {showKeys.atlassian_confluence_token ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">Optional: For Confluence MCP server access (search, read pages)</p>
      </div>

      <div className="key-section">
        <label htmlFor="gerrit-http-password">Gerrit HTTP Password</label>
        <div className="input-with-toggle">
          <input
            id="gerrit-http-password"
            type={showKeys.gerrit_http_password ? 'text' : 'password'}
            value={keys.gerrit_http_password}
            onChange={(e) => handleChange('gerrit_http_password', e.target.value)}
            placeholder="Required for auto Create CR in Handover"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('gerrit_http_password')}
            title={showKeys.gerrit_http_password ? 'Hide password' : 'Show password'}
          >
            {showKeys.gerrit_http_password ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">
          Required for automatic Gerrit CR creation in Handover. Generate it in Gerrit → Settings → HTTP Credentials.
          Username is your Gerrit/LDAP id shown on that page (e.g. firstname.lastname), not your email.
        </p>
      </div>

      <div className="key-section">
        <label htmlFor="flux-username">Flux Username</label>
        <div className="input-with-toggle">
          <input
            id="flux-username"
            type={showKeys.flux_username ? 'text' : 'password'}
            value={keys.flux_username}
            onChange={(e) => handleChange('flux_username', e.target.value)}
            placeholder="Required for Flux Quick Fix"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('flux_username')}
            title={showKeys.flux_username ? 'Hide username' : 'Show username'}
          >
            {showKeys.flux_username ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">Your Flux login username (may differ from RegX username).</p>
      </div>

      <div className="key-section">
        <label htmlFor="flux-password">Flux Password</label>
        <div className="input-with-toggle">
          <input
            id="flux-password"
            type={showKeys.flux_password ? 'text' : 'password'}
            value={keys.flux_password}
            onChange={(e) => handleChange('flux_password', e.target.value)}
            placeholder="Required for Flux Quick Fix"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('flux_password')}
            title={showKeys.flux_password ? 'Hide password' : 'Show password'}
          >
            {showKeys.flux_password ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">Your Flux login password.</p>
      </div>

      <div className="key-section">
        <label htmlFor="sourcegraph-token">Sourcegraph Token</label>
        <div className="input-with-toggle">
          <input
            id="sourcegraph-token"
            type={showKeys.sourcegraph_token ? 'text' : 'password'}
            value={keys.sourcegraph_token}
            onChange={(e) => handleChange('sourcegraph_token', e.target.value)}
            placeholder="Required for Suggest LST"
            disabled={saving || validating}
          />
          <button
            type="button"
            className="toggle-visibility-btn"
            onClick={() => toggleShowKey('sourcegraph_token')}
            title={showKeys.sourcegraph_token ? 'Hide token' : 'Show token'}
          >
            {showKeys.sourcegraph_token ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
        <p className="help-text">
          Used by Handover Suggest LST to query Sourcegraph per user.
        </p>
      </div>

      {validationResults && (
        <div className="validation-results">
          <h3>Validation Results</h3>
          {Object.entries(validationResults.results || {})
            .filter(([key]) => key !== 'nai_combined')
            .map(([key, result]) => {
              const labelMap = {
                nai_api_key: 'NAI Reasoning Access Key',
                nai_embed_api_key: 'NAI Embedding Access Key',
                cursor_api_key: 'Cursor API Key',
                atlassian_jira_token: 'Atlassian Jira Personal Token',
                atlassian_confluence_token: 'Atlassian Confluence Personal Token',
                gerrit_http_password: 'Gerrit HTTP Password',
                sourcegraph_token: 'Sourcegraph Token',
                flux_username: 'Flux Username',
                flux_password: 'Flux Password',
                ai_provider: 'AI Provider',
              };
              const label = labelMap[key] || key.replace(/_/g, ' ');
              return (
            <div
              key={key}
              className={`validation-item ${
                result.valid === true ? 'valid' : result.valid === false ? 'invalid' : 'skipped'
              }`}
            >
              <span className="validation-key">{label}</span>
              <span
                className={`validation-status ${
                  result.valid === true ? 'valid' : result.valid === false ? 'invalid' : 'skipped'
                }`}
              >
                {result.valid === true ? '✓ Valid' : result.valid === false ? '✗ Invalid' : '- Skipped'}
              </span>
              {result.message && <p className="validation-message">{result.message}</p>}
            </div>
              );
            })}
        </div>
      )}

      <div className="button-group">
        <button
          type="button"
          className="btn-validate"
          onClick={handleValidate}
          disabled={validating || saving}
          title="Optional connectivity check — not required for ticket lookups"
        >
          {validating ? 'Validating...' : 'Test Keys'}
        </button>
        <button
          type="button"
          className="btn-save"
          onClick={handleSave}
          disabled={saving || validating || !hasChanges()}
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button type="button" className="btn-cancel" onClick={onClose} disabled={saving || validating}>
          Cancel
        </button>
      </div>

      <div className="security-note">
        <p>
          <strong>Security:</strong> Your API keys are encrypted at rest and never shared with other
          users. Only you can access your keys.
        </p>
      </div>
    </div>
  );
}
