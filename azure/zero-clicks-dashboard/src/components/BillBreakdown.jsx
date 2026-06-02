import React, { useState } from "react";

export function BillBreakdown({ billing }) {
  const [expanded, setExpanded] = useState(false);
  const total = billing.breakdown.reduce((s, r) => s + r.amount, 0);
  const rows = expanded ? billing.breakdown : billing.breakdown.slice(0, 4);

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">🧾 Current Bill Breakdown</div>
        <div className="pill neutral">
          <span>Statement: Apr 28 – May 27</span>
        </div>
      </div>

      <table className="bill-table">
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td>${row.amount.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {billing.breakdown.length > 4 && (
        <button
          className="btn btn-ghost btn-sm"
          style={{ marginTop: 8 }}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show Less ▲" : `Show ${billing.breakdown.length - 4} More ▼`}
        </button>
      )}

      <div className="divider" style={{ marginTop: 12, marginBottom: 0 }} />

      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        paddingTop: 14,
      }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
          Total Due
        </span>
        <span style={{
          fontSize: 22,
          fontWeight: 700,
          color: "var(--brand-orange-light)",
        }}>
          ${total.toFixed(2)}
        </span>
      </div>

      <div style={{ marginTop: 12 }}>
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 12,
          color: "var(--text-tertiary)",
          marginBottom: 8,
        }}>
          <span>Last payment: ${billing.lastPayment.amount.toFixed(2)} on {billing.lastPayment.date}</span>
          <span className="pill success"><span className="pill-dot" />Paid</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button className="btn btn-primary" style={{ flex: 1 }}>Pay ${billing.currentBalance.toFixed(2)}</button>
        <button className="btn btn-secondary">Schedule</button>
        <button className="btn btn-ghost">Dispute</button>
      </div>
    </div>
  );
}
