import React from 'react';
import { ApprovalPanel } from '../components/ApprovalPanel.jsx';
import { BriefingWidget } from '../components/BriefingWidget.jsx';
import { ChatInterface } from '../components/ChatInterface.jsx';
import { JarvisCore } from '../components/JarvisCore.jsx';
import { SystemPanel } from '../components/SystemPanel.jsx';
import { TenderPanel } from '../components/TenderPanel.jsx';

export function CommandCenter() {
  return (
    <div className="layout-command">
      <div className="layout-command__left">
        <SystemPanel />
      </div>

      <div className="layout-command__center">
        <JarvisCore />
        <ChatInterface compact />
      </div>

      <div className="layout-command__right">
        <BriefingWidget />
        <TenderPanel />
        <ApprovalPanel />
      </div>
    </div>
  );
}
