const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function toDate(value) {
  if (value instanceof Date) return value;
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTime(date = new Date()) {
  const value = toDate(date);
  if (!value) return '--:--:--';
  return value.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function formatDate(date = new Date()) {
  const value = toDate(date);
  if (!value) return '---';
  return value.toLocaleDateString([], {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

/** Timestamps from the API are ISO strings; date-only strings stay date-only. */
export function formatTimestamp(value) {
  if (!value) return '--:--';
  if (typeof value === 'string' && DATE_ONLY.test(value)) return formatDateOnly(value);

  const date = toDate(value);
  if (!date) return '--:--';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function formatDateOnly(value) {
  const date = toDate(value);
  if (!date) return '---';
  return date.toLocaleDateString([], { day: '2-digit', month: 'short', year: 'numeric' });
}

/**
 * Deadlines include a time, so both are shown. A date-only value is rendered without a time
 * rather than inventing midnight.
 */
export function formatDeadline(value) {
  if (!value) return '—';
  if (typeof value === 'string' && DATE_ONLY.test(value)) return formatDateOnly(value);

  const date = toDate(value);
  if (!date) return '—';
  return `${date.toLocaleDateString([], {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })}, ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}`;
}

export function formatDuration(totalSeconds) {
  const safe = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const minutes = String(Math.floor(safe / 60)).padStart(2, '0');
  const seconds = String(safe % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

export function formatPercent(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value.toFixed(value >= 100 ? 0 : 1)}%`;
}

export function truncateText(text, maxLength = 160) {
  if (typeof text !== 'string') return '';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trimEnd()}…`;
}
