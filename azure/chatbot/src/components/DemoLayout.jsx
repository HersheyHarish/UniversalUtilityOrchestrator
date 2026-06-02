import React from 'react';
import DemoHeader from './DemoHeader';
import DemoChatArea from './DemoChatArea';
import '../styles/Layout.css';

export default function DemoLayout() {
  return (
    <div className="app-layout">
      <div className="main-content">
        <DemoHeader />
        <DemoChatArea />
      </div>
    </div>
  );
}
