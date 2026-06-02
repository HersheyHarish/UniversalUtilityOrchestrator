/** Registry for proactive feed — maps orchestrator agent ids to UI metadata. */
export const PROACTIVE_AGENT_REGISTRY = {
  outage_detection_agent: {
    id: "outage_detection_agent",
    name: "Outage Agent",
    icon: "⚠️",
    color: "#EF4444",
  },
  anomaly_detection_agent: {
    id: "anomaly_detection_agent",
    name: "Anomaly Agent",
    icon: "📈",
    color: "#8B5CF6",
  },
  bill_shock_forecast_agent: {
    id: "bill_shock_forecast_agent",
    name: "Bill Forecast Agent",
    icon: "📊",
    color: "#F59E0B",
  },
  solar_performance_credit_loss_agent: {
    id: "solar_performance_credit_loss_agent",
    name: "Solar Agent",
    icon: "☀️",
    color: "#10B981",
  },
  weather_context_agent: {
    id: "weather_context_agent",
    name: "Weather Agent",
    icon: "🌡️",
    color: "#3B82F6",
  },
  orchestrator: {
    id: "orchestrator",
    name: "Orchestrator",
    icon: "🤖",
    color: "#0A84FF",
  },
};

export const PROACTIVE_ROSTER = Object.values(PROACTIVE_AGENT_REGISTRY).filter(
  (a) => a.id !== "orchestrator"
);

const FEED_TRUNCATE = 280;

export function mapAgentMeta(agentId) {
  const key = agentId || "orchestrator";
  return (
    PROACTIVE_AGENT_REGISTRY[key] || {
      id: key,
      name: key.replace(/_/g, " ").replace(/\bagent\b/gi, "").trim() || "Agent",
      icon: "🤖",
      color: "#64748B",
    }
  );
}

export function truncateFeedMessage(message) {
  if (!message || message.length <= FEED_TRUNCATE) return message;
  return `${message.slice(0, FEED_TRUNCATE).trim()}…`;
}
