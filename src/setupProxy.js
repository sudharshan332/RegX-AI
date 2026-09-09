/**
 * Dev-server proxy with long timeouts for handover CR creation (git clone/push).
 * When this file exists, CRA ignores package.json "proxy".
 */
const { createProxyMiddleware } = require("http-proxy-middleware");

const LONG_TIMEOUT_MS = 600000; // 10 minutes

module.exports = function setupProxy(app) {
  app.use(
    ["/mcp", "/api"],
    createProxyMiddleware({
      target: "http://localhost:5001",
      changeOrigin: true,
      proxyTimeout: LONG_TIMEOUT_MS,
      timeout: LONG_TIMEOUT_MS,
    })
  );
};
