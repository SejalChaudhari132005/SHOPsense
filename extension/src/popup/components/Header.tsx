// ShopSense AI — Minimalist Luxury Concierge Header (Section 4.A)
import React from 'react';
import { 
  SlidersHorizontal, 
  RotateCcw,
  Settings,
  RefreshCw,
  ExternalLink
} from 'lucide-react';
import { BackendHealth, PageContext } from '../../types';
import CompassLogo from './CompassLogo';

interface HeaderProps {
  health: BackendHealth | null;
  isConnecting: boolean;
  comparedCount: number;
  onOpenCompare: () => void;
  onOpenRefine: () => void;
  onOpenPreferences?: () => void;
  onResetSession: () => void;
  onRefreshTab?: () => void;
  pageContext: PageContext | null;
  onIncorporatePageContext?: (context: PageContext) => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  isConnecting,
  comparedCount,
  onOpenCompare,
  onOpenRefine: _onOpenRefine,
  onOpenPreferences,
  onResetSession,
  onRefreshTab,
  pageContext,
  onIncorporatePageContext,
}) => {
  return (
    <header className="extension-header">
      {/* Top Brand & Actions Row */}
      <div className="header-top-row">
        <div className="brand-badge-group">
          <div className="brand-icon-wrapper" title="ShopSense AI Concierge">
            <CompassLogo size={20} className="luxury-compass-logo" />
          </div>
          <div className="brand-text-col">
            <h1 className="brand-name">
              <span>ShopSense</span>
              <span className="ai-tag">AI</span>
            </h1>
            <span className="brand-tagline">Your personal shopping guide</span>
          </div>
        </div>

        {/* Right Action Controls */}
        <div className="header-actions">
          {/* Scan Page Button */}
          {onRefreshTab && (
            <button
              type="button"
              className="btn-header-action"
              onClick={onRefreshTab}
              title="Scan active browser tab for product details"
              aria-label="Scan active tab"
            >
              <RefreshCw size={12} />
              <span>Scan</span>
            </button>
          )}

          {/* Compare Button */}
          <button
            type="button"
            className={`btn-header-action ${comparedCount > 0 ? 'highlighted' : ''}`}
            onClick={onOpenCompare}
            title={comparedCount > 0 ? `Compare ${comparedCount} selected products` : 'Compare products'}
            aria-label="Compare products"
          >
            <SlidersHorizontal size={13} />
            {comparedCount > 0 && <span className="counter-badge">{comparedCount}</span>}
          </button>

          {/* Subtle Settings / Preferences Icon */}
          {onOpenPreferences && (
            <button
              type="button"
              className="btn-header-action"
              onClick={onOpenPreferences}
              title="Shopping preferences and memory settings"
              aria-label="Settings and preferences"
            >
              <Settings size={13} />
            </button>
          )}

          {/* Reset Conversation */}
          <button
            type="button"
            className="btn-header-action"
            onClick={onResetSession}
            title="Start new shopping request"
            aria-label="Reset conversation"
          >
            <RotateCcw size={12} />
          </button>
        </div>
      </div>

      {/* Sub-bar: Discreet Status & Page Attribution */}
      <div className="header-status-bar">
        {/* Discreet Status Indicator (Section 4.A) */}
        <div className="connection-indicator">
          {isConnecting ? (
            <span className="status-pill status-connecting">Connecting...</span>
          ) : health ? (
            <span className="status-pill status-online" title="10-agent concierge active and ready">
              Active concierge
            </span>
          ) : (
            <span className="status-pill status-offline" title="FastAPI server offline">
              Offline
            </span>
          )}
        </div>

        {/* Active Tab Page Attribution */}
        {pageContext && pageContext.supported && pageContext.isProductPage && (
          <div className="page-context-pill">
            <span className="context-store-tag">Viewing {pageContext.host.replace(/^www\./, '')}</span>
            {onIncorporatePageContext && (
              <button
                type="button"
                className="btn-context-ask"
                onClick={() => onIncorporatePageContext(pageContext)}
                title="Ask ShopSense about this page's product"
              >
                <span>Evaluate</span>
                <ExternalLink size={9} />
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
};

export default Header;
