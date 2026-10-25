// ShopSense AI — Minimalist Luxury Product Comparison Modal (Section 4.F)
import React, { useEffect, useState } from 'react';
import { 
  X, 
  SlidersHorizontal, 
  AlertCircle, 
  Sparkles, 
  Loader2, 
  Trash2, 
  Check, 
  X as XMark
} from 'lucide-react';
import { CompareResponse } from '../../types';
import apiClient from '../../services/api';

interface CompareModalProps {
  productIds: string[];
  sessionId: string;
  onClose: () => void;
  onRemoveProduct: (productId: string) => void;
  onClearAll: () => void;
}

export const CompareModal: React.FC<CompareModalProps> = ({
  productIds,
  sessionId,
  onClose,
  onRemoveProduct,
  onClearAll,
}) => {
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const clampedIds = productIds.slice(0, 3);

    if (clampedIds.length < 2) {
      setError('Select at least 2 products to compare.');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    apiClient
      .compareProducts(clampedIds, sessionId)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to generate side-by-side comparison');
        setLoading(false);
      });
  }, [productIds, sessionId]);

  // Find the top scoring product
  const maxScore = data && data.products.length > 0 
    ? Math.max(...data.products.map(p => p.fit_score || 0)) 
    : 0;

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="drawer-content" onClick={(e) => e.stopPropagation()} style={{ maxHeight: '88vh' }}>
        {/* Header */}
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <SlidersHorizontal size={16} style={{ color: '#B08D57' }} />
            <h2 className="drawer-title">
              Product Comparison ({Math.min(productIds.length, 3)} items)
            </h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              type="button"
              className="btn-header-action"
              onClick={onClearAll}
              title="Clear all compared items"
              style={{ padding: '4px 8px', fontSize: '11px' }}
            >
              <Trash2 size={11} />
              <span>Clear</span>
            </button>
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
        </div>

        {/* Body */}
        <div className="drawer-body">
          {loading && (
            <div style={{ padding: '32px 16px', textAlign: 'center', color: '#8A8176' }}>
              <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', marginBottom: '8px', color: '#B08D57' }} />
              <p style={{ fontSize: '12px' }}>Evaluating specifications, constraints, and fit-score breakdowns...</p>
            </div>
          )}

          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px', background: 'rgba(166, 95, 75, 0.08)', borderRadius: '6px', color: '#A65F4B', fontSize: '12px' }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && data && (
            <div>
              {/* Concierge Summary (Section 4.F) */}
              {data.recommendation_summary && (
                <div style={{ background: '#FAF7F0', borderLeft: '3px solid #B08D57', padding: '10px 12px', borderRadius: '0 6px 6px 0', marginBottom: '14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', fontSize: '11px', fontWeight: 600, color: '#B08D57', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    <Sparkles size={12} />
                    <span>Concierge Comparison Summary</span>
                  </div>
                  <p style={{ fontSize: '12.5px', lineHeight: 1.4, color: '#24221F' }}>
                    {data.recommendation_summary}
                  </p>
                </div>
              )}

              {/* Side-by-Side Columns */}
              <div className="comparison-grid-3">
                {data.products.slice(0, 3).map((item) => {
                  const isBestFit = maxScore > 0 && item.fit_score === maxScore && data.products.length > 1;
                  return (
                    <div 
                      key={item.product_id} 
                      className={`comparison-col ${isBestFit ? 'best-match' : ''}`}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        {isBestFit ? (
                          <span className="best-fit-tag">Best fit</span>
                        ) : (
                          <span style={{ fontSize: '10px', color: '#8A8176' }}>{item.brand}</span>
                        )}
                        <button
                          type="button"
                          onClick={() => onRemoveProduct(item.product_id)}
                          style={{ background: 'none', border: 'none', color: '#8A8176', cursor: 'pointer', padding: '2px' }}
                          title="Remove from comparison"
                        >
                          <X size={11} />
                        </button>
                      </div>

                      <h4 style={{ fontFamily: 'var(--font-heading)', fontSize: '12.5px', fontWeight: 600, color: '#24221F', margin: '2px 0 4px', lineHeight: 1.3 }}>
                        {item.product_name}
                      </h4>

                      <div style={{ fontSize: '14px', fontWeight: 700, color: '#24221F' }}>
                        {item.currency === 'INR' ? '₹' : '$'}{item.price.toLocaleString()}
                      </div>

                      {/* Fit Score Badge */}
                      {item.fit_score != null && (
                        <div style={{ fontSize: '11px', fontWeight: 600, color: '#78836B', background: 'rgba(120, 131, 107, 0.12)', padding: '2px 6px', borderRadius: '4px', alignSelf: 'flex-start' }}>
                          {Math.round(item.fit_score)}% Fit
                        </div>
                      )}

                      {/* Hard Constraints */}
                      <div style={{ marginTop: '6px', paddingTop: '6px', borderTop: '1px solid #E9E0D2' }}>
                        <span style={{ fontSize: '10px', fontWeight: 600, color: '#8A8176', textTransform: 'uppercase' }}>Constraints</span>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginTop: '3px', fontSize: '11px' }}>
                          {item.hard_constraint_satisfaction && Object.entries(item.hard_constraint_satisfaction).map(([k, satisfied]) => (
                            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: '4px', color: satisfied ? '#78836B' : '#A65F4B' }}>
                              {satisfied ? <Check size={11} /> : <XMark size={11} />}
                              <span>{k}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Advantages */}
                      {((item.advantages && item.advantages.length > 0) || (item.highlights && item.highlights.length > 0)) && (
                        <div style={{ marginTop: '6px', paddingTop: '6px', borderTop: '1px solid #E9E0D2', fontSize: '11px' }}>
                          <span style={{ fontSize: '10px', fontWeight: 600, color: '#78836B', textTransform: 'uppercase' }}>Advantages</span>
                          <ul style={{ paddingLeft: '14px', margin: '2px 0 0', color: '#24221F', lineHeight: 1.35 }}>
                            {(item.advantages || item.highlights || []).map((adv: string, i: number) => (
                              <li key={i}>{adv}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Trade-offs */}
                      {item.trade_offs && item.trade_offs.length > 0 && (
                        <div style={{ marginTop: '6px', paddingTop: '6px', borderTop: '1px solid #E9E0D2', fontSize: '11px' }}>
                          <span style={{ fontSize: '10px', fontWeight: 600, color: '#8A8176', textTransform: 'uppercase' }}>Considerations</span>
                          <ul style={{ paddingLeft: '14px', margin: '2px 0 0', color: '#8A8176', lineHeight: 1.35 }}>
                            {item.trade_offs.map((to, i) => (
                              <li key={i}>{to}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CompareModal;
