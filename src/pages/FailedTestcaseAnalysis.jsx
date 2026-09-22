import React, { useState, useEffect, useCallback, useRef } from 'react';
import api from '../api';
import { API_BASE_URL } from '../config';
import { extractJitaTaskIds, buildJitaResultsUrls } from '../utils/jitaTaskIds';
import './FailedTestcaseAnalysis.css';

const API_BASE = `${API_BASE_URL}/mcp/regression/failed-analysis`;
const FLUX_API = `${API_BASE_URL}/mcp/regression/flux`;
const NODE_POOL_SEARCH_URL = `${API_BASE_URL}/mcp/regression/dynamic-jp/search-node-pools`;
const JIRA_URL = 'https://jira.nutanix.com/browse/';
const NO_JIRA_TICKET = 'No Ticket';
export const JIRA_BUG_TYPE_OPTIONS = ['Product Bug', 'Test Bug', 'Environment', 'Flaky', 'Other', NO_JIRA_TICKET];

/** Classify a Jira issue type string into Test Bug / Product Bug / related categories. */
export function categorizeJiraBugType(issueType) {
  if (!issueType) return null;
  const s = String(issueType).toLowerCase();
  if (s === 'n/a' || s === 'unknown') return null;
  if (s.includes('environment')) return 'Environment';
  if (s.includes('flaky')) return 'Flaky';
  if (s.includes('test') || s.includes('testbed')) return 'Test Bug';
  if (s.includes('bug')) return 'Product Bug';
  return null;
}

/** Join tester log URL with testcase name, replacing '.' with '/'. */
export function buildCompleteLogsPath(logUrl, testcaseName) {
  const base = String(logUrl || '').trim();
  const name = String(testcaseName || '').trim();
  if (!base || !name) return '';
  const path = name.replace(/\./g, '/');
  return `${base.replace(/\/+$/, '')}/${path}/`;
}

export function collectResultJiraTickets(result) {
  return [...new Set((result?.jira_tickets || []).map(t => String(t).trim()).filter(Boolean))];
}

export function fluxFirstJiraKey(result) {
  return collectResultJiraTickets(result)[0] || '';
}

export function fluxConfidencePercent(confidence) {
  if (confidence == null || confidence === '') return null;
  const n = Number(confidence);
  if (!Number.isFinite(n)) return null;
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n);
  return Math.max(0, Math.min(100, pct));
}

export function fluxCategoryLabel(category) {
  const c = String(category || '').toLowerCase();
  if (c === 'product_issue' || c === 'product_bug') return 'Product-side Issue';
  if (c === 'test_bug' || c === 'genuine_test_bug') return 'Genuine Test Bug';
  if (c === 'environment_issue' || c === 'environment') return 'Environment Issue';
  return category ? String(category) : '';
}

export const FLUX_MAX_WAIT_MS = 15 * 60 * 1000;
export const FLUX_POLL_INTERVAL_MS = 10000;

/** Safe React text: primitives only; objects/arrays must not be rendered as children. */
export function textOrEmpty(value) {
  if (value == null || value === false) return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
}

export function triageModalAnalysisText(modal) {
  if (!modal) return '';
  return (
    textOrEmpty(modal.root_cause)
    || textOrEmpty(modal.ai_summary)
    || textOrEmpty(modal.analysis)
  );
}

function mcpEntryIsDown(entry) {
  if (entry == null) return false;
  if (typeof entry === 'boolean') return entry === false;
  if (typeof entry === 'string') {
    const s = entry.trim().toLowerCase();
    return s === 'unavailable' || s === 'down' || s === 'error' || s === 'failed' || s === 'false';
  }
  if (typeof entry === 'object') {
    if (entry.ok === false) return true;
    const status = String(entry.status || entry.state || '').toLowerCase();
    return status === 'unavailable' || status === 'down' || status === 'error' || status === 'failed';
  }
  return false;
}

export function rdmMcpHealthBanners(mcpHealth) {
  const health = mcpHealth || {};
  const banners = [];
  if (mcpEntryIsDown(health.glean)) {
    banners.push({
      key: 'glean',
      title: 'Glean MCP unavailable',
      detail: 'Ticket matching may be incomplete. Using pre-fetched search results if any.',
    });
  }
  if (mcpEntryIsDown(health.sourcegraph)) {
    banners.push({
      key: 'sourcegraph',
      title: 'Sourcegraph MCP unavailable',
      detail: 'Skill files may not have loaded. Analysis used the RDM failure message and logs only.',
    });
  }
  return banners;
}

export function rdmRecommendedActionLabel(skill) {
  const action = textOrEmpty(skill?.recommended_action);
  const ticket = textOrEmpty(skill?.jira_ticket) || textOrEmpty(skill?.jira_refs?.[0]);
  const project = textOrEmpty(skill?.suggested_jira_project) || textOrEmpty(skill?.jira_create?.project) || 'DIAL';
  if (action === 'link_existing') {
    return ticket ? `Link ${ticket}` : 'Link existing ticket';
  }
  if (action === 'create_jira') {
    return `Create ${project} ticket`;
  }
  if (action === 'disable_node_and_rerun') {
    return 'Disable node and rerun';
  }
  if (action === 'rerun') {
    return 'Rerun';
  }
  return action;
}

export function fluxHasRootCause(ticket) {
  return Boolean(String(ticket?.root_cause || '').trim());
}

export function fluxHasGerritCr(ticket) {
  return Boolean(String(ticket?.gerrit_url || '').trim() && String(ticket?.gerrit_change_id || '').trim());
}

export function fluxPipelineError(ticket) {
  const events = ticket?.task_events || [];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i] || {};
    const type = String(ev.type || '').toLowerCase();
    const stage = String(ev.stage || '').toLowerCase();
    if (type === 'error' || stage === 'failed' || stage === 'error') {
      return String(ev.message || '').trim() || 'Flux pipeline failed';
    }
  }
  return '';
}

export function fluxCanCreateGerritCr(ticket) {
  if (!fluxHasRootCause(ticket) || fluxHasGerritCr(ticket)) return false;
  const cat = String(ticket?.failure_category || '').toLowerCase();
  if (cat !== 'test_bug' && cat !== 'genuine_test_bug') return false;
  return fluxConfidencePercent(ticket?.confidence) != null;
}

const FLUX_ACTIVE_STATUSES = new Set([
  'starting', 'queued', 'ingesting', 'analyzing', 'fixing', 'running', 'processing',
]);

export function fluxShouldPoll(status, ticket, job = {}) {
  const s = String(status || ticket?.status || job.status || '').toLowerCase();
  if (!job.record_id && s !== 'starting') return false;
  if (fluxHasGerritCr(ticket)) return false;
  if (fluxPipelineError(ticket)) return false;
  const startedAt = Number(job.startedAt) || 0;
  if (startedAt && Date.now() - startedAt > FLUX_MAX_WAIT_MS) return false;
  if (!fluxHasRootCause(ticket)) return true;
  if (fluxCanCreateGerritCr(ticket) && !job.resumeAttempted) return true;
  if (job.resumeAttempted && !fluxHasGerritCr(ticket)) return true;
  return FLUX_ACTIVE_STATUSES.has(s);
}

export function fluxIsRunning(status, ticket, job = {}) {
  if (job.resuming) return true;
  return fluxShouldPoll(status, ticket, job);
}

export function fluxNutestTargetBranch(result, analysisBranch) {
  const fromRow = String(
    (result && (result.nutest_branch || result['nutest-py3-tests_branch'] || result.framework_branch)) || ''
  ).trim();
  const raw = fromRow || String(analysisBranch || (result && result.branch) || '').trim();
  if (!raw) return '';
  const lower = raw.toLowerCase();
  if (lower === 'master' || lower === 'main') return 'master';
  if (/^ganges-.+-stable$/i.test(raw)) return raw;
  if (/^\d+(?:\.\d+)+$/.test(raw)) return `ganges-${raw}-stable`;
  return raw;
}

export function fluxLatestStageMessage(ticket) {
  const events = ticket?.task_events || [];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const msg = events[i]?.message;
    if (msg) return msg;
  }
  return ticket?.status || '';
}

export function bugTypeLabelForDetail(detail) {
  if (!detail) return 'Other';
  const bt = detail.bug_type || categorizeJiraBugType(detail.issue_type);
  return bt || 'Other';
}

export function jiraBugTypesForResult(result, details = {}) {
  const tickets = collectResultJiraTickets(result);
  if (!tickets.length) return [NO_JIRA_TICKET];
  return tickets.map(t => bugTypeLabelForDetail(details[t]));
}

export function jiraStatusesForResult(result, details = {}) {
  const tickets = collectResultJiraTickets(result);
  if (!tickets.length) return [NO_JIRA_TICKET];
  return tickets.map(t => {
    const st = details[t]?.status;
    if (!st || st === 'N/A') return details[t] ? 'Unknown' : 'Loading';
    return st;
  });
}

export function resultMatchesJiraBugTypes(result, details, selectedTypes) {
  if (!selectedTypes || selectedTypes.length === 0) return false;
  if (selectedTypes.length >= JIRA_BUG_TYPE_OPTIONS.length) return true;
  return jiraBugTypesForResult(result, details).some(t => selectedTypes.includes(t));
}

export function resultMatchesJiraStatuses(result, details, selectedStatuses) {
  if (!selectedStatuses || selectedStatuses.length === 0) return false;
  return jiraStatusesForResult(result, details).some(s => selectedStatuses.includes(s));
}
const RESOURCE_MODE_OPTIONS = [
  { value: 'node_pool', label: 'By Node Pool' },
  { value: 'cluster', label: 'By Cluster Pool' },
  { value: 'global_pool', label: 'By Global Pool' },
  { value: 'name', label: 'By Name' },
];
const RESOURCE_TYPE_OPTIONS = [
  { value: 'physical', label: 'Physical' },
  { value: 'nested_2.0', label: 'NestedAHV 2.0' },
  { value: 'nested_1.0', label: 'NestedAHV 1.0' },
];
const HYPERVISOR_OPTIONS = ['esx', 'kvm', 'hyperv', 'xen'];

function normalizeJitaTaskId(id) {
  if (!id) return '';
  if (typeof id === 'object') return String(id.$oid || id._id || id.id || '');
  return String(id).trim();
}

const TRIAGE_GENIE_REVIEW_BASE = 'http://triage-genie.eng.nutanix.com/review';


function jitaResultsUrl(taskIds) {
  const urls = buildJitaResultsUrls(
    (Array.isArray(taskIds) ? taskIds : [taskIds]).map(normalizeJitaTaskId).filter(Boolean)
  );
  return urls[0] || '';
}

function jitaResultsUrls(taskIds) {
  return buildJitaResultsUrls(
    (Array.isArray(taskIds) ? taskIds : [taskIds]).map(normalizeJitaTaskId).filter(Boolean)
  );
}

function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  return Promise.resolve();
}

const RETRIGGER_SMOKE_TAGS = [
  'Latest Smoke Passed',
  'Latest DIAL Passed',
  'latest_smoke_passed',
  '$LATEST_SMOKE_PASSED',
];

function applyCommitOrTag(overrides, raw, commitKey, tagKey) {
  const value = (raw || '').trim();
  if (!value) return;
  const mapped = RETRIGGER_SMOKE_TAGS.find(t => t.toLowerCase() === value.toLowerCase());
  if (mapped || value.startsWith('$')) {
    overrides[tagKey] = mapped || value;
  } else {
    overrides[commitKey] = value;
  }
}

function triageGenieReviewId(result) {
  if (result?.testcase_id) return String(result.testcase_id);
  const logUrl = (result?.test_log_url || '').replace(/\/+$/, '');
  const last = logUrl.split('/').filter(Boolean).pop();
  return last || '';
}

function triageGenieReviewUrl(result) {
  const id = triageGenieReviewId(result);
  return id ? `${TRIAGE_GENIE_REVIEW_BASE}/${id}` : '';
}

function tgTicketFromResult(result) {
  return result?.triage_genie_ticket_id || result?.triage_genie_ticket || '';
}

function tgVerdictClass(verdict) {
  const v = String(verdict || 'Missing').toLowerCase();
  if (v === 'correct') return 'tg-verdict-correct';
  if (v === 'incorrect') return 'tg-verdict-incorrect';
  if (v === 'partial') return 'tg-verdict-partial';
  return 'tg-verdict-missing';
}

function buildFailedAnalysisTestResult(result) {
  const tg = tgTicketFromResult(result);
  const rdm = result.rdm_info || {};
  return {
    testcase_id: result.testcase_id,
    testcase_name: result.testcase_name,
    status: result.status,
    failure_stage: result.failure_stage,
    exception_summary: result.exception_summary || rdm.rdm_message || '',
    exception: result.exception || rdm.rdm_message || '',
    ai_summary: result.ai_summary || '',
    agave_task_id: result.agave_task_id,
    test_log_url: result.test_log_url || '',
    rdm_link: rdm.rdm_link || result.rdm_link || '',
    rdm_message: rdm.rdm_message || '',
    jira_tickets: result.jira_tickets || [],
    triage_genie_ticket: tg,
    triage_genie_ticket_id: tg,
  };
}

function TgValidationBlock({ validation }) {
  if (!validation) return null;
  const verdict = validation.verdict || 'Missing';
  return (
    <div className={`tg-validation-box tg-box-${String(verdict).toLowerCase()}`}>
      <div className="tg-validation-header">
        <span className={`badge ${tgVerdictClass(verdict)}`}>TG Ticket {verdict}</span>
        {validation.ticket ? (
          <a
            href={`${JIRA_URL}${validation.ticket}`}
            target="_blank"
            rel="noopener noreferrer"
            className="jira-link"
          >
            {validation.ticket}
          </a>
        ) : (
          <span className="tg-validation-none">No ticket suggested</span>
        )}
        {validation.jira_status && (
          <span className={`glean-status-badge ${validation.is_open ? 'glean-status-open' : 'glean-status-closed'}`}>
            {validation.jira_status}
          </span>
        )}
      </div>
      {validation.jira_summary && (
        <div className="tg-validation-summary">{validation.jira_summary}</div>
      )}
      {validation.reason && (
        <div className="tg-validation-reason">{validation.reason}</div>
      )}
    </div>
  );
}

function EnrichedTicketTable({ tickets, onAiValidate, validatingTicket, showMatchScore }) {
  if (!tickets || tickets.length === 0) return null;
  return (
    <div className="glean-ticket-table-wrapper">
      <table className="glean-ticket-table">
        <thead>
          <tr>
            <th>Ticket</th>
            <th>Status</th>
            {showMatchScore ? <th>Match</th> : null}
            <th>Type</th>
            <th>Summary</th>
            {onAiValidate ? <th>AI Validate</th> : null}
          </tr>
        </thead>
        <tbody>
          {tickets.map((t) => (
            <tr key={t.ticket} className={t.is_open ? 'glean-ticket-open' : 'glean-ticket-closed'}>
              <td>
                <a href={t.url || `${JIRA_URL}${t.ticket}`} target="_blank" rel="noopener noreferrer" className="jira-link">
                  {t.ticket}
                </a>
              </td>
              <td>
                <span className={`glean-status-badge ${t.is_open ? 'glean-status-open' : 'glean-status-closed'}`}>
                  {t.jira_status || 'Unknown'}
                </span>
                {t.jira_resolution && <span className="glean-resolution">({t.jira_resolution})</span>}
              </td>
              {showMatchScore ? (
                <td className="glean-match-score">
                  {t.match_score != null ? Number(t.match_score).toFixed(2) : '—'}
                </td>
              ) : null}
              <td className="glean-ticket-type">{t.jira_type || '-'}</td>
              <td className="glean-ticket-summary" title={t.jira_summary || t.glean_title || t.title}>
                {t.jira_summary || t.glean_title || t.title || '-'}
                {t.ai_validation?.verdict && (
                  <div className="glean-candidate-ai-verdict">
                    AI: {t.ai_validation.verdict}
                  </div>
                )}
              </td>
              {onAiValidate ? (
                <td>
                  <button
                    type="button"
                    className="btn-glean-ai-validate"
                    disabled={validatingTicket === t.ticket}
                    onClick={() => onAiValidate(t)}
                    title="Human-triggered AI validation for this candidate (not auto-run)"
                  >
                    {validatingTicket === t.ticket ? 'Validating…' : '[AI Validate]'}
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function McpHealthBadges({ mcpHealth }) {
  if (!mcpHealth) return null;
  const services = ['glean', 'sourcegraph', 'jira', 'triage_genie'];
  return (
    <div className="mcp-health-row" title="MCP / integration health — never treat failed services as successful evidence">
      {services.map((name) => {
        const h = mcpHealth[name];
        if (!h) return null;
        const ok = h.ok === true;
        const available = h.available !== false;
        const cls = !available || h.ok === false ? 'mcp-health-bad' : ok ? 'mcp-health-ok' : 'mcp-health-unknown';
        return (
          <span key={name} className={`badge mcp-health-badge ${cls}`}>
            {name}{ok ? ' ✓' : h.ok === false ? ' ✗' : ' ?'}
          </span>
        );
      })}
    </div>
  );
}

function DecisionBadge({ decision }) {
  if (!decision?.outcome) return null;
  const outcome = decision.outcome;
  const cls = `decision-badge decision-${String(outcome).toLowerCase()}`;
  return (
    <div className="decision-block">
      <span className={`badge ${cls}`} title={(decision.reasons || []).join('; ')}>
        {outcome}
      </span>
      {decision.deep_ai_recommended && !decision.deep_ai_started && (
        <span className="badge decision-deep-recommended">Deep AI recommended</span>
      )}
      {decision.deep_ai_started && (
        <span className="badge decision-deep-started">Deep AI started</span>
      )}
      {decision.auto_triage_write === 'recommend_only' && (
        <span className="badge decision-recommend-only">Recommend only</span>
      )}
      {decision.auto_triage_write === 'applied' && (
        <span className="badge decision-auto-applied">Auto-triage applied</span>
      )}
    </div>
  );
}

const TEST_STATUS_OPTIONS = [
  { id: 'failed', label: 'Failed' },
  { id: 'skipped', label: 'Skipped' },
  { id: 'warning', label: 'Warning' },
  { id: 'killed', label: 'Killed' },
  { id: 'pending', label: 'Pending' },
];

const STATUS_OPTION_ALIASES = {
  failed: ['failed', 'failure'],
  skipped: ['skipped', 'skip'],
  warning: ['warning', 'warn'],
  killed: ['killed', 'terminated', 'cancelled'],
  pending: ['pending', 'waiting', 'running', 'started'],
};

function optionIdForRawStatus(raw) {
  const s = String(raw || '').toLowerCase();
  if (!s || s === '(empty)') return null;
  for (const opt of TEST_STATUS_OPTIONS) {
    const aliases = STATUS_OPTION_ALIASES[opt.id] || [opt.id];
    if (opt.id === s || aliases.includes(s)) return opt.id;
  }
  return null;
}

function formatStatusCountSummary(counts) {
  return Object.entries(counts || {})
    .sort((a, b) => b[1] - a[1])
    .map(([status, n]) => `${n} ${status}`)
    .join(', ');
}

const COLUMNS = [
  { id: 'testcase_name', label: 'Testcase Name', defaultVisible: true },
  { id: 'jita_task', label: 'Jita Task', defaultVisible: true },
  { id: 'complete_logs_path', label: 'Complete Logs Path', defaultVisible: true },
  { id: 'regression_owner', label: 'Regression Owner', defaultVisible: true },
  { id: 'status', label: 'Status', defaultVisible: true },
  { id: 'failure_stage', label: 'Failure Stage', defaultVisible: true },
  { id: 'exception_summary', label: 'Exception Summary', defaultVisible: true },
  { id: 'ai_summary', label: 'AI Summary', defaultVisible: false },
  { id: 'intelligent_triage', label: 'Intelligent Triage', defaultVisible: true },
  { id: 'auto_test_details', label: 'Auto Test Details', defaultVisible: true },
  { id: 'glean_search', label: 'Glean Search', defaultVisible: true },
  { id: 'cursor_ai_analysis', label: 'Deep AI / Cursor', defaultVisible: false },
  { id: 'triage_genie_ticket', label: 'Triage Genie Ticket', defaultVisible: true },
  { id: 'triage_genie_review', label: 'Triage Genie Review', defaultVisible: true },
  { id: 'jira_tickets', label: 'Jira Tickets', defaultVisible: true },
  { id: 'jira_issue_type', label: 'Jira Ticket Issue Type', defaultVisible: true },
  { id: 'jira_ticket_status', label: 'Jira Ticket Status', defaultVisible: true },
  { id: 'flux_quick_fix', label: 'Flux Quick Fix', defaultVisible: true },
  { id: 'comment', label: 'Comment', defaultVisible: true },
  { id: 'update_jita', label: 'Update Jita', defaultVisible: true },
  { id: 'issue_type', label: 'Issue Type', defaultVisible: false },
  { id: 'suggestion_by_ai_agent', label: 'Suggestion By AI Agent', defaultVisible: false },
  { id: 'intermittent', label: 'Intermittent', defaultVisible: false },
  { id: 'rdm_analysis', label: 'RDM Analysis', defaultVisible: true },
  { id: 'history_same_branch', label: 'History (Same Branch)', defaultVisible: false },
  { id: 'history_other_branch', label: 'History (Other Branch)', defaultVisible: false },
  { id: 'actions', label: 'Actions', defaultVisible: true },
];

const DEFAULT_VISIBLE = COLUMNS.filter(c => c.defaultVisible).map(c => c.id);
const STORAGE_KEY = 'failedAnalysisVisibleColumns';
const TG_REVIEW_COL_KEY = 'failedAnalysisAddedTgReview';
const JITA_TASK_COL_KEY = 'failedAnalysisAddedJitaTask';
const COMPLETE_LOGS_COL_KEY = 'failedAnalysisAddedCompleteLogsPath';
const JIRA_META_COL_KEY = 'failedAnalysisAddedJiraMetaCols';
const FLUX_COL_KEY = 'failedAnalysisAddedFluxQuickFix';

function getStoredVisibleColumns() {
  try {
    const s = localStorage.getItem(STORAGE_KEY);
    if (s) {
      const parsed = JSON.parse(s);
      if (Array.isArray(parsed) && parsed.length > 0) {
        const known = new Set(COLUMNS.map(c => c.id));
        const cols = parsed.filter(id => known.has(id));
        if (!localStorage.getItem(TG_REVIEW_COL_KEY) && !cols.includes('triage_genie_review')) {
          const idx = cols.indexOf('triage_genie_ticket');
          if (idx !== -1) cols.splice(idx + 1, 0, 'triage_genie_review');
          else cols.push('triage_genie_review');
          localStorage.setItem(STORAGE_KEY, JSON.stringify(cols));
        }
        localStorage.setItem(TG_REVIEW_COL_KEY, '1');
        if (!localStorage.getItem(JITA_TASK_COL_KEY) && !cols.includes('jita_task')) {
          const nameIdx = cols.indexOf('testcase_name');
          if (nameIdx !== -1) cols.splice(nameIdx + 1, 0, 'jita_task');
          else cols.unshift('jita_task');
          localStorage.setItem(STORAGE_KEY, JSON.stringify(cols));
        }
        localStorage.setItem(JITA_TASK_COL_KEY, '1');
        if (!localStorage.getItem(COMPLETE_LOGS_COL_KEY) && !cols.includes('complete_logs_path')) {
          const jitaIdx = cols.indexOf('jita_task');
          const nameIdx = cols.indexOf('testcase_name');
          if (jitaIdx !== -1) cols.splice(jitaIdx + 1, 0, 'complete_logs_path');
          else if (nameIdx !== -1) cols.splice(nameIdx + 1, 0, 'complete_logs_path');
          else cols.unshift('complete_logs_path');
          localStorage.setItem(STORAGE_KEY, JSON.stringify(cols));
        }
        localStorage.setItem(COMPLETE_LOGS_COL_KEY, '1');
        if (!localStorage.getItem(JIRA_META_COL_KEY)) {
          const jiraIdx = cols.indexOf('jira_tickets');
          const insertAt = jiraIdx !== -1 ? jiraIdx + 1 : cols.length;
          if (!cols.includes('jira_issue_type')) cols.splice(insertAt, 0, 'jira_issue_type');
          const typeIdx = cols.indexOf('jira_issue_type');
          const statusAt = typeIdx !== -1 ? typeIdx + 1 : insertAt + 1;
          if (!cols.includes('jira_ticket_status')) cols.splice(statusAt, 0, 'jira_ticket_status');
          localStorage.setItem(STORAGE_KEY, JSON.stringify(cols));
        }
        localStorage.setItem(JIRA_META_COL_KEY, '1');
        if (!localStorage.getItem(FLUX_COL_KEY)) {
          const statusIdx = cols.indexOf('jira_ticket_status');
          const typeIdx = cols.indexOf('jira_issue_type');
          const jiraIdx = cols.indexOf('jira_tickets');
          const insertAt = statusIdx !== -1 ? statusIdx + 1
            : typeIdx !== -1 ? typeIdx + 1
            : jiraIdx !== -1 ? jiraIdx + 1
            : cols.length;
          if (!cols.includes('flux_quick_fix')) cols.splice(insertAt, 0, 'flux_quick_fix');
          localStorage.setItem(STORAGE_KEY, JSON.stringify(cols));
        }
        localStorage.setItem(FLUX_COL_KEY, '1');
        return cols.length > 0 ? cols : DEFAULT_VISIBLE;
      }
    }
  } catch (_) {}
  return DEFAULT_VISIBLE;
}

function getIntermittentLabel(r) {
  if (r.intermittent_rerun === 'Yes') return 'Yes';
  if (r.intermittent_rerun === 'No') return 'No';
  return '-';
}

function rdmNeedsNodeDisable(rdm) {
  if (!rdm) return false;
  const action = rdm.next_action || '';
  const cat = (rdm.pattern_category || '').toUpperCase();
  return action === 'disable_node_and_rerun' || cat === 'INFRA_NODE';
}

function rdmNeedsRerun(rdm) {
  const action = (rdm && rdm.next_action) || '';
  return action === 'disable_node_and_rerun' || action === 'rerun';
}

function isSkippedRow(row) {
  const s = ((row && row.status) || '').toLowerCase();
  return s === 'skipped' || s === 'skip';
}

function parseTaskIdsText(text) {
  return (text || '').split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
}

function resolveParentJitaTaskId(rows, inputMode, taskIdsText) {
  if (inputMode === 'task_ids') {
    const ids = parseTaskIdsText(taskIdsText);
    if (ids.length === 1) return ids[0];
  }
  const counts = {};
  (rows || []).forEach((row) => {
    const id = row && row.agave_task_id;
    if (!id) return;
    counts[id] = (counts[id] || 0) + 1;
  });
  const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return ranked.length ? ranked[0][0] : '';
}

function expandSkippedRowsByJitaTask(selectedSkipped, allResults) {
  const selected = (selectedSkipped || []).filter(Boolean);
  const taskIds = new Set(selected.map(r => r.agave_task_id).filter(Boolean));
  if (taskIds.size === 0) return selected;
  const seen = new Set();
  const expanded = [];
  (allResults || []).forEach((row) => {
    if (!isSkippedRow(row) || !row.agave_task_id || !taskIds.has(row.agave_task_id)) return;
    const key = row.testcase_id || `${row.agave_task_id}:${row.testcase_name}`;
    if (seen.has(key)) return;
    seen.add(key);
    expanded.push(row);
  });
  return expanded.length ? expanded : selected;
}

function mapRdmAnalyzeFields(taskRdm) {
  return {
    rdm_found: true,
    rdm_message: taskRdm.rdm_message,
    rdm_link: taskRdm.rdm_link,
    rdm_category: taskRdm.rdm_category,
    rdm_resolution: taskRdm.rdm_resolution,
    failed_deployments: taskRdm.failed_deployments,
    pattern_matched: taskRdm.pattern_matched,
    generated_comment: taskRdm.generated_comment,
    pattern_description: taskRdm.pattern_description,
    pattern_jira: taskRdm.pattern_jira || '',
    pattern_id: taskRdm.pattern_id || '',
    pattern_category: taskRdm.pattern_category || '',
    failed_nodes: taskRdm.failed_nodes || [],
    next_action: taskRdm.next_action || '',
    jita_deployment_id: taskRdm.jita_deployment_id || '',
  };
}

const STATUS_GROUP_MAP = {
  failed: 'Failed', failure: 'Failed',
  skipped: 'Skipped', skip: 'Skipped',
  warning: 'Warning', warn: 'Warning',
  killed: 'Killed', terminated: 'Killed', cancelled: 'Killed',
  pending: 'Pending', waiting: 'Pending', running: 'Pending', started: 'Pending',
};
const ALL_STATUS_GROUPS = ['Failed', 'Skipped', 'Warning', 'Killed', 'Pending'];

function normalizeStatusGroup(status) {
  return STATUS_GROUP_MAP[(status || '').toLowerCase()] || 'Failed';
}

const EMPTY_EXCEPTION_KEY = '__empty__';

function normalizeExceptionSummary(summary) {
  const raw = String(summary || '').replace(/\s+/g, ' ').trim();
  if (!raw) {
    return { key: '', label: '(No exception summary)', preview: '' };
  }
  const normalized = raw
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '<UUID>')
    .replace(/scsi-SNUTANIX_VDISK[A-Za-z0-9_]*/gi, '<DISK>')
    .replace(/\b(?:[0-9a-f]{8}_){3}[0-9a-f]{12}\b/gi, '<HEXID>')
    .replace(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g, '<IP>')
    .replace(/\bF20\d{6}\b/g, '<FDATE>')
    .replace(/\b\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b/g, '<TIME>')
    .replace(/0x[0-9a-f]+/gi, '<PTR>')
    .replace(/Thread-\d+/g, 'Thread-N')
    .replace(/internal_pm_uvm_\d+_\d+/g, 'internal_pm_uvm_*')
    .replace(/test_VM_\d+/g, 'test_VM_*')
    .replace(/\b\d{10,}\b/g, '<ID>')
    .replace(/\s+/g, ' ')
    .trim();
  const key = normalized.slice(0, 200).toLowerCase();
  const label = normalized.length > 160 ? `${normalized.slice(0, 160)}…` : normalized;
  return { key, label, preview: normalized };
}

function buildExceptionGroups(rows) {
  const map = new Map();
  (rows || []).forEach((r) => {
    const meta = normalizeExceptionSummary(r.exception_summary);
    if (!map.has(meta.key)) {
      map.set(meta.key, { key: meta.key, label: meta.label, preview: meta.preview, rows: [] });
    }
    map.get(meta.key).rows.push(r);
  });
  return [...map.values()]
    .map((g) => ({
      ...g,
      rows: [...g.rows].sort((a, b) => (a.testcase_name || '').localeCompare(b.testcase_name || '')),
    }))
    .sort((a, b) => {
      const aEmpty = !a.key;
      const bEmpty = !b.key;
      if (aEmpty !== bEmpty) return aEmpty ? 1 : -1;
      if (b.rows.length !== a.rows.length) return b.rows.length - a.rows.length;
      return a.label.localeCompare(b.label);
    });
}

function isSkippedStatus(status) {
  const s = (status || '').toLowerCase();
  return s === 'skipped' || s === 'skip';
}

function normalizeRdmFailureText(message) {
  const base = normalizeExceptionSummary(message);
  if (!base.key) return base;
  const extra = base.preview
    .replace(/\b[0-9a-f]{24}\b/gi, '<OID>')
    .replace(/\b[a-zA-Z][a-zA-Z0-9]*\d{2,}-\d+\b/g, '<NODE>')
    .replace(/\s+/g, ' ')
    .trim();
  const key = extra.slice(0, 200).toLowerCase();
  const label = extra.length > 160 ? `${extra.slice(0, 160)}…` : extra;
  return { key, label, preview: extra };
}

function rdmGroupMeta(result) {
  if (!isSkippedStatus(result?.status)) return null;
  const rdm = result.rdm_info;
  if (!rdm) return null;
  if (rdm.rdm_found === false) {
    return {
      key: 'rdm:none',
      label: 'RDM: No deployment found',
      preview: '',
      kind: 'rdm',
    };
  }
  if (rdm.pattern_matched && rdm.pattern_id) {
    const desc = rdm.pattern_description || rdm.pattern_id;
    return {
      key: `rdm:pattern:${rdm.pattern_id}`,
      label: `RDM [${rdm.pattern_id}]: ${desc}`,
      preview: rdm.rdm_message || desc,
      kind: 'rdm',
    };
  }
  if (rdm.rdm_message) {
    const meta = normalizeRdmFailureText(rdm.rdm_message);
    return {
      key: `rdm:msg:${meta.key}`,
      label: `RDM: ${meta.label}`,
      preview: rdm.rdm_message,
      kind: 'rdm',
    };
  }
  if (rdm.rdm_link) {
    return {
      key: `rdm:link:${rdm.rdm_link}`,
      label: `RDM: ${rdm.rdm_link}`,
      preview: rdm.rdm_link,
      kind: 'rdm',
    };
  }
  return {
    key: 'rdm:unknown',
    label: 'RDM: Analyzed (no message)',
    preview: '',
    kind: 'rdm',
  };
}

function buildResultGroups(rows) {
  const map = new Map();
  (rows || []).forEach((r) => {
    const rdmMeta = rdmGroupMeta(r);
    const meta = rdmMeta || (() => {
      const e = normalizeExceptionSummary(r.exception_summary);
      return {
        key: `exc:${e.key || EMPTY_EXCEPTION_KEY}`,
        label: e.label,
        preview: e.preview,
        kind: 'exception',
      };
    })();
    if (!map.has(meta.key)) {
      map.set(meta.key, { ...meta, rows: [] });
    }
    map.get(meta.key).rows.push(r);
  });
  return [...map.values()]
    .map((g) => ({
      ...g,
      rows: [...g.rows].sort((a, b) => {
        const aLink = a.rdm_info?.rdm_link || '';
        const bLink = b.rdm_info?.rdm_link || '';
        if (aLink !== bLink) return aLink.localeCompare(bLink);
        return (a.testcase_name || '').localeCompare(b.testcase_name || '');
      }),
    }))
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'rdm' ? -1 : 1;
      if (b.rows.length !== a.rows.length) return b.rows.length - a.rows.length;
      return a.label.localeCompare(b.label);
    });
}

export default function FailedTestcaseAnalysis() {
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [streamPhase, setStreamPhase] = useState('');
  const [totalExpected, setTotalExpected] = useState(0);
  const [tag, setTag] = useState(() => localStorage.getItem('regressionDashboardTag') || 'cdp_master_full_reg');
  const [taskIds, setTaskIds] = useState('');
  const [inputMode, setInputMode] = useState('tag');
  const [results, setResults] = useState([]);
  const [filteredResults, setFilteredResults] = useState([]);
  const [error, setError] = useState(null);
  const [statusMismatch, setStatusMismatch] = useState(null);
  const [visibleColumns, setVisibleColumns] = useState(getStoredVisibleColumns);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [columnCheckboxes, setColumnCheckboxes] = useState(() => {
    const vis = getStoredVisibleColumns();
    return COLUMNS.reduce((acc, c) => ({ ...acc, [c.id]: vis.includes(c.id) }), {});
  });
  const [currentBranch, setCurrentBranch] = useState('');
  const [analysisTag, setAnalysisTag] = useState('');
  const [commentEdits, setCommentEdits] = useState({});
  const [jiraAdd, setJiraAdd] = useState({});
  const [updateLoading, setUpdateLoading] = useState({});
  const [historyCache, setHistoryCache] = useState({});
  const [filterOwner, setFilterOwner] = useState('');
  const [filterFailureStage, setFilterFailureStage] = useState('');
  const [filterIntermittent, setFilterIntermittent] = useState('');
  const [filterComment, setFilterComment] = useState('');
  const [filterException, setFilterException] = useState('');
  const [filterTestStatus, setFilterTestStatus] = useState([...ALL_STATUS_GROUPS]);
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);
  const statusDropdownRef = useRef(null);
  const [jiraTicketDetails, setJiraTicketDetails] = useState({});
  const [filterJiraBugTypes, setFilterJiraBugTypes] = useState([...JIRA_BUG_TYPE_OPTIONS]);
  const [filterJiraStatuses, setFilterJiraStatuses] = useState([]);
  const [jiraTypeDropdownOpen, setJiraTypeDropdownOpen] = useState(false);
  const [jiraStatusDropdownOpen, setJiraStatusDropdownOpen] = useState(false);
  const jiraTypeDropdownRef = useRef(null);
  const jiraStatusDropdownRef = useRef(null);
  const jiraStatusTouchedRef = useRef(false);
  const jiraFetchPendingRef = useRef(new Set());
  const [selectedStatuses, setSelectedStatuses] = useState(['failed']);
  const [selectedRows, setSelectedRows] = useState([]);
  const [bulkJiraTicket, setBulkJiraTicket] = useState('');
  const [bulkComment, setBulkComment] = useState('');
  const [bulkUpdating, setBulkUpdating] = useState(false);
  const selectAllCheckboxRef = useRef(null);

  // Cursor AI deep analysis state
  const [cursorAiLoading, setCursorAiLoading] = useState({});
  const [cursorAiResults, setCursorAiResults] = useState({});
  const [cursorAiDetailModal, setCursorAiDetailModal] = useState(null);
  const [cursorAiBatchJobId, setCursorAiBatchJobId] = useState(null);
  const [cursorAiBatchStatus, setCursorAiBatchStatus] = useState(null);
  const [cursorAiSessions, setCursorAiSessions] = useState({});
  const [cursorAiOpenTabs, setCursorAiOpenTabs] = useState([]);
  const [cursorAiMinimizedTabs, setCursorAiMinimizedTabs] = useState({});
  const [followUpInput, setFollowUpInput] = useState('');
  const [followUpLoading, setFollowUpLoading] = useState(false);
  const [followUpHistory, setFollowUpHistory] = useState([]);
  const [followUpHistoryByTestcase, setFollowUpHistoryByTestcase] = useState({});
  // Ask is the fast path (answer from existing analysis; minimal/no MCP).
  // Use Agent/Plan only when the user wants deeper re-investigation.
  const [followUpMode, setFollowUpMode] = useState('ask');
  // Deep AI chat action tags: create ENG (optional details) / Flux Quick Fix
  const [deepAiActionTag, setDeepAiActionTag] = useState(null); // 'create_eng' | 'flux' | null
  const [engDetailsOpen, setEngDetailsOpen] = useState(false);
  const [engDetailsForm, setEngDetailsForm] = useState({
    summary: '',
    primary_component: '',
    affects_version: '',
    fix_version: 'Triage',
    test_type: '',
    issue_type: '',
    additional_details: '',
  });
  const [engCreateLoading, setEngCreateLoading] = useState(false);
  const [deepAiFluxForm, setDeepAiFluxForm] = useState({
    branch: '',
    loading: false,
    error: null,
    taskId: '',
    starting: false,
  });

  // Retrigger state
  const [retriggerModalOpen, setRetriggerModalOpen] = useState(false);
  const [retriggerLoading, setRetriggerLoading] = useState(false);
  const RETRIGGER_DEFAULTS = {
    updateNos: false,
    nos: { branch: '', commitId: '', gbn: '' },
    updatePc: false,
    pc: { branch: '', commitId: '', gbn: '', buildUrl: '', qcow2Url: '' },
    updateImage: false,
    image: { branch: '', commitId: '', gbn: '' },
    updateFramework: false,
    nutest_branch: '',
    patch_url: '',
    framework_patch_url: '',
    overridePool: false,
    resource_pool: '',
    updateResource: false,
    overrideResource: false,
    resources_mode: 'node_pool',
    resource_type: 'physical',
    hypervisor: '',
    node_pools: [],
    match_resource_spec: true,
    label: '',
    priority: '',
    tester_tags: '',
    overrideScheduling: false,
    skip_resource_spec_match: false,
    check_image_compatibility: true,
    syncToTcms: true,  // Default to sync to TCMS
  };
  const [retriggerOverrides, setRetriggerOverrides] = useState({ ...RETRIGGER_DEFAULTS });
  const [retriggerResults, setRetriggerResults] = useState(null);
  const [retriggerCopied, setRetriggerCopied] = useState('');
  const [retriggerResourcePreview, setRetriggerResourcePreview] = useState({ loading: false, tasks: [] });
  const [nodePoolSearch, setNodePoolSearch] = useState('');
  const [nodePoolResults, setNodePoolResults] = useState([]);
  const [nodePoolLoading, setNodePoolLoading] = useState(false);
  const nodePoolDebounce = useRef(null);
  const nodePoolReqId = useRef(0);

  // Per-row AI summary state
  const [aiSummaryLoading, setAiSummaryLoading] = useState({});

  // Per-row Glean search state
  const [gleanSearchLoading, setGleanSearchLoading] = useState({});
  const [gleanSearchResults, setGleanSearchResults] = useState({});
  const [gleanDetailModal, setGleanDetailModal] = useState(null);

  // RDM analysis state
  const [rdmAnalyzing, setRdmAnalyzing] = useState(false);
  const [rdmAiLoading, setRdmAiLoading] = useState({});
  const [rdmAiResults, setRdmAiResults] = useState({});
  const [rdmSkillLoading, setRdmSkillLoading] = useState({});
  const [rdmSkillResults, setRdmSkillResults] = useState({});
  const [rdmWorkflowLoading, setRdmWorkflowLoading] = useState({});
  const [patternModal, setPatternModal] = useState(null);
  const [patternSaving, setPatternSaving] = useState(false);

  // Intelligent Triage state
  const [intelligentTriageResults, setIntelligentTriageResults] = useState({});
  const [intelligentTriageByTestcase, setIntelligentTriageByTestcase] = useState({});
  const [gleanAiValidating, setGleanAiValidating] = useState({});
  const [firstLevelAiLoading, setFirstLevelAiLoading] = useState({});
  const [firstLevelAiResults, setFirstLevelAiResults] = useState({});
  const [deepAiLoading, setDeepAiLoading] = useState({});
  const [deepAiResults, setDeepAiResults] = useState({});
  const [triageAnalysisModal, setTriageAnalysisModal] = useState(null);

  // Auto Test Fix state 
  const [autoTestFixLoading, setAutoTestFixLoading] = useState({});
  const [autoTestFixResults, setAutoTestFixResults] = useState({});
  const [crApprovalLoading, setCrApprovalLoading] = useState({});

  // Flux Quick Fix per-row jobs
  const [fluxJobs, setFluxJobs] = useState({});
  const fluxJobsRef = useRef({});
  const fluxResumeInFlight = useRef({});
  const [fluxBranchPrompt, setFluxBranchPrompt] = useState(null);

  // Saved tags management
  const [savedTags, setSavedTags] = useState([]);
  const [selectedSavedTag, setSelectedSavedTag] = useState('');
  const [newTagInput, setNewTagInput] = useState('');
  const [savingResults, setSavingResults] = useState(false);
  const [tagPickerOpen, setTagPickerOpen] = useState(false);
  const tagPickerRef = useRef(null);

  const toggleStatus = (statusId) => {
    setSelectedStatuses(prev =>
      prev.includes(statusId)
        ? prev.filter(s => s !== statusId)
        : [...prev, statusId]
    );
  };

  const toggleFilterTestStatus = (group) => {
    setFilterTestStatus(prev =>
      prev.includes(group) ? prev.filter(g => g !== group) : [...prev, group]
    );
  };

  const toggleFilterJiraBugType = (type) => {
    setFilterJiraBugTypes(prev =>
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    );
  };

  const toggleFilterJiraStatus = (status) => {
    jiraStatusTouchedRef.current = true;
    setFilterJiraStatuses(prev =>
      prev.includes(status) ? prev.filter(s => s !== status) : [...prev, status]
    );
  };

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e) => {
      if (statusDropdownRef.current && !statusDropdownRef.current.contains(e.target)) {
        setStatusDropdownOpen(false);
      }
      if (jiraTypeDropdownRef.current && !jiraTypeDropdownRef.current.contains(e.target)) {
        setJiraTypeDropdownOpen(false);
      }
      if (jiraStatusDropdownRef.current && !jiraStatusDropdownRef.current.contains(e.target)) {
        setJiraStatusDropdownOpen(false);
      }
      if (tagPickerRef.current && !tagPickerRef.current.contains(e.target)) {
        setTagPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Fetch saved tags on mount (team + legacy failed_analysis_saved_tags.json)
  useEffect(() => {
    const fetchSavedTags = async () => {
      try {
        const { data } = await api.get(`${API_BASE}/saved-tags`);
        setSavedTags(data.tags || []);
      } catch (err) {
        console.warn('Failed to load saved tags', err);
        setSavedTags([]);
      }
    };
    fetchSavedTags();
  }, []);

  const handleAddTag = async () => {
    const name = newTagInput.trim();
    if (!name) return;
    try {
      const { data } = await api.post(`${API_BASE}/saved-tags`, { tag: name });
      if (data.success) {
        setSavedTags(data.tags || []);
        setNewTagInput('');
        setTag(name);
        setSelectedSavedTag(name);
        setInputMode('tag');
      }
    } catch (err) {
      alert(err.response?.data?.error || 'Failed to add tag');
    }
  };

  const handleDeleteTag = async (tagName) => {
    if (!window.confirm(`Remove "${tagName}" and its cached analysis and triage accuracy files?`)) return;
    try {
      const { data } = await api.delete(`${API_BASE}/saved-tags/${encodeURIComponent(tagName)}`);
      if (data.success) {
        setSavedTags(data.tags || []);
        if (selectedSavedTag === tagName) {
          setSelectedSavedTag('');
          setResults([]);
          setFilteredResults([]);
        }
      }
    } catch (err) {
      alert(err.response?.data?.error || 'Failed to remove tag');
    }
  };

  const hydrateIntelligentTriageFromMap = (itMap) => {
    const flHydrate = {};
    const deepHydrate = {};
    const triageOpen = {};
    Object.entries(itMap || {}).forEach(([tid, analysis]) => {
      if (!analysis) return;
      triageOpen[tid] = { analysis_type: 'ready', requires_first_level_ai: true, requires_deep_ai_analysis: true };
      if (analysis.triage_analysis || analysis.decision) {
        flHydrate[tid] = {
          success: true,
          cached: true,
          analysis_type: 'first_level_ai',
          issue_type: analysis.triage_analysis?.issue_type,
          analysis: analysis.triage_analysis?.summary,
          recommended_action: analysis.triage_analysis?.recommended_action,
          best_matching_ticket: analysis.triage_analysis?.best_matching_ticket,
          triage_confidence: analysis.triage_analysis?.triage_confidence,
          intermittent_confidence: analysis.intermittent_analysis?.intermittent_confidence,
          tg_ticket_validation: analysis.triage_genie?.ai_validation
            ? { ...analysis.triage_genie.ai_validation, ticket: analysis.triage_genie?.original?.ticket }
            : null,
          enriched_tickets: analysis.glean_candidates?.search?.candidates || [],
          glean_snippets: analysis.glean_candidates?.search?.snippets || [],
          search_source: analysis.glean_candidates?.search?.search_source,
          glean_ok: analysis.glean_candidates?.search?.mcp_health?.ok,
          mcp_health: analysis.mcp_health,
          decision: analysis.decision,
          intelligent_triage: analysis,
        };
      }
      if (analysis.deep_ai?.status && analysis.deep_ai.status !== 'not_run') {
        deepHydrate[tid] = {
          success: true,
          cached: true,
          session_id: analysis.deep_ai.session_id,
          root_cause: analysis.deep_ai.root_cause,
          classification: analysis.deep_ai.classification,
          confidence: analysis.deep_ai.confidence,
          skill_used: analysis.deep_ai.skill_used,
          suggested_fix: analysis.deep_ai.suggested_fix,
          failing_code: analysis.deep_ai.failing_code,
          related_components: analysis.deep_ai.related_components,
          jira_duplicates: analysis.deep_ai.jira_duplicates,
          triage_report: analysis.deep_ai.triage_report,
          mcp_health: analysis.deep_ai.mcp_health || analysis.mcp_health,
          intelligent_triage: analysis,
        };
      }
    });
    return { flHydrate, deepHydrate, triageOpen };
  };

  const handleSelectSavedTag = async (tagName) => {
    setSelectedSavedTag(tagName);
    if (!tagName) return;
    setTag(tagName);
    setInputMode('tag');
    setError(null);
    setSelectedRows([]);
    setHistoryCache({});
    setFilterOwner('');
    setFilterFailureStage('');
    setFilterIntermittent('');
    setFilterComment('');
    setFilterException('');
    setFilterJiraBugTypes([...JIRA_BUG_TYPE_OPTIONS]);
    setFilterJiraStatuses([]);
    jiraStatusTouchedRef.current = false;
    setJiraTicketDetails({});
    jiraFetchPendingRef.current = new Set();
    try {
      setLoading(true);
      const { data } = await api.get(`${API_BASE}/saved-tags/${encodeURIComponent(tagName)}/results`);
      const cached = data.results || [];
      setResults(cached);
      setCurrentBranch(data.current_branch || '');
      setAnalysisTag(tagName);
      const cursorAi = data.cursor_ai || {};
      setCursorAiResults(cursorAi.results || {});
      setCursorAiSessions(cursorAi.sessions || {});
      setFollowUpHistoryByTestcase(cursorAi.follow_up_history_by_testcase || {});
      const itMap = data.intelligent_triage || {};
      setIntelligentTriageByTestcase(itMap);
      const { flHydrate, deepHydrate, triageOpen } = hydrateIntelligentTriageFromMap(itMap);
      // Replace (do not merge) so switching tags does not keep stale analyses.
      setIntelligentTriageResults(triageOpen);
      setFirstLevelAiResults(flHydrate);
      setDeepAiResults(deepHydrate);
    } catch (_) {
      setResults([]);
      setCursorAiResults({});
      setCursorAiSessions({});
      setFollowUpHistoryByTestcase({});
      setIntelligentTriageByTestcase({});
      setIntelligentTriageResults({});
      setFirstLevelAiResults({});
      setDeepAiResults({});
    } finally {
      setLoading(false);
    }
  };

  const saveResultsForTag = useCallback(async (tagName, rows, branch, cursorAiState = null, intelligentTriageState = null) => {
    if (!tagName) return;
    setSavingResults(true);
    try {
      await api.put(`${API_BASE}/saved-tags/${encodeURIComponent(tagName)}/results`, {
        results: rows,
        current_branch: branch,
        ...(cursorAiState ? { cursor_ai: cursorAiState } : {}),
        ...(intelligentTriageState ? { intelligent_triage: intelligentTriageState } : {}),
      });
    } catch (_) {}
    setSavingResults(false);
  }, []);

  useEffect(() => {
    if (inputMode !== 'tag' || !analysisTag) return;
    if (
      results.length === 0
      && Object.keys(cursorAiResults).length === 0
      && Object.keys(followUpHistoryByTestcase).length === 0
      && Object.keys(intelligentTriageByTestcase).length === 0
    ) return;
    saveResultsForTag(
      analysisTag,
      results,
      currentBranch,
      {
        results: cursorAiResults,
        sessions: cursorAiSessions,
        follow_up_history_by_testcase: followUpHistoryByTestcase,
      },
      intelligentTriageByTestcase,
    );
  }, [inputMode, analysisTag, results, currentBranch, cursorAiResults, cursorAiSessions, followUpHistoryByTestcase, intelligentTriageByTestcase, saveResultsForTag]);

  const buildIncludeParam = useCallback((cols) => {
    const include = new Set(['basic', 'exception_summary', 'intermittent']);
    if (cols.includes('issue_type')) include.add('issue_type');
    if (cols.includes('suggestion_by_ai_agent')) include.add('suggestion');
    if (cols.includes('triage_genie_ticket')) include.add('triage_genie_ticket');
    if (cols.includes('ai_summary')) include.add('ai_summary');
    return Array.from(include).join(',');
  }, []);

  const handleAnalyze = async (statusOverride = null) => {
    const statuses = (Array.isArray(statusOverride) && statusOverride.length)
      ? statusOverride
      : selectedStatuses;
    const parsedTaskIds = inputMode === 'task_ids' ? extractJitaTaskIds(taskIds) : [];
    if (inputMode === 'task_ids') {
      if (!parsedTaskIds.length) {
        alert('Please provide valid JITA task IDs (24-char hex) or a JITA results URL');
        return;
      }
    } else if (!tag.trim()) {
      alert('Please provide either a tag or task IDs');
      return;
    }
    if (statuses.length === 0) {
      alert('Please select at least one test status');
      return;
    }
    if (Array.isArray(statusOverride) && statusOverride.length) {
      setSelectedStatuses(statusOverride);
    }
    setAnalyzing(true);
    setStreamPhase('preparing');
    setTotalExpected(0);
    setError(null);
    setStatusMismatch(null);
    setResults([]);
    setFilteredResults([]);
    setFilterOwner('');
    setFilterFailureStage('');
    setFilterIntermittent('');
    setFilterComment('');
    setFilterException('');
    setFilterJiraBugTypes([...JIRA_BUG_TYPE_OPTIONS]);
    setFilterJiraStatuses([]);
    jiraStatusTouchedRef.current = false;
    setJiraTicketDetails({});
    jiraFetchPendingRef.current = new Set();
    setSelectedRows([]);
    setHistoryCache({});
    const include = buildIncludeParam(visibleColumns);
    const searchParams = new URLSearchParams({ include });
    const isTagMode = inputMode === 'tag' && tag.trim();
    // Keep prior First Level / Deep AI maps across re-analyze; backend merges by testcase_id.
    // Do NOT wipe saved results_<tag>.json before streaming (that shadowed legacy caches).
    if (isTagMode) {
      searchParams.set('tag', tag.trim());
    } else if (inputMode === 'task_ids' && parsedTaskIds.length) {
      searchParams.set('task_ids', parsedTaskIds.join(','));
    }
    searchParams.set('statuses', statuses.join(','));
    const url = `${API_BASE}/analyze-stream?${searchParams.toString()}`;

    const collectedRows = [];
    let branch = '';

    try {
      const token = localStorage.getItem('regx_auth_token');
      const response = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        setError(errData.error || `Request failed: ${response.status}`);
        setAnalyzing(false);
        setStreamPhase('');
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              if (event.type === 'progress') {
                setStreamPhase(event.phase || 'preparing');
              } else if (event.type === 'start') {
                branch = event.current_branch || '';
                setCurrentBranch(branch);
                setAnalysisTag(event.tag ?? '');
                setTotalExpected(event.total || 0);
                setStreamPhase('streaming');
                if (event.total === 0) {
                  setAnalyzing(false);
                  setStreamPhase('');
                  const counts = event.status_counts || {};
                  const summary = formatStatusCountSummary(counts);
                  const optionIds = [...new Set(
                    Object.keys(counts).map(optionIdForRawStatus).filter(Boolean)
                  )];
                  if ((event.fetched_total || 0) > 0 && summary) {
                    setStatusMismatch({
                      counts,
                      optionIds,
                      fetchedTotal: event.fetched_total,
                      taskCount: event.task_count,
                    });
                    setError(
                      `No testcases matched the selected status filter. ` +
                      `Fetched ${event.fetched_total} result(s)` +
                      (event.task_count ? ` from ${event.task_count} task(s)` : '') +
                      `: ${summary}. Select those statuses and analyze again.`
                    );
                  } else {
                    setStatusMismatch(null);
                    setError('No testcases found for the given criteria and selected statuses.');
                  }
                }
              } else if (event.type === 'row' && event.result) {
                collectedRows.push(event.result);
                setResults(prev => [...prev, event.result]);
              } else if (event.type === 'done') {
                setAnalyzing(false);
                setStreamPhase('');
              } else if (event.type === 'error') {
                setError(event.message || 'Analysis failed');
                setAnalyzing(false);
                setStreamPhase('');
              }
            } catch (e) {
              // skip malformed lines
            }
          }
        }
      }
      if (buffer.trim()) {
        try {
          const line = buffer.trim();
          if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'row' && event.result) {
              collectedRows.push(event.result);
              setResults(prev => [...prev, event.result]);
            } else if (event.type === 'done') {
              setAnalyzing(false);
              setStreamPhase('');
            } else if (event.type === 'error') {
              setError(event.message || 'Analysis failed');
              setAnalyzing(false);
              setStreamPhase('');
            }
          }
        } catch (_) {}
      }
      setAnalyzing(false);
      setStreamPhase('');

      // Auto-save results for tag mode if the tag is in the saved tags list.
      // Preserve intelligent_triage / cursor AI already in React state (and on disk via server merge).
      if (isTagMode && collectedRows.length > 0) {
        const tagName = tag.trim();
        const tagEntry = savedTags.find(t => (typeof t === 'string' ? t : t.name) === tagName);
        if (tagEntry) {
          await saveResultsForTag(
            tagName,
            collectedRows,
            branch,
            {
              results: cursorAiResults,
              sessions: cursorAiSessions,
              follow_up_history_by_testcase: followUpHistoryByTestcase,
            },
            intelligentTriageByTestcase,
          );
          // Re-load from disk so First Level / Deep AI for matching testcase_ids stay hydrated.
          try {
            const { data } = await api.get(`${API_BASE}/saved-tags/${encodeURIComponent(tagName)}/results`);
            const itMap = data.intelligent_triage || intelligentTriageByTestcase || {};
            setIntelligentTriageByTestcase(itMap);
            const { flHydrate, deepHydrate, triageOpen } = hydrateIntelligentTriageFromMap(itMap);
            setIntelligentTriageResults(prev => ({ ...prev, ...triageOpen }));
            setFirstLevelAiResults(prev => ({ ...prev, ...flHydrate }));
            setDeepAiResults(prev => ({ ...prev, ...deepHydrate }));
            if (data.cursor_ai) {
              setCursorAiResults(data.cursor_ai.results || cursorAiResults);
              setCursorAiSessions(data.cursor_ai.sessions || cursorAiSessions);
              setFollowUpHistoryByTestcase(
                data.cursor_ai.follow_up_history_by_testcase || followUpHistoryByTestcase
              );
            }
          } catch (_) {}
        }
      }
    } catch (err) {
      console.error('Error analyzing testcases:', err);
      const errorMessage = err.message || 'Failed to analyze testcases';
      if (errorMessage.includes('Failed to fetch') || errorMessage.includes('NetworkError')) {
        setError(`Network Error: ${errorMessage}. Please check your network connection and ensure you can access the server.`);
      } else {
        setError(errorMessage);
      }
      setAnalyzing(false);
      setStreamPhase('');
    }
  };

  const getIssueTypeBadge = (issueType) => {
    if (issueType === 'Test Issue') return <span className="badge badge-test-issue">Test Issue</span>;
    if (issueType === 'Product Issue') return <span className="badge badge-product-issue">Product Issue</span>;
    if (issueType === 'Unknown / Needs Manual Review') return <span className="badge badge-unknown-issue">Unknown / Needs Review</span>;
    return <span className="badge badge-unknown">-</span>;
  };

  const getFailureStageBadge = (stage) => {
    const stageColors = { 'Test Body': 'stage-test-body', 'Test Setup': 'stage-setup', 'Teardown': 'stage-teardown', 'Infra': 'stage-infra' };
    return <span className={`badge ${stageColors[stage] || 'stage-unknown'}`}>{stage || 'Unknown'}</span>;
  };

  const handleCustomizeDone = () => {
    const selected = COLUMNS.filter(c => columnCheckboxes[c.id]).map(c => c.id);
    if (selected.length === 0) return;
    setVisibleColumns(selected);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(selected));
    } catch (_) {}
    setCustomizeOpen(false);
  };

  const openCustomize = () => {
    setColumnCheckboxes(COLUMNS.reduce((acc, c) => ({ ...acc, [c.id]: visibleColumns.includes(c.id) }), {}));
    setCustomizeOpen(true);
  };

  useEffect(() => {
    const tickets = [...new Set(results.flatMap(r => collectResultJiraTickets(r)))];
    const missing = tickets.filter(t => !(t in jiraTicketDetails) && !jiraFetchPendingRef.current.has(t));
    if (!missing.length) return undefined;
    const delay = analyzing ? 700 : 80;
    const timer = setTimeout(() => {
      missing.forEach(t => jiraFetchPendingRef.current.add(t));
      api.post(`${API_BASE_URL}/mcp/regression/jira-ticket-details`, { ticket_ids: missing }, { timeout: 120000 })
        .then((resp) => {
          const details = (resp.data && resp.data.success && resp.data.details) ? resp.data.details : {};
          setJiraTicketDetails(prev => {
            const next = { ...prev, ...details };
            missing.forEach(t => {
              if (!next[t]) next[t] = { status: 'N/A', issue_type: 'N/A', bug_type: null };
            });
            return next;
          });
        })
        .catch(() => {
          setJiraTicketDetails(prev => {
            const next = { ...prev };
            missing.forEach(t => {
              if (!next[t]) next[t] = { status: 'N/A', issue_type: 'N/A', bug_type: null };
            });
            return next;
          });
        })
        .finally(() => {
          missing.forEach(t => jiraFetchPendingRef.current.delete(t));
        });
    }, delay);
    return () => clearTimeout(timer);
  }, [results, analyzing, jiraTicketDetails]);

  const uniqueJiraStatuses = (() => {
    const statusSet = new Set();
    let hasNoTicket = false;
    results.forEach(r => {
      const tickets = collectResultJiraTickets(r);
      if (!tickets.length) {
        hasNoTicket = true;
        return;
      }
      tickets.forEach(t => {
        const st = jiraTicketDetails[t]?.status;
        if (!jiraTicketDetails[t]) return;
        if (!st || st === 'N/A') statusSet.add('Unknown');
        else statusSet.add(st);
      });
    });
    const list = [...statusSet].sort((a, b) => a.localeCompare(b));
    if (hasNoTicket) list.push(NO_JIRA_TICKET);
    return list;
  })();

  useEffect(() => {
    if (jiraStatusTouchedRef.current) {
      setFilterJiraStatuses(prev => prev.filter(s => uniqueJiraStatuses.includes(s)));
      return;
    }
    setFilterJiraStatuses([...uniqueJiraStatuses]);
  }, [uniqueJiraStatuses.join('|')]);

  useEffect(() => {
    let filtered = [...results];
    if (filterTestStatus.length < ALL_STATUS_GROUPS.length) {
      filtered = filtered.filter(r => filterTestStatus.includes(normalizeStatusGroup(r.status)));
    }
    if (filterOwner) filtered = filtered.filter(r => r.regression_owner && r.regression_owner.toLowerCase().includes(filterOwner.toLowerCase()));
    if (filterFailureStage) filtered = filtered.filter(r => r.failure_stage === filterFailureStage);
    if (filterIntermittent) filtered = filtered.filter(r => getIntermittentLabel(r) === filterIntermittent);
    if (filterComment.trim()) {
      const q = filterComment.trim().toLowerCase();
      filtered = filtered.filter(r => {
        const id = r.testcase_id;
        const text = id != null && commentEdits[id] !== undefined
          ? String(commentEdits[id])
          : String(r.comments || '');
        return text.toLowerCase().includes(q);
      });
    }
    if (filterException) {
      const want = filterException === EMPTY_EXCEPTION_KEY ? '' : filterException;
      filtered = filtered.filter(r => normalizeExceptionSummary(r.exception_summary).key === want);
    }
    if (filterJiraBugTypes.length !== JIRA_BUG_TYPE_OPTIONS.length) {
      filtered = filtered.filter(r => resultMatchesJiraBugTypes(r, jiraTicketDetails, filterJiraBugTypes));
    }
    if (filterJiraStatuses.length > 0 && filterJiraStatuses.length < uniqueJiraStatuses.length) {
      filtered = filtered.filter(r => resultMatchesJiraStatuses(r, jiraTicketDetails, filterJiraStatuses));
    } else if (filterJiraStatuses.length === 0 && uniqueJiraStatuses.length > 0 && jiraStatusTouchedRef.current) {
      filtered = [];
    }
    setFilteredResults(filtered);
  }, [results, filterTestStatus, filterOwner, filterFailureStage, filterIntermittent, filterComment, filterException, commentEdits, filterJiraBugTypes, filterJiraStatuses, jiraTicketDetails, uniqueJiraStatuses]);

  const uniqueOwners = [...new Set(results.map(r => r.regression_owner).filter(Boolean))].sort();
  const uniqueFailureStages = [...new Set(results.map(r => r.failure_stage).filter(Boolean))].sort();
  const uniqueExceptionGroups = buildExceptionGroups(results).map(g => ({
    key: g.key,
    label: g.label,
    count: g.rows.length,
  }));
  const resultGroups = buildResultGroups(filteredResults);
  const rdmGroupCount = resultGroups.filter(g => g.kind === 'rdm').length;
  const exceptionGroupCount = resultGroups.filter(g => g.kind !== 'rdm').length;
  const uniqueIntermittent = [...new Set(results.map(r => getIntermittentLabel(r)))].sort((a, b) => {
    const order = { Yes: 0, No: 1, '-': 2 };
    return (order[a] ?? 99) - (order[b] ?? 99);
  });

  const fetchHistory = useCallback(async (testName, sameBranch) => {
    if (!analysisTag || testName == null) return null;
    const key = `${testName}|${sameBranch}`;
    if (historyCache[key]) return historyCache[key];
    try {
      const { data } = await api.get(`${API_BASE}/history`, {
        params: { test_name: testName, branch: currentBranch, same_branch: sameBranch, tag: analysisTag }
      });
      const runs = data.runs || [];
      setHistoryCache(prev => ({ ...prev, [key]: runs }));
      return runs;
    } catch (_) {
      return [];
    }
  }, [analysisTag, currentBranch, historyCache]);

  const applyTriageUpdate = async (testId, comment, jiraTickets) => {
    const { data } = await api.put(`${API_BASE}/update-triage`, {
      test_id: testId,
      comment: comment || '',
      jira_tickets: jiraTickets || []
    });
    return !!data.success;
  };

  const handleUpdateJita = async (result) => {
    const testId = result.testcase_id;
    if (!testId) return;
    const comment = commentEdits[testId] !== undefined ? commentEdits[testId] : (result.comments || '');
    const existing = result.jira_tickets || [];
    const added = (jiraAdd[testId] || '').trim();
    const merged = added
      ? [...new Set([...existing, added])]
      : existing;
    setUpdateLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const success = await applyTriageUpdate(testId, comment, merged);
      if (success) {
        setResults(prev => prev.map(r => r.testcase_id === testId
          ? { ...r, comments: comment || r.comments, jira_tickets: merged }
          : r));
        setCommentEdits(prev => { const n = { ...prev }; delete n[testId]; return n; });
        setJiraAdd(prev => { const n = { ...prev }; delete n[testId]; return n; });
      }
    } catch (err) {
      console.error('Update Jita failed:', err);
      alert(err.response?.data?.error || 'Failed to update Jita');
    } finally {
      setUpdateLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const toggleRowSelect = (testId) => {
    if (!testId) return;
    setSelectedRows(prev => (prev.includes(testId) ? prev.filter(id => id !== testId) : [...prev, testId]));
  };

  const toggleSelectAllVisible = () => {
    const visibleIds = filteredResults.map(r => r.testcase_id).filter(Boolean);
    if (visibleIds.length === 0) return;
    const allSelected = visibleIds.every(id => selectedRows.includes(id));
    if (allSelected) {
      setSelectedRows(prev => prev.filter(id => !visibleIds.includes(id)));
    } else {
      setSelectedRows(prev => [...new Set([...prev, ...visibleIds])]);
    }
  };

  const toggleSelectGroup = (groupIds) => {
    const ids = (groupIds || []).filter(Boolean);
    if (ids.length === 0) return;
    const allSelected = ids.every(id => selectedRows.includes(id));
    if (allSelected) {
      setSelectedRows(prev => prev.filter(id => !ids.includes(id)));
    } else {
      setSelectedRows(prev => [...new Set([...prev, ...ids])]);
    }
  };

  useEffect(() => {
    const el = selectAllCheckboxRef.current;
    if (!el) return;
    const visibleIds = filteredResults.map(r => r.testcase_id).filter(Boolean);
    const count = visibleIds.filter(id => selectedRows.includes(id)).length;
    el.indeterminate = count > 0 && count < visibleIds.length;
  }, [filteredResults, selectedRows]);

  const handleBulkUpdate = async () => {
    const ids = selectedRows.filter(Boolean);
    if (ids.length === 0) {
      alert('Select at least one row.');
      return;
    }
    const jira = bulkJiraTicket.trim();
    const comment = bulkComment || '';
    setBulkUpdating(true);
    let ok = 0;
    let fail = 0;
    try {
      for (const testId of ids) {
        try {
          const row = results.find(r => r.testcase_id === testId);
          const existing = row?.jira_tickets || [];
          const tickets = jira ? [...new Set([...existing, jira])] : existing;
          const success = await applyTriageUpdate(testId, comment, tickets);
          if (success) {
            ok++;
            setResults(prev => prev.map(r => {
              if (r.testcase_id !== testId) return r;
              return {
                ...r,
                comments: comment || r.comments,
                jira_tickets: tickets
              };
            }));
            setCommentEdits(prev => { const n = { ...prev }; delete n[testId]; return n; });
            setJiraAdd(prev => { const n = { ...prev }; delete n[testId]; return n; });
          } else {
            fail++;
          }
        } catch {
          fail++;
        }
      }
      if (fail > 0) {
        alert(`Bulk update finished: ${ok} succeeded, ${fail} failed.`);
      } else if (ok > 0) {
        alert(`Updated ${ok} testcase(s).`);
      }
    } finally {
      setBulkUpdating(false);
    }
  };

  // --------------- Cursor AI Deep Analysis handlers ---------------

  const handleCursorAiAnalyze = async (result) => {
    const testId = result.testcase_id;
    if (!testId) return;
    setCursorAiLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const glean = gleanSearchResults[testId] || firstLevelAiResults[testId] || {};
      const resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/analyze-testcase`, {
        testcase_id: testId,
        testcase_name: result.testcase_name,
        status: result.status,
        exception_summary: result.exception_summary,
        exception: result.exception,
        test_log_url: result.test_log_url,
        jira_tickets: result.jira_tickets || [],
        failure_stage: result.failure_stage,
        triage_genie_ticket: tgTicketFromResult(result),
        glean_tickets: glean.enriched_tickets || [],
        glean_snippets: glean.glean_snippets || [],
      });
      if (resp.data?.success) {
        setCursorAiResults(prev => ({ ...prev, [testId]: resp.data.analysis }));
        if (resp.data.session_id) {
          setCursorAiSessions(prev => ({ ...prev, [testId]: resp.data.session_id }));
        }
      } else {
        setCursorAiResults(prev => ({ ...prev, [testId]: { error: resp.data?.error || 'Analysis failed' } }));
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Cursor AI analysis failed';
      setCursorAiResults(prev => ({ ...prev, [testId]: { error: msg } }));
    } finally {
      setCursorAiLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const handleCursorAiBatchAnalyze = async () => {
    const ids = selectedRows.filter(Boolean);
    if (ids.length === 0) { alert('Select at least one row.'); return; }

    const testcases = ids.map(id => {
      const r = results.find(row => row.testcase_id === id);
      if (!r) return null;
      return {
        testcase_id: r.testcase_id,
        testcase_name: r.testcase_name,
        exception_summary: r.exception_summary,
        exception: r.exception,
        test_log_url: r.test_log_url,
        jira_tickets: r.jira_tickets || [],
        failure_stage: r.failure_stage,
      };
    }).filter(Boolean);

    ids.forEach(id => setCursorAiLoading(prev => ({ ...prev, [id]: true })));
    setCursorAiBatchStatus({ total: testcases.length, completed: 0, status: 'running' });

    try {
      const resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/analyze-batch`, { testcases });
      if (resp.data?.success && resp.data.job_id) {
        setCursorAiBatchJobId(resp.data.job_id);
        pollBatchJob(resp.data.job_id, ids);
      } else {
        ids.forEach(id => setCursorAiLoading(prev => ({ ...prev, [id]: false })));
        setCursorAiBatchStatus(null);
        alert(resp.data?.error || 'Batch analysis failed to start');
      }
    } catch (err) {
      ids.forEach(id => setCursorAiLoading(prev => ({ ...prev, [id]: false })));
      setCursorAiBatchStatus(null);
      alert(err.response?.data?.error || 'Failed to start batch analysis');
    }
  };

  const pollBatchJob = async (jobId, testIds) => {
    const poll = async () => {
      try {
        const resp = await api.get(`${API_BASE_URL}/mcp/regression/cursor-ai/status/${jobId}`);
        const data = resp.data;
        setCursorAiBatchStatus({ total: data.total, completed: data.completed, status: data.status });

        if (data.results) {
          Object.entries(data.results).forEach(([key, val]) => {
            if (val.success) {
              setCursorAiResults(prev => ({ ...prev, [key]: val.analysis }));
              if (val.session_id) {
                setCursorAiSessions(prev => ({ ...prev, [key]: val.session_id }));
              }
              setCursorAiLoading(prev => ({ ...prev, [key]: false }));
            } else {
              setCursorAiResults(prev => ({ ...prev, [key]: { error: val.error || 'Failed' } }));
              setCursorAiLoading(prev => ({ ...prev, [key]: false }));
            }
          });
        }

        if (data.status !== 'done') {
          setTimeout(poll, 5000);
        } else {
          testIds.forEach(id => setCursorAiLoading(prev => ({ ...prev, [id]: false })));
          setCursorAiBatchJobId(null);
        }
      } catch {
        testIds.forEach(id => setCursorAiLoading(prev => ({ ...prev, [id]: false })));
        setCursorAiBatchStatus(prev => prev ? { ...prev, status: 'error' } : null);
      }
    };
    setTimeout(poll, 3000);
  };

  const getDeepChatContext = () => {
    if (triageAnalysisModal?.kind === 'deep') {
      const testId = triageAnalysisModal.testcase_id;
      return {
        source: 'deep',
        sessionId: triageAnalysisModal.session_id || cursorAiSessions[testId] || null,
        testcaseId: testId,
        testcaseName: triageAnalysisModal.testcase_name || '',
        resultRow: triageAnalysisModal.resultRow || results.find(r => r.testcase_id === testId) || null,
        classification: triageAnalysisModal.classification || triageAnalysisModal.issue_type || '',
        latestAnalysis: {
          root_cause: triageAnalysisModal.root_cause || '',
          classification: triageAnalysisModal.classification || triageAnalysisModal.issue_type || '',
          failing_code: triageAnalysisModal.failing_code || null,
          suggested_fix: triageAnalysisModal.suggested_fix || '',
          confidence: triageAnalysisModal.confidence || '',
          related_components: triageAnalysisModal.related_components || [],
          jira_duplicates: triageAnalysisModal.jira_duplicates
            || (triageAnalysisModal.enriched_tickets || []).map(t => t.ticket).filter(Boolean)
            || [],
          triage_report: triageAnalysisModal.triage_report || '',
          pending_ticket_draft: triageAnalysisModal.pending_ticket_draft || null,
          created_ticket: triageAnalysisModal.created_ticket || null,
          exception_summary: triageAnalysisModal.resultRow?.exception_summary || '',
          test_log_url: triageAnalysisModal.resultRow?.test_log_url || '',
          testcase_id: testId,
          agave_task_id: triageAnalysisModal.resultRow?.agave_task_id || '',
          nutest_branch: triageAnalysisModal.resultRow?.nutest_branch || currentBranch || '',
          current_branch: currentBranch || '',
        },
      };
    }
    if (cursorAiDetailModal) {
      const testId = cursorAiDetailModal._testcase_id;
      return {
        source: 'cursor',
        sessionId: cursorAiDetailModal._session_id || cursorAiSessions[testId] || null,
        testcaseId: testId,
        testcaseName: cursorAiDetailModal.testcase_name || '',
        resultRow: results.find(r => r.testcase_id === testId) || null,
        classification: cursorAiDetailModal.classification || '',
        latestAnalysis: {
          root_cause: cursorAiDetailModal.root_cause || '',
          classification: cursorAiDetailModal.classification || '',
          failing_code: cursorAiDetailModal.failing_code || null,
          suggested_fix: cursorAiDetailModal.suggested_fix || '',
          confidence: cursorAiDetailModal.confidence || '',
          related_components: cursorAiDetailModal.related_components || [],
          jira_duplicates: cursorAiDetailModal.jira_duplicates || [],
          triage_report: cursorAiDetailModal.triage_report || '',
          pending_ticket_draft: cursorAiDetailModal.pending_ticket_draft || null,
          created_ticket: cursorAiDetailModal.created_ticket || null,
          testcase_id: testId,
        },
      };
    }
    return null;
  };

  const appendFollowUpMessage = (testcaseId, message) => {
    setFollowUpHistory(prev => {
      const next = [...prev, message];
      if (testcaseId) {
        setFollowUpHistoryByTestcase(hist => ({ ...hist, [testcaseId]: next }));
      }
      return next;
    });
  };

  const applyFollowUpAnalysis = (ctx, analysis) => {
    if (!analysis) return;
    if (ctx.source === 'deep') {
      setTriageAnalysisModal(prev => (prev ? {
        ...prev,
        ...analysis,
        follow_up_answer: analysis.follow_up_answer,
        pending_ticket_draft: analysis.pending_ticket_draft,
        created_ticket: analysis.created_ticket || prev.created_ticket,
        created_ticket_url: analysis.created_ticket_url || prev.created_ticket_url,
      } : prev));
      if (ctx.testcaseId) {
        setDeepAiResults(prev => ({
          ...prev,
          [ctx.testcaseId]: { ...(prev[ctx.testcaseId] || {}), ...analysis },
        }));
      }
    } else if (ctx.source === 'cursor') {
      setCursorAiDetailModal(prev => ({
        ...prev,
        ...analysis,
        follow_up_answer: analysis.follow_up_answer,
      }));
      if (ctx.testcaseId) {
        setCursorAiResults(prev => ({
          ...prev,
          [ctx.testcaseId]: { ...(prev[ctx.testcaseId] || {}), ...analysis },
        }));
      }
    }
  };

  const handleApproveTicketToJita = async (ticketKey) => {
    const ctx = getDeepChatContext();
    const result = ctx?.resultRow;
    const testId = ctx?.testcaseId || result?.testcase_id;
    const ticket = String(ticketKey || '').trim().toUpperCase();
    if (!testId || !ticket) return;
    const existing = result?.jira_tickets || [];
    const merged = [...new Set([...existing, ticket])];
    const comment = commentEdits[testId] !== undefined
      ? commentEdits[testId]
      : (result?.comments || `Linked ${ticket} from Deep AI triage`);
    if (!window.confirm(`Approve and tag JITA with ${ticket}?`)) return;
    setUpdateLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const success = await applyTriageUpdate(testId, comment, merged);
      if (success) {
        setResults(prev => prev.map(r => r.testcase_id === testId
          ? { ...r, comments: comment || r.comments, jira_tickets: merged }
          : r));
        appendFollowUpMessage(testId, {
          role: 'assistant',
          data: { follow_up_answer: `Approved ${ticket} and updated JITA triage tags/comments.` },
          mode: 'system',
        });
        if (ctx?.source === 'deep') {
          setTriageAnalysisModal(prev => prev ? {
            ...prev,
            resultRow: { ...(prev.resultRow || result || {}), jira_tickets: merged, comments: comment },
          } : prev);
        }
      }
    } catch (err) {
      alert(err.response?.data?.error || 'Failed to tag JITA');
    } finally {
      setUpdateLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const handleFluxFromDeepChat = (result) => {
    // Open Flux tag panel with on-page target branch selection (no confirm dialog).
    if (!result) return;
    setDeepAiActionTag('flux');
    prepareDeepAiFluxForm(result);
  };

  const prepareDeepAiFluxForm = async (result) => {
    if (!result) return;
    const taskId = String(result.agave_task_id || '').trim();
    const fallback = fluxNutestTargetBranch(result, currentBranch);
    setDeepAiFluxForm({
      branch: fallback,
      loading: Boolean(taskId),
      error: taskId ? null : 'No Jita Task ID on this row; enter or select the nutest target branch.',
      taskId,
      starting: false,
    });
    if (!taskId) return;
    try {
      const { data } = await api.get(`${FLUX_API}/nutest-branch`, {
        params: { task_id: taskId },
        timeout: 30000,
      });
      const fromJita = fluxNutestTargetBranch(
        { 'nutest-py3-tests_branch': data?.nutest_branch || data?.['nutest-py3-tests_branch'] },
        fallback,
      );
      setDeepAiFluxForm(prev => ({
        ...prev,
        branch: fromJita || prev.branch || '',
        loading: false,
        error: fromJita ? null : (data?.error || 'JITA did not return nutest-py3-tests_branch.'),
      }));
    } catch (err) {
      const message = err.response?.data?.error || err.message || 'Failed to fetch nutest branch from JITA';
      setDeepAiFluxForm(prev => ({
        ...prev,
        loading: false,
        error: message,
        branch: prev.branch || fallback,
      }));
    }
  };

  const startDeepAiFluxQuickFix = async (result) => {
    if (!result) return;
    const testId = result.testcase_id;
    const jiraKey = fluxFirstJiraKey(result);
    const targetBranch = fluxNutestTargetBranch({ nutest_branch: deepAiFluxForm.branch }, currentBranch);
    if (!testId) return;
    if (!jiraKey) {
      alert('Add a Jira ticket first.');
      return;
    }
    if (!targetBranch) {
      alert('Select or enter a nutest target branch (for example ganges-7.5-stable).');
      return;
    }
    setDeepAiFluxForm(prev => ({ ...prev, starting: true, error: null }));
    updateFluxJob(testId, {
      status: 'starting',
      error: null,
      ticket: null,
      rerun: null,
      startedAt: Date.now(),
      resumeAttempted: false,
    });
    fluxResumeInFlight.current[testId] = false;
    try {
      const resp = await api.post(`${FLUX_API}/quick-fix`, {
        jira_key: jiraKey,
        target_branch: targetBranch,
        log_url: null,
        send_test_fix: true,
        update_jira: true,
        pause_for_review: true,
        testcase_id: testId,
        testcase_name: result.testcase_name,
      }, { timeout: 60000 });
      const data = resp.data || {};
      const recordId = data.record_id || data.id;
      updateFluxJob(testId, {
        record_id: recordId,
        status: data.status || 'queued',
        ticket: data,
        error: null,
      });
      appendFollowUpMessage(testId, {
        role: 'assistant',
        data: {
          follow_up_answer: `Started Flux Quick Fix for ${jiraKey} on target branch \`${targetBranch}\`.`,
          suggested_action: null,
        },
        mode: 'system',
      });
      setDeepAiFluxForm(prev => ({ ...prev, starting: false }));
    } catch (err) {
      const data = err.response?.data || {};
      const message = data.error || err.message || 'Flux Quick Fix failed';
      if (data.require_key_setup) {
        alert(message || 'Cursor API key and Gerrit HTTP password are required. Configure them in Settings → API Keys.');
      } else if (data.code === 'CREDENTIALS_EXPIRED') {
        alert(message || 'Session expired. Please re-login.');
      } else {
        alert(message);
      }
      updateFluxJob(testId, {
        status: 'error',
        error: message,
      });
      setDeepAiFluxForm(prev => ({ ...prev, starting: false, error: message }));
    }
  };

  const isDeepAiTestIssue = (modalOrCtx) => {
    const cls = String(
      modalOrCtx?.classification
      || modalOrCtx?.issue_type
      || modalOrCtx?.latestAnalysis?.classification
      || ''
    ).toLowerCase();
    return cls.includes('test');
  };

  const inferEngDetailsFromContext = (ctx) => {
    const analysis = ctx?.latestAnalysis || {};
    const classification = String(analysis.classification || ctx?.classification || '').toLowerCase();
    const isTest = classification.includes('test');
    const comps = analysis.related_components || [];
    const primary = Array.isArray(comps) && comps.length ? String(comps[0]) : '';
    const branch = analysis.current_branch || analysis.nutest_branch || '';
    let affects = 'master';
    if (/7\.6|ganges/i.test(branch)) affects = '7.6';
    else if (branch && branch.toLowerCase() !== 'main') affects = branch;
    const tc = ctx?.testcaseName || analysis.testcase_name || '';
    const shortTc = (tc.split('.').pop() || tc || 'testcase').trim();
    const root = String(analysis.root_cause || '').trim();
    return {
      summary: root ? `${shortTc}: ${root.slice(0, 140)}` : shortTc,
      primary_component: primary,
      affects_version: affects,
      fix_version: 'Triage',
      test_type: isTest ? 'Test Bug' : 'Product Bug',
      issue_type: 'Test',
      additional_details: '',
    };
  };

  const resetDeepAiActionUi = () => {
    setDeepAiActionTag(null);
    setEngDetailsOpen(false);
    setEngDetailsForm({
      summary: '',
      primary_component: '',
      affects_version: '',
      fix_version: 'Triage',
      test_type: '',
      issue_type: '',
      additional_details: '',
    });
    setEngCreateLoading(false);
    setDeepAiFluxForm({
      branch: '',
      loading: false,
      error: null,
      taskId: '',
      starting: false,
    });
  };

  const selectDeepAiActionTag = (tag) => {
    if (deepAiActionTag === tag) {
      resetDeepAiActionUi();
      return;
    }
    setDeepAiActionTag(tag);
    setEngDetailsOpen(false);
    if (tag === 'create_eng') {
      const ctx = getDeepChatContext();
      if (ctx) setEngDetailsForm(inferEngDetailsFromContext(ctx));
    }
    if (tag === 'flux') {
      const ctx = getDeepChatContext();
      if (ctx?.resultRow) prepareDeepAiFluxForm(ctx.resultRow);
    }
  };

  const applyCreateEngAnalysisResult = (ctx, analysis, sessionId) => {
    appendFollowUpMessage(ctx.testcaseId, {
      role: 'assistant',
      data: analysis,
      mode: 'system',
    });
    applyFollowUpAnalysis(ctx, analysis);
    if (analysis.created_ticket && ctx.resultRow) {
      appendFollowUpMessage(ctx.testcaseId, {
        role: 'assistant',
        data: {
          follow_up_answer: `Created ${analysis.created_ticket}. Use Approve on the ticket below to tag JITA.`,
          created_ticket: analysis.created_ticket,
          suggested_action: 'approve_tag_jita',
        },
        mode: 'system',
      });
    }
    if (sessionId && ctx.source === 'deep') {
      setTriageAnalysisModal(prev => (prev ? { ...prev, session_id: sessionId } : prev));
    }
  };

  const handleCreateEngFromAction = async ({ useDetails }) => {
    const ctx = getDeepChatContext();
    if (!ctx) return;

    const overrides = useDetails
      ? Object.fromEntries(
          Object.entries(engDetailsForm).map(([k, v]) => [k, String(v || '').trim()])
            .filter(([, v]) => v)
        )
      : {};

    const label = useDetails && Object.keys(overrides).length
      ? 'Create ENG ticket (with details)'
      : 'Create ENG ticket (defaults from analysis)';

    setEngCreateLoading(true);
    appendFollowUpMessage(ctx.testcaseId, { role: 'user', text: label, mode: 'system' });

    const ticketContext = {
      testcase_name: ctx.testcaseName,
      ...ctx.latestAnalysis,
      ...overrides,
      confirm: true,
    };

    try {
      const resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/create-eng-ticket`, {
        ticket_context: ticketContext,
        require_confirm: false,
        confirm: true,
      });
      if (resp.data?.success) {
        const analysis = resp.data.analysis || {
          follow_up_answer: resp.data.key
            ? `Created ${resp.data.key}: ${resp.data.url || ''}`
            : resp.data.draft
              ? 'ENG draft ready — fill missing fields and retry.'
              : 'ENG ticket request processed.',
          created_ticket: resp.data.key,
          created_ticket_url: resp.data.url,
          pending_ticket_draft: resp.data.draft || resp.data.analysis?.pending_ticket_draft,
        };
        applyCreateEngAnalysisResult(ctx, analysis, resp.data.session_id || ctx.sessionId);
        if (analysis.created_ticket) {
          resetDeepAiActionUi();
        } else if (analysis.pending_ticket_draft) {
          setEngDetailsOpen(true);
          setEngDetailsForm(prev => ({
            ...prev,
            ...Object.fromEntries(
              Object.entries(analysis.pending_ticket_draft)
                .filter(([k, v]) => k in prev && v)
                .map(([k, v]) => [k, String(v)])
            ),
          }));
        }
      } else {
        appendFollowUpMessage(ctx.testcaseId, {
          role: 'error',
          text: resp.data?.error || 'Failed to create ENG ticket',
        });
      }
    } catch (err) {
      appendFollowUpMessage(ctx.testcaseId, {
        role: 'error',
        text: err.response?.data?.error || err.message || 'Failed to create ENG ticket',
      });
    } finally {
      setEngCreateLoading(false);
    }
  };

  const isCreateEngChatIntent = (text) => {
    const t = String(text || '')
      .toLowerCase()
      .replace(/\bcreat\b/g, 'create')
      .replace(/\bcreaet\b/g, 'create')
      .replace(/\bcrate\b/g, 'create')
      .replace(/ticet|tiket|ticekt/g, 'ticket')
      .replace(/\s+/g, ' ')
      .trim();
    if (!t) return false;
    if (/\b(open|show|view|get)\b.{0,24}\b[a-z][a-z0-9]+-\d+\b/.test(t)
      && !/\b(create|file|raise|submit)\b/.test(t)) {
      return false;
    }
    return (
      /\b(create|file|raise|submit)\b.{0,40}\b(eng\s+)?(jira\s+)?ticket\b/.test(t)
      || /\b(create|file|raise|submit)\b.{0,24}\beng\b/.test(t)
      || /\bnew\s+(eng\s+)?(jira\s+)?ticket\b/.test(t)
      || /\b(create|file)\s+eng\b/.test(t)
    );
  };

  const handleFollowUp = async () => {
    if (!followUpInput.trim()) return;
    const ctx = getDeepChatContext();
    if (!ctx) return;

    const question = followUpInput.trim();
    const selectedMode = followUpMode;
    const sessionId = ctx.sessionId;
    setFollowUpLoading(true);
    appendFollowUpMessage(ctx.testcaseId, { role: 'user', text: question, mode: selectedMode });
    setFollowUpInput('');

    const ticketContext = {
      testcase_name: ctx.testcaseName,
      ...ctx.latestAnalysis,
    };
    const recoveryContext = {
      testcase_name: ctx.testcaseName,
      latest_analysis: ctx.latestAnalysis,
      prior_history: followUpHistory.slice(-20),
      agave_task_id: ctx.latestAnalysis.agave_task_id || '',
      testcase_id: ctx.testcaseId || '',
    };

    try {
      let resp;
      const pendingDraft = ctx.latestAnalysis?.pending_ticket_draft;
      const confirmDraft = Boolean(pendingDraft) && /^(yes|y|confirm|ok|okay|proceed)\b/i.test(question.trim());
      // Create ENG via dedicated User Settings Jira REST path — never agent MCP / jira_helper.
      if (isCreateEngChatIntent(question) || confirmDraft) {
        resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/create-eng-ticket`, {
          ticket_context: {
            ...ticketContext,
            ...(confirmDraft && pendingDraft ? { ...pendingDraft, confirm: true } : {}),
          },
          require_confirm: false,
          confirm: confirmDraft || undefined,
        });
        if (resp.data?.success) {
          resp = {
            data: {
              success: true,
              session_id: sessionId,
              analysis: resp.data.analysis || {
                follow_up_answer: resp.data.key
                  ? `Created ${resp.data.key}: ${resp.data.url || ''}`
                  : resp.data.draft
                    ? 'ENG draft ready — confirm to create.'
                    : 'ENG ticket request processed.',
                created_ticket: resp.data.key,
                created_ticket_url: resp.data.url,
                pending_ticket_draft: resp.data.draft || resp.data.analysis?.pending_ticket_draft,
              },
            },
          };
        }
      } else {
        resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/follow-up`, {
          session_id: sessionId || `deep-ai-${ctx.testcaseId || 'anon'}`,
          question,
          mode: followUpMode,
          ticket_context: ticketContext,
          recovery_context: recoveryContext,
        });
      }
      if (resp.data?.success) {
        const analysis = resp.data.analysis || {};
        appendFollowUpMessage(ctx.testcaseId, {
          role: 'assistant',
          data: analysis,
          mode: selectedMode,
        });
        applyFollowUpAnalysis(ctx, analysis);

        if (analysis.suggested_action === 'flux_quick_fix' && analysis.requires_confirmation) {
          handleFluxFromDeepChat(ctx.resultRow);
        }
        if (analysis.created_ticket && ctx.resultRow) {
          // Offer approve-to-JITA after create without forcing it.
          appendFollowUpMessage(ctx.testcaseId, {
            role: 'assistant',
            data: {
              follow_up_answer: `Created ${analysis.created_ticket}. Use Approve on the ticket below to tag JITA.`,
              created_ticket: analysis.created_ticket,
              suggested_action: 'approve_tag_jita',
            },
            mode: 'system',
          });
        }
      } else {
        appendFollowUpMessage(ctx.testcaseId, {
          role: 'error',
          text: resp.data?.error || 'Follow-up failed',
        });
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Follow-up failed';
      appendFollowUpMessage(ctx.testcaseId, { role: 'error', text: msg });
    } finally {
      setFollowUpLoading(false);
    }
  };


  const getCursorAiStatusBadge = (testId) => {
    if (cursorAiLoading[testId]) return <span className="badge cursor-ai-loading">Analyzing…</span>;
    const res = cursorAiResults[testId];
    if (!res) return null;
    if (res.error) return <span className="badge cursor-ai-error" title={res.error}>Error</span>;
    const cls = res.classification || '';
    const badgeClass = cls.includes('Test') ? 'cursor-ai-test-issue'
      : cls.includes('Product') ? 'cursor-ai-product-issue'
      : cls.includes('Infra') ? 'cursor-ai-infra-issue'
      : 'cursor-ai-other';
    return (
      <span className={`badge ${badgeClass}`} title={res.root_cause}>
        {res.classification || 'Analyzed'}
      </span>
    );
  };

  const openCursorAiInTab = (result) => {
    const testId = result?.testcase_id;
    const analysis = testId ? cursorAiResults[testId] : null;
    if (!testId || !analysis || analysis.error) return;

    const tabId = String(testId);
    const sessionId = cursorAiSessions[testId] || null;
    setCursorAiOpenTabs(prev => {
      const without = prev.filter(t => t.tabId !== tabId);
      return [...without, {
        tabId,
        testcase_id: testId,
        testcase_name: result.testcase_name,
        analysis,
        session_id: sessionId,
      }];
    });
    setCursorAiMinimizedTabs(prev => ({ ...prev, [tabId]: false }));
  };

  const closeCursorAiTab = (tabId) => {
    setCursorAiOpenTabs(prev => prev.filter(t => t.tabId !== tabId));
    setCursorAiMinimizedTabs(prev => {
      const next = { ...prev };
      delete next[tabId];
      return next;
    });
  };

  const toggleCursorAiTabMinimized = (tabId) => {
    setCursorAiMinimizedTabs(prev => ({ ...prev, [tabId]: !prev[tabId] }));
  };

  // --------------- Re-trigger handlers ---------------

  const openRetriggerModal = () => {
    if (selectedRows.length === 0) {
      alert('Select at least one testcase to re-trigger.');
      return;
    }
    setRetriggerOverrides({ ...RETRIGGER_DEFAULTS,
      nos: { ...RETRIGGER_DEFAULTS.nos },
      pc: { ...RETRIGGER_DEFAULTS.pc },
      image: { ...RETRIGGER_DEFAULTS.image },
      node_pools: [],
    });
    setNodePoolSearch('');
    setNodePoolResults([]);
    setNodePoolLoading(false);
    setRetriggerResults(null);
    setRetriggerCopied('');
    setRetriggerModalOpen(true);
    const taskIds = [...new Set(
      selectedRows
        .map(id => results.find(r => r.testcase_id === id))
        .filter(Boolean)
        .map(r => r.agave_task_id)
        .filter(Boolean)
    )];
    setRetriggerResourcePreview({ loading: true, tasks: [] });
    api.post(`${API_BASE}/retrigger-preview`, { task_ids: taskIds })
      .then((resp) => {
        const tasks = resp.data?.tasks || [];
        setRetriggerResourcePreview({ loading: false, tasks });
        const first = tasks[0] || {};
        setRetriggerOverrides(prev => ({
          ...prev,
          nos: { ...prev.nos, branch: first.nos_branch || prev.nos.branch },
          resources_mode: first.resources_mode || prev.resources_mode,
          resource_type: first.resource_type_key || prev.resource_type,
          hypervisor: first.hypervisor || prev.hypervisor,
          node_pools: Array.isArray(first.node_pools) ? [...first.node_pools] : [],
          match_resource_spec: first.match_resource_spec !== false,
        }));
      })
      .catch(() => {
        setRetriggerResourcePreview({ loading: false, tasks: [] });
      });
  };

  const updateResourceOverride = (patch) => {
    setRetriggerOverrides(prev => ({ ...prev, overrideResource: true, ...patch }));
  };

  const toggleAllComponentOverrides = (checked) => {
    setRetriggerOverrides(prev => ({
      ...prev,
      updateNos: checked,
      updatePc: checked,
      updateImage: checked,
      updateFramework: checked,
      updateResource: checked,
    }));
  };
  const allComponentsOverride = !!(
    retriggerOverrides.updateNos &&
    retriggerOverrides.updatePc &&
    retriggerOverrides.updateImage &&
    retriggerOverrides.updateFramework &&
    retriggerOverrides.updateResource
  );

  const handleSearchRetriggerNodePools = (query) => {
    setNodePoolSearch(query);
    if (nodePoolDebounce.current) clearTimeout(nodePoolDebounce.current);
    if (!query || query.length < 2) {
      setNodePoolResults([]);
      setNodePoolLoading(false);
      return;
    }
    setNodePoolLoading(true);
    nodePoolDebounce.current = setTimeout(async () => {
      const reqId = ++nodePoolReqId.current;
      try {
        const response = await api.post(NODE_POOL_SEARCH_URL, { query });
        if (reqId === nodePoolReqId.current) {
          setNodePoolResults(Array.isArray(response.data?.pools) ? response.data.pools : []);
        }
      } catch (_) {
        if (reqId === nodePoolReqId.current) setNodePoolResults([]);
      } finally {
        if (reqId === nodePoolReqId.current) setNodePoolLoading(false);
      }
    }, 300);
  };

  const addRetriggerNodePool = (pool) => {
    const name = String(pool || '').trim();
    if (!name) return;
    const current = retriggerOverrides.node_pools || [];
    updateResourceOverride({
      node_pools: current.includes(name) ? current : [...current, name],
    });
    setNodePoolSearch('');
    setNodePoolResults([]);
  };

  const removeRetriggerNodePool = (pool) => {
    updateResourceOverride({
      node_pools: (retriggerOverrides.node_pools || []).filter(p => p !== pool),
    });
  };

  const selectedRetriggerRows = selectedRows
    .map(id => results.find(r => r.testcase_id === id))
    .filter(Boolean);
  const selectedRetriggerTaskIds = [...new Set(selectedRetriggerRows.map(r => r.agave_task_id).filter(Boolean))];
  const succeededRerunIds = (retriggerResults?.rerun_task_ids?.length
    ? retriggerResults.rerun_task_ids
    : (retriggerResults?.results || [])
        .filter(r => r.success && r.rerun_task_id)
        .map(r => r.rerun_task_id)
  ).map(normalizeJitaTaskId).filter(Boolean);
  const retriggerResultUrls = jitaResultsUrls(succeededRerunIds);
  const pcBuildChanged = retriggerOverrides.updatePc && (
    !!(retriggerOverrides.pc.commitId || '').trim() ||
    !!(retriggerOverrides.pc.gbn || '').trim()
  );
  const pcBuildUrlsMissing = pcBuildChanged && (
    !(retriggerOverrides.pc.buildUrl || '').trim() ||
    !(retriggerOverrides.pc.qcow2Url || '').trim()
  );
  const handleRetrigger = async () => {
    const selected = selectedRows.filter(Boolean);
    if (selected.length === 0) return;

    const testsPayload = selected.map(id => {
      const r = results.find(row => row.testcase_id === id);
      if (!r) return null;
      return {
        testcase_id: r.testcase_id,
        testcase_name: r.testcase_name,
        agave_task_id: r.agave_task_id,
      };
    }).filter(Boolean);

    if (testsPayload.length === 0) {
      alert('No valid tests found for retrigger.');
      return;
    }

    const overrides = {};
    if (retriggerOverrides.updateNos) {
      const n = retriggerOverrides.nos;
      applyCommitOrTag(overrides, n.commitId, 'nos_commit', 'nos_tag');
      if (n.gbn) overrides.nos_gbn = n.gbn.trim();
    }
    if (retriggerOverrides.updatePc) {
      const p = retriggerOverrides.pc;
      if (p.branch) overrides.pc_branch = p.branch.trim();
      applyCommitOrTag(overrides, p.commitId, 'pc_commit', 'pc_tag');
      if (p.gbn) overrides.pc_gbn = p.gbn.trim();
      if (p.buildUrl) overrides.pc_build_url = p.buildUrl.trim();
      if (p.qcow2Url) overrides.pc_build_url_qcow2 = p.qcow2Url.trim();
    }
    if (retriggerOverrides.updateImage) {
      const im = retriggerOverrides.image;
      if (im.branch) overrides.image_branch = im.branch.trim();
      if (im.commitId) overrides.image_commit = im.commitId.trim();
      if (im.gbn) overrides.image_gbn = im.gbn.trim();
    }
    if (retriggerOverrides.updateFramework) {
      if (retriggerOverrides.nutest_branch) {
        const branch = retriggerOverrides.nutest_branch.trim();
        overrides.nutest_branch = branch;
        overrides.test_branch = branch;
      }
      if (retriggerOverrides.patch_url) overrides.patch_url = retriggerOverrides.patch_url.trim();
      if (retriggerOverrides.framework_patch_url) overrides.framework_patch_url = retriggerOverrides.framework_patch_url.trim();
    }
    if (retriggerOverrides.updateResource) {
      overrides.override_resource_config = true;
      overrides.resources_mode = retriggerOverrides.resources_mode;
      overrides.resource_type = retriggerOverrides.resource_type;
      overrides.node_pools = retriggerOverrides.node_pools;
      overrides.hypervisor = (retriggerOverrides.hypervisor || '').trim();
      overrides.match_resource_spec = !!retriggerOverrides.match_resource_spec;
    } else if (retriggerOverrides.overridePool && retriggerOverrides.resource_pool.trim()) {
      overrides.override_pool = true;
      overrides.resource_pool = retriggerOverrides.resource_pool.trim();
      if (retriggerOverrides.resource_type) {
        overrides.resource_type = retriggerOverrides.resource_type;
      }
    }
    if ((retriggerOverrides.label || '').trim()) {
      overrides.label = retriggerOverrides.label.trim();
    }
    if ((retriggerOverrides.priority || '').trim()) {
      overrides.priority = retriggerOverrides.priority.trim();
    }
    if ((retriggerOverrides.tester_tags || '').trim()) {
      overrides.tester_tags = retriggerOverrides.tester_tags.trim();
    }
    if (retriggerOverrides.overrideScheduling) {
      overrides.skip_resource_spec_match = !!retriggerOverrides.skip_resource_spec_match;
      overrides.check_image_compatibility = !!retriggerOverrides.check_image_compatibility;
    }

    setRetriggerLoading(true);
    setRetriggerResults(null);
    setRetriggerCopied('');

    try {
      const resp = await api.post(`${API_BASE}/retrigger`, {
        tests: testsPayload,
        overrides,
        sync_to_tcms: retriggerOverrides.syncToTcms,
      });
      setRetriggerResults(resp.data);
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Retrigger failed';
      setRetriggerResults({ success: false, error: msg });
    } finally {
      setRetriggerLoading(false);
    }
  };

  // --------------- RDM Skipped Analysis handler ---------------

  const handleAnalyzeSkipped = async () => {
    const selected = selectedRows.filter(Boolean);
    if (selected.length === 0) {
      alert('Select at least one testcase to analyze.');
      return;
    }
    const skippedRows = selected
      .map(id => results.find(r => r.testcase_id === id))
      .filter((r) => {
        const status = (r?.status || '').toLowerCase();
        return status === 'skipped' || status === 'skip';
      });

    if (skippedRows.length === 0) {
      alert('No skipped testcases selected. Please select skipped testcases to analyze.');
      return;
    }

    const tests = skippedRows
      .filter(r => r.agave_task_id)
      .map(r => ({
        agave_task_id: r.agave_task_id,
        testcase_id: r.testcase_id,
        testcase_name: r.testcase_name,
        deployment_id: r.deployment_id || r.rdm_info?.jita_deployment_id || '',
      }));
    if (tests.length === 0) {
      alert('Selected skipped testcases have no task IDs.');
      return;
    }

    setRdmAnalyzing(true);
    try {
      const resp = await api.post(`${API_BASE}/rdm-analyze`, { tests });
      if (resp.data?.success && resp.data.results) {
        const rdmByTest = {};
        for (const r of resp.data.results) {
          if (r.testcase_id) rdmByTest[r.testcase_id] = r;
        }
        setResults(prev => prev.map(row => {
          if (!selected.includes(row.testcase_id)) return row;
          const taskRdm = rdmByTest[row.testcase_id];
          if (!taskRdm || !taskRdm.rdm_found) return { ...row, rdm_info: { rdm_found: false } };
          return {
            ...row,
            deployment_id: taskRdm.jita_deployment_id || row.deployment_id,
            rdm_info: mapRdmAnalyzeFields(taskRdm),
          };
        }));
      }
    } catch (err) {
      console.error('RDM analysis failed:', err);
      alert('RDM analysis failed: ' + (err.response?.data?.error || err.message));
    } finally {
      setRdmAnalyzing(false);
    }
  };

  const applyRdmAnalysisSideEffects = (testcaseId, payload) => {
    if (!payload?.failed_nodes && !payload?.suggested_next_action && !payload?.issue_category) return;
    setResults(prev => prev.map(r =>
      r.testcase_id === testcaseId
        ? {
            ...r,
            rdm_info: {
              ...r.rdm_info,
              failed_nodes: payload.failed_nodes || r.rdm_info?.failed_nodes || [],
              next_action: payload.suggested_next_action || r.rdm_info?.next_action || '',
              pattern_category: payload.suggested_next_action === 'disable_node_and_rerun'
                ? 'INFRA_NODE'
                : (payload.issue_category || r.rdm_info?.pattern_category || ''),
            },
          }
        : r
    ));
  };

  const handleRdmAiAnalyze = async (result) => {
    const testId = result.testcase_id;
    const rdm = result.rdm_info || {};
    setRdmAiLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const resp = await api.post(`${API_BASE}/rdm-analyze-ai`, {
        task_id: result.agave_task_id,
        testcase_id: testId,
        deployment_id: result.deployment_id || rdm.jita_deployment_id || '',
        rdm_message: rdm.rdm_message,
        testcase_name: result.testcase_name,
      });
      if (resp.data?.success) {
        setRdmAiResults(prev => ({ ...prev, [testId]: resp.data }));
        applyRdmAnalysisSideEffects(testId, resp.data);
      } else {
        alert(resp.data?.error || 'First Level Analysis failed');
      }
    } catch (err) {
      console.error('RDM First Level Analysis failed:', err);
      alert('First Level Analysis failed: ' + (err.response?.data?.error || err.message));
    } finally {
      setRdmAiLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const handleRdmSkillAnalyze = async (result) => {
    const testId = result.testcase_id;
    const rdm = result.rdm_info || {};
    setRdmSkillLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const resp = await api.post(`${API_BASE}/rdm-skill-analyze`, {
        task_id: result.agave_task_id,
        testcase_id: testId,
        testcase_name: result.testcase_name,
        deployment_id: result.deployment_id || rdm.jita_deployment_id || '',
        rdm_message: rdm.rdm_message,
        rdm_link: rdm.rdm_link || '',
        jira_tickets: result.jira_tickets || [],
        failure_stage: result.failure_stage,
        triage_genie_ticket: tgTicketFromResult(result),
      }, { timeout: 620000 });
      if (resp.data?.success) {
        setRdmSkillResults(prev => ({ ...prev, [testId]: resp.data }));
        applyRdmAnalysisSideEffects(testId, resp.data);
      } else {
        alert(resp.data?.error || 'AI RDM Failure Analysis failed');
      }
    } catch (err) {
      const data = err.response?.data || {};
      if (data.require_key_setup) {
        alert('Cursor API key required. Configure it in Settings.');
      } else {
        alert('AI RDM Failure Analysis failed: ' + (data.error || err.message));
      }
    } finally {
      setRdmSkillLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const openRdmSkillJiraCreate = async (skill) => {
    const create = skill?.jira_create || {};
    const text = [create.summary, create.description].filter(Boolean).join('\n\n');
    try {
      if (text && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      }
    } catch (_) { /* clipboard optional */ }
    window.open(create.url || 'https://jira.nutanix.com/secure/CreateIssue!default.jspa', '_blank', 'noopener,noreferrer');
    alert(`Triage text copied. Create a ${create.project || 'DIAL'} ticket and paste the report, then Approve with the new ticket key.`);
  };

  const applyRdmApproveResult = (testcaseId, comment, mergedJira, respData) => {
    setResults(prev => prev.map(r => {
      if (r.testcase_id !== testcaseId) return r;
      return {
        ...r,
        comments: comment,
        jira_tickets: mergedJira,
        rdm_info: {
          ...r.rdm_info,
          approved: !!respData?.triage_updated || !!respData?.success,
          generated_comment: comment,
          jarvis_results: respData?.jarvis_results || r.rdm_info?.jarvis_results,
          retrigger: respData?.retrigger || r.rdm_info?.retrigger,
          workflow_error: respData?.success === false ? (respData?.error || '') : '',
        },
      };
    }));
    if (comment) {
      setCommentEdits(prev => ({ ...prev, [testcaseId]: comment }));
    }
  };

  const handleRdmApproveComment = async (testcaseId, comment, jiraTicket, { retrigger = false } = {}) => {
    setRdmAiLoading(prev => ({ ...prev, [testcaseId]: true }));
    try {
      const row = results.find(r => r.testcase_id === testcaseId);
      const rdm = row?.rdm_info || {};
      const existing = row?.jira_tickets || [];
      const merged = jiraTicket
        ? [...new Set([...existing, jiraTicket])]
        : existing;
      const resp = await api.post(`${API_BASE}/rdm-approve`, {
        testcase_id: testcaseId,
        testcase_name: row?.testcase_name,
        agave_task_id: row?.agave_task_id,
        comment,
        jira_tickets: merged,
        rdm_link: rdm.rdm_link || '',
        failed_nodes: rdm.failed_nodes || [],
        pattern_category: rdm.pattern_category || '',
        next_action: rdm.next_action || '',
        retrigger,
      });
      if (resp.data) {
        applyRdmApproveResult(testcaseId, comment, merged, resp.data);
        if (resp.data.success === false) {
          alert(resp.data.error || 'Approve completed with errors. Check RDM Analysis status.');
        }
      } else {
        alert('Failed to update: Unknown error');
      }
    } catch (err) {
      alert('Update failed: ' + (err.response?.data?.error || err.message));
    } finally {
      setRdmAiLoading(prev => ({ ...prev, [testcaseId]: false }));
    }
  };

  const handleRdmAutoWorkflow = async (rows, { requirePattern = true, parentTaskId = '' } = {}) => {
    const parent = parentTaskId || resolveParentJitaTaskId(rows, inputMode, taskIds);
    const tests = (rows || []).filter(Boolean).map(r => ({
      testcase_id: r.testcase_id,
      testcase_name: r.testcase_name,
      agave_task_id: parent || r.agave_task_id,
      deployment_id: r.deployment_id || r.rdm_info?.jita_deployment_id || '',
      rdm_info: r.rdm_info || {},
      jira_tickets: r.jira_tickets || [],
    }));
    if (tests.length === 0) {
      alert('Select at least one skipped testcase.');
      return;
    }
    const ids = tests.map(t => t.testcase_id);
    setRdmWorkflowLoading(prev => {
      const next = { ...prev };
      ids.forEach(id => { next[id] = true; });
      return next;
    });
    try {
      const resp = await api.post(`${API_BASE}/rdm-auto-workflow`, {
        tests,
        retrigger: true,
        parent_task_id: parent,
      });
      const wfResults = resp.data?.results || [];
      setResults(prev => prev.map(row => {
        const wr = wfResults.find(w => w.testcase_id === row.testcase_id);
        if (!wr) return row;
        const rdm = wr.rdm_info ? { ...row.rdm_info, ...wr.rdm_info } : (row.rdm_info || {});
        return {
          ...row,
          comments: wr.comment || row.comments,
          rdm_info: {
            ...rdm,
            approved: !!wr.triage_updated || !!wr.success,
            generated_comment: wr.comment || rdm.generated_comment,
            jarvis_results: wr.jarvis_results || rdm.jarvis_results,
            retrigger: wr.retrigger || rdm.retrigger,
            workflow_error: wr.success ? '' : (wr.error || ''),
          },
        };
      }));
      const unmatched = wfResults.filter(w => w.pattern_matched === false);
      const failed = wfResults.filter(w => !w.success);
      if (requirePattern && unmatched.length === wfResults.length) {
        alert('Analyze, Fix & Re-run only runs for pattern-matched RDM failures. Run Analyze Skipped first, or add a pattern from First Level Analysis.');
      } else if (failed.length > 0) {
        alert(`${resp.data.succeeded || 0}/${resp.data.total || wfResults.length} succeeded. ${failed.length} failed — see RDM Analysis status.`);
      }
    } catch (err) {
      alert('Workflow failed: ' + (err.response?.data?.error || err.message));
    } finally {
      setRdmWorkflowLoading(prev => {
        const next = { ...prev };
        ids.forEach(id => { next[id] = false; });
        return next;
      });
    }
  };

  const openAddPatternModal = (result, rdmAi) => {
    const rdm = result?.rdm_info || {};
    const suggested = rdmAi?.suggested_pattern || {};
    setPatternModal({
      testcase_id: result.testcase_id,
      testcase_name: result.testcase_name,
      id: suggested.id || '',
      regex: suggested.regex || '',
      comment_template: suggested.comment_template || rdmAi?.suggested_comment || 'regx_rerun',
      category: suggested.category || (rdmAi?.failed_nodes?.length ? 'INFRA_NODE' : 'INFRA_INTERMITTENT'),
      next_action: suggested.next_action || rdmAi?.suggested_next_action || 'rerun',
      description: suggested.description || '',
      example_failure: suggested.example_failure || rdm.rdm_message || '',
      reference_task: suggested.reference_task || rdm.rdm_link || '',
      jira: rdmAi?.jira_ticket || (rdmAi?.jira_refs && rdmAi.jira_refs[0]) || '',
    });
  };

  const handleSavePattern = async () => {
    if (!patternModal) return;
    if (!patternModal.regex.trim() || !patternModal.comment_template.trim()) {
      alert('Regex and comment template are required.');
      return;
    }
    setPatternSaving(true);
    try {
      const resp = await api.post(`${API_BASE}/rdm-patterns/add`, {
        pattern: {
          id: patternModal.id,
          regex: patternModal.regex,
          comment_template: patternModal.comment_template,
          category: patternModal.category,
          next_action: patternModal.next_action,
          description: patternModal.description,
          example_failure: patternModal.example_failure,
          reference_task: patternModal.reference_task,
          jira: patternModal.jira,
        },
      });
      if (resp.data?.success) {
        setPatternModal(null);
        alert(`Pattern saved (${resp.data.pattern?.id}). Future Analyze Skipped runs will use it.`);
      } else {
        alert(resp.data?.error || 'Failed to save pattern');
      }
    } catch (err) {
      alert('Save pattern failed: ' + (err.response?.data?.error || err.message));
    } finally {
      setPatternSaving(false);
    }
  };

  // --------------- Per-row AI Summary handler ---------------

  const handleAiSummarySingle = async (result) => {
    const testId = result.testcase_id;
    if (!testId) return;
    setAiSummaryLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const resp = await api.post(`${API_BASE}/ai-summary-single`, {
        testcase_name: result.testcase_name,
        exception_summary: result.exception_summary || '',
        exception: result.exception || '',
        test_log_url: result.test_log_url || '',
      });
      if (resp.data?.success) {
        setResults(prev => prev.map(r =>
          r.testcase_id === testId ? { ...r, ai_summary: resp.data.ai_summary } : r
        ));
      } else {
        setResults(prev => prev.map(r =>
          r.testcase_id === testId ? { ...r, ai_summary: `Error: ${resp.data?.error || 'Unknown error'}` } : r
        ));
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Failed to generate AI summary';
      setResults(prev => prev.map(r =>
        r.testcase_id === testId ? { ...r, ai_summary: `Error: ${msg}` } : r
      ));
    } finally {
      setAiSummaryLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  // --------------- Glean Search handler ---------------

  const handleGleanSearch = async (result) => {
    const testId = result.testcase_id;
    if (!testId) return;
    setGleanSearchLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const resp = await api.post(`${API_BASE}/glean-search-single`, {
        testcase_id: testId,
        testcase_name: result.testcase_name,
        exception_summary: result.exception_summary || '',
        exception: result.exception || '',
        ai_summary: result.ai_summary || '',
        test_log_url: result.test_log_url || '',
        failure_stage: result.failure_stage || '',
        jira_tickets: result.jira_tickets || [],
      });
      if (resp.data?.success) {
        setGleanSearchResults(prev => ({ ...prev, [testId]: resp.data }));
      } else {
        setGleanSearchResults(prev => ({
          ...prev,
          [testId]: { error: resp.data?.error || 'Glean search failed' },
        }));
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Glean search failed';
      setGleanSearchResults(prev => ({
        ...prev,
        [testId]: { error: msg },
      }));
    } finally {
      setGleanSearchLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  // --------------- End Cursor AI handlers ---------------

  // --------------- Intelligent Triage handlers ---------------

  const handleIntelligentTriage = (result) => {
    const testId = result.testcase_id;
    if (!testId) {
      alert('No test ID available for analysis');
      return;
    }
    setIntelligentTriageResults(prev => ({
      ...prev,
      [testId]: {
        analysis_type: 'ready',
        requires_first_level_ai: true,
        requires_deep_ai_analysis: true,
      },
    }));
  };

  const handleFirstLevelAiAnalysis = async (result, { force = false } = {}) => {
    const testId = result.testcase_id;
    if (!testId) return;

    // Prefer already-hydrated analysis after tag load / page restore.
    if (!force && firstLevelAiResults[testId]?.intelligent_triage) {
      setTriageAnalysisModal({
        kind: 'first_level',
        testcase_name: result.testcase_name,
        testcase_id: testId,
        resultRow: result,
        ...firstLevelAiResults[testId],
      });
      return;
    }

    setFirstLevelAiLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const response = await api.post(`${API_BASE}/first-level-ai`, {
        test_result: buildFailedAnalysisTestResult(result),
        user_requested_ai: true,
        tag: analysisTag || tag || selectedSavedTag || '',
        apply_auto_triage: true,
        force: !!force,
      });
      const data = response.data || {};
      if (!data.success) {
        throw new Error(data.error || 'Analysis failed');
      }
      const stored = {
        ...data,
        analysis_type: data.analysis_type || 'first_level_ai',
        confidence: data.triage_confidence ?? data.analysis_result?.triage_confidence ?? data.analysis_result?.confidence ?? 0.8,
        triage_confidence: data.triage_confidence,
        intermittent_confidence: data.intermittent_confidence,
        existing_issues: data.enriched_tickets || data.existing_issues || [],
        decision: data.decision,
        mcp_health: data.mcp_health,
        intelligent_triage: data.intelligent_triage,
      };
      setFirstLevelAiResults(prev => ({ ...prev, [testId]: stored }));
      if (data.intelligent_triage) {
        setIntelligentTriageByTestcase(prev => ({ ...prev, [testId]: data.intelligent_triage }));
      }
      if (data.enriched_tickets || data.glean_snippets || data.intelligent_triage?.glean_candidates) {
        const candidates = data.intelligent_triage?.glean_candidates?.search?.candidates
          || data.enriched_tickets
          || [];
        setGleanSearchResults(prev => ({
          ...prev,
          [testId]: {
            ...(prev[testId] || {}),
            success: true,
            issue_type: data.issue_type,
            enriched_tickets: candidates,
            glean_snippets: data.glean_snippets || data.intelligent_triage?.glean_candidates?.search?.snippets || [],
            glean_jira_refs: data.glean_jira_refs || [],
            search_source: data.search_source,
            glean_ok: data.glean_ok,
            mcp_health: data.mcp_health,
            ai_validation: data.intelligent_triage?.glean_candidates?.ai_validation || null,
          },
        }));
      }
      setTriageAnalysisModal({
        kind: 'first_level',
        testcase_name: result.testcase_name,
        testcase_id: testId,
        resultRow: result,
        ...stored,
      });
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Unknown error occurred';
      alert(`First Level AI analysis failed: ${errorMessage}`);
    } finally {
      setFirstLevelAiLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const handleGleanAiValidate = async (result, ticketInfo) => {
    const testId = result.testcase_id;
    const ticket = ticketInfo?.ticket;
    if (!testId || !ticket) return;
    setGleanAiValidating(prev => ({ ...prev, [testId]: ticket }));
    try {
      const response = await api.post(`${API_BASE}/glean-ai-validate`, {
        ticket,
        testcase_id: testId,
        tag: analysisTag || tag || selectedSavedTag || '',
        test_result: buildFailedAnalysisTestResult(result),
      });
      const data = response.data || {};
      if (!data.success) throw new Error(data.error || 'Validation failed');
      if (data.intelligent_triage) {
        setIntelligentTriageByTestcase(prev => ({ ...prev, [testId]: data.intelligent_triage }));
        setFirstLevelAiResults(prev => ({
          ...prev,
          [testId]: {
            ...(prev[testId] || {}),
            intelligent_triage: data.intelligent_triage,
            enriched_tickets: data.intelligent_triage?.glean_candidates?.search?.candidates || prev[testId]?.enriched_tickets,
            glean_ai_validation: data.ai_validation,
          },
        }));
      }
      setGleanSearchResults(prev => ({
        ...prev,
        [testId]: {
          ...(prev[testId] || {}),
          ai_validation: data.ai_validation,
          enriched_tickets: (prev[testId]?.enriched_tickets || []).map((t) => (
            t.ticket === ticket ? { ...t, ai_validation: data.ai_validation } : t
          )),
        },
      }));
      if (triageAnalysisModal?.testcase_id === testId) {
        setTriageAnalysisModal(prev => prev ? {
          ...prev,
          intelligent_triage: data.intelligent_triage || prev.intelligent_triage,
          glean_ai_validation: data.ai_validation,
          enriched_tickets: data.intelligent_triage?.glean_candidates?.search?.candidates || prev.enriched_tickets,
        } : prev);
      }
    } catch (error) {
      alert(`Glean AI Validate failed: ${error.response?.data?.error || error.message}`);
    } finally {
      setGleanAiValidating(prev => ({ ...prev, [testId]: null }));
    }
  };

  const handleDeepAiAnalysis = async (result, { force = false } = {}) => {
    const testId = result.testcase_id;
    if (!testId) return;

    if (!force && deepAiResults[testId]?.root_cause) {
      setFollowUpHistory(followUpHistoryByTestcase[testId] || []);
      setFollowUpMode('ask');
      resetDeepAiActionUi();
      setTriageAnalysisModal({
        kind: 'deep',
        testcase_name: result.testcase_name,
        testcase_id: testId,
        resultRow: result,
        session_id: deepAiResults[testId].session_id || cursorAiSessions[testId] || null,
        ...deepAiResults[testId],
      });
      return;
    }

    const fl = firstLevelAiResults[testId];
    const recommended = fl?.decision?.deep_ai_recommended || fl?.decision?.outcome === 'NEEDS_DEEP_ANALYSIS';
    if (fl?.decision && !recommended && !fl?.decision?.deep_ai_started) {
      const proceed = window.confirm(
        'Deep AI is not recommended by First-Level decision for this failure. Start Deep AI anyway? (Never auto-started.)'
      );
      if (!proceed) return;
    }

    setDeepAiLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const glean = gleanSearchResults[testId] || firstLevelAiResults[testId] || {};
      const response = await api.post(`${API_BASE}/deep-ai`, {
        test_result: buildFailedAnalysisTestResult(result),
        glean_tickets: glean.enriched_tickets || [],
        glean_snippets: glean.glean_snippets || [],
        user_requested: true,
        tag: analysisTag || tag || selectedSavedTag || '',
        force: !!force,
      });
      const data = response.data || {};
      if (!data.success) {
        throw new Error(data.error || 'Deep AI analysis failed');
      }
      setDeepAiResults(prev => ({ ...prev, [testId]: data }));
      if (data.session_id) {
        // Shared session model with Cursor AI column.
        setCursorAiSessions(prev => ({ ...prev, [testId]: data.session_id }));
      }
      if (data.intelligent_triage) {
        setIntelligentTriageByTestcase(prev => ({ ...prev, [testId]: data.intelligent_triage }));
      }
      setFollowUpHistory(followUpHistoryByTestcase[testId] || []);
      setFollowUpMode('ask');
      resetDeepAiActionUi();
      setTriageAnalysisModal({
        kind: 'deep',
        testcase_name: result.testcase_name,
        testcase_id: testId,
        resultRow: result,
        session_id: data.session_id || cursorAiSessions[testId] || null,
        ...data,
      });
    } catch (error) {
      alert(`Deep AI analysis failed: ${error.response?.data?.error || error.message}`);
    } finally {
      setDeepAiLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const handleAutoTestFixSuggest = async (result) => {
    const testId = result.testcase_id;
    if (!testId) return;
    
    setAutoTestFixLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const response = await api.post(`${API_BASE_URL}/api/agents/triage/auto-fix-suggest`, {
        test_result: {
          testcase_id: testId,
          testcase_name: result.testcase_name,
          status: result.status,
          failure_stage: result.failure_stage,
          exception_summary: result.exception_summary,
          agave_task_id: result.agave_task_id,
          test_log_url: result.test_log_url
        }
      });
      
      if (response.data.success) {
        setAutoTestFixResults(prev => ({
          ...prev,
          [testId]: response.data
        }));
      }
    } catch (error) {
      console.error('Auto test fix suggestion failed:', error);
      const errorMessage = error.response?.data?.error || error.message || 'Unknown error occurred';
      
      // For now, provide a fallback simulation if the endpoint isn't ready
      if (error.response?.status === 404 || errorMessage.includes('not available')) {
        console.log('Using fallback simulation for Auto Test Fix');
        setAutoTestFixResults(prev => ({
          ...prev,
          [testId]: {
            success: true,
            fix_type: "config",
            fix_suggestion: {
              description: "Increase timeout value in test configuration",
              code_changes: [
                {
                  file: "test_config.py",
                  changes: "timeout = 300  # Increased from 60 seconds"
                }
              ]
            },
            simulation_mode: true
          }
        }));
        return;
      }
      
      alert(`Auto test fix suggestion failed: ${errorMessage}`);
    } finally {
      setAutoTestFixLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const handleReviewTestFix = (result, autoFixResult) => {
    // Open modal to review the suggested fix
    alert(`Fix Review:\n\nType: ${autoFixResult.fix_type}\nDescription: ${autoFixResult.fix_suggestion.description}\n\nFiles to change: ${autoFixResult.fix_suggestion.code_changes?.length || 0}`);
  };

  const handleApproveTestFix = async (result, autoFixResult) => {
    const testId = result.testcase_id;
    if (!testId) return;
    
    if (!window.confirm('Are you sure you want to create a Change Request with the suggested fix?')) {
      return;
    }
    
    setCrApprovalLoading(prev => ({ ...prev, [testId]: true }));
    try {
      const response = await api.post(`${API_BASE_URL}/api/agents/triage/approve-fix`, {
        test_result: {
          testcase_id: testId,
          testcase_name: result.testcase_name,
          status: result.status,
          failure_stage: result.failure_stage,
          exception_summary: result.exception_summary,
          agave_task_id: result.agave_task_id
        },
        fix_suggestion: autoFixResult.fix_suggestion,
        original_test_result: result
      });
      
      if (response.data.success) {
        // Update the auto test fix results with CR information
        setAutoTestFixResults(prev => ({
          ...prev,
          [testId]: {
            ...prev[testId],
            change_request: response.data.change_request
          }
        }));
        alert(`Change Request created successfully: ${response.data.change_request.change_id}`);
      }
    } catch (error) {
      console.error('CR creation failed:', error);
      alert(`Change Request creation failed: ${error.response?.data?.error || error.message}`);
    } finally {
      setCrApprovalLoading(prev => ({ ...prev, [testId]: false }));
    }
  };

  const updateFluxJob = (testId, patch) => {
    setFluxJobs(prev => {
      const next = { ...prev, [testId]: { ...(prev[testId] || {}), ...patch } };
      fluxJobsRef.current = next;
      return next;
    });
  };

  const handleFluxQuickFix = async (result) => {
    const testId = result.testcase_id;
    if (!testId) return;
    const jiraKey = fluxFirstJiraKey(result);
    if (!jiraKey) {
      alert('Add a Jira ticket first.');
      return;
    }
    const taskId = String(result.agave_task_id || '').trim();
    const fallback = fluxNutestTargetBranch(result, currentBranch);
    setFluxBranchPrompt({
      result,
      taskId,
      branch: fallback,
      loading: Boolean(taskId),
      error: taskId ? null : 'No Jita Task ID on this row; enter the nutest branch.',
    });
    if (!taskId) return;
    try {
      const { data } = await api.get(`${FLUX_API}/nutest-branch`, {
        params: { task_id: taskId },
        timeout: 30000,
      });
      const fromJita = fluxNutestTargetBranch(
        { 'nutest-py3-tests_branch': data?.nutest_branch || data?.['nutest-py3-tests_branch'] },
        fallback,
      );
      setFluxBranchPrompt(prev => {
        if (!prev || prev.result?.testcase_id !== testId) return prev;
        return {
          ...prev,
          branch: fromJita || prev.branch || '',
          loading: false,
          error: fromJita ? null : (data?.error || 'JITA did not return nutest-py3-tests_branch.'),
        };
      });
    } catch (err) {
      const message = err.response?.data?.error || err.message || 'Failed to fetch nutest branch from JITA';
      setFluxBranchPrompt(prev => {
        if (!prev || prev.result?.testcase_id !== testId) return prev;
        return { ...prev, loading: false, error: message, branch: prev.branch || fallback };
      });
    }
  };

  const confirmFluxQuickFix = async () => {
    const prompt = fluxBranchPrompt;
    const result = prompt?.result;
    const testId = result?.testcase_id;
    const jiraKey = fluxFirstJiraKey(result);
    const targetBranch = fluxNutestTargetBranch({ nutest_branch: prompt?.branch }, currentBranch);
    if (!testId || !jiraKey) return;
    if (!targetBranch) {
      alert('Enter a nutest target branch (for example ganges-7.5-stable).');
      return;
    }
    setFluxBranchPrompt(null);
    updateFluxJob(testId, {
      status: 'starting',
      error: null,
      ticket: null,
      rerun: null,
      startedAt: Date.now(),
      resumeAttempted: false,
    });
    fluxResumeInFlight.current[testId] = false;
    try {
      const resp = await api.post(`${FLUX_API}/quick-fix`, {
        jira_key: jiraKey,
        target_branch: targetBranch,
        log_url: null,
        send_test_fix: true,
        update_jira: true,
        pause_for_review: true,
        testcase_id: testId,
        testcase_name: result.testcase_name,
      }, { timeout: 60000 });
      const data = resp.data || {};
      const recordId = data.record_id || data.id;
      updateFluxJob(testId, {
        record_id: recordId,
        status: data.status || 'queued',
        ticket: data,
        error: null,
      });
    } catch (err) {
      const data = err.response?.data || {};
      if (data.require_key_setup) {
        alert(data.error || 'Cursor API key and Gerrit HTTP password are required. Configure them in Settings → API Keys.');
      } else if (data.code === 'CREDENTIALS_EXPIRED') {
        alert(data.error || 'Session expired. Please re-login.');
      } else {
        alert(data.error || err.message || 'Flux Quick Fix failed');
      }
      updateFluxJob(testId, {
        status: 'error',
        error: data.error || err.message || 'Flux Quick Fix failed',
      });
    }
  };

  const handleFluxCreateGerritCr = async (result) => {
    const testId = result.testcase_id;
    const job = fluxJobsRef.current[testId] || fluxJobs[testId];
    const recordId = job?.record_id;
    if (!testId || !recordId) return;
    fluxResumeInFlight.current[testId] = true;
    updateFluxJob(testId, { resuming: true, resumeAttempted: true, error: null });
    try {
      const resp = await api.post(`${FLUX_API}/tickets/${recordId}/resume`, {}, { timeout: 60000 });
      const data = resp.data || {};
      updateFluxJob(testId, {
        status: data.status || 'fixing',
        ticket: { ...(job.ticket || {}), ...data },
        resuming: false,
      });
    } catch (err) {
      const data = err.response?.data || {};
      fluxResumeInFlight.current[testId] = false;
      alert(data.error || err.message || 'Failed to resume Flux pipeline');
      updateFluxJob(testId, {
        resuming: false,
        resumeAttempted: false,
        error: data.error || err.message || 'Failed to resume Flux pipeline',
      });
    }
  };

  const handleFluxRerunWithCr = async (result) => {
    const testId = result.testcase_id;
    const job = fluxJobsRef.current[testId] || fluxJobs[testId];
    const gerritUrl = job?.ticket?.gerrit_url;
    if (!testId || !gerritUrl) return;
    if (!result.agave_task_id) {
      alert('No JITA task id available to retrigger.');
      return;
    }
    updateFluxJob(testId, { rerunning: true, rerun: null, error: null });
    try {
      const resp = await api.post(`${API_BASE}/retrigger`, {
        tests: [{
          testcase_id: result.testcase_id,
          testcase_name: result.testcase_name,
          agave_task_id: result.agave_task_id,
        }],
        overrides: { patch_url: gerritUrl },
        sync_to_tcms: false,
      });
      const data = resp.data || {};
      const rerunId = data.rerun_task_ids?.[0]
        || (data.results || []).find(r => r.success && r.rerun_task_id)?.rerun_task_id
        || null;
      updateFluxJob(testId, {
        rerunning: false,
        rerun: {
          success: !!(data.success || rerunId),
          rerun_task_id: rerunId,
          error: data.error || (data.results || []).find(r => !r.success)?.error || null,
        },
      });
    } catch (err) {
      const data = err.response?.data || {};
      updateFluxJob(testId, {
        rerunning: false,
        rerun: { success: false, error: data.error || err.message || 'Retrigger failed' },
      });
      alert(data.error || err.message || 'Rerun with CR failed');
    }
  };

  useEffect(() => {
    fluxJobsRef.current = fluxJobs;
  }, [fluxJobs]);

  const fluxPollKey = Object.values(fluxJobs)
    .filter(job => job?.record_id && fluxShouldPoll(job.status, job.ticket, job))
    .map(job => String(job.record_id))
    .sort()
    .join(',');

  useEffect(() => {
    if (!fluxPollKey) return undefined;
    let cancelled = false;
    const poll = async () => {
      const jobs = fluxJobsRef.current || {};
      await Promise.all(Object.entries(jobs).map(async ([testId, job]) => {
        if (!job?.record_id || !fluxShouldPoll(job.status, job.ticket, job)) return;
        try {
          const { data } = await api.get(`${FLUX_API}/tickets/${job.record_id}`);
          if (cancelled) return;
          const ticket = data || {};
          const startedAt = job.startedAt || Date.now();
          const timedOut = Date.now() - startedAt > FLUX_MAX_WAIT_MS;
          const pipelineError = fluxPipelineError(ticket);
          let timeoutError = null;
          if (!pipelineError && timedOut && !fluxHasRootCause(ticket) && !fluxHasGerritCr(ticket)) {
            timeoutError = 'Flux Quick Fix timed out after 15 minutes waiting for root cause analysis.';
          }
          updateFluxJob(testId, {
            status: pipelineError ? 'failed' : (ticket.status || job.status),
            ticket,
            error: pipelineError || timeoutError || null,
          });
          if (
            !pipelineError
            && !timeoutError
            && fluxCanCreateGerritCr(ticket)
            && !job.resumeAttempted
            && !fluxResumeInFlight.current[testId]
          ) {
            fluxResumeInFlight.current[testId] = true;
            updateFluxJob(testId, { resumeAttempted: true, resuming: true, error: null });
            try {
              const resp = await api.post(`${FLUX_API}/tickets/${job.record_id}/resume`, {}, { timeout: 60000 });
              if (cancelled) return;
              const resumed = resp.data || {};
              updateFluxJob(testId, {
                resuming: false,
                status: resumed.status || 'fixing',
                ticket: { ...ticket, ...resumed },
              });
            } catch (err) {
              if (cancelled) return;
              const message = err.response?.data?.error || err.message || 'Failed to resume Flux pipeline';
              fluxResumeInFlight.current[testId] = false;
              updateFluxJob(testId, {
                resuming: false,
                resumeAttempted: false,
                error: message,
              });
            }
          }
        } catch (err) {
          if (cancelled) return;
          const message = err.response?.data?.error || err.message || 'Failed to poll Flux ticket';
          updateFluxJob(testId, { error: message });
        }
      }));
    };
    poll();
    const timer = setInterval(poll, FLUX_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [fluxPollKey]);

  // --------------- End Intelligent Triage handlers ---------------

  const renderHistoryCell = (result, sameBranch) => {
    if (!analysisTag) return <span className="history-unknown">—</span>;
    const testName = result.testcase_name;
    const key = `${testName}|${sameBranch}`;
    const cached = historyCache[key];
    if (cached) {
      return (
        <div className="history-runs">
          {cached.slice(0, 3).map((run, i) => (
            <span key={i} className="history-run-item">
              {run.status === 'passed' ? (
                <span className="history-tick" title="Passed">✓</span>
              ) : run.status === 'failed' ? (
                run.jira_ticket ? (
                  <a href={`${JIRA_URL}${run.jira_ticket}`} target="_blank" rel="noopener noreferrer" className="jira-link">{run.jira_ticket}</a>
                ) : run.comment ? (
                  <span className="history-comment" title={run.comment}>💬</span>
                ) : (
                  <span className="history-cross" title="Failed">✗</span>
                )
              ) : (
                <span className="history-unknown">-</span>
              )}
            </span>
          ))}
        </div>
      );
    }
    return <span className="history-loading">Loading…</span>;
  };

  const renderCell = (colId, result, index) => {
    switch (colId) {
      case 'testcase_name':
        return <td key={colId} className="testcase-name" title={result.testcase_name}>{result.testcase_name || '-'}</td>;
      case 'jita_task': {
        const taskId = result.agave_task_id || '';
        const href = taskId ? jitaResultsUrl(taskId) : '';
        return (
          <td key={colId} className="jita-task-cell">
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer" className="jita-task-link" title={taskId}>
                {taskId}
              </a>
            ) : '-'}
          </td>
        );
      }
      case 'complete_logs_path': {
        const href = buildCompleteLogsPath(result.test_log_url, result.testcase_name);
        return (
          <td key={colId} className="complete-logs-path-cell">
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer" className="complete-logs-path-link" title={href}>
                {href}
              </a>
            ) : '-'}
          </td>
        );
      }
      case 'regression_owner':
        return <td key={colId} className="owner-cell">{result.regression_owner || 'Unknown'}</td>;
      case 'status': {
        const s = (result.status || 'failed').toLowerCase();
        const statusLabel = s.charAt(0).toUpperCase() + s.slice(1);
        const badgeCls = s === 'failed' || s === 'failure' ? 'badge-failed'
          : s === 'skipped' || s === 'skip' ? 'badge-skipped'
          : s === 'warning' || s === 'warn' ? 'badge-warning'
          : s === 'killed' || s === 'terminated' || s === 'cancelled' ? 'badge-killed'
          : s === 'pending' || s === 'waiting' || s === 'running' || s === 'started' ? 'badge-pending'
          : 'badge-failed';
        return <td key={colId}><span className={`badge ${badgeCls}`}>{statusLabel}</span></td>;
      }
      case 'failure_stage':
        return <td key={colId}>{getFailureStageBadge(result.failure_stage)}</td>;
      case 'exception_summary':
        return <td key={colId} className="exception-summary-cell" title={result.exception_summary}>{result.exception_summary || '-'}</td>;
      case 'ai_summary': {
        const summaryLoading = aiSummaryLoading[result.testcase_id];
        return (
          <td key={colId} className="ai-summary-cell">
            {summaryLoading ? (
              <span className="ai-summary-loading">Generating AI Summary…</span>
            ) : result.ai_summary ? (
              <span title={result.ai_summary}>{result.ai_summary}</span>
            ) : (
              <button
                type="button"
                className="btn-ai-summary"
                onClick={() => handleAiSummarySingle(result)}
                title="Generate AI summary for this testcase"
              >
                AI Summary
              </button>
            )}
          </td>
        );
      }
      case 'jira_tickets': {
        const tickets = result.jira_tickets || [];
        const added = jiraAdd[result.testcase_id];
        return (
          <td key={colId}>
            <div className="jira-tickets">
              {tickets.map((ticket, idx) => (
                <a key={idx} href={`${JIRA_URL}${ticket}`} target="_blank" rel="noopener noreferrer" className="jira-link">{ticket}</a>
              ))}
              {added && <a href={`${JIRA_URL}${added}`} target="_blank" rel="noopener noreferrer" className="jira-link">{(added.length > 12 ? added.slice(0, 12) + '…' : added)}</a>}
            </div>
            <input
              type="text"
              className="jira-add-input"
              placeholder="Add ticket"
              value={added || ''}
              onChange={e => setJiraAdd(prev => ({ ...prev, [result.testcase_id]: e.target.value }))}
            />
          </td>
        );
      }
      case 'jira_issue_type': {
        const tickets = collectResultJiraTickets(result);
        if (!tickets.length) return <td key={colId} className="jira-meta-cell">-</td>;
        const labels = jiraBugTypesForResult(result, jiraTicketDetails);
        return (
          <td key={colId} className="jira-meta-cell">
            {labels.map((label, idx) => {
              const pending = !jiraTicketDetails[tickets[idx]];
              const cls = label === 'Product Bug' ? 'jira-bug-product'
                : label === 'Test Bug' ? 'jira-bug-test'
                : label === 'Environment' ? 'jira-bug-env'
                : label === 'Flaky' ? 'jira-bug-flaky'
                : 'jira-bug-other';
              return (
                <span key={`${tickets[idx] || idx}-${label}`}>
                  {idx > 0 ? ', ' : ''}
                  <span className={`jira-bug-chip ${cls}`} title={tickets[idx] || ''}>
                    {pending ? 'Loading' : label}
                  </span>
                </span>
              );
            })}
          </td>
        );
      }
      case 'jira_ticket_status': {
        const tickets = collectResultJiraTickets(result);
        if (!tickets.length) return <td key={colId} className="jira-meta-cell">-</td>;
        const labels = jiraStatusesForResult(result, jiraTicketDetails);
        return (
          <td key={colId} className="jira-meta-cell">
            {labels.map((label, idx) => (
              <span key={`${tickets[idx] || idx}-${label}`}>
                {idx > 0 ? ', ' : ''}
                <span className="jira-status-chip" title={tickets[idx] || ''}>{label}</span>
              </span>
            ))}
          </td>
        );
      }
      case 'flux_quick_fix': {
        const job = fluxJobs[result.testcase_id] || {};
        const ticket = job.ticket || {};
        const jiraKey = fluxFirstJiraKey(result);
        const status = String(job.status || ticket.status || '').toLowerCase();
        const confidence = fluxConfidencePercent(ticket.confidence);
        const categoryLabel = fluxCategoryLabel(ticket.failure_category);
        const canCreateCr = fluxCanCreateGerritCr(ticket);
        const gerritUrl = ticket.gerrit_url || '';
        const gerritId = ticket.gerrit_change_id || '';
        const running = fluxIsRunning(job.status, ticket, job);
        const rerunHref = job.rerun?.rerun_task_id ? jitaResultsUrl(job.rerun.rerun_task_id) : '';
        const statusLabel = running ? 'Running' : (ticket.status || job.status);
        return (
          <td key={colId} className="flux-quick-fix-cell">
            <button
              type="button"
              className="btn-flux-quick-fix"
              disabled={!jiraKey || running || job.resuming}
              onClick={() => handleFluxQuickFix(result)}
              title={jiraKey ? `Start Flux Quick Fix for ${jiraKey}` : 'Add a Jira ticket first'}
            >
              {running ? 'Running' : 'Flux Quick Fix'}
            </button>
            {job.error && <div className="flux-job-error" title={job.error}>{job.error}</div>}
            {statusLabel && status !== 'starting' && (
              <div className="flux-job-status">Status: {statusLabel}</div>
            )}
            {(confidence != null || categoryLabel) && (
              <div className="flux-review-meta">
                {confidence != null && <span className="flux-confidence">{confidence}%</span>}
                {categoryLabel && (
                  <span className={`flux-category-chip flux-category-${String(ticket.failure_category || '').toLowerCase()}`}>
                    {categoryLabel}
                  </span>
                )}
              </div>
            )}
            {ticket.root_cause && (
              <details className="flux-rca">
                <summary>View RCA</summary>
                <pre className="flux-rca-text">{ticket.root_cause}</pre>
                {ticket.remediation_strategy && (
                  <div className="flux-remediation">
                    <strong>Remediation:</strong> {ticket.remediation_strategy}
                  </div>
                )}
              </details>
            )}
            {canCreateCr && !gerritUrl && !job.resumeAttempted && (
              <button
                type="button"
                className="btn-flux-create-cr"
                disabled={job.resuming || running}
                onClick={() => handleFluxCreateGerritCr(result)}
                title="Approve and create a Gerrit CR"
              >
                {job.resuming ? 'Creating CR…' : 'Create Gerrit CR'}
              </button>
            )}
            {(gerritUrl || gerritId) && (
              <a
                href={gerritUrl || undefined}
                target="_blank"
                rel="noopener noreferrer"
                className="flux-gerrit-link"
                title={gerritUrl}
              >
                CR: {gerritId || gerritUrl}
              </a>
            )}
            {gerritUrl && (
              <button
                type="button"
                className="btn-flux-rerun-cr"
                disabled={job.rerunning}
                onClick={() => handleFluxRerunWithCr(result)}
                title="Retrigger this test with the Gerrit CR patch"
              >
                {job.rerunning ? 'Rerunning…' : 'Rerun with CR'}
              </button>
            )}
            {job.rerun?.rerun_task_id && (
              rerunHref ? (
                <a href={rerunHref} target="_blank" rel="noopener noreferrer" className="flux-rerun-link">
                  JITA: {job.rerun.rerun_task_id}
                </a>
              ) : (
                <div className="flux-rerun-link">JITA: {job.rerun.rerun_task_id}</div>
              )
            )}
            {job.rerun?.error && <div className="flux-job-error">{job.rerun.error}</div>}
          </td>
        );
      }
      case 'comment':
        return (
          <td key={colId}>
            <input
              type="text"
              className="comment-input"
              value={commentEdits[result.testcase_id] !== undefined ? commentEdits[result.testcase_id] : (result.comments || '')}
              onChange={e => setCommentEdits(prev => ({ ...prev, [result.testcase_id]: e.target.value }))}
              placeholder="Comment"
            />
          </td>
        );
      case 'update_jita':
        return (
          <td key={colId}>
            <button
              type="button"
              className="btn-update-jita"
              disabled={updateLoading[result.testcase_id]}
              onClick={() => handleUpdateJita(result)}
            >
              {updateLoading[result.testcase_id] ? 'Updating…' : 'Update Jita'}
            </button>
          </td>
        );
      case 'issue_type':
        return <td key={colId}>{getIssueTypeBadge(result.issue_type)}</td>;
      case 'suggestion_by_ai_agent':
        return <td key={colId} className="suggestion-cell" title={result.suggestion_by_ai_agent}>{result.suggestion_by_ai_agent || '-'}</td>;
      case 'intermittent':
        return <td key={colId}>{getIntermittentLabel(result)}</td>;
      case 'rdm_analysis': {
        const isSkipped = (result.status || '').toLowerCase() === 'skipped' || (result.status || '').toLowerCase() === 'skip';
        if (!isSkipped) return <td key={colId} className="rdm-cell"><span className="rdm-na">—</span></td>;
        const rdm = result.rdm_info;
        const rdmAi = rdmAiResults[result.testcase_id];
        const rdmAiLoad = rdmAiLoading[result.testcase_id];
        const rdmSkill = rdmSkillResults[result.testcase_id];
        const rdmSkillLoad = rdmSkillLoading[result.testcase_id];
        const wfLoad = rdmWorkflowLoading[result.testcase_id];
        const jarvisResults = rdm?.jarvis_results || [];
        const renderJarvisStatus = () => (
          jarvisResults.length > 0 ? (
            <div className="rdm-jarvis-status">
              {jarvisResults.map((jr, idx) => (
                <div key={jr.node_id || jr.node_name || idx} className={jr.success ? 'rdm-jarvis-ok' : 'rdm-jarvis-fail'}>
                  {jr.success
                    ? `Jarvis: ${jr.node_name} disabled (is_enabled=${String(jr.is_enabled)})`
                    : `Jarvis disable failed for ${jr.node_name || 'node'}: ${jr.error || 'unknown error'}`}
                </div>
              ))}
            </div>
          ) : null
        );
        const rerunTaskId = rdm?.retrigger?.results?.[0]?.rerun_task_id;
        return (
          <td key={colId} className="rdm-cell">
            {!rdm ? (
              <span className="rdm-pending">Select &amp; click "Analyze Skipped"</span>
            ) : rdm.rdm_found === false ? (
              <span className="rdm-no-deploy">No RDM deployment found</span>
            ) : rdm.approved ? (
              <div className="rdm-approved">
                <span className="rdm-badge rdm-badge-approved">Approved</span>
                <code className="rdm-approved-comment">{rdm.generated_comment || result.comments}</code>
                {renderJarvisStatus()}
                {rerunTaskId && (
                  <a href={jitaResultsUrl(rerunTaskId)} target="_blank" rel="noopener noreferrer" className="rdm-link">
                    Rerun task {rerunTaskId}
                  </a>
                )}
                {rdm.workflow_error && <div className="rdm-jarvis-fail">{rdm.workflow_error}</div>}
                {rdm.rdm_link && <a href={rdm.rdm_link} target="_blank" rel="noopener noreferrer" className="rdm-link">RDM Details</a>}
              </div>
            ) : rdm.pattern_matched ? (
              <div className="rdm-matched">
                <span className="rdm-badge rdm-badge-matched">Pattern Matched</span>
                {rdm.pattern_id && <span className="rdm-pattern-id">{rdm.pattern_id}</span>}
                <div className="rdm-comment-preview">
                  <strong>Comment:</strong> <code>{rdm.generated_comment}</code>
                </div>
                {rdm.failed_nodes && rdm.failed_nodes.length > 0 && (
                  <div className="rdm-failed-nodes">
                    <strong>Nodes:</strong> {rdm.failed_nodes.join(', ')}
                  </div>
                )}
                {rdm.pattern_jira && (
                  <div className="rdm-pattern-jira">
                    <strong>Jira:</strong>{' '}
                    <a href={`${JIRA_URL}${rdm.pattern_jira}`} target="_blank" rel="noopener noreferrer" className="jira-link">{rdm.pattern_jira}</a>
                  </div>
                )}
                <div className="rdm-desc">{rdm.pattern_description}</div>
                {renderJarvisStatus()}
                <div className="rdm-actions">
                  <button
                    type="button"
                    className="btn-rdm-approve"
                    disabled={rdmAiLoad || wfLoad}
                    onClick={() => handleRdmApproveComment(result.testcase_id, rdm.generated_comment, rdm.pattern_jira || '')}
                    title={rdmNeedsNodeDisable(rdm)
                      ? 'Update JITA comment and disable failed node(s) in Jarvis'
                      : 'Update JITA comment'}
                  >
                    {rdmAiLoad
                      ? 'Updating…'
                      : rdmNeedsNodeDisable(rdm)
                        ? 'Approve & Disable Node'
                        : 'Approve & Update'}
                  </button>
                  {rdmNeedsRerun(rdm) && (
                    <button
                      type="button"
                      className="btn-rdm-workflow"
                      disabled={rdmAiLoad || wfLoad}
                      onClick={() => handleRdmAutoWorkflow([result], { parentTaskId: result.agave_task_id })}
                      title="Pattern-matched workflow: update comment, disable node if needed, then re-run the test"
                    >
                      {wfLoad ? 'Running…' : 'Analyze, Fix & Re-run'}
                    </button>
                  )}
                </div>
                {rdm.rdm_link && <a href={rdm.rdm_link} target="_blank" rel="noopener noreferrer" className="rdm-link">RDM Details</a>}
              </div>
            ) : (
              <div className="rdm-unmatched">
                <span className="rdm-badge rdm-badge-unmatched">No Pattern Match</span>
                <div className="rdm-msg-preview" title={rdm.rdm_message}>
                  {(rdm.rdm_message || '').substring(0, 150)}
                </div>
                <div className="rdm-analyze-actions">
                  <button
                    type="button"
                    className="btn-rdm-analyze"
                    disabled={rdmAiLoad || rdmSkillLoad}
                    onClick={() => handleRdmAiAnalyze(result)}
                    title="First Level Analysis: Glean search of the RDM error message"
                  >
                    {rdmAiLoad ? 'Analyzing…' : rdmAi ? 'Re-run First Level' : 'First Level Analysis'}
                  </button>
                  <button
                    type="button"
                    className="btn-rdm-skill-analyze"
                    disabled={rdmAiLoad || rdmSkillLoad}
                    onClick={() => handleRdmSkillAnalyze(result)}
                    title={`AI RDM Failure Analysis via triage-rdm-deployment-failure${rdm.rdm_link ? ` — ${rdm.rdm_link}` : ''}`}
                  >
                    {rdmSkillLoad ? 'RDM analyzing…' : rdmSkill ? 'Re-run AI RDM Failure Analysis' : 'AI RDM Failure Analysis'}
                  </button>
                </div>
                {rdmAi && (
                  <div className="rdm-ai-result">
                    <div className="rdm-ai-summary">{rdmAi.ai_summary}</div>
                    {rdmAi.jira_refs && rdmAi.jira_refs.length > 0 && (
                      <div className="rdm-ai-jiras">
                        {rdmAi.jira_refs.map(j => (
                          <a key={j} href={`${JIRA_URL}${j}`} target="_blank" rel="noopener noreferrer" className="jira-link">{j}</a>
                        ))}
                      </div>
                    )}
                    {rdmAi.suggested_comment && (
                      <div className="rdm-ai-suggest">
                        <strong>Suggested:</strong> <code>{rdmAi.suggested_comment}</code>
                        <button
                          type="button"
                          className="btn-rdm-approve btn-rdm-approve-sm"
                          disabled={rdmAiLoad}
                          onClick={() => handleRdmApproveComment(
                            result.testcase_id,
                            rdmAi.suggested_comment,
                            rdmAi.jira_ticket || rdmAi.jira_refs?.[0] || '',
                          )}
                        >
                          {rdmAiLoad ? '…' : 'Approve'}
                        </button>
                      </div>
                    )}
                    <button
                      type="button"
                      className="btn-rdm-add-pattern"
                      onClick={() => openAddPatternModal(result, rdmAi)}
                      title="Save this analysis as a pattern for future auto-triage and next actions"
                    >
                      Add Pattern
                    </button>
                  </div>
                )}
                {rdmSkill && (
                  <div className="rdm-skill-result">
                    <div className="rdm-skill-header">
                      <span className="rdm-badge rdm-badge-skill">RDM skill</span>
                      <span className="rdm-skill-name">{rdmSkill.skill_used || 'triage-rdm-deployment-failure'}</span>
                      {(textOrEmpty(rdmSkill.issue_category) || textOrEmpty(rdmSkill.classification)) && (
                        <span className="rdm-skill-category">{textOrEmpty(rdmSkill.issue_category) || textOrEmpty(rdmSkill.classification)}</span>
                      )}
                    </div>
                    {rdmMcpHealthBanners(rdmSkill.mcp_health).map(banner => (
                      <div key={banner.key} className="rdm-mcp-banner" role="status">
                        <strong>{banner.title}</strong>
                        <span>{banner.detail}</span>
                      </div>
                    ))}
                    <div className="rdm-ai-summary">{textOrEmpty(rdmSkill.root_cause) || textOrEmpty(rdmSkill.ai_summary)}</div>
                    {textOrEmpty(rdmSkill.recommended_action) && (
                      <div className="rdm-skill-action">
                        Decision: <strong>{rdmRecommendedActionLabel(rdmSkill)}</strong>
                        {' '}
                        <code>{textOrEmpty(rdmSkill.recommended_action)}</code>
                      </div>
                    )}
                    {(() => {
                      const skillTickets = [...new Set([
                        ...(rdmSkill.jira_refs || []),
                        ...(rdmSkill.enriched_tickets || []).map(t => t.ticket || t.key).filter(Boolean),
                      ])];
                      if (!skillTickets.length) return null;
                      return (
                        <div className="rdm-ai-jiras">
                          {skillTickets.map(j => (
                            <a key={j} href={`${JIRA_URL}${j}`} target="_blank" rel="noopener noreferrer" className="jira-link">{j}</a>
                          ))}
                        </div>
                      );
                    })()}
                    {rdmSkill.suggested_comment && (
                      <div className="rdm-ai-suggest">
                        <strong>Suggested:</strong> <code>{rdmSkill.suggested_comment}</code>
                        <button
                          type="button"
                          className="btn-rdm-approve btn-rdm-approve-sm"
                          disabled={rdmAiLoad}
                          onClick={() => handleRdmApproveComment(
                            result.testcase_id,
                            rdmSkill.suggested_comment,
                            rdmSkill.jira_ticket || rdmSkill.jira_refs?.[0] || '',
                          )}
                        >
                          {rdmAiLoad ? '…' : 'Approve comment'}
                        </button>
                      </div>
                    )}
                    <div className="rdm-skill-actions">
                      {rdmSkill.jira_create?.needed && (
                        <button
                          type="button"
                          className="btn-rdm-create-jira"
                          onClick={() => openRdmSkillJiraCreate(rdmSkill)}
                          title="Copy triage report and open Jira create"
                        >
                          Create {rdmSkill.suggested_jira_project || rdmSkill.jira_create?.project || 'Jira'} ticket
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn-view-analysis"
                        onClick={() => {
                          const { analysis: nestedAnalysis, ...rdmSkillRest } = rdmSkill;
                          setTriageAnalysisModal({
                            kind: 'rdm_skill',
                            testcase_name: result.testcase_name,
                            testcase_id: result.testcase_id,
                            ...rdmSkillRest,
                            root_cause: textOrEmpty(rdmSkill.root_cause) || textOrEmpty(nestedAnalysis?.root_cause),
                            ai_summary: textOrEmpty(rdmSkill.ai_summary),
                            classification: textOrEmpty(rdmSkill.classification) || textOrEmpty(nestedAnalysis?.classification),
                            suggested_fix: textOrEmpty(rdmSkill.suggested_fix) || textOrEmpty(nestedAnalysis?.suggested_fix),
                            triage_report: textOrEmpty(rdmSkill.triage_report) || textOrEmpty(nestedAnalysis?.triage_report),
                            jira_duplicates: rdmSkill.jira_duplicates || rdmSkill.jira_refs || [],
                            best_matching_ticket: rdmSkill.jira_ticket,
                            mcp_health: rdmSkill.mcp_health,
                            glean_ok: rdmSkill.glean_ok,
                            search_source: rdmSkill.search_source,
                          });
                        }}
                      >
                        View report
                      </button>
                      <button
                        type="button"
                        className="btn-rdm-add-pattern"
                        onClick={() => openAddPatternModal(result, rdmSkill)}
                        title="Save this skill analysis as a pattern"
                      >
                        Add Pattern
                      </button>
                    </div>
                  </div>
                )}
                {rdm.rdm_link && <a href={rdm.rdm_link} target="_blank" rel="noopener noreferrer" className="rdm-link">RDM Details</a>}
              </div>
            )}
          </td>
        );
      }
      case 'history_same_branch':
        return <td key={colId} className="history-cell">{renderHistoryCell(result, true)}</td>;
      case 'history_other_branch':
        return <td key={colId} className="history-cell">{renderHistoryCell(result, false)}</td>;
      case 'triage_genie_ticket':
        return (
          <td key={colId}>
            {result.triage_genie_ticket_id ? (
              <a href={`${JIRA_URL}${result.triage_genie_ticket_id}`} target="_blank" rel="noopener noreferrer" className="jira-link triage-genie-ticket">{result.triage_genie_ticket_id}</a>
            ) : '-'}
          </td>
        );
      case 'triage_genie_review': {
        const reviewUrl = triageGenieReviewUrl(result);
        return (
          <td key={colId}>
            {reviewUrl ? (
              <a
                href={reviewUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-tg-review"
                title="Open Triage Genie Review"
              >
                Review
              </a>
            ) : '-'}
          </td>
        );
      }
      case 'glean_search': {
        const gleanLoading = gleanSearchLoading[result.testcase_id];
        const gleanRes = gleanSearchResults[result.testcase_id];
        const enrichedTickets = gleanRes?.enriched_tickets || [];
        const openTickets = enrichedTickets.filter(t => t.is_open);
        return (
          <td key={colId} className="glean-search-cell">
            {gleanLoading ? (
              <span className="glean-search-loading">Searching Glean…</span>
            ) : gleanRes ? (
              gleanRes.error ? (
                <span className="glean-search-error" title={gleanRes.error}>Search failed</span>
              ) : (
                <div className="glean-search-result-inline">
                  <span className={`badge glean-issue-badge glean-issue-${(gleanRes.issue_type || '').replace(/\s+/g, '-').toLowerCase()}`}>
                    {gleanRes.issue_type || 'Unknown'}
                  </span>
                  {enrichedTickets.length > 0 && (
                    <span className="glean-jira-count" title={enrichedTickets.map(t => t.ticket).join(', ')}>
                      {enrichedTickets.length} ticket{enrichedTickets.length !== 1 ? 's' : ''}
                      {openTickets.length > 0 && <span className="glean-open-count"> ({openTickets.length} open)</span>}
                    </span>
                  )}
                  {openTickets.length > 0 && (
                    <a
                      href={openTickets[0].url || `${JIRA_URL}${openTickets[0].ticket}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="jira-link glean-top-ticket"
                      title={openTickets[0].jira_summary || openTickets[0].glean_title}
                    >
                      {openTickets[0].ticket}
                    </a>
                  )}
                  <button
                    type="button"
                    className="btn-glean-view"
                    onClick={() => setGleanDetailModal({ testcase_name: result.testcase_name, ...gleanRes })}
                  >
                    View
                  </button>
                </div>
              )
            ) : (
              <button
                type="button"
                className="btn-glean-search"
                onClick={() => handleGleanSearch(result)}
                title="Search Glean for matching failures and JIRA tickets"
              >
                Glean Search
              </button>
            )}
          </td>
        );
      }
      case 'cursor_ai_analysis': {
        const aiRes = cursorAiResults[result.testcase_id];
        const isLoading = cursorAiLoading[result.testcase_id];
        return (
          <td key={colId} className="cursor-ai-cell">
            {isLoading ? (
              <span className="cursor-ai-spinner">Analyzing…</span>
            ) : aiRes ? (
              aiRes.error ? (
                <span className="cursor-ai-error-text" title={aiRes.error}>Failed</span>
              ) : (
                <div className="cursor-ai-actions">
                  <button
                    type="button"
                    className="btn-link cursor-ai-view-btn"
                    onClick={() => {
                      setCursorAiDetailModal({
                        testcase_name: result.testcase_name,
                        _testcase_id: result.testcase_id,
                        _session_id: cursorAiSessions[result.testcase_id] || null,
                        ...aiRes,
                      });
                      setFollowUpInput('');
                      setFollowUpHistory(followUpHistoryByTestcase[result.testcase_id] || []);
                      setFollowUpMode('agent');
                    }}
                  >
                    {getCursorAiStatusBadge(result.testcase_id)} View
                  </button>
                  <button
                    type="button"
                    className="btn-cursor-ai-open-tab"
                    onClick={() => openCursorAiInTab(result)}
                    title="Open analysis in tab on this page"
                  >
                    Open Tab
                  </button>
                </div>
              )
            ) : (
              <button
                type="button"
                className="btn-cursor-ai-analyze"
                onClick={() => handleCursorAiAnalyze(result)}
                title="Deep analysis via Cursor AI + nutest source code"
              >
                Cursor AI
              </button>
            )}
          </td>
        );
      }
      case 'intelligent_triage': {
        const triageResult = intelligentTriageResults[result.testcase_id];
        const firstLevelLoading = firstLevelAiLoading[result.testcase_id];
        const firstLevelResult = firstLevelAiResults[result.testcase_id];
        const deepAiLoadingState = deepAiLoading[result.testcase_id];
        const deepAiResult = deepAiResults[result.testcase_id];
        const tgValidation = firstLevelResult?.tg_ticket_validation || deepAiResult?.tg_ticket_validation;
        const decision = firstLevelResult?.decision || intelligentTriageByTestcase[result.testcase_id]?.decision;
        const mcpHealth = firstLevelResult?.mcp_health || deepAiResult?.mcp_health || intelligentTriageByTestcase[result.testcase_id]?.mcp_health;
        const deepRecommended = decision?.deep_ai_recommended || decision?.outcome === 'NEEDS_DEEP_ANALYSIS';

        return (
          <td key={colId} className="intelligent-triage-cell">
            {triageResult ? (
              <div className="triage-results">
                <div className="triage-action-row">
                  <button
                    type="button"
                    className="btn-first-level-ai"
                    disabled={firstLevelLoading}
                    onClick={() => handleFirstLevelAiAnalysis(result)}
                    title="First Level AI: failure analysis plus Triage Genie ticket validation"
                  >
                    {firstLevelLoading ? 'Analyzing...' : firstLevelResult ? 'Re-run First Level' : 'First Level AI'}
                  </button>
                  <button
                    type="button"
                    className={`btn-deep-ai-analysis${deepRecommended ? ' deep-ai-recommended' : ''}`}
                    disabled={deepAiLoadingState}
                    onClick={() => handleDeepAiAnalysis(result)}
                    title={deepRecommended
                      ? 'Deep AI recommended by decision engine (user-triggered only; never auto-started)'
                      : 'Deep AI: skill-based log triage — user-triggered only'}
                  >
                    {deepAiLoadingState ? 'Analyzing...' : deepAiResult ? 'Re-run Deep AI' : (deepRecommended ? 'Deep AI (recommended)' : 'Deep AI Analysis')}
                  </button>
                </div>
                {decision && <DecisionBadge decision={decision} />}
                <McpHealthBadges mcpHealth={mcpHealth} />
                {firstLevelResult && (
                  <div className="first-level-result">
                    <span className={`badge glean-issue-badge glean-issue-${(firstLevelResult.issue_type || '').replace(/\s+/g, '-').toLowerCase()}`}>
                      {firstLevelResult.issue_type || 'First Level AI'}
                    </span>
                    {firstLevelResult.triage_confidence != null && (
                      <span className="badge triage-conf-badge" title="Independent triage_confidence (not averaged with intermittent)">
                        triage {Number(firstLevelResult.triage_confidence).toFixed(2)}
                      </span>
                    )}
                    {firstLevelResult.intermittent_confidence != null && (
                      <span className="badge intermittent-conf-badge" title="Independent intermittent_confidence">
                        intermittent {Number(firstLevelResult.intermittent_confidence).toFixed(2)}
                      </span>
                    )}
                    {tgValidation && (
                      <span className={`badge ${tgVerdictClass(tgValidation.verdict)}`}>
                        TG {tgValidation.verdict || 'Missing'}
                        {tgValidation.ticket ? ` ${tgValidation.ticket}` : ''}
                      </span>
                    )}
                    {(firstLevelResult.enriched_tickets || firstLevelResult.existing_issues || []).length > 0 && (
                      <span className="existing-issues-count">
                        {(firstLevelResult.enriched_tickets || firstLevelResult.existing_issues).length} existing ticket(s)
                      </span>
                    )}
                    {firstLevelResult.analysis && (
                      <div className="first-level-analysis-preview" title={firstLevelResult.analysis}>
                        {firstLevelResult.analysis}
                      </div>
                    )}
                    <button
                      type="button"
                      className="btn-view-analysis"
                      onClick={() => setTriageAnalysisModal({
                        kind: 'first_level',
                        testcase_name: result.testcase_name,
                        testcase_id: result.testcase_id,
                        resultRow: result,
                        ...firstLevelResult,
                      })}
                    >
                      View First Level
                    </button>
                  </div>
                )}
                {deepAiResult && (
                  <div className="deep-ai-result">
                    <span className={`badge triage-badge-${String(deepAiResult.confidence || '').toLowerCase() === 'high' || deepAiResult.confidence > 0.8 ? 'high' : 'medium'}`}>
                      Deep AI {deepAiResult.classification || 'Complete'}
                    </span>
                    {deepAiResult.skill_used && (
                      <span className="deep-ai-skill" title={deepAiResult.skill_used}>
                        {deepAiResult.skill_used}
                      </span>
                    )}
                    {deepAiResult.root_cause && (
                      <div className="deep-ai-summary" title={deepAiResult.root_cause}>
                        {deepAiResult.root_cause}
                      </div>
                    )}
                    <button
                      type="button"
                      className="btn-view-analysis"
                      onClick={() => {
                        setFollowUpHistory(followUpHistoryByTestcase[result.testcase_id] || []);
                        setFollowUpMode('ask');
                        setFollowUpInput('');
                        resetDeepAiActionUi();
                        setTriageAnalysisModal({
                          kind: 'deep',
                          testcase_name: result.testcase_name,
                          testcase_id: result.testcase_id,
                          resultRow: result,
                          session_id: deepAiResult.session_id || cursorAiSessions[result.testcase_id] || null,
                          ...deepAiResult,
                        });
                      }}
                    >
                      View Deep AI
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <button
                type="button"
                className="btn-intelligent-triage"
                onClick={() => handleIntelligentTriage(result)}
                title="Open First Level AI and Deep AI Analysis"
              >
                Analyze
              </button>
            )}
          </td>
        );
      }
      case 'auto_test_details': {
        const autoFixLoading = autoTestFixLoading[result.testcase_id];
        const autoFixResult = autoTestFixResults[result.testcase_id];
        const crLoading = crApprovalLoading[result.testcase_id];
        
        return (
          <td key={colId} className="auto-test-details-cell">
            {autoFixResult ? (
              <div className="auto-fix-results">
                {autoFixResult.fix_suggestion && (
                  <div className="fix-suggestion">
                    <div className="fix-type">
                      <span className={`badge fix-badge-${autoFixResult.fix_type || 'general'}`}>
                        {autoFixResult.fix_type || 'General Fix'}
                      </span>
                    </div>
                    <div className="fix-description" title={autoFixResult.fix_suggestion.description}>
                      {autoFixResult.fix_suggestion.description}
                    </div>
                    {autoFixResult.fix_suggestion.code_changes && (
                      <div className="fix-changes">
                        <strong>Changes:</strong> {autoFixResult.fix_suggestion.code_changes.length} file(s)
                      </div>
                    )}
                    <div className="fix-actions">
                      <button
                        type="button"
                        className="btn-review-fix"
                        onClick={() => handleReviewTestFix(result, autoFixResult)}
                        title="Review suggested changes"
                      >
                        Review Fix
                      </button>
                      <button
                        type="button"
                        className="btn-approve-fix"
                        disabled={crLoading}
                        onClick={() => handleApproveTestFix(result, autoFixResult)}
                        title="Approve and create Change Request"
                      >
                        {crLoading ? 'Creating CR...' : 'Approve & Create CR'}
                      </button>
                    </div>
                  </div>
                )}
                {autoFixResult.change_request && (
                  <div className="cr-status">
                    <a 
                      href={autoFixResult.change_request.gerrit_url} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="cr-link"
                    >
                      CR: {autoFixResult.change_request.change_id}
                    </a>
                    <span className={`cr-status-badge cr-status-${autoFixResult.change_request.status}`}>
                      {autoFixResult.change_request.status}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <button
                type="button"
                className="btn-auto-fix-suggest"
                disabled={autoFixLoading}
                onClick={() => handleAutoTestFixSuggest(result)}
                title="Generate automated test fix suggestions"
              >
                {autoFixLoading ? 'Analyzing...' : 'Suggest Fix'}
              </button>
            )}
          </td>
        );
      }
      case 'actions':
        return (
          <td key={colId} className="actions-cell">
            {result.test_log_url && (
              <a href={result.test_log_url} target="_blank" rel="noopener noreferrer" className="btn-link">View Log</a>
            )}
            {!cursorAiResults[result.testcase_id] && !cursorAiLoading[result.testcase_id] && (
              <button
                type="button"
                className="btn-cursor-ai-small"
                onClick={() => handleCursorAiAnalyze(result)}
                title="Analyze with Cursor AI"
              >
                AI
              </button>
            )}
          </td>
        );
      default:
        return <td key={colId}>-</td>;
    }
  };

  useEffect(() => {
    const needSame = visibleColumns.includes('history_same_branch');
    const needOther = visibleColumns.includes('history_other_branch');
    if ((!needSame && !needOther) || !analysisTag || !currentBranch || filteredResults.length === 0) return;
    filteredResults.forEach((result) => {
      const testName = result.testcase_name;
      if (!testName) return;
      const keySame = `${testName}|true`;
      const keyOther = `${testName}|false`;
      if (needSame && !historyCache[keySame]) {
        fetchHistory(testName, true);
      }
      if (needOther && !historyCache[keyOther]) {
        fetchHistory(testName, false);
      }
    });
  }, [visibleColumns, analysisTag, currentBranch, filteredResults, fetchHistory, historyCache]);

  const visibleIdsForHeader = filteredResults.map(r => r.testcase_id).filter(Boolean);
  const selectedVisibleCount = visibleIdsForHeader.filter(id => selectedRows.includes(id)).length;
  const allVisibleSelected = visibleIdsForHeader.length > 0 && selectedVisibleCount === visibleIdsForHeader.length;

  return (
    <div className="failed-analysis-container">
      <div className="failed-analysis-header">
        <h1>🔍 Failed Testcase Analysis - RegX-AI Agent</h1>
        <div className="header-actions">
          <button onClick={handleAnalyze} className="btn-primary" disabled={analyzing || loading}>
            {analyzing ? 'Analyzing...' : '🔍 Analyze Failed Testcases'}
          </button>
          <button type="button" className="btn-customize-columns" onClick={openCustomize}>
            Customize Columns
          </button>
          {savingResults && <span className="saving-indicator">Saving...</span>}
        </div>
      </div>

      <div className="analysis-controls">
        <div className="input-mode-selector">
          <label><input type="radio" value="tag" checked={inputMode === 'tag'} onChange={e => setInputMode(e.target.value)} /> Tag</label>
          <label><input type="radio" value="task_ids" checked={inputMode === 'task_ids'} onChange={e => setInputMode(e.target.value)} /> Task IDs</label>
        </div>

        {inputMode === 'tag' ? (
          <div className="form-group">
            <label>Tag <span className="required">*</span></label>
            <div className="tag-picker-wrapper" ref={tagPickerRef}>
              <div className="tag-picker-control" onClick={() => setTagPickerOpen(prev => !prev)}>
                <span className={`tag-picker-value ${selectedSavedTag ? '' : 'tag-picker-placeholder'}`}>
                  {selectedSavedTag || 'Select or add a tag'}
                </span>
                <span className="tag-picker-arrow">{tagPickerOpen ? '▲' : '▼'}</span>
              </div>
              {tagPickerOpen && (
                <div className="tag-picker-dropdown">
                  {savedTags.length > 0 && (
                    <div className="tag-picker-list">
                      {savedTags.map(t => {
                        const name = typeof t === 'string' ? t : t.name;
                        return (
                          <div
                            key={name}
                            className={`tag-picker-option ${selectedSavedTag === name ? 'tag-picker-option-active' : ''}`}
                            onClick={() => { handleSelectSavedTag(name); setTagPickerOpen(false); }}
                          >
                            <span className="tag-picker-option-name">{name}</span>
                            <button
                              type="button"
                              className="tag-picker-option-remove"
                              onClick={e => { e.stopPropagation(); handleDeleteTag(name); }}
                              title={`Remove "${name}"`}
                            >
                              Remove
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {savedTags.length === 0 && (
                    <div className="tag-picker-empty">No saved tags yet</div>
                  )}
                  <div className="tag-picker-add-section">
                    <input
                      type="text"
                      className="tag-picker-add-input"
                      placeholder="Enter new tag name…"
                      value={newTagInput}
                      onChange={e => setNewTagInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && newTagInput.trim()) { handleAddTag(); setTagPickerOpen(false); } }}
                      onClick={e => e.stopPropagation()}
                    />
                    <button
                      type="button"
                      className="tag-picker-add-btn"
                      disabled={!newTagInput.trim()}
                      onClick={() => { handleAddTag(); setTagPickerOpen(false); }}
                    >
                      + Add Tag
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="form-group">
            <label>Task IDs (comma or newline separated, or JITA URL) <span className="required">*</span></label>
            <textarea
              value={taskIds}
              onChange={e => setTaskIds(e.target.value)}
              placeholder="Paste 24-char JITA task IDs (comma or newline separated) or a JITA results URL"
              rows={3}
            />
          </div>
        )}
        <div className="form-group status-filter-group">
          <label>Test Status <span className="required">*</span></label>
          <div className="status-checkbox-row">
            {TEST_STATUS_OPTIONS.map(opt => (
              <label key={opt.id} className="status-checkbox-label">
                <input
                  type="checkbox"
                  checked={selectedStatuses.includes(opt.id)}
                  onChange={() => toggleStatus(opt.id)}
                />
                <span className={`status-chip status-chip-${opt.id}`}>{opt.label}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
          {statusMismatch?.optionIds?.length > 0 && (
            <div className="error-message-actions">
              <button
                type="button"
                className="btn-analyze-found-statuses"
                onClick={() => handleAnalyze(statusMismatch.optionIds)}
              >
                Analyze found statuses ({statusMismatch.optionIds.join(', ')})
              </button>
            </div>
          )}
        </div>
      )}
      {loading && !analyzing && (
        <div className="loading">
          <div className="spinner" />
          <p>Loading cached results...</p>
        </div>
      )}
      {analyzing && results.length === 0 && (
        <div className="loading">
          <div className="spinner" />
          <p>
            {streamPhase === 'preparing' && 'Preparing analysis... Fetching regression tasks.'}
            {streamPhase === 'fetching_results' && 'Fetching test results from JITA...'}
            {streamPhase === 'fetching_triage_genie' && 'Fetching Triage Genie ticket data...'}
            {streamPhase === 'streaming' && 'Analyzing failed testcases...'}
            {!streamPhase && 'Analyzing failed testcases... This may take a few moments.'}
          </p>
        </div>
      )}

      {results.length > 0 && (
        <div className="results-container">
          <div className="results-header">
            <h2>
              Analysis Results ({filteredResults.length} of {results.length} testcases
              {rdmGroupCount > 0 ? `, ${rdmGroupCount} RDM group${rdmGroupCount === 1 ? '' : 's'}` : ''}
              {exceptionGroupCount > 0 ? `, ${exceptionGroupCount} exception group${exceptionGroupCount === 1 ? '' : 's'}` : ''})
              {analyzing && totalExpected > 0 && (
                <span className="stream-progress-inline">
                  &nbsp;— Loading {results.length} of {totalExpected}…
                </span>
              )}
            </h2>
            {analyzing && totalExpected > 0 && (
              <div className="stream-progress-bar-container">
                <div
                  className="stream-progress-bar-fill"
                  style={{ width: `${Math.min(100, Math.round((results.length / totalExpected) * 100))}%` }}
                />
              </div>
            )}
          </div>
          {cursorAiOpenTabs.length > 0 && (
            <div className="cursor-ai-tabs-panel">
              <div className="cursor-ai-tabs-title">Cursor AI Open Tabs</div>
              {cursorAiOpenTabs.map(tab => {
                const isMinimized = !!cursorAiMinimizedTabs[tab.tabId];
                const tabSessionId = cursorAiSessions[tab.testcase_id] || tab.session_id || null;
                return (
                  <div key={tab.tabId} className="cursor-ai-inline-tab">
                    <div className="cursor-ai-inline-tab-header">
                      <div className="cursor-ai-inline-tab-name" title={tab.testcase_name}>
                        {tab.testcase_name}
                      </div>
                      <div className="cursor-ai-inline-tab-actions">
                        <button
                          type="button"
                          className="btn-inline-tab-action"
                          onClick={() => {
                            setCursorAiDetailModal({
                              testcase_name: tab.testcase_name,
                              _testcase_id: tab.testcase_id,
                              _session_id: tabSessionId,
                              ...(cursorAiResults[tab.testcase_id] || tab.analysis),
                            });
                            setFollowUpInput('');
                            setFollowUpHistory(followUpHistoryByTestcase[tab.testcase_id] || []);
                            setFollowUpMode('agent');
                          }}
                        >
                          Open Full
                        </button>
                        <button
                          type="button"
                          className="btn-inline-tab-action"
                          onClick={() => toggleCursorAiTabMinimized(tab.tabId)}
                        >
                          {isMinimized ? 'Expand' : 'Minimize'}
                        </button>
                        <button
                          type="button"
                          className="btn-inline-tab-action btn-inline-tab-close"
                          onClick={() => closeCursorAiTab(tab.tabId)}
                        >
                          Close
                        </button>
                      </div>
                    </div>
                    {!isMinimized && (
                      <div className="cursor-ai-inline-tab-body">
                        <div><strong>Classification:</strong> {(cursorAiResults[tab.testcase_id] || tab.analysis)?.classification || 'Unknown'}</div>
                        <div><strong>Confidence:</strong> {(cursorAiResults[tab.testcase_id] || tab.analysis)?.confidence || 'N/A'}</div>
                        <div><strong>Root Cause:</strong> {(cursorAiResults[tab.testcase_id] || tab.analysis)?.root_cause || 'N/A'}</div>
                        <div><strong>Suggested Fix:</strong> {(cursorAiResults[tab.testcase_id] || tab.analysis)?.suggested_fix || 'N/A'}</div>
                        {!tabSessionId && (
                          <div className="cursor-ai-inline-tab-warning">
                            Follow-up is unavailable for this tab (session not found).
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <div className="filter-controls">
            <div className="filter-group filter-group-status-dropdown" ref={statusDropdownRef}>
              <label>Filter by Test Status:</label>
              <button
                type="button"
                className="filter-select status-dropdown-trigger"
                onClick={() => setStatusDropdownOpen(prev => !prev)}
              >
                {filterTestStatus.length === ALL_STATUS_GROUPS.length
                  ? 'All Statuses'
                  : filterTestStatus.length === 0
                    ? 'None'
                    : filterTestStatus.join(', ')}
                <span className="status-dropdown-arrow">{statusDropdownOpen ? '▲' : '▼'}</span>
              </button>
              {statusDropdownOpen && (
                <div className="status-dropdown-menu">
                  {ALL_STATUS_GROUPS.map(group => (
                    <label key={group} className="status-dropdown-item">
                      <input
                        type="checkbox"
                        checked={filterTestStatus.includes(group)}
                        onChange={() => toggleFilterTestStatus(group)}
                      />
                      <span className={`status-chip status-chip-${group.toLowerCase()}`}>{group}</span>
                    </label>
                  ))}
                  <div className="status-dropdown-actions">
                    <button type="button" className="status-dropdown-action-btn" onClick={() => setFilterTestStatus([...ALL_STATUS_GROUPS])}>All</button>
                    <button type="button" className="status-dropdown-action-btn" onClick={() => setFilterTestStatus([])}>None</button>
                  </div>
                </div>
              )}
            </div>
            <div className="filter-group filter-group-status-dropdown" ref={jiraTypeDropdownRef}>
              <label>Filter by Jira Bug Type:</label>
              <button
                type="button"
                className="filter-select status-dropdown-trigger"
                onClick={() => setJiraTypeDropdownOpen(prev => !prev)}
              >
                {filterJiraBugTypes.length === JIRA_BUG_TYPE_OPTIONS.length
                  ? 'All Types'
                  : filterJiraBugTypes.length === 0
                    ? 'None'
                    : filterJiraBugTypes.join(', ')}
                <span className="status-dropdown-arrow">{jiraTypeDropdownOpen ? '▲' : '▼'}</span>
              </button>
              {jiraTypeDropdownOpen && (
                <div className="status-dropdown-menu">
                  {JIRA_BUG_TYPE_OPTIONS.map(type => (
                    <label key={type} className="status-dropdown-item">
                      <input
                        type="checkbox"
                        checked={filterJiraBugTypes.includes(type)}
                        onChange={() => toggleFilterJiraBugType(type)}
                      />
                      <span>{type}</span>
                    </label>
                  ))}
                  <div className="status-dropdown-actions">
                    <button type="button" className="status-dropdown-action-btn" onClick={() => setFilterJiraBugTypes([...JIRA_BUG_TYPE_OPTIONS])}>All</button>
                    <button type="button" className="status-dropdown-action-btn" onClick={() => setFilterJiraBugTypes([])}>None</button>
                  </div>
                </div>
              )}
            </div>
            <div className="filter-group filter-group-status-dropdown" ref={jiraStatusDropdownRef}>
              <label>Filter by Jira Status:</label>
              <button
                type="button"
                className="filter-select status-dropdown-trigger"
                onClick={() => setJiraStatusDropdownOpen(prev => !prev)}
              >
                {uniqueJiraStatuses.length === 0
                  ? 'No tickets'
                  : filterJiraStatuses.length === uniqueJiraStatuses.length
                    ? 'All Statuses'
                    : filterJiraStatuses.length === 0
                      ? 'None'
                      : filterJiraStatuses.join(', ')}
                <span className="status-dropdown-arrow">{jiraStatusDropdownOpen ? '▲' : '▼'}</span>
              </button>
              {jiraStatusDropdownOpen && (
                <div className="status-dropdown-menu">
                  {uniqueJiraStatuses.length === 0 ? (
                    <div className="status-dropdown-item">No Jira statuses yet</div>
                  ) : uniqueJiraStatuses.map(status => (
                    <label key={status} className="status-dropdown-item">
                      <input
                        type="checkbox"
                        checked={filterJiraStatuses.includes(status)}
                        onChange={() => toggleFilterJiraStatus(status)}
                      />
                      <span>{status}</span>
                    </label>
                  ))}
                  {uniqueJiraStatuses.length > 0 && (
                    <div className="status-dropdown-actions">
                      <button
                        type="button"
                        className="status-dropdown-action-btn"
                        onClick={() => {
                          jiraStatusTouchedRef.current = false;
                          setFilterJiraStatuses([...uniqueJiraStatuses]);
                        }}
                      >
                        All
                      </button>
                      <button
                        type="button"
                        className="status-dropdown-action-btn"
                        onClick={() => {
                          jiraStatusTouchedRef.current = true;
                          setFilterJiraStatuses([]);
                        }}
                      >
                        None
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="filter-group">
              <label>Filter by Regression Owner:</label>
              <select value={filterOwner} onChange={e => setFilterOwner(e.target.value)} className="filter-select">
                <option value="">All Owners</option>
                {uniqueOwners.map(owner => <option key={owner} value={owner}>{owner}</option>)}
              </select>
            </div>
            <div className="filter-group">
              <label>Filter by Failure Stage:</label>
              <select value={filterFailureStage} onChange={e => setFilterFailureStage(e.target.value)} className="filter-select">
                <option value="">All Stages</option>
                {uniqueFailureStages.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="filter-group">
              <label>Filter by Intermittent:</label>
              <select value={filterIntermittent} onChange={e => setFilterIntermittent(e.target.value)} className="filter-select">
                <option value="">All</option>
                {uniqueIntermittent.map(v => (
                  <option key={v} value={v}>{v === '-' ? 'Unknown' : v}</option>
                ))}
              </select>
            </div>
            <div className="filter-group filter-group-comment">
              <label htmlFor="filter-comment">Filter by Comment:</label>
              <input
                id="filter-comment"
                type="text"
                className="filter-input"
                value={filterComment}
                onChange={e => setFilterComment(e.target.value)}
              />
            </div>
            <div className="filter-group filter-group-exception">
              <label htmlFor="filter-exception">Filter by Exception Summary:</label>
              <select
                id="filter-exception"
                value={filterException}
                onChange={e => setFilterException(e.target.value)}
                className="filter-select"
              >
                <option value="">All Exception Summaries</option>
                {uniqueExceptionGroups.map(g => (
                  <option key={g.key || EMPTY_EXCEPTION_KEY} value={g.key || EMPTY_EXCEPTION_KEY}>
                    {g.count}× {g.label}
                  </option>
                ))}
              </select>
            </div>
            {(filterOwner || filterFailureStage || filterIntermittent || filterComment.trim() || filterException || filterTestStatus.length < ALL_STATUS_GROUPS.length || filterJiraBugTypes.length !== JIRA_BUG_TYPE_OPTIONS.length || (uniqueJiraStatuses.length > 0 && filterJiraStatuses.length < uniqueJiraStatuses.length)) && (
              <button onClick={() => {
                setFilterTestStatus([...ALL_STATUS_GROUPS]);
                setFilterOwner('');
                setFilterFailureStage('');
                setFilterIntermittent('');
                setFilterComment('');
                setFilterException('');
                setFilterJiraBugTypes([...JIRA_BUG_TYPE_OPTIONS]);
                jiraStatusTouchedRef.current = false;
                setFilterJiraStatuses([...uniqueJiraStatuses]);
              }} className="btn-clear-filters">Clear Filters</button>
            )}
          </div>
          <div className="results-table-toolbar">
            <div className="bulk-update-panel">
              <div className="bulk-field">
                <label htmlFor="bulk-jira-ticket">Jira ticket</label>
                <input
                  id="bulk-jira-ticket"
                  type="text"
                  className="bulk-input"
                  placeholder="e.g. PROJ-1234"
                  value={bulkJiraTicket}
                  onChange={e => setBulkJiraTicket(e.target.value)}
                />
              </div>
              <div className="bulk-field bulk-field-comment">
                <textarea
                  id="bulk-comment"
                  className="bulk-textarea bulk-textarea-compact"
                  rows={1}
                  placeholder="Comment"
                  aria-label="Comment"
                  value={bulkComment}
                  onChange={e => setBulkComment(e.target.value)}
                />
              </div>
              <button
                type="button"
                className="btn-bulk-update"
                disabled={bulkUpdating || selectedRows.length === 0}
                onClick={handleBulkUpdate}
              >
                {bulkUpdating ? 'Updating…' : 'Bulk Update'}
              </button>
              <button
                type="button"
                className="btn-cursor-ai-batch"
                disabled={selectedRows.length === 0 || !!cursorAiBatchJobId}
                onClick={handleCursorAiBatchAnalyze}
                title="Deep-analyze selected testcases via Cursor AI agent + nutest source"
              >
                {cursorAiBatchJobId ? 'AI Analyzing…' : 'Cursor AI Analyze Selected'}
              </button>
              <button
                type="button"
                className="btn-retrigger"
                disabled={selectedRows.length === 0}
                onClick={openRetriggerModal}
                title="Re-trigger selected failed testcases via Jita"
              >
                Re-trigger ({selectedRows.length})
              </button>
              <button
                type="button"
                className="btn-rdm-analyze-skipped"
                disabled={rdmAnalyzing || selectedRows.length === 0}
                onClick={handleAnalyzeSkipped}
                title="Analyze RDM deployment failures for selected skipped testcases"
              >
                {rdmAnalyzing ? 'Analyzing RDM…' : `Analyze Skipped (${selectedRows.length})`}
              </button>
              <button
                type="button"
                className="btn-rdm-workflow-bulk"
                disabled={selectedRows.length === 0 || Object.values(rdmWorkflowLoading).some(Boolean)}
                onClick={() => {
                  const selectedSkipped = selectedRows
                    .map(id => results.find(r => r.testcase_id === id))
                    .filter(isSkippedRow);
                  if (selectedSkipped.length === 0) {
                    alert('Select skipped testcases. Analyze, Fix & Re-run only applies to pattern-matched RDM failures.');
                    return;
                  }
                  const parentTaskId = resolveParentJitaTaskId(selectedSkipped, inputMode, taskIds);
                  const selectedTaskIds = new Set(selectedSkipped.map(r => r.agave_task_id).filter(Boolean));
                  const rows = selectedTaskIds.size === 1
                    ? expandSkippedRowsByJitaTask(selectedSkipped, results)
                    : selectedSkipped;
                  const extra = rows.length - selectedSkipped.length;
                  if (extra > 0) {
                    setSelectedRows(prev => [...new Set([
                      ...prev,
                      ...rows.map(r => r.testcase_id).filter(Boolean),
                    ])]);
                    alert(
                      `Same JITA task: included ${extra} more skipped testcase${extra === 1 ? '' : 's'} `
                      + `(${rows.length} total). Re-run will use parent ${parentTaskId || 'task'} once.`
                    );
                  }
                  handleRdmAutoWorkflow(rows, { parentTaskId });
                }}
                title="Pattern-matched only: approve/disable selected skipped tests, then re-run them once on the parent JITA task"
              >
                {Object.values(rdmWorkflowLoading).some(Boolean) ? 'Running workflow…' : `Analyze, Fix & Re-run (${selectedRows.length})`}
              </button>
              {cursorAiBatchStatus && (
                <span className="cursor-ai-batch-status">
                  {cursorAiBatchStatus.status === 'done'
                    ? `Done (${cursorAiBatchStatus.completed}/${cursorAiBatchStatus.total})`
                    : `${cursorAiBatchStatus.completed}/${cursorAiBatchStatus.total} analyzed`
                  }
                </span>
              )}
            </div>
          </div>
          <div className="results-table-wrapper">
            <table className="analysis-table">
              <thead>
                <tr>
                  <th className="col-select" title="Select rows">
                    <input
                      ref={selectAllCheckboxRef}
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleSelectAllVisible}
                      disabled={visibleIdsForHeader.length === 0}
                      aria-label="Select all visible rows"
                    />
                  </th>
                  {COLUMNS.filter(c => visibleColumns.includes(c.id)).map(c => (
                    <th key={c.id}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {resultGroups.map((group) => {
                  const groupIds = group.rows.map(r => r.testcase_id).filter(Boolean);
                  const selectedInGroup = groupIds.filter(id => selectedRows.includes(id)).length;
                  const allGroupSelected = groupIds.length > 0 && selectedInGroup === groupIds.length;
                  const sharedRdmLink = group.kind === 'rdm'
                    ? [...new Set(group.rows.map(r => r.rdm_info?.rdm_link).filter(Boolean))]
                    : [];
                  return (
                    <React.Fragment key={group.key || EMPTY_EXCEPTION_KEY}>
                      <tr className={group.kind === 'rdm' ? 'rdm-group-header' : 'exception-group-header'}>
                        <td className="col-select">
                          <input
                            type="checkbox"
                            checked={allGroupSelected}
                            ref={el => {
                              if (el) el.indeterminate = selectedInGroup > 0 && selectedInGroup < groupIds.length;
                            }}
                            onChange={() => toggleSelectGroup(groupIds)}
                            disabled={groupIds.length === 0}
                            aria-label={`Select all ${group.rows.length} testcases in this ${group.kind === 'rdm' ? 'RDM' : 'exception'} group`}
                            title={`Select all testcases in this ${group.kind === 'rdm' ? 'RDM failure' : 'exception'} group`}
                          />
                        </td>
                        <td colSpan={Math.max(visibleColumns.length, 1)}>
                          <div className="exception-group-meta">
                            <span
                              className={`exception-group-count${group.kind === 'rdm' ? ' rdm-group-count' : ''}`}
                              title={`${group.rows.length} testcase${group.rows.length === 1 ? '' : 's'} share this ${group.kind === 'rdm' ? 'RDM failure' : 'exception'}`}
                            >
                              {group.rows.length}
                            </span>
                            {group.kind === 'rdm' && <span className="rdm-group-badge">RDM</span>}
                            <span className="exception-group-label" title={group.preview || group.label}>
                              {group.label}
                            </span>
                            {sharedRdmLink.length === 1 && (
                              <a
                                href={sharedRdmLink[0]}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="rdm-link rdm-group-link"
                                onClick={e => e.stopPropagation()}
                              >
                                RDM Details
                              </a>
                            )}
                          </div>
                        </td>
                      </tr>
                      {group.rows.map((result, index) => (
                        <tr key={result.testcase_id || `${group.key}-${index}`}>
                          <td className="col-select">
                            <input
                              type="checkbox"
                              checked={!!result.testcase_id && selectedRows.includes(result.testcase_id)}
                              onChange={() => toggleRowSelect(result.testcase_id)}
                              disabled={!result.testcase_id}
                              aria-label={`Select row ${result.testcase_name || index + 1}`}
                            />
                          </td>
                          {COLUMNS.filter(c => visibleColumns.includes(c.id)).map(c => renderCell(c.id, result, index))}
                        </tr>
                      ))}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {fluxBranchPrompt && (
        <div className="modal-overlay" onClick={() => !fluxBranchPrompt.loading && setFluxBranchPrompt(null)}>
          <div className="modal-content flux-branch-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Flux Quick Fix — target branch</h3>
              <button type="button" className="modal-close" onClick={() => setFluxBranchPrompt(null)}>×</button>
            </div>
            <div className="modal-body">
              <p className="flux-branch-hint">
                Nutest branch from Jita Task {fluxBranchPrompt.taskId || '(none)'}
                {fluxBranchPrompt.result?.testcase_name ? ` for ${fluxBranchPrompt.result.testcase_name}` : ''}.
              </p>
              <label htmlFor="flux-target-branch">target_branch</label>
              <input
                id="flux-target-branch"
                type="text"
                className="flux-branch-input"
                value={fluxBranchPrompt.branch || ''}
                disabled={fluxBranchPrompt.loading}
                onChange={e => setFluxBranchPrompt(prev => prev ? { ...prev, branch: e.target.value } : prev)}
                placeholder="e.g. ganges-7.5-stable"
              />
              {fluxBranchPrompt.loading && <div className="flux-branch-loading">Loading nutest-py3-tests_branch from JITA…</div>}
              {fluxBranchPrompt.error && <div className="flux-job-error">{fluxBranchPrompt.error}</div>}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-secondary" onClick={() => setFluxBranchPrompt(null)}>Cancel</button>
              <button
                type="button"
                className="btn-flux-quick-fix"
                disabled={fluxBranchPrompt.loading || !(fluxBranchPrompt.branch || '').trim()}
                onClick={confirmFluxQuickFix}
              >
                Start Quick Fix
              </button>
            </div>
          </div>
        </div>
      )}

      {customizeOpen && (
        <div className="modal-overlay" onClick={() => setCustomizeOpen(false)}>
          <div className="modal-content customize-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Customize Columns</h3>
              <button type="button" className="modal-close" onClick={() => setCustomizeOpen(false)}>×</button>
            </div>
            <div className="modal-body">
              {COLUMNS.map(c => (
                <label key={c.id} className="column-checkbox-label">
                  <input
                    type="checkbox"
                    checked={columnCheckboxes[c.id] !== false}
                    onChange={e => setColumnCheckboxes(prev => ({ ...prev, [c.id]: e.target.checked }))}
                  />
                  {c.label}
                </label>
              ))}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-primary" onClick={handleCustomizeDone}>Done</button>
              <button type="button" className="btn-secondary" onClick={() => setCustomizeOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {cursorAiDetailModal && (
        <div className="modal-overlay" onClick={() => setCursorAiDetailModal(null)}>
          <div className="modal-content cursor-ai-detail-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Cursor AI Deep Analysis</h3>
              <button type="button" className="modal-close" onClick={() => setCursorAiDetailModal(null)}>×</button>
            </div>
            <div className="modal-body cursor-ai-detail-body">
              <div className="cursor-ai-tc-name">{cursorAiDetailModal.testcase_name}</div>

              <div className="cursor-ai-section">
                <h4>Classification</h4>
                <span className={`badge ${
                  (cursorAiDetailModal.classification || '').includes('Test') ? 'cursor-ai-test-issue'
                  : (cursorAiDetailModal.classification || '').includes('Product') ? 'cursor-ai-product-issue'
                  : (cursorAiDetailModal.classification || '').includes('Infra') ? 'cursor-ai-infra-issue'
                  : 'cursor-ai-other'
                }`}>
                  {cursorAiDetailModal.classification || 'Unknown'}
                </span>
                <span className="cursor-ai-confidence">
                  Confidence: <strong>{cursorAiDetailModal.confidence || 'N/A'}</strong>
                </span>
              </div>

              <div className="cursor-ai-section">
                <h4>Root Cause</h4>
                <p>{cursorAiDetailModal.root_cause || 'N/A'}</p>
              </div>

              {cursorAiDetailModal.failing_code && (
                <div className="cursor-ai-section">
                  <h4>Failing Code</h4>
                  <div className="cursor-ai-code-location">
                    {cursorAiDetailModal.failing_code.file}
                    {cursorAiDetailModal.failing_code.line_range && ` (lines ${cursorAiDetailModal.failing_code.line_range})`}
                  </div>
                  {cursorAiDetailModal.failing_code.snippet && (
                    <pre className="cursor-ai-code-snippet">{cursorAiDetailModal.failing_code.snippet}</pre>
                  )}
                </div>
              )}

              <div className="cursor-ai-section">
                <h4>Suggested Fix</h4>
                <p>{cursorAiDetailModal.suggested_fix || 'N/A'}</p>
              </div>

              {cursorAiDetailModal.related_components && cursorAiDetailModal.related_components.length > 0 && (
                <div className="cursor-ai-section">
                  <h4>Related Components</h4>
                  <div className="cursor-ai-tags">
                    {cursorAiDetailModal.related_components.map((c, i) => (
                      <span key={i} className="cursor-ai-tag">{c}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {followUpHistory.length > 0 && (
              <div className="cursor-ai-followup-history">
                <h4>Follow-up Conversation</h4>
                {followUpHistory.map((msg, i) => (
                  <div key={i} className={`cursor-ai-followup-msg cursor-ai-followup-${msg.role}`}>
                    {msg.role === 'user' && (
                      <div className="cursor-ai-followup-user">
                        <strong>You:</strong>
                        {msg.mode && <span className="cursor-ai-followup-mode-badge">{msg.mode.toUpperCase()}</span>}
                        {' '}
                        {msg.text}
                      </div>
                    )}
                    {msg.role === 'assistant' && (
                      <div className="cursor-ai-followup-assistant">
                        <strong>AI:</strong>
                        {msg.mode && <span className="cursor-ai-followup-mode-badge">{msg.mode.toUpperCase()}</span>}
                        {' '}
                        {msg.data?.follow_up_answer || msg.data?.root_cause || JSON.stringify(msg.data, null, 2)}
                      </div>
                    )}
                    {msg.role === 'error' && (
                      <div className="cursor-ai-followup-error">{msg.text}</div>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="modal-footer cursor-ai-modal-footer">
              {cursorAiDetailModal._session_id ? (
                <div className="cursor-ai-followup-bar">
                  <select
                    className="cursor-ai-followup-mode"
                    value={followUpMode}
                    onChange={e => setFollowUpMode(e.target.value)}
                    disabled={followUpLoading}
                    title="Follow-up AI mode"
                  >
                    <option value="ask">Ask (fast)</option>
                    <option value="agent">Agent (deep)</option>
                    <option value="plan">Plan</option>
                  </select>
                  <input
                    type="text"
                    className="cursor-ai-followup-input"
                    placeholder="Ask a follow-up (Ask mode is fastest)..."
                    value={followUpInput}
                    onChange={e => setFollowUpInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !followUpLoading) handleFollowUp(); }}
                    disabled={followUpLoading}
                  />
                  <button
                    type="button"
                    className="btn-primary cursor-ai-followup-send"
                    onClick={handleFollowUp}
                    disabled={followUpLoading || !followUpInput.trim()}
                  >
                    {followUpLoading ? 'Sending...' : 'Ask'}
                  </button>
                </div>
              ) : (
                <span className="cursor-ai-no-session-hint">
                  Re-run analysis to enable follow-up questions
                </span>
              )}
              <button type="button" className="btn-secondary" onClick={() => setCursorAiDetailModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {triageAnalysisModal && (
        <div className="modal-overlay" onClick={() => { resetDeepAiActionUi(); setTriageAnalysisModal(null); }}>
          <div className="modal-content glean-detail-modal triage-analysis-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {triageAnalysisModal.kind === 'rdm_skill'
                  ? 'AI RDM Failure Analysis'
                  : triageAnalysisModal.kind === 'deep'
                  ? 'Deep AI Analysis'
                  : 'First Level AI Analysis'}
              </h3>
              <button type="button" className="modal-close" onClick={() => { resetDeepAiActionUi(); setTriageAnalysisModal(null); }}>×</button>
            </div>
            <div className="modal-body glean-detail-body">
              <div className="glean-tc-name">{triageAnalysisModal.testcase_name}</div>

              {triageAnalysisModal.decision && (
                <div className="glean-section">
                  <h4>Decision</h4>
                  <DecisionBadge decision={triageAnalysisModal.decision} />
                  {(triageAnalysisModal.decision.reasons || []).length > 0 && (
                    <ul className="decision-reasons">
                      {triageAnalysisModal.decision.reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <McpHealthBadges mcpHealth={triageAnalysisModal.mcp_health || triageAnalysisModal.intelligent_triage?.mcp_health} />

              <div className="glean-section">
                <h4>Failure Classification</h4>
                <span className={`badge glean-issue-badge glean-issue-${(textOrEmpty(triageAnalysisModal.issue_type) || textOrEmpty(triageAnalysisModal.classification) || 'unknown').replace(/\s+/g, '-').toLowerCase()}`}>
                  {textOrEmpty(triageAnalysisModal.issue_type) || textOrEmpty(triageAnalysisModal.classification) || 'Unknown'}
                </span>
                {triageAnalysisModal.triage_confidence != null && (
                  <span className="badge triage-conf-badge" title="Independent triage_confidence">
                    triage_confidence {Number(triageAnalysisModal.triage_confidence).toFixed(2)}
                  </span>
                )}
                {triageAnalysisModal.intermittent_confidence != null && (
                  <span className="badge intermittent-conf-badge" title="Independent intermittent_confidence">
                    intermittent_confidence {Number(triageAnalysisModal.intermittent_confidence).toFixed(2)}
                  </span>
                )}
                {textOrEmpty(triageAnalysisModal.skill_used) && (
                  <span className="deep-ai-skill">Skill: {textOrEmpty(triageAnalysisModal.skill_used)}</span>
                )}
                {triageAnalysisModal.search_source && (
                  <span className="search-source-hint">
                    Ticket search: {triageAnalysisModal.search_source}
                    {triageAnalysisModal.glean_ok === false ? ' (Glean unavailable, Jira fallback used)' : ''}
                  </span>
                )}
                {rdmMcpHealthBanners(triageAnalysisModal.mcp_health).map(banner => (
                  <div key={banner.key} className="rdm-mcp-banner" role="status">
                    <strong>{banner.title}</strong>
                    <span>{banner.detail}</span>
                  </div>
                ))}
              </div>

              <div className="glean-section">
                <h4>Triage Genie (original evidence)</h4>
                <div className="tg-original-ticket">
                  {(triageAnalysisModal.intelligent_triage?.triage_genie?.original?.ticket
                    || triageAnalysisModal.tg_ticket_validation?.ticket
                    || '—')}
                </div>
                <h4>AI Validation of Triage Genie</h4>
                <TgValidationBlock validation={triageAnalysisModal.tg_ticket_validation} />
              </div>

              {triageModalAnalysisText(triageAnalysisModal) && (
                <div className="glean-section">
                  <h4>{triageAnalysisModal.kind === 'deep' ? 'Root Cause' : 'Analysis'}</h4>
                  <div className="glean-ai-analysis">
                    {triageModalAnalysisText(triageAnalysisModal)}
                  </div>
                </div>
              )}

              {textOrEmpty(triageAnalysisModal.recommended_action) && (
                <div className="glean-section">
                  <h4>Recommended Action</h4>
                  <div className="glean-ai-analysis">
                    {['link_existing', 'create_jira', 'rerun', 'disable_node_and_rerun'].includes(textOrEmpty(triageAnalysisModal.recommended_action))
                      ? `${rdmRecommendedActionLabel(triageAnalysisModal)}${textOrEmpty(triageAnalysisModal.suggested_comment) ? ` — ${textOrEmpty(triageAnalysisModal.suggested_comment)}` : ''}`
                      : textOrEmpty(triageAnalysisModal.recommended_action)}
                  </div>
                </div>
              )}

              {textOrEmpty(triageAnalysisModal.suggested_fix) && (
                <div className="glean-section">
                  <h4>Suggested Fix</h4>
                  <div className="glean-ai-analysis">{textOrEmpty(triageAnalysisModal.suggested_fix)}</div>
                </div>
              )}

              {triageAnalysisModal.failing_code && (triageAnalysisModal.failing_code.file || triageAnalysisModal.failing_code.snippet) && (
                <div className="glean-section">
                  <h4>Failing Code</h4>
                  <div className="failing-code-block">
                    {triageAnalysisModal.failing_code.file && (
                      <div className="failing-code-file">
                        {triageAnalysisModal.failing_code.file}
                        {triageAnalysisModal.failing_code.line_range ? `:${triageAnalysisModal.failing_code.line_range}` : ''}
                      </div>
                    )}
                    {triageAnalysisModal.failing_code.snippet && (
                      <pre>{triageAnalysisModal.failing_code.snippet}</pre>
                    )}
                  </div>
                </div>
              )}

              {triageAnalysisModal.best_matching_ticket && (
                <div className="glean-section">
                  <h4>Best Matching Ticket</h4>
                  <a
                    href={`${JIRA_URL}${triageAnalysisModal.best_matching_ticket}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="jira-link"
                  >
                    {triageAnalysisModal.best_matching_ticket}
                  </a>
                </div>
              )}

              {triageAnalysisModal.jira_duplicates && triageAnalysisModal.jira_duplicates.length > 0 && (
                <div className="glean-section">
                  <h4>Jira Duplicates</h4>
                  <div className="glean-jira-list">
                    {triageAnalysisModal.jira_duplicates.map((ticket, idx) => {
                      const key = textOrEmpty(ticket?.ticket || ticket);
                      if (!key) return null;
                      return (
                        <a key={`${key}-${idx}`} href={`${JIRA_URL}${key}`} target="_blank" rel="noopener noreferrer" className="jira-link">{key}</a>
                      );
                    })}
                  </div>
                </div>
              )}

              {((triageAnalysisModal.enriched_tickets && triageAnalysisModal.enriched_tickets.length > 0)
                || (triageAnalysisModal.intelligent_triage?.glean_candidates?.search?.candidates || []).length > 0) && (
                <div className="glean-section">
                  <h4>Glean Candidates (search only — AI Validate is human-triggered)</h4>
                  <EnrichedTicketTable
                    tickets={
                      triageAnalysisModal.intelligent_triage?.glean_candidates?.search?.candidates
                      || triageAnalysisModal.enriched_tickets
                    }
                    showMatchScore
                    validatingTicket={gleanAiValidating[triageAnalysisModal.testcase_id]}
                    onAiValidate={
                      triageAnalysisModal.resultRow
                        ? (t) => handleGleanAiValidate(triageAnalysisModal.resultRow, t)
                        : undefined
                    }
                  />
                  {triageAnalysisModal.intelligent_triage?.glean_candidates?.ai_validation && (
                    <div className="glean-ai-validation-persisted">
                      <strong>Persisted Glean AI validation:</strong>{' '}
                      {triageAnalysisModal.intelligent_triage.glean_candidates.ai_validation.verdict
                        || triageAnalysisModal.intelligent_triage.glean_candidates.ai_validation.match_verdict}
                      {' — '}
                      {triageAnalysisModal.intelligent_triage.glean_candidates.ai_validation.reason}
                    </div>
                  )}
                </div>
              )}

              {triageAnalysisModal.glean_snippets && triageAnalysisModal.glean_snippets.length > 0 && (
                <div className="glean-section">
                  <h4>Product Knowledge / Glean Results</h4>
                  <div className="glean-snippets-list">
                    {triageAnalysisModal.glean_snippets.map((s, i) => (
                      <div key={i} className="glean-snippet-item">
                        {s.url ? (
                          <a href={s.url} target="_blank" rel="noopener noreferrer" className="glean-snippet-title">{s.title || 'Untitled'}</a>
                        ) : (
                          <span className="glean-snippet-title">{s.title || 'Untitled'}</span>
                        )}
                        {s.snippet && <div className="glean-snippet-text">{s.snippet}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {textOrEmpty(triageAnalysisModal.triage_report) && (
                <div className="glean-section">
                  <h4>Skill Triage Report</h4>
                  <div className="glean-ai-analysis triage-report-block">{textOrEmpty(triageAnalysisModal.triage_report)}</div>
                </div>
              )}

              {triageAnalysisModal.kind === 'deep' && (
                <div className="glean-section deep-ai-chat-section">
                  <h4>Interactive Triage Chat</h4>
                  <p className="deep-ai-chat-hint">
                    Select an action tag below, or type a follow-up. Create ENG uses your User Settings
                    Jira token (defaults from analysis, or add optional details).
                  </p>

                  <div className="deep-ai-action-tags" role="group" aria-label="Deep AI actions">
                    <button
                      type="button"
                      className={`deep-ai-action-tag${deepAiActionTag === 'create_eng' ? ' is-selected' : ''}`}
                      disabled={engCreateLoading || followUpLoading}
                      onClick={() => selectDeepAiActionTag('create_eng')}
                    >
                      Create ENG Ticket
                    </button>
                    {isDeepAiTestIssue(triageAnalysisModal) && (
                      <button
                        type="button"
                        className={`deep-ai-action-tag deep-ai-action-tag-flux${deepAiActionTag === 'flux' ? ' is-selected' : ''}`}
                        disabled={engCreateLoading || followUpLoading}
                        onClick={() => selectDeepAiActionTag('flux')}
                      >
                        Flux Quick Fix
                      </button>
                    )}
                  </div>

                  {deepAiActionTag === 'create_eng' && (
                    <div className="deep-ai-eng-panel">
                      <div className="deep-ai-eng-panel-actions">
                        <button
                          type="button"
                          className="btn-primary"
                          disabled={engCreateLoading || followUpLoading}
                          onClick={() => handleCreateEngFromAction({ useDetails: false })}
                        >
                          {engCreateLoading ? 'Creating…' : 'Create with defaults'}
                        </button>
                        <button
                          type="button"
                          className={`btn-secondary${engDetailsOpen ? ' is-active' : ''}`}
                          disabled={engCreateLoading || followUpLoading}
                          onClick={() => setEngDetailsOpen(v => !v)}
                        >
                          {engDetailsOpen ? 'Hide additional details' : 'Add additional details'}
                        </button>
                      </div>
                      {engDetailsOpen && (
                        <div className="deep-ai-eng-details">
                          <label>
                            Summary
                            <input
                              type="text"
                              value={engDetailsForm.summary}
                              onChange={e => setEngDetailsForm(f => ({ ...f, summary: e.target.value }))}
                              disabled={engCreateLoading}
                            />
                          </label>
                          <div className="deep-ai-eng-details-row">
                            <label>
                              Primary Component
                              <input
                                type="text"
                                value={engDetailsForm.primary_component}
                                onChange={e => setEngDetailsForm(f => ({ ...f, primary_component: e.target.value }))}
                                disabled={engCreateLoading}
                                placeholder="e.g. Stargate"
                              />
                            </label>
                            <label>
                              Affects Version
                              <input
                                type="text"
                                value={engDetailsForm.affects_version}
                                onChange={e => setEngDetailsForm(f => ({ ...f, affects_version: e.target.value }))}
                                disabled={engCreateLoading}
                                placeholder="e.g. master"
                              />
                            </label>
                          </div>
                          <div className="deep-ai-eng-details-row">
                            <label>
                              Fix Version
                              <input
                                type="text"
                                value={engDetailsForm.fix_version}
                                onChange={e => setEngDetailsForm(f => ({ ...f, fix_version: e.target.value }))}
                                disabled={engCreateLoading}
                              />
                            </label>
                            <label>
                              Test Type
                              <input
                                type="text"
                                value={engDetailsForm.test_type}
                                onChange={e => setEngDetailsForm(f => ({ ...f, test_type: e.target.value }))}
                                disabled={engCreateLoading}
                                placeholder="Test Bug / Product Bug"
                              />
                            </label>
                            <label>
                              Issue Type
                              <input
                                type="text"
                                value={engDetailsForm.issue_type}
                                onChange={e => setEngDetailsForm(f => ({ ...f, issue_type: e.target.value }))}
                                disabled={engCreateLoading}
                                placeholder="Test"
                              />
                            </label>
                          </div>
                          <label>
                            Additional details (optional notes on the ticket)
                            <textarea
                              rows={3}
                              value={engDetailsForm.additional_details}
                              onChange={e => setEngDetailsForm(f => ({ ...f, additional_details: e.target.value }))}
                              disabled={engCreateLoading}
                              placeholder="Extra context to include in the ENG description…"
                            />
                          </label>
                          <button
                            type="button"
                            className="btn-primary"
                            disabled={engCreateLoading || followUpLoading}
                            onClick={() => handleCreateEngFromAction({ useDetails: true })}
                          >
                            {engCreateLoading ? 'Creating…' : 'Create with these details'}
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {deepAiActionTag === 'flux' && isDeepAiTestIssue(triageAnalysisModal) && (
                    <div className="deep-ai-flux-panel">
                      <div className="deep-ai-flux-panel-title">Flux Quick Fix</div>
                      <p className="deep-ai-chat-hint">
                        Select the nutest target branch, then start Flux on this page
                        {deepAiFluxForm.taskId ? ` (Jita task ${deepAiFluxForm.taskId})` : ''}.
                      </p>
                      <label className="deep-ai-flux-branch-label" htmlFor="deep-ai-flux-target-branch">
                        Target branch
                      </label>
                      <div className="deep-ai-flux-branch-row">
                        <input
                          id="deep-ai-flux-target-branch"
                          type="text"
                          list="deep-ai-flux-branch-options"
                          className="flux-branch-input deep-ai-flux-branch-input"
                          value={deepAiFluxForm.branch || ''}
                          disabled={deepAiFluxForm.loading || deepAiFluxForm.starting}
                          onChange={e => setDeepAiFluxForm(prev => ({ ...prev, branch: e.target.value }))}
                          placeholder="e.g. master or ganges-7.6-stable"
                        />
                        <datalist id="deep-ai-flux-branch-options">
                          <option value="master" />
                          <option value="ganges-7.6-stable" />
                          <option value="ganges-7.6-stable-pc" />
                          <option value="ganges-7.5-stable" />
                        </datalist>
                        <button
                          type="button"
                          className="btn-flux-quick-fix"
                          disabled={
                            deepAiFluxForm.loading
                            || deepAiFluxForm.starting
                            || !(deepAiFluxForm.branch || '').trim()
                            || !fluxFirstJiraKey(triageAnalysisModal.resultRow)
                          }
                          title={
                            fluxFirstJiraKey(triageAnalysisModal.resultRow)
                              ? 'Start Flux Quick Fix with selected target branch'
                              : 'Add a Jira ticket first'
                          }
                          onClick={() => startDeepAiFluxQuickFix(triageAnalysisModal.resultRow)}
                        >
                          {deepAiFluxForm.starting ? 'Starting…' : 'Start Flux Quick Fix'}
                        </button>
                      </div>
                      {deepAiFluxForm.loading && (
                        <div className="flux-branch-loading">Loading nutest-py3-tests_branch from JITA…</div>
                      )}
                      {deepAiFluxForm.error && (
                        <div className="flux-job-error">{deepAiFluxForm.error}</div>
                      )}
                      {!fluxFirstJiraKey(triageAnalysisModal.resultRow) && (
                        <div className="flux-job-error">Add / Approve a Jira ticket before starting Flux.</div>
                      )}
                    </div>
                  )}

                  {(() => {
                    const related = [
                      ...(triageAnalysisModal.jira_duplicates || []),
                      ...((triageAnalysisModal.enriched_tickets || []).map(t => t.ticket).filter(Boolean)),
                      triageAnalysisModal.best_matching_ticket,
                      triageAnalysisModal.created_ticket,
                      ...((triageAnalysisModal.resultRow?.jira_tickets) || []),
                    ].map(t => String(t || '').trim().toUpperCase()).filter(Boolean);
                    const uniq = [...new Set(related)];
                    if (!uniq.length) return null;
                    return (
                      <div className="deep-ai-related-tickets">
                        <div className="deep-ai-related-label">Related ENG tickets — review and Approve to tag JITA:</div>
                        <div className="deep-ai-related-list">
                          {uniq.map(ticket => (
                            <div key={ticket} className="deep-ai-related-row">
                              <a href={`${JIRA_URL}${ticket}`} target="_blank" rel="noopener noreferrer" className="jira-link">{ticket}</a>
                              <button
                                type="button"
                                className="btn-rdm-approve btn-rdm-approve-sm"
                                disabled={!!updateLoading[triageAnalysisModal.testcase_id]}
                                onClick={() => handleApproveTicketToJita(ticket)}
                              >
                                {updateLoading[triageAnalysisModal.testcase_id] ? '…' : 'Approve → JITA'}
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })()}

                  {followUpHistory.length > 0 && (
                    <div className="cursor-ai-followup-history deep-ai-followup-history">
                      {followUpHistory.map((msg, i) => (
                        <div key={i} className={`cursor-ai-followup-msg cursor-ai-followup-${msg.role}`}>
                          {msg.role === 'user' && (
                            <div className="cursor-ai-followup-user">
                              <strong>You:</strong>
                              {msg.mode && <span className="cursor-ai-followup-mode-badge">{msg.mode.toUpperCase()}</span>}
                              {' '}
                              {msg.text}
                            </div>
                          )}
                          {msg.role === 'assistant' && (
                            <div className="cursor-ai-followup-assistant">
                              <strong>AI:</strong>
                              {msg.mode && msg.mode !== 'system' && (
                                <span className="cursor-ai-followup-mode-badge">{msg.mode.toUpperCase()}</span>
                              )}
                              {' '}
                              {msg.data?.follow_up_answer || msg.data?.root_cause || JSON.stringify(msg.data, null, 2)}
                              {msg.data?.created_ticket && (
                                <div className="deep-ai-related-row" style={{ marginTop: 6 }}>
                                  <a
                                    href={msg.data.created_ticket_url || `${JIRA_URL}${msg.data.created_ticket}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="jira-link"
                                  >
                                    {msg.data.created_ticket}
                                  </a>
                                  <button
                                    type="button"
                                    className="btn-rdm-approve btn-rdm-approve-sm"
                                    onClick={() => handleApproveTicketToJita(msg.data.created_ticket)}
                                  >
                                    Approve → JITA
                                  </button>
                                </div>
                              )}
                              {msg.data?.suggested_action === 'flux_quick_fix' && (
                                <div style={{ marginTop: 6 }}>
                                  <button
                                    type="button"
                                    className="btn-flux-quick-fix"
                                    onClick={() => handleFluxFromDeepChat(triageAnalysisModal.resultRow)}
                                  >
                                    Select target branch
                                  </button>
                                </div>
                              )}
                            </div>
                          )}
                          {msg.role === 'error' && (
                            <div className="cursor-ai-followup-error">{msg.text}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className={`modal-footer${triageAnalysisModal.kind === 'deep' ? ' cursor-ai-modal-footer' : ''}`}>
              {triageAnalysisModal.kind === 'deep' && (
                <div className="cursor-ai-followup-bar">
                  <select
                    className="cursor-ai-followup-mode"
                    value={followUpMode}
                    onChange={e => setFollowUpMode(e.target.value)}
                    disabled={followUpLoading}
                    title="Follow-up AI mode"
                  >
                    <option value="ask">Ask (fast)</option>
                    <option value="agent">Agent (deep)</option>
                    <option value="plan">Plan</option>
                  </select>
                  <input
                    type="text"
                    className="cursor-ai-followup-input"
                    placeholder="Ask a follow-up, or use action tags above…"
                    value={followUpInput}
                    onChange={e => setFollowUpInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !followUpLoading) handleFollowUp(); }}
                    disabled={followUpLoading}
                  />
                  <button
                    type="button"
                    className="btn-primary cursor-ai-followup-send"
                    onClick={handleFollowUp}
                    disabled={followUpLoading || !followUpInput.trim()}
                  >
                    {followUpLoading ? 'Sending...' : 'Ask'}
                  </button>
                </div>
              )}
              <button type="button" className="btn-secondary" onClick={() => { resetDeepAiActionUi(); setTriageAnalysisModal(null); }}>Close</button>
            </div>
          </div>
        </div>
      )}

      {gleanDetailModal && (
        <div className="modal-overlay" onClick={() => setGleanDetailModal(null)}>
          <div className="modal-content glean-detail-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Glean Search Analysis</h3>
              <button type="button" className="modal-close" onClick={() => setGleanDetailModal(null)}>×</button>
            </div>
            <div className="modal-body glean-detail-body">
              <div className="glean-tc-name">{gleanDetailModal.testcase_name}</div>

              <div className="glean-section">
                <h4>Failure Classification</h4>
                <span className={`badge glean-issue-badge glean-issue-${(gleanDetailModal.issue_type || '').replace(/\s+/g, '-').toLowerCase()}`}>
                  {gleanDetailModal.issue_type || 'Unknown'}
                </span>
              </div>

              {gleanDetailModal.enriched_tickets && gleanDetailModal.enriched_tickets.length > 0 && (
                <div className="glean-section">
                  <h4>Matching ENG JIRA Tickets ({gleanDetailModal.enriched_tickets.length})</h4>
                  <div className="glean-ticket-table-wrapper">
                    <table className="glean-ticket-table">
                      <thead>
                        <tr>
                          <th>Ticket</th>
                          <th>Status</th>
                          <th>Type</th>
                          <th>Summary</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gleanDetailModal.enriched_tickets.map(t => (
                          <tr key={t.ticket} className={t.is_open ? 'glean-ticket-open' : 'glean-ticket-closed'}>
                            <td>
                              <a href={t.url || `${JIRA_URL}${t.ticket}`} target="_blank" rel="noopener noreferrer" className="jira-link">{t.ticket}</a>
                            </td>
                            <td>
                              <span className={`glean-status-badge ${t.is_open ? 'glean-status-open' : 'glean-status-closed'}`}>
                                {t.jira_status || 'Unknown'}
                              </span>
                              {t.jira_resolution && <span className="glean-resolution">({t.jira_resolution})</span>}
                            </td>
                            <td className="glean-ticket-type">{t.jira_type || '-'}</td>
                            <td className="glean-ticket-summary" title={t.jira_summary || t.glean_title}>
                              {t.jira_summary || t.glean_title || '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {(!gleanDetailModal.enriched_tickets || gleanDetailModal.enriched_tickets.length === 0)
                && gleanDetailModal.glean_jira_refs && gleanDetailModal.glean_jira_refs.length > 0 && (
                <div className="glean-section">
                  <h4>Matching JIRA Tickets</h4>
                  <div className="glean-jira-list">
                    {gleanDetailModal.glean_jira_refs.map(ticket => (
                      <a key={ticket} href={`${JIRA_URL}${ticket}`} target="_blank" rel="noopener noreferrer" className="jira-link">{ticket}</a>
                    ))}
                  </div>
                </div>
              )}

              {gleanDetailModal.ai_analysis && (
                <div className="glean-section">
                  <h4>AI Analysis</h4>
                  <div className="glean-ai-analysis">{gleanDetailModal.ai_analysis}</div>
                </div>
              )}

              {gleanDetailModal.glean_snippets && gleanDetailModal.glean_snippets.length > 0 && (
                <div className="glean-section">
                  <h4>Glean Search Results</h4>
                  <div className="glean-snippets-list">
                    {gleanDetailModal.glean_snippets.map((s, i) => (
                      <div key={i} className="glean-snippet-item">
                        {s.url ? (
                          <a href={s.url} target="_blank" rel="noopener noreferrer" className="glean-snippet-title">{s.title || 'Untitled'}</a>
                        ) : (
                          <span className="glean-snippet-title">{s.title || 'Untitled'}</span>
                        )}
                        {s.snippet && <div className="glean-snippet-text">{s.snippet}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-secondary" onClick={() => setGleanDetailModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {patternModal && (
        <div className="modal-overlay" onClick={() => !patternSaving && setPatternModal(null)}>
          <div className="modal-content rdm-pattern-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add RDM Pattern</h3>
              <button type="button" className="modal-close" onClick={() => !patternSaving && setPatternModal(null)}>×</button>
            </div>
            <div className="modal-body">
              <p className="rdm-pattern-modal-hint">
                Save this approved analysis as a pattern so future similar RDM failures auto-match
                and apply the selected next action (disable node and/or re-run).
              </p>
              <div className="rdm-pattern-field">
                <label>Pattern ID</label>
                <input
                  type="text"
                  value={patternModal.id}
                  onChange={e => setPatternModal(prev => ({ ...prev, id: e.target.value }))}
                />
              </div>
              <div className="rdm-pattern-field">
                <label>Regex</label>
                <textarea
                  rows={3}
                  value={patternModal.regex}
                  onChange={e => setPatternModal(prev => ({ ...prev, regex: e.target.value }))}
                />
              </div>
              <div className="rdm-pattern-field">
                <label>Comment template</label>
                <input
                  type="text"
                  value={patternModal.comment_template}
                  onChange={e => setPatternModal(prev => ({ ...prev, comment_template: e.target.value }))}
                />
              </div>
              <div className="rdm-pattern-row">
                <div className="rdm-pattern-field">
                  <label>Category</label>
                  <select
                    value={patternModal.category}
                    onChange={e => setPatternModal(prev => ({ ...prev, category: e.target.value }))}
                  >
                    <option value="INFRA_NODE">INFRA_NODE</option>
                    <option value="INFRA_INTERMITTENT">INFRA_INTERMITTENT</option>
                    <option value="INFRA_RESOURCE">INFRA_RESOURCE</option>
                    <option value="INFRA_BUG">INFRA_BUG</option>
                  </select>
                </div>
                <div className="rdm-pattern-field">
                  <label>Next action</label>
                  <select
                    value={patternModal.next_action}
                    onChange={e => setPatternModal(prev => ({ ...prev, next_action: e.target.value }))}
                  >
                    <option value="disable_node_and_rerun">Disable node &amp; re-run</option>
                    <option value="rerun">Re-run only</option>
                    <option value="comment_only">Comment only</option>
                  </select>
                </div>
              </div>
              <div className="rdm-pattern-field">
                <label>Description</label>
                <textarea
                  rows={2}
                  value={patternModal.description}
                  onChange={e => setPatternModal(prev => ({ ...prev, description: e.target.value }))}
                />
              </div>
              <div className="rdm-pattern-field">
                <label>Reference RDM</label>
                <input
                  type="text"
                  value={patternModal.reference_task}
                  onChange={e => setPatternModal(prev => ({ ...prev, reference_task: e.target.value }))}
                />
              </div>
              <div className="rdm-pattern-field">
                <label>Jira (optional)</label>
                <input
                  type="text"
                  value={patternModal.jira}
                  onChange={e => setPatternModal(prev => ({ ...prev, jira: e.target.value }))}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-secondary" disabled={patternSaving} onClick={() => setPatternModal(null)}>Cancel</button>
              <button type="button" className="btn-primary" disabled={patternSaving} onClick={handleSavePattern}>
                {patternSaving ? 'Saving…' : 'Save Pattern'}
              </button>
            </div>
          </div>
        </div>
      )}

      {retriggerModalOpen && (
        <div className="modal-overlay" onClick={() => !retriggerLoading && setRetriggerModalOpen(false)}>
          <div className="modal-content retrigger-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Re-trigger Failed Testcases</h3>
              <button type="button" className="modal-close" onClick={() => !retriggerLoading && setRetriggerModalOpen(false)}>×</button>
            </div>
            <div className="modal-body retrigger-modal-body">
              <p className="retrigger-summary">
                <strong>{selectedRetriggerRows.length}</strong> selected testcase(s) across{' '}
                <strong>{selectedRetriggerTaskIds.length}</strong>{' '}
                Jita task(s) will be re-triggered (one rerun per task).
                Blank fields keep the original values.
              </p>
              <ul className="retrigger-selected-tests">
                {selectedRetriggerRows.map(row => (
                  <li key={row.testcase_id} title={row.testcase_name || row.testcase_id}>
                    <span>{row.testcase_name || row.testcase_id}</span>
                    {row.agave_task_id && (
                      <span className="retrigger-selected-task">task {row.agave_task_id}</span>
                    )}
                  </li>
                ))}
              </ul>

              <div className="retrigger-component-select">
                <span className="retrigger-component-label">Select Components to Override</span>
                <div className="retrigger-component-checks">
                  <label className="retrigger-check-label retrigger-check-all">
                    <input type="checkbox" checked={allComponentsOverride}
                      onChange={e => toggleAllComponentOverrides(e.target.checked)} />
                    <span>Override All</span>
                  </label>
                  <label className="retrigger-check-label">
                    <input type="checkbox" checked={retriggerOverrides.updateNos}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, updateNos: e.target.checked }))} />
                    <span>NOS Build</span>
                  </label>
                  <label className="retrigger-check-label">
                    <input type="checkbox" checked={retriggerOverrides.updatePc}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, updatePc: e.target.checked }))} />
                    <span>Prism Central Build</span>
                  </label>
                  <label className="retrigger-check-label">
                    <input type="checkbox" checked={retriggerOverrides.updateImage}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, updateImage: e.target.checked }))} />
                    <span>Image Build</span>
                  </label>
                  <label className="retrigger-check-label">
                    <input type="checkbox" checked={retriggerOverrides.updateFramework}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, updateFramework: e.target.checked }))} />
                    <span>Nutest / Framework Branch</span>
                  </label>
                  <label className="retrigger-check-label">
                    <input type="checkbox" checked={retriggerOverrides.updateResource}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, updateResource: e.target.checked }))} />
                    <span>Resource Requirement Configuration</span>
                  </label>
                </div>
              </div>

              <div className="retrigger-tcms-sync-section">
                <span className="retrigger-component-label">TCMS Integration</span>
                <div className="retrigger-component-checks">
                  <label className="retrigger-check-label retrigger-tcms-sync">
                    <input type="checkbox" checked={retriggerOverrides.syncToTcms}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, syncToTcms: e.target.checked }))} />
                    <span>Sync results to TCMS</span>
                  </label>
                </div>
                <p className="retrigger-pool-hint">
                  When enabled, the rerun is marked official so JITA can validate reporting config and sync results to TCMS. When disabled, official is omitted and results are not synced. Sync still skips if the testcase service does not match reporting config.
                </p>
              </div>

              {(retriggerOverrides.updateNos || retriggerOverrides.updatePc || retriggerOverrides.updateImage) && (
              <div className="retrigger-panels">
                {retriggerOverrides.updateNos && (
                  <div className="retrigger-panel">
                    <h4 className="retrigger-panel-title">NOS Build</h4>
                    <p className="retrigger-pool-hint">NOS branch is taken from the original Jita task and cannot be changed. Commit and GBN are passed through if you enter them.</p>
                    <div className="retrigger-form-group">
                      <label>NOS Branch</label>
                      <input type="text" readOnly disabled
                        className="retrigger-readonly"
                        placeholder="from original Jita task"
                        value={retriggerOverrides.nos.branch}
                      />
                    </div>
                    <div className="retrigger-form-group">
                      <label>Commit ID</label>
                      <input type="text" placeholder="commit id, or Latest Smoke Passed"
                        value={retriggerOverrides.nos.commitId}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, nos: { ...prev.nos, commitId: e.target.value }
                        }))} />
                    </div>
                    <div className="retrigger-form-group">
                      <label>GBN</label>
                      <input type="text" placeholder="optional; leave blank to keep original"
                        value={retriggerOverrides.nos.gbn}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, nos: { ...prev.nos, gbn: e.target.value }
                        }))} />
                    </div>

                  </div>
                )}

                {retriggerOverrides.updatePc && (
                  <div className="retrigger-panel">
                    <h4 className="retrigger-panel-title">Prism Central Build</h4>
                    <p className="retrigger-pool-hint">Build Url and Build QCOW2 URL are required when changing PC commit or GBN.</p>
                    <div className="retrigger-form-group">
                      <label>PC Branch</label>
                      <input type="text" placeholder="e.g. ganges-7.6.0.6-stable-pc"
                        value={retriggerOverrides.pc.branch}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, pc: { ...prev.pc, branch: e.target.value }
                        }))} />
                    </div>
                    <div className="retrigger-form-group">
                      <label>Commit ID</label>
                      <input type="text" placeholder="commit id, or Latest Smoke Passed"
                        value={retriggerOverrides.pc.commitId}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, pc: { ...prev.pc, commitId: e.target.value }
                        }))} />
                    </div>
                    <div className="retrigger-form-group">
                      <label>GBN</label>
                      <input type="text" placeholder="optional; leave blank to keep original"
                        value={retriggerOverrides.pc.gbn}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, pc: { ...prev.pc, gbn: e.target.value }
                        }))} />
                    </div>
                    <div className="retrigger-form-group">
                      <label>Build Url {pcBuildChanged && <span className="retrigger-required">*</span>}</label>
                      <input type="text" placeholder="http://vendor.dyn.nutanix.com/.../opt/"
                        value={retriggerOverrides.pc.buildUrl}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, pc: { ...prev.pc, buildUrl: e.target.value }
                        }))} />
                    </div>
                    <div className="retrigger-form-group">
                      <label>Build QCOW2 URL {pcBuildChanged && <span className="retrigger-required">*</span>}</label>
                      <input type="text" placeholder="http://vendor.dyn.nutanix.com/.../publish_pc_image_internal/"
                        value={retriggerOverrides.pc.qcow2Url}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, pc: { ...prev.pc, qcow2Url: e.target.value }
                        }))} />
                    </div>
                    {pcBuildUrlsMissing && (
                      <p className="retrigger-pool-hint retrigger-url-required-hint">
                        Enter both Build Url and Build QCOW2 URL for the new PC GBN (same fields as the Jita rerun form).
                      </p>
                    )}
                  </div>
                )}

                {retriggerOverrides.updateImage && (
                  <div className="retrigger-panel">
                    <h4 className="retrigger-panel-title">Image Build</h4>
                    <p className="retrigger-pool-hint">If the original JP used the same branch for NOS and image (Jita default), leave this unchecked so image stays a copy of NOS.</p>
                    <div className="retrigger-form-group">
                      <label>Image Branch</label>
                      <input type="text" placeholder="e.g. ganges-7.6.0.6-stable"
                        value={retriggerOverrides.image.branch}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, image: { ...prev.image, branch: e.target.value }
                        }))} />
                    </div>
                    <div className="retrigger-form-group">
                      <label>Image Commit</label>
                      <input type="text" placeholder="e.g. fd96efb85c11ac75f282d51dce06e04a279bad2d"
                        value={retriggerOverrides.image.commitId}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, image: { ...prev.image, commitId: e.target.value }
                        }))} />
                    </div>
                    <div className="retrigger-form-group">
                      <label>Image GBN</label>
                      <input type="text" placeholder="optional; leave blank to keep original"
                        value={retriggerOverrides.image.gbn}
                        onChange={e => setRetriggerOverrides(prev => ({
                          ...prev, image: { ...prev.image, gbn: e.target.value }
                        }))} />
                    </div>
                  </div>
                )}
              </div>
              )}

              {retriggerOverrides.updateFramework && (
                <div className="retrigger-section">
                  <h4>Nutest / Framework Branch</h4>
                  <p className="retrigger-pool-hint">
                    Framework and Nutest-py3-tests commits are left empty so Jita picks the latest on this branch.
                  </p>
                  <div className="retrigger-fields">
                    <div className="retrigger-field">
                      <label>Branch</label>
                      <input type="text" placeholder="e.g. ganges-7.6-stable"
                        value={retriggerOverrides.nutest_branch}
                        onChange={e => setRetriggerOverrides(prev => ({ ...prev, nutest_branch: e.target.value }))} />
                    </div>

                    <div className="retrigger-field retrigger-field-wide">
                      <label>Test Patch URL</label>
                      <input type="text" placeholder="e.g. https://nugerrit.ntnxdpro.com/changes/..."
                        value={retriggerOverrides.patch_url}
                        onChange={e => setRetriggerOverrides(prev => ({ ...prev, patch_url: e.target.value }))} />
                    </div>
                    <div className="retrigger-field retrigger-field-wide">
                      <label>Framework Patch URL</label>
                      <input type="text" placeholder="e.g. https://nugerrit.ntnxdpro.com/changes/..."
                        value={retriggerOverrides.framework_patch_url}
                        onChange={e => setRetriggerOverrides(prev => ({ ...prev, framework_patch_url: e.target.value }))} />
                    </div>
                  </div>
                </div>
              )}

              {retriggerOverrides.updateResource && (
              <div className="retrigger-section">
                <h4>Resource Requirement Configuration</h4>
                <p className="retrigger-pool-hint">
                  Pre-filled from the original Jita task. Edit these the same way you would on Jita; the rerun uses the values shown here.
                </p>
                {retriggerResourcePreview.loading && (
                  <p className="retrigger-pool-hint">Loading Jita resource config…</p>
                )}
                {!retriggerResourcePreview.loading && retriggerResourcePreview.tasks.length === 0 && (
                  <p className="retrigger-pool-hint">Could not load Jita resource config. Edits you make here still apply to the rerun.</p>
                )}
                {selectedRetriggerTaskIds.length > 1 && (
                  <div className="retrigger-warning">
                    Selected testcases belong to multiple Jita tasks. These resource values apply to every rerun.
                  </div>
                )}
                <div className="retrigger-resource-card">
                  <div className="retrigger-resource-grid">
                    <div className="retrigger-form-group">
                      <label>Resources</label>
                      <select
                        value={retriggerOverrides.resources_mode}
                        onChange={e => updateResourceOverride({ resources_mode: e.target.value })}
                      >
                        {RESOURCE_MODE_OPTIONS.map(opt => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="retrigger-form-group">
                      <label>Resource Type</label>
                      <select
                        value={retriggerOverrides.resource_type}
                        onChange={e => updateResourceOverride({ resource_type: e.target.value })}
                      >
                        {RESOURCE_TYPE_OPTIONS.map(opt => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="retrigger-form-group">
                      <label>Hypervisor</label>
                      <select
                        value={retriggerOverrides.hypervisor}
                        onChange={e => updateResourceOverride({ hypervisor: e.target.value })}
                      >
                        <option value="">Keep original</option>
                        {[...new Set([...HYPERVISOR_OPTIONS, retriggerOverrides.hypervisor].filter(Boolean))].map(h => (
                          <option key={h} value={h}>{h}</option>
                        ))}
                      </select>
                    </div>
                    <div className="retrigger-form-group">
                      <label className="retrigger-check-label">
                        <input
                          type="checkbox"
                          checked={!!retriggerOverrides.match_resource_spec}
                          onChange={e => updateResourceOverride({ match_resource_spec: e.target.checked })}
                        />
                        <span>Match Resources to Resource Spec</span>
                      </label>
                    </div>
                  </div>
                  {retriggerOverrides.resources_mode !== 'global_pool' && (
                    <div className="retrigger-form-group">
                      <label>{retriggerOverrides.resources_mode === 'node_pool' ? 'Node Pools' : 'Clusters / Names'}</label>
                      <input
                        type="text"
                        value={nodePoolSearch}
                        onChange={e => handleSearchRetriggerNodePools(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            addRetriggerNodePool(nodePoolSearch);
                          }
                        }}
                        placeholder="Type to search or press Enter to add"
                      />
                      {nodePoolLoading && <p className="retrigger-pool-hint">Searching…</p>}
                      {nodePoolSearch.length >= 2 && !nodePoolLoading && nodePoolResults.length === 0 && (
                        <p className="retrigger-pool-hint">No matches. Press Enter to add &quot;{nodePoolSearch}&quot;.</p>
                      )}
                      {nodePoolResults.length > 0 && (
                        <div className="retrigger-pool-results">
                          {nodePoolResults.map(pool => {
                            const selected = retriggerOverrides.node_pools.includes(pool);
                            return (
                              <button
                                key={pool}
                                type="button"
                                className={`retrigger-pool-result${selected ? ' selected' : ''}`}
                                onClick={() => addRetriggerNodePool(pool)}
                              >
                                {pool}
                                {selected ? ' (selected)' : ''}
                              </button>
                            );
                          })}
                        </div>
                      )}
                      <div className="retrigger-pool-tags">
                        {retriggerOverrides.node_pools.length === 0 && (
                          <span className="retrigger-pool-hint">None selected</span>
                        )}
                        {retriggerOverrides.node_pools.map(pool => (
                          <span key={pool} className="retrigger-pool-tag retrigger-pool-tag-edit">
                            {pool}
                            <button type="button" onClick={() => removeRetriggerNodePool(pool)} title="Remove">&times;</button>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
              )}

              <div className="retrigger-section">
                <h4>Task / Infra Options</h4>
                <div className="retrigger-fields">
                  <div className="retrigger-field">
                    <label>Label</label>
                    <input type="text" placeholder="original label + -rerun"
                      value={retriggerOverrides.label}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, label: e.target.value }))} />
                  </div>
                  <div className="retrigger-field">
                    <label>Priority</label>
                    <input type="text" placeholder="e.g. 10"
                      value={retriggerOverrides.priority}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, priority: e.target.value }))} />
                  </div>
                  <div className="retrigger-field retrigger-field-wide">

                    <label>Tester Tags</label>
                    <textarea
                      rows={2}
                      placeholder="comma-separated tags; jita3 is always added"
                      value={retriggerOverrides.tester_tags}
                      onChange={e => setRetriggerOverrides(prev => ({ ...prev, tester_tags: e.target.value }))}
                    />
                  </div>
                </div>
              </div>

              <div className="retrigger-section">
                <h4>Scheduling</h4>
                <div className="retrigger-fields">
                  <div className="retrigger-field retrigger-field-wide">
                    <label className="retrigger-check-label retrigger-override-toggle">
                      <input type="checkbox" checked={retriggerOverrides.overrideScheduling}
                        onChange={e => setRetriggerOverrides(prev => ({ ...prev, overrideScheduling: e.target.checked }))} />
                      <span>Override skip_resource_spec_match / check_image_compatibility</span>
                    </label>
                    {retriggerOverrides.overrideScheduling && (
                      <div className="retrigger-inline-checks">
                        <label className="retrigger-check-label">
                          <input type="checkbox" checked={retriggerOverrides.skip_resource_spec_match}
                            onChange={e => setRetriggerOverrides(prev => ({
                              ...prev, skip_resource_spec_match: e.target.checked
                            }))} />
                          <span>skip_resource_spec_match</span>
                        </label>
                        <label className="retrigger-check-label">
                          <input type="checkbox" checked={retriggerOverrides.check_image_compatibility}
                            onChange={e => setRetriggerOverrides(prev => ({
                              ...prev, check_image_compatibility: e.target.checked
                            }))} />
                          <span>check_image_compatibility</span>
                        </label>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {retriggerResults && (
                <div className={`retrigger-results ${retriggerResults.error ? 'retrigger-results-error' : ''}`}>
                  {retriggerResults.error ? (
                    <div className="retrigger-error-msg">{retriggerResults.error}</div>
                  ) : (
                    <>
                      <div className="retrigger-results-summary">
                        <span className="retrigger-stat retrigger-stat-ok">{retriggerResults.succeeded || 0} succeeded</span>
                        {retriggerResults.failed > 0 && (
                          <span className="retrigger-stat retrigger-stat-fail">{retriggerResults.failed} failed</span>
                        )}
                      </div>
                      {succeededRerunIds.length > 0 && (
                        <div className="retrigger-merged-link">
                          <div className="retrigger-merged-link-label">
                            New Jita task IDs ({succeededRerunIds.length})
                          </div>
                          <div className="retrigger-id-list">
                            {succeededRerunIds.map((id) => (
                              <a key={id} href={jitaResultsUrl(id)} target="_blank" rel="noopener noreferrer">{id}</a>
                            ))}
                          </div>
                          <div className="retrigger-merged-link-row">
                            <button
                              type="button"
                              className="retrigger-copy-link"
                              onClick={() => {
                                copyTextToClipboard(succeededRerunIds.join(',')).then(() => {
                                  setRetriggerCopied('ids');
                                  setTimeout(() => setRetriggerCopied(''), 2000);
                                }).catch(() => {});
                              }}
                            >
                              {retriggerCopied === 'ids' ? 'Copied IDs' : 'Copy IDs'}
                            </button>
                          </div>
                        </div>
                      )}
                      {retriggerResultUrls.length > 0 && (
                        <div className="retrigger-merged-link">
                          <div className="retrigger-merged-link-label">
                            {retriggerResultUrls.length > 1
                              ? `Jita links (${retriggerResultUrls.length} parts — URL too long for one GET)`
                              : succeededRerunIds.length > 1
                                ? `Single Jita link for all ${succeededRerunIds.length} new tasks`
                                : 'Jita link for the new task'}
                          </div>
                          {retriggerResultUrls.map((url, i) => (
                            <div key={url} className="retrigger-merged-link-row">
                              <a href={url} target="_blank" rel="noopener noreferrer">
                                {retriggerResultUrls.length > 1 ? `Part ${i + 1}: ${url}` : url}
                              </a>
                              <button
                                type="button"
                                className="retrigger-copy-link"
                                onClick={() => {
                                  copyTextToClipboard(url).then(() => {
                                    setRetriggerCopied(`link-${i}`);
                                    setTimeout(() => setRetriggerCopied(''), 2000);
                                  }).catch(() => {});
                                }}
                              >
                                {retriggerCopied === `link-${i}` ? 'Copied' : 'Copy'}
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                      {retriggerResults.results && retriggerResults.results.map((r, i) => (
                        <div key={i} className={`retrigger-result-row ${r.success ? 'retrigger-result-ok' : 'retrigger-result-fail'}`}>
                          <span className="retrigger-result-task">Source: {r.agave_task_id}</span>
                          {r.success ? (
                            <span className="retrigger-result-new-id">
                              Rerun:{' '}
                              <a href={jitaResultsUrl(r.rerun_task_id)} target="_blank" rel="noopener noreferrer">{r.rerun_task_id}</a>
                              {r.triggered_as && (
                                <span className="retrigger-triggered-as"> as {r.triggered_as}</span>
                              )}
                              {r.job_profile_name && (
                                <span className="retrigger-jp-name"> ({r.job_profile_name})</span>
                              )}
                              {r.message && <span> — {r.message}</span>}
                            </span>
                          ) : (
                            <span className="retrigger-result-err">{r.error}</span>
                          )}
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="btn-primary btn-retrigger-submit"
                disabled={retriggerLoading || pcBuildUrlsMissing}
                onClick={handleRetrigger}
              >
                {retriggerLoading ? 'Re-triggering…' : 'Re-trigger'}
              </button>
              <button type="button" className="btn-secondary" disabled={retriggerLoading} onClick={() => setRetriggerModalOpen(false)}>
                {retriggerResults ? 'Close' : 'Cancel'}
              </button>
            </div>
          </div>
        </div>
      )}

      {!analyzing && results.length === 0 && filteredResults.length === 0 && !error && (
        <div className="empty-state">
          <p>Enter a tag or task IDs and click "Analyze Failed Testcases" to get started.</p>
          <p className="empty-state-hint">The AI agent will analyze failures and provide triage options.</p>
        </div>
      )}
    </div>
  );
}
