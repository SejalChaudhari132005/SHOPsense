// ShopSense AI — Minimalist Luxury Why Not Explanation (Section 4.G)
import React, { useEffect, useState } from 'react';
import { 
  X, 
  HelpCircle, 
  AlertCircle, 
  AlertTriangle, 
  Loader2, 
  ArrowRight,
  Sliders,
  GitCompare
} from 'lucide-react';
import { WhyNotResponse, ProductRecommendation } from '../../types';
import apiClient from '../../services/api';
import { formatPriceInINR } from '../../services/currency';

interface WhyNotModalProps {
  productId: string;
  productName: string;
  sessionId: string;
  onClose: () => void;
  onSelectAlternative?: (altId: string) => void;
  availableRecommendations?: ProductRecommendation[];
}

export const WhyNotModal: React.FC<WhyNotModalProps> = ({
  productId,
  productName,
  sessionId,
  onClose,
  onSelectAlternative: _onSelectAlternative,
  availableRecommendations = [],
}) => {
  const [data, setData] = useState<WhyNotResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCompareId, setSelectedCompareId] = useState<string>(
    availableRecommendations[0]?.product?.product_id || ''
  );

  const fetchAnalysis = (compareId?: string) => {
    setLoading(true);
    setError(null);

    apiClient
      .getWhyNotAnalysis(productId, sessionId, compareId || undefined)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to analyze product constraints');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchAnalysis(selectedCompareId);
  }, [productId, sessionId]);

  const handleCompareChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newId = e.target.value;
    setSelectedCompareId(newId);
    fetchAnalysis(newId);
  };

  const getStatusLabel = (status?: string) => {
    switch (status) {
      case 'excluded':
        return { text: 'Excluded: Hard Constraint Violation', color: '#A65F4B', bg: 'rgba(166, 95, 75, 0.10)' };
      case 'ranked_lower':
        return { text: 'Ranked Lower: Eligible but Lower Fit Score', color: '#6B4F3A', bg: 'rgba(107, 79, 58, 0.10)' };
      case 'possible_alternative':
        return { text: 'Possible Alternative: Strong Match', color: '#78836B', bg: 'rgba(120, 131, 107, 0.12)' };
      case 'not_retrieved':
        return { text: 'Not Retrieved in Initial Search', color: '#8A8176', bg: 'rgba(138, 129, 118, 0.10)' };
      default:
        return { text: 'Evaluated Candidate', color: '#24221F', bg: '#FAF7F0' };
    }
  };

  const statusInfo = getStatusLabel(data?.rejection_status);

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="drawer-content" onClick={(e) => e.stopPropagation()} style={{ maxHeight: '88vh' }}>
        {/* Header */}
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <HelpCircle size={16} style={{ color: '#B08D57' }} />
            <h2 className="drawer-title">Why wasn't this recommended?</h2>
          </div>
          <button
            type="button"
            className="btn-drawer-close"
            onClick={onClose}
            title="Close modal"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="drawer-body">
          {/* Candidate Under Scrutiny Bar */}
          <div style={{ background: '#FAF7F0', border: '1px solid #E9E0D2', borderRadius: '8px', padding: '10px 12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '8px' }}>
              <div>
                <span style={{ fontSize: '10.5px', color: '#8A8176', textTransform: 'uppercase', letterSpacing: '0.04em', display: 'block' }}>Candidate Product:</span>
                <strong style={{ fontSize: '13px', color: '#24221F' }}>{productName}</strong>
              </div>
              <span style={{ fontSize: '11px', fontWeight: 600, color: statusInfo.color, background: statusInfo.bg, padding: '3px 8px', borderRadius: '4px' }}>
                {statusInfo.text}
              </span>
            </div>
          </div>

          {/* Compare Against Recommendation Selector */}
          {availableRecommendations.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: '#8A8176' }}>
              <GitCompare size={12} style={{ color: '#B08D57' }} />
              <span>Compare against:</span>
              <select
                value={selectedCompareId}
                onChange={handleCompareChange}
                style={{ flex: 1, padding: '4px 8px', fontSize: '11px', borderRadius: '4px', border: '1px solid #E9E0D2', background: '#FFFDF8', color: '#24221F' }}
              >
                {availableRecommendations.map((rec) => (
                  <option key={rec.product.product_id} value={rec.product.product_id}>
                    {rec.product.brand} - {rec.product.product_name} ({formatPriceInINR(rec.product.price, rec.product.currency)})
                  </option>
                ))}
              </select>
            </div>
          )}

          {loading && (
            <div style={{ padding: '32px 16px', textAlign: 'center', color: '#8A8176' }}>
              <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', marginBottom: '8px', color: '#B08D57' }} />
              <p style={{ fontSize: '12px' }}>Analyzing candidate against catalog constraints and criteria...</p>
            </div>
          )}

          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px', background: 'rgba(166, 95, 75, 0.08)', borderRadius: '6px', color: '#A65F4B', fontSize: '12px' }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && data && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {/* Verdict Explanation (Section 4.G) */}
              <div style={{ background: '#FFFDF8', borderLeft: '3px solid #6B4F3A', padding: '10px 12px', borderRadius: '0 6px 6px 0', border: '1px solid #E9E0D2', borderLeftWidth: '3px' }}>
                <p style={{ fontSize: '12.5px', lineHeight: 1.45, color: '#24221F' }}>
                  {data.explanation}
                </p>
              </div>

              {/* Violated Constraints */}
              {data.violated_hard_constraints && data.violated_hard_constraints.length > 0 && (
                <div style={{ background: 'rgba(166, 95, 75, 0.06)', border: '1px solid rgba(166, 95, 75, 0.2)', borderRadius: '8px', padding: '10px 12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#A65F4B', fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', marginBottom: '4px' }}>
                    <AlertTriangle size={12} />
                    <span>Failed Constraints:</span>
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '12px', color: '#24221F', lineHeight: 1.4 }}>
                    {data.violated_hard_constraints.map((v, i) => (
                      <li key={i}>{v}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* What Would Need to Change */}
              {((data.what_needs_to_change && data.what_needs_to_change.length > 0) || 
                (data.changes_needed_for_eligibility && data.changes_needed_for_eligibility.length > 0)) && (
                <div style={{ background: '#FAF7F0', border: '1px solid #E9E0D2', borderRadius: '8px', padding: '10px 12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#6B4F3A', fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', marginBottom: '4px' }}>
                    <Sliders size={12} />
                    <span>What would need to change:</span>
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '12px', color: '#24221F', lineHeight: 1.4 }}>
                    {(data.what_needs_to_change || data.changes_needed_for_eligibility || []).map((c: string, i: number) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Comparison with Recommended Alternative */}
              {(data.recommended_comparison || data.compared_product) && (() => {
                const comp: any = data.recommended_comparison || data.compared_product;
                return (
                  <div style={{ background: '#FFFDF8', border: '1px solid #E9E0D2', borderRadius: '8px', padding: '10px 12px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 600, color: '#B08D57', textTransform: 'uppercase', display: 'block', marginBottom: '4px' }}>
                      Comparison with Recommended Choice:
                    </span>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', fontSize: '12px', color: '#24221F', marginBottom: '4px' }}>
                      {comp.candidate_price && <span>Candidate: {formatPriceInINR(comp.candidate_price, 'INR')}</span>}
                      {comp.recommended_price && <ArrowRight size={11} style={{ color: '#8A8176' }} />}
                      {comp.recommended_price && (
                        <span style={{ fontWeight: 600, color: '#78836B' }}>
                          Recommended: {formatPriceInINR(comp.recommended_price, 'INR')} {comp.recommended_name ? `(${comp.recommended_name})` : ''}
                        </span>
                      )}
                    </div>
                    {comp.trade_off_summary && (
                      <p style={{ fontSize: '11.5px', color: '#8A8176', margin: 0 }}>
                        {comp.trade_off_summary}
                      </p>
                    )}
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default WhyNotModal;
