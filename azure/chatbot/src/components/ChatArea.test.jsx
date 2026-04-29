import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ChatArea from './ChatArea';
import { useChat } from '../context/ChatContext';

// Mock MessageInput so we don't have to test it here
vi.mock('./MessageInput', () => ({
  default: () => <div data-testid="message-input-mock">Input</div>
}));

vi.mock('../context/ChatContext', () => ({
  useChat: vi.fn(),
}));

describe('ChatArea Component', () => {
  it('renders welcome screen when there are no messages', () => {
    useChat.mockReturnValue({ messages: [], error: null });
    render(<ChatArea />);
    expect(screen.getByText('Hello, User')).toBeInTheDocument();
  });

  it('renders messages correctly', () => {
    useChat.mockReturnValue({
      messages: [
        { role: 'user', content: 'Hello' },
        { role: 'system', content: 'Processing plan...' },
        { role: 'assistant', content: 'Hi there!' }
      ],
      error: null
    });

    render(<ChatArea />);
    expect(screen.getByText('Hello')).toBeInTheDocument();
    expect(screen.getByText(/Processing plan/)).toBeInTheDocument();
    expect(screen.getByText('Hi there!')).toBeInTheDocument();
  });

  it('renders error messages when API fails', () => {
    useChat.mockReturnValue({
      messages: [],
      error: '500 Internal Server Error'
    });

    render(<ChatArea />);
    expect(screen.getByText(/500 Internal Server Error/i)).toBeInTheDocument();
  });
});
