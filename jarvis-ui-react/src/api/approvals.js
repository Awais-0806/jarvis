import { ApiError, apiRequest } from './client.js';

const NOT_CONNECTED =
  'Approval actions are not connected — the core API has no /approvals route yet. ' +
  'Backend endpoints are required.';

/**
 * GET /api/approvals.
 *
 * The current core has no approvals route at all, so a 404 is the expected answer and is
 * reported as "backend integration required" rather than as a generic failure. If the route
 * appears later, the same code starts rendering it unchanged.
 */
export async function getApprovals({ signal } = {}) {
  try {
    const payload = await apiRequest('/approvals', { method: 'GET', signal });

    if (!payload || !Array.isArray(payload.items)) {
      throw new ApiError('Unexpected approvals response from core.', {
        code: 'INVALID_RESPONSE',
      });
    }

    const items = payload.items
      .filter((entry) => entry && typeof entry === 'object')
      .map((entry) => ({
        id: typeof entry.id === 'string' || typeof entry.id === 'number' ? String(entry.id) : '',
        subject: typeof entry.subject === 'string' ? entry.subject : '',
        body: typeof entry.body === 'string' ? entry.body : '',
      }))
      .filter((entry) => entry.id);

    return { items, available: true };
  } catch (error) {
    if (error instanceof ApiError && error.code === 'NOT_FOUND') {
      return { items: [], available: false, notice: NOT_CONNECTED };
    }
    throw error;
  }
}

export { NOT_CONNECTED };
