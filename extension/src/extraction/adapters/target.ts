// ShopSense AI — Target Store Page Adapter
// Extracts visible product data from Target product pages.

import { StoreAdapter, ExtractionResult } from '../../types/extraction';
import { normalizeExtractedProduct } from '../normalizer';

export class TargetAdapter implements StoreAdapter {
  id = 'target';
  name = 'Target';
  supportedDomains = ['target.com'];

  canHandle(_url: string, host: string): boolean {
    const cleanHost = host.toLowerCase().replace(/^www\./, '');
    return this.supportedDomains.some((d) => cleanHost === d || cleanHost.endsWith('.' + d));
  }

  isProductPage(doc: Document, url: string): boolean {
    if (/\/p\/[^\/]+\/-\/A-\d+/i.test(url) || /\/p\/-\/A-\d+/i.test(url)) {
      return true;
    }
    return !!(
      doc.querySelector('h1#pdp-product-title-id') ||
      doc.querySelector('h1[data-test="product-title"]') ||
      doc.querySelector('span[data-test="product-price"]')
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
        message: 'This Target page is not an individual product detail page.',
      };
    }

    try {
      // 1. Title
      const titleEl =
        doc.querySelector('h1#pdp-product-title-id') ||
        doc.querySelector('h1[data-test="product-title"]') ||
        doc.querySelector('h1');
      const name = titleEl?.textContent?.trim() || '';

      if (!name) {
        return {
          status: 'extraction_failed',
          store: this.name,
          host,
          url,
          product: null,
          message: 'Target layout change detected: Title selector not found.',
        };
      }

      // 2. Brand
      let brand: string | null = null;
      const brandEl =
        doc.querySelector('a[data-test="product-brand"]') ||
        doc.querySelector('a[data-test="shop-all-brand-link"]');
      if (brandEl) {
        brand = brandEl.textContent?.trim() || null;
      }

      // 3. Price
      let rawPrice: string | null = null;
      const priceSelectors = [
        'span[data-test="product-price"]',
        'div[data-test="product-price"]',
        'span.h-text-bs',
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
      const imgEl = (doc.querySelector('img[data-test="carousel-image-0"]') ||
        doc.querySelector('img[data-test="primary-image"]') ||
        doc.querySelector('div[data-test="image-gallery-container"] img')) as HTMLImageElement | null;
      if (imgEl && imgEl.src) {
        imageUrl = imgEl.src;
      }

      // 5. Category
      let category: string | null = null;
      const breadcrumbEl = doc.querySelector('nav[data-test="breadcrumbs"]');
      if (breadcrumbEl) {
        category = breadcrumbEl.textContent?.replace(/\s+/g, ' ').trim() || null;
      }

      // 6. Specifications
      const specifications: Record<string, string> = {};
      const specRows = doc.querySelectorAll(
        'div[data-test="item-details-specifications"] div, div[data-test="specifications-list"] > div'
      );
      specRows.forEach((row) => {
        const text = row.textContent?.trim() || '';
        if (text.includes(':')) {
          const [k, ...vParts] = text.split(':');
          const v = vParts.join(':').trim();
          if (k && v && k.length < 50) {
            specifications[k.trim()] = v;
          }
        }
      });

      // 7. TCIN / SkuId
      const tcinMatch = url.match(/A-(\d+)/i);
      const tcin = tcinMatch ? tcinMatch[1] : null;

      const product = normalizeExtractedProduct({
        name,
        brand,
        rawPrice,
        productUrl: url,
        sourceStore: this.name,
        imageUrl,
        category,
        specifications,
        rawSkuId: tcin,
      });

      return {
        status: 'success',
        store: this.name,
        host,
        url,
        product,
        message: 'Successfully extracted product details from Target page.',
      };
    } catch (err: any) {
      return {
        status: 'extraction_failed',
        store: this.name,
        host,
        url,
        product: null,
        message: 'Unexpected error extracting data from Target page.',
        error: err.message,
      };
    }
  }
}

export const targetAdapter = new TargetAdapter();
