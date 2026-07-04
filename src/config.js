/**
 * Central API configuration. Set REACT_APP_API_URL in .env or .env.production
 * to point to your backend (e.g. http://10.111.52.90:5001 for server deployment).
 * In development, empty string uses the dev server proxy (see package.json "proxy").
 */
export const API_BASE_URL =
  process.env.REACT_APP_API_URL !== undefined
    ? process.env.REACT_APP_API_URL
    : process.env.NODE_ENV === "development"
    ? ""
    : "http://localhost:5001";

/** JITA web app origin (no trailing slash). Override if your cluster uses another host. */
export const JITA_WEB_ORIGIN = (
  process.env.REACT_APP_JITA_WEB_ORIGIN || "https://jita.eng.nutanix.com"
).replace(/\/$/, "");

/** Query key on /manage/* pages for the filter string (JITA may use search, filter, or q). */
const _jitaManageSearchParam =
  (process.env.REACT_APP_JITA_MANAGE_SEARCH_PARAM || "search")
    .trim()
    .replace(/[^\w.-]/g, "") || "search";

const _jitaJobProfileTmpl =
  process.env.REACT_APP_JITA_JOB_PROFILE_URL ||
  `{origin}/manage/job_profiles?${_jitaManageSearchParam}={search_query}`;
const _jitaTestSetTmpl =
  process.env.REACT_APP_JITA_TEST_SET_URL ||
  `{origin}/manage/test_sets?${_jitaManageSearchParam}={search_query}`;

/** JITA manage list + name filter (same as filter bar: showAll:true name:…). Override template for id-only URLs. */
export function jitaJobProfileWebUrl(entityId, entityName) {
  let out = _jitaJobProfileTmpl.replace("{origin}", JITA_WEB_ORIGIN);
  const id = entityId != null ? String(entityId).trim() : "";
  const name = entityName != null ? String(entityName).trim() : "";
  if (out.includes("{id}")) {
    if (!id) return "";
    out = out.replace(/{id}/g, id);
  }
  if (out.includes("{search_query}")) {
    if (!name) return "";
    out = out.replace(
      "{search_query}",
      encodeURIComponent(`showAll:true name:${name}`)
    );
  }
  if (out.includes("{id}") || out.includes("{search_query}")) return "";
  return out;
}

/** JITA manage list + name filter for test sets. */
export function jitaTestSetWebUrl(entityId, entityName) {
  let out = _jitaTestSetTmpl.replace("{origin}", JITA_WEB_ORIGIN);
  const id = entityId != null ? String(entityId).trim() : "";
  const name = entityName != null ? String(entityName).trim() : "";
  if (out.includes("{id}")) {
    if (!id) return "";
    out = out.replace(/{id}/g, id);
  }
  if (out.includes("{search_query}")) {
    if (!name) return "";
    out = out.replace(
      "{search_query}",
      encodeURIComponent(`showAll:true name:${name}`)
    );
  }
  if (out.includes("{id}") || out.includes("{search_query}")) return "";
  return out;
}
