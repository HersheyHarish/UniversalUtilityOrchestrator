/**
 * ProactiveNotifications.jsx — Admin observability for proactive triggers.
 *
 * Two tabs:
 *   Execution traces — lists traces where user_message starts with [PROACTIVE
 *                      (filtered from the existing traces container).
 *                      Clicking a row opens full TraceDetail (DAG, timeline, steps).
 *   Customer messages — calls GET /api/proactive/messages/{customer_id} on the
 *                       orchestrator to show all proactive_trigger messages for
 *                       a specific customer, with original vs enriched diff.
 *
 * No separate Cosmos container is needed — proactive messages live in the
 * existing `messages` container with message_type="proactive_trigger".
 */
import React, { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { traces as tracesApi, ProactiveMessages as fetchProactiveMessages } from "../api/client.js";
import { Spinner, Alert, EmptyState } from "./Primitives.jsx";
import { IcRefresh, IcSearch, IcChevronRight } from "./Icons.jsx";

// ── Constants ─────────────────────────────────────────────────────────────────

const SEVERITY_STYLE = {
  high: { bg: "#fee2e2", color: "#991b1b", dot: "#ef4444" },
  medium: { bg: "#fef3c7", color: "#92400e", dot: "#f59e0b" },
  low: { bg: "#f0fdf4", color: "#166534", dot: "#22c55e" },
};

const STATUS_STYLE = {
  completed: { bg: "#dcfce7", color: "#15803d" },
  failed: { bg: "#fee2e2", color: "#991b1b" },
  running: { bg: "#e0e7ff", color: "#3730a3" },
};

const WINDOW_OPTS = [
  { label: "1 h", value: 1 },
  { label: "6 h", value: 6 },
  { label: "24 h", value: 24 },
  { label: "7 d", value: 168 },
];

// ── Badge helpers ─────────────────────────────────────────────────────────────

function SeverityBadge({ severity }) {
  const s = SEVERITY_STYLE[severity] || SEVERITY_STYLE.medium;
  return (
    <span style={{
      background: s.bg, color: s.color,
      padding: "2px 8px", borderRadius: 99, fontSize: 11,
      fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: s.dot }} />
      {severity || "medium"}
    </span>
  );
}

function StatusPill({ status }) {
  const s = STATUS_STYLE[status] || { bg: "#f1f5f9", color: "#334155" };
  return (
    <span style={{
      background: s.bg, color: s.color,
      padding: "2px 8px", borderRadius: 99, fontSize: 11, fontWeight: 500,
    }}>
      {status}
    </span>
  );
}

function msLabel(ms) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

// ── Parse proactive metadata from trace user_message ─────────────────────────
// Proactive traces store the enrichment prompt as user_message with the format:
//   [PROACTIVE ENRICHMENT — HIGH SEVERITY]\nAgent: ...\nEvent: ...\n...

function parseTraceMetadata(userMessage = "") {
  const severityMatch = userMessage.match(/PROACTIVE ENRICHMENT — (\w+) SEVERITY/i);
  const agentMatch = userMessage.match(/Agent: ([^\n]+)/);
  const eventMatch = userMessage.match(/Event: ([^\n]+)/);
  const custMatch = userMessage.match(/Customer: ([^\n]+)/);
  return {
    severity: severityMatch ? severityMatch[1].toLowerCase() : "medium",
    agentName: agentMatch ? agentMatch[1].trim() : "—",
    eventType: eventMatch ? eventMatch[1].trim() : "—",
    customerId: custMatch ? custMatch[1].trim() : null,
  };
}

// ── Trace table row ───────────────────────────────────────────────────────────

function TraceRow({ trace, onClick }) {
  const { severity, agentName, eventType, customerId } =
    parseTraceMetadata(trace.user_message);

  return (
    <tr style={{ cursor: "pointer" }} onClick={onClick}>
      <td>
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
          <SeverityBadge severity={severity} />
          <span style={{
            fontSize: 11, fontWeight: 600,
            background: "#f0fdf4", color: "#166534",
            padding: "1px 7px", borderRadius: 99,
          }}>
            {eventType}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          <span>Agent: <strong>{agentName}</strong></span>
          {(customerId || trace.customer_id) && (
            <span style={{ marginLeft: 10 }}>
              Customer: {customerId || trace.customer_id}
            </span>
          )}
        </div>
      </td>
      <td><StatusPill status={trace.status} /></td>
      <td>
        <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          {trace.agents_invoked || 0}
          <span style={{ color: "var(--text-muted)", marginLeft: 4, fontSize: 11 }}>steps</span>
        </span>
      </td>
      <td style={{ fontSize: 12, color: "var(--text-secondary)" }}>
        {msLabel(trace.total_latency_ms)}
      </td>
      <td style={{ fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
        {trace.started_at ? new Date(trace.started_at).toLocaleString() : "—"}
      </td>
      <td>
        <IcChevronRight size={13} style={{ color: "var(--text-muted)" }} />
      </td>
    </tr>
  );
}

// ── Message card ──────────────────────────────────────────────────────────────

function MessageCard({ msg }) {
  const [expanded, setExpanded] = useState(false);
  const meta = msg.metadata || {};
  const isEnriched = Boolean(
    meta.enriched && meta.original_message && meta.original_message !== msg.content
  );

  return (
    <div style={{
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: "var(--bg-card)",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 14px", display: "flex",
        alignItems: "flex-start", gap: 10, cursor: "pointer",
      }}
        onClick={() => setExpanded(e => !e)}>
        {/* Severity stripe */}
        <div style={{
          width: 3, alignSelf: "stretch", borderRadius: 99, flexShrink: 0,
          background: SEVERITY_STYLE[meta.severity]?.dot || "#94a3b8",
        }} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            display: "flex", gap: 6, flexWrap: "wrap",
            alignItems: "center", marginBottom: 4
          }}>
            <SeverityBadge severity={meta.severity} />
            <span style={{
              fontSize: 11, background: "#f1f5f9", color: "var(--text-secondary)",
              padding: "1px 7px", borderRadius: 99,
            }}>
              {meta.event_type || "—"}
            </span>
            {isEnriched && (
              <span style={{
                fontSize: 10, fontWeight: 600,
                background: "#ede9fe", color: "#5b21b6",
                padding: "1px 6px", borderRadius: 99,
              }}>
                🧠 enriched
              </span>
            )}
          </div>

          <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.5 }}>
            {msg.content}
          </div>

          <div style={{
            fontSize: 11, color: "var(--text-muted)", marginTop: 4,
            display: "flex", gap: 10,
          }}>
            <span>From: <strong>{meta.source_agent || "—"}</strong></span>
            <span>{new Date(msg.created_at).toLocaleString()}</span>
          </div>
        </div>

        <span style={{ fontSize: 10, color: "var(--text-muted)", flexShrink: 0 }}>
          {expanded ? "▲" : "▼"}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{
          borderTop: "1px solid var(--border)", padding: "10px 14px",
          display: "flex", flexDirection: "column", gap: 10,
        }}>
          {/* Original message (if enriched) */}
          {isEnriched && (
            <div>
              <div style={{
                fontSize: 10, fontWeight: 600, color: "var(--text-muted)",
                textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 3,
              }}>
                Original (before enrichment)
              </div>
              <div style={{
                fontSize: 12, color: "var(--text-secondary)",
                fontStyle: "italic", lineHeight: 1.5,
              }}>
                {meta.original_message}
              </div>
            </div>
          )}

          {/* Context key-values */}
          {meta.context && Object.keys(meta.context).length > 0 && (
            <div>
              <div style={{
                fontSize: 10, fontWeight: 600, color: "var(--text-muted)",
                textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4,
              }}>
                Context
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {Object.entries(meta.context).map(([k, v]) => (
                  <div key={k} style={{
                    padding: "3px 9px", borderRadius: 6,
                    background: "var(--bg-page)", border: "1px solid var(--border)",
                    fontSize: 11,
                  }}>
                    <span style={{ color: "var(--text-muted)", marginRight: 4 }}>{k}:</span>
                    <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>
                      {String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Technical metadata */}
          <div style={{ display: "flex", gap: 14, fontSize: 11, color: "var(--text-muted)" }}>
            <span>
              Session:{" "}
              <code style={{ fontSize: 10 }}>{msg.session_id?.slice(0, 12)}…</code>
            </span>
            <span>Role: <strong>{msg.role}</strong></span>
            <span>Type: <strong>{msg.message_type}</strong></span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ProactiveNotifications() {
  const navigate = useNavigate();
  const [sp, setSP] = useSearchParams();

  const [activeTab, setActiveTab] = useState("traces");

  // Traces tab
  const [traceList, setTraceList] = useState([]);
  const [traceLoading, setTraceLoading] = useState(true);
  const [traceError, setTraceError] = useState("");
  const [sinceHours, setSinceHours] = useState(24);
  const [statusFilter, setStatusFilter] = useState("all");

  // Messages tab
  const [customerId, setCustomerId] = useState(sp.get("customer") || "");
  const [custInput, setCustInput] = useState(sp.get("customer") || "");
  const [messages, setMessages] = useState([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState("");

  // ── Load proactive traces ─────────────────────────────────────────────────

  const loadTraces = useCallback(async () => {
    setTraceLoading(true); setTraceError("");
    try {
      const res = await tracesApi.list({
        since_hours: sinceHours,
        limit: 200,
        status: statusFilter !== "all" ? statusFilter : undefined,
      });
      // Filter client-side: proactive traces have the [PROACTIVE prefix
      const proactive = (res.traces || []).filter(t =>
        (t.user_message || "").startsWith("[PROACTIVE")
      );
      setTraceList(proactive);
    } catch (err) {
      setTraceError(err.message);
    } finally {
      setTraceLoading(false);
    }
  }, [sinceHours, statusFilter]);

  useEffect(() => {
    if (activeTab === "traces") loadTraces();
  }, [loadTraces, activeTab]);

  // ── Load messages for a customer ─────────────────────────────────────────

  const loadMessages = useCallback(async () => {
    if (!customerId) return;
    setMsgLoading(true); setMsgError("");
    try {
      setMessages(fetchProactiveMessages.fetch(customerId) || []);
    } catch (err) {
      setMsgError(err.message);
    } finally {
      setMsgLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    if (activeTab === "messages" && customerId) loadMessages();
  }, [customerId, activeTab, loadMessages]);

  const handleCustSearch = (e) => {
    e.preventDefault();
    const id = custInput.trim();
    if (!id) return;
    setCustomerId(id);
    setSP({ customer: id }, { replace: true });
  };

  // ── Tab style ─────────────────────────────────────────────────────────────

  const tabStyle = (tab) => ({
    padding: "8px 16px", fontSize: 13,
    fontWeight: activeTab === tab ? 600 : 400,
    color: activeTab === tab ? "var(--c-primary)" : "var(--text-secondary)",
    background: "none", border: "none",
    borderBottom: activeTab === tab
      ? "2px solid var(--c-primary)" : "2px solid transparent",
    cursor: "pointer", transition: "all 0.15s",
  });

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Page header */}
      <div className="page-header">
        <div>
          <div className="page-title">Proactive triggers</div>
          <div className="page-desc">
            Admin view — agent-initiated enrichment workflows
          </div>
        </div>
        <button className="btn btn-secondary"
          onClick={activeTab === "traces" ? loadTraces : loadMessages}>
          <IcRefresh size={14} /> Refresh
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
        <button style={tabStyle("traces")} onClick={() => setActiveTab("traces")}>
          Execution traces
          {traceList.length > 0 && (
            <span style={{
              marginLeft: 5, padding: "1px 5px", borderRadius: 99,
              fontSize: 10, fontWeight: 600,
              background: "var(--c-primary-light)", color: "var(--c-primary-text)",
            }}>
              {traceList.length}
            </span>
          )}
        </button>
        <button style={tabStyle("messages")} onClick={() => setActiveTab("messages")}>
          Customer messages
        </button>
      </div>

      {/* ── Traces tab ──────────────────────────────────────────────────────── */}
      {activeTab === "traces" && (
        <>
          {traceError && (
            <Alert type="error" onClose={() => setTraceError("")}>{traceError}</Alert>
          )}

          {/* Filters */}
          <div className="card">
            <div className="card-body" style={{
              padding: "12px 16px", display: "flex",
              gap: 16, flexWrap: "wrap", alignItems: "center",
            }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Status:</span>
                <div className="filter-chips">
                  {["all", "completed", "failed", "running"].map(s => (
                    <span key={s}
                      className={`chip ${statusFilter === s ? "selected" : ""}`}
                      onClick={() => setStatusFilter(s)}>
                      {s === "all" ? "All" : s}
                    </span>
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Window:</span>
                <div className="filter-chips">
                  {WINDOW_OPTS.map(o => (
                    <span key={o.value}
                      className={`chip ${sinceHours === o.value ? "selected" : ""}`}
                      onClick={() => setSinceHours(o.value)}>
                      {o.label}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Trace table */}
          <div className="card">
            {traceLoading ? (
              <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
                <Spinner large />
              </div>
            ) : traceList.length === 0 ? (
              <EmptyState
                icon="⚡"
                title="No proactive traces found"
                desc="No proactive triggers in the selected time window." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>Status</th>
                      <th>Steps</th>
                      <th>Latency</th>
                      <th>Triggered</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {traceList.map(t => (
                      <TraceRow
                        key={t.id}
                        trace={t}
                        onClick={() => navigate(`/traces/${t.id}`)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Messages tab ────────────────────────────────────────────────────── */}
      {activeTab === "messages" && (
        <>
          {msgError && (
            <Alert type="error" onClose={() => setMsgError("")}>{msgError}</Alert>
          )}

          {/* Customer search */}
          <div className="card">
            <div className="card-body" style={{ padding: "14px 18px" }}>
              <form onSubmit={handleCustSearch}
                style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <input
                  className="form-control"
                  value={custInput}
                  onChange={e => setCustInput(e.target.value)}
                  placeholder="Customer ID (e.g. CUST-1001)"
                  style={{ maxWidth: 360 }} />
                <button type="submit" className="btn btn-primary"
                  disabled={!custInput.trim()}>
                  <IcSearch size={14} /> Load messages
                </button>
              </form>
            </div>
          </div>

          {!customerId ? (
            <EmptyState
              icon="🔔"
              title="Enter a customer ID"
              desc="View all proactive system messages delivered to a customer." />
          ) : msgLoading ? (
            <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
              <Spinner large />
            </div>
          ) : messages.length === 0 ? (
            <EmptyState
              icon="📭"
              title="No proactive messages"
              desc={`No proactive_trigger messages found for ${customerId}.`} />
          ) : (
            <>
              {/* Context note about role */}
              <div style={{
                padding: "8px 12px", borderRadius: "var(--radius-sm)",
                background: "#f0f9ff", border: "1px solid #bae6fd",
                fontSize: 12, color: "#0369a1",
              }}>
                All messages below have <strong>role: "system"</strong> and{" "}
                <strong>message_type: "proactive_trigger"</strong>.
                Customer portal should render these as notification cards
                (not as chat bubbles).
              </div>

              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                {messages.length} proactive message{messages.length !== 1 ? "s" : ""}{" "}
                for {customerId}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {messages.map(m => <MessageCard key={m.id} msg={m} />)}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
