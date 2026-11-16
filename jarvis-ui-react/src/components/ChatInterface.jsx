import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { AlertTriangle, Check, Copy, Loader2, MessageSquarePlus, Mic, X } from 'lucide-react';
import { useJarvis } from '../context/JarvisContext.jsx';
import { formatTimestamp } from '../utils/formatters.js';
import { CommandBar } from './CommandBar.jsx';

/** Only explicit schemes may become links; everything else is rendered as text. */
function safeUrl(url) {
  if (typeof url !== 'string') return '';
  const trimmed = url.trim();
  return /^(https?:|mailto:)/i.test(trimmed) ? trimmed : '';
}

const markdownComponents = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

const STAGE_LABEL = {
  submitting: 'Submitting directive to core…',
  polling: 'Core job running — polling for the reply…',
  finishing: 'Reply received, finalising…',
};

export function ChatInterface({ compact = false }) {
  const { chat } = useJarvis();
  const historyRef = useRef(null);
  const stickToBottom = useRef(true);
  const [copiedId, setCopiedId] = useState(null);

  const onScroll = () => {
    const node = historyRef.current;
    if (!node) return;
    stickToBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 90;
  };

  useEffect(() => {
    const node = historyRef.current;
    if (!node || !stickToBottom.current) return;
    node.scrollTop = node.scrollHeight;
  }, [chat.messages, chat.isProcessing]);

  const copy = async (message) => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedId(message.id);
      setTimeout(() => setCopiedId((current) => (current === message.id ? null : current)), 1500);
    } catch {
      // Clipboard permission is optional; nothing else to do here.
    }
  };

  return (
    <section className={`panel chat ${compact ? 'chat--compact' : ''}`}>
      <header className="panel__header">
        <div>
          <span className="eyebrow">CONVERSATION LINK</span>
          <h2 className="panel__title">Command Terminal</h2>
        </div>
        <div className="panel__actions">
          <span className="chip chip--id mono" title={chat.conversationId}>
            {chat.conversationId.slice(0, 16)}
          </span>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={chat.startNewConversation}
            title="Start a new conversation id"
          >
            <MessageSquarePlus size={13} />
            <span>New</span>
          </button>
        </div>
      </header>

      {chat.error && (
        <div className="alert alert--error" role="alert">
          <AlertTriangle size={14} />
          <span className="grow">{chat.error}</span>
          <button type="button" className="icon-btn" onClick={chat.clearError} aria-label="Dismiss error">
            <X size={13} />
          </button>
        </div>
      )}

      <div className="chat__history" ref={historyRef} onScroll={onScroll} aria-live="polite">
        {chat.messages.length === 0 ? (
          <div className="chat__empty">
            <p className="chat__empty-title">Terminal ready</p>
            <p className="chat__empty-copy">
              Every answer comes from a core job: the message is posted, then
              <code> GET /api/jobs/&lt;id&gt; </code>
              is polled until the core replies. Nothing is simulated.
            </p>
          </div>
        ) : (
          chat.messages.map((message) => {
            const mine = message.role === 'user';
            return (
              <article
                key={message.id}
                className={`message ${mine ? 'message--user' : 'message--jarvis'}`}
              >
                <header className="message__head">
                  <span className="message__author">
                    {mine ? 'OPERATOR' : 'J.A.R.V.I.S.'}
                    {message.source === 'voice' && (
                      <span className="message__tag" title="Sent from a transcription">
                        <Mic size={10} /> VOICE
                      </span>
                    )}
                  </span>
                  <span className="message__tools">
                    <span className="mono message__time">{formatTimestamp(message.timestamp)}</span>
                    {!mine && (
                      <button
                        type="button"
                        className="icon-btn"
                        onClick={() => copy(message)}
                        aria-label="Copy reply"
                        title="Copy reply"
                      >
                        {copiedId === message.id ? <Check size={12} /> : <Copy size={12} />}
                      </button>
                    )}
                  </span>
                </header>

                {mine ? (
                  <p className="message__text">{message.content}</p>
                ) : (
                  <div className="markdown">
                    <ReactMarkdown urlTransform={safeUrl} components={markdownComponents}>
                      {message.content}
                    </ReactMarkdown>
                  </div>
                )}
              </article>
            );
          })
        )}

        {chat.isProcessing && (
          <p className="chat__working" role="status">
            <Loader2 size={14} className="spin" />
            <span>{STAGE_LABEL[chat.stage] || 'Working…'}</span>
            {chat.activeJobId && <span className="mono chat__job">{chat.activeJobId.slice(0, 8)}</span>}
          </p>
        )}
      </div>

      <CommandBar />
    </section>
  );
}
