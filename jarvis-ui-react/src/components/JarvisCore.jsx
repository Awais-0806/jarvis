import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle } from 'lucide-react';
import { CORE_STATES } from '../config/constants.js';
import { useJarvis } from '../context/JarvisContext.jsx';

const SUBTITLE = {
  [CORE_STATES.IDLE]: 'STANDBY · AWAITING DIRECTIVE',
  [CORE_STATES.LISTENING]: 'MICROPHONE CAPTURE ACTIVE',
  [CORE_STATES.PROCESSING]: 'CORE JOB IN PROGRESS',
  [CORE_STATES.SPEAKING]: 'AUDIO OUTPUT ACTIVE',
  [CORE_STATES.EXECUTING]: 'DRAFTING TENDER PITCH',
  [CORE_STATES.ERROR]: 'SUBSYSTEM ATTENTION REQUIRED',
};

/** Deterministic particle ring: same layout every render, no Math.random during paint. */
const PARTICLES = Array.from({ length: 18 }, (_, index) => {
  const angle = (index / 18) * Math.PI * 2;
  const radius = 46 + ((index * 7) % 9);
  return {
    left: 50 + Math.cos(angle) * radius,
    top: 50 + Math.sin(angle) * radius,
    delay: (index % 6) * 0.45,
    size: index % 3 === 0 ? 3 : 2,
  };
});

function coreTone(state) {
  if (state === CORE_STATES.ERROR) return 'error';
  if (state === CORE_STATES.LISTENING) return 'listen';
  if (state === CORE_STATES.PROCESSING) return 'process';
  if (state === CORE_STATES.EXECUTING) return 'execute';
  return 'idle';
}

export function JarvisCore({ compact = false }) {
  const {
    coreState,
    voice,
    chat,
    pitchTenderId,
    pitchError,
    prefersReducedMotion,
  } = useJarvis();

  const tone = coreTone(coreState);
  const errorText = chat.error || voice.error || pitchError?.message || null;

  const jobLabel = pitchTenderId
    ? `PITCH · ${pitchTenderId}`
    : chat.activeJobId
      ? `JOB · ${chat.activeJobId.slice(0, 12)}`
      : null;

  const level = voice.state === 'recording' ? Math.min(1, voice.level * 2.4) : 0;

  return (
    <section
      className={`core core--${tone} ${compact ? 'core--compact' : ''}`}
      data-state={coreState}
      style={{ '--levels': level.toFixed(3) }}
      aria-label={`Holographic core, state ${coreState}`}
      role="img"
    >
      <div className="core__grid" aria-hidden="true" />
      <div className="core__scan" aria-hidden="true" />

      <div className="core__stage" aria-hidden="true">
        <div className="core__halo" />
        <div className="core__ring core__ring--outer" />
        <div className="core__ring core__ring--mid" />
        <div className="core__ring core__ring--inner" />

        <svg className="core__ticks" viewBox="0 0 300 300">
          <defs>
            <path id="coreTickPath" d="M150,150 m-118,0 a118,118 0 1,1 236,0 a118,118 0 1,1 -236,0" />
          </defs>
          <text className="core__ticktext">
            <textPath href="#coreTickPath" startOffset="0%">
              JARVIS · INTEGRATED INTELLIGENCE · SECTOR 07 · LOCAL ONLY · JARVIS · COMMAND LINK ·
            </textPath>
          </text>
        </svg>

        <div className="core__sphere">
          <div className="core__sheen" />
          <div className="core__filament core__filament--a" />
          <div className="core__filament core__filament--b" />
          <div className="core__nucleus" />
        </div>

        <div className="core__orbit core__orbit--a">
          <span className="core__satellite" />
        </div>
        <div className="core__orbit core__orbit--b">
          <span className="core__satellite core__satellite--alt" />
        </div>

        <div className="core__particles">
          {PARTICLES.map((particle, index) => (
            <span
              key={index}
              className="core__particle"
              style={{
                left: `${particle.left}%`,
                top: `${particle.top}%`,
                width: particle.size,
                height: particle.size,
                animationDelay: `${particle.delay}s`,
              }}
            />
          ))}
        </div>
      </div>

      <div className="core__readout">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={coreState}
            className="core__badge"
            initial={prefersReducedMotion ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={prefersReducedMotion ? undefined : { opacity: 0, y: -4 }}
            transition={{ duration: 0.22 }}
          >
            {coreState === CORE_STATES.ERROR && <AlertCircle size={12} />}
            <span>{coreState}</span>
          </motion.div>
        </AnimatePresence>

        <p className="core__subtitle">{SUBTITLE[coreState]}</p>
        {jobLabel && <p className="core__job mono">{jobLabel}</p>}
        {coreState === CORE_STATES.ERROR && errorText && (
          <p className="core__error" role="status">
            {errorText}
          </p>
        )}
      </div>
    </section>
  );
}
