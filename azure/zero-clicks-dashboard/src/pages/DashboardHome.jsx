import React, { useState } from "react";
import { BillingHero } from "../components/BillingHero";
import { BillExplanation } from "../components/BillExplanation";
import { UsageChart } from "../components/UsageChart";
import { BillBreakdown } from "../components/BillBreakdown";
import { CopilotChat } from "../components/CopilotChat";
import { AIInsightsFeed } from "../components/AIInsightsFeed";
import { MessageSquare } from "lucide-react";

export function DashboardHome({
  billing,
  usageData,
  insights,
  insightsLoading,
  billExplanation,
  billExplanationLoading,
  billExplanationError,
  billExplanationAgents,
  refetchBillExplanation,
  chatMessages,
  chatInput,
  setChatInput,
  chatLoading,
  sendChat,
  activeTrace,
  triggerProactiveNotification,
}) {
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const handleAskCopilot = (query) => {
    setIsDrawerOpen(true);
    sendChat(query);
  };

  const handleCtaClick = (cta) => {
    setIsDrawerOpen(true);
    let prompt = "";
    switch (cta.action) {
      case "open_copilot_context":
        prompt = `Analyze the usage spike and retrieve copilot context for session ${cta.payload.session_id}`;
        break;
      case "open_session":
        prompt = `Show me the agent output details and breakdown for session ${cta.payload.session_id}`;
        break;
      case "retry_session":
        prompt = `Retry the failed agent workflow in session ${cta.payload.session_id}`;
        break;
      case "apply_ev_schedule":
        prompt = `Apply the EV charging schedule for window ${cta.payload.window || "23:00-05:00"} to optimize my bill, referencing session ${cta.payload.session_id}`;
        break;
      default:
        prompt = `Tell me about: ${cta.label}`;
    }
    sendChat(prompt);
  };

  return (
    <div className={`dashboard-home-container ${isDrawerOpen ? "drawer-open" : ""}`}>
      {/* Page Header with Chat Toggle */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: "var(--text-primary)" }}>Account Overview</h1>
          <p style={{ color: "var(--text-tertiary)", fontSize: 13, marginTop: 4 }}>
            AI-monitored utility accounts & continuous operations.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setIsDrawerOpen((prev) => !prev)}
          style={{ gap: 8, padding: "10px 20px", borderRadius: "var(--radius-md)" }}
        >
          <MessageSquare size={16} />
          {isDrawerOpen ? "Close Assistant" : "Ask AI Copilot"}
        </button>
      </div>

      {/* Main Grid Layout */}
      <div className="dashboard-grid-layout">
        {/* Left Column: Financials & Account Analytics */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {/* Stats Summary Card */}
          <BillingHero billing={billing} />

          {/* RAG Bill Explanation directly under the stats */}
          <BillExplanation
            explanation={billExplanation}
            loading={billExplanationLoading}
            error={billExplanationError}
            agents={billExplanationAgents}
            onRetry={refetchBillExplanation}
          />

          {/* Usage Chart and Statement Breakdown side-by-side */}
          <div className="dashboard-sub-grid">
            <UsageChart usageData={usageData} />
            <BillBreakdown billing={billing} />
          </div>
        </div>

        {/* Right Column: AI Insights & Advisories Feed */}
        <div className="dashboard-right-col">
          <AIInsightsFeed
            insights={insights}
            insightsLoading={insightsLoading}
            onCtaClick={handleCtaClick}
            onAskCopilot={handleAskCopilot}
          />

          {/* Live Orchestrator Activity Run Trace Card */}
          <div className="card execution-trace-card" style={{ marginTop: 24 }}>
            <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 12, borderBottom: "1px solid var(--border-subtle)" }}>
              <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 700 }}>
                <span>🤖</span> Orchestrator Activity Trace
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {activeTrace.status === "running" ? (
                  <>
                    <span className="trace-spinner" />
                    <span style={{ fontSize: 10, color: "var(--brand-blue)", fontWeight: 700, letterSpacing: "0.05em" }}>RUNNING</span>
                  </>
                ) : activeTrace.status === "completed" ? (
                  <>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--status-success)", boxShadow: "0 0 6px var(--status-success)" }} />
                    <span style={{ fontSize: 10, color: "var(--status-success)", fontWeight: 700, letterSpacing: "0.05em" }}>IDLE</span>
                  </>
                ) : activeTrace.status === "failed" ? (
                  <>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--status-danger)", boxShadow: "0 0 6px var(--status-danger)" }} />
                    <span style={{ fontSize: 10, color: "var(--status-danger)", fontWeight: 700, letterSpacing: "0.05em" }}>FAILED</span>
                  </>
                ) : (
                  <>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--text-tertiary)" }} />
                    <span style={{ fontSize: 10, color: "var(--text-tertiary)", fontWeight: 700, letterSpacing: "0.05em" }}>STANDBY</span>
                  </>
                )}
              </div>
            </div>
            
            <div className="trace-body" style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
              {activeTrace.steps.length === 0 ? (
                <div style={{ padding: "20px 8px", textAlign: "center", color: "var(--text-tertiary)", fontSize: 12, fontStyle: "italic" }}>
                  Orchestrator standby. Run a proactive check or ask the AI Copilot to see live planning and execution layers.
                </div>
              ) : (
                activeTrace.steps.map((step, idx) => (
                  <div key={idx} className={`trace-step-item ${step.status}`} style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 12,
                    padding: "8px 12px",
                    borderRadius: "var(--radius-md)",
                    background: step.status === "running" ? "rgba(10, 132, 255, 0.04)" : "transparent",
                    border: step.status === "running" ? "1px dashed rgba(10, 132, 255, 0.25)" : "1px solid transparent",
                    transition: "all 0.2s ease"
                  }}>
                    {/* Status Dot / Icon */}
                    <div style={{ marginTop: 2, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", width: 14, height: 14 }}>
                      {step.status === "completed" ? (
                        <span style={{ color: "var(--status-success)", fontSize: 12, fontWeight: "bold" }}>✓</span>
                      ) : step.status === "running" ? (
                        <span className="trace-dot-pulse" />
                      ) : step.status === "failed" ? (
                        <span style={{ color: "var(--status-danger)", fontSize: 12, fontWeight: "bold" }}>✕</span>
                      ) : (
                        <span style={{ color: "var(--text-tertiary)", fontSize: 14 }}>○</span>
                      )}
                    </div>
                    
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span className="trace-step-stage" style={{
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: "0.07em",
                        color: step.status === "completed" ? "var(--text-tertiary)" : step.status === "running" ? "var(--brand-blue)" : "var(--text-tertiary)"
                      }}>{step.stage}</span>
                      <span className="trace-step-message" style={{
                        fontSize: 12,
                        lineHeight: 1.4,
                        color: step.status === "pending" ? "var(--text-tertiary)" : "var(--text-primary)"
                      }}>{step.message}</span>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Simulate Agent Trigger Event control panel */}
            <div className="trace-footer" style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border-subtle)" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>
                Simulate Agent Proactive Trigger
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => triggerProactiveNotification({
                    agentName: "anomaly_detection_agent",
                    eventType: "usage_anomaly_detected",
                    message: "Critical: Anomaly detected on account CUST-1001. Smart meter registered a 3.4x spike in consumption relative to the 30-day baseline.",
                    severity: "high"
                  })}
                  disabled={activeTrace.status === "running"}
                  style={{ fontSize: 11, padding: "6px 12px", display: "flex", alignItems: "center", gap: 5, borderRadius: "var(--radius-md)" }}
                >
                  📈 Anomaly Spike
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => triggerProactiveNotification({
                    agentName: "solar_performance_credit_loss_agent",
                    eventType: "solar_underperformance_alert",
                    message: "Alert: Solar generation efficiency dropped by 45% below expected clear-sky output for customer CUST-1001.",
                    severity: "medium"
                  })}
                  disabled={activeTrace.status === "running"}
                  style={{ fontSize: 11, padding: "6px 12px", display: "flex", alignItems: "center", gap: 5, borderRadius: "var(--radius-md)" }}
                >
                  ☀️ Solar Drop
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => triggerProactiveNotification({
                    agentName: "bill_shock_forecast_agent",
                    eventType: "bill_shock_warning",
                    message: "Forecast Warning: Customer CUST-1001 is projected to exceed their standard monthly billing threshold by 60% due to active consumption rates.",
                    severity: "high"
                  })}
                  disabled={activeTrace.status === "running"}
                  style={{ fontSize: 11, padding: "6px 12px", display: "flex", alignItems: "center", gap: 5, borderRadius: "var(--radius-md)" }}
                >
                  📊 Bill Shock
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Floating Copilot Drawer Panel */}
      <div className={`copilot-drawer ${isDrawerOpen ? "open" : ""}`}>
        <div className="copilot-drawer-header">
          <div className="copilot-drawer-title">
            <span style={{
              width: 24, height: 24, borderRadius: "50%",
              background: "linear-gradient(135deg, var(--brand-blue), #7C3AED)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, flexShrink: 0, color: "#fff"
            }}>✨</span>
            AI Copilot Assistant
          </div>
          <button className="copilot-drawer-close" onClick={() => setIsDrawerOpen(false)}>
            ✕
          </button>
        </div>
        <div className="copilot-drawer-body">
          <CopilotChat
            chatMessages={chatMessages}
            chatInput={chatInput}
            setChatInput={setChatInput}
            chatLoading={chatLoading}
            sendChat={sendChat}
          />
        </div>
      </div>
    </div>
  );
}

