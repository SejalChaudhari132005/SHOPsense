// ShopSense AI — Welcome & Query Suggestion Chips (Section 4.C)
import React from 'react';
import { ArrowUpRight } from 'lucide-react';
import CompassLogo from './CompassLogo';

interface EmptyStateProps {
  onSelectPrompt: (prompt: string) => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ onSelectPrompt }) => {
  const samplePrompts = [
    {
      category: 'Laptops',
      text: 'Best laptop for coding under ₹60,000',
    },
    {
      category: 'Comparison',
      text: 'Compare this with alternatives',
    },
    {
      category: 'Budget Value',
      text: 'Find something more affordable',
    },
    {
      category: 'Audio',
      text: 'Best everyday headphones',
    },
  ];

  return (
    <div className="empty-state-container" role="region" aria-label="Welcome concierge">
      <div className="hero-badge">
        <CompassLogo size={14} />
        <span>Personal Shopping Concierge</span>
      </div>

      <h2 className="hero-title">What are you looking for today?</h2>
      <p className="hero-subtitle">
        Describe your budget, specifications, or preferred aesthetic in natural language. I’ll search across stores, check hard constraints, and curate verified recommendations.
      </p>

      {/* Suggested Query Chips (Section 4.C) */}
      <div className="quick-prompts-section">
        <span className="prompts-heading">Suggested inquiries</span>
        <div className="prompts-grid">
          {samplePrompts.map((p, idx) => (
            <button
              key={idx}
              type="button"
              className="sample-prompt-card"
              onClick={() => onSelectPrompt(p.text)}
              aria-label={`Ask: ${p.text}`}
            >
              <div className="prompt-content">
                <span className="prompt-category">{p.category}</span>
                <span className="prompt-text">“{p.text}”</span>
              </div>
              <ArrowUpRight size={13} className="prompt-arrow" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default EmptyState;
