/**
 * client.js — Registry API client
 *
 * Reads VITE_REGISTRY_URL and VITE_FUNC_CODE from env.
 * Empty VITE_REGISTRY_URL means same-origin (useful behind SWA proxy).
 * Session token is read from sessionStorage on every call.
 */

const BASE      = import.meta.env.VITE_REGISTRY_URL || "";
const FUNC_CODE = import.meta.env.VITE_FUNC_CODE    || "";

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

async function req(method, path, { body, params } = {}) {
  const headers = { "Content-Type": "application/json" };
  const t = token();
  if (t) headers["X-Session-Token"] = t;

  const res = await fetch(url(path, params), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    sessionStorage.clear();
    window.location.href = "/login";
    throw new Error("Session expired");
  }

  const ct   = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();

  if (!res.ok) {
    const msg = (typeof data === "object" ? data?.error || data?.detail : data) || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

// ── Auth ─────────────────────────────────────────────────────────────────────
export const auth = {
  login:  (username, password) =>
    req("POST", "/api/auth/login", { body: { username, password } }),
  logout: () =>
    req("POST", "/api/auth/logout"),
  verify: () =>
    req("GET", "/api/auth/verify"),
};

// ── Agents ────────────────────────────────────────────────────────────────────
export const agents = {
  list:   (p = {}) => req("GET",  "/api/agents",              { params: p }),
  get:    (id)     => req("GET",  `/api/agents/${id}`),
  create: (body)   => req("POST", "/api/agents",              { body }),
  replace:(id, b)  => req("PUT",  `/api/agents/${id}`,        { body: b }),
  patch:  (id, b)  => req("PATCH",`/api/agents/${id}`,        { body: b }),
  delete: (id, hard = false) =>
    req("DELETE", `/api/agents/${id}`, { params: hard ? { hard: "true" } : {} }),

  setStatus: (id, status, reason) =>
    req("PATCH", `/api/agents/${id}/status`, { body: { status, reason } }),

  ping:    (id) => req("GET",  `/api/agents/${id}/ping`),
  pingAll: ()   => req("POST", "/api/agents/ping-all"),

  addCapability:    (id, cap)  => req("POST",   `/api/agents/${id}/capabilities`,      { body: cap }),
  removeCapability: (id, name) => req("DELETE",  `/api/agents/${id}/capabilities/${encodeURIComponent(name)}`),
};

// ── Registry ──────────────────────────────────────────────────────────────────
export const registry = {
  stats:        () => req("GET", "/api/agents/stats"),
  capabilities: () => req("GET", "/api/agents/capabilities"),

  export: async () => {
    const headers = { "Content-Type": "application/json" };
    const t = token();
    if (t) headers["X-Session-Token"] = t;
    const res  = await fetch(url("/api/agents/export"), { headers });
    const blob = await res.blob();
    const link = document.createElement("a");
    link.href     = URL.createObjectURL(blob);
    link.download = "registry-export.json";
    link.click();
    URL.revokeObjectURL(link.href);
  },
};
