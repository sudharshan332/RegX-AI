import React, { useEffect, useState } from 'react';
import api from '../api';
import './KeyManagementPanel.css';

const EMPTY_KEYS = {
  cursor_api_key: '',
  atlassian_jira_token: '',
  atlassian_confluence_token: '',
  gerrit_http_password: '',
  sourcegraph_token: '',
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
    atlassian_jira_token: false,
    atlassian_confluence_token: false,
    gerrit_http_password: false,
    sourcegraph_token: false,
  });

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    try {
      const response = await api.get('/mcp/regression/user-keys');
      const loadedKeys = { ...EMPTY_KEYS, ...(response.data || {}) };
      setKeys(loadedKeys);
      setOriginalKeys(loadedKeys);
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
        const value = (keys[key] || '').trim();
        if (value && !value.includes('****')) {
          keysToSave[key] = value;
        }
      });
      if (Object.keys(keysToSave).length === 0) {
        setError('No new keys to save. Enter a new value in any field, then click Save.');
        return;
      }
      await api.put('/mcp/regression/user-keys', keysToSave);
      setSuccess('Keys saved successfully!');
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
      const keysToValidate = {};
      Object.keys(keys).forEach((key) => {
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

  const hasChanges = () =>
    Object.keys(keys).some((key) => {
      const value = (keys[key] || '').trim();
      const original = (originalKeys[key] || '').trim();
      return value && value !== original && !value.includes('****');
    });

  return (
    <div className="key-management-panel">
      <h2>API Key Configuration</h2>
      <p className="panel-description">
        Paste your Atlassian Jira Personal Token and click <strong>Save</strong>.
        Dashboard Jira status / product-vs-test lookups use that saved token.
        Test Keys is optional and may fail if Jira is unreachable — that does not
        block ticket data after Save.
      </p>

      {error && <div className="message-banner error-banner">{error}</div>}
      {success && <div className="message-banner success-banner">{success}</div>}

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
          Required for AI analysis features. Get yours from{' '}
          <a href="https://cursor.com/settings" target="_blank" rel="noopener noreferrer">
            cursor.com/settings
          </a>
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
          Used for automatic Gerrit CR creation in Handover. Username is your logged-in email.
        </p>
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
          {Object.entries(validationResults.results || {}).map(([key, result]) => (
            <div
              key={key}
              className={`validation-item ${
                result.valid === true ? 'valid' : result.valid === false ? 'invalid' : 'skipped'
              }`}
            >
              <span className="validation-key">{key.replace(/_/g, ' ')}</span>
              <span
                className={`validation-status ${
                  result.valid === true ? 'valid' : result.valid === false ? 'invalid' : 'skipped'
                }`}
              >
                {result.valid === true ? '✓ Valid' : result.valid === false ? '✗ Invalid' : '- Skipped'}
              </span>
              {result.message && <p className="validation-message">{result.message}</p>}
            </div>
          ))}
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
