import React from "react";

export function InsightsSection({ insights, onInsightAction }) {
  return (
    <section className="section">
      <h2>AI Insights (Zero-Click)</h2>
      <div className="card-grid">
        {(insights || []).map((item) => (
          <div className="card" key={item.id}>
            <div className="row">
              <span className="chip">{item.severity}</span>
              <span className="chip">{item.type}</span>
            </div>
            <h3>{item.title}</h3>
            <p>{item.summary}</p>
            {item.cta?.label && (
              <button
                className="button"
                onClick={() => onInsightAction(item.cta.action, item.cta.payload)}
              >
                {item.cta.label}
              </button>
            )}
            <p style={{ color: "#9fb0c7", fontSize: 12 }}>
              Source session: {item.session_id}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
