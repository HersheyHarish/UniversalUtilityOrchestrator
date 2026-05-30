import React from "react";

export function BillingHero({ billing }) {
  const total = billing.breakdown.reduce((sum, r) => sum + r.amount, 0);

  return (
    <div className="billing-hero">
      {/* Current Balance */}
      <div className="billing-stat due">
        <div className="billing-stat-label">Amount Due</div>
        <div className="billing-stat-value">${billing.currentBalance.toFixed(2)}</div>
        <div className="billing-stat-sub">
          <span>📅</span>
          Due {billing.dueDate} · {billing.daysUntilDue} days
        </div>
        <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
          <button className="btn btn-primary btn-sm">Pay Now</button>
          <button className="btn btn-secondary btn-sm">Auto-Pay On</button>
        </div>
      </div>

      {/* Usage */}
      <div className="billing-stat usage">
        <div className="billing-stat-label">Gas Usage This Period</div>
        <div className="billing-stat-value">42 <span style={{ fontSize: 16, fontWeight: 400, color: "var(--text-secondary)" }}>therms</span></div>
        <div className="billing-stat-sub">
          <span style={{ color: "var(--status-success)" }}>↓ 14% vs last year</span>
        </div>
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-tertiary)", marginBottom: 6 }}>
            <span>0 therms</span><span>60 therms</span>
          </div>
          <div className="gauge-bar">
            <div className="gauge-fill" style={{
              width: "70%",
              background: "linear-gradient(90deg, var(--brand-blue), var(--brand-blue-light))"
            }} />
          </div>
        </div>
      </div>

      {/* AI Savings */}
      <div className="billing-stat savings">
        <div className="billing-stat-label">AI-Identified Savings</div>
        <div className="billing-stat-value">$34<span style={{ fontSize: 16, fontWeight: 400, color: "var(--text-secondary)" }}>/mo</span></div>
        <div className="billing-stat-sub">
          <span style={{ color: "var(--status-success)" }}>3 opportunities found</span>
        </div>
        <div style={{ marginTop: 14 }}>
          <button className="btn btn-success btn-sm">View Savings</button>
        </div>
      </div>
    </div>
  );
}
