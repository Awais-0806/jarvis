import React from 'react';
import {
  Globe2,
  LayoutDashboard,
  MessageSquare,
  Mic,
  MonitorSmartphone,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { NAV_VIEWS } from '../config/constants.js';
import { useJarvis } from '../context/JarvisContext.jsx';

const ITEMS = [
  { id: NAV_VIEWS.COMMAND_CENTER, label: 'Command Center', tag: 'HUD', Icon: LayoutDashboard },
  { id: NAV_VIEWS.CONVERSATION, label: 'AI Conversation', tag: 'CHAT', Icon: MessageSquare },
  { id: NAV_VIEWS.VOICE, label: 'Voice Interface', tag: 'MIC', Icon: Mic },
  { id: NAV_VIEWS.TENDERS, label: 'Global Tenders', tag: 'INTEL', Icon: Globe2 },
  { id: NAV_VIEWS.APPROVALS, label: 'Pending Approvals', tag: 'HITL', Icon: ShieldCheck },
  { id: NAV_VIEWS.REMOTE_CONTROL, label: 'Remote Control', tag: 'HOST', Icon: MonitorSmartphone },
  { id: NAV_VIEWS.SETTINGS, label: 'Application Settings', tag: 'SYS', Icon: SlidersHorizontal },
];

export function Sidebar({ open, onClose }) {
  const { activeView, setActiveView, tenders, approvals } = useJarvis();

  const select = (id) => {
    setActiveView(id);
    onClose();
  };

  return (
    <>
      {open && <button className="sidebar-scrim" onClick={onClose} aria-label="Close navigation" />}
      <aside className={`sidebar ${open ? 'sidebar--open' : ''}`} aria-label="Primary navigation">
        <div className="sidebar__head">
          <span className="eyebrow">NAVIGATION</span>
          <button type="button" className="icon-btn sidebar__close" onClick={onClose} aria-label="Close navigation">
            <X size={16} />
          </button>
        </div>

        <nav className="nav">
          {ITEMS.map(({ id, label, tag, Icon }) => {
            const active = activeView === id;
            const count =
              id === NAV_VIEWS.TENDERS
                ? tenders.length
                : id === NAV_VIEWS.APPROVALS
                  ? approvals.length
                  : null;

            return (
              <button
                key={id}
                type="button"
                className={`nav__item ${active ? 'nav__item--active' : ''}`}
                onClick={() => select(id)}
                aria-current={active ? 'page' : undefined}
              >
                <Icon size={16} className="nav__icon" />
                <span className="nav__label">{label}</span>
                {count ? (
                  <span className="nav__count">{count}</span>
                ) : (
                  <span className="nav__tag">{tag}</span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="sidebar__foot">
          <span className="eyebrow">SECURITY MODE</span>
          <p className="sidebar__note">
            Bearer token injected by the proxy. Human review only — nothing is sent automatically.
          </p>
        </div>
      </aside>
    </>
  );
}
