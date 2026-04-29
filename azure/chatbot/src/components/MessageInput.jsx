import React, { useState } from 'react';
import { useChat } from '../context/ChatContext';
import { SendHorizontal } from 'lucide-react';
import '../styles/MessageInput.css';

export default function MessageInput() {
  const [text, setText] = useState('');
  const { sendMessage, isLoading } = useChat();

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!text.trim() || isLoading) return;
    sendMessage(text);
    setText('');
  };

  return (
    <div className="input-container">
      <form onSubmit={handleSubmit} className="message-form">
        <input
          type="text"
          className="message-input"
          placeholder="Ask Universal Agent..."
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={isLoading}
        />
        <button type="submit" className="send-btn" disabled={!text.trim() || isLoading}>
          {isLoading ? <span className="spinner" /> : <SendHorizontal size={18} />}
        </button>
      </form>
      <div className="input-footer">Universal Utility Orchestrator can make mistakes. Consider verifying important information. Demo Purposes Only.</div>
    </div>
  );
}
