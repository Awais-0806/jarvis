import { ApiError, apiRequest } from './client.js';

function text(value, max = 2_000) {
  return typeof value === 'string' ? value.slice(0, max) : '';
}

function textList(value, maxItems = 8) {
  if (!Array.isArray(value)) return [];
  return value.filter((entry) => typeof entry === 'string' && entry.trim()).slice(0, maxItems);
}

/**
 * The core returns fields the dashboard may display verbatim; unknown or malformed fields
 * become empty instead of being invented.
 */
function normalizeTender(raw) {
  if (!raw || typeof raw !== 'object') return null;

  const id = typeof raw.id === 'string' ? raw.id : '';
  if (!id) return null;

  const deadline = typeof raw.submission_deadline === 'string' ? raw.submission_deadline : '';
  const published = typeof raw.published_on === 'string' ? raw.published_on : '';

  return {
    id,
    reference: text(raw.reference, 64),
    title: text(raw.title, 200) || 'Untitled tender',
    buyer: text(raw.buyer, 200) || 'Unspecified buyer',
    country: text(raw.country, 60),
    region: text(raw.region, 16),
    sourcePortal: text(raw.source_portal, 80),
    procedure: text(raw.procedure, 120),
    classification: text(raw.classification, 200),
    estimatedValue: text(raw.estimated_value, 60),
    publishedOn: published,
    submissionDeadline: deadline,
    summary: text(raw.summary, 900),
    requiredCapabilities: textList(raw.required_capabilities),
    mandatoryRequirements: textList(raw.mandatory_requirements),
    isMock: raw.is_mock === true,
  };
}

/** GET /api/global-tenders -> {items, mode, notice} */
export async function getGlobalTenders({ signal } = {}) {
  const payload = await apiRequest('/global-tenders', { method: 'GET', signal });

  if (!payload || !Array.isArray(payload.items)) {
    throw new ApiError('Unexpected tender feed response from core.', {
      code: 'INVALID_RESPONSE',
    });
  }

  return {
    items: payload.items.map(normalizeTender).filter(Boolean),
    mode: payload.mode === 'live' ? 'live' : 'mock',
    notice: text(payload.notice, 300),
  };
}

/**
 * POST /api/global-tenders/{id}/pitch -> 202 {job_id, ...}
 * The body is optional; core accepts {"regenerate": bool}.
 */
export async function requestTenderPitch(tenderId, { regenerate = false, signal } = {}) {
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(tenderId || '')) {
    throw new ApiError('Invalid tender id.', { code: 'INVALID_ARGUMENT' });
  }

  const payload = await apiRequest(
    `/global-tenders/${encodeURIComponent(tenderId)}/pitch`,
    { method: 'POST', body: { regenerate: regenerate === true }, signal }
  );

  if (!payload || typeof payload.job_id !== 'string' || !payload.job_id.trim()) {
    throw new ApiError('The pitch job was not accepted by core.', {
      code: 'INVALID_RESPONSE',
    });
  }

  return { jobId: payload.job_id.trim() };
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * A pitch job's `reply` is JSON (see core/main.py `_encode_pitch`). Parse it into the fields
 * the dossier shows. Returns null when the reply is not that structure, so the caller can
 * display the raw text instead of pretending it understood it.
 */
export function parsePitchReply(raw) {
  if (typeof raw !== 'string' || !raw.trim()) return null;

  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!data || typeof data !== 'object' || typeof data.pitch !== 'string' || !data.pitch.trim()) {
    return null;
  }

  const evidence = Array.isArray(data.evidence)
    ? data.evidence
        .filter((entry) => entry && typeof entry === 'object')
        .slice(0, 8)
        .map((entry) => ({
          title: text(entry.title, 200),
          section: text(entry.section, 100),
          score: numberOrNull(entry.score),
          text: text(entry.text, 1_500),
        }))
    : [];

  return {
    pitch: text(data.pitch, 8_000),
    matchedProject: text(data.matched_project, 200),
    matchSource: text(data.match_source, 120),
    matchRationale: text(data.match_rationale, 1_500),
    warnings: textList(data.warnings, 5),
    evidence,
    generatedAt: text(data.generated_at, 40),
    cached: data.cached === true,
    tenderId: text(data.tender_id, 64),
  };
}
