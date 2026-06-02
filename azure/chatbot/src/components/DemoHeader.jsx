import React, { useState, useEffect, useRef } from 'react';
import { Settings, Bot, ChevronDown } from 'lucide-react';
import SettingsModal from './SettingsModal';
import { useChat } from '../context/ChatContext';
import '../styles/Header.css';

export default function DemoHeader() {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [agentsOpen, setAgentsOpen] = useState(false);
  const { activeAgents = [] } = useChat();
  const popoverRef = useRef(null);

  // Close popover on outside click
  useEffect(() => {
    if (!agentsOpen) return;
    const handler = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setAgentsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [agentsOpen]);

  return (
    <>
      <header className="app-header">
        <div className="header-brand">
          <h2>Universal Utility Orchestrator</h2>
          <span className="header-subtitle">Service Agent Scenario</span>
        </div>

        <div className="header-actions">
          {/* Agents popover */}
          <div className="agents-popover-anchor" ref={popoverRef}>
            <button
              className="agents-btn"
              onClick={() => setAgentsOpen(o => !o)}
              aria-expanded={agentsOpen}
            >
              <Bot size={14} />
              <span>Agents{activeAgents.length > 0 ? ` (${activeAgents.length})` : ''}</span>
              <ChevronDown size={12} className={`agents-chevron ${agentsOpen ? 'open' : ''}`} />
            </button>

            {agentsOpen && (
              <div className="agents-popover">
                <div className="agents-popover-header">
                  Active Agents
                  <span className="agents-count-badge">{activeAgents.length}</span>
                </div>
                {activeAgents.length === 0 && (
                  <div className="agent-row agent-row-empty">
                    No agents found — is the orchestrator running?
                  </div>
                )}
                {activeAgents.map((agent, i) => (
                  <div key={i} className="agent-row">
                    <span className="agent-dot" />
                    <div className="agent-row-info">
                      <span className="agent-row-name">{agent.name}</span>
                      {agent.description && (
                        <span className="agent-row-desc">{agent.description}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Orchestrator status */}
          <div className="orch-status">
            <div className="orch-status-dot connected" />
            <span>Orchestrator Connected</span>
          </div>

          <button className="settings-btn" onClick={() => setIsSettingsOpen(true)}>
            <Settings size={20} />
          </button>
        </div>
      </header>

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </>
  );
}
