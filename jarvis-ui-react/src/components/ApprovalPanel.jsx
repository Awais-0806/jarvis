import React, { useState } from 'react';
import { AlertTriangle, Check, Copy, Lock, RefreshCw, ShieldAlert, X } from 'lucide-react';
import { useJarvis } from '../context/JarvisContext.jsx';
import { ApprovalCard } from './ApprovalCard.jsx';

const NOT_CONNECTED = 'Approval actions are not connected — backend endpoints required.';

export function ApprovalPanel({ detail = true }) {
  const {
    approvals,
    approvalsAvailable,
    approvalsNotice,
    approvalsLoading,
    approvalsError,
    selectedApproval,
    selectedApprovalId,
    setSelectedApprovalId,
    refreshApprovals,
  } = useJarvis();

  const [copied, setCopied] = useState(false);

  const copyDraft = async () => {
    if (!selectedApproval) return;
    try {
      await navigator.clipboard.writeText(
        `Subject: ${selectedApproval.subject}\n\n${selectedApproval.body}`
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is best-effort only.
    }
  };

  const unsupported = approvalsAvailable === false;

  return (
    <section className="panel intel">
      <header className="panel__header">
        <div>
          <span className="eyebrow">HUMAN-IN-THE-LOOP QUEUE</span>
          <h2 className="panel__title">
            Pending Approvals <span className="counter">{approvals.length}</span>
          </h2>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={() => refreshApprovals()}
          disabled={approvalsLoading}
          title="Refresh pending approvals"
          aria-label="Refresh pending approvals"
        >
          <RefreshCw size={14} className={approvalsLoading ? 'spin' : ''} />
        </button>
      </header>

      <div className="alert alert--warn">
        <ShieldAlert size={14} />
        <span className="grow">
          {NOT_CONNECTED} Drafts are for human review only; J.A.R.V.I.S. never sends anything.
        </span>
      </div>

      {unsupported ? (
        <div className="state-box state-box--tall">
          <span className="eyebrow">BACKEND INTEGRATION REQUIRED</span>
          <p>
            <code>GET /api/approvals</code> is not implemented by the running core (it returned
            404), so there is no approval queue to display.
          </p>
          {approvalsNotice && <p className="muted">{approvalsNotice}</p>}
          <p className="muted">
            Implement <code>GET /api/approvals</code> (and approve/reject routes) in the core to
            light this panel up. Nothing is faked in the meantime.
          </p>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => refreshApprovals()}
            disabled={approvalsLoading}
          >
            <RefreshCw size={12} className={approvalsLoading ? 'spin' : ''} />
            <span>Check again</span>
          </button>
        </div>
      ) : null}

      {approvalsError && (
        <div className="alert alert--error" role="alert">
          <AlertTriangle size={14} />
          <span className="grow">{approvalsError}</span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => refreshApprovals()}>
            Retry
          </button>
        </div>
      )}

      {!unsupported && approvalsLoading && approvals.length === 0 && (
        <div className="state-box">
          <RefreshCw size={16} className="spin accent" />
          <span>Loading pending approvals…</span>
        </div>
      )}

      {!unsupported && !approvalsLoading && approvals.length === 0 && !approvalsError && (
        <div className="state-box">
          <span>The approvals queue is empty.</span>
        </div>
      )}

      {approvals.length > 0 && (
        <div className="cards">
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              selected={approval.id === selectedApprovalId}
              onSelect={setSelectedApprovalId}
            />
          ))}
        </div>
      )}

      {detail && selectedApproval && (
        <div className="dossier">
          <header className="dossier__head">
            <div>
              <span className="eyebrow">DRAFT REVIEW · {selectedApproval.id}</span>
              <h3 className="dossier__title">{selectedApproval.subject || '(no subject)'}</h3>
            </div>
            <button type="button" className="btn btn--ghost btn--sm" onClick={copyDraft}>
              {copied ? <Check size={12} /> : <Copy size={12} />}
              <span>{copied ? 'Copied' : 'Copy draft'}</span>
            </button>
          </header>

          <pre className="draft">{selectedApproval.body || 'The draft body is empty.'}</pre>

          <div className="dossier__actions">
            <button type="button" className="btn btn--ghost btn--sm" disabled title={NOT_CONNECTED}>
              <Lock size={12} />
              <span>Approve &amp; send (unavailable)</span>
            </button>
            <button type="button" className="btn btn--ghost btn--sm" disabled title={NOT_CONNECTED}>
              <Lock size={12} />
              <span>Reject (unavailable)</span>
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setSelectedApprovalId(null)}
              aria-label="Close review"
            >
              <X size={12} />
              <span>Close</span>
            </button>
          </div>

          <p className="footnote">{NOT_CONNECTED}</p>
        </div>
      )}
    </section>
  );
}
