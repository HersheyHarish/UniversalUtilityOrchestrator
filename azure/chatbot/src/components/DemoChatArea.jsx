import React, { useRef, useEffect, useState } from 'react';
import { useChat } from '../context/ChatContext';
import MessageContent from './MessageContent';
import MessageInput from './MessageInput';
import { Sparkles, Bot, AlertTriangle, FileText, Zap, BarChart2, Info, ChevronDown, Sun, TrendingUp } from 'lucide-react';
import { getUserName } from '../utils/nameMapping';
import '../styles/ChatArea.css';

// ── Agent Outputs Panel ───────────────────────────────────────────────────────
function AgentOutputCard({ output }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = output.result && output.result.length > 300;

  return (
    <div className="agent-output-card">
      <div className="agent-output-header">
        <Bot size={13} className="agent-output-icon" />
        <span className="agent-output-name">{output.agent_name}</span>
      </div>
      <p className={`agent-output-text ${expanded ? 'expanded' : ''}`}>
        {output.result || 'No output recorded.'}
      </p>
      {isLong && (
        <button className="agent-output-toggle" onClick={() => setExpanded(e => !e)}>
          {expanded ? 'Show less' : 'Show more'}
          <ChevronDown size={12} className={expanded ? 'rotated' : ''} />
        </button>
      )}
    </div>
  );
}

function AgentOutputsPanel({ outputs }) {
  return (
    <div className="agent-outputs-panel">
      <div className="demo-steps-title">Agent Outputs</div>
      <div className="agent-outputs-list">
        {outputs.map((o, i) => (
          <AgentOutputCard key={`${o.agent_name}-${i}`} output={o} />
        ))}
      </div>
    </div>
  );
}

const SUGGESTIONS = [
  {
    id: 1,
    title: "Explain my bill",
    desc: "Analyze your current charges",
    icon: <FileText size={24} />,
    prompt: "can you explain this months bill for me (july 2019)"
  },
  {
    id: 2,
    title: "Check outages",
    desc: "Check for area issues",
    icon: <Zap size={24} />,
    prompt: "is there an outage in my area"
  },
  {
    id: 3,
    title: "Comprehensive Review",
    desc: "Usage & bill analysis",
    icon: <BarChart2 size={24} />,
    prompt: "Can you analyze my energy usage for the last month and explain how it impacted my current bill?"
  },
  {
    id: 4,
    title: "Forecast Bill Shock",
    desc: "Predict upcoming bill shock",
    icon: <AlertTriangle size={24} />,
    prompt: "Am I at risk of bill shock for the current period (July 2019)?"
  },
  {
    id: 5,
    title: "Detect Anomalies",
    desc: "Find unusual spikes in usage",
    icon: <TrendingUp size={24} />,
    prompt: "Did customer CUST-1001 have any usage anomalies or spikes in July 2019?"
  },
  {
    id: 6,
    title: "Solar Calculations",
    desc: "Check solar credits and loss",
    icon: <Sun size={24} />,
    prompt: "Check solar underperformance and credit loss for customer CUST-1001 in July 2019."
  }
];

const NAMES_TO_CYCLE = [
  "Ryan", "Mary", "Alex", "Jordan", "Sarah", "Harish", "Michael", "Emma", 
  "David", "Jessica", "Daniel", "Emily", "Matthew", "Olivia", "James", 
  "Sophia", "Christopher", "Isabella", "Joshua", "Ava", "Andrew", "Mia", 
  "Joseph", "Charlotte", "William", "Amelia", "Anthony", "Harper", "Evelyn"
];

export default function DemoChatArea() {
  const { messages, error, customerId, demoEvents, demoStepsEnabled, isLoading, agentOutputs } = useChat();
  const bottomRef = useRef(null);

  const [currentNameText, setCurrentNameText] = useState("");
  const [nameIndex, setNameIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [simulatedPrompt, setSimulatedPrompt] = useState('');

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, error, demoEvents, simulatedPrompt]);

  // Typing effect for the greeting
  useEffect(() => {
    let timeout;
    const currentName = NAMES_TO_CYCLE[nameIndex];
    
    if (!isDeleting) {
      if (currentNameText.length < currentName.length) {
        timeout = setTimeout(() => {
          setCurrentNameText(currentName.slice(0, currentNameText.length + 1));
        }, 125);
      } else {
        timeout = setTimeout(() => {
          setIsDeleting(true);
        }, 1700);
      }
    } else {
      if (currentNameText.length > 0) {
        timeout = setTimeout(() => {
          setCurrentNameText(currentName.slice(0, currentNameText.length - 1));
        }, 85);
      } else {
        setIsDeleting(false);
        setNameIndex((prev) => (prev + 1) % NAMES_TO_CYCLE.length);
      }
    }
    
    return () => clearTimeout(timeout);
  }, [currentNameText, isDeleting, nameIndex]);

  const handleSuggestionClick = (prompt) => {
    if (!isLoading && !simulatedPrompt) {
      setSimulatedPrompt(prompt);
    }
  };

  return (
    <main className="chat-area">
      {messages.length === 0 && (
        <div className="demo-intro-banner">
          <Info size={20} className="intro-icon" />
          <div className="intro-content">
            <strong>The orchestrator is the brain for multi-agent systems.</strong> In this scenario, it acts as a customer service agent for an energy utilities company. I can help you understand your bills, check for local outages, and analyze your energy consumption. Try one of the scenarios below!
          </div>
        </div>
      )}

      {messages.length === 0 && !error ? (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
          <div className="messages-container" style={{ flex: 1, paddingBottom: 0 }}>
            <div className="welcome-screen">
              <h1>
                Hello,{' '}
                <span className="typing-container">
                  <span className="typing-text">{currentNameText}</span>
                  <span className="cursor"></span>
                </span>
              </h1>
              <p className="welcome-subtext">Welcome to the interactive demo. Select an option below to start.</p>
              
              <div className="suggestions-grid">
                {SUGGESTIONS.map((s) => (
                  <div key={s.id} className="suggestion-card" onClick={() => handleSuggestionClick(s.prompt)}>
                    <div className="suggestion-icon">{s.icon}</div>
                    <div className="suggestion-title">{s.title}</div>
                    <div className="suggestion-desc">{s.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="demo-input-area" style={{ maxWidth: '800px', margin: '0 auto', width: '100%', borderTop: 'none', background: 'transparent' }}>
            <MessageInput 
              simulatedPrompt={simulatedPrompt} 
              onSimulationComplete={() => setSimulatedPrompt('')} 
            />
          </div>
        </div>
      ) : (
          <div className="demo-two-column">
            {/* Left Column: Orchestrator Steps */}
            <div className="demo-left-column">
              <div className="demo-steps-panel">
                <div className="demo-steps-title">Orchestrator Activity</div>
                <div className="demo-steps-list">
                  {(!demoEvents || demoEvents.length === 0) && isLoading && (
                    <div className="demo-step-item status-running">
                      <span className="demo-step-stage">request</span>
                      <span className="demo-step-message">Initializing orchestration...</span>
                    </div>
                  )}
                  {(demoEvents || []).map((ev, idx) => (
                    <div key={`${ev.timestamp || "t"}-${idx}`} className={`demo-step-item status-${ev.status || "info"}`}>
                      <span className="demo-step-stage">{ev.stage || "stage"}</span>
                      <span className="demo-step-message">{ev.message || "Working..."}</span>
                    </div>
                  ))}
                  {(!demoEvents || demoEvents.length === 0) && !isLoading && (
                    <div className="demo-step-item status-info">
                      <span className="demo-step-stage">idle</span>
                      <span className="demo-step-message">Awaiting request...</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Agent Outputs panel — appears after response received */}
              {agentOutputs && agentOutputs.length > 0 && (
                <AgentOutputsPanel outputs={agentOutputs} />
              )}
            </div>

            {/* Right Column: Chat Interface */}
            <div className="demo-right-column">
              <div className="messages-list">
                {messages.map((msg, idx) => {
                  if (msg.role === 'user') {
                    return (
                      <div key={idx} className="message user">
                        <div className="bubble">{msg.content}</div>
                      </div>
                    );
                  } else if (msg.role === 'system') {
                    return (
                      <div key={idx} className={`message system ${msg.isError ? 'error' : ''}`}>
                        <div className="system-pill">
                          {msg.isError ? <AlertTriangle size={14} /> : <Bot size={14} />}
                          {msg.content}
                          {msg.agent && <span className="agent-tag">by {msg.agent}</span>}
                        </div>
                      </div>
                    );
                  } else {
                    return (
                      <div key={idx} className="message assistant">
                        <div className="avatar">
                          <Sparkles size={20} className="accent-icon" />
                        </div>
                        <div className="bubble">
                          <MessageContent content={msg.content} segments={msg.segments} />
                        </div>
                      </div>
                    );
                  }
                })}

                {isLoading && (
                  <div className="message assistant loading">
                    <div className="avatar">
                      <Sparkles size={20} className="accent-icon rotating" />
                    </div>
                    <div className="bubble">
                      <div className="orchestrator-thinking">
                        <span className="dot"></span>
                        <span className="dot"></span>
                        <span className="dot"></span>
                      </div>
                    </div>
                  </div>
                )}
                
                {error && (
                  <div className="message system error">
                    <div className="system-pill">
                      <AlertTriangle size={14} /> Error: {error}
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>

              <div className="demo-input-area">
                <div className="quick-replies-container">
                  {SUGGESTIONS.map((s) => (
                    <button 
                      key={s.id} 
                      className="quick-reply-pill" 
                      onClick={() => handleSuggestionClick(s.prompt)}
                      disabled={!!simulatedPrompt || isLoading}
                    >
                      {s.icon}
                      <span>{s.title}</span>
                    </button>
                  ))}
                </div>
                <MessageInput 
                  simulatedPrompt={simulatedPrompt} 
                  onSimulationComplete={() => setSimulatedPrompt('')} 
                />
              </div>
            </div>
          </div>
        )}
    </main>
  );
}
