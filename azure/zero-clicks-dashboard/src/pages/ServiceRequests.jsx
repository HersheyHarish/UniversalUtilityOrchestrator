import React from "react";
import { ServiceQuickLinks } from "../components/ServiceQuickLinks";

export function ServiceRequests() {
  return (
    <div className="main-content">
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 24 }}>
        <h2 style={{ fontSize: 24 }}>Service Requests</h2>
        <ServiceQuickLinks />
        <div className="card">
          <p style={{ color: "var(--text-secondary)" }}>
            Track the status of your recent service requests here.
          </p>
        </div>
      </div>
    </div>
  );
}
