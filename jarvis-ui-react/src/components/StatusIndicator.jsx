import React from 'react';

const TONES = {
  cyan: 'status--cyan',
  blue: 'status--blue',
  warn: 'status--warn',
  error: 'status--error',
  muted: 'status--muted',
};

const MAP = {
  connected: { tone: 'cyan', label: 'ONLINE' },
  ready: { tone: 'cyan', label: 'READY' },
  active: { tone: 'cyan', label: 'ACTIVE' },
  recording: { tone: 'cyan', label: 'CAPTURING' },
  checking: { tone: 'blue', label: 'VERIFYING' },
  processing: { tone: 'blue', label: 'PROCESSING' },
  executing: { tone: 'blue', label: 'EXECUTING' },
  idle: { tone: 'cyan', label: 'IDLE' },
  warning: { tone: 'warn', label: 'WARNING' },
  auth_error: { tone: 'error', label: 'AUTH ERROR' },
  disconnected: { tone: 'error', label: 'OFFLINE' },
  error: { tone: 'error', label: 'FAULT' },
  unavailable: { tone: 'muted', label: 'Not connected' },
  unknown: { tone: 'muted', label: 'UNKNOWN' },
  unsupported: { tone: 'muted', label: 'UNSUPPORTED' },
};

export function StatusIndicator({ status = 'unknown', label, compact = false, title }) {
  const meta = MAP[status] || MAP.unknown;
  return (
    <span className={`status ${TONES[meta.tone]} ${compact ? 'status--compact' : ''}`} title={title}>
      <span className="status__dot" aria-hidden="true" />
      <span>{label || meta.label}</span>
    </span>
  );
}
