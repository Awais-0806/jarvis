import React from 'react';
import { AlertTriangle, Mic, ShieldCheck, X } from 'lucide-react';
import { AudioWaveform } from '../components/AudioWaveform.jsx';
import { JarvisCore } from '../components/JarvisCore.jsx';
import { VoiceRecorder } from '../components/VoiceRecorder.jsx';
import { useJarvis } from '../context/JarvisContext.jsx';
import { formatDuration, formatTimestamp } from '../utils/formatters.js';

export function Voice() {
  const { voice, chat } = useJarvis();
  const latestReply = [...chat.messages].reverse().find((message) => message.role === 'assistant');

  return (
    <div className="layout-narrow">
      <section className="panel voice-stage">
        <header className="panel__header">
          <div>
            <span className="eyebrow">SPEECH COMMAND PIPELINE</span>
            <h2 className="panel__title">Voice Interface</h2>
          </div>
          <span className="chip chip--id mono">{voice.state.toUpperCase()}</span>
        </header>

        <JarvisCore compact />

        <div className="voice-stage__controls">
          <VoiceRecorder large />
          <p className="mono voice-stage__timer">
            {voice.state === 'recording'
              ? `CAPTURE ${formatDuration(voice.durationSec)}`
              : 'TRANSCRIBE → SEND TO CORE'}
          </p>
        </div>

        <div className="waveform-box">
          <div className="waveform-box__head">
            <span>
              <Mic size={12} className="inline-icon" /> LIVE MICROPHONE SPECTRUM
            </span>
            <span className="mono">{voice.permission.toUpperCase()}</span>
          </div>
          <AudioWaveform bars={voice.bars} active={voice.state === 'recording'} />
        </div>

        {voice.error && (
          <div className="alert alert--error" role="alert">
            <AlertTriangle size={14} />
            <span className="grow">{voice.error}</span>
            <button type="button" className="icon-btn" onClick={voice.clearError} aria-label="Dismiss">
              <X size={13} />
            </button>
          </div>
        )}

        <div className="voice-stage__outputs">
          <div className="subpanel">
            <span className="eyebrow">RECOGNISED TRANSCRIPT</span>
            <p>{voice.lastTranscript || 'No voice directive transcribed in this session yet.'}</p>
          </div>

          <div className="subpanel">
            <span className="eyebrow">LATEST J.A.R.V.I.S. REPLY</span>
            {chat.isProcessing ? (
              <p className="muted">Core job running — the reply will appear here.</p>
            ) : latestReply ? (
              <>
                <p>{latestReply.content}</p>
                <p className="footnote mono">{formatTimestamp(latestReply.timestamp)}</p>
              </>
            ) : (
              <p className="muted">No reply yet.</p>
            )}
          </div>
        </div>

        <div className="alert alert--info">
          <ShieldCheck size={14} />
          <span className="grow">
            Audio stays local until you stop: it is uploaded only to
            <code> /api/voice/transcribe</code>. Empty or unrecognised audio is never sent to the
            assistant.
          </span>
        </div>
      </section>
    </div>
  );
}
