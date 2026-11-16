import React, { useState } from 'react';
import {
  AlertTriangle,
  Building2,
  CalendarClock,
  Coins,
  Database,
  FileText,
  RefreshCw,
  Sparkles,
  X,
} from 'lucide-react';
import { useJarvis } from '../context/JarvisContext.jsx';
import { formatDateOnly, formatDeadline } from '../utils/formatters.js';
import { TenderCard } from './TenderCard.jsx';
import { PitchPending, PitchResult } from './PitchResult.jsx';

function CapabilityList({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="dossier__block">
      <span className="eyebrow">{title}</span>
      <ul className="bullets">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function TenderPanel({ detail = true }) {
  const {
    tenders,
    tenderMode,
    tenderNotice,
    tendersLoading,
    tendersError,
    selectedTender,
    selectedTenderId,
    setSelectedTenderId,
    refreshTenders,
    pitches,
    pitchTenderId,
    pitchError,
    clearPitchError,
    draftPitch,
    isBusy,
  } = useJarvis();

  const [copied, setCopied] = useState(false);

  const pitch = selectedTender ? pitches[selectedTender.id] : null;
  const pitchingThis = selectedTender ? pitchTenderId === selectedTender.id : false;
  const errorForSelected =
    pitchError && selectedTender && pitchError.tenderId === selectedTender.id
      ? pitchError.message
      : null;

  const copyPitch = async () => {
    const text = pitch?.parsed?.pitch || pitch?.raw;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is best-effort only.
    }
  };

  return (
    <section className="panel intel">
      <header className="panel__header">
        <div>
          <span className="eyebrow">OPPORTUNITY FEED</span>
          <h2 className="panel__title">
            Global Tender Intelligence <span className="counter">{tenders.length}</span>
          </h2>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={() => refreshTenders()}
          disabled={tendersLoading}
          title="Refresh tenders"
          aria-label="Refresh tenders"
        >
          <RefreshCw size={14} className={tendersLoading ? 'spin' : ''} />
        </button>
      </header>

      {tenderMode !== 'live' && (
        <div className="alert alert--warn">
          <Database size={14} />
          <span className="grow">
            The core is serving <strong>sample tender records</strong>
            {tenderNotice ? `: ${tenderNotice}` : '. Connectors are not wired in yet.'}
          </span>
        </div>
      )}

      {tendersError && (
        <div className="alert alert--error" role="alert">
          <AlertTriangle size={14} />
          <span className="grow">{tendersError}</span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => refreshTenders()}>
            Retry
          </button>
        </div>
      )}

      {pitchError && !errorForSelected && (
        <div className="alert alert--error" role="alert">
          <AlertTriangle size={14} />
          <span className="grow">
            Pitch for {pitchError.tenderId}: {pitchError.message}
          </span>
          <button type="button" className="icon-btn" onClick={clearPitchError} aria-label="Dismiss">
            <X size={13} />
          </button>
        </div>
      )}

      {tendersLoading && tenders.length === 0 ? (
        <div className="state-box">
          <RefreshCw size={16} className="spin accent" />
          <span>Loading the tender feed from the core…</span>
        </div>
      ) : tenders.length === 0 ? (
        <div className="state-box">
          <span>
            {tendersError
              ? 'No tenders could be loaded.'
              : 'The core returned no tender records.'}
          </span>
        </div>
      ) : (
        <div className="cards">
          {tenders.map((tender) => (
            <TenderCard
              key={tender.id}
              tender={tender}
              selected={tender.id === selectedTenderId}
              pitching={pitchTenderId === tender.id}
              hasPitch={Boolean(pitches[tender.id])}
              disabled={isBusy && pitchTenderId !== tender.id}
              onSelect={setSelectedTenderId}
              onDraftPitch={(id) => draftPitch(id)}
            />
          ))}
        </div>
      )}

      {detail && selectedTender && (
        <div className="dossier">
          <header className="dossier__head">
            <div>
              <span className="eyebrow">TENDER DOSSIER · {selectedTender.id}</span>
              <h3 className="dossier__title">{selectedTender.title}</h3>
            </div>
            <div className="dossier__actions">
              <button
                type="button"
                className="btn btn--cyan btn--sm"
                onClick={() => draftPitch(selectedTender.id)}
                disabled={isBusy}
              >
                <Sparkles size={12} />
                <span>{pitchingThis ? 'DRAFTING…' : 'DRAFT VIP PITCH'}</span>
              </button>
              {pitches[selectedTender.id] && (
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => draftPitch(selectedTender.id, { regenerate: true })}
                  disabled={isBusy}
                  title="Ask the core to draft a new pitch instead of reusing the cached one"
                >
                  <RefreshCw size={12} />
                  <span>Regenerate</span>
                </button>
              )}
            </div>
          </header>

          <dl className="dossier__facts">
            <div>
              <dt>
                <Building2 size={12} /> Buyer
              </dt>
              <dd>
                {selectedTender.buyer}
                {selectedTender.country ? ` · ${selectedTender.country}` : ''}
              </dd>
            </div>
            {selectedTender.estimatedValue && (
              <div>
                <dt>
                  <Coins size={12} /> Estimated value
                </dt>
                <dd className="mono">{selectedTender.estimatedValue}</dd>
              </div>
            )}
            {selectedTender.submissionDeadline && (
              <div>
                <dt>
                  <CalendarClock size={12} /> Submission deadline
                </dt>
                <dd className="mono">{formatDeadline(selectedTender.submissionDeadline)}</dd>
              </div>
            )}
            {selectedTender.procedure && (
              <div>
                <dt>
                  <FileText size={12} /> Procedure
                </dt>
                <dd>{selectedTender.procedure}</dd>
              </div>
            )}
          </dl>

          <div className="dossier__block">
            <span className="eyebrow">SUMMARY</span>
            <p>{selectedTender.summary || 'No summary returned by the core.'}</p>
          </div>

          <CapabilityList
            title="REQUIRED CAPABILITIES"
            items={selectedTender.requiredCapabilities}
          />
          <CapabilityList
            title="MANDATORY REQUIREMENTS"
            items={selectedTender.mandatoryRequirements}
          />

          {selectedTender.sourcePortal && (
            <p className="footnote mono">
              {selectedTender.sourcePortal}
              {selectedTender.publishedOn ? ` · published ${formatDateOnly(selectedTender.publishedOn)}` : ''}
              {selectedTender.classification ? ` · ${selectedTender.classification}` : ''}
            </p>
          )}

          {errorForSelected && (
            <div className="alert alert--error" role="alert">
              <AlertTriangle size={14} />
              <span className="grow">{errorForSelected}</span>
              <button type="button" className="icon-btn" onClick={clearPitchError} aria-label="Dismiss">
                <X size={13} />
              </button>
            </div>
          )}

          {pitchingThis && <PitchPending tenderId={selectedTender.id} />}

          <PitchResult pitch={pitch} copied={copied} onCopy={copyPitch} />
        </div>
      )}
    </section>
  );
}
