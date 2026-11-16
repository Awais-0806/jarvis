import { HOST_TIMEOUT_MS, MAX_SCREENSHOT_BYTES } from '../config/constants.js';
import { ApiError, apiRequest } from './client.js';

function percent(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return Math.min(100, Math.max(0, value));
}

function gigabyte(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return Math.round(value * 10) / 10;
}

/**
 * GET /api/host/screenshot
 *
 * The bridge returns base64 PNG plus its size. The image is decoded here (never injected as
 * HTML) and handed to the component as a data: URL, which the edge CSP allows.
 */
export async function takeScreenshot({ signal } = {}) {
  const payload = await apiRequest('/host/screenshot', {
    method: 'GET',
    signal,
    timeoutMs: HOST_TIMEOUT_MS,
  });

  if (!payload || typeof payload.image_base64 !== 'string' || !payload.image_base64) {
    throw new ApiError('The host bridge returned no screenshot data.', {
      code: 'INVALID_RESPONSE',
    });
  }

  const mimeType =
    typeof payload.mime_type === 'string' && /^image\/[a-z0-9.+-]+$/i.test(payload.mime_type)
      ? payload.mime_type
      : 'image/png';

  const base64 = payload.image_base64.replace(/\s+/g, '');

  if (base64.length > Math.ceil((MAX_SCREENSHOT_BYTES * 4) / 3)) {
    throw new ApiError('The screenshot is larger than the interface will display.', {
      code: 'SCREENSHOT_TOO_LARGE',
    });
  }

  return {
    dataUrl: `data:${mimeType};base64,${base64}`,
    mimeType,
    width: typeof payload.width === 'number' ? payload.width : null,
    height: typeof payload.height === 'number' ? payload.height : null,
    monitor: typeof payload.monitor === 'number' ? payload.monitor : null,
    capturedAt: typeof payload.captured_at === 'string' ? payload.captured_at : '',
  };
}

/** POST /api/host/open_app -> {ok, action, app, resolved} */
export async function openApplication(appName, { signal } = {}) {
  const name = typeof appName === 'string' ? appName.trim() : '';
  if (!name) {
    throw new ApiError('An application name is required.', { code: 'INVALID_ARGUMENT' });
  }

  const payload = await apiRequest('/host/open_app', {
    method: 'POST',
    body: { app_name: name },
    signal,
    timeoutMs: HOST_TIMEOUT_MS,
  });

  if (!payload || payload.ok !== true) {
    throw new ApiError('The host bridge did not confirm the launch.', {
      code: 'INVALID_RESPONSE',
    });
  }

  return {
    app: typeof payload.app === 'string' ? payload.app : name,
    resolved: typeof payload.resolved === 'string' ? payload.resolved : '',
  };
}

/** GET /api/host/stats -> CPU, RAM and battery readings from the laptop. */
export async function getHostStats({ signal } = {}) {
  const payload = await apiRequest('/host/stats', {
    method: 'GET',
    signal,
    timeoutMs: HOST_TIMEOUT_MS,
  });

  if (!payload || typeof payload !== 'object') {
    throw new ApiError('The host bridge returned no system statistics.', {
      code: 'INVALID_RESPONSE',
    });
  }

  return {
    cpuPercent: percent(payload.cpu_percent),
    ramPercent: percent(payload.ram_percent),
    ramUsedGb: gigabyte(payload.ram_used_gb),
    ramTotalGb: gigabyte(payload.ram_total_gb),
    batteryPercent: percent(payload.battery_percent),
    batteryPlugged:
      typeof payload.battery_plugged === 'boolean' ? payload.battery_plugged : null,
    cpuCores: typeof payload.cpu_cores === 'number' ? payload.cpu_cores : null,
    hostname: typeof payload.hostname === 'string' ? payload.hostname : '',
    platform: typeof payload.platform === 'string' ? payload.platform : '',
    collectedAt: typeof payload.collected_at === 'string' ? payload.collected_at : '',
  };
}
