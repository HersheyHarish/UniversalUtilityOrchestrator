import React, { useState } from "react";
import SchemaMappingPanel from "./SchemaMappingPanel.jsx";

const STATUS_COLORS = {
  completed: { bg: "#dcfce7", color: "#15803d" },
  failed:    { bg: "#fee2e2", color: "#991b1b" },
  running:   { bg: "#e0e7ff", color: "#3730a3" },
  skipped:   { bg: "#f1f5f9", color: "#64748b" },
};

const SCHEMA_MODE_STYLE = {
  schema_driven: { bg: "#ede9fe", color: "#5b21b6", icon: "🧠", label: "Schema-driven" },
  template:      { bg: "#e0f2fe", color: "#0369a1", icon: "📝", label: "Template"       },
  default:       { bg: "#f1f5f9", color: "#334155", icon: "⚙",  label: "Default"        },
};

function msLabel(ms) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

function JSONViewer({ data, label }) {
  const [collapsed, setCollapsed] = useState(false);
  const [copied,    setCopied]    = useState(false);
  if (data === null || data === undefined) return null;
  const text      = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  const lineCount = (text.match(/\n/g) || []).length + 1;
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); } catch (_) {}
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center",
        justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
          textTransform: "uppercase", letterSpacing: ".06em" }}>
          {label}
          <span style={{ marginLeft: 8, fontWeight: 400, textTransform: "none" }}>
            ({lineCount} lines)
          </span>
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="btn btn-ghost btn-sm" style={{ fontSize: 11, padding: "2px 8px" }}
            onClick={copy}>
            {copied ? "✓ copied" : "⎘ copy"}
          </button>
          <button className="btn btn-ghost btn-sm" style={{ fontSize: 11, padding: "2px 8px" }}
            onClick={() => setCollapsed(c => !c)}>
            {collapsed ? "▶ expand" : "▼ collapse"}
          </button>
        </div>
      </div>
      {!collapsed && (
        <pre style={{
          background: "#0f172a", color: "#e2e8f0",
          padding: "12px 14px", borderRadius: 8,
          fontSize: 11, lineHeight: 1.6, overflowX: "auto",
          maxHeight: 280, overflowY: "auto",
          fontFamily: "'SF Mono', 'Fira Code', monospace",
          margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all",
        }}>
          {text}
        </pre>
      )}
    </div>
  );
}

function MetaRow({ label, value, monospace }) {
  return (
    <div style={{ display: "flex", gap: 8, fontSize: 12 }}>
      <span style={{ color: "var(--text-muted)", minWidth: 110,
        flexShrink: 0, fontSize: 11 }}>{label}</span>
      <span style={{
        color: "var(--text-primary)",
        fontFamily: monospace ? "'SF Mono', monospace" : undefined,
        fontSize: monospace ? 11 : 13, wordBreak: "break-all",
      }}>
        {value}
      </span>
    </div>
  );
}

export default function StepInspector({ step, onClose }) {
  if (!step) {
    return (
      <div style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
        <div style={{ fontSize: 28, marginBottom: 12 }}>👆</div>
        <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 6 }}>
          Click a node or timeline bar
        </div>
        <div style={{ fontSize: 13 }}>to inspect inputs, outputs, and mapping decisions</div>
      </div>
    );
  }

  const sc         = STATUS_COLORS[step.status] || STATUS_COLORS.skipped;
  const modeStyle  = SCHEMA_MODE_STYLE[step.schema_mode] || SCHEMA_MODE_STYLE.default;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 20,
      height: "100%", overflowY: "auto" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start",
        justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <span style={{ background: sc.bg, color: sc.color,
              padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 500 }}>
              {step.status}
            </span>
            <span style={{ background: modeStyle.bg, color: modeStyle.color,
              padding: "2px 10px", borderRadius: 99, fontSize: 11, fontWeight: 500 }}>
              {modeStyle.icon} {modeStyle.label}
            </span>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Step {step.step_id}
            </span>
          </div>
          <div style={{ fontSize: 17, fontWeight: 700 }}>{step.agent_name}</div>
        </div>
        {onClose && (
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}
            style={{ flexShrink: 0 }}>×</button>
        )}
      </div>

      {/* Metadata */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8,
        padding: 12, borderRadius: 8, background: "var(--bg-page)",
        border: "1px solid var(--border)" }}>
        <MetaRow label="Agent URL"    value={step.agent_url || "—"} monospace />
        <MetaRow label="Auth type"    value={step.auth_type || "none"} />
        <MetaRow label="Latency"      value={msLabel(step.latency_ms)} />
        <MetaRow label="Started"
          value={step.started_at?.slice(0,19).replace("T"," ") + " UTC" || "—"} />
        <MetaRow label="Completed"
          value={step.completed_at?.slice(0,19).replace("T"," ") + " UTC" || "—"} />
        {(step.depends_on || []).length > 0 && (
          <MetaRow label="Depends on"
            value={`Steps: ${step.depends_on.join(", ")}`} />
        )}
      </div>

      {/* Task */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
          textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>
          Task assigned by planner
        </div>
        <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.6,
          padding: "10px 12px", background: "var(--bg-page)",
          borderRadius: 8, border: "1px solid var(--border)" }}>
          {step.task || "—"}
        </div>
      </div>

      {/* Schema mapping decisions — shown only when schema_driven */}
      {step.schema_mode === "schema_driven" && (
        <SchemaMappingPanel step={step} />
      )}

      {/* Error */}
      {step.error && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#991b1b",
            textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>
            Error
          </div>
          <div style={{ padding: "10px 12px", borderRadius: 8,
            background: "#fee2e2", color: "#991b1b",
            fontSize: 12, lineHeight: 1.6, fontFamily: "monospace",
            whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {step.error}
          </div>
        </div>
      )}

      {/* Input payload */}
      <JSONViewer data={step.input_payload} label="Input payload (sent to agent)" />

      {/* Output */}
      {step.output_raw && (
        <JSONViewer data={step.output_raw} label="Raw output from agent" />
      )}

      {step.result && step.result !== step.output_raw && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>
            Extracted result
          </div>
          <div style={{ padding: "10px 12px", borderRadius: 8,
            background: "#f0fdf4", border: "1px solid #bbf7d0",
            fontSize: 13, lineHeight: 1.6, color: "#166534" }}>
            {step.result}
          </div>
        </div>
      )}
    </div>
  );
}
