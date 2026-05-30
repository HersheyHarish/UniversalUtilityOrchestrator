import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { api } from "../api/client";
import { streamChat } from "../api/orchestratorStream";

const ChatContext = createContext();
const DEMO_STEPS_ENABLED = String(import.meta.env.VITE_DEMO_STEPS || "").toLowerCase() === "true";
const STREAM_ENABLED = String(import.meta.env.VITE_CHAT_STREAM ?? "true").toLowerCase() !== "false";
const POLL_INTERVAL_MS = 1200;

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
  const [pipelineStages, setPipelineStages] = useState([]);
  const abortRef = useRef(null);

  useEffect(() => {
    const fetchSessions = async () => {
      try {
        const data = await api.get(`/api/users/${encodeURIComponent(customerId)}/sessions`);
        setSessions(data.sessions || []);
      } catch (err) {
        // logged by client
      }
    };
    fetchSessions();
  }, [customerId]);

  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      setDemoEvents([]);
      setPipelineStages([]);
      return;
    }

    const fetchSessionDetails = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await api.get(`/api/sessions/${activeSessionId}`);
        const history = [];

        if (data.session.user_message) {
          history.push({ role: "user", content: data.session.user_message });
        }

        if (data.step_results) {
          data.step_results.forEach((msg) => {
            history.push({
              role: "system",
              type: msg.type,
              content: msg.content,
              agent: msg.agent_name,
            });
          });
        }

        if (data.session.final_response) {
          history.push({
            role: "assistant",
            content: data.session.final_response,
          });
        }

        setMessages(history);
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
    setPipelineStages([]);
    setError(null);
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const appendAssistantDelta = (delta) => {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant" && last.streaming) {
        next[next.length - 1] = {
          ...last,
          content: (last.content || "") + delta,
        };
        return next;
      }
      return [
        ...next,
        { role: "assistant", content: delta, streaming: true },
      ];
    });
  };

  const finalizeAssistant = (content, segments) => {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant") {
        next[next.length - 1] = {
          role: "assistant",
          content,
          segments,
          streaming: false,
        };
        return next;
      }
      return [...next, { role: "assistant", content, segments }];
    });
  };

  const sendMessage = async (text) => {
    const newMsg = { role: "user", content: text };
    setMessages((prev) => [...prev, newMsg]);
    setIsLoading(true);
    setError(null);
    setPipelineStages([]);
    if (DEMO_STEPS_ENABLED) setDemoEvents([]);

    const priorIds = new Set((sessions || []).map((s) => s.id));
    let observedSessionId = activeSessionId || null;
    const pollingControl = { done: false };
    let pollPromise = Promise.resolve();

    const useStream = STREAM_ENABLED;
    const body = {
      message: text,
      customer_id: customerId,
      session_id: activeSessionId,
    };

    try {
      if (DEMO_STEPS_ENABLED && !useStream) {
        pollPromise = (async () => {
          while (!pollingControl.done) {
            try {
              if (!observedSessionId) {
                const sessionData = await api.get(
                  `/api/users/${encodeURIComponent(customerId)}/sessions`
                );
                const listed = sessionData.sessions || [];
                setSessions(listed);
                const newlyCreated = listed.find((s) => !priorIds.has(s.id));
                if (newlyCreated?.id) {
                  observedSessionId = newlyCreated.id;
                  setActiveSessionId((prev) => prev || newlyCreated.id);
                }
              }
              if (observedSessionId) {
                const detail = await api.get(`/api/sessions/${observedSessionId}`);
                setDemoEvents(Array.isArray(detail.demo_events) ? detail.demo_events : []);
              }
            } catch {
              /* non-fatal */
            }
            await sleep(POLL_INTERVAL_MS);
          }
        })();
      }

      if (useStream) {
        abortRef.current = new AbortController();
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "", streaming: true },
        ]);

        await streamChat({
          url: "/api/chat/stream",
          body,
          signal: abortRef.current.signal,
          onEvent: (event, data) => {
            if (event === "session" && data.session_id) {
              observedSessionId = data.session_id;
              setActiveSessionId((prev) => prev || data.session_id);
            }
            if (event === "stage") {
              setPipelineStages((prev) => [
                ...prev,
                {
                  stage: data.stage,
                  status: data.status,
                  message: data.message,
                },
              ]);
              if (DEMO_STEPS_ENABLED) {
                setDemoEvents((prev) => [
                  ...prev,
                  {
                    stage: data.stage,
                    status: data.status,
                    message: data.message,
                    timestamp: new Date().toISOString(),
                  },
                ]);
              }
            }
            if (event === "step") {
              setPipelineStages((prev) => [
                ...prev,
                {
                  stage: "execution",
                  status: data.status,
                  message: `${data.agent_name} (step ${data.step_id})`,
                },
              ]);
            }
            if (event === "token" && data.delta) {
              appendAssistantDelta(data.delta);
            }
            if (event === "done") {
              finalizeAssistant(
                data.response || "",
                data.content_segments || null
              );
              if (data.session_id) {
                observedSessionId = data.session_id;
                setActiveSessionId((prev) => prev || data.session_id);
              }
            }
            if (event === "error") {
              throw new Error(data.detail || data.error || "Stream failed");
            }
          },
        });
      } else {
        const data = await api.post("/api/chat", body);
        if (!activeSessionId && data.session_id) {
          setActiveSessionId(data.session_id);
        }
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.response,
            segments: data.content_segments,
          },
        ]);
        observedSessionId = data.session_id || observedSessionId;
      }

      pollingControl.done = true;
      await pollPromise;

      const sessionData = await api.get(
        `/api/users/${encodeURIComponent(customerId)}/sessions`
      );
      setSessions(sessionData.sessions || []);

      const sid = observedSessionId || activeSessionId;
      if (sid && DEMO_STEPS_ENABLED) {
        const detail = await api.get(`/api/sessions/${sid}`);
        setDemoEvents(Array.isArray(detail.demo_events) ? detail.demo_events : []);
      }
    } catch (err) {
      pollingControl.done = true;
      await pollPromise;

      if (useStream && err.name !== "AbortError") {
        try {
          const data = await api.post("/api/chat", body);
          finalizeAssistant(data.response, data.content_segments);
          if (data.session_id) setActiveSessionId((prev) => prev || data.session_id);
          const sessionData = await api.get(
            `/api/users/${encodeURIComponent(customerId)}/sessions`
          );
          setSessions(sessionData.sessions || []);
          return;
        } catch (fallbackErr) {
          setError(fallbackErr.message);
        }
      } else if (err.name !== "AbortError") {
        setError(err.message);
      }

      setMessages((prev) => {
        const filtered = prev.filter(
          (m) => !(m.role === "assistant" && m.streaming && !m.content)
        );
        if (err.name !== "AbortError" && !useStream) {
          return [
            ...filtered,
            {
              role: "system",
              isError: true,
              content: `Error: ${err.message}`,
            },
          ];
        }
        return filtered;
      });
    } finally {
      pollingControl.done = true;
      setIsLoading(false);
      abortRef.current = null;
    }
  };

  return (
    <ChatContext.Provider
      value={{
        customerId,
        sessions,
        activeSessionId,
        setActiveSessionId,
        messages,
        demoEvents,
        pipelineStages,
        demoStepsEnabled: DEMO_STEPS_ENABLED || STREAM_ENABLED,
        streamEnabled: STREAM_ENABLED,
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
