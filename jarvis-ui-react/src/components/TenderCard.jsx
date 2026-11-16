import React from 'react';
import { Building2, CalendarClock, Eye, Loader2, Sparkles } from 'lucide-react';
import { formatDeadline, formatTimestamp, truncateText } from '../utils/formatters.js';

export function TenderCard({
  tender,
  selected,
  pitching,
  hasPitch,
  disabled,
  onSelect,
  onDraftPitch,
}) {
  return (
    <article
      className={`card ${selected ? 'card--selected' : ''}`}
      onClick={() => onSelect(tender.id)}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="card__top">
        <span className="card__id mono">{tender.id}</span>
        <span className="card__tags">
          {tender.isMock && <span className="tag tag--warn">SAMPLE</span>}
          {hasPitch && <span className="tag tag--ok">PITCH READY</span>}
          {tender.region && <span className="tag">{tender.region}</span>}
        </span>
      </div>

      <h3 className="card__title">{tender.title}</h3>

      <p className="card__meta">
        <Building2 size={12} />
        <span>{tender.buyer}</span>
      </p>

      {tender.submissionDeadline && (
        <p className="card__meta">
          <CalendarClock size={12} />
          <span className="mono">Closes {formatDeadline(tender.submissionDeadline)}</span>
        </p>
      )}

      {tender.estimatedValue && <p className="card__value mono">{tender.estimatedValue}</p>}

      <p className="card__summary">
        {tender.summary ? truncateText(tender.summary, 150) : 'No summary returned by the core.'}
      </p>

      <div className="card__actions" onClick={(event) => event.stopPropagation()}>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => onSelect(tender.id)}>
          <Eye size={12} />
          <span>Inspect</span>
        </button>

        <button
          type="button"
          className="btn btn--cyan btn--sm"
          onClick={() => onDraftPitch(tender.id)}
          disabled={disabled || pitching}
        >
          {pitching ? <Loader2 size={12} className="spin" /> : <Sparkles size={12} />}
          <span>{pitching ? 'DRAFTING…' : 'DRAFT VIP PITCH'}</span>
        </button>
      </div>

      <p className="card__stamp mono">
        {tender.reference ? `${tender.reference} · ` : ''}
        {tender.publishedOn ? `published ${formatTimestamp(tender.publishedOn)}` : 'source not supplied'}
      </p>
    </article>
  );
}
