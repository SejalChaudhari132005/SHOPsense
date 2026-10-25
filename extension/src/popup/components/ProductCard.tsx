// ShopSense AI — Minimalist Luxury Product Card (Section 4.E)
import React, { useState } from 'react';
import { 
  ExternalLink, 
  ChevronDown, 
  ChevronUp, 
  AlertTriangle, 
  Tag
} from 'lucide-react';
import { ProductRecommendation } from '../../types';

interface ProductCardProps {
  recommendation: ProductRecommendation;
  onCompareToggle?: (productId: string) => void;
  isCompared?: boolean;
  onWhyNotClick?: (productId: string, productName: string) => void;
  isTopPick?: boolean;
}

export const ProductCard: React.FC<ProductCardProps> = ({
  recommendation,
  onCompareToggle,
  isCompared = false,
  onWhyNotClick,
  isTopPick = false,
}) => {
  const [showScoreBreakdown, setShowScoreBreakdown] = useState(false);
  const [imageError, setImageError] = useState(false);

  const { product, fit_score, explanation, unverified_aspects } = recommendation;

  // Format currency display cleanly
  const formatPrice = (price: number, currency: string) => {
    try {
      const symbols: Record<string, string> = {
        USD: '$',
        EUR: '€',
        GBP: '£',
        INR: '₹',
      };
      const symbol = symbols[currency.toUpperCase()] || currency + ' ';
      return `${symbol}${price.toLocaleString()}`;
    } catch {
      return `${currency} ${price}`;
    }
  };

  const handleOpenProduct = (e: React.MouseEvent) => {
    e.stopPropagation();
    const url = product.product_url || `https://www.google.com/search?q=${encodeURIComponent(product.brand + ' ' + product.product_name)}`;
    if (typeof chrome !== 'undefined' && chrome.tabs && chrome.tabs.create) {
      chrome.tabs.create({ url });
    } else {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  };

  // Up to 3-4 key specifications
  const keySpecsEntries = Object.entries(product.specifications || product.attributes || {}).slice(0, 3);

  return (
    <article className={`product-card ${isTopPick ? 'top-pick' : ''}`} aria-label={`Product recommendation: ${product.product_name}`}>
      {/* Top Meta Bar */}
      <div className="card-top-row">
        <div className="card-badge-group">
          {isTopPick && <span className="top-pick-pill">Best Fit</span>}
          <span className="store-pill">{product.source_store || 'Verified Store'}</span>
        </div>

        {/* Restrained Match Indicator / Fit Score (Section 4.E) */}
        <button
          type="button"
          className="fit-score-pill"
          onClick={() => setShowScoreBreakdown(!showScoreBreakdown)}
          title="Click to view fit score breakdown"
          aria-expanded={showScoreBreakdown}
          style={{ cursor: 'pointer', border: 'none' }}
        >
          <span>{Math.round(fit_score.total_score)}% Fit</span>
          {showScoreBreakdown ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
      </div>

      {/* Fit Score Breakdown Accordion */}
      {showScoreBreakdown && (
        <div className="score-breakdown-drawer" style={{ background: '#FAF7F0', padding: '8px 10px', borderRadius: '6px', border: '1px solid #E9E0D2', fontSize: '11px', margin: '4px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontWeight: 600, color: '#24221F' }}>
            <span>Score Factors</span>
            <span style={{ color: '#78836B' }}>{fit_score.total_score.toFixed(1)} / 100</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', color: '#8A8176' }}>
            <span>Category: {fit_score.category_score.toFixed(0)}/20</span>
            <span>Use Case: {fit_score.use_case_score.toFixed(0)}/25</span>
            <span>Features: {fit_score.feature_score.toFixed(0)}/25</span>
            <span>Budget: {fit_score.budget_score.toFixed(0)}/20</span>
          </div>
        </div>
      )}

      {/* Main Body: Image + Details */}
      <div className="card-body-row">
        {/* Product Image Frame */}
        <div className="product-img-frame">
          {product.image_url && !imageError ? (
            <img
              src={product.image_url}
              alt={product.product_name}
              className="product-img"
              onError={() => setImageError(true)}
              loading="lazy"
            />
          ) : (
            <div style={{ color: '#8A8176', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
              <Tag size={18} />
            </div>
          )}
        </div>

        {/* Titles & Pricing */}
        <div className="card-details-col">
          {product.brand && <span className="card-brand">{product.brand}</span>}
          <h3 className="card-product-name" title={product.product_name}>
            {product.product_name}
          </h3>

          <div className="card-price-row">
            <span className="card-price">{formatPrice(product.price, product.currency)}</span>
            {product.rating != null && (
              <span className="card-rating" title={`Rating: ${product.rating}`}>
                ★ {product.rating.toFixed(1)}
              </span>
            )}
          </div>

          {/* Key Specifications (Section 4.E) */}
          {keySpecsEntries.length > 0 && (
            <div className="card-specs-row">
              {keySpecsEntries.map(([k, v], idx) => (
                <span key={idx} className="spec-chip">
                  {k}: {typeof v === 'boolean' ? (v ? 'Yes' : 'No') : String(v)}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Concise "Why it fits" Explanation (Section 4.E) */}
      {explanation && (
        <div className="card-why-fits">
          <span className="why-fits-label">Why it fits:</span>
          <span>{explanation}</span>
        </div>
      )}

      {/* Unverified Aspects Warning */}
      {unverified_aspects && unverified_aspects.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '10.5px', color: '#A65F4B', background: 'rgba(166, 95, 75, 0.08)', padding: '3px 6px', borderRadius: '4px' }}>
          <AlertTriangle size={11} style={{ flexShrink: 0 }} />
          <span>Unverified on page: {unverified_aspects.join(', ')}</span>
        </div>
      )}

      {/* Card Actions: Compare, View Product, Why Not */}
      <div className="card-bottom-actions">
        {/* Compare Checkbox */}
        {onCompareToggle && (
          <label className="compare-checkbox-label">
            <input
              type="checkbox"
              checked={isCompared}
              onChange={() => onCompareToggle(product.product_id)}
            />
            <span style={{ fontWeight: isCompared ? 600 : 400, color: isCompared ? '#6B4F3A' : '#24221F' }}>
              {isCompared ? 'Comparing' : 'Compare'}
            </span>
          </label>
        )}

        <div className="card-cta-group">
          {/* Secondary "Why Not" / "Why This" action */}
          {onWhyNotClick && (
            <button
              type="button"
              className="btn-why-not-link"
              onClick={() => onWhyNotClick(product.product_id, product.product_name)}
              title="Understand why this item was chosen or how it compares"
            >
              Why Not?
            </button>
          )}

          {/* View Product Action (Warm dark brown) */}
          <button
            type="button"
            className="btn-view-product"
            onClick={handleOpenProduct}
            title="Open product page in new tab"
          >
            <span>View Product</span>
            <ExternalLink size={11} />
          </button>
        </div>
      </div>
    </article>
  );
};

export default ProductCard;
