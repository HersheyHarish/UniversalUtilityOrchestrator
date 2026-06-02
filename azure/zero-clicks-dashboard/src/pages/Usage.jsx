import React from "react";
import { UsageChart } from "../components/UsageChart";

export function Usage({ usageData }) {
  return (
    <div className="main-content">
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 24 }}>
        <h2 style={{ fontSize: 24 }}>Detailed Usage Analysis</h2>
        {usageData && <UsageChart usageData={usageData} />}
        <div className="card">
          <p style={{ color: "var(--text-secondary)" }}>
            More detailed breakdown of daily and hourly usage trends will appear here.
          </p>
        </div>
      </div>
    </div>
  );
}
