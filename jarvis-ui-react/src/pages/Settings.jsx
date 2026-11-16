import React from 'react';
import { Cpu, HardDrive, Lock, Mic, RefreshCw, ShieldCheck, TerminalSquare } from 'lucide-react';
import { StatusIndicator } from '../components/StatusIndicator.jsx';
import { useJarvis } from '../context/JarvisContext.jsx';
import { VOICE_UPLOAD_FIELD } from '../config/constants.js';

function Row({ label, children }) {
  return (
    <div className="metrics__row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function Settings() {
  const { telemetry, isChecking, refreshTenders, voice, chat, prefersReducedMotion } = useJarvis();

  return (
    <div className="layout-settings">
      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">CONNECTIVITY &amp; PROXY</span>
            <h2 className="panel__title">Backend integration</h2>
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => refreshTenders()}
            disabled={isChecking}
          >
            <RefreshCw size={12} className={isChecking ? 'spin' : ''} />
            <span>Test connection</span>
          </button>
        </header>

        <dl className="metrics">
          <Row label="Browser API base">
            <span className="mono">/api (same origin)</span>
          </Row>
          <Row label="Core API">
            <StatusIndicator status={telemetry.status} compact />
          </Row>
          <Row label="Last verified">
            <span className="mono">{telemetry.lastCheckedAt ? telemetry.lastCheckedAt.slice(11, 19) : '—'}</span>
          </Row>
          <Row label="Bearer token">
            <span className="mono">Injected by proxy · never in the bundle</span>
          </Row>
          <Row label="Conversation id">
            <span className="mono">{chat.conversationId}</span>
          </Row>
          <Row label="Voice form field">
            <span className="mono">{VOICE_UPLOAD_FIELD}</span>
          </Row>
        </dl>

        {telemetry.lastError && <p className="alert alert--error">{telemetry.lastError}</p>}
      </section>

      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">SECURITY POSTURE</span>
            <h2 className="panel__title">Local-first guarantees</h2>
          </div>
          <ShieldCheck size={16} className="accent" />
        </header>

        <ul className="bullets">
          <li>No cloud AI calls: every request goes to your core through the same-origin proxy.</li>
          <li>No token in JavaScript, localStorage or sessionStorage.</li>
          <li>No analytics, telemetry beacons or external fonts.</li>
          <li>Markdown links are restricted to http, https and mailto; raw HTML is never rendered.</li>
          <li>Approvals are read-only — the UI cannot approve, reject or send anything.</li>
          <li>
            Motion follow <code>prefers-reduced-motion</code>
            {prefersReducedMotion ? ' (currently active)' : ''}.
          </li>
        </ul>
      </section>

      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">BROWSER CAPABILITIES</span>
            <h2 className="panel__title">Audio diagnostics</h2>
          </div>
          <Mic size={16} className="accent" />
        </header>

        <dl className="metrics">
          <Row label="MediaRecorder">
            <span className="mono">{voice.isSupported ? 'Available' : 'Unsupported'}</span>
          </Row>
          <Row label="Microphone permission">
            <span className="mono">{voice.permission}</span>
          </Row>
          <Row label="Capture state">
            <span className="mono">{voice.state}</span>
          </Row>
          <Row label="Secure context">
            <span className="mono">
              {typeof window !== 'undefined' && window.isSecureContext ? 'Yes' : 'No'}
            </span>
          </Row>
        </dl>

        {!voice.isSupported && (
          <p className="footnote">
            Microphone capture needs a secure context (https or localhost) and a Chromium/Firefox
            browser.
          </p>
        )}
      </section>

      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">SUBSYSTEM STATUS</span>
            <h2 className="panel__title">Backend contracts</h2>
          </div>
          <TerminalSquare size={16} className="accent" />
        </header>

        <dl className="metrics">
          <Row label="Chat + jobs">
            <span className="mono ok">POST /chat · GET /jobs/&lt;id&gt;</span>
          </Row>
          <Row label="Tenders">
            <span className="mono ok">GET /api/global-tenders</span>
          </Row>
          <Row label="Pitch jobs">
            <span className="mono ok">POST /global-tenders/&lt;id&gt;/pitch</span>
          </Row>
          <Row label="Voice">
            <span className="mono ok">POST /api/voice/transcribe</span>
          </Row>
          <Row label="Host control">
            <span className="mono ok">GET/POST /api/host/*</span>
          </Row>
          <Row label="Approvals">
            <span className="mono muted">Not implemented by core (404)</span>
          </Row>
        </dl>

        <div className="alert alert--warn">
          <Lock size={14} />
          <span className="grow">
            Approve/reject endpoints do not exist. A missing CPU/RAM endpoint is covered by the
            host bridge instead, so those readings are real when the bridge is running.
          </span>
        </div>
      </section>

      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">REFERENCE</span>
            <h2 className="panel__title">How requests are routed</h2>
          </div>
          <Cpu size={16} className="accent" />
        </header>

        <dl className="metrics">
          <Row label="POST /api/chat">
            <span className="mono">→ core /chat</span>
          </Row>
          <Row label="GET /api/jobs/&lt;id&gt;">
            <span className="mono">→ core /jobs/&lt;id&gt;</span>
          </Row>
          <Row label="POST /api/global-tenders/&lt;id&gt;/pitch">
            <span className="mono">→ core /global-tenders/&lt;id&gt;/pitch</span>
          </Row>
          <Row label="Other /api/*">
            <span className="mono">→ core unchanged</span>
          </Row>
        </dl>

        <p className="footnote">
          The mapping lives in <code>vite.config.js</code> for development and in
          <code> nginx.conf</code> for the container, because core exposes chat and jobs without the
          <code> /api</code> prefix.
        </p>
      </section>

      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">RESOURCES</span>
            <h2 className="panel__title">Diagnostics</h2>
          </div>
          <HardDrive size={16} className="accent" />
        </header>
        <dl className="metrics">
          <Row label="Active job">
            <span className="mono">{chat.activeJobId || 'None'}</span>
          </Row>
          <Row label="Messages this session">
            <span className="mono">{chat.messages.length}</span>
          </Row>
        </dl>
      </section>
    </div>
  );
}
