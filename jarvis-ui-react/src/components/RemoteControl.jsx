import React from 'react';
import {
  AlertTriangle,
  BatteryCharging,
  Camera,
  CheckCircle2,
  Cpu,
  HardDrive,
  Loader2,
  MonitorSmartphone,
  RefreshCw,
  TerminalSquare,
  X,
} from 'lucide-react';
import { useJarvis } from '../context/JarvisContext.jsx';
import { formatPercent, formatTimestamp } from '../utils/formatters.js';

function Metric({ icon: Icon, label, value, detail, percent }) {
  const hasPercent = typeof percent === 'number';
  return (
    <div className="metric">
      <div className="metric__head">
        <span className="metric__label">
          <Icon size={13} /> {label}
        </span>
        <span className="metric__value mono">{value}</span>
      </div>
      <div className="meter" role="presentation">
        <span
          className={`meter__fill ${hasPercent && percent >= 85 ? 'meter__fill--warn' : ''}`}
          style={{ width: hasPercent ? `${Math.max(2, Math.min(100, percent))}%` : '0%' }}
        />
      </div>
      {detail && <p className="metric__detail mono">{detail}</p>}
    </div>
  );
}

export function RemoteControl() {
  const { host } = useJarvis();
  const { screenshot, stats, pending, error, notice } = host;

  const busy = pending.screenshot || pending.openApp || pending.stats;

  return (
    <div className="remote">
      <section className="panel remote__console">
        <header className="panel__header">
          <div>
            <span className="eyebrow">HOST BRIDGE · WINDOWS LAPTOP</span>
            <h2 className="panel__title">
              <MonitorSmartphone size={16} className="accent" /> Remote Control
            </h2>
          </div>
          <span className={`pill ${busy ? 'pill--busy' : 'pill--ok'}`}>
            {busy ? 'LINK ACTIVE' : 'READY'}
          </span>
        </header>

        <p className="remote__lede">
          These actions are proxied by the core to <code>host_bridge.py</code> running on the
          Windows host. Nothing is simulated: when the bridge is not running the buttons report the
          error instead.
        </p>

        <div className="remote__actions">
          <button
            type="button"
            className="btn btn--cyan remote__action"
            onClick={host.capture}
            disabled={pending.screenshot}
            aria-busy={pending.screenshot}
          >
            {pending.screenshot ? <Loader2 size={16} className="spin" /> : <Camera size={16} />}
            <span>{pending.screenshot ? 'Capturing…' : 'Take Screenshot'}</span>
          </button>

          <button
            type="button"
            className="btn btn--primary remote__action"
            onClick={host.launchEditor}
            disabled={pending.openApp}
            aria-busy={pending.openApp}
          >
            {pending.openApp ? <Loader2 size={16} className="spin" /> : <TerminalSquare size={16} />}
            <span>{pending.openApp ? 'Launching…' : 'Open VS Code'}</span>
          </button>

          <button
            type="button"
            className="btn btn--ghost remote__action"
            onClick={host.readStats}
            disabled={pending.stats}
            aria-busy={pending.stats}
          >
            {pending.stats ? <Loader2 size={16} className="spin" /> : <Cpu size={16} />}
            <span>{pending.stats ? 'Reading…' : 'System Stats'}</span>
          </button>
        </div>

        <div aria-live="polite" className="remote__messages">
          {notice && (
            <div className="alert alert--ok">
              <CheckCircle2 size={14} />
              <span className="grow">{notice}</span>
              <button type="button" className="icon-btn" onClick={host.clearMessages} aria-label="Dismiss">
                <X size={13} />
              </button>
            </div>
          )}

          {error && (
            <div className="alert alert--error" role="alert">
              <AlertTriangle size={14} />
              <span className="grow">{error}</span>
              <button type="button" className="icon-btn" onClick={host.clearMessages} aria-label="Dismiss">
                <X size={13} />
              </button>
            </div>
          )}
        </div>
      </section>

      <div className="remote__grid">
        <section className="panel remote__screen">
          <header className="panel__header">
            <div>
              <span className="eyebrow">SCREEN CAPTURE</span>
              <h2 className="panel__title">Laptop display</h2>
            </div>
            {screenshot && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={host.capture}
                disabled={pending.screenshot}
              >
                <RefreshCw size={12} className={pending.screenshot ? 'spin' : ''} />
                <span>Recapture</span>
              </button>
            )}
          </header>

          {pending.screenshot && !screenshot ? (
            <div className="state-box state-box--tall" role="status">
              <Loader2 size={18} className="spin accent" />
              <span>Requesting a screenshot from the host bridge…</span>
            </div>
          ) : screenshot ? (
            <figure className="capture">
              <img
                src={screenshot.dataUrl}
                alt={`Laptop screen captured ${screenshot.capturedAt || 'just now'}`}
                className="capture__image"
              />
              <figcaption className="capture__meta mono">
                {screenshot.width && screenshot.height
                  ? `${screenshot.width}×${screenshot.height}`
                  : 'size not reported'}
                {screenshot.capturedAt ? ` · ${formatTimestamp(screenshot.capturedAt)}` : ''}
                {screenshot.monitor ? ` · monitor ${screenshot.monitor}` : ''}
              </figcaption>
            </figure>
          ) : (
            <div className="state-box state-box--tall">
              <Camera size={20} className="muted" />
              <span>No capture yet. Use “Take Screenshot” to fetch the laptop display.</span>
            </div>
          )}
        </section>

        <section className="panel remote__stats">
          <header className="panel__header">
            <div>
              <span className="eyebrow">HOST TELEMETRY</span>
              <h2 className="panel__title">System health</h2>
            </div>
            {stats && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={host.readStats}
                disabled={pending.stats}
              >
                <RefreshCw size={12} className={pending.stats ? 'spin' : ''} />
                <span>Refresh</span>
              </button>
            )}
          </header>

          {stats ? (
            <>
              <div className="metrics-grid">
                <Metric
                  icon={Cpu}
                  label="CPU"
                  value={stats.cpuPercent !== null ? formatPercent(stats.cpuPercent) : 'Not reported'}
                  percent={stats.cpuPercent ?? undefined}
                  detail={stats.cpuCores ? `${stats.cpuCores} logical cores` : null}
                />
                <Metric
                  icon={HardDrive}
                  label="RAM"
                  value={stats.ramPercent !== null ? formatPercent(stats.ramPercent) : 'Not reported'}
                  percent={stats.ramPercent ?? undefined}
                  detail={
                    stats.ramUsedGb !== null && stats.ramTotalGb !== null
                      ? `${stats.ramUsedGb} GB of ${stats.ramTotalGb} GB`
                      : stats.ramUsedGb !== null
                        ? `${stats.ramUsedGb} GB in use`
                        : null
                  }
                />
                <Metric
                  icon={BatteryCharging}
                  label="Battery"
                  value={
                    stats.batteryPercent !== null
                      ? formatPercent(stats.batteryPercent)
                      : 'Not reported'
                  }
                  percent={stats.batteryPercent ?? undefined}
                  detail={
                    stats.batteryPlugged === null
                      ? 'No battery sensor'
                      : stats.batteryPlugged
                        ? 'Plugged in'
                        : 'On battery'
                  }
                />
              </div>

              <p className="footnote mono">
                {[stats.hostname, stats.platform].filter(Boolean).join(' · ') || 'Host identity not reported'}
                {stats.collectedAt ? ` · collected ${formatTimestamp(stats.collectedAt)}` : ''}
              </p>
            </>
          ) : (
            <div className="state-box state-box--tall">
              <Cpu size={20} className="muted" />
              <span>No readings yet. Use “System Stats” to query the laptop.</span>
            </div>
          )}
        </section>
      </div>

      <section className="panel remote__help">
        <span className="eyebrow">BRIDGE REQUIREMENTS</span>
        <ul className="bullets">
          <li>
            Start the bridge on Windows: <code>python host_bridge.py</code> (listens on port 9090).
          </li>
          <li>
            Core reaches it through <code>HOST_BRIDGE_URL</code>; the compose <code>hostlink</code>{' '}
            network and <code>host.docker.internal</code> provide the route.
          </li>
          <li>
            The shared <code>host_token</code> secret must exist, or core returns 503 and the bridge
            rejects the call.
          </li>
          <li>Open VS Code sends <code>{'{"app_name":"code"}'}</code> to <code>/api/host/open_app</code>.</li>
        </ul>
      </section>
    </div>
  );
}
