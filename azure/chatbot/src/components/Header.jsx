import React, { useState } from 'react';
import { useChat } from '../context/ChatContext';
import { User, Settings } from 'lucide-react';
import SettingsModal from './SettingsModal';
import { getUserName } from '../utils/nameMapping';
import '../styles/Header.css';

export default function Header() {
  const { customerId } = useChat();
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  return (
    <>
      <header className="app-header">
        <div className="header-brand">
          <h2>Universal Utility Orchestrator</h2>
        </div>
        <div className="header-actions">
          <div className="profile-pill">
            <User size={16} className="profile-icon" />
            <span className="profile-id" title={customerId}>
              {getUserName(customerId)}
            </span>
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
