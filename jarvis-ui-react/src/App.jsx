import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { ErrorBoundary } from './components/ErrorBoundary.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { TopBar } from './components/TopBar.jsx';
import { BACKEND_STATUS, NAV_VIEWS } from './config/constants.js';
import { JarvisProvider, useJarvis } from './context/JarvisContext.jsx';
import { Approvals } from './pages/Approvals.jsx';
import { CommandCenter } from './pages/CommandCenter.jsx';
import { Conversation } from './pages/Conversation.jsx';
import { RemoteControlPage } from './pages/RemoteControlPage.jsx';
import { Settings } from './pages/Settings.jsx';
import { Tenders } from './pages/Tenders.jsx';
import { Voice } from './pages/Voice.jsx';

function View({ view }) {
  switch (view) {
    case NAV_VIEWS.CONVERSATION:
      return <Conversation />;
    case NAV_VIEWS.VOICE:
      return <Voice />;
    case NAV_VIEWS.TENDERS:
      return <Tenders />;
    case NAV_VIEWS.APPROVALS:
      return <Approvals />;
    case NAV_VIEWS.REMOTE_CONTROL:
      return <RemoteControlPage />;
    case NAV_VIEWS.SETTINGS:
      return <Settings />;
    case NAV_VIEWS.COMMAND_CENTER:
    default:
      return <CommandCenter />;
  }
}

function BackendBanner() {
  const { telemetry, isChecking, refreshTenders } = useJarvis();

  const offline = telemetry.status === BACKEND_STATUS.DISCONNECTED;
  const authFailed = telemetry.status === BACKEND_STATUS.AUTH_ERROR;
  if (!offline && !authFailed) return null;

  return (
    <div className={`banner ${authFailed ? 'banner--error' : 'banner--warn'}`} role="alert">
      <AlertTriangle size={14} />
      <span className="grow">
        {authFailed
          ? 'The core rejected the proxy token. Check JARVIS_API_TOKEN in .env.local (dev) or the core_api_token secret (container).'
          : 'Jarvis core is unreachable. Start the stack, then retry. Panels show their real state meanwhile.'}
      </span>
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        onClick={() => refreshTenders()}
        disabled={isChecking}
      >
        <RefreshCw size={12} className={isChecking ? 'spin' : ''} />
        <span>Retry</span>
      </button>
    </div>
  );
}

function Shell() {
  const { activeView, prefersReducedMotion } = useJarvis();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    // Close the drawer whenever the view changes (including keyboard navigation).
    setNavOpen(false);
  }, [activeView]);

  return (
    <div className="app">
      <div className="app__grid" aria-hidden="true" />
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <TopBar onMenu={() => setNavOpen(true)} />

      <div className="workspace">
        <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />

        <main className="main" id="main" tabIndex={-1}>
          <BackendBanner />

          <ErrorBoundary title="View failed to render">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={activeView}
                initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={prefersReducedMotion ? undefined : { opacity: 0, y: -6 }}
                transition={{ duration: prefersReducedMotion ? 0 : 0.18, ease: 'easeOut' }}
              >
                <View view={activeView} />
              </motion.div>
            </AnimatePresence>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary title="J.A.R.V.I.S. shell failure">
      <JarvisProvider>
        <Shell />
      </JarvisProvider>
    </ErrorBoundary>
  );
}
