// ShopSense AI — Minimalist App Footer (Section 4.J)
import React from 'react';

interface AppFooterProps {
  onResetSession: () => void;
  onOpenPreferences?: () => void;
  dataSourceLabel?: string;
}

export const AppFooter: React.FC<AppFooterProps> = ({
  onResetSession,
  onOpenPreferences,
  dataSourceLabel = 'Curated Store Feeds',
}) => {
  return (
    <footer className="app-footer" role="contentinfo">
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span className="footer-brand">ShopSense AI</span>
        <span>&bull;</span>
        <span style={{ fontSize: '10.5px' }}>{dataSourceLabel}</span>
      </div>

      <div className="footer-actions">
        <button
          type="button"
          className="footer-link"
          onClick={onResetSession}
          title="Clear current conversation"
        >
          Reset
        </button>
        {onOpenPreferences && (
          <button
            type="button"
            className="footer-link"
            onClick={onOpenPreferences}
            title="Privacy and storage preferences"
          >
            Preferences
          </button>
        )}
      </div>
    </footer>
  );
};

export default AppFooter;
