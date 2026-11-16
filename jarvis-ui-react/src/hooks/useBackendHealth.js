import { useCallback, useEffect, useState } from 'react';
import { getBackendTelemetry, markBackendChecking, subscribeBackendTelemetry } from '../api/client.js';
import { getGlobalTenders } from '../api/tenders.js';
import { BACKEND_STATUS } from '../config/constants.js';

/**
 * Connectivity is derived from real responses only. The probe is GET /api/global-tenders:
 * it is protected, so a 200 proves the proxy token works, and it is cheap compared to chat.
 */
export function useBackendHealth() {
  const [telemetry, setTelemetry] = useState(getBackendTelemetry);

  useEffect(() => subscribeBackendTelemetry(setTelemetry), []);

  const probe = useCallback(async ({ signal } = {}) => {
    markBackendChecking();
    return getGlobalTenders({ signal });
  }, []);

  return {
    telemetry,
    probe,
    isChecking: telemetry.status === BACKEND_STATUS.CHECKING,
    isConnected: telemetry.status === BACKEND_STATUS.CONNECTED,
  };
}
