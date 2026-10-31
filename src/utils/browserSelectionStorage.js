/**
 * Browser-local (localStorage) helpers for per-user UI selections.
 *
 * Home tag and Release Dashboard release/branch must never be shared via the
 * backend. Keys are namespaced with the authenticated user's stable id when
 * available so multiple users on one browser keep independent selections.
 */

export const HOME_TAG_STORAGE_BASE = 'regx.home.selectedTag';
export const HOME_TAG_LEGACY_KEY = 'regressionDashboardTag';

export const RELEASE_MILESTONE_STORAGE_BASE = 'regx.release-dashboard.last';
export const RELEASE_LIST_STORAGE_BASE = 'regx.release-dashboard.releases';
export const RELEASE_LIST_LEGACY_KEY = 'regx.release-dashboard.releases';

/** Stable id for namespacing — prefer username, then JWT sub, then email local-part. */
export function stableUserId(userOrId) {
  if (userOrId == null || userOrId === '') return '';
  if (typeof userOrId === 'string' || typeof userOrId === 'number') {
    return String(userOrId).trim();
  }
  const username = String(
    userOrId.username || userOrId.sub || userOrId.user_name || userOrId.preferred_username || ''
  ).trim();
  if (username) return username;
  const email = String(userOrId.email || userOrId.mail || '').trim();
  if (email.includes('@')) return email.split('@')[0];
  return email;
}

export function scopedStorageKey(baseKey, userOrId) {
  const id = stableUserId(userOrId);
  return id ? `${baseKey}.${id}` : `${baseKey}.anonymous`;
}

function safeGet(key) {
  if (!key) return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key, value) {
  if (!key) return false;
  try {
    if (value == null || value === '') {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, String(value));
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * Read a scoped value. Prefers user-scoped key, then optional legacy unscoped keys.
 */
export function readScopedItem(baseKey, userOrId, { legacyKeys = [] } = {}) {
  const scoped = safeGet(scopedStorageKey(baseKey, userOrId));
  if (scoped != null && scoped !== '') return scoped;
  for (const legacy of legacyKeys) {
    const v = safeGet(legacy);
    if (v != null && v !== '') return v;
  }
  return null;
}

/** Write only the user-scoped key (never a shared/global backend store). */
export function writeScopedItem(baseKey, userOrId, value) {
  return safeSet(scopedStorageKey(baseKey, userOrId), value);
}

export function readHomeSelectedTag(userOrId) {
  const raw = readScopedItem(HOME_TAG_STORAGE_BASE, userOrId, {
    legacyKeys: [HOME_TAG_LEGACY_KEY],
  });
  return (raw || '').trim() || null;
}

export function writeHomeSelectedTag(userOrId, tag) {
  const value = (tag || '').trim();
  writeScopedItem(HOME_TAG_STORAGE_BASE, userOrId, value || null);
  // Mirror into the legacy unscoped key so same-session readers (regressionScope,
  // Failed Analysis) stay aligned without every call site needing AuthContext yet.
  safeSet(HOME_TAG_LEGACY_KEY, value || null);
}

export function readReleaseMilestone(userOrId, fallback = '7.7') {
  const raw = readScopedItem(RELEASE_MILESTONE_STORAGE_BASE, userOrId);
  const value = (raw || '').trim();
  return value || fallback;
}

export function writeReleaseMilestone(userOrId, milestone) {
  const value = (milestone || '').trim();
  if (!value) return false;
  return writeScopedItem(RELEASE_MILESTONE_STORAGE_BASE, userOrId, value);
}

export function readReleaseList(userOrId) {
  const raw = readScopedItem(RELEASE_LIST_STORAGE_BASE, userOrId, {
    legacyKeys: [RELEASE_LIST_LEGACY_KEY],
  });
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function writeReleaseList(userOrId, releases) {
  const list = Array.isArray(releases) ? releases : [];
  try {
    return writeScopedItem(RELEASE_LIST_STORAGE_BASE, userOrId, JSON.stringify(list));
  } catch {
    return false;
  }
}
