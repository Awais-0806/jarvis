import { useCallback, useEffect, useRef, useState } from 'react';
import { getHostStats, openApplication, takeScreenshot } from '../api/host.js';
import { HOST_OPEN_APP_TARGET } from '../config/constants.js';

/**
 * Remote control state for the Windows host bridge (via core's /api/host proxy).
 * Each action tracks its own pending flag so one slow call never blocks another button.
 */
export function useHostControl() {
  const [screenshot, setScreenshot] = useState(null);
  const [stats, setStats] = useState(null);
  const [pending, setPending] = useState({ screenshot: false, openApp: false, stats: false });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const controllers = useRef(new Map());

  useEffect(() => {
    const active = controllers.current;
    return () => {
      for (const controller of active.values()) controller.abort();
      active.clear();
    };
  }, []);

  const run = useCallback(async (key, task) => {
    if (controllers.current.has(key)) return null;

    const controller = new AbortController();
    controllers.current.set(key, controller);
    setPending((current) => ({ ...current, [key]: true }));
    setError(null);

    try {
      return await task(controller.signal);
    } catch (err) {
      if (err?.code !== 'ABORTED') {
        setError(err?.message || 'The host bridge request failed.');
      }
      return null;
    } finally {
      controllers.current.delete(key);
      setPending((current) => ({ ...current, [key]: false }));
    }
  }, []);

  const capture = useCallback(async () => {
    const next = await run('screenshot', (signal) => takeScreenshot({ signal }));
    if (next) {
      setScreenshot(next);
      setNotice(null);
    }
    return next;
  }, [run]);

  const launchEditor = useCallback(async () => {
    const next = await run('openApp', (signal) =>
      openApplication(HOST_OPEN_APP_TARGET, { signal })
    );
    if (next) {
      setNotice(
        `Launch request accepted for "${next.app}"` +
          (next.resolved ? ` (${next.resolved})` : '') +
          '.'
      );
    }
    return next;
  }, [run]);

  const readStats = useCallback(async () => {
    const next = await run('stats', (signal) => getHostStats({ signal }));
    if (next) {
      setStats(next);
      setNotice(null);
    }
    return next;
  }, [run]);

  const clearMessages = useCallback(() => {
    setError(null);
    setNotice(null);
  }, []);

  return {
    screenshot,
    stats,
    pending,
    error,
    notice,
    capture,
    launchEditor,
    readStats,
    clearMessages,
  };
}
