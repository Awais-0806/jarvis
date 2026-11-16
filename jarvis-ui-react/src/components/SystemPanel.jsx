import React from 'react';
import { Activity, BatteryCharging, Cpu, HardDrive, Mic, RefreshCw } from 'lucide-react';
import { BACKEND_STATUS } from '../config/constants.js';
import { useJarvis } from '../context/JarvisContext.jsx';
import { formatDuration, formatPercent, formatTimestamp } from '../utils/formatters.js';
import { AudioWaveform } from './AudioWaveform.jsx';
import { StatusIndicator } from './StatusIndicator.jsx';

export function SystemPanel() {
  const { telemetry, isChecking, refreshTenders, voice, chat, host } = useJarvis();

  const stats = host.stats;

  const micState = !voice.isSupported
    ? 'Unsupported'
    : voice.permission === 'denied'
      ? 'Permission denied'
      : voice.permission === 'granted'
        ? 'Authorised'
        : 'Prompt required';

  const voiceState =
    voice.state === 'recording'
      ? `Recording ${formatDuration(voice.durationSec)}`
      : voice.state === 'requesting'
        ? 'Requesting microphone…'
        : voice.state === 'transcribing'
          ? 'Transcribing…'
          : 'Standby';

  return (
    <div className="stack">
      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">DIAGNOSTICS</span>
            <h2 className="panel__title">System Overview</h2>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={() => refreshTenders()}
            disabled={isChecking}
            title="Re-check core connectivity"
            aria-label="Re-check core connectivity"
          >
            <RefreshCw size={14} className={isChecking ? 'spin' : ''} />
          </button>
        </header>

        <dl className="metrics">
          <div className="metrics__row">
            <dt>
              <Activity size={13} /> Core API
            </dt>
            <dd>
              <StatusIndicator status={telemetry.status} compact />
            </dd>
          </div>
          <div className="metrics__row">
            <dt>API latency</dt>
            <dd className="mono">
              {telemetry.status === BACKEND_STATUS.CONNECTED && telemetry.latencyMs !== null
                ? `${telemetry.latencyMs} ms`
                : 'Not connected'}
            </dd>
          </div>
          <div className="metrics__row">
            <dt>
              <Cpu size={13} /> CPU (laptop)
            </dt>
            <dd className="mono">
              {stats && stats.cpuPercent !== null ? formatPercent(stats.cpuPercent) : 'Not fetched'}
            </dd>
          </div>
          <div className="metrics__row">
            <dt>
              <HardDrive size={13} /> Memory (laptop)
            </dt>
            <dd className="mono">
              {stats && stats.ramPercent !== null ? formatPercent(stats.ramPercent) : 'Not fetched'}
            </dd>
          </div>
          <div className="metrics__row">
            <dt>
              <BatteryCharging size={13} /> Battery
            </dt>
            <dd className="mono">
              {stats && stats.batteryPercent !== null ? formatPercent(stats.batteryPercent) : '—'}
            </dd>
          </div>
        </dl>

        {stats ? (
          <p className="footnote mono">
            {stats.hostname || 'host'} · collected {formatTimestamp(stats.collectedAt)}
          </p>
        ) : (
          <p className="footnote">
            Laptop metrics come from the host bridge. Read them in Remote Control.
          </p>
        )}

        {telemetry.lastError && (
          <p className="alert alert--error" role="status">
            {telemetry.lastError}
          </p>
        )}
      </section>

      <section className="panel">
        <header className="panel__header">
          <div>
            <span className="eyebrow">AUDIO SUBSYSTEM</span>
            <h2 className="panel__title">Voice Monitor</h2>
          </div>
          <Mic size={15} className="accent" />
        </header>

        <dl className="metrics">
          <div className="metrics__row">
            <dt>Microphone</dt>
            <dd className="mono">{micState}</dd>
          </div>
          <div className="metrics__row">
            <dt>Capture state</dt>
            <dd className="mono">{voiceState}</dd>
          </div>
          <div className="metrics__row">
            <dt>Active job</dt>
            <dd className="mono">{chat.activeJobId ? chat.activeJobId.slice(0, 12) : 'Idle'}</dd>
          </div>
        </dl>

        <div className="waveform-box">
          <div className="waveform-box__head">
            <span>INPUT SPECTRUM</span>
            <span className="mono">{voice.state === 'recording' ? 'LIVE' : 'STANDBY'}</span>
          </div>
          <AudioWaveform bars={voice.bars} active={voice.state === 'recording'} />
        </div>

        {voice.lastTranscript && (
          <div className="transcript">
            <span className="eyebrow">LAST TRANSCRIPT</span>
            <p>{voice.lastTranscript}</p>
          </div>
        )}
      </section>
    </div>
  );
}
