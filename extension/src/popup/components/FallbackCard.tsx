// ShopSense AI — Zero-Result & Controlled Budget-Relaxation Diff View (Section 4.I)
import React, { useState } from 'react';
import { 
  Check, 
  X, 
  AlertCircle 
} from 'lucide-react';
import { FallbackSuggestion } from '../../types';

interface FallbackCardProps {
  fallback: FallbackSuggestion;
  onApproveRelaxation?: (proposedBudget?: number, relaxedConstraints?: Record<string, any>) => void;
  onKeepOriginal?: () => void;
}

export const FallbackCard: React.FC<FallbackCardProps> = ({ 
  fallback, 
  onApproveRelaxation, 
  onKeepOriginal 
}) => {
  const {
    reason,
    relaxed_constraints,
    explanation,
    original_budget,
    proposed_budget,
    price_delta,
    exact_change_made,
    remaining_unmet_requirements,
  } = fallback;

  const candidates = fallback.suggested_alternatives || (fallback as any).eligible_products || [];
  const resultKind = fallback.result_kind || 'relaxed_alternatives';
  const hasChanges = Object.keys(relaxed_constraints || {}).length > 0;
  const isEmptyResult = resultKind === 'no_valid_alternatives' || candidates.length === 0;
  const candidateLabel = resultKind === 'related_alternatives'
    ? 'Related alternatives (not exact matches):'
    : resultKind === 'exact_matches'
      ? 'Matching products:'
      : 'Products available if you approve the proposed change:';
  const formatBudget = (amount: number) => (
    `₹${amount.toLocaleString(
      'en-IN',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 },
    )}`
  );
  const formatConstraintValue = (value: unknown): string => {
    if (Array.isArray(value)) {
      return value.map(formatConstraintValue).join(', ');
    }
    if (value && typeof value === 'object') {
      return Object.entries(value)
        .map(([key, nestedValue]) => `${key.replace(/_/g, ' ')}: ${formatConstraintValue(nestedValue)}`)
        .join(', ');
    }
    return String(value);
  };
  const deltaDisplay = price_delta != null
    && price_delta !== 0
    ? `${price_delta >= 0 ? '+' : '-'}${formatBudget(Math.abs(price_delta))}`
    : null;

  const [decisionMade, setDecisionMade] = useState<'approved' | 'rejected' | null>(null);

  const handleApprove = () => {
    setDecisionMade('approved');
    if (onApproveRelaxation) {
      onApproveRelaxation(proposed_budget ?? undefined, relaxed_constraints);
    }
  };

  const handleKeep = () => {
    setDecisionMade('rejected');
    if (onKeepOriginal) {
      onKeepOriginal();
    }
  };

  return (
    <div className="fallback-card" role="region" aria-label="No exact matches found and relaxation proposal">
      {/* Header (Section 4.I) */}
      <div className="fallback-header" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <AlertCircle size={15} style={{ color: '#A65F4B', flexShrink: 0 }} />
        <span>{isEmptyResult ? 'No valid alternatives found.' : 'No exact matches found.'}</span>
      </div>

      <p className="fallback-reason">
        {reason || "None of the available products satisfy all strict constraints simultaneously."}
      </p>

      {explanation && (
        <p style={{ fontSize: '11.5px', color: '#8A8176', marginBottom: '10px' }}>
          {explanation}
        </p>
      )}

      {fallback.preserved_constraints && Object.keys(fallback.preserved_constraints).length > 0 && (
        <p style={{ fontSize: '10.5px', color: '#6B4F3A', marginBottom: '10px' }}>
          Preserved: {Object.entries(fallback.preserved_constraints)
            .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${formatConstraintValue(value)}`)
            .join('; ')}
        </p>
      )}

      {(hasChanges || (original_budget != null && proposed_budget != null && proposed_budget !== original_budget)) && (
        <table className="diff-view-table">
          <thead>
            <tr>
              <th>Constraint</th>
              <th>Original</th>
              <th>Proposed Relaxation</th>
            </tr>
          </thead>
          <tbody>
            {original_budget != null && proposed_budget != null && proposed_budget !== original_budget && (
              <tr>
                <td>Budget Ceiling</td>
                <td>{formatBudget(original_budget)}</td>
                <td>
                  <span style={{ fontWeight: 600 }}>{formatBudget(proposed_budget)}</span>
                  {deltaDisplay && <span className="diff-delta" style={{ marginLeft: '6px' }}>({deltaDisplay})</span>}
                </td>
              </tr>
            )}
            {relaxed_constraints && Object.entries(relaxed_constraints).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td style={{ color: '#A65F4B' }}>Strict requirement</td>
                <td style={{ color: '#6B4F3A', fontWeight: 600 }}>{String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {exact_change_made && (
        <p style={{ fontSize: '11px', color: '#6B4F3A', fontStyle: 'italic', marginBottom: '10px' }}>
          Suggested adjustment: {exact_change_made}
        </p>
      )}

      {/* Unlocked Products Preview Chips */}
      {candidates && candidates.length > 0 && (
        <div style={{ marginBottom: '10px' }}>
          <span style={{ fontSize: '10.5px', fontWeight: 600, color: '#8A8176', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            {candidateLabel}
          </span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
            {candidates.slice(0, 3).map((item: any, i: number) => (
              <span key={i} className="spec-chip">
                {item.product_name || item.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {remaining_unmet_requirements && remaining_unmet_requirements.length > 0 && (
        <p style={{ fontSize: '10.5px', color: '#A65F4B', marginBottom: '10px' }}>
          Note: {remaining_unmet_requirements.join(', ')}
          {resultKind !== 'no_valid_alternatives' && ' may still require consideration.'}
        </p>
      )}

      {/* User Decision Controls */}
      {decisionMade === null && candidates.length > 0 && fallback.requires_user_approval && hasChanges ? (
        <div className="fallback-actions">
          <button
            type="button"
            className="btn-approve-relaxation"
            onClick={handleApprove}
          >
            <Check size={12} style={{ marginRight: '4px', display: 'inline-block', verticalAlign: 'middle' }} />
            Approve Relaxation & Search
          </button>
          <button
            type="button"
            className="btn-keep-strict"
            onClick={handleKeep}
          >
            <X size={12} style={{ marginRight: '4px', display: 'inline-block', verticalAlign: 'middle' }} />
            Keep Strict Constraints
          </button>
        </div>
      ) : decisionMade !== null ? (
        <p style={{ fontSize: '11.5px', fontWeight: 600, color: decisionMade === 'approved' ? '#78836B' : '#6B4F3A' }}>
          {decisionMade === 'approved' ? '✓ Relaxation approved. Searching alternatives...' : 'Strict constraints preserved.'}
        </p>
      ) : null}
    </div>
  );
};

export default FallbackCard;
