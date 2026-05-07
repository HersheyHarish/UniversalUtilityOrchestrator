import React, { createContext, useContext, useState, useEffect } from "react";
import { api } from "../api/client";

const ChatContext = createContext();
const DEMO_STEPS_ENABLED = String(import.meta.env.VITE_DEMO_STEPS || "").toLowerCase() === "true";
const POLL_INTERVAL_MS = 1200;

export function ChatProvider({ children }) {
  // Keep demo customer id aligned with backend demo data (CUST-1001 / CUST-1002).
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

  // Fetch all sessions for this customer on mount
  useEffect(() => {
    const fetchSessions = async () => {
      try {
        const data = await api.get(`/api/users/${encodeURIComponent(customerId)}/sessions`);
        setSessions(data.sessions || []);
      } catch (err) {
        // Will be console logged by client
      }
    };
    fetchSessions();
  }, [customerId]);

  // Fetch specific session details when activeSessionId changes
  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      setDemoEvents([]);
      return;
    }

    const fetchSessionDetails = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await api.get(`/api/sessions/${activeSessionId}`);
        // Combine user message, plans, and step results into a readable message list
        // For simplicity in this demo, we can just show the final responses or full history
        const history = [];
        
        // Push user message
        if (data.session.user_message) {
          history.push({ role: 'user', content: data.session.user_message });
        }
        
        // Push step results
        if (data.step_results) {
          data.step_results.forEach(msg => {
             // For the demo, we might just want to show the final response
             // or format step results nicely. We'll store them all.
             history.push({ role: 'system', type: msg.type, content: msg.content, agent: msg.agent_name });
          });
        }

        // Push final response if it exists and wasn't already in messages
        if (data.session.final_response) {
          history.push({ role: 'assistant', content: data.session.final_response });
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
    setActiveSessionId(null);
    setMessages([]);
    setDemoEvents([]);
    setError(null);
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const sendMessage = async (text) => {
    // Optimistic UI update
    const newMsg = { role: 'user', content: text };
    setMessages(prev => [...prev, newMsg]);
    setIsLoading(true);
    setError(null);
    if (DEMO_STEPS_ENABLED) setDemoEvents([]);

    const priorIds = new Set((sessions || []).map((s) => s.id));
    let observedSessionId = activeSessionId || null;
    const pollingControl = { done: false };
    let pollPromise = Promise.resolve();
    try {

      if (DEMO_STEPS_ENABLED) {
        pollPromise = (async () => {
          while (!pollingControl.done) {
            try {
              if (!observedSessionId) {
                const sessionData = await api.get(`/api/users/${encodeURIComponent(customerId)}/sessions`);
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
            } catch (_pollErr) {
              // Poll failures should not interrupt normal chat flow.
            }
            await sleep(POLL_INTERVAL_MS);
          }
        })();
      }

      const data = await api.post('/api/chat', {
        message: text,
        customer_id: customerId,
        session_id: activeSessionId
      });

      if (!activeSessionId && data.session_id) {
        setActiveSessionId(data.session_id);
      }

      // Keep sidebar in sync after every successful turn (Cosmos write succeeded)
      const sessionData = await api.get(`/api/users/${encodeURIComponent(customerId)}/sessions`);
      setSessions(sessionData.sessions || []);

      setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
      pollingControl.done = true;
      await pollPromise;
      const detail = await api.get(`/api/sessions/${data.session_id || observedSessionId || activeSessionId}`);
      if (DEMO_STEPS_ENABLED) {
        setDemoEvents(Array.isArray(detail.demo_events) ? detail.demo_events : []);
      }
    } catch (err) {
      pollingControl.done = true;
      await pollPromise;
      setError(err.message);
      setMessages(prev => [...prev, { role: 'system', isError: true, content: `Error: ${err.message}` }]);
    } finally {
      pollingControl.done = true;
      setIsLoading(false);
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
        demoStepsEnabled: DEMO_STEPS_ENABLED,
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
