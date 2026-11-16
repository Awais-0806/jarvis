import React, { useEffect, useState } from 'react';
import { Activity, Menu, RefreshCw, Settings, ShieldAlert } from 'lucide-react';
import { BACKEND_STATUS, NAV_VIEWS } from '../config/constants.js';
import { useJarvis } from '../context/JarvisContext.jsx';
import { formatDate, formatTime } from '../utils/formatters.js';
import { StatusIndicator } from './StatusIndicator.jsx';

export function TopBar({ onMenu }) {
  const { telemetry, isChecking, refreshTenders, coreState, voice, setActiveView } = useJarvis();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const voiceStatus = !voice.isSupported
    ? 'unsupported'
    : voice.permission === 'denied'
      ? 'error'
      : voice.state === 'recording'
        ? 'recording'
        : voice.state === 'transcribing'
          ? 'processing'
          : voice.permission === 'granted'
            ? 'ready'
            : 'unknown';

  const voiceLabel = !voice.isSupported
    ? 'VOICE UNSUPPORTED'
    : voice.permission === 'denied'
      ? 'MIC DENIED'
      : voice.state === 'recording'
        ? 'CAPTURING'
        : voice.state === 'transcribing'
          ? 'TRANSCRIBING'
          : voice.permission === 'granted'
            ? 'VOICE READY'
            : 'MIC STANDBY';

  const backendLabel =
    telemetry.status === BACKEND_STATUS.CONNECTED && telemetry.latencyMs !== null
      ? `ONLINE · ${telemetry.latencyMs}ms`
      : undefined;

  return (
    <header className="topbar">
      <div className="topbar__side">
        <button
          type="button"
          className="icon-btn topbar__menu"
          onClick={onMenu}
          aria-label="Open navigation"
        >
          <Menu size={18} />
        </button>

        <div className="brand">
          <span className="brand__emblem" aria-hidden="true">
            <span className="brand__ring" />
            <span className="brand__core" />
          </span>
          <span className="brand__text">
            <span className="brand__name">J.A.R.V.I.S.</span>
            <span className="brand__tagline">LOCAL COMMAND INTERFACE</span>
          </span>
        </div>
      </div>

      <div className="topbar__telemetry">
        <div className="chip">
          <span className="chip__label">CORE</span>
          <StatusIndicator
            status={coreState === 'ERROR' ? 'error' : coreState === 'IDLE' ? 'ready' : 'active'}
            label={coreState}
            compact
          />
        </div>
        <div className="chip">
          <span className="chip__label">CORE API</span>
          <StatusIndicator status={telemetry.status} label={backendLabel} compact />
        </div>
        <div className="chip chip--hide-sm">
          <span className="chip__label">VOICE</span>
          <StatusIndicator status={voiceStatus} label={voiceLabel} compact />
        </div>
      </div>

      <div className="topbar__side topbar__side--right">
        <div className="clock" aria-label="Local time">
          <span className="clock__time">{formatTime(now)}</span>
          <span className="clock__date">{formatDate(now)}</span>
        </div>

        <button
          type="button"
          className="icon-btn"
          onClick={() => refreshTenders()}
          disabled={isChecking}
          title="Re-check core connectivity"
          aria-label="Re-check core connectivity"
        >
          <RefreshCw size={15} className={isChecking ? 'spin' : ''} />
        </button>

        <button
          type="button"
          className="icon-btn"
          onClick={() => setActiveView(NAV_VIEWS.SETTINGS)}
          title="Application settings"
          aria-label="Application settings"
        >
          <Settings size={15} />
        </button>

        {telemetry.status === BACKEND_STATUS.AUTH_ERROR && (
          <span className="pill pill--error" title={telemetry.lastError || 'Token rejected'}>
            <ShieldAlert size={13} /> TOKEN
          </span>
        )}
        {telemetry.status === BACKEND_STATUS.CONNECTED && (
          <span className="pill pill--ok" title="Core API reachable">
            <Activity size={13} />
          </span>
        )}
      </div>
    </header>
  );
}
