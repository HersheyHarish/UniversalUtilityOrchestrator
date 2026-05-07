import { useEffect, useState } from "react";
import { api } from "../api/client";

export function useDashboardData() {
  const [customerId] = useState("CUST-1001");
  const [sinceHours] = useState(168);
  const [selectedDate, setSelectedDate] = useState("2019-07-15");
  const [insights, setInsights] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [copilotContext, setCopilotContext] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadAll = async () => {
    setLoading(true);
    setError("");
    try {
      const [ins, al, ctx] = await Promise.all([
        api.insights(customerId, sinceHours),
        api.alerts(customerId, "all"),
        api.copilotContext(customerId, selectedDate),
      ]);
      setInsights(ins.insights || []);
      setAlerts(al.alerts || []);
      setCopilotContext(ctx.context || null);
    } catch (e) {
      setError(e.message || "Failed to load dashboard data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onDateSelect = async (date) => {
    setSelectedDate(date);
    try {
      const ctx = await api.copilotContext(customerId, date);
      setCopilotContext(ctx.context || null);
    } catch (e) {
      setError(e.message || "Failed to load copilot context.");
    }
  };

  const onAckAlert = async (alertId, action) => {
    try {
      await api.ackAlert(alertId, action, customerId);
      const al = await api.alerts(customerId, "all");
      setAlerts(al.alerts || []);
    } catch (e) {
      setError(e.message || "Failed to acknowledge alert.");
    }
  };

  const onInsightAction = async (action, payload = {}) => {
    if (action === "apply_ev_schedule") {
      setError("");
      return;
    }
    if (action === "open_copilot_context") {
      const chosenDate = selectedDate;
      await onDateSelect(chosenDate);
      return;
    }
    if (action === "retry_session" && payload.session_id) {
      try {
        await api.ackAlert(`alert-${payload.session_id}`, "retry", customerId);
        const al = await api.alerts(customerId, "all");
        setAlerts(al.alerts || []);
      } catch (e) {
        setError(e.message || "Failed to register retry action.");
      }
    }
  };

  return {
    customerId,
    sinceHours,
    insights,
    alerts,
    copilotContext,
    selectedDate,
    loading,
    error,
    onDateSelect,
    onAckAlert,
    onInsightAction,
  };
}
