// ShopSense AI — Price, Currency, and Schema Normalizer
// Parses heterogeneous prices, validates currencies, and normalizes into shared product schema.

import { ExtractedProduct, ExtractionValidation } from '../types/extraction';
import { ProductProvenance } from '../types';
import { sanitizeUntrustedText, sanitizeUrl, sanitizeImageUrl, sanitizeSpecifications } from './sanitizer';

export interface ParsedPriceResult {
  numericPrice: number | null;
  currency: string | null;
  rawText: string;
}

/**
 * Currency symbol to standard ISO 4217 code mapping.
 */
const CURRENCY_SYMBOLS: Record<string, string> = {
  '$': 'USD',
  '₹': 'INR',
  '€': 'EUR',
  '£': 'GBP',
  '¥': 'JPY',
  'C$': 'CAD',
  'A$': 'AUD',
  'USD': 'USD',
  'INR': 'INR',
  'EUR': 'EUR',
  'GBP': 'GBP',
  'CAD': 'CAD',
  'AUD': 'AUD',
};

/**
 * Reliably extracts numeric price and ISO currency from price strings.
 * Supports: '$1,299.99', '₹7,999.00', '1.499,90 €', '£150', 'USD 49.95'
 */
export function parsePriceAndCurrency(rawPriceText: string | null | undefined): ParsedPriceResult {
  if (!rawPriceText || typeof rawPriceText !== 'string') {
    return { numericPrice: null, currency: null, rawText: '' };
  }

  const raw = rawPriceText.trim();
  let detectedCurrency: string | null = null;

  // 1. Detect Currency Symbol or Code
  for (const [symbol, code] of Object.entries(CURRENCY_SYMBOLS)) {
    if (raw.toUpperCase().includes(symbol)) {
      detectedCurrency = code;
      break;
    }
  }

  // 2. Clean numeric string
  // Extract the numeric portion (digits, commas, periods)
  const match = raw.match(/[\d\.,\s]+/);
  if (!match) {
    return { numericPrice: null, currency: detectedCurrency, rawText: raw };
  }

  let numStr = match[0].trim().replace(/\s+/g, '');

  // Case A: Both period and comma present
  if (numStr.includes('.') && numStr.includes(',')) {
    if (numStr.lastIndexOf(',') > numStr.lastIndexOf('.')) {
      // European: 1.299,50 -> comma is decimal
      numStr = numStr.replace(/\./g, '').replace(',', '.');
    } else {
      // Standard: 1,299.50 -> comma is thousands
      numStr = numStr.replace(/,/g, '');
    }
  } else if (numStr.includes(',')) {
    // Comma only:
    // If followed by exactly 1 or 2 digits at the end (e.g. "49,99" or "49,5"), it's a decimal separator
    if (/,\d{1,2}$/.test(numStr)) {
      numStr = numStr.replace(',', '.');
    } else {
      // Otherwise it's thousands separator (e.g. "1,999", "18,999")
      numStr = numStr.replace(/,/g, '');
    }
  } else if (numStr.includes('.')) {
    // Dot only: If multiple dots (e.g. "1.299.000"), dots are thousands
    if ((numStr.match(/\./g) || []).length > 1) {
      numStr = numStr.replace(/\./g, '');
    }
  }

  const parsed = parseFloat(numStr);

  if (isNaN(parsed) || !isFinite(parsed) || parsed <= 0 || parsed > 1_000_000) {
    return { numericPrice: null, currency: detectedCurrency, rawText: raw };
  }

  return {
    numericPrice: Math.round(parsed * 100) / 100,
    currency: detectedCurrency || 'INR',
    rawText: raw,
  };
}

export interface NormalizeProductInput {
  name: string;
  brand?: string | null;
  rawPrice?: string | null;
  productUrl: string;
  sourceStore: string;
  imageUrl?: string | null;
  category?: string | null;
  specifications?: Record<string, any>;
  availability?: string | null;
  rawSkuId?: string | null;
}

/**
 * Normalizes raw extracted product fields into the typed ExtractedProduct schema.
 * Performs prompt injection neutralization, URL verification, and honest provenance tracking.
 */
export function normalizeExtractedProduct(input: NormalizeProductInput): ExtractedProduct {
  const errors: string[] = [];
  const warnings: string[] = [];
  const missingFields: string[] = [];

  // 1. Sanitize & Validate Title
  const cleanName = sanitizeUntrustedText(input.name, 250);
  if (!cleanName || cleanName.length < 3) {
    errors.push('Product name is missing or too short.');
  }

  // 2. Sanitize Brand
  const cleanBrand = input.brand ? sanitizeUntrustedText(input.brand, 80) : null;
  if (!cleanBrand) {
    missingFields.push('brand');
    warnings.push('Brand was not reliably found on page.');
  }

  // 3. Parse & Validate Price
  const priceResult = parsePriceAndCurrency(input.rawPrice);
  if (priceResult.numericPrice === null) {
    missingFields.push('price');
    warnings.push('Displayed price was unavailable or unparseable.');
  }

  // 4. Sanitize & Validate Product URL
  const cleanUrl = sanitizeUrl(input.productUrl);
  if (!cleanUrl) {
    errors.push('Product URL is invalid or malformed.');
  }

  // 5. Sanitize Image URL
  const cleanImageUrl = sanitizeImageUrl(input.imageUrl);
  if (!cleanImageUrl) {
    missingFields.push('image_url');
    warnings.push('Product image URL is unavailable or invalid.');
  }

  // 6. Sanitize Specifications & Category
  const cleanSpecs = sanitizeSpecifications(input.specifications);
  if (Object.keys(cleanSpecs).length === 0) {
    missingFields.push('specifications');
  }

  const cleanCategory = input.category ? sanitizeUntrustedText(input.category, 60) : null;
  if (!cleanCategory) {
    missingFields.push('category');
  }

  // 7. Calculate Provenance & Confidence Score
  // Max score 1.0; each critical missing field deducts confidence
  let confidence = 1.0;
  if (priceResult.numericPrice === null) confidence -= 0.3;
  if (!cleanBrand) confidence -= 0.15;
  if (!cleanImageUrl) confidence -= 0.1;
  if (Object.keys(cleanSpecs).length === 0) confidence -= 0.15;
  confidence = Math.max(0.2, Math.round(confidence * 100) / 100);

  const provenance: ProductProvenance = {
    is_sample_data: false,
    data_source_type: 'extension_scraped',
    verified: false, // Scraped data is marked unverified until cross-referenced
    confidence_score: confidence,
    missing_fields: missingFields,
    notes: `Extracted from active page on ${input.sourceStore}`,
  };

  const validation: ExtractionValidation = {
    is_valid: errors.length === 0,
    errors,
    warnings,
  };

  // Generate deterministic scraped ID
  const storePrefix = input.sourceStore.toLowerCase().replace(/[^a-z0-9]/g, '');
  const idSuffix = input.rawSkuId
    ? input.rawSkuId.replace(/[^a-zA-Z0-9_-]/g, '')
    : Math.abs(hashCode(cleanUrl || input.name)).toString(36);
  const productId = `ext_${storePrefix}_${idSuffix}`;

  return {
    product_id: productId,
    product_name: cleanName || 'Unnamed Product',
    brand: cleanBrand,
    price: priceResult.numericPrice,
    currency: priceResult.currency,
    raw_price: input.rawPrice || null,
    image_url: cleanImageUrl,
    product_url: cleanUrl || input.productUrl,
    source_store: input.sourceStore,
    category: cleanCategory,
    specifications: cleanSpecs,
    attributes: cleanSpecs,
    availability: input.availability ? sanitizeUntrustedText(input.availability, 40) : null,
    extracted_at: new Date().toISOString(),
    provenance,
    validation,
  };
}

function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash |= 0;
  }
  return hash;
}
