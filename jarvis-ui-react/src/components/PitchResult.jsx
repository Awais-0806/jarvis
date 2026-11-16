import React from 'react';
import { Check, Copy, Database, Loader2 } from 'lucide-react';
import { formatTimestamp } from '../utils/formatters.js';

/**
 * Renders a pitch job result.
 *
 * Core's pitch reply is JSON with `pitch` plus match metadata; when that shape is absent the
 * raw reply is shown verbatim instead of guessing at its structure.
 */
export function PitchResult({ pitch, onCopy, copied = false }) {
  if (!pitch) return null;

  const parsed = pitch.parsed;

  return (
    <div className="pitch">
      <header className="pitch__head">
        <div>
          <span className="eyebrow">
            PITCH JOB · {pitch.jobId.slice(0, 8)} · {formatTimestamp(pitch.completedAt)}
          </span>
          <h3 className="pitch__title">
            {parsed ? 'Draft VIP pitch' : 'Pitch job reply'}
            {parsed?.cached && <span className="tag tag--ok">CACHED</span>}
          </h3>
        </div>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onCopy}>
          {copied ? <Check size={12} /> : <Copy size={12} />}
          <span>{copied ? 'Copied' : 'Copy pitch'}</span>
        </button>
      </header>

      {parsed ? (
        <>
          {parsed.matchedProject && (
            <p className="pitch__match">
              <span className="eyebrow">MATCHED TRACK RECORD</span>
              <span>{parsed.matchedProject}</span>
              {parsed.matchSource && <span className="mono pitch__source">via {parsed.matchSource}</span>}
            </p>
          )}

          {parsed.matchRationale && <p className="pitch__rationale">{parsed.matchRationale}</p>}

          {parsed.warnings.length > 0 && (
            <div className="alert alert--warn">
              <span className="grow">
                <strong>Model warnings:</strong> {parsed.warnings.join(' · ')}
              </span>
            </div>
          )}

          <pre className="pitch__body">{parsed.pitch}</pre>

          {parsed.evidence.length > 0 && (
            <details className="pitch__evidence">
              <summary>
                <Database size={12} /> {parsed.evidence.length} retrieved evidence excerpt
                {parsed.evidence.length === 1 ? '' : 's'}
              </summary>
              <ul>
                {parsed.evidence.map((item, index) => (
                  <li key={index}>
                    <p className="mono">
                      {item.title || 'Untitled'}
                      {item.section ? ` · ${item.section}` : ''}
                      {item.score !== null ? ` · score ${item.score.toFixed(3)}` : ''}
                    </p>
                    <p>{item.text}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      ) : (
        <pre className="pitch__body">{pitch.raw}</pre>
      )}
    </div>
  );
}

export function PitchPending({ tenderId }) {
  return (
    <div className="state-box" role="status">
      <Loader2 size={18} className="spin accent" />
      <span>Drafting a pitch for {tenderId}. A CPU pitch takes minutes; polling continues.</span>
    </div>
  );
}
