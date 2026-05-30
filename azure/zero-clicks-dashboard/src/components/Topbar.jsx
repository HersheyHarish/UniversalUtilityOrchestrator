import React from "react";
import { NavLink, Link } from "react-router-dom";

export function Topbar({
  customerId,
  orchStatus,
  onProactiveTrigger,
  proactiveLoading,
  hasUnreadProactive,
}) {
  const statusLabel = {
    connected: "Orchestrator Connected",
    disconnected: "Orchestrator Offline",
    checking: "Connecting...",
  }[orchStatus];

  return (
    <header className="topbar">
      <Link className="topbar-brand" to="/">
        <div className="topbar-logo">🔥</div>
        NexusGas
      </Link>

      <nav className="topbar-nav">
        <NavLink className={({ isActive }) => `topbar-link ${isActive ? "active" : ""}`} to="/" end>Dashboard</NavLink>
        <NavLink className={({ isActive }) => `topbar-link ${isActive ? "active" : ""}`} to="/bills">Bills & Payments</NavLink>
        <NavLink className={({ isActive }) => `topbar-link ${isActive ? "active" : ""}`} to="/usage">Usage</NavLink>
        <NavLink className={({ isActive }) => `topbar-link ${isActive ? "active" : ""}`} to="/service-requests">Service Requests</NavLink>
        <NavLink className={({ isActive }) => `topbar-link ${isActive ? "active" : ""}`} to="/programs">Programs</NavLink>
      </nav>

      <div className="topbar-right">
        <button
          type="button"
          className="topbar-proactive-btn"
          onClick={onProactiveTrigger}
          disabled={proactiveLoading || orchStatus !== "connected"}
          title="Run proactive check"
          aria-label="Run proactive check"
        >
          {proactiveLoading ? (
            <span className="topbar-proactive-spinner" />
          ) : (
            "🔔"
          )}
          {hasUnreadProactive && !proactiveLoading && (
            <span className="proactive-unread" />
          )}
        </button>

        <div className="orch-status" style={{ padding: "5px 10px" }}>
          <div className={`orch-status-dot ${orchStatus}`} />
          <span style={{ fontSize: 11 }}>{statusLabel}</span>
        </div>

        <div className="topbar-account">
          <div className="topbar-avatar">JD</div>
          <div className="topbar-account-info">
            <span className="topbar-account-name">James Doe</span>
            <span className="topbar-account-id">{customerId}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
