import React from "react";

export function PhonePreview({ alert, onAction }) {
  return (
    <div className="card" style={{ maxWidth: 360 }}>
      <div className="chip">Mobile Alert</div>
      <h3>{alert?.title || "No active alert"}</h3>
      <p>{alert?.body || "No alert body available."}</p>
      <div className="row">
        {(alert?.actions || []).map((a) => (
          <button className="button" key={a.action} onClick={() => onAction(a.action, alert.id)}>
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
