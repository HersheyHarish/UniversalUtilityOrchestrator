import React from "react";

export function BillsAndPayments() {
  return (
    <div className="main-content">
      <div className="card" style={{ flex: 1 }}>
        <h2 style={{ fontSize: 24, marginBottom: 16 }}>Bills & Payments</h2>
        <p style={{ color: "var(--text-secondary)" }}>
          Your payment history and detailed billing information will appear here.
        </p>
      </div>
    </div>
  );
}
