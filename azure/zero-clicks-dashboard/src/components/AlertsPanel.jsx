import React from "react";

// Static mock alerts — in production these come from /api/alerts
const MOCK_ALERTS = [
  {
    id: "alert-1",
    icon: "🌡️",
    iconBg: "rgba(245, 158, 11, 0.15)",
    title: "Cold snap detected in your area",
    desc: "Temperatures expected to drop to 28°F this weekend. Your heating system may work harder than usual.",
    time: "10 min ago",
    pill: "warning",
    pillLabel: "Advisory",
    isUnread: true,
  },
  {
    id: "alert-2",
    icon: "✅",
    iconBg: "rgba(34, 197, 94, 0.15)",
    title: "Autopay confirmed — May 28",
    desc: "Payment of $84.50 scheduled to Visa ****4821. You'll receive a confirmation email 24h before.",
    time: "2 hrs ago",
    pill: "success",
    pillLabel: "Confirmed",
    isUnread: true,
  },
  {
    id: "alert-3",
    icon: "🔧",
    iconBg: "rgba(59, 130, 246, 0.15)",
    title: "Planned maintenance — May 15, 2–5 PM",
    desc: "Brief service interruption for your zone (Zone 4B). No action needed.",
    time: "Yesterday",
    pill: "info",
    pillLabel: "Scheduled",
    isUnread: false,
  },
  {
    id: "alert-4",
    icon: "💡",
    iconBg: "rgba(167, 139, 250, 0.15)",
    title: "Smart thermostat rebate available",
    desc: "EfficiencyAgent found a $150 rebate for qualifying devices. Deadline: May 31.",
    time: "2 days ago",
    pill: "neutral",
    pillLabel: "Opportunity",
    isUnread: false,
  },
];

export function AlertsPanel({ realAlerts, onAckAlert }) {
  const displayAlerts = realAlerts.length > 0
    ? realAlerts.map(a => ({
        id: a.id,
        icon: "🔔",
        iconBg: "rgba(10,132,255,0.15)",
        title: a.title || "New Alert",
        desc: a.body || "",
        time: "just now",
        pill: "info",
        pillLabel: a.channel || "Alert",
        isUnread: a.status !== "acked",
      }))
    : MOCK_ALERTS;

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          🔔 Notifications
          <span style={{
            background: "var(--brand-blue)",
            color: "#fff",
            borderRadius: "999px",
            fontSize: 10,
            fontWeight: 700,
            padding: "1px 7px",
          }}>
            {displayAlerts.filter(a => a.isUnread).length}
          </span>
        </div>
        <button className="btn btn-ghost btn-sm">Mark all read</button>
      </div>

      <div className="scroll-list">
        {displayAlerts.map(alert => (
          <div key={alert.id} className={`alert-item ${alert.isUnread ? "unread" : ""}`}>
            <div className="alert-icon-wrap" style={{ background: alert.iconBg }}>
              {alert.icon}
            </div>
            <div className="alert-body">
              <div className="alert-title">{alert.title}</div>
              <div className="alert-desc">{alert.desc}</div>
              <div className="alert-meta">
                <span className={`pill ${alert.pill}`}>
                  <span className="pill-dot" />{alert.pillLabel}
                </span>
                <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{alert.time}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
