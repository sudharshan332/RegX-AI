/** Per-browser, per-user preferences. Never written to shared backend config. */

export function preferenceUserId(user) {
  return String(user?.username || user?.sub || "").trim();
}

export function scopedStorageKey(base, userId) {
  return `${base}.${userId || "anonymous"}`;
}

export function readScopedPref(base, userId) {
  try {
    const value = localStorage.getItem(scopedStorageKey(base, userId));
    return value == null ? null : value;
  } catch (_) {
    return null;
  }
}

export function writeScopedPref(base, userId, value) {
  try {
    const key = scopedStorageKey(base, userId);
    if (value == null || value === "") localStorage.removeItem(key);
    else localStorage.setItem(key, String(value));
  } catch (_) { /* storage may be blocked */ }
}

export const HOME_TAG_PREF = "regx.home.selectedTag";
export const HOME_MODE_PREF = "regx.home.inputMode";

const HOME_TAG_MIGRATED = "regx.home.selectedTag.migrated";
const LEGACY_HOME_TAG = "regressionDashboardTag";

/**
 * Last Home tag for this user. A pre-existing unscoped tag is claimed once
 * so the first signed-in user keeps their selection; later users do not inherit it.
 */
export function readHomeTagPref(userId) {
  const scoped = readScopedPref(HOME_TAG_PREF, userId);
  if (scoped) return scoped;
  try {
    if (localStorage.getItem(HOME_TAG_MIGRATED)) return null;
    const legacy = localStorage.getItem(LEGACY_HOME_TAG);
    if (!legacy) return null;
    writeScopedPref(HOME_TAG_PREF, userId, legacy);
    localStorage.setItem(HOME_TAG_MIGRATED, userId || "anonymous");
    return legacy;
  } catch (_) {
    return null;
  }
}

export function writeHomeTagPref(userId, tag) {
  writeScopedPref(HOME_TAG_PREF, userId, tag || "");
  try {
    if (tag) localStorage.setItem(LEGACY_HOME_TAG, tag);
    else localStorage.removeItem(LEGACY_HOME_TAG);
  } catch (_) { /* ignore */ }
}
