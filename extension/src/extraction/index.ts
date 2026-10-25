// ShopSense AI — Multi-Store Page Extraction Engine
// Manages store adapters, coordinates extraction, and handles unsupported domains gracefully.

import { StoreAdapter, ExtractionResult } from '../types/extraction';
import { amazonAdapter } from './adapters/amazon';
import { bestBuyAdapter } from './adapters/bestbuy';
import { flipkartAdapter } from './adapters/flipkart';
import { walmartAdapter } from './adapters/walmart';
import { targetAdapter } from './adapters/target';

class ExtractionRegistry {
  private adapters: StoreAdapter[] = [];

  constructor() {
    this.registerAdapter(amazonAdapter);
    this.registerAdapter(bestBuyAdapter);
    this.registerAdapter(flipkartAdapter);
    this.registerAdapter(walmartAdapter);
    this.registerAdapter(targetAdapter);
  }

  public registerAdapter(adapter: StoreAdapter) {
    this.adapters.push(adapter);
  }

  public getSupportedDomains(): string[] {
    return Array.from(new Set(this.adapters.flatMap((a) => a.supportedDomains)));
  }

  public getSupportedStoreNames(): string[] {
    return this.adapters.map((a) => a.name);
  }

  public findAdapter(url: string): StoreAdapter | null {
    try {
      const parsed = new URL(url);
      const host = parsed.hostname.toLowerCase();
      for (const adapter of this.adapters) {
        if (adapter.canHandle(url, host)) {
          return adapter;
        }
      }
    } catch {
      // Invalid URL
    }
    return null;
  }

  public extractFromDocument(doc: Document, url: string): ExtractionResult {
    try {
      const parsed = new URL(url);
      const host = parsed.hostname;
      const adapter = this.findAdapter(url);

      if (!adapter) {
        return {
          status: 'unsupported_domain',
          store: 'Unsupported Store',
          host,
          url,
          product: null,
          message: `ShopSense does not currently support automated extraction on ${host}. Supported stores: ${this.getSupportedStoreNames().join(', ')}.`,
        };
      }

      return adapter.extract(doc, url);
    } catch (err: any) {
      return {
        status: 'extraction_failed',
        store: 'Unknown',
        host: 'unknown',
        url,
        product: null,
        message: 'Could not parse URL or document.',
        error: err.message,
      };
    }
  }
}

export const extractionRegistry = new ExtractionRegistry();
export default extractionRegistry;

export * from './sanitizer';
export * from './normalizer';
