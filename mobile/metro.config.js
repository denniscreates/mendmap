// Metro config for MendMap.
// In development, requests to /api/* on the Expo dev server are forwarded to the
// FastAPI backend on this computer (port 8000). The phone then only needs to reach
// the dev server, which also works through `expo start --tunnel` on networks
// (school/guest Wi-Fi) that block devices from talking to each other.
const http = require("http");
const { getDefaultConfig } = require("expo/metro-config");

const API_TARGET = { host: "127.0.0.1", port: Number(process.env.MENDMAP_API_PORT || 8000) };

const config = getDefaultConfig(__dirname);

const previous = config.server.enhanceMiddleware;
config.server.enhanceMiddleware = (middleware, server) => {
  const base = previous ? previous(middleware, server) : middleware;
  return (req, res, next) => {
    if (!req.url || !(req.url === "/api" || req.url.startsWith("/api/"))) return base(req, res, next);

    const path = req.url.slice(4) || "/";
    const headers = { ...req.headers, host: `${API_TARGET.host}:${API_TARGET.port}` };
    const proxied = http.request({ ...API_TARGET, path, method: req.method, headers }, (apiRes) => {
      res.writeHead(apiRes.statusCode || 502, apiRes.headers);
      apiRes.pipe(res);
    });
    proxied.on("error", () => {
      if (!res.headersSent) res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "MendMap API is not running on this computer (port 8000)" }));
    });
    req.pipe(proxied);
  };
};

module.exports = config;
