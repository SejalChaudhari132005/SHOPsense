// ShopSense AI — Best Buy Store Page Adapter
// Extracts visible product data from Best Buy pages.

import { StoreAdapter, ExtractionResult } from '../../types/extraction';
import { normalizeExtractedProduct } from '../normalizer';

export class BestBuyAdapter implements StoreAdapter {
  id = 'bestbuy';
  name = 'Best Buy';
  supportedDomains = ['bestbuy.com'];

  canHandle(_url: string, host: string): boolean {
    const cleanHost = host.toLowerCase().replace(/^www\./, '');
    return this.supportedDomains.some((d) => cleanHost === d || cleanHost.endsWith('.' + d));
  }

  isProductPage(doc: Document, url: string): boolean {
    if (/\/site\/.*\.p\?skuId=\d+/i.test(url) || /\/site\/.*\/\d+\.p/i.test(url)) {
      return true;
    }
    return !!(
      doc.querySelector('.sku-title h1') ||
      doc.querySelector('.priceView-customer-price') ||
      doc.querySelector('.fulfillment-add-to-cart-button')
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
        message: 'This Best Buy page is not a product detail page.',
      };
    }

    try {
      // 1. Title
      const titleEl = doc.querySelector('.sku-title h1') || doc.querySelector('h1.heading-5');
      const name = titleEl?.textContent?.trim() || '';

      if (!name) {
        return {
          status: 'extraction_failed',
          store: this.name,
          host,
          url,
          product: null,
          message: 'Best Buy layout change detected: Title selector not found.',
        };
      }

      // 2. Brand
      let brand: string | null = null;
      const brandEl = doc.querySelector('.sku-title .heading-5') || doc.querySelector('[data-track="Brand"]');
      if (brandEl) {
        brand = brandEl.textContent?.trim() || null;
      }
      if (!brand) {
        // Try extracting first word of product title if recognizable brand
        const words = name.split(' ');
        if (words.length > 1 && words[0].length > 1) {
          brand = words[0];
        }
      }

      // 3. Price
      let rawPrice: string | null = null;
      const priceSelectors = [
        '.priceView-customer-price span',
        'div[data-testid="customer-price"] span',
        '.priceView-hero-price span',
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
      const imgEl = (doc.querySelector('img.primary-image') || doc.querySelector('img.picture-wrapper__image')) as HTMLImageElement | null;
      if (imgEl && imgEl.src) {
        imageUrl = imgEl.src;
      }

      // 5. Category
      let category: string | null = null;
      const breadcrumbEl = doc.querySelector('.c-breadcrumbs');
      if (breadcrumbEl) {
        category = breadcrumbEl.textContent?.replace(/\s+/g, ' ').trim() || null;
      }

      // 6. Specifications
      const specifications: Record<string, string> = {};
      const specRows = doc.querySelectorAll('.specifications-table tr, .specs-table-row, [data-testid="specs-row"]');
      specRows.forEach((row) => {
        const titleEl = row.querySelector('.specs-table-col-title, th, dt, [data-testid="spec-name"]');
        const valEl = row.querySelector('.specs-table-col-value, td, dd, [data-testid="spec-value"]');
        const k = titleEl?.textContent?.trim();
        const v = valEl?.textContent?.trim();
        if (k && v && k !== v && k.length < 50) {
          specifications[k] = v;
        }
      });

      // 7. SKU
      const skuMatch = url.match(/skuId=(\d+)/i) || url.match(/\/(\d+)\.p/i);
      const skuId = skuMatch ? skuMatch[1] : null;

      const product = normalizeExtractedProduct({
        name,
        brand,
        rawPrice,
        productUrl: url,
        sourceStore: this.name,
        imageUrl,
        category,
        specifications,
        rawSkuId: skuId,
      });

      return {
        status: 'success',
        store: this.name,
        host,
        url,
        product,
        message: 'Successfully extracted product details from Best Buy page.',
      };
    } catch (err: any) {
      return {
        status: 'extraction_failed',
        store: this.name,
        host,
        url,
        product: null,
        message: 'Unexpected error extracting data from Best Buy page.',
        error: err.message,
      };
    }
  }
}

export const bestBuyAdapter = new BestBuyAdapter();
