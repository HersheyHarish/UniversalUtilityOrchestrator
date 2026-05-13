import React, { useState, useRef, useEffect } from 'react';
import { sendChatMessage } from '../api/client';

export default function Chatbot() {
  const [messages, setMessages] = useState([
    { role: 'system', content: 'Hello! I am your Universal Utility assistant. How can I help you today?' }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const result = await sendChatMessage(userMessage, sessionId);
      if (result.session_id && !sessionId) {
        setSessionId(result.session_id);
      }
      setMessages(prev => [
        ...prev, 
        { 
          role: 'system', 
          content: result.response,
          metadata: {
            agents: result.agents_used,
            steps: result.steps_completed
          }
        }
      ]);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'error', content: `Sorry, I encountered an error: ${err.message}` }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="chatbot-card card">
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <div className="message-bubble">
              <p>{msg.content}</p>
              {msg.metadata && msg.metadata.agents?.length > 0 && (
                <div className="message-metadata">
                  <span>Powered by: {msg.metadata.agents.join(', ')}</span>
                  <span>({msg.metadata.steps} steps)</span>
                </div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="chat-message system">
            <div className="message-bubble loading-bubble">
              <span className="dot"></span>
              <span className="dot"></span>
              <span className="dot"></span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      
      <form className="chat-input-area" onSubmit={handleSubmit}>
        <input 
          type="text" 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your bill, outages, or usage..."
          disabled={isLoading}
          className="form-input chat-input"
        />
        <button type="submit" disabled={isLoading || !input.trim()} className="btn btn-primary send-btn">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </form>
    </div>
  );
}
