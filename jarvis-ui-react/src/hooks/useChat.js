import { useCallback, useEffect, useRef, useState } from 'react';
import { sendChatMessage } from '../api/chat.js';
import { pollJobUntilComplete } from './useJobPolling.js';
import { createConversationId, createMessageId } from '../utils/conversation.js';
import { MAX_MESSAGE_CHARS } from '../config/constants.js';

/**
 * Owns one conversation: id, messages and the single in-flight job.
 *
 * Core allows one job at a time, so a second send is rejected locally instead of provoking
 * a 503. Aborting stops polling; the backend job keeps running and is simply not awaited.
 */
export function useChat() {
  const [conversationId, setConversationId] = useState(createConversationId);
  const [messages, setMessages] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [stage, setStage] = useState(null);
  const [activeJobId, setActiveJobId] = useState(null);
  const [error, setError] = useState(null);

  const controllerRef = useRef(null);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(() => () => cancel(), [cancel]);

  const sendMessage = useCallback(
    async (rawText, { source = 'text' } = {}) => {
      const text = typeof rawText === 'string' ? rawText.trim() : '';
      if (!text) return false;
      if (text.length > MAX_MESSAGE_CHARS) {
        setError(`Messages are limited to ${MAX_MESSAGE_CHARS} characters by the core.`);
        return false;
      }
      if (controllerRef.current) return false;

      setError(null);
      setMessages((current) => [
        ...current,
        {
          id: createMessageId(),
          role: 'user',
          content: text,
          source,
          timestamp: new Date().toISOString(),
        },
      ]);

      const controller = new AbortController();
      controllerRef.current = controller;
      setIsProcessing(true);
      setStage('submitting');

      try {
        const job = await sendChatMessage({
          message: text,
          conversationId,
          signal: controller.signal,
        });

        setActiveJobId(job.jobId);
        setStage('polling');

        const reply = await pollJobUntilComplete(job.jobId, {
          signal: controller.signal,
          onStatus: ({ status }) => setStage(status === 'running' ? 'polling' : 'finishing'),
        });

        setMessages((current) => [
          ...current,
          {
            id: createMessageId(),
            role: 'assistant',
            content: reply,
            jobId: job.jobId,
            timestamp: new Date().toISOString(),
          },
        ]);
        return true;
      } catch (err) {
        if (err?.code === 'ABORTED') {
          setError('Cancelled. The backend may still be finishing this job.');
        } else {
          setError(err?.message || 'The request failed.');
        }
        return false;
      } finally {
        controllerRef.current = null;
        setIsProcessing(false);
        setStage(null);
        setActiveJobId(null);
      }
    },
    [conversationId]
  );

  const startNewConversation = useCallback(() => {
    cancel();
    setConversationId(createConversationId());
    setMessages([]);
    setError(null);
    setIsProcessing(false);
    setStage(null);
    setActiveJobId(null);
  }, [cancel]);

  const clearError = useCallback(() => setError(null), []);

  return {
    conversationId,
    messages,
    isProcessing,
    stage,
    activeJobId,
    error,
    sendMessage,
    cancel,
    startNewConversation,
    clearError,
  };
}
