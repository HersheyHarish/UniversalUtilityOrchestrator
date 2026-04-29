import React, { useState } from 'react';
import { useTheme } from '../context/ThemeContext';
import { useChat } from '../context/ChatContext';
import { X, Moon, Sun, Monitor, Trash2, Code } from 'lucide-react';
import '../styles/SettingsModal.css';

export default function SettingsModal({ isOpen, onClose }) {
  const { theme, setTheme } = useTheme();
  const { customerId, startNewChat } = useChat();
  const [activeTab, setActiveTab] = useState('user');

  if (!isOpen) return null;

  const handleClearData = () => {
    if (confirm("Are you sure? This will clear your local ID and reset the current session.")) {
      localStorage.removeItem('demo_customer_id');
      startNewChat();
      window.location.reload();
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Settings</h2>
          <button className="close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        
        <div className="modal-body">
          <div className="settings-sidebar">
            <button 
              className={`tab-btn ${activeTab === 'user' ? 'active' : ''}`}
              onClick={() => setActiveTab('user')}
            >
              <Monitor size={16} /> User
            </button>
            <button 
              className={`tab-btn ${activeTab === 'dev' ? 'active' : ''}`}
              onClick={() => setActiveTab('dev')}
            >
              <Code size={16} /> Developer
            </button>
          </div>
          
          <div className="settings-content">
            {activeTab === 'user' && (
              <div className="settings-section">
                <h3>Appearance</h3>
                <div className="theme-options">
                  <button 
                    className={`theme-btn ${theme === 'light' ? 'active' : ''}`}
                    onClick={() => setTheme('light')}
                  >
                    <Sun size={20} /> Light
                  </button>
                  <button 
                    className={`theme-btn ${theme === 'dark' ? 'active' : ''}`}
                    onClick={() => setTheme('dark')}
                  >
                    <Moon size={20} /> Dark
                  </button>
                </div>
              </div>
            )}
            
            {activeTab === 'dev' && (
              <div className="settings-section">
                <h3>Developer Tools</h3>
                <div className="dev-info">
                  <label>Current Customer ID:</label>
                  <code className="code-block">{customerId}</code>
                </div>
                
                <div className="danger-zone">
                  <h4>Danger Zone</h4>
                  <button className="danger-btn" onClick={handleClearData}>
                    <Trash2 size={16} /> Clear Local Data & Reset
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
