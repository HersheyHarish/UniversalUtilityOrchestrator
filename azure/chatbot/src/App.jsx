import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { ChatProvider } from './context/ChatContext';
import { ThemeProvider } from './context/ThemeContext';
import Layout from './components/Layout';
import DemoLayout from './components/DemoLayout';
import './styles/globals.css';

function App() {
  return (
    <ThemeProvider>
      <ChatProvider>
        <Routes>
          <Route path="/" element={<Layout />} />
          <Route path="/demo" element={<DemoLayout />} />
        </Routes>
      </ChatProvider>
    </ThemeProvider>
  );
}

export default App;
