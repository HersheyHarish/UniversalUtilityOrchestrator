import React, { useState, useEffect } from "react";
import { orchestratorApi } from "../api/orchestratorClient";
import { Bot, Mail, Sparkles, MapPin, Zap, AlertTriangle, ShieldCheck, Play, ArrowRight } from "lucide-react";
import "../styles/reactiveEmail.css";

export function ReactiveEmail() {
  const [simulationState, setSimulationState] = useState("idle"); // idle, loading, completed, failed
  const [errorMsg, setErrorMsg] = useState("");
  const [sessionInfo, setSessionInfo] = useState(null);
  const [emailDetails, setEmailDetails] = useState(null);
  const [planSteps, setPlanSteps] = useState([]);
  
  // Custom states for animating stepper stages during backend execution
  const [currentStepperIndex, setCurrentStepperIndex] = useState(0);

  useEffect(() => {
    let timer;
    if (simulationState === "loading") {
      // Simulate stepper progress every 1.5 seconds during execution
      setCurrentStepperIndex(0);
      const intervals = [1000, 2500, 4200, 5800];
      
      intervals.forEach((time, index) => {
        timer = setTimeout(() => {
          setCurrentStepperIndex(index + 1);
        }, time);
      });
    }
    return () => clearTimeout(timer);
  }, [simulationState]);

  const runSimulation = async () => {
    setSimulationState("loading");
    setErrorMsg("");
    setEmailDetails(null);
    setPlanSteps([]);
    setCurrentStepperIndex(0);
    
    try {
      // Trigger simulation for CUST-1001 (James Doe)
      const res = await orchestratorApi.simulateOutage("CUST-1001");
      
      // Fetch the actual session trace from Cosmos DB via orchestrator api
      let sessionData = null;
      try {
        sessionData = await orchestratorApi.session(res.session_id);
      } catch (sessErr) {
        console.warn("Could not fetch full session data, falling back", sessErr);
      }

      const stepsList = [];
      let mockEmail = null;

      if (sessionData && sessionData.session && sessionData.session.plan) {
        const planStepsData = sessionData.session.plan.steps || [];
        const stepResults = sessionData.step_results || [];

        planStepsData.forEach((step, idx) => {
          const result = stepResults.find(r => r.step_id === step.step_id);
          stepsList.push({
            id: `step-${step.step_id}`,
            agent: step.agent_name || "Unknown Agent",
            objective: step.task || "Analysis",
            status: result ? "completed" : "pending",
            output: result ? result.content : "",
            error: result && result.type === "step_error" ? result.content : ""
          });

          // Find email details from the email notification agent step
          if (step.agent_name === "email_notification_agent" && result) {
            if (result.metadata && result.metadata.body) {
              mockEmail = {
                recipient: result.metadata.recipient || "james.doe@example.com",
                subject: result.metadata.subject || "⚠️ NexusGas Service Alert: Outage Detected & Action Plan",
                body: result.metadata.body,
                sent_at: result.metadata.sent_at || new Date().toISOString(),
                status: "sent"
              };
            } else {
              try {
                if (typeof result.content === "string" && result.content.trim().startsWith("{")) {
                  mockEmail = JSON.parse(result.content);
                }
              } catch (e) {
                console.warn("Failed to parse email content", e);
              }
            }
          }
        });
      }

      // Fallback: parse steps from the direct simulateOutage response if stepsList is empty
      if (stepsList.length === 0) {
        const steps = res.steps_completed || res.steps || {};
        if (res.steps_completed && Array.isArray(res.steps_completed)) {
          res.steps_completed.forEach((step, idx) => {
            stepsList.push({
              id: `step-${idx}`,
              agent: step.agent || "Unknown Agent",
              objective: step.objective || "Analysis",
              status: "completed",
              output: step.output || "",
            });
          });
        } else {
          Object.entries(steps).forEach(([stepId, stepData]) => {
            stepsList.push({
              id: stepId,
              agent: stepData.agent || "Unknown Agent",
              objective: stepData.objective || "Analysis",
              status: stepData.status || "completed",
              output: stepData.output || "",
              error: stepData.error || ""
            });

            if (stepData.agent === "email_notification_agent" && stepData.output) {
              try {
                mockEmail = typeof stepData.output === "string" 
                  ? JSON.parse(stepData.output) 
                  : stepData.output;
              } catch (e) {
                console.warn("Failed to parse email stepData output", e);
              }
            }
          });
        }
      }

      // Extract agents used to find email if it's not nested
      if (!mockEmail && res.agents_used && res.agents_used.includes("email_notification_agent")) {
        // Find it in response text
        mockEmail = {
          recipient: "james.doe@example.com",
          subject: "⚠️ NexusGas Service Alert: Outage Detected & Action Plan",
          body: res.response || "Service Outage Warning.",
          sent_at: new Date().toISOString(),
          status: "sent"
        };
      }

      // Fallback email generation
      if (!mockEmail && res.response) {
        mockEmail = {
          recipient: "james.doe@example.com",
          subject: "⚠️ NexusGas Service Alert: Outage Detected & Action Plan",
          body: res.response,
          sent_at: new Date().toISOString(),
          status: "sent"
        };
      }

      setPlanSteps(stepsList);
      setEmailDetails(mockEmail);
      setSessionInfo(res);
      setSimulationState("completed");
    } catch (err) {
      console.error("Simulation failed:", err);
      setErrorMsg(err.message || "Failed to complete simulation pipeline.");
      setSimulationState("failed");
    }
  };

  return (
    <div className="reactive-email-container" style={{ maxWidth: 1200, margin: "0 auto", padding: "28px 32px" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24, flexWrap: "wrap", gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: "var(--text-primary)" }}>Reactive Alerts Dashboard</h1>
          <p style={{ color: "var(--text-tertiary)", fontSize: 13, marginTop: 4 }}>
            Simulate and trace automated email alerts triggered by outage events in real time.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          style={{ gap: 8, padding: "12px 24px", borderRadius: "var(--radius-md)" }}
          onClick={runSimulation}
          disabled={simulationState === "loading"}
        >
          {simulationState === "loading" ? (
            <>
              <span className="topbar-proactive-spinner" />
              Executing Outage Workflow...
            </>
          ) : (
            <>
              <Play size={16} />
              Simulate Outage (CUST-1001)
            </>
          )}
        </button>
      </div>

      {simulationState === "failed" && (
        <div style={{ padding: "14px 20px", background: "var(--status-danger-bg)", color: "var(--status-danger)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "var(--radius-md)", marginBottom: 20, display: "flex", gap: 10, alignItems: "center", fontSize: 13 }}>
          <AlertTriangle size={16} />
          <span><strong>Simulation Failed:</strong> {errorMsg}</span>
        </div>
      )}

      {/* Grid Layout */}
      <div className="reactive-email-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        
        {/* Left Column: Map and Stepper Trace */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          
          {/* Map Card */}
          <div className="card" style={{ padding: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div className="card-title">
                <MapPin size={16} style={{ color: "var(--brand-orange)" }} />
                Austin Grid Outage Monitor
              </div>
              <span className="pill info" style={{ padding: "2px 8px" }}>Zone 78712</span>
            </div>

            <div className="map-view-wrapper" style={{ border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", overflow: "hidden", background: "#0f172a" }}>
              <svg viewBox="0 0 500 320" style={{ width: "100%", height: "auto" }}>
                {/* City grid layout */}
                <path d="M 0,40 L 500,40 M 0,80 L 500,80 M 0,120 L 500,120 M 0,160 L 500,160 M 0,200 L 500,200 M 0,240 L 500,240 M 0,280 L 500,280" stroke="rgba(255,255,255,0.03)" strokeWidth="1" />
                <path d="M 50,0 L 50,320 M 100,0 L 100,320 M 150,0 L 150,320 M 200,0 L 200,320 M 250,0 L 250,320 M 300,0 L 300,320 M 350,0 L 350,320 M 400,0 L 400,320 M 450,0 L 450,320" stroke="rgba(255,255,255,0.03)" strokeWidth="1" />
                
                {/* Highway paths */}
                <path d="M 60,0 Q 180,140 260,320" stroke="rgba(255,255,255,0.05)" strokeWidth="3" fill="none" />
                <path d="M 0,150 L 500,150" stroke="rgba(255,255,255,0.05)" strokeWidth="3" fill="none" />

                {/* Map labels */}
                <text x="360" y="30" fill="rgba(255,255,255,0.15)" fontSize="10" fontWeight="bold" fontFamily="sans-serif">N. AUSTIN SUBGRID</text>
                
                {/* Outage State Display */}
                {simulationState === "loading" || simulationState === "completed" ? (
                  <>
                    {/* Glowing outer outage ring */}
                    <circle cx="260" cy="160" r="80" className="outage-overlay-pulse" />
                    <circle cx="260" cy="160" r="80" fill="url(#outageGrad)" opacity="0.3" />

                    {/* Substation Center */}
                    <circle cx="260" cy="160" r="6" fill="var(--status-danger)" />
                    <text x="272" y="164" fill="var(--status-danger)" fontSize="9" fontWeight="bold" fontFamily="sans-serif">Substation 78712 (offline)</text>

                    {/* Affected Customer Location */}
                    <g transform="translate(210, 130)">
                      <circle cx="0" cy="0" r="8" className="customer-node-pulse" />
                      <circle cx="0" cy="0" r="4" fill="var(--brand-blue)" />
                      <text x="10" y="3" fill="#fff" fontSize="9" fontWeight="bold" fontFamily="sans-serif">CUST-1001</text>
                    </g>
                  </>
                ) : (
                  <>
                    {/* Normal State */}
                    <g transform="translate(210, 130)">
                      <circle cx="0" cy="0" r="4" fill="var(--status-success)" />
                      <text x="10" y="3" fill="rgba(255,255,255,0.4)" fontSize="9" fontFamily="sans-serif">CUST-1001 (online)</text>
                    </g>
                    <text x="180" y="165" fill="rgba(255,255,255,0.2)" fontSize="12" fontFamily="sans-serif">Grid operates normally</text>
                  </>
                )}

                <defs>
                  <radialGradient id="outageGrad" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity="0.8" />
                    <stop offset="70%" stopColor="#ef4444" stopOpacity="0.2" />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity="0" />
                  </radialGradient>
                </defs>
              </svg>
            </div>
          </div>

          {/* Stepper Timeline card */}
          <div className="card" style={{ padding: 20 }}>
            <div className="card-header" style={{ marginBottom: 16 }}>
              <div className="card-title">
                <Bot size={16} style={{ color: "var(--brand-blue)" }} />
                Orchestration Pipeline Trace
              </div>
            </div>

            {simulationState === "idle" && (
              <div style={{ textAlign: "center", padding: "20px 0", color: "var(--text-tertiary)", fontSize: 13 }}>
                Click the simulation button to execute the reactive agent workflow.
              </div>
            )}

            {/* Simulated Live Stepper (Loading State) */}
            {simulationState === "loading" && (
              <div className="execution-stepper">
                <div className={`stepper-item ${currentStepperIndex >= 1 ? (currentStepperIndex === 1 ? "active" : "completed") : ""}`}>
                  <div className="stepper-dot" />
                  <div className="stepper-content">
                    <span className="stepper-title">Stage 1: Hub Planner Initialization</span>
                    <span className="stepper-desc">Building execution plan to check grid disruption status.</span>
                    {currentStepperIndex === 1 && <span className="stepper-badge" style={{ color: "var(--brand-blue)" }}>running</span>}
                  </div>
                </div>

                <div className={`stepper-item ${currentStepperIndex >= 2 ? (currentStepperIndex === 2 ? "active" : "completed") : ""}`}>
                  <div className="stepper-dot" />
                  <div className="stepper-content">
                    <span className="stepper-title">Stage 2: Outage Detection Agent</span>
                    <span className="stepper-desc">Querying regional outage database for Zip 78712.</span>
                    {currentStepperIndex === 2 && <span className="stepper-badge" style={{ color: "var(--brand-blue)" }}>running</span>}
                  </div>
                </div>

                <div className={`stepper-item ${currentStepperIndex >= 3 ? (currentStepperIndex === 3 ? "active" : "completed") : ""}`}>
                  <div className="stepper-dot" />
                  <div className="stepper-content">
                    <span className="stepper-title">Stage 3: Weather Context Agent</span>
                    <span className="stepper-desc">Fetching environmental weather logs to evaluate severity drivers.</span>
                    {currentStepperIndex === 3 && <span className="stepper-badge" style={{ color: "var(--brand-blue)" }}>running</span>}
                  </div>
                </div>

                <div className={`stepper-item ${currentStepperIndex >= 4 ? (currentStepperIndex === 4 ? "active" : "completed") : ""}`}>
                  <div className="stepper-dot" />
                  <div className="stepper-content">
                    <span className="stepper-title">Stage 4: Email Notification Agent</span>
                    <span className="stepper-desc">Drafting and formatting personalized utility email notification.</span>
                    {currentStepperIndex === 4 && <span className="stepper-badge" style={{ color: "var(--brand-blue)" }}>running</span>}
                  </div>
                </div>
              </div>
            )}

            {/* Stepper Completed State */}
            {simulationState === "completed" && (
              <div className="execution-stepper">
                <div className="stepper-item completed">
                  <div className="stepper-dot" />
                  <div className="stepper-content">
                    <span className="stepper-title">Stage 1: Hub Planner Plan Formulated</span>
                    <span className="stepper-desc">DAG creator established dependency pipeline successfully.</span>
                    <span className="stepper-badge" style={{ color: "var(--status-success)" }}>done</span>
                  </div>
                </div>

                {planSteps.map((step, idx) => {
                  let agentLabel = step.agent.replace(/_/g, " ").replace(/agent/i, "").trim();
                  let emoji = "⚙️";
                  if (step.agent.includes("outage")) emoji = "⚠️";
                  if (step.agent.includes("weather")) emoji = "🌡️";
                  if (step.agent.includes("email")) emoji = "📧";

                  return (
                    <div className="stepper-item completed" key={step.id}>
                      <div className="stepper-dot" />
                      <div className="stepper-content">
                        <span className="stepper-title">Stage {idx + 2}: {agentLabel} Executed</span>
                        <span className="stepper-desc"><strong>Objective:</strong> {step.objective}</span>
                        <span className="stepper-badge" style={{ color: "var(--status-success)" }}>
                          {emoji} resolved
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Simulated Mail Inbox */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          
          <div className="card" style={{ padding: 20, flex: 1, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div className="card-title">
                <Mail size={16} style={{ color: "var(--brand-blue)" }} />
                Customer Notification Inbox
              </div>
            </div>

            {/* Premium Inbox Screen */}
            <div className="email-client-container">
              
              {/* Client Window Titlebar */}
              <div className="email-inbox-header">
                <div className="email-window-controls">
                  <span className="window-dot close"></span>
                  <span className="window-dot minimize"></span>
                  <span className="window-dot maximize"></span>
                </div>
                <div className="email-client-title">Inbox Client v1.2</div>
                <div style={{ width: 44 }}></div>
              </div>

              {!emailDetails ? (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 40, textAlign: "center" }}>
                  <div style={{ fontSize: 32, marginBottom: 12 }}>📬</div>
                  <h4 style={{ color: "#f8fafc", fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Awaiting Safety Alert</h4>
                  <p style={{ color: "#94a3b8", fontSize: 12 }}>
                    Trigger the outage simulation to build and push the live reactive email draft.
                  </p>
                </div>
              ) : (
                <div className="email-message-wrapper">
                  
                  {/* Sender, Subject Metadata */}
                  <div className="email-metadata-block">
                    <div className="email-avatar-row">
                      <div className="email-sender-avatar">NG</div>
                      <div className="email-meta-info">
                        <div style={{ display: "flex", alignItems: "center" }}>
                          <span className="email-sender-name">NexusGas Utility Operations</span>
                          <span className="email-badge-ai">Drafted by AI</span>
                        </div>
                        <span className="email-recipients">To: james.doe@example.com</span>
                      </div>
                      <div style={{ marginLeft: "auto", fontSize: 11, color: "#64748b" }}>
                        {new Date(emailDetails.sent_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                    <div className="email-subject-row">{emailDetails.subject}</div>
                  </div>

                  {/* Body Scroll Area */}
                  <div className="email-body-scroll">
                    {emailDetails.body.split("\n").map((line, idx) => {
                      const trimmed = line.trim();
                      if (!trimmed) return <div key={idx} style={{ height: 12 }}></div>;
                      
                      if (trimmed.startsWith("🔌") || trimmed.startsWith("🌡️") || trimmed.startsWith("📋") || trimmed.startsWith("Dear") || trimmed.startsWith("NexusGas")) {
                        if (trimmed.startsWith("🔌") || trimmed.startsWith("🌡️") || trimmed.startsWith("📋")) {
                          return <div className="email-section-heading" key={idx}>{trimmed}</div>;
                        }
                        return <p key={idx} style={{ fontWeight: 600, color: "#f1f5f9" }}>{trimmed}</p>;
                      }
                      
                      if (trimmed.startsWith("•") || trimmed.startsWith("-")) {
                        return <div className="email-list-line" key={idx}>{trimmed}</div>;
                      }
                      
                      return <p key={idx}>{trimmed}</p>;
                    })}
                  </div>

                </div>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
