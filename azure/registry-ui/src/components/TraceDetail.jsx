import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { traces } from "../api/client.js";
import { Spinner, Alert } from "./Primitives.jsx";
import { IcChevronRight, IcRefresh } from "./Icons.jsx";
import DAGVisualization  from "./DAGVisualization.jsx";
import TimelineView      from "./TimelineView.jsx";
import StepInspector     from "./StepInspector.jsx";
import DataFlowView      from "./DataFlowView.jsx";

const STATUS_STYLE = {
  completed: { bg: "#dcfce7", color: "#15803d" },
  failed:    { bg: "#fee2e2", color: "#991b1b" },
  running:   { bg: "#e0e7ff", color: "#3730a3" },
};

const VIEWS = [
  { id: "dag",      label: "DAG" },
  { id: "timeline", label: "Timeline" },
  { id: "dataflow", label: "Data flow" },
];

function msLabel(ms) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

export default function TraceDetail() {
  const { id }    = useParams();
  const navigate  = useNavigate();

  const [trace,       setTrace]       = useState(null);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState("");
  const [activeView,  setActiveView]  = useState("dag");
  const [selectedStep, setSelectedStep] = useState(null);

  const load = async () => {
    setLoading(true); setError("");
    try {
      const doc = await traces.get(id);
      setTrace(doc);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  const handleSelectStep = (step) => {
    setSelectedStep(prev => prev?.step_id === step.step_id ? null : step);
  };

  if (loading) return (
    <div style={{ display: "flex", justifyContent: "center", padding: 60 }}>
      <Spinner large />
    </div>
  );

  if (!trace) return (
    <div className="card"><div className="card-body">
      <p className="text-muted">Trace not found.</p>
      <button className="btn btn-secondary" style={{ marginTop: 12 }}
        onClick={() => navigate("/traces")}>← Back to traces</button>
    </div></div>
  );

  const sc       = STATUS_STYLE[trace.status] || { bg: "#f1f5f9", color: "#64748b" };
  const steps    = trace.steps || [];
  const failed   = steps.filter(s => s.status === "failed");
  const slowStep = steps.reduce((a, b) =>
    (b.latency_ms || 0) > (a?.latency_ms || 0) ? b : a, null);

  const tabStyle = (view) => ({
    padding: "8px 16px", fontSize: 13, fontWeight: activeView === view ? 600 : 400,
    color: activeView === view ? "var(--c-primary)" : "var(--text-secondary)",
    background: "none", border: "none",
    borderBottom: activeView === view ? "2px solid var(--c-primary)" : "2px solid transparent",
    cursor: "pointer", transition: "all 0.15s",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 6,
        fontSize: 13, color: "var(--text-muted)" }}>
        <button className="btn btn-ghost btn-sm" style={{ padding: "4px 8px" }}
          onClick={() => navigate("/traces")}>Traces</button>
        <IcChevronRight size={12} />
        <span className="font-mono" style={{ fontSize: 12 }}>{id.slice(0, 16)}…</span>
      </div>

      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {/* Summary header */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <span style={{ background: sc.bg, color: sc.color, padding: "2px 10px",
                borderRadius: 99, fontSize: 12, fontWeight: 500 }}>
                {trace.status}
              </span>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {trace.started_at ? new Date(trace.started_at).toLocaleString() : ""}
              </span>
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>
              {trace.user_message || "(no message)"}
            </div>
            {trace.plan?.user_intent && (
              <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                Intent: {trace.plan.user_intent}
              </div>
            )}
          </div>
          <button className="btn btn-secondary btn-sm" onClick={load}>
            <IcRefresh size={13} /> Refresh
          </button>
        </div>

        <div className="card-body">
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            {/* KPIs */}
            {[
              { label: "Total latency",    value: msLabel(trace.total_latency_ms) },
              { label: "Agents invoked",   value: trace.agents_invoked || 0 },
              { label: "Steps",            value: steps.length },
              { label: "Customer ID",      value: trace.customer_id || "—" },
              { label: "Session ID",       value: id.slice(0, 12) + "…" },
            ].map(({ label, value }) => (
              <div key={label}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 3 }}>
                  {label}
                </div>
                <div style={{ fontSize: 15, fontWeight: 600 }}>{value}</div>
              </div>
            ))}
          </div>

          {/* Alerts */}
          {failed.length > 0 && (
            <div style={{ marginTop: 14, padding: "8px 12px", borderRadius: 8,
              background: "#fee2e2", color: "#991b1b", fontSize: 13,
              display: "flex", gap: 8 }}>
              <span>⚠</span>
              <span>
                {failed.length} step{failed.length > 1 ? "s" : ""} failed:{" "}
                {failed.map(s => s.agent_name).join(", ")}
              </span>
            </div>
          )}

          {slowStep && slowStep.latency_ms > 3000 && (
            <div style={{ marginTop: 8, padding: "8px 12px", borderRadius: 8,
              background: "#fef3c7", color: "#92400e", fontSize: 13,
              display: "flex", gap: 8 }}>
              <span>🐢</span>
              <span>
                Bottleneck: <strong>{slowStep.agent_name}</strong> took {msLabel(slowStep.latency_ms)}
              </span>
            </div>
          )}

          {trace.plan?.synthesis_instruction && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>
                Synthesis instruction
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", fontStyle: "italic" }}>
                {trace.plan.synthesis_instruction}
              </div>
            </div>
          )}

          {trace.final_response && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>
                Final response
              </div>
              <div style={{ fontSize: 13, lineHeight: 1.6, color: "var(--text-primary)",
                padding: "10px 12px", borderRadius: 8, background: "#f0fdf4",
                border: "1px solid #bbf7d0" }}>
                {trace.final_response}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main visualization area + inspector */}
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>

        {/* Left: visualization panel */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="card" style={{ overflow: "hidden" }}>
            {/* Tab bar */}
            <div style={{ display: "flex", borderBottom: "1px solid var(--border)",
              padding: "0 20px", gap: 0 }}>
              {VIEWS.map(v => (
                <button key={v.id} style={tabStyle(v.id)}
                  onClick={() => setActiveView(v.id)}>
                  {v.label}
                </button>
              ))}
            </div>

            <div className="card-body" style={{ padding: 16, minHeight: 300 }}>
              {activeView === "dag" && (
                <DAGVisualization
                  steps={steps}
                  selectedStepId={selectedStep?.step_id}
                  onSelectStep={handleSelectStep}
                />
              )}
              {activeView === "timeline" && (
                <TimelineView
                  steps={steps}
                  traceStartedAt={trace.started_at}
                  selectedStepId={selectedStep?.step_id}
                  onSelectStep={handleSelectStep}
                />
              )}
              {activeView === "dataflow" && (
                <DataFlowView
                  steps={steps}
                  selectedStepId={selectedStep?.step_id}
                  onSelectStep={handleSelectStep}
                />
              )}
            </div>
          </div>
        </div>

        {/* Right: step inspector */}
        <div style={{ width: 360, flexShrink: 0 }}>
          <div className="card" style={{ position: "sticky", top: 20 }}>
            <div className="card-header">
              <span className="card-title">
                {selectedStep ? `Step ${selectedStep.step_id} — ${selectedStep.agent_name}` : "Step inspector"}
              </span>
              {selectedStep && (
                <button className="btn btn-ghost btn-sm"
                  onClick={() => setSelectedStep(null)}
                  style={{ fontSize: 12 }}>Clear</button>
              )}
            </div>
            <StepInspector step={selectedStep} />
          </div>
        </div>
      </div>
    </div>
  );
}
