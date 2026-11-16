import React from 'react';
import { Loader2, Mic, Square, X } from 'lucide-react';
import { useJarvis } from '../context/JarvisContext.jsx';
import { formatDuration } from '../utils/formatters.js';

export function VoiceRecorder({ large = false }) {
  const { voice, stopVoiceAndSend, chat } = useJarvis();

  const recording = voice.state === 'recording';
  const requesting = voice.state === 'requesting';
  const transcribing = voice.state === 'transcribing';
  const busy = requesting || transcribing || chat.isProcessing;

  const toggle = async () => {
    if (recording) {
      await stopVoiceAndSend();
      return;
    }
    await voice.startRecording();
  };

  return (
    <div className={`voice ${large ? 'voice--large' : ''}`}>
      <button
        type="button"
        className={`btn ${recording ? 'btn--danger' : 'btn--cyan'} ${large ? 'btn--lg' : ''}`}
        onClick={toggle}
        disabled={(!voice.isSupported && !recording) || (busy && !recording)}
        aria-label={recording ? 'Stop recording and send the transcript' : 'Start voice recording'}
        title={
          !voice.isSupported
            ? 'This browser cannot record audio'
            : recording
              ? 'Stop, transcribe, then send'
              : 'Record a voice directive'
        }
      >
        {requesting || transcribing ? (
          <Loader2 size={large ? 18 : 15} className="spin" />
        ) : recording ? (
          <Square size={large ? 16 : 13} />
        ) : (
          <Mic size={large ? 18 : 15} />
        )}
        <span>
          {requesting
            ? 'Authorising…'
            : recording
              ? `Stop · ${formatDuration(voice.durationSec)}`
              : transcribing
                ? 'Transcribing…'
                : large
                  ? 'ACTIVATE VOICE'
                  : 'Voice'}
        </span>
      </button>

      {(recording || transcribing) && (
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={voice.cancelRecording}
          title="Discard this recording"
        >
          <X size={13} />
          <span>Cancel</span>
        </button>
      )}
    </div>
  );
}
