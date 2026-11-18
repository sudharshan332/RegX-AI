/** Hash routes that survive the LDAP login screen (the address bar is not changed). */

export function parseAppHash(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  const [pathPart, queryPart] = raw.split("?");
  const page = pathPart.replace(/^\//, "").split("/").filter(Boolean)[0] || "home";
  const params = new URLSearchParams(queryPart || "");
  return { page, tab: params.get("tab") || "" };
}

export function readAppLocation() {
  if (typeof window === "undefined") return { page: "home", tab: "" };
  return parseAppHash(window.location.hash);
}

export function formatAppHash(page, extra = {}) {
  const params = new URLSearchParams();
  if (page === "release-dashboard" && extra.tab === "feats") {
    params.set("tab", "feats");
  }
  const qs = params.toString();
  if (page === "home" && !qs) return "";
  return `#/${page}${qs ? `?${qs}` : ""}`;
}

export function writeAppHash(page, extra = {}) {
  if (typeof window === "undefined") return;
  const next = formatAppHash(page, extra);
  const current = window.location.hash || "";
  if (current === next || (next === "" && (current === "" || current === "#" || current === "#/"))) return;
  if (next === "") {
    const url = `${window.location.pathname}${window.location.search}`;
    window.history.pushState(null, "", url);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    return;
  }
  window.location.hash = next;
}
