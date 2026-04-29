import React from 'react';
import { ChatProvider } from './context/ChatContext';
import { ThemeProvider } from './context/ThemeContext';
import Layout from './components/Layout';
import './styles/globals.css';

function App() {
  return (
    <ThemeProvider>
      <ChatProvider>
        <Layout />
      </ChatProvider>
    </ThemeProvider>
  );
}

export default App;
