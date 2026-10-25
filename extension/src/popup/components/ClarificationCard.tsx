// ShopSense AI — Minimalist Clarification Card (Section 4.D)
import React, { useState } from 'react';
import { HelpCircle } from 'lucide-react';
import { ClarificationDecision } from '../../types';

interface ClarificationCardProps {
  clarification: ClarificationDecision;
  onSelectOption: (option: string) => void;
}

export const ClarificationCard: React.FC<ClarificationCardProps> = ({
  clarification,
  onSelectOption,
}) => {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);

  const { 
    clarification_question, 
    suggested_options, 
  } = clarification;

  const handleSelect = (option: string) => {
    setSelectedOption(option);
    onSelectOption(option);
  };

  return (
    <div className="clarification-card" role="region" aria-label="Clarification inquiry">
      <div className="clarification-question">
        <HelpCircle size={14} style={{ color: '#B08D57', flexShrink: 0 }} />
        <span>{clarification_question || "Could you clarify a preference to help narrow down the best match?"}</span>
      </div>

      {/* 2 to 3 Compact Selectable Options (Section 4.D) */}
      {suggested_options && suggested_options.length > 0 && (
        <div className="clarification-options-grid">
          {suggested_options.slice(0, 4).map((option, idx) => {
            const isSelected = selectedOption === option;
            return (
              <button
                key={idx}
                type="button"
                className={`clarification-opt-btn ${isSelected ? 'selected' : ''}`}
                onClick={() => handleSelect(option)}
                aria-pressed={isSelected}
              >
                {option}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ClarificationCard;
