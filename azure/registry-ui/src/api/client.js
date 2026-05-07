/**
 * client.js — Registry API client
 *
 * All API calls to the registry function app.
 * Session token is read from sessionStorage on every call.
 */

const runtimeConfig = window.__UUA_RUNTIME_CONFIG__ || {};
const BASE = runtimeConfig.VITE_REGISTRY_URL || import.meta.env.VITE_REGISTRY_URL || "";
const FUNC_CODE = runtimeConfig.VITE_FUNC_CODE || import.meta.env.VITE_FUNC_CODE || "";

function token() {
  return sessionStorage.getItem("session_token") || "";
}

function url(path, params = {}) {
  const u = new URL(BASE + path, window.location.origin);
  if (FUNC_CODE) u.searchParams.set("code", FUNC_CODE);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, String(v));
  }
  return u.toString();
}

function messageFrom(data, fallback) {
  if (typeof data === "object" && data) return data.error || data.detail || fallback;
  return data || fallback;
}

function isSessionAuthFailure(path, msg) {
  if (path.startsWith("/api/auth/verify") || path.startsWith("/api/auth/logout")) return true;
  return /session|x-session-token|authentication required|log in/i.test(msg || "");
}

async function req(method, path, { body, params } = {}) {
  const headers = { "Content-Type": "application/json" };
  const t = token();
  if (t) headers["X-Session-Token"] = t;

  const res = await fetch(url(path, params), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  const msg = messageFrom(data, `HTTP ${res.status}`);

  if (res.status === 401 && isSessionAuthFailure(path, msg)) {
    sessionStorage.clear();
    window.location.href = "/login";
    throw new Error("Session expired");
  }

  if (!res.ok) {
    throw new Error(msg);
  }
  return data;
}

// ── Auth ─────────────────────────────────────────────────────────────────────
export const auth = {
  login: (username, password) =>
    req("POST", "/api/auth/login", { body: { username, password } }),
  logout: () =>
    req("POST", "/api/auth/logout"),
  verify: () =>
    req("GET", "/api/auth/verify"),
};

// ── Agents ────────────────────────────────────────────────────────────────────
export const agents = {
  list: (p = {}) => req("GET", "/api/agents", { params: p }),
  get: (id) => req("GET", `/api/agents/${id}`),
  create: (body) => req("POST", "/api/agents", { body }),
  replace: (id, b) => req("PUT", `/api/agents/${id}`, { body: b }),
  patch: (id, b) => req("PATCH", `/api/agents/${id}`, { body: b }),
  delete: (id, hard = false) =>
    req("DELETE", `/api/agents/${id}`, { params: hard ? { hard: "true" } : {} }),

  setStatus: (id, status, reason) =>
    req("PATCH", `/api/agents/${id}/status`, { body: { status, reason } }),

  ping: (id) => req("GET", `/api/agents/${id}/ping`),
  pingAll: () => req("POST", "/api/agents/ping-all"),

  addCapability: (id, cap) => req("POST", `/api/agents/${id}/capabilities`, { body: cap }),
  removeCapability: (id, name) => req("DELETE", `/api/agents/${id}/capabilities/${encodeURIComponent(name)}`),

  /**
   * Auto-fetch capabilities from a remote agent.
   *
   * Sends a capability-discovery prompt to the agent using the provided
   * endpoint, auth, and invocation config. Plain secret values are used here
   * (not Key Vault refs) so the fetch works before the agent is saved.
   *
   * @param {string}  endpointUrl       - Agent invoke URL
   * @param {object}  authConfig        - AuthConfig (type, names, locations)
   * @param {object}  authSecrets       - AuthSecrets (plain values — NOT saved)
   * @param {object}  invocationConfig  - InvocationConfig (body template, etc.)
   * @returns {Promise<{
   *   capabilities: Array<{name, description, input_schema, output_schema}>,
   *   raw_response: string,
   *   parse_strategy: string,
   *   warning: string|null
   * }>}
   */
  fetchCapabilities: (endpointUrl, authConfig, authSecrets, invocationConfig) =>
    req("POST", "/api/agents/capabilities/fetch", {
      body: {
        endpoint_url: endpointUrl,
        auth_config: authConfig,
        auth_secrets: authSecrets,
        invocation_config: invocationConfig,
      },
    }),
};

// ── Registry ──────────────────────────────────────────────────────────────────
export const registry = {
  stats: () => req("GET", "/api/agents/stats"),
  capabilities: () => req("GET", "/api/agents/capabilities"),

  export: async () => {
    const headers = { "Content-Type": "application/json" };
    const t = token();
    if (t) headers["X-Session-Token"] = t;
    const res = await fetch(url("/api/agents/export"), { headers });
    const blob = await res.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "registry-export.json";
    link.click();
    URL.revokeObjectURL(link.href);
  },
};

export const traces = {
  list: (params = {}) =>
    req("GET", "/api/traces", { params }),

  get: (id) =>
    req("GET", `/api/traces/${id}`),
};

export const observability = {
  metrics: (since_hours = 24) =>
    req("GET", "/api/observability/metrics", { params: { since_hours } }),

  agentMetrics: (since_hours = 24) =>
    req("GET", "/api/observability/agents", { params: { since_hours } }),

  timeseries: (since_hours = 24, bucket_hours = 1) =>
    req("GET", "/api/observability/timeseries", { params: { since_hours, bucket_hours } }),
};


export const ProactiveMessages = {
  fetch: (customerId, since, limit) =>
    req("GET", `/api/proactive/messages/${customerId}`, { params: { since, limit } }),
};