// api/orchestratorClient.js
// All calls proxy through Vite dev server -> orchestrator at :7071

const BASE = "";   // relative – Vite proxy handles /api/*

async function req(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await res.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { error: text }; }
  if (!res.ok) throw new Error(body.error || body.detail || `HTTP ${res.status}`);
  return body;
}

export const orchestratorApi = {
  // Health check
  health: () => req("/api/health"),

  // Proactive insights (built by orchestrator from Cosmos history)
  insights: (customerId, sinceHours = 168) =>
    req(`/api/insights?customer_id=${encodeURIComponent(customerId)}&since_hours=${sinceHours}`),

  // Copilot context for a specific date
  copilotContext: (customerId, date) =>
    req(`/api/copilot/context?customer_id=${encodeURIComponent(customerId)}&date=${encodeURIComponent(date)}`),

  // Alerts
  alerts: (customerId, status = "all") =>
    req(`/api/alerts?customer_id=${encodeURIComponent(customerId)}&status=${encodeURIComponent(status)}`),

  ackAlert: (alertId, action, customerId) =>
    req(`/api/alerts/${encodeURIComponent(alertId)}/ack`, {
      method: "POST",
      body: JSON.stringify({ action, customer_id: customerId }),
    }),

  // Reactive chat (goes to orchestrator planner -> executor pipeline)
  chat: (message, customerId, sessionId = null) =>
    req("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, customer_id: customerId, session_id: sessionId }),
    }),

  // Streaming chat (SSE) — use orchestratorStream.streamChat from callers
  chatStreamUrl: () => "/api/chat/stream",

  // Session history
  session: (sessionId) => req(`/api/sessions/${encodeURIComponent(sessionId)}`),
};
