import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import Sidebar from './Sidebar';
import { useChat } from '../context/ChatContext';

// Mock the ChatContext hook
vi.mock('../context/ChatContext', () => ({
  useChat: vi.fn(),
}));

describe('Sidebar Component', () => {
  it('renders "No previous conversations" when session list is empty', () => {
    useChat.mockReturnValue({
      sessions: [],
      activeSessionId: null,
      setActiveSessionId: vi.fn(),
      startNewChat: vi.fn(),
    });

    render(<Sidebar />);
    expect(screen.getByText('No previous conversations.')).toBeInTheDocument();
  });

  it('renders a list of sessions and handles click', () => {
    const mockSetActiveSessionId = vi.fn();
    useChat.mockReturnValue({
      sessions: [
        { id: '1', user_message: 'First Chat' },
        { id: '2', user_message: 'Second Chat' },
      ],
      activeSessionId: '1',
      setActiveSessionId: mockSetActiveSessionId,
      startNewChat: vi.fn(),
    });

    render(<Sidebar />);
    
    expect(screen.getByText('First Chat')).toBeInTheDocument();
    expect(screen.getByText('Second Chat')).toBeInTheDocument();

    const secondChat = screen.getByText('Second Chat');
    fireEvent.click(secondChat);
    expect(mockSetActiveSessionId).toHaveBeenCalledWith('2');
  });
});
