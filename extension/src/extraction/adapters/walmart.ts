// ShopSense AI — Walmart Store Page Adapter
// Extracts visible product data from Walmart product pages.

import { StoreAdapter, ExtractionResult } from '../../types/extraction';
import { normalizeExtractedProduct } from '../normalizer';

export class WalmartAdapter implements StoreAdapter {
  id = 'walmart';
  name = 'Walmart';
  supportedDomains = ['walmart.com'];

  canHandle(_url: string, host: string): boolean {
    const cleanHost = host.toLowerCase().replace(/^www\./, '');
    return this.supportedDomains.some((d) => cleanHost === d || cleanHost.endsWith('.' + d));
  }

  isProductPage(doc: Document, url: string): boolean {
    if (/\/ip\/[^\/]+\/\d+/i.test(url) || /\/ip\/\d+/i.test(url)) {
      return true;
    }
    return !!(
      doc.querySelector('h1#main-title') ||
      doc.querySelector('span[itemprop="price"]') ||
      doc.querySelector('[data-testid="add-to-cart-section"]')
    );
  }

  extract(doc: Document, url: string): ExtractionResult {
    const host = new URL(url).hostname;

    if (!this.isProductPage(doc, url)) {
      return {
        status: 'not_product_page',
        store: this.name,
        host,
        url,
        product: null,
        message: 'This Walmart page is not an individual product detail page.',
      };
    }

    try {
      // 1. Title
      const titleEl = doc.querySelector('h1#main-title') || doc.querySelector('h1[itemprop="name"]');
      const name = titleEl?.textContent?.trim() || '';

      if (!name) {
        return {
          status: 'extraction_failed',
          store: this.name,
          host,
          url,
          product: null,
          message: 'Walmart layout change detected: Title selector not found.',
        };
      }

      // 2. Brand
      let brand: string | null = null;
      const brandEl =
        doc.querySelector('[itemprop="brand"]') ||
        doc.querySelector('a.f6[href*="/brand/"]') ||
        doc.querySelector('[data-testid="product-brand-link"]');
      if (brandEl) {
        brand = brandEl.textContent?.trim() || null;
      }

      // 3. Price
      let rawPrice: string | null = null;
      const priceSelectors = [
        'span[itemprop="price"]',
        'span[data-seo-id="hero-price"]',
        'div[data-testid="line-price"]',
        'span.w_iUH7',
      ];
      for (const sel of priceSelectors) {
        const el = doc.querySelector(sel);
        if (el && el.textContent?.trim()) {
          rawPrice = el.textContent.trim();
          break;
        }
      }

      // 4. Image
      let imageUrl: string | null = null;
      const imgEl = (doc.querySelector('img[data-testid="hero-image"]') ||
        doc.querySelector('img.main-image') ||
        doc.querySelector('img[data-testid="product-image"]')) as HTMLImageElement | null;
      if (imgEl && imgEl.src) {
        imageUrl = imgEl.src;
      }

      // 5. Category
      let category: string | null = null;
      const breadcrumbEl = doc.querySelector('nav[aria-label="breadcrumb"]') || doc.querySelector('.w_96');
      if (breadcrumbEl) {
        category = breadcrumbEl.textContent?.replace(/\s+/g, ' ').trim() || null;
      }

      // 6. Specifications
      const specifications: Record<string, string> = {};
      const specRows = doc.querySelectorAll(
        'section[aria-labelledby="specifications"] tr, div[data-testid="ui-collapse"] tr, .nt3 tr'
      );
      specRows.forEach((row) => {
        const kEl = row.querySelector('th, td:first-child');
        const vEl = row.querySelector('td:last-child');
        const k = kEl?.textContent?.trim();
        const v = vEl?.textContent?.trim();
        if (k && v && k !== v && k.length < 50) {
          specifications[k] = v;
        }
      });

      // 7. Item ID from URL
      const idMatch = url.match(/\/ip\/(?:[^\/]+\/)?(\d+)/i);
      const itemId = idMatch ? idMatch[1] : null;

      const product = normalizeExtractedProduct({
        name,
        brand,
        rawPrice,
        productUrl: url,
        sourceStore: this.name,
        imageUrl,
        category,
        specifications,
        rawSkuId: itemId,
      });

      return {
        status: 'success',
        store: this.name,
        host,
        url,
        product,
        message: 'Successfully extracted product details from Walmart page.',
      };
    } catch (err: any) {
      return {
        status: 'extraction_failed',
        store: this.name,
        host,
        url,
        product: null,
        message: 'Unexpected error extracting data from Walmart page.',
        error: err.message,
      };
    }
  }
}

export const walmartAdapter = new WalmartAdapter();
