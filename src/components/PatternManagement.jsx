/**
 * Pattern Management Component
 * 
 * Manages pattern learning, approval workflows, and effectiveness tracking.
 * Provides interface for:
 * - Viewing pattern candidates awaiting approval
 * - Approving/rejecting/modifying suggested patterns  
 * - Tracking pattern effectiveness metrics
 * - Managing pattern database
 */

import React, { useState, useEffect } from 'react';
import './PatternManagement.css';

const PatternManagement = ({ apiEndpoint }) => {
  const [activeTab, setActiveTab] = useState('pending');
  const [pendingPatterns, setPendingPatterns] = useState([]);
  const [approvedPatterns, setApprovedPatterns] = useState([]);
  const [effectivenessData, setEffectivenessData] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadPatternData();
  }, []);

  const loadPatternData = async () => {
    setLoading(true);
    setError(null);
    
    try {
      // Load pending pattern approvals
      const pendingResponse = await fetch(`${apiEndpoint}/patterns/pending`);
      if (pendingResponse.ok) {
        const pendingData = await pendingResponse.json();
        setPendingPatterns(pendingData.patterns || []);
      }

      // Load approved patterns
      const approvedResponse = await fetch(`${apiEndpoint}/patterns/approved`);
      if (approvedResponse.ok) {
        const approvedData = await approvedResponse.json();
        setApprovedPatterns(approvedData.patterns || []);
      }

      // Load effectiveness metrics
      const effectivenessResponse = await fetch(`${apiEndpoint}/patterns/effectiveness`);
      if (effectivenessResponse.ok) {
        const effectivenessData = await effectivenessResponse.json();
        setEffectivenessData(effectivenessData);
      }
    } catch (err) {
      setError('Failed to load pattern data: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handlePatternApproval = async (patternId, action, modifications = null) => {
    try {
      const response = await fetch(`${apiEndpoint}/patterns/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pattern_id: patternId,
          action,
          modifications
        })
      });

      const result = await response.json();
      
      if (result.success) {
        // Refresh data after approval
        await loadPatternData();
        
        // Show success message
        setError(null);
        alert(`Pattern ${action} successfully!`);
      } else {
        setError(`Pattern ${action} failed: ${result.error}`);
      }
    } catch (err) {
      setError(`Error ${action}ing pattern: ${err.message}`);
    }
  };

  const formatConfidence = (confidence) => {
    return `${(confidence * 100).toFixed(1)}%`;
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short', 
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getEffectivenessColor = (score) => {
    if (score >= 0.8) return '#28a745';
    if (score >= 0.6) return '#ffc107';
    return '#dc3545';
  };

  const PendingPatternsTab = () => (
    <div className="patterns-tab">
      <h3>Pending Pattern Approvals</h3>
      
      {pendingPatterns.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">📋</span>
          <p>No patterns pending approval</p>
        </div>
      ) : (
        <div className="patterns-grid">
          {pendingPatterns.map((pattern) => (
            <div key={pattern.id} className="pattern-card pending">
              <div className="pattern-header">
                <div className="pattern-meta">
                  <span className="pattern-id">{pattern.id}</span>
                  <span className="pattern-confidence">
                    {formatConfidence(pattern.confidence)}
                  </span>
                </div>
                <span className="pattern-type">{pattern.pattern_type}</span>
              </div>
              
              <div className="pattern-content">
                <p className="pattern-description">{pattern.description}</p>
                
                <div className="pattern-details">
                  <div className="detail-row">
                    <span className="detail-label">Category:</span>
                    <span className="detail-value">{pattern.category}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-label">Source Test:</span>
                    <span className="detail-value">{pattern.source_test_id}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-label">Created:</span>
                    <span className="detail-value">{formatDate(pattern.created_at)}</span>
                  </div>
                </div>

                <div className="pattern-regex">
                  <strong>Pattern:</strong>
                  <code>{pattern.regex}</code>
                </div>
                
                <div className="pattern-analysis">
                  <strong>Action:</strong> {pattern.action}
                </div>
              </div>
              
              <div className="pattern-actions">
                <button 
                  className="approve-btn"
                  onClick={() => handlePatternApproval(pattern.id, 'approve')}
                >
                  ✅ Approve
                </button>
                <button 
                  className="reject-btn"
                  onClick={() => handlePatternApproval(pattern.id, 'reject')}
                >
                  ❌ Reject
                </button>
                <button 
                  className="modify-btn"
                  onClick={() => {
                    // In a real implementation, this would open a modification dialog
                    const newDescription = prompt('Enter new description:', pattern.description);
                    if (newDescription) {
                      handlePatternApproval(pattern.id, 'modify', { description: newDescription });
                    }
                  }}
                >
                  ✏️ Modify
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const ApprovedPatternsTab = () => (
    <div className="patterns-tab">
      <h3>Approved Patterns</h3>
      
      {approvedPatterns.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">✅</span>
          <p>No approved patterns yet</p>
        </div>
      ) : (
        <div className="patterns-grid">
          {approvedPatterns.map((pattern) => {
            const effectiveness = effectivenessData.patterns?.find(e => e.pattern_id === pattern.id);
            
            return (
              <div key={pattern.id} className="pattern-card approved">
                <div className="pattern-header">
                  <div className="pattern-meta">
                    <span className="pattern-id">{pattern.id}</span>
                    <span className="pattern-confidence">
                      {formatConfidence(pattern.confidence)}
                    </span>
                  </div>
                  <div className="effectiveness-info">
                    {effectiveness && (
                      <span 
                        className="effectiveness-score"
                        style={{ color: getEffectivenessColor(effectiveness.effectiveness_score) }}
                      >
                        {formatConfidence(effectiveness.effectiveness_score)} effective
                      </span>
                    )}
                  </div>
                </div>
                
                <div className="pattern-content">
                  <p className="pattern-description">{pattern.description}</p>
                  
                  <div className="pattern-details">
                    <div className="detail-row">
                      <span className="detail-label">Category:</span>
                      <span className="detail-value">{pattern.category}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-label">Approved:</span>
                      <span className="detail-value">{formatDate(pattern.approved_at || pattern.created_at)}</span>
                    </div>
                  </div>

                  {effectiveness && (
                    <div className="effectiveness-metrics">
                      <h5>Usage Metrics:</h5>
                      <div className="metrics-grid">
                        <div className="metric">
                          <span className="metric-value">{effectiveness.total_matches}</span>
                          <span className="metric-label">Total Matches</span>
                        </div>
                        <div className="metric">
                          <span className="metric-value">{effectiveness.correct_matches}</span>
                          <span className="metric-label">Correct</span>
                        </div>
                        <div className="metric">
                          <span className="metric-value">{effectiveness.false_positives}</span>
                          <span className="metric-label">False Positives</span>
                        </div>
                      </div>
                      {effectiveness.last_matched && (
                        <div className="last-match">
                          Last used: {formatDate(effectiveness.last_matched)}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  const EffectivenessTab = () => (
    <div className="patterns-tab">
      <h3>Pattern Effectiveness Report</h3>
      
      {effectivenessData.summary && (
        <div className="effectiveness-summary">
          <div className="summary-cards">
            <div className="summary-card">
              <span className="summary-value">{effectivenessData.total_patterns}</span>
              <span className="summary-label">Total Patterns</span>
            </div>
            <div className="summary-card high">
              <span className="summary-value">{effectivenessData.summary.high_effectiveness}</span>
              <span className="summary-label">High Effectiveness (80%+)</span>
            </div>
            <div className="summary-card medium">
              <span className="summary-value">{effectivenessData.summary.medium_effectiveness}</span>
              <span className="summary-label">Medium Effectiveness (60-80%)</span>
            </div>
            <div className="summary-card low">
              <span className="summary-value">{effectivenessData.summary.low_effectiveness}</span>
              <span className="summary-label">Low Effectiveness (30-60%)</span>
            </div>
            <div className="summary-card needs-review">
              <span className="summary-value">{effectivenessData.summary.needs_review}</span>
              <span className="summary-label">Needs Review (&lt;30%)</span>
            </div>
          </div>
        </div>
      )}
      
      {effectivenessData.patterns && effectivenessData.patterns.length > 0 && (
        <div className="effectiveness-table">
          <table>
            <thead>
              <tr>
                <th>Pattern ID</th>
                <th>Effectiveness</th>
                <th>Total Matches</th>
                <th>Accuracy</th>
                <th>Last Used</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {effectivenessData.patterns
                .sort((a, b) => b.effectiveness_score - a.effectiveness_score)
                .map((pattern) => {
                  const accuracy = pattern.total_matches > 0 
                    ? (pattern.correct_matches / (pattern.correct_matches + pattern.false_positives))
                    : 0;
                  
                  return (
                    <tr key={pattern.pattern_id}>
                      <td className="pattern-id-cell">{pattern.pattern_id}</td>
                      <td 
                        className="effectiveness-cell"
                        style={{ color: getEffectivenessColor(pattern.effectiveness_score) }}
                      >
                        {formatConfidence(pattern.effectiveness_score)}
                      </td>
                      <td>{pattern.total_matches}</td>
                      <td>{isNaN(accuracy) ? 'N/A' : formatConfidence(accuracy)}</td>
                      <td>
                        {pattern.last_matched 
                          ? formatDate(pattern.last_matched)
                          : 'Never'
                        }
                      </td>
                      <td>
                        <span className={`status-badge ${pattern.effectiveness_score >= 0.7 ? 'good' : pattern.effectiveness_score >= 0.3 ? 'warning' : 'poor'}`}>
                          {pattern.effectiveness_score >= 0.7 ? 'Good' : 
                           pattern.effectiveness_score >= 0.3 ? 'Fair' : 'Poor'}
                        </span>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <div className="pattern-management">
      <div className="management-header">
        <h2>Pattern Learning Management</h2>
        <button 
          className="refresh-btn"
          onClick={loadPatternData}
          disabled={loading}
        >
          {loading ? '⏳' : '🔄'} Refresh
        </button>
      </div>

      {error && (
        <div className="error-banner">
          <span className="error-icon">❌</span>
          <span className="error-message">{error}</span>
          <button 
            className="error-dismiss"
            onClick={() => setError(null)}
          >
            ✕
          </button>
        </div>
      )}

      <div className="tab-navigation">
        <button 
          className={`tab-btn ${activeTab === 'pending' ? 'active' : ''}`}
          onClick={() => setActiveTab('pending')}
        >
          📋 Pending ({pendingPatterns.length})
        </button>
        <button 
          className={`tab-btn ${activeTab === 'approved' ? 'active' : ''}`}
          onClick={() => setActiveTab('approved')}
        >
          ✅ Approved ({approvedPatterns.length})
        </button>
        <button 
          className={`tab-btn ${activeTab === 'effectiveness' ? 'active' : ''}`}
          onClick={() => setActiveTab('effectiveness')}
        >
          📊 Effectiveness
        </button>
      </div>

      <div className="tab-content">
        {loading ? (
          <div className="loading-state">
            <div className="loading-spinner"></div>
            <p>Loading pattern data...</p>
          </div>
        ) : (
          <>
            {activeTab === 'pending' && <PendingPatternsTab />}
            {activeTab === 'approved' && <ApprovedPatternsTab />}
            {activeTab === 'effectiveness' && <EffectivenessTab />}
          </>
        )}
      </div>
    </div>
  );
};

export default PatternManagement;