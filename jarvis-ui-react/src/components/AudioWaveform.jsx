import React from 'react';

/** Live microphone spectrum. Bars come from the analyser node, never from a random generator. */
export function AudioWaveform({ bars = [], active = false, label = 'Microphone input spectrum' }) {
  return (
    <div className={`waveform ${active ? 'waveform--live' : ''}`} role="img" aria-label={label}>
      {bars.map((value, index) => (
        <span
          key={index}
          className="waveform__bar"
          style={{ height: `${Math.round(Math.min(1, Math.max(0.06, value)) * 100)}%` }}
        />
      ))}
    </div>
  );
}
