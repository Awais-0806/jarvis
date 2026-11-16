import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

/**
 * Catches render errors so one broken panel cannot blank the whole command center.
 * The fallback is deliberately plain: it must not depend on anything that could also fail.
 */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false, message: '' };
  }

  static getDerivedStateFromError(error) {
    return { failed: true, message: error?.message || 'Unknown rendering error.' };
  }

  componentDidCatch(error, info) {
    // Keep the console useful without ever logging message contents or tokens.
    console.error('[jarvis-ui] render error', error?.name, info?.componentStack);
  }

  reset = () => this.setState({ failed: false, message: '' });

  render() {
    if (!this.state.failed) return this.props.children;

    if (this.props.fallback) {
      return typeof this.props.fallback === 'function'
        ? this.props.fallback({ message: this.state.message, reset: this.reset })
        : this.props.fallback;
    }

    return (
      <div className="panel panel--error" role="alert">
        <div className="panel__headline panel__headline--error">
          <AlertTriangle size={16} />
          <span>{this.props.title || 'Interface fault'}</span>
        </div>
        <p className="muted">{this.state.message}</p>
        <button type="button" className="btn btn--ghost btn--sm" onClick={this.reset}>
          <RotateCcw size={13} />
          <span>Recover module</span>
        </button>
      </div>
    );
  }
}
