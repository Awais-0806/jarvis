import { ApiError, apiRequest } from './client.js';

const JOB_ID_RE = /^[0-9a-f]{32}$/;

function normalizeJob(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new ApiError('Invalid job response from core.', { code: 'INVALID_RESPONSE' });
  }
  if (typeof payload.status !== 'string') {
    throw new ApiError('Job response is missing a status.', { code: 'INVALID_RESPONSE' });
  }
  return {
    jobId: typeof payload.job_id === 'string' ? payload.job_id : '',
    status: payload.status,
    reply: typeof payload.reply === 'string' ? payload.reply : '',
    error: typeof payload.error === 'string' ? payload.error : null,
  };
}

/** POST /api/chat -> 202 {job_id, status, reply, error} */
export async function sendChatMessage({ message, conversationId, signal }) {
  const payload = await apiRequest('/chat', {
    method: 'POST',
    body: { message, conversation_id: conversationId },
    signal,
  });

  const job = normalizeJob(payload);

  if (!JOB_ID_RE.test(job.jobId)) {
    throw new ApiError('The backend returned an unexpected job id.', {
      code: 'INVALID_RESPONSE',
    });
  }

  return job;
}

/** GET /api/jobs/{job_id} */
export async function getJobStatus(jobId, { signal } = {}) {
  if (typeof jobId !== 'string' || !JOB_ID_RE.test(jobId)) {
    throw new ApiError('Cannot poll an invalid job id.', { code: 'INVALID_ARGUMENT' });
  }

  const payload = await apiRequest(`/jobs/${jobId}`, { method: 'GET', signal });
  return normalizeJob(payload);
}
