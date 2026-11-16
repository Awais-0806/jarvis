import { ApiError, apiRequest } from './client.js';

const INVALID_RESPONSE = 'Core returned an unexpected briefing response.';

function normaliseBriefing(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new ApiError(INVALID_RESPONSE, { code: 'INVALID_RESPONSE' });
  }

  return {
    available: payload.available === true,
    text: typeof payload.text === 'string' ? payload.text : '',
    generatedAt: typeof payload.generated_at === 'string' ? payload.generated_at : null,
    source: typeof payload.source === 'string' ? payload.source : null,
    tenderCount: Number.isFinite(payload.tender_count) ? payload.tender_count : 0,
    tenderMode: typeof payload.tender_mode === 'string' ? payload.tender_mode : 'none',
    notice: typeof payload.notice === 'string' ? payload.notice : '',
  };
}

/**
 * GET /api/briefing/latest.
 *
 * Core answers 200 with `available: false` before the first run, so "no briefing yet" is a
 * normal state rather than an error. The text is the crew's own output and is rendered as
 * plain text: it is never interpreted as HTML.
 */
export async function getLatestBriefing({ signal } = {}) {
  const payload = await apiRequest('/briefing/latest', { method: 'GET', signal });
  return normaliseBriefing(payload);
}

/**
 * POST /api/briefing/generate.
 *
 * Starts a background job (202) and returns its id; poll GET /api/jobs/{id} until done, then
 * refresh GET /api/briefing/latest. Shares the single job slot with chat and pitches.
 */
export async function requestBriefing({ signal } = {}) {
  const payload = await apiRequest('/briefing/generate', { method: 'POST', body: {}, signal });
  const jobId = payload && typeof payload.job_id === 'string' ? payload.job_id : '';

  if (!jobId) {
    throw new ApiError(INVALID_RESPONSE, { code: 'INVALID_RESPONSE' });
  }

  return { jobId, status: payload.status };
}
