import React, { useRef, useEffect } from "react";
import { PROACTIVE_ROSTER } from "../constants/proactiveAgents";

function relTime(iso) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 10) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export function AgentFeed({ agentEvents }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [agentEvents.length]);

  return (
    <div className="card" style={{ flex: 1 }}>
      <div className="card-header">
        <div className="card-title">
          🤖 Proactive Agent Activity
          <span className="tag proactive">Live</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--status-success)",
              animation: "pulse-dot 2s infinite",
            }}
          />
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
            {PROACTIVE_ROSTER.length} proactive agents
          </span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        {PROACTIVE_ROSTER.map((agent) => (
          <div
            key={agent.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              padding: "4px 10px",
              borderRadius: "var(--radius-sm)",
              background: "var(--surface-2)",
              border: "1px solid var(--border-subtle)",
              fontSize: 11,
              color: agent.color,
              fontWeight: 600,
            }}
          >
            <span>{agent.icon}</span>
            <span>{agent.name}</span>
          </div>
        ))}
      </div>

      <div className="divider" style={{ marginBottom: 8 }} />

      <div className="scroll-list" ref={scrollRef}>
        {agentEvents.length === 0 && (
          <div
            style={{
              padding: 20,
              textAlign: "center",
              color: "var(--text-tertiary)",
              fontSize: 13,
            }}
          >
            Agents initializing...
          </div>
        )}
        {agentEvents.map((event, idx) => (
          <AgentEventRow key={event.id} event={event} isNew={idx === 0} />
        ))}
      </div>
    </div>
  );
}

function AgentEventRow({ event, isNew }) {
  return (
    <div
      className="agent-event"
      style={{
        animationDelay: "0ms",
        background: isNew ? "rgba(10, 132, 255, 0.04)" : undefined,
        borderRadius: "var(--radius-md)",
      }}
    >
      <div className="agent-icon" style={{ background: `${event.agentColor}22` }}>
        <span>{event.agentIcon}</span>
        <div className="live-dot" />
      </div>
      <div className="agent-body">
        <div className="agent-name">
          <span style={{ color: event.agentColor }}>{event.agentName}</span>
          <span className="pill neutral" style={{ fontSize: 9, padding: "1px 6px" }}>
            AUTO
          </span>
        </div>
        <div className="agent-message">{event.message}</div>
        <div className="agent-time">{relTime(event.timestamp)}</div>
        {event.actions?.length > 0 && (
          <div className="agent-action-row">
            {event.actions.map((action, i) => (
              <button
                key={i}
                type="button"
                className={`btn btn-sm ${action.type === "primary" ? "btn-primary" : "btn-secondary"}`}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
