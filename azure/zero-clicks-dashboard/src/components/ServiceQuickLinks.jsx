import React from "react";

const SERVICE_ITEMS = [
  { icon: "🔥", label: "Report Gas Smell", color: "var(--status-danger)", urgent: true },
  { icon: "🚿", label: "Start/Stop Service", color: "var(--brand-blue)" },
  { icon: "📋", label: "Transfer Service", color: "var(--brand-blue)" },
  { icon: "🔎", label: "Check Outage Map", color: "var(--status-warning)" },
  { icon: "📞", label: "Schedule Inspection", color: "var(--status-success)" },
  { icon: "♻️", label: "Green Energy Program", color: "#34D399" },
];

export function ServiceQuickLinks() {
  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 16 }}>⚡ Quick Actions</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {SERVICE_ITEMS.map(item => (
          <button
            key={item.label}
            className="btn btn-secondary"
            style={{
              justifyContent: "flex-start",
              gap: 8,
              padding: "10px 12px",
              border: item.urgent ? "1px solid rgba(239,68,68,0.3)" : undefined,
              background: item.urgent ? "var(--status-danger-bg)" : undefined,
              color: item.urgent ? "var(--status-danger)" : undefined,
            }}
          >
            <span>{item.icon}</span>
            <span style={{ fontSize: 12 }}>{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
