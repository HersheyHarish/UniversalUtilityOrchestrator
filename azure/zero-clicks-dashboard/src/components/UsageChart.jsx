import React, { useState } from "react";

const MAX_HEIGHT = 100;

export function UsageChart({ usageData }) {
  const [hovered, setHovered] = useState(null);
  const maxVal = Math.max(...usageData.map(d => Math.max(d.therms, d.prev)));

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          📈 Monthly Gas Usage
          <span className="tag proactive">Proactive</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost btn-sm">6 Mo</button>
          <button className="btn btn-secondary btn-sm">12 Mo</button>
        </div>
      </div>

      <div className="usage-chart-container">
        {/* Chart */}
        <div className="chart-bars">
          {usageData.map((d, i) => {
            const thisH = Math.round((d.therms / maxVal) * MAX_HEIGHT);
            const prevH = Math.round((d.prev / maxVal) * MAX_HEIGHT);
            const isHovered = hovered === i;
            const isLast = i === usageData.length - 1;

            return (
              <div
                key={d.month}
                className="chart-bar-group"
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
              >
                {/* Tooltip */}
                {isHovered && (
                  <div style={{
                    position: "absolute",
                    bottom: `${thisH + 16}px`,
                    background: "var(--surface-4)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "var(--radius-sm)",
                    padding: "6px 10px",
                    fontSize: 11,
                    color: "var(--text-primary)",
                    whiteSpace: "nowrap",
                    zIndex: 10,
                    pointerEvents: "none",
                    boxShadow: "var(--shadow-sm)",
                  }}>
                    <strong>{d.month}</strong>: {d.therms} therms
                    <div style={{ color: "var(--text-tertiary)" }}>Prior: {d.prev} therms</div>
                  </div>
                )}

                <div className="chart-bar-wrap" style={{ position: "relative" }}>
                  {/* Previous year bar */}
                  <div
                    className={`chart-bar previous`}
                    style={{ height: `${prevH}px`, marginRight: 2, flex: 1 }}
                  />
                  {/* This year bar */}
                  <div
                    className={`chart-bar ${isLast ? "selected" : "current"}`}
                    style={{
                      height: `${thisH}px`,
                      flex: 1,
                      boxShadow: isLast ? "0 0 12px rgba(10,132,255,0.3)" : undefined,
                    }}
                  />
                </div>
                <div className="chart-label">{d.month}</div>
              </div>
            );
          })}
        </div>

        <div className="chart-legend">
          <div className="chart-legend-item">
            <div className="chart-legend-dot" style={{ background: "var(--brand-blue)" }} />
            This Year
          </div>
          <div className="chart-legend-item">
            <div className="chart-legend-dot" style={{ background: "var(--surface-4)" }} />
            Prior Year
          </div>
          <div className="chart-legend-item">
            <div className="chart-legend-dot" style={{ background: "var(--brand-orange)" }} />
            Current Period
          </div>
        </div>
      </div>
    </div>
  );
}
