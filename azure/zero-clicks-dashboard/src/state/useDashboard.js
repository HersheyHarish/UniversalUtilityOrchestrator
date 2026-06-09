// state/useDashboard.js
// Central state hook — orchestrates real API calls and background orchestrator jobs

import { useCallback, useEffect, useRef, useState } from "react";
import { orchestratorApi } from "../api/orchestratorClient";
import { mapAgentMeta, truncateFeedMessage, PROACTIVE_ROSTER } from "../constants/proactiveAgents";

const CUSTOMER_ID = "CUST-1001";
const SINCE_HOURS = 168;

const PROACTIVE_BUTTON_PROMPT =
  "Run a proactive check for customer CUST-1001 using outage detection and anomaly detection agents only. Summarize any advisories. Do not use the billing agent or review payment details.";

function buildBillExplanationPrompt(billing) {
  const lineItems = billing.breakdown
    .map((r) => `${r.label}: $${r.amount.toFixed(2)}`)
    .join("; ");
  return `Explain why customer ${CUSTOMER_ID}'s current bill is $${billing.currentBalance.toFixed(2)}. Line items: ${lineItems}. Be concise and customer-friendly.`;
}

export function useDashboard() {
  const [orchStatus, setOrchStatus] = useState("checking");

  const [billing] = useState({
    currentBalance: 84.50,
    dueDate: "May 28, 2026",
    daysUntilDue: 15,
    lastPayment: { amount: 91.20, date: "Apr 28, 2026" },
    breakdown: [
      { label: "Gas Delivery", amount: 48.20 },
      { label: "Distribution Charge", amount: 16.80 },
      { label: "Pipeline Safety Fee", amount: 3.75 },
      { label: "State Tax (4.2%)", amount: 2.88 },
      { label: "Customer Service Charge", amount: 8.53 },
    ],
  });

  const [usageData] = useState([
    { month: "Jan", therms: 96, prev: 102 },
    { month: "Feb", therms: 89, prev: 95 },
    { month: "Mar", therms: 71, prev: 78 },
    { month: "Apr", therms: 53, prev: 61 },
    { month: "May", therms: 42, prev: 49 },
  ]);

  const [activeAgents, setActiveAgents] = useState([]);
  const [realAlerts, setRealAlerts] = useState([]);
  const [insights, setInsights] = useState([]);
  const [insightsLoading, setInsightsLoading] = useState(false);

  const [billExplanation, setBillExplanation] = useState(null);
  const [billExplanationLoading, setBillExplanationLoading] = useState(false);
  const [billExplanationError, setBillExplanationError] = useState(null);
  const [billExplanationAgents, setBillExplanationAgents] = useState([]);

  const [proactiveLoading, setProactiveLoading] = useState(false);
  const [proactiveToast, setProactiveToast] = useState(null);
  const [hasUnreadProactive, setHasUnreadProactive] = useState(false);

  const [chatMessages, setChatMessages] = useState([
    {
      role: "assistant",
      content: "Hi! I'm your NexusGas AI assistant. I can help you understand your bill, check usage, report issues, or explore ways to save energy. What can I help you with today?",
    },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);

  const [activeTrace, setActiveTrace] = useState({
    status: "idle",
    triggerType: null,
    steps: []
  });

  const billExplanationFetchedRef = useRef(false);
  const toastTimerRef = useRef(null);
  const traceTimerRef = useRef(null);

  const showToast = useCallback((toast) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setProactiveToast(toast);
    setHasUnreadProactive(true);
    toastTimerRef.current = setTimeout(() => {
      setProactiveToast(null);
    }, 8000);
  }, []);

  const dismissToast = useCallback(() => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setProactiveToast(null);
    setHasUnreadProactive(false);
  }, []);

  const runSimulatedTrace = useCallback((triggerType, triggeringAgent = null) => {
    if (traceTimerRef.current) clearInterval(traceTimerRef.current);
    
    const steps = [
      { stage: "guardrails", message: "Validating input request and security policy...", status: "completed" },
      { stage: "planning", message: triggeringAgent 
        ? `LLM Planner: Triggered by ${triggeringAgent.replace(/_/g, " ")}. Planning DAG...`
        : "LLM Planner: Building execution plan DAG...", status: "running" },
      { stage: "execution", message: "Awaiting execution DAG...", status: "pending" },
      { stage: "synthesis", message: "Synthesizing final response...", status: "pending" }
    ];

    setActiveTrace({
      status: "running",
      triggerType,
      steps
    });

    let currentStep = 0;
    traceTimerRef.current = setInterval(() => {
      currentStep += 1;
      if (currentStep === 1) {
        setActiveTrace(prev => ({
          ...prev,
          steps: [
            { stage: "guardrails", message: "Validating input request and security policy...", status: "completed" },
            { stage: "planning", message: "LLM Planner: Built execution plan with 2 steps.", status: "completed" },
            { stage: "execution", message: triggerType === "proactive" 
              ? "Running anomaly_detection_agent..." 
              : "Running billing_agent...", status: "running" },
            { stage: "synthesis", message: "Synthesizing final response...", status: "pending" }
          ]
        }));
      } else if (currentStep === 2) {
        setActiveTrace(prev => ({
          ...prev,
          steps: [
            { stage: "guardrails", message: "Validating input request and security policy...", status: "completed" },
            { stage: "planning", message: "LLM Planner: Built execution plan with 2 steps.", status: "completed" },
            { stage: "execution", message: triggerType === "proactive" 
              ? "Running solar_performance_credit_loss_agent..." 
              : "Running customer_lookup_agent...", status: "running" },
            { stage: "synthesis", message: "Synthesizing final response...", status: "pending" }
          ]
        }));
      } else if (currentStep === 3) {
        setActiveTrace(prev => ({
          ...prev,
          steps: [
            { stage: "guardrails", message: "Validating input request and security policy...", status: "completed" },
            { stage: "planning", message: "LLM Planner: Built execution plan with 2 steps.", status: "completed" },
            { stage: "execution", message: "Graph execution complete.", status: "completed" },
            { stage: "synthesis", message: "Synthesizing agent responses with GPT-4o...", status: "running" }
          ]
        }));
        clearInterval(traceTimerRef.current);
      }
    }, 2000);
  }, []);

  const finishTrace = useCallback((res, status = "completed") => {
    if (traceTimerRef.current) clearInterval(traceTimerRef.current);
    const agents = res.agents_used || [];
    setActiveTrace(prev => ({
      ...prev,
      status,
      steps: [
        { stage: "guardrails", message: "Input validation passed.", status: "completed" },
        { stage: "planning", message: `LLM Planner: Planned ${agents.length} agent steps.`, status: "completed" },
        { stage: "execution", message: `Executed: ${agents.join(", ") || "orchestrator"}.`, status: "completed" },
        { stage: "synthesis", message: "Response successfully synthesized.", status: "completed" }
      ]
    }));
  }, []);

  const failTrace = useCallback((err) => {
    if (traceTimerRef.current) clearInterval(traceTimerRef.current);
    setActiveTrace(prev => ({
      ...prev,
      status: "failed",
      steps: [
        { stage: "guardrails", message: "Input validation passed.", status: "completed" },
        { stage: "planning", message: "LLM Planner failed or aborted.", status: "failed" },
        { stage: "error", message: err.message || "Execution failed.", status: "failed" }
      ]
    }));
  }, []);

  const checkOrchHealth = useCallback(async () => {
    try {
      await orchestratorApi.health();
      setOrchStatus("connected");
    } catch {
      setOrchStatus("disconnected");
    }
  }, []);

  const loadRealData = useCallback(async () => {
    setInsightsLoading(true);
    try {
      const [insData, alertData, agentsData] = await Promise.all([
        orchestratorApi.insights(CUSTOMER_ID, SINCE_HOURS).catch(() => ({ insights: [] })),
        orchestratorApi.alerts(CUSTOMER_ID, "all").catch(() => ({ alerts: [] })),
        orchestratorApi.agents().catch(() => ({ agents: [] })),
      ]);
      setInsights(insData.insights || []);
      setRealAlerts(alertData.alerts || []);
      const fetchedAgents = agentsData.agents || [];
      if (fetchedAgents.length > 0) {
        setActiveAgents(fetchedAgents);
      } else {
        const fallback = [
          { name: "billing_agent", description: "Explains billing charges using RAG-based policy retrieval and structured billing facts." },
          { name: "anomaly_detection_agent", description: "Detects usage anomalies for demo households over a requested billing window." },
          { name: "customer_lookup_agent", description: "Returns comprehensive customer account profiles, including current plan details." },
          { name: "solar_performance_credit_loss_agent", description: "Monitors solar production against baselines and identifies underperformance." },
          { name: "bill_shock_forecast_agent", description: "Mid-cycle bill forecaster that projects end-of-cycle charges and flags anomalies." }
        ];
        setActiveAgents(fallback);
      }
    } catch {
      // non-fatal
    } finally {
      setInsightsLoading(false);
    }
  }, []);



  const fetchBillExplanation = useCallback(async () => {
    setBillExplanationLoading(true);
    setBillExplanationError(null);
    runSimulatedTrace("explanation");
    try {
      const prompt = buildBillExplanationPrompt(billing);
      const res = await orchestratorApi.chat(prompt, CUSTOMER_ID);
      setBillExplanation(res.response || "No explanation available.");
      setBillExplanationAgents(res.agents_used || []);
      finishTrace(res);
    } catch (err) {
      setBillExplanationError(err.message || "Could not load bill explanation.");
      setBillExplanation(null);
      failTrace(err);
    } finally {
      setBillExplanationLoading(false);
    }
  }, [billing, runSimulatedTrace, finishTrace, failTrace]);

  const triggerProactiveNotification = useCallback(async (scenario = null) => {
    if (proactiveLoading) return;

    const selectedScenario = scenario || {
      agentName: "anomaly_detection_agent",
      eventType: "usage_anomaly_detected",
      message: "Critical: Anomaly detected on account CUST-1001. Smart meter registered a 3.4x spike in consumption relative to the 30-day baseline.",
      severity: "high"
    };

    setProactiveLoading(true);
    setHasUnreadProactive(false);
    runSimulatedTrace("proactive", selectedScenario.agentName);
    try {
      const res = await orchestratorApi.proactiveTrigger(
        selectedScenario.message,
        CUSTOMER_ID,
        selectedScenario.agentName,
        selectedScenario.eventType,
        selectedScenario.severity
      );
      const agentLabel = res.agents_used?.length
        ? res.agents_used.map((a) => a.replace(/_/g, " ")).join(", ")
        : "Orchestrator";
      showToast({
        id: `toast-${Date.now()}`,
        title: `Proactive Alert: ${selectedScenario.agentName.replace(/_/g, " ").replace(/\bagent\b/gi, "")}`,
        body: res.response || "Your account alert was checked successfully.",
        agents: agentLabel,
      });
      finishTrace(res);
    } catch (err) {
      showToast({
        id: `toast-err-${Date.now()}`,
        title: "Proactive check failed",
        body: err.message || "Could not reach the orchestrator.",
        agents: null,
      });
      failTrace(err);
    } finally {
      setProactiveLoading(false);
    }
  }, [proactiveLoading, showToast, runSimulatedTrace, finishTrace, failTrace]);

  const ackAlert = useCallback(async (alertId, action) => {
    try {
      await orchestratorApi.ackAlert(alertId, action, CUSTOMER_ID);
      const alertData = await orchestratorApi.alerts(CUSTOMER_ID, "all").catch(() => ({ alerts: [] }));
      setRealAlerts(alertData.alerts || []);
    } catch {
      // silent
    }
  }, []);

  const sendChat = useCallback(async (message) => {
    if (!message.trim() || chatLoading) return;

    setChatMessages((prev) => [...prev, { role: "user", content: message }]);
    setChatInput("");
    setChatLoading(true);
    setChatMessages((prev) => [...prev.filter((m) => m.role !== "thinking"), { role: "thinking" }]);
    runSimulatedTrace("copilot");

    try {
      const res = await orchestratorApi.chat(message, CUSTOMER_ID, sessionId);
      if (res.session_id) {
        setSessionId((prev) => prev || res.session_id);
      }
      setChatMessages((prev) =>
        prev
          .filter((m) => m.role !== "thinking")
          .concat({
            role: "assistant",
            content: res.response || "I processed your request successfully.",
            segments: res.content_segments,
            metadata: { agents: res.agents_used, steps: res.steps_completed },
          })
      );
      finishTrace(res);
    } catch (err) {
      setChatMessages((prev) =>
        prev
          .filter((m) => m.role !== "thinking")
          .concat({
            role: "assistant",
            content: `I encountered an issue connecting to the orchestrator: ${err.message}. Please try again.`,
          })
      );
      failTrace(err);
    } finally {
      setChatLoading(false);
    }
  }, [chatLoading, sessionId, runSimulatedTrace, finishTrace, failTrace]);

  useEffect(() => {
    checkOrchHealth();
    loadRealData();

    const healthInterval = setInterval(checkOrchHealth, 30000);
    return () => {
      clearInterval(healthInterval);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      if (traceTimerRef.current) clearInterval(traceTimerRef.current);
    };
  }, [checkOrchHealth, loadRealData]);

  useEffect(() => {
    if (orchStatus === "connected" && !billExplanationFetchedRef.current) {
      billExplanationFetchedRef.current = true;
      fetchBillExplanation();
    }
  }, [orchStatus, fetchBillExplanation]);

  return {
    customerId: CUSTOMER_ID,
    orchStatus,
    billing,
    usageData,
    realAlerts,
    insights,
    insightsLoading,
    billExplanation,
    billExplanationLoading,
    billExplanationError,
    billExplanationAgents,
    refetchBillExplanation: fetchBillExplanation,
    proactiveLoading,
    proactiveToast,
    hasUnreadProactive,
    triggerProactiveNotification,
    dismissToast,
    chatMessages,
    chatInput,
    setChatInput,
    chatLoading,
    sendChat,
    ackAlert,
    activeAgents,
    activeTrace,
  };
}
