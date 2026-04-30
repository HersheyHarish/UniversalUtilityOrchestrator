import React, { useMemo, useState } from "react";

function truncate(str, n = 80) {
  if (!str) return "";
  const s = typeof str === "string" ? str : JSON.stringify(str);
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function extractFields(payload) {
  if (!payload || typeof payload !== "object") return {};
  const fields = {};
  Object.entries(payload).forEach(([k, v]) => {
    fields[k] = truncate(v, 60);
  });
  return fields;
}

function extractContextFields(payload) {
  // The context dict passed to later steps contains step_N_output keys
  const ctx = payload?.context || {};
  const fields = {};
  Object.entries(ctx).forEach(([k, v]) => {
    if (k.startsWith("step_") && k.endsWith("_output")) {
      const stepNum = k.replace("step_", "").replace("_output", "");
      fields[`Step ${stepNum} output`] = truncate(v, 60);
    } else if (k !== "planner_note") {
      fields[k] = truncate(v, 60);
    }
  });
  return fields;
}

function StepBox({ step, highlight, onClick, selected }) {
  const hasError = step.status === "failed";
  const border   = selected ? "#6366f1" : hasError ? "#dc2626" : "var(--border)";
  const bg       = selected ? "#f0f4ff" : hasError ? "#fff5f5" : "var(--bg-card)";

  const inputFields  = extractFields(step.input_payload);
  const outputPreview = step.result ? truncate(step.result, 80) : null;

  return (
    <div onClick={() => onClick(step)}
      style={{ cursor: "pointer", borderRadius: 10, border: `1px solid ${border}`,
        background: bg, transition: "all 0.15s", padding: 0, overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "10px 14px",
        borderBottom: "1px solid var(--border)",
        background: selected ? "#e0e7ff" : "var(--bg-page)",
        display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <span style={{ fontSize: 11, color: "var(--text-muted)", marginRight: 6 }}>
            Step {step.step_id}
          </span>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{step.agent_name}</span>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 500, padding: "2px 8px", borderRadius: 99,
          background: step.status === "completed" ? "#dcfce7" :
                      step.status === "failed"    ? "#fee2e2" : "#f1f5f9",
          color:      step.status === "completed" ? "#15803d" :
                      step.status === "failed"    ? "#991b1b" : "#64748b",
        }}>
          {step.status}
        </span>
      </div>

      {/* Input fields */}
      <div style={{ padding: "10px 14px" }}>
        {Object.keys(inputFields).length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)",
              textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>
              Input fields
            </div>
            {Object.entries(inputFields).slice(0, 4).map(([k, v]) => (
              <div key={k} style={{ display: "flex", gap: 6, marginBottom: 3 }}>
                <span style={{ fontSize: 11, color: "var(--c-primary)",
                  fontFamily: "monospace", minWidth: 70, flexShrink: 0 }}>{k}</span>
                <span style={{ fontSize: 11, color: "var(--text-secondary)",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {v}
                </span>
              </div>
            ))}
          </div>
        )}

        {outputPreview && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)",
              textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>
              Output
            </div>
            <div style={{ fontSize: 11, color: "#166534", background: "#f0fdf4",
              padding: "5px 8px", borderRadius: 6, lineHeight: 1.5,
              overflow: "hidden", textOverflow: "ellipsis",
              display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
              {outputPreview}
            </div>
          </div>
        )}

        {step.status === "failed" && step.error && (
          <div style={{ fontSize: 11, color: "#991b1b", background: "#fee2e2",
            padding: "5px 8px", borderRadius: 6, marginTop: 4 }}>
            ✕ {step.error.slice(0, 80)}
          </div>
        )}
      </div>
    </div>
  );
}

function ContextFlow({ fromStep, toStep }) {
  const ctx = extractContextFields(toStep.input_payload);
  const keys = Object.keys(ctx);
  if (keys.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
      padding: "4px 0", gap: 4, minWidth: 120 }}>
      <div style={{ width: 1, height: 12, background: "#6366f1", opacity: 0.5 }} />
      <div style={{ padding: "4px 10px", borderRadius: 99, fontSize: 10,
        background: "#e0e7ff", color: "#3730a3", fontWeight: 600, textAlign: "center",
        maxWidth: 110 }}>
        {keys.length} field{keys.length !== 1 ? "s" : ""} passed
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", textAlign: "center", maxWidth: 110 }}>
        {keys.slice(0, 2).join(", ")}{keys.length > 2 ? ` +${keys.length-2}` : ""}
      </div>
      <div style={{ width: 1, height: 12, background: "#6366f1", opacity: 0.5 }} />
      {/* Arrow head */}
      <div style={{ width: 0, height: 0,
        borderLeft: "5px solid transparent",
        borderRight: "5px solid transparent",
        borderTop: "6px solid #6366f1", opacity: 0.5,
        marginTop: -4 }} />
    </div>
  );
}

export default function DataFlowView({ steps, onSelectStep, selectedStepId }) {
  if (!steps || steps.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 14 }}>
        No steps to display
      </div>
    );
  }

  // Sort by step_id
  const sorted = [...steps].sort((a, b) => a.step_id - b.step_id);

  // Build dependency map: which step's output feeds which step
  const stepById = {};
  sorted.forEach(s => { stepById[s.step_id] = s; });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
        Showing {sorted.length} steps · arrows show context fields passed between agents
      </div>

      {sorted.map((step, i) => {
        const prevStep = i > 0 ? sorted[i - 1] : null;
        // Does this step receive context from any previous step?
        const deps = (step.depends_on || [])
          .map(id => stepById[id])
          .filter(Boolean);

        return (
          <div key={step.step_id}>
            {/* Show context flow connector if there are dependencies */}
            {deps.length > 0 && (
              <div style={{ paddingLeft: 20 }}>
                {deps.map(dep => (
                  <ContextFlow key={dep.step_id} fromStep={dep} toStep={step} />
                ))}
              </div>
            )}

            {/* Step box */}
            <StepBox
              step={step}
              selected={selectedStepId === step.step_id}
              onClick={onSelectStep}
            />
          </div>
        );
      })}

      {/* Final output */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start",
        paddingLeft: 20, marginTop: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div style={{ width: 1, height: 16, background: "#1d9e75", opacity: 0.6 }} />
          <div style={{ fontSize: 11, fontWeight: 600, padding: "4px 10px",
            background: "#e1f5ee", color: "#0f6e56", borderRadius: 99 }}>
            Synthesizer → final response
          </div>
        </div>
      </div>
    </div>
  );
}
