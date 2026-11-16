import React, { useState } from 'react';
import { Check, Copy, Mail, ShieldAlert } from 'lucide-react';
import { truncateText } from '../utils/formatters.js';

export function ApprovalCard({ approval, selected, onSelect }) {
  const [copied, setCopied] = useState(false);

  const copy = async (event) => {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(`Subject: ${approval.subject}\n\n${approval.body}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is best-effort only.
    }
  };

  return (
    <article
      className={`card ${selected ? 'card--selected' : ''}`}
      onClick={() => onSelect(approval.id)}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="card__top">
        <span className="card__id mono">{approval.id}</span>
        <span className="tag tag--warn">
          <ShieldAlert size={10} /> REVIEW
        </span>
      </div>

      <h3 className="card__title">
        <Mail size={13} className="inline-icon" />
        {approval.subject || '(no subject)'}
      </h3>

      <p className="card__summary">
        {approval.body ? truncateText(approval.body, 150) : 'The draft body is empty.'}
      </p>

      <div className="card__actions" onClick={(event) => event.stopPropagation()}>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => onSelect(approval.id)}>
          <span>Review draft</span>
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={copy}>
          {copied ? <Check size={12} /> : <Copy size={12} />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
    </article>
  );
}
