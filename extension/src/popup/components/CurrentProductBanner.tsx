// ShopSense AI — Current Product Context Panel (Section 4.B)
import React, { useState } from 'react';
import { 
  Sparkles, 
  SlidersHorizontal, 
  ExternalLink, 
  RefreshCw,
  Search,
  Tag,
  Compass
} from 'lucide-react';
import { PageContext, ExtractedProduct } from '../../types';
import { formatPriceInINR } from '../../services/currency';

interface CurrentProductBannerProps {
  pageContext: PageContext | null;
  onAnalyzeProduct: (product: ExtractedProduct) => void;
  onFindAlternatives: (product: ExtractedProduct) => void;
  onCompareProduct: (product: ExtractedProduct) => void;
  onRefreshTab?: () => void;
  isLoading: boolean;
}

export const CurrentProductBanner: React.FC<CurrentProductBannerProps> = ({
  pageContext,
  onAnalyzeProduct,
  onFindAlternatives,
  onCompareProduct,
  onRefreshTab,
  isLoading,
}) => {
  const [imageError, setImageError] = useState(false);
  const [isDismissed, setIsDismissed] = useState(false);

  if (isDismissed) {
    return null;
  }

  // Calm Empty State when no supported product page is active (Section 4.B)
  if (!pageContext || !pageContext.supported || !pageContext.isProductPage || !pageContext.extractedProduct) {
    return (
      <div className="current-context-notice" role="region" aria-label="Current page status">
        <Compass size={15} className="notice-icon" />
        <div className="notice-body">
          <span className="notice-title">
            {pageContext?.supported && pageContext?.host 
              ? `Browsing ${pageContext.host.replace(/^www\./, '')}` 
              : 'Current page evaluation'}
          </span>
          <p className="notice-desc">
            Open a product page and I’ll help you evaluate it.
          </p>
        </div>
        {onRefreshTab && (
          <button
            type="button"
            className="btn-banner-action"
            onClick={onRefreshTab}
            title="Scan active browser tab"
          >
            <RefreshCw size={11} />
            <span>Scan</span>
          </button>
        )}
      </div>
    );
  }

  const product = pageContext.extractedProduct;

  const formatPrice = (price: number | null, currency: string | null) => {
    if (price !== null) {
      return formatPriceInINR(price, currency);
    }
    return 'Price unavailable';
  };

  return (
    <section className="current-product-banner" aria-label="Detected current product">
      {/* Top Meta Bar */}
      <div className="banner-top-bar">
        <div className="banner-title-group">
          <span className="provenance-tag">Current page</span>
          <span className="confidence-pill">{product.source_store}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          {onRefreshTab && (
            <button
              type="button"
              className="btn-notice-dismiss"
              onClick={onRefreshTab}
              title="Refresh product data from page"
              aria-label="Refresh product"
            >
              <RefreshCw size={11} />
            </button>
          )}
          <button
            type="button"
            className="btn-notice-dismiss"
            onClick={() => setIsDismissed(true)}
            title="Dismiss banner"
            aria-label="Dismiss banner"
          >
            &times;
          </button>
        </div>
      </div>

      {/* Main Product Row */}
      <div className="banner-main-row">
        {/* Product Thumbnail */}
        <div className="banner-thumbnail-container">
          {product.image_url && !imageError ? (
            <img
              src={product.image_url}
              alt={product.product_name}
              className="banner-thumbnail"
              onError={() => setImageError(true)}
              loading="lazy"
            />
          ) : (
            <div className="banner-placeholder-thumb">
              <Tag size={16} />
            </div>
          )}
        </div>

        {/* Product Details */}
        <div className="banner-info">
          {product.brand && <span className="banner-brand">{product.brand}</span>}
          <h2 className="banner-product-title" title={product.product_name}>
            {product.product_name}
          </h2>
          <div className="banner-price-row">
            <span className="banner-price">
              {formatPrice(product.price, product.currency)}
            </span>
            <span className="banner-availability">
              {product.availability || 'In stock'}
            </span>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="banner-actions-row">
        <button
          type="button"
          className="btn-banner-action btn-analyze"
          onClick={() => onAnalyzeProduct(product)}
          disabled={isLoading}
          title="Evaluate this product with ShopSense"
        >
          <Sparkles size={12} />
          <span>Evaluate with ShopSense</span>
        </button>

        <button
          type="button"
          className="btn-banner-action"
          onClick={() => onFindAlternatives(product)}
          disabled={isLoading}
          title="Find similar curated alternatives"
        >
          <Search size={12} />
          <span>Alternatives</span>
        </button>

        <button
          type="button"
          className="btn-banner-action"
          onClick={() => onCompareProduct(product)}
          disabled={isLoading}
          title="Add to product comparison"
        >
          <SlidersHorizontal size={12} />
          <span>Compare</span>
        </button>

        {product.product_url && (
          <a
            href={product.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-banner-link"
            title="View original product page"
            aria-label="View original product page"
          >
            <ExternalLink size={12} />
          </a>
        )}
      </div>
    </section>
  );
};

export default CurrentProductBanner;
