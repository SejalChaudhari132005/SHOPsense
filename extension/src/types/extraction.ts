// ShopSense AI — Current-Page Product Extraction Type Definitions
// Defines contracts for store adapters, extracted products, validation, and provenance.

import { ProductProvenance } from './index';

export type ExtractionStatus = 
  | 'success'
  | 'unsupported_domain'
  | 'not_product_page'
  | 'extraction_failed';

export interface ExtractionValidation {
  is_valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ExtractedProduct {
  product_id?: string;
  product_name: string;
  brand: string | null;
  price: number | null;
  currency: string | null;
  raw_price: string | null;
  image_url: string | null;
  product_url: string;
  source_store: string;
  category: string | null;
  specifications: Record<string, string | number | boolean>;
  attributes: Record<string, any>;
  availability: string | null;
  extracted_at: string; // ISO 8601
  provenance: ProductProvenance;
  validation: ExtractionValidation;
}

export interface ExtractionResult {
  status: ExtractionStatus;
  store: string;
  host: string;
  url: string;
  product: ExtractedProduct | null;
  message: string;
  error?: string;
}

export interface StoreAdapter {
  id: string;
  name: string;
  supportedDomains: string[];
  canHandle(url: string, host: string): boolean;
  isProductPage(doc: Document, url: string): boolean;
  extract(doc: Document, url: string): ExtractionResult;
}
