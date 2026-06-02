import React, { useRef, useEffect } from "react";
import { MessageContent } from "./MessageContent";

// Suggested quick questions
const QUICK_PROMPTS = [
  "Why is my bill higher this month?",
  "What's my current rate?",
  "When is my next payment due?",
  "Show me usage for last winter",
  "Are there any outages in my area?",
];

export function CopilotChat({ chatMessages, chatInput, setChatInput, chatLoading, sendChat }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat(chatInput);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <span style={{
            width: 28, height: 28, borderRadius: "50%",
            background: "linear-gradient(135deg, var(--brand-blue), #7C3AED)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 13, flexShrink: 0,
          }}>✨</span>
          AI Copilot
          <span className="tag reactive">Reactive</span>
        </div>
        <div className="pill info">
          <span className="pill-dot" />Wired to Orchestrator
        </div>
      </div>

      {/* Quick prompts */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {QUICK_PROMPTS.map(q => (
          <button
            key={q}
            className="btn btn-ghost btn-sm"
            style={{
              border: "1px solid var(--border-subtle)",
              borderRadius: "999px",
              fontSize: 11,
            }}
            onClick={() => sendChat(q)}
          >
            {q}
          </button>
        ))}
      </div>

      {/* Chat messages */}
      <div className="chat-messages">
        {chatMessages.map((msg, i) => {
          if (msg.role === "thinking") {
            return (
              <div key={i} className="chat-msg">
                <div className="chat-avatar assistant">✨</div>
                <div className="chat-bubble assistant thinking">
                  <div className="thinking-dot" />
                  <div className="thinking-dot" />
                  <div className="thinking-dot" />
                </div>
              </div>
            );
          }
          return (
            <div key={i} className={`chat-msg ${msg.role}`}>
              {msg.role === "assistant" && (
                <div className="chat-avatar assistant">✨</div>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 4, width: "100%" }}>
                <div className={`chat-bubble ${msg.role}`}>
                  {msg.role === "assistant" ? (
                    <MessageContent content={msg.content} segments={msg.segments} />
                  ) : (
                    msg.content
                  )}
                </div>
                {msg.metadata && msg.metadata.agents && msg.metadata.agents.length > 0 && (
                  <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginLeft: 4 }}>
                    Powered by: {msg.metadata.agents.join(", ")}
                  </div>
                )}
              </div>
              {msg.role === "user" && (
                <div className="chat-avatar user">JD</div>
              )}
            </div>
          );
        })}
        <div ref={endRef} />
      </div>

      <div className="divider" style={{ margin: "12px 0" }} />

      {/* Input */}
      <div className="copilot-input-row">
        <textarea
          className="copilot-input"
          rows={2}
          placeholder="Ask about your bill, usage, outages, or savings..."
          value={chatInput}
          onChange={e => setChatInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={chatLoading}
        />
        <button
          className="btn btn-primary"
          onClick={() => sendChat(chatInput)}
          disabled={chatLoading || !chatInput.trim()}
          style={{ height: 56, paddingLeft: 18, paddingRight: 18, flexShrink: 0 }}
        >
          {chatLoading ? (
            <span style={{ display: "inline-block", width: 14, height: 14, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
          ) : "Send →"}
        </button>
      </div>
    </div>
  );
}
