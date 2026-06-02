import React, { useState, useEffect } from 'react';
import { useChat } from '../context/ChatContext';
import { SendHorizontal } from 'lucide-react';
import '../styles/MessageInput.css';

export default function MessageInput({ simulatedPrompt, onSimulationComplete }) {
  const [text, setText] = useState('');
  const { sendMessage, isLoading } = useChat();

  const sendMessageRef = React.useRef(sendMessage);
  React.useEffect(() => { sendMessageRef.current = sendMessage; }, [sendMessage]);
  
  const onSimCompleteRef = React.useRef(onSimulationComplete);
  React.useEffect(() => { onSimCompleteRef.current = onSimulationComplete; }, [onSimulationComplete]);

  useEffect(() => {
    if (!simulatedPrompt) return;
    
    let currentIndex = 0;
    setText('');
    
    const intervalId = setInterval(() => {
      currentIndex++;
      setText(simulatedPrompt.slice(0, currentIndex));
      
      if (currentIndex >= simulatedPrompt.length) {
        clearInterval(intervalId);
        setTimeout(() => {
          sendMessageRef.current(simulatedPrompt);
          setText('');
          if (onSimCompleteRef.current) onSimCompleteRef.current();
        }, 300);
      }
    }, 30);
    
    return () => clearInterval(intervalId);
  }, [simulatedPrompt]);

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
          disabled={isLoading || !!simulatedPrompt}
        />
        <button type="submit" className="send-btn" disabled={!text.trim() || isLoading || !!simulatedPrompt}>
          {isLoading ? <span className="spinner" /> : <SendHorizontal size={18} />}
        </button>
      </form>
      <div className="input-footer">Universal Utility Orchestrator can make mistakes. Consider verifying important information. Demo Purposes Only.</div>
    </div>
  );
}
