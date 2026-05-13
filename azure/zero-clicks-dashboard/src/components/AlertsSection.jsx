import React from "react";
import { PhonePreview } from "./PhonePreview";

export function AlertsSection({ alerts, onAckAlert }) {
  const topAlert = (alerts || [])[0];
  return (
    <section className="section">
      <h2>Omnichannel Alert Simulation</h2>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <PhonePreview
          alert={topAlert}
          onAction={(action, alertId) => onAckAlert(alertId, action)}
        />
        <div style={{ flex: 1 }}>
          <div className="card-grid">
            {(alerts || []).map((a) => (
              <div className="card" key={a.id}>
                <div className="row">
                  <span className="chip">{a.channel}</span>
                  <span className="chip">{a.status}</span>
                </div>
                <h3>{a.title}</h3>
                <p>{a.body}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
