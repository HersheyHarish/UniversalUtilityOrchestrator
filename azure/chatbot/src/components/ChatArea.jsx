import React, { useRef, useEffect } from 'react';
import { useChat } from '../context/ChatContext';
import MessageInput from './MessageInput';
import { Sparkles, Bot, AlertTriangle } from 'lucide-react';
import { getUserName } from '../utils/nameMapping';
import '../styles/ChatArea.css';

export default function ChatArea() {
  const { messages, error, customerId } = useChat();
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, error]);

  return (
    <main className="chat-area">
      <div className="messages-container">
        {messages.length === 0 && !error ? (
          <div className="welcome-screen">
            <h1>Hello, {getUserName(customerId)}</h1>
            <p className="welcome-subtext">How can I help you today?</p>
          </div>
        ) : (
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
                    <div className="bubble">{msg.content}</div>
                  </div>
                );
              }
            })}
            
            {error && (
              <div className="message system error">
                <div className="system-pill">
                  <AlertTriangle size={14} /> Error: {error}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
      <MessageInput />
    </main>
  );
}
