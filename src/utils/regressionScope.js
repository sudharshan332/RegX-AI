/**
 * Resolve active regression tag / Full-regression task_ids (Regression_Run_Tasks),
 * same sources as Regression Home, with optional GET /mcp/regression/config fallback.
 *
 * Full-regression IDs are tag-scoped so moon TG coverage / triage never mixes jobs.
 */
import { extractJitaTaskIds, normalizeJitaTaskId } from './jitaTaskIds.js';

export const FULL_LINK_TAG_KEY = 'regressionDashboardFullLinkTag';
export const FULL_LINK_TASK_IDS_KEY = 'regressionDashboardTaskIds';
export const DASHBOARD_TAG_KEY = 'regressionDashboardTag';
export const DASHBOARD_MODE_KEY = 'regressionDashboardInputMode';

function readTaskIdsFromStorageRaw() {
  const raw = localStorage.getItem(FULL_LINK_TASK_IDS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    const list = Array.isArray(parsed) ? parsed : String(parsed).split(',');
    return list.map(normalizeJitaTaskId).filter(Boolean);
  } catch {
    return String(raw)
      .split(',')
      .map(normalizeJitaTaskId)
      .filter(Boolean);
  }
}

/**
 * Scrape only Regression_Run_Tasks links (data attribute), not every JITA href on page.
 */
export function readFullRegressionTaskIdsFromDom() {
  if (typeof document === 'undefined') return [];
  const seen = new Set();
  const out = [];
  const pushHref = (href) => {
    extractJitaTaskIds(href || '').forEach((id) => {
      if (!seen.has(id)) {
        seen.add(id);
        out.push(id);
      }
    });
  };
  const pushNode = (el) => {
    const dataIds = el.getAttribute('data-task-ids') || '';
    if (dataIds) {
      extractJitaTaskIds(dataIds).forEach((id) => {
        if (!seen.has(id)) {
          seen.add(id);
          out.push(id);
        }
      });
      return;
    }
    pushHref(el.getAttribute('href'));
  };
  document
    .querySelectorAll('[data-regression-run-tasks="1"]')
    .forEach((el) => pushNode(el));
  // Fallback: link text / title still named Regression_Run_Tasks
  if (out.length === 0) {
    document.querySelectorAll('a[href*="task_ids="]').forEach((a) => {
      const label = `${a.textContent || ''} ${a.getAttribute('title') || ''}`;
      if (/Regression_Run_Tasks/i.test(label)) {
        pushHref(a.getAttribute('href'));
      }
    });
  }
  return out;
}

/**
 * Full regression IDs trusted for `tag` only when storage is scoped to that tag.
 * task_ids mode: storage always trusted.
 */
export function readScopedFullRegressionTaskIds(tag = null) {
  const mode = localStorage.getItem(DASHBOARD_MODE_KEY) || 'tag';
  const stored = readTaskIdsFromStorageRaw();
  const linkTag = (localStorage.getItem(FULL_LINK_TAG_KEY) || '').trim();
  const activeTag = (tag || localStorage.getItem(DASHBOARD_TAG_KEY) || '').trim();

  if (mode === 'task_ids') {
    return stored;
  }

  // Tag mode: ignore storage from a different job/tag
  if (activeTag && linkTag && linkTag !== activeTag) {
    return readFullRegressionTaskIdsFromDom();
  }
  if (activeTag && linkTag === activeTag && stored.length) {
    return stored;
  }
  if (stored.length && !activeTag) {
    return stored;
  }
  return readFullRegressionTaskIdsFromDom();
}

/** @deprecated prefer readScopedFullRegressionTaskIds — kept for callers */
export function readFullRegressionTaskIds() {
  return readScopedFullRegressionTaskIds();
}

export function persistFullRegressionLink(taskIds, tag = null) {
  const ids = [];
  const seen = new Set();
  (taskIds || []).forEach((raw) => {
    const id = normalizeJitaTaskId(raw);
    if (!id || seen.has(id)) return;
    seen.add(id);
    ids.push(id);
  });
  localStorage.setItem(FULL_LINK_TASK_IDS_KEY, JSON.stringify(ids));
  const t = (tag || '').trim();
  if (t) {
    localStorage.setItem(FULL_LINK_TAG_KEY, t);
  } else if ((localStorage.getItem(DASHBOARD_MODE_KEY) || 'tag') === 'task_ids') {
    localStorage.removeItem(FULL_LINK_TAG_KEY);
  }
  return ids;
}

export function clearFullRegressionLink() {
  localStorage.removeItem(FULL_LINK_TASK_IDS_KEY);
  localStorage.removeItem(FULL_LINK_TAG_KEY);
}

export function readRegressionScopeFromLocalStorage() {
  const mode = localStorage.getItem(DASHBOARD_MODE_KEY) || 'tag';
  const tag = (localStorage.getItem(DASHBOARD_TAG_KEY) || '').trim();
  const fullLinkIds = readScopedFullRegressionTaskIds(tag || null);

  if (mode === 'task_ids') {
    if (fullLinkIds.length) {
      return { mode: 'task_ids', tag: null, taskIds: fullLinkIds };
    }
    return { mode: 'task_ids', tag: null, taskIds: null };
  }

  // Tag mode: Full regression link IDs for THIS tag only (Regression_Run_Tasks)
  if (tag) {
    return {
      mode: 'tag',
      tag,
      taskIds: fullLinkIds.length ? fullLinkIds : null,
    };
  }
  if (fullLinkIds.length) {
    return { mode: 'task_ids', tag: null, taskIds: fullLinkIds };
  }
  return { mode: 'tag', tag: null, taskIds: null };
}

export async function resolveRegressionScope() {
  const fromLs = readRegressionScopeFromLocalStorage();
  if (fromLs.tag || (fromLs.taskIds && fromLs.taskIds.length)) {
    return fromLs;
  }
  try {
    const { default: api } = await import('../api');
    const { data: config } = await api.get('/mcp/regression/config');
    if (config?.input_mode === 'task_ids' && Array.isArray(config.task_ids) && config.task_ids.length) {
      return {
        mode: 'task_ids',
        tag: null,
        taskIds: config.task_ids.map(normalizeJitaTaskId).filter(Boolean),
      };
    }
    const tag = (config?.default_tag || config?.tag || '').trim();
    const fullLinkIds = readScopedFullRegressionTaskIds(tag || null);
    if (tag) {
      return {
        mode: 'tag',
        tag,
        taskIds: fullLinkIds.length ? fullLinkIds : null,
      };
    }
  } catch {
    // ignore — caller shows missing-scope error
  }
  return fromLs;
}

/** Prefer POST body when Full-link ID count exceeds this (avoids browser→Flask GET 414). */
export const TG_SCOPE_POST_THRESHOLD = 40;

/**
 * Build TG / triage-accuracy request scope from dashboard Regression_Run_Tasks.
 * Full-link task_ids win (same set as JITA → View in Triage Genie).
 * Tag is kept for labeling/cache when present; alone is fallback when no Full link.
 */
export function scopeToRequestPayload(scope, { reload = false } = {}) {
  const payload = {};
  const taskIds = Array.isArray(scope?.taskIds)
    ? scope.taskIds.map(normalizeJitaTaskId).filter(Boolean)
    : [];
  const tag = (scope?.tag || '').trim();

  if (taskIds.length) {
    payload.task_ids = taskIds;
    if (tag) payload.tag = tag;
  } else if (tag) {
    payload.tag = tag;
  }

  if (reload) payload.reload = true;
  return payload;
}

/**
 * Query-string form of {@link scopeToRequestPayload} for small GET requests.
 * task_ids are joined with commas. Prefer {@link shouldPostTriageScope} + POST for large lists.
 */
export function scopeToQueryParams(scope, { reload = false } = {}) {
  const payload = scopeToRequestPayload(scope, { reload });
  const params = {};
  if (payload.tag) params.tag = payload.tag;
  if (Array.isArray(payload.task_ids) && payload.task_ids.length) {
    params.task_ids = payload.task_ids.join(',');
  }
  if (payload.reload) params.reload = 'true';
  return params;
}

/** True when Full-link ID count should use POST JSON instead of GET query. */
export function shouldPostTriageScope(scope) {
  const n = Array.isArray(scope?.taskIds) ? scope.taskIds.filter(Boolean).length : 0;
  return n > TG_SCOPE_POST_THRESHOLD;
}
