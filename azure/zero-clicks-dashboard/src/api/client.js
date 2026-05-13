async function request(endpoint, options = {}) {
  const res = await fetch(endpoint, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await res.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { error: text || `HTTP ${res.status}` };
  }
  if (!res.ok) {
    throw new Error(payload.error || payload.detail || `HTTP ${res.status}`);
  }
  return payload;
}

export const api = {
  insights: (customerId, sinceHours = 24) =>
    request(`/api/insights?customer_id=${encodeURIComponent(customerId)}&since_hours=${sinceHours}`),
  copilotContext: (customerId, date) =>
    request(`/api/copilot/context?customer_id=${encodeURIComponent(customerId)}&date=${encodeURIComponent(date)}`),
  alerts: (customerId, status = "all") =>
    request(`/api/alerts?customer_id=${encodeURIComponent(customerId)}&status=${encodeURIComponent(status)}`),
  ackAlert: (alertId, action, customerId) =>
    request(`/api/alerts/${encodeURIComponent(alertId)}/ack`, {
      method: "POST",
      body: JSON.stringify({ action, customer_id: customerId }),
    }),
};
