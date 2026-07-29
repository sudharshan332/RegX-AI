/**
 * Normalize auth user payloads from login (LDAP) and /me (JWT).
 * Login returns: { username, displayName, email }
 * JWT /me returns: { sub, name, email, iat, exp }
 */

export function normalizeAuthUser(raw) {
  if (!raw || typeof raw !== "object") return null;

  const username = String(
    raw.username || raw.sub || raw.user_name || raw.preferred_username || ""
  ).trim();
  const name = String(
    raw.name || raw.displayName || raw.display_name || raw.full_name || ""
  ).trim();
  const email = String(raw.email || raw.mail || "").trim();

  if (!username && !name && !email) return null;

  return {
    ...raw,
    username: username || (email.includes("@") ? email.split("@")[0] : ""),
    sub: raw.sub || username || "",
    name: name || username || (email.includes("@") ? email.split("@")[0] : ""),
    displayName: name || username || "",
    email,
  };
}

/** Best human-readable label for chrome (sidebar, headers). */
export function resolveDisplayName(user, fallback = "User") {
  const u = normalizeAuthUser(user);
  if (!u) return fallback;
  return (
    u.displayName ||
    u.name ||
    u.username ||
    u.sub ||
    (u.email.includes("@") ? u.email.split("@")[0] : u.email) ||
    fallback
  );
}
