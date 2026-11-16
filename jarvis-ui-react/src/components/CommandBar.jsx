import React, { useRef, useState } from 'react';
import { Send, Square } from 'lucide-react';
import { useJarvis } from '../context/JarvisContext.jsx';
import { MAX_MESSAGE_CHARS } from '../config/constants.js';
import { VoiceRecorder } from './VoiceRecorder.jsx';

export function CommandBar() {
  const { chat, voice, stopVoiceAndSend } = useJarvis();
  const [value, setValue] = useState('');
  const areaRef = useRef(null);

  const recording = voice.state === 'recording';
  const transcribing = voice.state === 'transcribing';

  const submit = async (event) => {
    event?.preventDefault();

    if (recording) {
      await stopVoiceAndSend();
      return;
    }

    const text = value.trim();
    if (!text || chat.isProcessing || text.length > MAX_MESSAGE_CHARS) return;

    setValue('');
    if (areaRef.current) areaRef.current.style.height = 'auto';
    await chat.sendMessage(text, { source: 'text' });
  };

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const onInput = (event) => {
    setValue(event.target.value);
    const area = areaRef.current;
    if (!area) return;
    area.style.height = 'auto';
    area.style.height = `${Math.min(area.scrollHeight, 132)}px`;
  };

  return (
    <form className="command" onSubmit={submit}>
      <div className="command__field">
        <textarea
          ref={areaRef}
          className="command__input"
          rows={1}
          value={value}
          onChange={onInput}
          onKeyDown={onKeyDown}
          maxLength={MAX_MESSAGE_CHARS}
          placeholder={
            recording
              ? 'Recording… press Stop to transcribe and send'
              : 'Directive for J.A.R.V.I.S. — Enter to send, Shift+Enter for a new line'
          }
          disabled={chat.isProcessing || transcribing}
          aria-label="Message J.A.R.V.I.S."
        />
        {value.length > MAX_MESSAGE_CHARS - 400 && (
          <span className="command__count mono">
            {value.length}/{MAX_MESSAGE_CHARS}
          </span>
        )}
      </div>

      <div className="command__actions">
        <VoiceRecorder />

        {chat.isProcessing ? (
          <button
            type="button"
            className="btn btn--ghost"
            onClick={chat.cancel}
            title="Stop waiting for this job"
          >
            <Square size={14} />
            <span>Abort</span>
          </button>
        ) : (
          <button
            type="submit"
            className="btn btn--primary"
            disabled={!value.trim() || transcribing}
            aria-label="Send message"
          >
            <Send size={15} />
            <span>Transmit</span>
          </button>
        )}
      </div>
    </form>
  );
}
