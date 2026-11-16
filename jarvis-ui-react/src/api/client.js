import { API_BASE, BACKEND_STATUS, REQUEST_TIMEOUT_MS } from '../config/constants.js';

export class ApiError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status ?? 0;
    this.code = options.code ?? 'API_ERROR';
    this.isNetworkError = options.isNetworkError === true;
    this.isTimeout = options.isTimeout === true;
  }
}

let telemetry = {
  status: BACKEND_STATUS.UNKNOWN,
  latencyMs: null,
  lastCheckedAt: null,
  lastError: null,
};

const listeners = new Set();

function publish(patch) {
  telemetry = { ...telemetry, ...patch, lastCheckedAt: new Date().toISOString() };
  for (const listener of listeners) {
    try {
      listener(telemetry);
    } catch {
      // A broken subscriber must never break a request.
    }
  }
}

export function subscribeBackendTelemetry(listener) {
  listeners.add(listener);
  listener(telemetry);
  return () => listeners.delete(listener);
}

export function getBackendTelemetry() {
  return telemetry;
}

export function markBackendChecking() {
  publish({ status: BACKEND_STATUS.CHECKING, lastError: null });
}

export function resetBackendTelemetry() {
  publish({ status: BACKEND_STATUS.UNKNOWN, latencyMs: null, lastError: null });
}

function linkSignals(externalSignal, timeoutSignal) {
  if (!externalSignal) return timeoutSignal;
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.any === 'function') {
    return AbortSignal.any([externalSignal, timeoutSignal]);
  }

  const controller = new AbortController();
  const forward = (signal) => {
    if (signal.aborted) controller.abort(signal.reason);
    else signal.addEventListener('abort', () => controller.abort(signal.reason), { once: true });
  };
  forward(externalSignal);
  forward(timeoutSignal);
  return controller.signal;
}

function readDetail(payload) {
  if (payload && typeof payload === 'object') {
    if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail.trim();
    if (typeof payload.message === 'string' && payload.message.trim()) return payload.message.trim();
    // FastAPI validation errors arrive as a list of {loc, msg, type}.
    if (Array.isArray(payload.detail) && payload.detail.length > 0) {
      const first = payload.detail[0];
      if (first && typeof first.msg === 'string') return first.msg;
    }
  }
  return null;
}

/**
 * The single entry point for every backend call.
 *
 * Requests always use a relative /api/... URL: the Vite dev proxy injects the bearer token
 * in Node.js, and in production the nginx container injects it. No token ever reaches the
 * browser, and nothing here reads or writes localStorage / sessionStorage.
 */
export async function apiRequest(path, options = {}) {
  const {
    method = 'GET',
    body,
    headers = {},
    signal,
    timeoutMs = REQUEST_TIMEOUT_MS,
  } = options;

  const suffix = path.startsWith('/') ? path : `/${path}`;
  const url = `${API_BASE}${suffix}`;
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;

  const requestHeaders = { Accept: 'application/json', ...headers };
  let payloadBody = body;

  if (body !== undefined && !isFormData && typeof body !== 'string') {
    requestHeaders['Content-Type'] = 'application/json';
    payloadBody = JSON.stringify(body);
  }

  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => {
    timeoutController.abort(new DOMException('Request timed out', 'TimeoutError'));
  }, timeoutMs);

  const combinedSignal = linkSignals(signal, timeoutController.signal);
  const startedAt = performance.now();

  try {
    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: payloadBody,
      signal: combinedSignal,
      credentials: 'same-origin',
      cache: 'no-store',
    });

    const latencyMs = Math.round(performance.now() - startedAt);
    const contentType = response.headers.get('content-type') || '';

    let payload = null;
    if (contentType.includes('application/json')) {
      try {
        payload = await response.json();
      } catch {
        throw new ApiError('The backend returned malformed JSON.', {
          status: response.status,
          code: 'INVALID_JSON',
        });
      }
    } else if (contentType.startsWith('image/')) {
      payload = await response.blob();
    } else {
      const text = await response.text();
      payload = text ? { detail: text } : null;
    }

    if (!response.ok) {
      const detail = readDetail(payload);

      if (response.status === 401 || response.status === 403) {
        publish({
          status: BACKEND_STATUS.AUTH_ERROR,
          latencyMs,
          lastError: 'The core rejected the injected bearer token (HTTP ' + response.status + ').',
        });
        throw new ApiError(
          'Authentication rejected by Jarvis core (HTTP ' +
            response.status +
            '). The proxy token is missing or wrong.',
          { status: response.status, code: 'AUTH_ERROR' }
        );
      }

      if (response.status === 404) {
        publish({ status: BACKEND_STATUS.CONNECTED, latencyMs, lastError: detail });
        throw new ApiError(detail || 'The requested backend route does not exist (404).', {
          status: 404,
          code: 'NOT_FOUND',
        });
      }

      if (response.status === 503) {
        publish({ status: BACKEND_STATUS.CONNECTED, latencyMs, lastError: detail });
        throw new ApiError(
          detail || 'Jarvis is busy with another request. Try again shortly.',
          { status: 503, code: 'BUSY' }
        );
      }

      if (response.status === 502 || response.status === 504) {
        publish({ status: BACKEND_STATUS.CONNECTED, latencyMs, lastError: detail });
        throw new ApiError(
          detail ||
            'The host bridge did not answer (HTTP ' +
              response.status +
              '). Is host_bridge.py running on the laptop?',
          { status: response.status, code: 'UPSTREAM_UNAVAILABLE' }
        );
      }

      publish({ status: BACKEND_STATUS.CONNECTED, latencyMs, lastError: detail });
      throw new ApiError(detail || `Request failed with HTTP ${response.status}.`, {
        status: response.status,
        code: 'HTTP_ERROR',
      });
    }

    publish({ status: BACKEND_STATUS.CONNECTED, latencyMs, lastError: null });
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;

    const abortedByTimeout =
      timeoutController.signal.aborted && (!signal || !signal.aborted);

    if (abortedByTimeout) {
      publish({
        status: BACKEND_STATUS.DISCONNECTED,
        latencyMs: null,
        lastError: 'The backend did not answer before the request timeout.',
      });
      throw new ApiError('Jarvis core did not respond in time.', {
        code: 'TIMEOUT',
        isTimeout: true,
        isNetworkError: true,
      });
    }

    if (error && error.name === 'AbortError') {
      throw new ApiError('Request cancelled.', { code: 'ABORTED' });
    }

    publish({
      status: BACKEND_STATUS.DISCONNECTED,
      latencyMs: null,
      lastError: 'Cannot reach the API proxy. Is the stack running?',
    });
    throw new ApiError(
      'Cannot reach the Jarvis API. Check that Docker Compose is running and the UI was built with a proxy.',
      { code: 'NETWORK_ERROR', isNetworkError: true }
    );
  } finally {
    clearTimeout(timeoutId);
  }
}
