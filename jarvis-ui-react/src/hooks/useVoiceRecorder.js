import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { transcribeAudio } from '../api/voice.js';

const BAR_COUNT = 24;
const IDLE_BARS = Array.from({ length: BAR_COUNT }, () => 0.06);

function supportedMimeType() {
  if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) return '';
  return (
    ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find((type) =>
      MediaRecorder.isTypeSupported(type)
    ) || ''
  );
}

/**
 * MediaRecorder capture + /api/voice/transcribe.
 *
 * Every track, AudioContext, rAF loop and timer is released on stop, cancel and unmount.
 * stopAndTranscribe() resolves with the transcript, or null when nothing usable was captured;
 * it never sends audio to /api/chat itself.
 */
export function useVoiceRecorder() {
  const isSupported = useMemo(
    () =>
      typeof window !== 'undefined' &&
      Boolean(navigator?.mediaDevices?.getUserMedia) &&
      typeof window.MediaRecorder !== 'undefined',
    []
  );

  const [state, setState] = useState('idle'); // idle | requesting | recording | transcribing
  const [permission, setPermission] = useState(isSupported ? 'prompt' : 'unsupported');
  const [bars, setBars] = useState(IDLE_BARS);
  const [level, setLevel] = useState(0);
  const [durationSec, setDurationSec] = useState(0);
  const [error, setError] = useState(null);
  const [lastTranscript, setLastTranscript] = useState('');

  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const contextRef = useRef(null);
  const analyserRef = useRef(null);
  const frameRef = useRef(null);
  const timerRef = useRef(null);
  const uploadRef = useRef(null);
  const chunksRef = useRef([]);
  const modeRef = useRef('cancel');
  const resolverRef = useRef(null);

  const release = useCallback(() => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) track.stop();
    }
    streamRef.current = null;
    if (contextRef.current) contextRef.current.close().catch(() => {});
    contextRef.current = null;
    analyserRef.current = null;
    recorderRef.current = null;
    setBars(IDLE_BARS);
    setLevel(0);
  }, []);

  useEffect(() => {
    return () => {
      uploadRef.current?.abort();
      modeRef.current = 'cancel';
      resolverRef.current?.(null);
      resolverRef.current = null;
      release();
    };
  }, [release]);

  const drawWaveform = useCallback((stream) => {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;

    try {
      const context = new Ctx();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.78;
      source.connect(analyser);

      contextRef.current = context;
      analyserRef.current = analyser;
      const bins = new Uint8Array(analyser.frequencyBinCount);
      let frame = 0;

      const tick = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(bins);

        // ~15 updates/second instead of 60: the spectrum stays live without re-rendering the
        // whole command center on every animation frame.
        frame += 1;
        if (frame % 4 === 0) {
          let sum = 0;
          const next = [];
          for (let i = 0; i < BAR_COUNT; i += 1) {
            const index = Math.min(bins.length - 1, Math.floor((i / BAR_COUNT) * bins.length));
            const value = Math.max(0.06, bins[index] / 255);
            next.push(value);
            sum += value;
          }
          setBars(next);
          setLevel(sum / BAR_COUNT);
        }

        frameRef.current = requestAnimationFrame(tick);
      };

      frameRef.current = requestAnimationFrame(tick);
    } catch {
      // Visualisation is optional; recording still works without Web Audio.
    }
  }, []);

  const fail = useCallback(
    (message) => {
      release();
      setState('idle');
      setError(message);
      resolverRef.current?.(null);
      resolverRef.current = null;
    },
    [release]
  );

  const startRecording = useCallback(async () => {
    if (!isSupported) {
      setPermission('unsupported');
      setError('This browser cannot record audio (MediaRecorder is unavailable).');
      return false;
    }
    if (state !== 'idle') return false;

    setError(null);
    setDurationSec(0);
    setState('requesting');

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });

      setPermission('granted');
      streamRef.current = stream;
      chunksRef.current = [];
      modeRef.current = 'cancel';

      const mimeType = supportedMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onerror = () => fail('Recording failed in the browser.');

      recorder.onstop = async () => {
        const stoppedByUser = modeRef.current === 'submit';
        const recordedType = recorder.mimeType || mimeType || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type: recordedType });
        chunksRef.current = [];
        release();

        if (!stoppedByUser) {
          setState('idle');
          resolverRef.current?.(null);
          resolverRef.current = null;
          return;
        }

        if (blob.size === 0) {
          setState('idle');
          setError('No audio was captured. Speak, then stop the recording.');
          resolverRef.current?.(null);
          resolverRef.current = null;
          return;
        }

        setState('transcribing');
        const controller = new AbortController();
        uploadRef.current = controller;

        try {
          const transcript = await transcribeAudio(blob, {
            signal: controller.signal,
            mimeType: recordedType,
          });

          if (!transcript) {
            setState('idle');
            setError('No speech was recognised, so nothing was sent to the assistant.');
            resolverRef.current?.(null);
          } else {
            setLastTranscript(transcript);
            setState('idle');
            resolverRef.current?.(transcript);
          }
        } catch (err) {
          if (err?.code === 'ABORTED') {
            setState('idle');
            resolverRef.current?.(null);
          } else {
            fail(err?.message || 'Transcription failed.');
          }
        } finally {
          uploadRef.current = null;
          resolverRef.current = null;
        }
      };

      recorder.start(250);
      setState('recording');
      drawWaveform(stream);

      const startedAt = Date.now();
      timerRef.current = setInterval(() => {
        setDurationSec(Math.floor((Date.now() - startedAt) / 1000));
      }, 250);

      return true;
    } catch (err) {
      release();
      setState('idle');

      if (err?.name === 'NotAllowedError' || err?.name === 'SecurityError') {
        setPermission('denied');
        setError('Microphone access was denied. Allow it in the browser site settings.');
      } else if (err?.name === 'NotFoundError') {
        setError('No microphone was found on this device.');
      } else {
        setError('The microphone could not be opened.');
      }
      return false;
    }
  }, [drawWaveform, fail, isSupported, release, state]);

  const stopAndTranscribe = useCallback(() => {
    return new Promise((resolve) => {
      const recorder = recorderRef.current;
      if (!recorder || recorder.state !== 'recording') {
        resolve(null);
        return;
      }
      modeRef.current = 'submit';
      resolverRef.current = resolve;
      recorder.stop();
    });
  }, []);

  const cancelRecording = useCallback(() => {
    uploadRef.current?.abort();
    uploadRef.current = null;

    const recorder = recorderRef.current;
    if (recorder && recorder.state === 'recording') {
      modeRef.current = 'cancel';
      recorder.stop();
      return;
    }

    release();
    setState('idle');
  }, [release]);

  const clearError = useCallback(() => setError(null), []);

  return {
    isSupported,
    state,
    permission,
    bars,
    level,
    durationSec,
    error,
    lastTranscript,
    startRecording,
    stopAndTranscribe,
    cancelRecording,
    clearError,
  };
}
