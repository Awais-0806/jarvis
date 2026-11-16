import { VOICE_UPLOAD_FIELD, VOICE_UPLOAD_TIMEOUT_MS } from '../config/constants.js';
import { ApiError, apiRequest } from './client.js';

function extensionFor(mimeType) {
  if (!mimeType) return 'webm';
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('mp4')) return 'mp4';
  if (mimeType.includes('wav')) return 'wav';
  return 'webm';
}

/** POST /api/voice/transcribe (multipart field name is configured in one place). */
export async function transcribeAudio(blob, { signal, mimeType } = {}) {
  if (!(blob instanceof Blob) || blob.size === 0) {
    throw new ApiError('There is no recorded audio to transcribe.', { code: 'EMPTY_AUDIO' });
  }

  const form = new FormData();
  form.append(VOICE_UPLOAD_FIELD, blob, `jarvis-command.${extensionFor(mimeType || blob.type)}`);

  const payload = await apiRequest('/voice/transcribe', {
    method: 'POST',
    body: form,
    signal,
    timeoutMs: VOICE_UPLOAD_TIMEOUT_MS,
  });

  if (!payload || typeof payload.text !== 'string') {
    throw new ApiError('The voice service returned no transcript.', {
      code: 'INVALID_RESPONSE',
    });
  }

  return payload.text.trim();
}
