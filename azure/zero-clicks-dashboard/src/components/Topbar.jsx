import React, { useState, useEffect, useRef } from "react";
import { NavLink, Link } from "react-router-dom";
import { Bot, ChevronDown } from "lucide-react";

export function Topbar({
  customerId,
  orchStatus,
  onProactiveTrigger,
  proactiveLoading,
  hasUnreadProactive,
  activeAgents = [],
}) {
  const [agentsOpen, setAgentsOpen] = useState(false);
  const popoverRef = useRef(null);

  // Close popover on outside click
  useEffect(() => {
    if (!agentsOpen) return;
    const handler = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setAgentsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [agentsOpen]);

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
        <NavLink className={({ isActive }) => `topbar-link ${isActive ? "active" : ""}`} to="/reactive-email">Reactive Email</NavLink>
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

        {/* Agents popover */}
        <div className="agents-popover-anchor" ref={popoverRef} style={{ position: "relative" }}>
          <button
            type="button"
            className="agents-btn"
            onClick={() => setAgentsOpen(o => !o)}
            aria-expanded={agentsOpen}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              padding: "6px 12px",
              background: "var(--surface-2)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-md)",
              fontSize: 12,
              fontWeight: 500,
              cursor: "pointer",
              color: "var(--text-secondary)",
              transition: "all var(--transition)",
              outline: "none"
            }}
          >
            <Bot size={13} style={{ color: "var(--brand-blue)" }} />
            <span>Agents{activeAgents.length > 0 ? ` (${activeAgents.length})` : ''}</span>
            <ChevronDown size={11} className={`agents-chevron ${agentsOpen ? 'open' : ''}`} style={{ transition: "transform 0.2s" }} />
          </button>

          {agentsOpen && (
            <div className="agents-popover" style={{
              position: "absolute",
              top: "calc(100% + 8px)",
              right: 0,
              minWidth: 280,
              maxHeight: 340,
              overflowY: "auto",
              background: "var(--surface-1)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-lg)",
              boxShadow: "var(--shadow-lg)",
              zIndex: 200,
              display: "flex",
              flexDirection: "column"
            }}>
              <div className="agents-popover-header" style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px 8px",
                fontSize: 10,
                fontWeight: 700,
                color: "var(--text-tertiary)",
                textTransform: "uppercase",
                letterSpacing: "0.07em",
                borderBottom: "1px solid var(--border-subtle)"
              }}>
                Active Agents
                <span className="agents-count-badge" style={{
                  background: "var(--brand-blue)",
                  color: "#fff",
                  fontSize: 9,
                  fontWeight: 700,
                  padding: "1px 7px",
                  borderRadius: "999px"
                }}>{activeAgents.length}</span>
              </div>
              {activeAgents.length === 0 && (
                <div className="agent-row agent-row-empty" style={{
                  padding: "12px 14px",
                  color: "var(--text-tertiary)",
                  fontSize: 12,
                  fontStyle: "italic",
                  textAlign: "center"
                }}>
                  No agents found — is the orchestrator running?
                </div>
              )}
              {activeAgents.map((agent, i) => (
                <div key={i} className="agent-row" style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "9px 14px",
                  borderBottom: "1px solid var(--border-subtle)",
                  background: "transparent",
                  transition: "background var(--transition)"
                }}>
                  <span className="agent-dot" style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: "var(--status-success)",
                    boxShadow: "0 0 6px var(--status-success)",
                    flexShrink: 0,
                    marginTop: 5
                  }} />
                  <div className="agent-row-info" style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                    minWidth: 0,
                    textAlign: "left"
                  }}>
                    <span className="agent-row-name" style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: "var(--text-primary)"
                    }}>{agent.name}</span>
                    {agent.description && (
                      <span className="agent-row-desc" style={{
                        fontSize: 10,
                        color: "var(--text-secondary)",
                        lineHeight: 1.4
                      }}>{agent.description}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

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
