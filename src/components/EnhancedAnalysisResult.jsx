/**
 * Enhanced Analysis Result Component
 * 
 * Displays analysis results with agent framework information including:
 * - Pattern match confidence and source
 * - Credit usage and cost tracking
 * - Agent execution details
 * - Handoff information (if applicable)
 */

import React, { useState } from 'react';
import './EnhancedAnalysisResult.css';

const EnhancedAnalysisResult = ({ result, testcase, onRetrigger, onFirstLevelAnalysis, onApprovePattern, onRetriggerAfterPattern, onApproveTestFix, onReviewTestFix }) => {
  const [showDetails, setShowDetails] = useState(false);

  if (!result || !result.analysis) return null;

  const analysis = result.analysis;
  
  // Determine analysis source display
  const getSourceInfo = () => {
    const source = analysis.source;
    switch (source) {
      case 'cache':
        return { label: 'Cached Result', color: '#28a745', icon: '💾' };
      case 'pattern':
      case 'pattern_cache':
        return { label: 'Pattern Match', color: '#17a2b8', icon: '🔍' };
      case 'skill':
        return { label: 'Skill Analysis', color: '#6f42c1', icon: '🧠' };
      case 'handoff':
        return { label: 'Cross-Agent', color: '#fd7e14', icon: '🔄' };
      case 'merged':
        return { label: 'Multi-Agent', color: '#20c997', icon: '🤝' };
      default:
        return { label: 'Agent Analysis', color: '#6c757d', icon: '🤖' };
    }
  };

  const sourceInfo = getSourceInfo();
  
  // Format confidence as percentage
  const confidencePercent = (analysis.confidence * 100).toFixed(1);
  
  // Get confidence color
  const getConfidenceColor = (confidence) => {
    if (confidence >= 0.8) return '#28a745';
    if (confidence >= 0.6) return '#ffc107';
    return '#dc3545';
  };

  // Format execution time
  const formatExecutionTime = (ms) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  // Check if this was a handoff
  const handoffInfo = analysis.data?.handoff_execution || analysis.data?.handoff_warning;
  const isMultiAgent = analysis.data?.orchestration?.multi_agent_analysis;
  
  return (
    <div className="enhanced-analysis-result">
      {/* Main Result Header */}
      <div className="analysis-header">
        <div className="source-badge">
          <span className="source-icon">{sourceInfo.icon}</span>
          <span className="source-label" style={{ color: sourceInfo.color }}>
            {sourceInfo.label}
          </span>
        </div>
        
        <div className="confidence-badge">
          <span 
            className="confidence-value"
            style={{ color: getConfidenceColor(analysis.confidence) }}
          >
            {confidencePercent}%
          </span>
          <span className="confidence-label">confidence</span>
        </div>
        
        {analysis.credits_used > 0 && (
          <div className="credits-badge">
            <span className="credits-value">{analysis.credits_used}</span>
            <span className="credits-label">credits</span>
          </div>
        )}
      </div>

      {/* Pattern Match Info */}
      {analysis.pattern_matched && (
        <div className="pattern-info">
          <div className="pattern-indicator">
            <span className="pattern-icon">✓</span>
            <span className="pattern-text">Pattern Matched</span>
          </div>
          <div className="pattern-description">
            {analysis.pattern_description}
          </div>
          {analysis.rdm_category && (
            <div className="pattern-category">
              Category: <span className="category-value">{analysis.rdm_category}</span>
            </div>
          )}
        </div>
      )}

      {/* Execution Details */}
      <div className="execution-details">
        <span className="execution-time">
          Executed in {formatExecutionTime(analysis.execution_time_ms)}
        </span>
        
        {analysis.analysis_type !== 'unknown' && (
          <span className="analysis-type">
            Type: {analysis.analysis_type.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {/* Handoff Information */}
      {handoffInfo && (
        <div className="handoff-info">
          {analysis.data.handoff_execution && (
            <div className="handoff-success">
              <span className="handoff-icon">🔄</span>
              <span>Handed off from {analysis.data.handoff_execution.source_agent}</span>
              <span className="handoff-rule">
                ({analysis.data.handoff_execution.handoff_rule})
              </span>
            </div>
          )}
          
          {analysis.data.handoff_warning && (
            <div className="handoff-warning">
              <span className="warning-icon">⚠️</span>
              <span>Handoff attempted but failed</span>
            </div>
          )}
        </div>
      )}

      {/* Multi-Agent Analysis */}
      {isMultiAgent && (
        <div className="multi-agent-info">
          <span className="multi-agent-icon">🤝</span>
          <span>Multi-agent analysis completed</span>
        </div>
      )}

      {/* Cost Optimization Indicators */}
      {analysis.credits_used === 0 && analysis.pattern_matched && (
        <div className="optimization-indicator success">
          <span className="opt-icon">💰</span>
          <span>Cost optimized - no credits used</span>
        </div>
      )}

      {analysis.data?.user_requested && (
        <div className="optimization-indicator ai-analysis">
          <span className="opt-icon">🧠</span>
          <span>Deep AI analysis - user requested (no limits)</span>
        </div>
      )}

      {analysis.data?.credit_limit_reached && (
        <div className="optimization-indicator warning">
          <span className="opt-icon">⚠️</span>
          <span>Credit limit reached - pattern fallback used</span>
        </div>
      )}

      {/* Details Toggle */}
      <div className="details-toggle">
        <button 
          className="toggle-btn"
          onClick={() => setShowDetails(!showDetails)}
        >
          {showDetails ? 'Hide' : 'Show'} Details
        </button>
      </div>

      {/* Expanded Details */}
      {showDetails && (
        <div className="expanded-details">
          {/* Suggested Actions */}
          {analysis.data?.suggested_actions && (
            <div className="suggested-actions">
              <h5>Suggested Actions:</h5>
              <ul>
                {analysis.data.suggested_actions.map((action, index) => (
                  <li key={index}>{action}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Failure Timeline */}
          {analysis.data?.failure_timeline && (
            <div className="failure-timeline">
              <h5>Failure Timeline:</h5>
              {analysis.data.failure_timeline.map((event, index) => (
                <div key={index} className="timeline-event">
                  <span className="event-time">
                    {new Date(event.timestamp * 1000).toLocaleString()}
                  </span>
                  <span className="event-name">{event.event}</span>
                  <span className="event-details">{event.details}</span>
                </div>
              ))}
            </div>
          )}

          {/* JIRA Integration */}
          {analysis.data?.jira_ticket && (
            <div className="jira-info">
              <h5>JIRA Integration:</h5>
              <div className="jira-status">
                Status: {analysis.data.jira_ticket.created ? 'Created' : 'Failed'}
              </div>
              {analysis.data.jira_ticket.summary && (
                <div className="jira-summary">{analysis.data.jira_ticket.summary}</div>
              )}
            </div>
          )}

          {/* Secondary Analysis (for merged results) */}
          {analysis.data?.secondary_analysis && (
            <div className="secondary-analysis">
              <h5>Secondary Analysis:</h5>
              <div className="secondary-details">
                <div className="secondary-row">
                  <span>Type:</span>
                  <span>{analysis.data.secondary_analysis.analysis_type}</span>
                </div>
                <div className="secondary-row">
                  <span>Confidence:</span>
                  <span>{(analysis.data.secondary_analysis.confidence * 100).toFixed(1)}%</span>
                </div>
                <div className="secondary-row">
                  <span>Source:</span>
                  <span>{analysis.data.secondary_analysis.source}</span>
                </div>
              </div>
            </div>
          )}

          {/* Raw Analysis Data */}
          <div className="raw-data">
            <h5>Raw Analysis Data:</h5>
            <pre className="raw-json">
              {JSON.stringify(analysis.data, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {/* Pattern Learning Approval UI */}
      {analysis.data?.pattern_suggestion && (
        <div className="pattern-approval-section">
          <h5>🔄 New Pattern Detected</h5>
          <div className="pattern-preview">
            <div className="pattern-info">
              <span className="pattern-confidence">
                Confidence: {(analysis.data.pattern_suggestion.confidence * 100).toFixed(1)}%
              </span>
              <span className="pattern-type">
                Type: {analysis.data.pattern_suggestion.pattern_type || 'intermittent'}
              </span>
              <span className="pattern-category">
                Category: {analysis.data.pattern_suggestion.category || 'INTERMITTENT'}
              </span>
            </div>
            <p className="pattern-description">
              {analysis.data.pattern_suggestion.description}
            </p>
            {analysis.data.pattern_suggestion.regex && (
              <div className="pattern-regex-preview">
                <strong>Pattern:</strong> 
                <code>{analysis.data.pattern_suggestion.regex.substring(0, 80)}...</code>
              </div>
            )}
          </div>
          
          <div className="pattern-impact">
            <h6>Expected Impact:</h6>
            <ul>
              <li>✅ Automatically triage similar failures in the future</li>
              <li>⚡ Reduce manual analysis workload</li>
              <li>🎯 Provide consistent failure classification</li>
              <li>📊 Improve pattern database coverage</li>
            </ul>
          </div>
          
          <div className="approval-actions">
            <button 
              className="approve-pattern-btn"
              onClick={() => onApprovePattern && onApprovePattern(analysis.data.pattern_suggestion, 'approve')}
              title="Add this pattern to improve future auto-triage"
            >
              ✅ Add Pattern
            </button>
            <button 
              className="reject-pattern-btn"
              onClick={() => onApprovePattern && onApprovePattern(analysis.data.pattern_suggestion, 'reject')}
              title="Don't add this pattern"
            >
              ❌ Skip Pattern
            </button>
            <button 
              className="modify-pattern-btn"
              onClick={() => onApprovePattern && onApprovePattern(analysis.data.pattern_suggestion, 'modify')}
              title="Suggest changes to this pattern"
            >
              ✏️ Modify Pattern
            </button>
          </div>
        </div>
      )}
      
      {/* Pattern Approval Feedback */}
      {analysis.data?.pattern_approval_status && (
        <div className={`pattern-feedback ${analysis.data.pattern_approval_status.type}`}>
          <span className="feedback-icon">
            {analysis.data.pattern_approval_status.type === 'success' ? '✅' : 
             analysis.data.pattern_approval_status.type === 'error' ? '❌' : 'ℹ️'}
          </span>
          <span className="feedback-message">
            {analysis.data.pattern_approval_status.message}
          </span>
          {analysis.data.pattern_approval_status.type === 'success' && onRetriggerAfterPattern && (
            <button 
              className="retrigger-after-pattern-btn"
              onClick={() => onRetriggerAfterPattern(testcase)}
              title="Re-run analysis with the new pattern"
            >
              🔄 Re-analyze
            </button>
          )}
        </div>
      )}

      {/* Auto Test Fix Section */}
      {analysis.data?.auto_fix_suggestion && (
        <div className="auto-fix-section">
          <h5>🔧 Auto Test Fix Suggestion</h5>
          <div className="fix-preview">
            <div className="fix-header">
              <span className="fix-type-badge">{analysis.data.auto_fix_suggestion.fix_type}</span>
              <span className="fix-confidence">
                Confidence: {(analysis.data.auto_fix_suggestion.confidence * 100).toFixed(1)}%
              </span>
              <span className="fix-effort">
                Effort: {analysis.data.auto_fix_suggestion.estimated_effort}
              </span>
              <span className="fix-risk">
                Risk: {analysis.data.auto_fix_suggestion.risk_level}
              </span>
            </div>
            
            <p className="fix-description">
              {analysis.data.auto_fix_suggestion.description}
            </p>
            
            <div className="fix-changes">
              <h6>Suggested Changes:</h6>
              <ul className="changes-list">
                {analysis.data.auto_fix_suggestion.suggested_changes.map((change, index) => (
                  <li key={index} className="change-item">
                    <span className="change-type">{change.type}:</span>
                    <span className="change-description">{change.change}</span>
                    {change.file && <span className="change-file">({change.file})</span>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
          
          <div className="fix-actions">
            <button 
              className="approve-fix-btn"
              onClick={() => onApproveTestFix && onApproveTestFix(analysis.data.auto_fix_suggestion)}
              title="Approve fix and create change request"
            >
              ✅ Approve Fix & Create CR
            </button>
            <button 
              className="review-fix-btn"  
              onClick={() => onReviewTestFix && onReviewTestFix(analysis.data.auto_fix_suggestion)}
              title="Review fix details"
            >
              👁️ Review Details
            </button>
          </div>
        </div>
      )}

      {/* Auto Test Fix Status */}
      {analysis.data?.auto_test_details && (
        <div className="auto-fix-status-section">
          <h5>🔧 Auto Test Fix Status</h5>
          <div className="fix-status-info">
            <div className="status-header">
              <span className={`status-badge ${analysis.data.auto_test_details.fix_status}`}>
                {analysis.data.auto_test_details.fix_status.toUpperCase()}
              </span>
              {analysis.data.auto_test_details.cr_number && (
                <span className="cr-number">CR: {analysis.data.auto_test_details.cr_number}</span>
              )}
            </div>
            
            {analysis.data.auto_test_details.fix_results && (
              <div className="fix-results">
                <div className="result-summary">
                  {analysis.data.auto_test_details.fix_results.success ? '✅' : '❌'} 
                  {analysis.data.auto_test_details.fix_results.details}
                </div>
                
                {analysis.data.auto_test_details.fix_results.test_results && (
                  <div className="test-results">
                    <span className="test-status">
                      Test Result: {analysis.data.auto_test_details.fix_results.test_results.test_passed ? '✅ Passed' : '❌ Failed'}
                    </span>
                    <span className="execution-time">
                      ({analysis.data.auto_test_details.fix_results.test_results.execution_time}s)
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Existing Bug Detection Results */}
      {analysis.data?.existing_bugs && analysis.data.existing_bugs.found_existing && (
        <div className="existing-bugs-section">
          <h5>🔍 Existing Issues Found</h5>
          <div className="bugs-summary">
            <span className="confidence-score">
              Confidence: {(analysis.data.existing_bugs.confidence_score * 100).toFixed(1)}%
            </span>
            <span className="search-summary">{analysis.data.existing_bugs.search_summary}</span>
          </div>
          
          {analysis.data.existing_bugs.jira_tickets && analysis.data.existing_bugs.jira_tickets.length > 0 && (
            <div className="jira-tickets">
              <h6>Related JIRA Tickets:</h6>
              <div className="tickets-grid">
                {analysis.data.existing_bugs.jira_tickets.slice(0, 10).map((ticket, index) => (
                  <span key={index} className="jira-ticket">
                    <a href={`https://jira.nutanix.com/browse/${ticket}`} 
                       target="_blank" 
                       rel="noopener noreferrer">
                      {ticket}
                    </a>
                  </span>
                ))}
              </div>
            </div>
          )}
          
          {analysis.data.existing_bugs.product_behavior_docs && analysis.data.existing_bugs.product_behavior_docs.length > 0 && (
            <div className="behavior-docs">
              <h6>Product Behavior Documentation:</h6>
              <ul className="docs-list">
                {analysis.data.existing_bugs.product_behavior_docs.slice(0, 5).map((doc, index) => (
                  <li key={index} className="doc-item">
                    <a href={doc} target="_blank" rel="noopener noreferrer">
                      Product Documentation #{index + 1}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          
          {analysis.data.existing_bugs.top_matches && analysis.data.existing_bugs.top_matches.length > 0 && (
            <div className="top-matches">
              <h6>Top Search Matches:</h6>
              <div className="matches-list">
                {analysis.data.existing_bugs.top_matches.slice(0, 3).map((match, index) => (
                  <div key={index} className="match-item">
                    <div className="match-title">{match.title}</div>
                    <div className="match-preview">{match.content_preview}</div>
                    {match.url && (
                      <a href={match.url} target="_blank" rel="noopener noreferrer" className="match-link">
                        View Details
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Action Buttons */}
      <div className="result-actions">
        {onRetrigger && (
          <>
            <button 
              className="retrigger-btn"
              onClick={() => onRetrigger(testcase, false)}
            >
              🔄 Retry Analysis
            </button>
            
            {/* First Level AI Analysis Button */}
            {analysis.data?.requires_manual_analysis && onFirstLevelAnalysis && (
              <button 
                className="first-level-ai-btn"
                onClick={() => onFirstLevelAnalysis(testcase)}
                title="Perform First Level AI analysis with JITA API and Glean search"
              >
                🧠 First Level AI Analysis
              </button>
            )}
            
            {/* Deep AI Analysis Button */}
            <button 
              className="deep-ai-btn"
              onClick={() => onRetrigger(testcase, true)}
              disabled={analysis.source === 'ai' || analysis.source === 'skill'}
              title="Comprehensive AI analysis with no credit limits - user controlled"
            >
              🧠 Deep AI Analysis
            </button>
          </>
        )}
        
        {analysis.data?.jira_ready && !analysis.data?.jira_ticket?.created && (
          <button className="create-jira-btn">
            📋 Create JIRA Ticket
          </button>
        )}
      </div>
      
      {/* Errors */}
      {analysis.errors && analysis.errors.length > 0 && (
        <div className="analysis-errors">
          <h5>Errors:</h5>
          {analysis.errors.map((error, index) => (
            <div key={index} className="error-item">
              {error}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default EnhancedAnalysisResult;