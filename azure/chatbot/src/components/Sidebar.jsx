import React from 'react';
import { useChat } from '../context/ChatContext';
import { MessageSquare, Plus } from 'lucide-react';
import '../styles/Sidebar.css';

export default function Sidebar() {
  const { sessions, activeSessionId, setActiveSessionId, startNewChat } = useChat();

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <button className="new-chat-btn" onClick={startNewChat}>
          <Plus size={16} /> New Chat
        </button>
      </div>
      
      <div className="sidebar-content">
        <h3 className="section-title">Recent</h3>
        {sessions.length === 0 ? (
          <p className="no-sessions">No previous conversations.</p>
        ) : (
          <ul className="session-list">
            {sessions.map((session) => (
              <li 
                key={session.id} 
                className={`session-item ${activeSessionId === session.id ? 'active' : ''}`}
                onClick={() => setActiveSessionId(session.id)}
              >
                <MessageSquare size={16} className="session-icon" />
                <span className="session-title">
                  {session.user_message || "New Conversation"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
