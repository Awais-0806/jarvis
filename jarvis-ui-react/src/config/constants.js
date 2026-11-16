export const API_BASE = '/api';

/** Multipart field name expected by POST /api/voice/transcribe (FastAPI `file: UploadFile`). */
export const VOICE_UPLOAD_FIELD = 'file';

export const REQUEST_TIMEOUT_MS = 30_000;
export const VOICE_UPLOAD_TIMEOUT_MS = 180_000;
export const HOST_TIMEOUT_MS = 45_000;

/**
 * Core runs one CPU-bound job at a time and keeps a job for 900s (jobs.py timeout_s=900).
 * Poll for slightly longer than that so the UI never gives up before the backend does.
 */
export const JOB_POLL_INTERVAL_MS = 3_000;
export const JOB_POLL_TIMEOUT_MS = 960_000;

/** The core rejects messages longer than 4000 chars (ChatRequest.max_length). */
export const MAX_MESSAGE_CHARS = 4_000;

/** Screenshots are PNG base64; core caps them defensively, the UI refuses anything larger. */
export const MAX_SCREENSHOT_BYTES = 15 * 1024 * 1024;

export const BACKEND_STATUS = Object.freeze({
  UNKNOWN: 'unknown',
  CHECKING: 'checking',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
  AUTH_ERROR: 'auth_error',
});

export const CORE_STATES = Object.freeze({
  IDLE: 'IDLE',
  LISTENING: 'LISTENING',
  PROCESSING: 'PROCESSING',
  SPEAKING: 'SPEAKING',
  EXECUTING: 'EXECUTING',
  ERROR: 'ERROR',
});

export const NAV_VIEWS = Object.freeze({
  COMMAND_CENTER: 'command-center',
  CONVERSATION: 'conversation',
  VOICE: 'voice',
  TENDERS: 'tenders',
  APPROVALS: 'approvals',
  REMOTE_CONTROL: 'remote-control',
  SETTINGS: 'settings',
});

/** Application the host bridge launches for the "Open VS Code" action. */
export const HOST_OPEN_APP_TARGET = 'code';
