import { useCallback, useEffect, useRef, useState } from 'react';
import { getJobStatus } from '../api/chat.js';
import { ApiError } from '../api/client.js';
import { JOB_POLL_INTERVAL_MS, JOB_POLL_TIMEOUT_MS } from '../config/constants.js';

function wait(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new ApiError('Cancelled.', { code: 'ABORTED' }));
      return;
    }

    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);

    function onAbort() {
      clearTimeout(timer);
      reject(new ApiError('Cancelled.', { code: 'ABORTED' }));
    }

    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * Poll GET /api/jobs/{id} until the job finishes.
 *
 * Core statuses are exactly running | done | error. `done` with an empty reply is treated as
 * a failure: the UI never fabricates an answer. Timeout and cancellation are explicit.
 */
export async function pollJobUntilComplete(jobId, options = {}) {
  const {
    intervalMs = JOB_POLL_INTERVAL_MS,
    timeoutMs = JOB_POLL_TIMEOUT_MS,
    signal,
    onStatus,
  } = options;

  const deadline = Date.now() + timeoutMs;
  let attempts = 0;

  while (Date.now() < deadline) {
    if (signal?.aborted) throw new ApiError('Cancelled.', { code: 'ABORTED' });

    attempts += 1;
    const job = await getJobStatus(jobId, { signal });
    onStatus?.({ status: job.status, attempts });

    if (job.status === 'done') {
      if (!job.reply || !job.reply.trim()) {
        throw new ApiError('The job finished without returning a reply.', {
          code: 'EMPTY_REPLY',
        });
      }
      return job.reply;
    }

    if (job.status === 'error') {
      throw new ApiError(job.error || 'The job failed on the backend.', {
        code: 'JOB_FAILED',
      });
    }

    if (job.status !== 'running') {
      throw new ApiError(`Unexpected job status "${job.status}".`, {
        code: 'UNEXPECTED_STATUS',
      });
    }

    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    await wait(Math.min(intervalMs, remaining), signal);
  }

  throw new ApiError(
    `The job is still running after ${Math.round(timeoutMs / 60_000)} minutes. ` +
      'Core keeps it for 15 minutes; check the backend logs.',
    { code: 'JOB_TIMEOUT', isTimeout: true }
  );
}

/** Tracks every in-flight poll so navigation/unmount can cancel them cleanly. */
export function useJobPolling() {
  const controllers = useRef(new Set());
  const [activeCount, setActiveCount] = useState(0);

  const poll = useCallback(async (jobId, options = {}) => {
    const controller = new AbortController();
    controllers.current.add(controller);
    setActiveCount(controllers.current.size);

    const onExternalAbort = () => controller.abort();
    options.signal?.addEventListener('abort', onExternalAbort, { once: true });

    try {
      return await pollJobUntilComplete(jobId, { ...options, signal: controller.signal });
    } finally {
      options.signal?.removeEventListener('abort', onExternalAbort);
      controllers.current.delete(controller);
      setActiveCount(controllers.current.size);
    }
  }, []);

  const cancelAll = useCallback(() => {
    for (const controller of controllers.current) controller.abort();
    controllers.current.clear();
    setActiveCount(0);
  }, []);

  useEffect(() => () => cancelAll(), [cancelAll]);

  return { poll, cancelAll, hasActiveJobs: activeCount > 0 };
}
