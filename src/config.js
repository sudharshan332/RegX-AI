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
