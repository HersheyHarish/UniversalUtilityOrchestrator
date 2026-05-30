import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { api } from "../api/client";
import { streamChat } from "../api/orchestratorStream";

const ChatContext = createContext();
const DEMO_STEPS_ENABLED = String(import.meta.env.VITE_DEMO_STEPS || "").toLowerCase() === "true";

export function ChatProvider({ children }) {
  const [customerId] = useState(() => {
    let id = localStorage.getItem("demo_customer_id");
    const normalized = (id || "").toUpperCase();
    const validDemoIds = new Set(["CUST-1001", "CUST-1002"]);
    if (!validDemoIds.has(normalized)) {
      id = "CUST-1001";
      localStorage.setItem("demo_customer_id", id);
      return id;
    }
    id = normalized;
    localStorage.setItem("demo_customer_id", id);
    return id;
  });

  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [demoEvents, setDemoEvents] = useState([]);
  const [agentOutputs, setAgentOutputs] = useState([]);
  const [activeAgents, setActiveAgents] = useState([]);

  useEffect(() => {
    const fetchSessions = async () => {
      try {
        const data = await api.get(`/api/users/${encodeURIComponent(customerId)}/sessions`);
        setSessions(data.sessions || []);
      } catch {
        // logged by client
      }
    };
    fetchSessions();
  }, [customerId]);

  // Fetch agent registry on mount and poll every 30s to stay live
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const data = await api.get('/api/agents');
        setActiveAgents(data.agents || []);
      } catch {
        // orchestrator may not be running yet; silently retry
      }
    };
    fetchAgents();
    const interval = setInterval(fetchAgents, 30000);
    return () => clearInterval(interval);
  }, []);

  const transcriptToMessages = (transcript) =>
    (transcript || [])
      .filter((t) => t.role === "user" || t.role === "assistant")
      .map((t) => ({
        role: t.role,
        content: t.content,
      }));

  const newlyCreatedSessionRef = React.useRef(null);

  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      setDemoEvents([]);
      setPipelineStages([]);
      return;
    }

    if (newlyCreatedSessionRef.current === activeSessionId) {
      // Session was just created by sendMessage, no need to fetch history
      newlyCreatedSessionRef.current = null;
      return;
    }

    const fetchSessionDetails = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await api.get(`/api/sessions/${activeSessionId}`);
        if (Array.isArray(data.transcript) && data.transcript.length > 0) {
          setMessages(transcriptToMessages(data.transcript));
        } else {
          const history = [];
          if (data.session?.user_message) {
            history.push({ role: "user", content: data.session.user_message });
          }
          if (data.session?.final_response) {
            history.push({ role: "assistant", content: data.session.final_response });
          }
          setMessages(history);
        }
        if (DEMO_STEPS_ENABLED) {
          setDemoEvents(Array.isArray(data.demo_events) ? data.demo_events : []);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };
    fetchSessionDetails();
  }, [activeSessionId]);

  const startNewChat = () => {
    if (abortRef.current) abortRef.current.abort();
    setActiveSessionId(null);
    setMessages([]);
    setDemoEvents([]);
    setAgentOutputs([]);
    setError(null);
  };

  const sendMessage = React.useCallback(async (text) => {
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setIsLoading(true);
    setError(null);
    setPipelineStages([]);
    if (DEMO_STEPS_ENABLED) setDemoEvents([]);
    setAgentOutputs([]);

    let currentSessionId = activeSessionId;
    if (!currentSessionId) {
      currentSessionId = crypto.randomUUID();
      newlyCreatedSessionRef.current = currentSessionId;
      setActiveSessionId(currentSessionId);
    }

    let pollInterval = null;
    if (DEMO_STEPS_ENABLED) {
      pollInterval = setInterval(async () => {
        try {
          const res = await api.get(`/api/sessions/${currentSessionId}`);
          if (res.demo_events) {
            setDemoEvents(res.demo_events);
          }
        } catch (err) {
          // silently ignore polling errors
        }
      }, 1500);
    }

    try {
      const data = await api.post("/api/chat", {
        message: text,
        customer_id: customerId,
        session_id: currentSessionId,
      });

      if (pollInterval) clearInterval(pollInterval);

      if (DEMO_STEPS_ENABLED) {
        try {
          const res = await api.get(`/api/sessions/${currentSessionId}`);
          if (res.demo_events) setDemoEvents(res.demo_events);
          if (res.step_results && Array.isArray(res.step_results)) {
            setAgentOutputs(res.step_results.map(s => ({
              step_id: s.step_id,
              agent_name: s.agent_name,
              result: s.content || s.result || '',
            })));
          }
        } catch (err) {}
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.response,
          segments: data.content_segments,
        },
      ]);

      const sessionData = await api.get(
        `/api/users/${encodeURIComponent(customerId)}/sessions`
      );
      setSessions(sessionData.sessions || []);
    } catch (err) {
      if (pollInterval) clearInterval(pollInterval);
      setError(err.message);
      setMessages((prev) => [
        ...prev,
        { role: "system", isError: true, content: `Error: ${err.message}` },
      ]);
    } finally {
      if (pollInterval) clearInterval(pollInterval);
      setIsLoading(false);
      abortRef.current = null;
    }
  }, [activeSessionId, customerId]);

  return (
    <ChatContext.Provider
      value={{
        customerId,
        sessions,
        activeSessionId,
        setActiveSessionId,
        messages,
        demoEvents,
        agentOutputs,
        activeAgents,
        demoStepsEnabled: DEMO_STEPS_ENABLED,
        streamEnabled: false,
        isLoading,
        error,
        startNewChat,
        sendMessage,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export const useChat = () => useContext(ChatContext);
