export function createId(prefix = 'jarvis') {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function createConversationId() {
  return createId('jarvis');
}

export function createMessageId() {
  return createId('msg');
}
