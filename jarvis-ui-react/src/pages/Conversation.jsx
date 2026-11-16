import React from 'react';
import { ChatInterface } from '../components/ChatInterface.jsx';
import { JarvisCore } from '../components/JarvisCore.jsx';

export function Conversation() {
  return (
    <div className="layout-split">
      <div className="layout-split__aside">
        <JarvisCore compact />
      </div>
      <div className="layout-split__main">
        <ChatInterface />
      </div>
    </div>
  );
}
