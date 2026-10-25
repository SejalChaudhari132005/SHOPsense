// ShopSense AI — Constraint Refinement Drawer
// Enables interactive constraint adjustments (budget, color, size, brand, preferences)

import React, { useState } from 'react';
import { X, SlidersHorizontal, Check, RefreshCw } from 'lucide-react';
import { RefineRequest } from '../../types';

interface RefinementDrawerProps {
  sessionId: string;
  onClose: () => void;
  onApplyRefine: (refineData: RefineRequest) => void;
  isLoading: boolean;
}

export const RefinementDrawer: React.FC<RefinementDrawerProps> = ({
  sessionId,
  onClose,
  onApplyRefine,
  isLoading,
}) => {
  const [budgetMax, setBudgetMax] = useState<number | ''>('');
  const [colour, setColour] = useState<string>('');
  const [brand, setBrand] = useState<string>('');
  const [selectedPreferences, setSelectedPreferences] = useState<string[]>([]);

  const commonPreferences = [
    'lightweight',
    'waterproof',
    'noise cancelling',
    'long battery life',
    'wireless',
    'compact',
    'durable',
    'cushioned',
  ];

  const togglePreference = (pref: string) => {
    if (selectedPreferences.includes(pref)) {
      setSelectedPreferences(selectedPreferences.filter((p) => p !== pref));
    } else {
      setSelectedPreferences([...selectedPreferences, pref]);
    }
  };

  const handleApply = (e: React.FormEvent) => {
    e.preventDefault();
    const payload: RefineRequest = {
      session_id: sessionId,
      message: 'Refining constraints for better match',
    };

    if (budgetMax !== '') {
      payload.new_budget_max = Number(budgetMax);
    }
    if (colour.trim()) {
      payload.new_colour = colour.trim();
    }
    if (brand.trim()) {
      payload.new_brand = brand.trim();
    }
    if (selectedPreferences.length > 0) {
      payload.added_preferences = selectedPreferences;
    }

    onApplyRefine(payload);
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-sheet refine-sheet" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <SlidersHorizontal size={18} className="modal-icon" />
            <h2 className="modal-title">Refine Constraints</h2>
          </div>
          <button
            type="button"
            className="btn-icon-close"
            onClick={onClose}
            title="Close refinement drawer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleApply} className="refine-form">
          <div className="modal-body">
            {/* Budget Adjustment */}
            <div className="form-group">
              <label htmlFor="refine-budget" className="form-label">
                Maximum Budget (USD)
              </label>
              <div className="input-prefix-wrapper">
                <span className="input-prefix">$</span>
                <input
                  id="refine-budget"
                  type="number"
                  min="0"
                  step="10"
                  className="form-input prefix-padding"
                  placeholder="e.g. 500"
                  value={budgetMax}
                  onChange={(e) => setBudgetMax(e.target.value === '' ? '' : Number(e.target.value))}
                />
              </div>
              <div className="quick-budget-chips">
                {[150, 300, 500, 1000, 1500].map((amt) => (
                  <button
                    key={amt}
                    type="button"
                    className={`chip-btn ${budgetMax === amt ? 'active' : ''}`}
                    onClick={() => setBudgetMax(amt)}
                  >
                    Under ${amt}
                  </button>
                ))}
              </div>
            </div>

            {/* Brand Filter */}
            <div className="form-group">
              <label htmlFor="refine-brand" className="form-label">
                Brand Preference
              </label>
              <input
                id="refine-brand"
                type="text"
                className="form-input"
                placeholder="e.g. Sony, Apple, Bose, Nike..."
                value={brand}
                onChange={(e) => setBrand(e.target.value)}
              />
            </div>

            {/* Color Filter */}
            <div className="form-group">
              <label htmlFor="refine-colour" className="form-label">
                Color
              </label>
              <input
                id="refine-colour"
                type="text"
                className="form-input"
                placeholder="e.g. Black, White, Silver, Midnight..."
                value={colour}
                onChange={(e) => setColour(e.target.value)}
              />
            </div>

            {/* Feature Preferences */}
            <div className="form-group">
              <label className="form-label">Desired Soft Preferences</label>
              <div className="pref-chips-grid">
                {commonPreferences.map((pref) => {
                  const isSelected = selectedPreferences.includes(pref);
                  return (
                    <button
                      key={pref}
                      type="button"
                      className={`pref-chip ${isSelected ? 'active' : ''}`}
                      onClick={() => togglePreference(pref)}
                    >
                      {isSelected && <Check size={12} />}
                      <span>{pref}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="modal-footer">
            <button
              type="button"
              className="btn-secondary"
              onClick={onClose}
              disabled={isLoading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <RefreshCw size={14} className="spinner-icon" />
                  <span>Updating...</span>
                </>
              ) : (
                <span>Apply Refinements</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RefinementDrawer;
