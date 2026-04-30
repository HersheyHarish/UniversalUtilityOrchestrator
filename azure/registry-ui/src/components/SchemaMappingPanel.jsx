import React, { useState } from "react";

// ── Helpers ───────────────────────────────────────────────────────────────────

function ConfidenceBar({ confidence }) {
  const pct   = Math.round((confidence ?? 1) * 100);
  const color = pct >= 80 ? "#22c55e" : pct >= 50 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: 4, background: "var(--border)", borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: "100%",
          background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 10, color, minWidth: 28, textAlign: "right" }}>
        {pct}%
      </span>
    </div>
  );
}

function FieldDecisionRow({ decision }) {
  const included  = decision.included;
  const inferred  = decision.inferred;
  const dotColor  = included
    ? (inferred ? "#f59e0b" : "#22c55e")
    : "#94a3b8";

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10,
      padding: "8px 10px",
      borderRadius: "var(--radius-sm)",
      background: included ? "#f0fdf4" : "#f8fafc",
      border: `1px solid ${included ? "#bbf7d0" : "var(--border)"}`,
      marginBottom: 4,
    }}>
      {/* Status dot */}
      <span style={{
        width: 8, height: 8, borderRadius: "50%",
        background: dotColor, flexShrink: 0, marginTop: 3,
      }} />

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Field name + badges */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 3 }}>
          <code style={{ fontSize: 12, fontWeight: 600,
            color: included ? "#166534" : "var(--text-muted)" }}>
            {decision.field_name}
          </code>

          {included && inferred && (
            <span style={{ fontSize: 10, fontWeight: 600,
              background: "#fef3c7", color: "#92400e",
              padding: "1px 6px", borderRadius: 99 }}>
              inferred
            </span>
          )}

          {!included && (
            <span style={{ fontSize: 10, fontWeight: 600,
              background: "#f1f5f9", color: "#64748b",
              padding: "1px 6px", borderRadius: 99 }}>
              skipped
            </span>
          )}
        </div>

        {/* Reason */}
        {decision.reason && (
          <div style={{ fontSize: 11, color: "var(--text-muted)",
            lineHeight: 1.4, marginBottom: included ? 5 : 0 }}>
            {decision.reason}
          </div>
        )}

        {/* Confidence bar (only when included) */}
        {included && decision.confidence != null && decision.confidence < 1 && (
          <ConfidenceBar confidence={decision.confidence} />
        )}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function SchemaMappingPanel({ step }) {
  const [expanded, setExpanded] = useState(true);

  const mr = step?.mapping_result;
  if (!mr && step?.schema_mode !== "schema_driven") return null;
  if (!mr) return null;

  const included  = mr.fields_included || [];
  const skipped   = mr.fields_skipped  || [];
  const decisions = mr.decisions       || [];
  const warnings  = mr.warnings        || [];
  const errors    = mr.errors          || [];

  const hasIssues = warnings.length > 0 || errors.length > 0 || mr.retry_count > 0;

  return (
    <div style={{ marginTop: 16 }}>
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 8,
          padding: "8px 10px", borderRadius: "var(--radius-sm)",
          background: "var(--bg-page)", border: "1px solid var(--border)",
          cursor: "pointer", marginBottom: expanded ? 8 : 0,
          transition: "background 0.15s",
        }}
      >
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {expanded ? "▼" : "▶"}
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, flex: 1, textAlign: "left" }}>
          🧠 Schema mapping
        </span>

        {/* Summary badges */}
        <div style={{ display: "flex", gap: 6 }}>
          {included.length > 0 && (
            <span style={{ fontSize: 10, fontWeight: 600,
              background: "#dcfce7", color: "#15803d",
              padding: "1px 7px", borderRadius: 99 }}>
              {included.length} included
            </span>
          )}
          {skipped.length > 0 && (
            <span style={{ fontSize: 10, fontWeight: 600,
              background: "#f1f5f9", color: "#64748b",
              padding: "1px 7px", borderRadius: 99 }}>
              {skipped.length} skipped
            </span>
          )}
          {hasIssues && (
            <span style={{ fontSize: 10, fontWeight: 600,
              background: "#fef3c7", color: "#92400e",
              padding: "1px 7px", borderRadius: 99 }}>
              ⚠ issues
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>

          {/* Metadata row */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap",
            padding: "8px 10px", borderRadius: "var(--radius-sm)",
            background: "var(--bg-page)", border: "1px solid var(--border)",
            fontSize: 11 }}>
            {[
              { label: "Mapping time",  value: mr.mapping_latency_ms != null ? `${mr.mapping_latency_ms}ms` : "—" },
              { label: "LLM tokens",    value: mr.llm_tokens_used || "0" },
              { label: "Retries",       value: mr.retry_count || "0" },
              { label: "Strict mode",   value: step.invocation_config?.request_schema?.strict !== false ? "on" : "off" },
            ].map(({ label, value }) => (
              <div key={label}>
                <div style={{ color: "var(--text-muted)", marginBottom: 1 }}>{label}</div>
                <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{value}</div>
              </div>
            ))}
          </div>

          {/* Errors */}
          {errors.length > 0 && (
            <div style={{ padding: "8px 10px", borderRadius: "var(--radius-sm)",
              background: "#fee2e2", border: "1px solid #fca5a5" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#991b1b", marginBottom: 4 }}>
                Errors
              </div>
              {errors.map((e, i) => (
                <div key={i} style={{ fontSize: 11, color: "#991b1b",
                  fontFamily: "monospace", lineHeight: 1.5 }}>
                  {e}
                </div>
              ))}
            </div>
          )}

          {/* Warnings */}
          {warnings.length > 0 && (
            <div style={{ padding: "8px 10px", borderRadius: "var(--radius-sm)",
              background: "#fef3c7", border: "1px solid #fde68a" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#92400e", marginBottom: 4 }}>
                Warnings ({warnings.length})
              </div>
              {warnings.map((w, i) => (
                <div key={i} style={{ fontSize: 11, color: "#92400e", lineHeight: 1.5 }}>
                  • {w}
                </div>
              ))}
            </div>
          )}

          {/* Per-field decisions */}
          {decisions.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600,
                color: "var(--text-muted)", textTransform: "uppercase",
                letterSpacing: ".06em", marginBottom: 6 }}>
                Field decisions
              </div>
              {decisions.map((d, i) => (
                <FieldDecisionRow key={i} decision={d} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
