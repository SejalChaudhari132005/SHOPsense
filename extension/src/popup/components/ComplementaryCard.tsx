import React from 'react';
import { Sparkles, Plus, ShieldCheck } from 'lucide-react';
import { ComplementarySuggestion } from '../../types';

interface ComplementaryCardProps {
  suggestion: ComplementarySuggestion;
  onExplore?: (query: string) => void;
}

export const ComplementaryCard: React.FC<ComplementaryCardProps> = ({ suggestion, onExplore }) => {
  const {
    product,
    price_formatted,
    why_relevant,
    utility_explanation,
    data_provenance,
  } = suggestion;

  const productName = product?.product_name || (suggestion as any).suggested_product_name || 'Complementary Accessory';
  const category = product?.category || (suggestion as any).category || 'Accessory';
  const displayPrice = price_formatted || (product ? `$${product.price}` : '');
  const explanation = why_relevant || utility_explanation || 'Pairs well with your selected item.';
  const parentName = (suggestion as any).parent_product_name || 'your items';

  return (
    <div className="complementary-card" role="complementary" aria-label="Suggested Accessory">
      <div className="comp-header">
        <div className="comp-title-group">
          <Sparkles size={13} className="text-brand" />
          <span className="comp-badge">Complementary Pairing</span>
          <span className="comp-parent-tag">Pairs with {parentName.slice(0, 24)}...</span>
        </div>
        <span className="provenance-pill" title="Catalog source attribution">
          <ShieldCheck size={10} /> {data_provenance || 'Verified Demo Data'}
        </span>
      </div>

      <div className="comp-body">
        <div className="comp-info">
          <h4 className="comp-name">{productName}</h4>
          <span className="comp-category-tag">{category}</span>
          <p className="comp-utility-explanation">{explanation}</p>
        </div>

        <div className="comp-price-col">
          <span className="comp-price">{displayPrice}</span>
          {onExplore && (
            <button
              type="button"
              className="btn-explore-comp"
              onClick={() => onExplore(`Tell me more about ${productName}`)}
              title="Learn more about this accessory"
            >
              <span>Explore</span>
              <Plus size={11} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default ComplementaryCard;
