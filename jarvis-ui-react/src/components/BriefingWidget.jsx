import React from 'react';
import { AlertTriangle, CalendarClock, RefreshCw, Sparkles } from 'lucide-react';
import { useJarvis } from '../context/JarvisContext.jsx';

function formatGeneratedAt(value) {
  if (!value) return 'never';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

export function BriefingWidget() {
  const {
    briefing,
    briefingLoading,
    briefingError,
    briefingGenerating,
    refreshBriefing,
    generateBriefing,
    chat,
  } = useJarvis();

  const available = briefing?.available === true;
  const busy = briefingGenerating || chat.isProcessing;
  const sourceLabel =
    briefing?.source === 'scheduled'
      ? 'daily schedule'
      : briefing?.source === 'manual'
        ? 'manual run'
        : 'unknown source';

  return (
    <section className="panel briefing">
      <header className="panel__header">
        <div>
          <span className="eyebrow">DAILY 08:00 BRIEFING</span>
          <h2 className="panel__title">Morning Briefing</h2>
        </div>
        <div className="panel__actions">
          <button
            type="button"
            className="icon-btn"
            onClick={() => refreshBriefing()}
            disabled={briefingLoading || briefingGenerating}
            title="Refresh the stored briefing"
            aria-label="Refresh the stored briefing"
          >
            <RefreshCw size={14} className={briefingLoading ? 'spin' : ''} />
          </button>
          <button
            type="button"
            className="btn btn--cyan btn--sm"
            onClick={() => generateBriefing()}
            disabled={busy}
            title={
              chat.isProcessing
                ? 'Wait for the current chat request to finish'
                : 'Generate a briefing now'
            }
          >
            {briefingGenerating ? (
              <RefreshCw size={12} className="spin" />
            ) : (
              <Sparkles size={12} />
            )}
            <span>{briefingGenerating ? 'Generating…' : 'Generate now'}</span>
          </button>
        </div>
      </header>

      {available ? (
        <>
          <div className="briefing__meta">
            <CalendarClock size={13} />
            <span>
              Generated {formatGeneratedAt(briefing.generatedAt)} · {sourceLabel} ·{' '}
              {briefing.tenderCount} tender{briefing.tenderCount === 1 ? '' : 's'}
              {briefing.tenderMode === 'mock' ? ' (sample feed)' : ''}
            </span>
          </div>
          <pre className="briefing__body">{briefing.text}</pre>
        </>
      ) : (
        <div className="state-box state-box--tall">
          <span className="eyebrow">NO BRIEFING YET</span>
          <p>
            {briefing?.notice ||
              'The scheduler has not produced a briefing yet. Generate one now, or wait for the daily run.'}
          </p>
          <p className="muted">
            Email and approvals connectors do not exist yet, so the briefing says so instead of
            inventing an inbox. Tenders come from the sample feed (<code>mode=mock</code>).
          </p>
        </div>
      )}

      {briefingError && (
        <div className="alert alert--error" role="alert">
          <AlertTriangle size={14} />
          <span className="grow">{briefingError}</span>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => refreshBriefing()}
          >
            Retry
          </button>
        </div>
      )}

      {briefingGenerating && (
        <p className="footnote">
          A briefing run takes 1–2 minutes on CPU. The job shares the single model slot, so chat
          waits until it finishes.
        </p>
      )}
    </section>
  );
}
