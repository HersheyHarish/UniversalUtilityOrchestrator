// state/useDashboard.js
// Central state hook — orchestrates real API calls and background orchestrator jobs

import { useCallback, useEffect, useRef, useState } from "react";
import { orchestratorApi } from "../api/orchestratorClient";
import { streamChat } from "../api/orchestratorStream";

const CHAT_STREAM_ENABLED =
  String(import.meta.env.VITE_CHAT_STREAM ?? "true").toLowerCase() !== "false";
import { mapAgentMeta, truncateFeedMessage } from "../constants/proactiveAgents";

const CUSTOMER_ID = "CUST-1001";
const SINCE_HOURS = 168;
const BACKGROUND_JOB_INTERVAL = 30000;

const BACKGROUND_PROMPTS = [
  "Ask the outage detection agent whether customer CUST-1001 had any service disruptions recently. Do not review billing.",
  "Ask the anomaly detection agent to check customer CUST-1001 for unusual usage spikes in the last billing period. Do not review billing.",
  "Ask the solar performance agent to check whether customer CUST-1001 solar production is underperforming. Do not review billing.",
  "Ask the bill shock forecast agent whether customer CUST-1001 is on track for an unusually high bill this cycle. Do not review past invoices or payment history.",
];

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

  const [agentEvents, setAgentEvents] = useState([]);
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

  const bgTimerRef = useRef(null);
  const promptIndexRef = useRef(0);
  const billExplanationFetchedRef = useRef(false);
  const toastTimerRef = useRef(null);

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
      const [insData, alertData] = await Promise.all([
        orchestratorApi.insights(CUSTOMER_ID, SINCE_HOURS).catch(() => ({ insights: [] })),
        orchestratorApi.alerts(CUSTOMER_ID, "all").catch(() => ({ alerts: [] })),
      ]);
      setInsights(insData.insights || []);
      setRealAlerts(alertData.alerts || []);
    } catch {
      // non-fatal
    } finally {
      setInsightsLoading(false);
    }
  }, []);

  const appendAgentEvent = useCallback((res, source = "proactive") => {
    const primaryAgent = res.agents_used?.length > 0 ? res.agents_used[0] : "orchestrator";
    const meta = mapAgentMeta(primaryAgent);
    const newEvent = {
      id: `orch-${Date.now()}`,
      agentId: meta.id,
      agentName: meta.name,
      agentIcon: meta.icon,
      agentColor: meta.color,
      message: truncateFeedMessage(res.response),
      timestamp: new Date().toISOString(),
      source,
      actions: [],
    };
    setAgentEvents((prev) => [newEvent, ...prev].slice(0, 30));
    return newEvent;
  }, []);

  const triggerBackgroundOrchestrator = useCallback(async () => {
    const prompt = BACKGROUND_PROMPTS[promptIndexRef.current % BACKGROUND_PROMPTS.length];
    promptIndexRef.current += 1;

    try {
      const res = await orchestratorApi.chat(prompt, CUSTOMER_ID);
      appendAgentEvent(res, "proactive");
    } catch (e) {
      console.warn("Background orchestrator job failed:", e);
    }
  }, [appendAgentEvent]);

  const startBackgroundJobs = useCallback(() => {
    triggerBackgroundOrchestrator();
    bgTimerRef.current = setInterval(() => {
      triggerBackgroundOrchestrator();
    }, BACKGROUND_JOB_INTERVAL);
  }, [triggerBackgroundOrchestrator]);

  const fetchBillExplanation = useCallback(async () => {
    setBillExplanationLoading(true);
    setBillExplanationError(null);
    try {
      const prompt = buildBillExplanationPrompt(billing);
      const res = await orchestratorApi.chat(prompt, CUSTOMER_ID);
      setBillExplanation(res.response || "No explanation available.");
      setBillExplanationAgents(res.agents_used || []);
    } catch (err) {
      setBillExplanationError(err.message || "Could not load bill explanation.");
      setBillExplanation(null);
    } finally {
      setBillExplanationLoading(false);
    }
  }, [billing]);

  const triggerProactiveNotification = useCallback(async () => {
    if (proactiveLoading) return;
    setProactiveLoading(true);
    setHasUnreadProactive(false);
    try {
      const res = await orchestratorApi.chat(PROACTIVE_BUTTON_PROMPT, CUSTOMER_ID);
      appendAgentEvent(res, "proactive");
      const agentLabel = res.agents_used?.length
        ? res.agents_used.map((a) => a.replace(/_/g, " ")).join(", ")
        : "Orchestrator";
      showToast({
        id: `toast-${Date.now()}`,
        title: "Proactive update",
        body: res.response || "Your account was checked successfully.",
        agents: agentLabel,
      });
    } catch (err) {
      showToast({
        id: `toast-err-${Date.now()}`,
        title: "Proactive check failed",
        body: err.message || "Could not reach the orchestrator.",
        agents: null,
      });
    } finally {
      setProactiveLoading(false);
    }
  }, [proactiveLoading, appendAgentEvent, showToast]);

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
    setChatMessages((prev) => [
      ...prev.filter((m) => m.role !== "thinking"),
      { role: "assistant", content: "", streaming: true },
    ]);

    const body = {
      message,
      customer_id: CUSTOMER_ID,
      session_id: sessionId,
    };

    const finishAssistant = (content, segments, metadata) => {
      setChatMessages((prev) =>
        prev
          .filter((m) => !(m.role === "assistant" && m.streaming))
          .concat({
            role: "assistant",
            content: content || "I processed your request successfully.",
            segments,
            metadata,
          })
      );
    };

    try {
      if (CHAT_STREAM_ENABLED) {
        let streamed = "";
        await streamChat({
          url: orchestratorApi.chatStreamUrl(),
          body,
          onEvent: (event, data) => {
            if (event === "session" && data.session_id && !sessionId) {
              setSessionId(data.session_id);
            }
            if (event === "token" && data.delta) {
              streamed += data.delta;
              setChatMessages((prev) => {
                const next = prev.filter((m) => m.role !== "thinking");
                const last = next[next.length - 1];
                if (last?.streaming) {
                  return [
                    ...next.slice(0, -1),
                    { ...last, content: streamed },
                  ];
                }
                return [
                  ...next,
                  { role: "assistant", content: streamed, streaming: true },
                ];
              });
            }
            if (event === "done") {
              if (data.session_id && !sessionId) setSessionId(data.session_id);
              finishAssistant(data.response, data.content_segments, {
                agents: data.agents_used,
                steps: data.steps_completed,
              });
            }
            if (event === "error") {
              throw new Error(data.detail || data.error || "Stream failed");
            }
          },
        });
      } else {
        const res = await orchestratorApi.chat(message, CUSTOMER_ID, sessionId);
        if (res.session_id && !sessionId) setSessionId(res.session_id);
        finishAssistant(res.response, res.content_segments, {
          agents: res.agents_used,
          steps: res.steps_completed,
        });
      }
    } catch (err) {
      try {
        const res = await orchestratorApi.chat(message, CUSTOMER_ID, sessionId);
        if (res.session_id && !sessionId) setSessionId(res.session_id);
        finishAssistant(res.response, res.content_segments, {
          agents: res.agents_used,
          steps: res.steps_completed,
        });
      } catch (fallbackErr) {
        setChatMessages((prev) =>
          prev
            .filter((m) => !(m.streaming && m.role === "assistant"))
            .concat({
              role: "assistant",
              content: `I encountered an issue connecting to the orchestrator: ${fallbackErr.message}. Please try again.`,
            })
        );
      }
    } finally {
      setChatLoading(false);
    }
  }, [chatLoading, sessionId]);

  useEffect(() => {
    checkOrchHealth();
    loadRealData();
    startBackgroundJobs();

    const healthInterval = setInterval(checkOrchHealth, 30000);
    return () => {
      clearInterval(bgTimerRef.current);
      clearInterval(healthInterval);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, [checkOrchHealth, loadRealData, startBackgroundJobs]);

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
    agentEvents,
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
  };
}
