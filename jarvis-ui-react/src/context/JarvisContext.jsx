import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { getApprovals } from '../api/approvals.js';
import { getLatestBriefing, requestBriefing } from '../api/briefing.js';
import { parsePitchReply, requestTenderPitch } from '../api/tenders.js';
import {
  BACKEND_STATUS,
  CORE_STATES,
  NAV_VIEWS,
} from '../config/constants.js';
import { useBackendHealth } from '../hooks/useBackendHealth.js';
import { useChat } from '../hooks/useChat.js';
import { useHostControl } from '../hooks/useHostControl.js';
import { pollJobUntilComplete } from '../hooks/useJobPolling.js';
import { useVoiceRecorder } from '../hooks/useVoiceRecorder.js';

const JarvisContext = createContext(null);

export function JarvisProvider({ children }) {
  const [activeView, setActiveView] = useState(NAV_VIEWS.COMMAND_CENTER);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  );

  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = (event) => setPrefersReducedMotion(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const { telemetry, probe, isChecking } = useBackendHealth();
  const chat = useChat();
  const voice = useVoiceRecorder();
  const host = useHostControl();

  // --- Tenders ---------------------------------------------------------------------------
  const [tenders, setTenders] = useState([]);
  const [tenderMode, setTenderMode] = useState('mock');
  const [tenderNotice, setTenderNotice] = useState('');
  const [tendersLoading, setTendersLoading] = useState(false);
  const [tendersError, setTendersError] = useState(null);
  const [selectedTenderId, setSelectedTenderId] = useState(null);

  const [pitches, setPitches] = useState({});
  const [pitchTenderId, setPitchTenderId] = useState(null);
  const [pitchError, setPitchError] = useState(null);
  const pitchControllerRef = useRef(null);

  // --- Approvals -------------------------------------------------------------------------
  const [approvals, setApprovals] = useState([]);
  const [approvalsAvailable, setApprovalsAvailable] = useState(null); // null = not checked yet
  const [approvalsNotice, setApprovalsNotice] = useState('');
  const [approvalsLoading, setApprovalsLoading] = useState(false);
  const [approvalsError, setApprovalsError] = useState(null);
  const [selectedApprovalId, setSelectedApprovalId] = useState(null);

  // --- Morning briefing ------------------------------------------------------------------
  const [briefing, setBriefing] = useState(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingError, setBriefingError] = useState(null);
  const [briefingGenerating, setBriefingGenerating] = useState(false);
  const briefingControllerRef = useRef(null);

  const applyTenders = useCallback((payload) => {
    setTenders(payload.items);
    setTenderMode(payload.mode);
    setTenderNotice(payload.notice);
    setSelectedTenderId((current) =>
      current && payload.items.some((item) => item.id === current)
        ? current
        : payload.items[0]?.id ?? null
    );
  }, []);

  const refreshTenders = useCallback(async ({ signal } = {}) => {
    setTendersLoading(true);
    setTendersError(null);
    try {
      applyTenders(await probe({ signal }));
    } catch (err) {
      if (err?.code !== 'ABORTED') {
        setTendersError(err?.message || 'The tender feed could not be loaded.');
      }
    } finally {
      setTendersLoading(false);
    }
  }, [applyTenders, probe]);

  const refreshApprovals = useCallback(async ({ signal } = {}) => {
    setApprovalsLoading(true);
    setApprovalsError(null);
    try {
      const result = await getApprovals({ signal });
      setApprovals(result.items);
      setApprovalsAvailable(result.available);
      setApprovalsNotice(result.notice || '');
      setSelectedApprovalId((current) =>
        current && result.items.some((item) => item.id === current)
          ? current
          : result.items[0]?.id ?? null
      );
    } catch (err) {
      if (err?.code !== 'ABORTED') {
        setApprovalsAvailable(false);
        setApprovalsError(err?.message || 'Pending approvals could not be loaded.');
      }
    } finally {
      setApprovalsLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function initialize() {
      setTendersLoading(true);
      setApprovalsLoading(true);
      setTendersError(null);
      setApprovalsError(null);

      const results = await Promise.allSettled([
        probe({ signal: controller.signal }),
        getApprovals({ signal: controller.signal }),
      ]);

      if (cancelled) return;

      const [tenderResult, approvalResult] = results;

      if (tenderResult.status === 'fulfilled') {
        applyTenders(tenderResult.value);
      } else if (tenderResult.reason?.code !== 'ABORTED') {
        setTendersError(tenderResult.reason?.message || 'The tender feed could not be loaded.');
      }
      setTendersLoading(false);

      if (approvalResult.status === 'fulfilled') {
        setApprovals(approvalResult.value.items);
        setApprovalsAvailable(approvalResult.value.available);
        setApprovalsNotice(approvalResult.value.notice || '');
        setSelectedApprovalId(approvalResult.value.items[0]?.id ?? null);
      } else if (approvalResult.reason?.code !== 'ABORTED') {
        setApprovalsAvailable(false);
        setApprovalsError(approvalResult.reason?.message || 'Pending approvals could not be loaded.');
      }
      setApprovalsLoading(false);
    }

    initialize();

    return () => {
      cancelled = true;
      controller.abort();
      pitchControllerRef.current?.abort();
    };
  }, [applyTenders, probe]);

  const draftPitch = useCallback(
    async (tenderId, { regenerate = false } = {}) => {
      if (!tenderId || pitchControllerRef.current || chat.isProcessing) return null;

      setPitchError(null);
      setPitchTenderId(tenderId);
      setSelectedTenderId(tenderId);

      const controller = new AbortController();
      pitchControllerRef.current = controller;

      try {
        const { jobId } = await requestTenderPitch(tenderId, {
          regenerate,
          signal: controller.signal,
        });

        const reply = await pollJobUntilComplete(jobId, { signal: controller.signal });

        const parsed = parsePitchReply(reply);
        setPitches((current) => ({
          ...current,
          [tenderId]: {
            jobId,
            parsed,
            raw: parsed ? null : reply,
            completedAt: new Date().toISOString(),
          },
        }));
        return true;
      } catch (err) {
        if (err?.code !== 'ABORTED') {
          setPitchError({
            tenderId,
            message: err?.message || 'The pitch could not be drafted.',
          });
        }
        return false;
      } finally {
        pitchControllerRef.current = null;
        setPitchTenderId(null);
      }
    },
    [chat.isProcessing]
  );

  const stopVoiceAndSend = useCallback(async () => {
    const transcript = await voice.stopAndTranscribe();
    if (!transcript) return false;
    return chat.sendMessage(transcript, { source: 'voice' });
  }, [chat, voice]);

  // --- Briefing actions ------------------------------------------------------------------
  const refreshBriefing = useCallback(async ({ signal } = {}) => {
    setBriefingLoading(true);
    setBriefingError(null);
    try {
      const latest = await getLatestBriefing({ signal });
      setBriefing(latest);
      return true;
    } catch (err) {
      if (err?.code !== 'ABORTED') {
        setBriefingError(err?.message || 'The briefing could not be loaded.');
      }
      return false;
    } finally {
      setBriefingLoading(false);
    }
  }, []);

  const generateBriefing = useCallback(async () => {
    if (briefingControllerRef.current || chat.isProcessing) return false;

    setBriefingGenerating(true);
    setBriefingError(null);

    const controller = new AbortController();
    briefingControllerRef.current = controller;

    try {
      const { jobId } = await requestBriefing({ signal: controller.signal });
      // The job's reply is the briefing text; prefer the stored copy, which is what
      // GET /briefing/latest serves and what survives a restart.
      await pollJobUntilComplete(jobId, { signal: controller.signal });
      const latest = await getLatestBriefing({ signal: controller.signal });
      setBriefing(latest);
      return true;
    } catch (err) {
      if (err?.code !== 'ABORTED') {
        setBriefingError(err?.message || 'The briefing could not be generated.');
      }
      return false;
    } finally {
      briefingControllerRef.current = null;
      setBriefingGenerating(false);
    }
  }, [chat.isProcessing]);

  useEffect(() => {
    const controller = new AbortController();
    refreshBriefing({ signal: controller.signal });
    return () => controller.abort();
  }, [refreshBriefing]);

  const mostRecentPitchError = pitchError ? pitchError.message : null;

  const coreState = useMemo(() => {
    const backendDown =
      telemetry.status === BACKEND_STATUS.DISCONNECTED ||
      telemetry.status === BACKEND_STATUS.AUTH_ERROR;

    if (backendDown || chat.error || voice.error || mostRecentPitchError) {
      return CORE_STATES.ERROR;
    }
    if (voice.state === 'recording' || voice.state === 'requesting') {
      return CORE_STATES.LISTENING;
    }
    if (pitchTenderId) {
      return CORE_STATES.EXECUTING;
    }
    if (voice.state === 'transcribing' || chat.isProcessing || briefingGenerating) {
      return CORE_STATES.PROCESSING;
    }
    return CORE_STATES.IDLE;
  }, [
    briefingGenerating,
    chat.error,
    chat.isProcessing,
    mostRecentPitchError,
    pitchTenderId,
    telemetry.status,
    voice.error,
    voice.state,
  ]);

  const selectedTender = useMemo(
    () => tenders.find((item) => item.id === selectedTenderId) ?? null,
    [selectedTenderId, tenders]
  );

  const selectedApproval = useMemo(
    () => approvals.find((item) => item.id === selectedApprovalId) ?? null,
    [approvals, selectedApprovalId]
  );

  const isBusy = chat.isProcessing || pitchTenderId !== null || briefingGenerating;

  const value = useMemo(
    () => ({
      activeView,
      setActiveView,
      prefersReducedMotion,
      coreState,
      telemetry,
      isChecking,
      refreshTenders,
      chat,
      voice,
      host,
      stopVoiceAndSend,
      tenders,
      tenderMode,
      tenderNotice,
      tendersLoading,
      tendersError,
      selectedTender,
      selectedTenderId,
      setSelectedTenderId,
      pitches,
      pitchTenderId,
      pitchError,
      clearPitchError: () => setPitchError(null),
      draftPitch,
      approvals,
      approvalsAvailable,
      approvalsNotice,
      approvalsLoading,
      approvalsError,
      selectedApproval,
      selectedApprovalId,
      setSelectedApprovalId,
      refreshApprovals,
      isBusy,
      briefing,
      briefingLoading,
      briefingError,
      briefingGenerating,
      refreshBriefing,
      generateBriefing,
    }),
    [
      activeView,
      approvals,
      approvalsAvailable,
      approvalsError,
      approvalsLoading,
      approvalsNotice,
      briefing,
      briefingError,
      briefingGenerating,
      briefingLoading,
      chat,
      coreState,
      draftPitch,
      generateBriefing,
      host,
      isBusy,
      isChecking,
      pitchError,
      pitchTenderId,
      pitches,
      prefersReducedMotion,
      refreshApprovals,
      refreshBriefing,
      refreshTenders,
      selectedApproval,
      selectedApprovalId,
      selectedTender,
      selectedTenderId,
      stopVoiceAndSend,
      telemetry,
      tenderMode,
      tenderNotice,
      tenders,
      tendersError,
      tendersLoading,
      voice,
    ]
  );

  return <JarvisContext.Provider value={value}>{children}</JarvisContext.Provider>;
}

export function useJarvis() {
  const context = useContext(JarvisContext);
  if (!context) throw new Error('useJarvis must be used inside <JarvisProvider>.');
  return context;
}
