// ShopSense AI — Flipkart Store Page Adapter
// Extracts visible product data from Flipkart pages with Indian Rupee (INR) support.

import { StoreAdapter, ExtractionResult } from '../../types/extraction';
import { normalizeExtractedProduct } from '../normalizer';

export class FlipkartAdapter implements StoreAdapter {
  id = 'flipkart';
  name = 'Flipkart';
  supportedDomains = ['flipkart.com'];

  canHandle(_url: string, host: string): boolean {
    const cleanHost = host.toLowerCase().replace(/^www\./, '');
    return this.supportedDomains.some((d) => cleanHost === d || cleanHost.endsWith('.' + d));
  }

  isProductPage(doc: Document, url: string): boolean {
    if (/\/p\/[a-zA-Z0-9]+/i.test(url) || url.includes('pid=')) {
      return true;
    }
    return !!(
      doc.querySelector('.B_NuCI') ||
      doc.querySelector('h1._6EBuvT') ||
      doc.querySelector('span.VU-ZEz') ||
      doc.querySelector('div._30jeq3') ||
      doc.querySelector('div.Nx9bqj')
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
        message: 'This Flipkart page is not an individual product detail page.',
      };
    }

    try {
      // 1. Title
      const titleEl =
        doc.querySelector('.B_NuCI') ||
        doc.querySelector('h1._6EBuvT') ||
        doc.querySelector('span.VU-ZEz') ||
        doc.querySelector('h1');
      const name = titleEl?.textContent?.trim() || '';

      if (!name) {
        return {
          status: 'extraction_failed',
          store: this.name,
          host,
          url,
          product: null,
          message: 'Flipkart layout change detected: Title selector not found.',
        };
      }

      // 2. Brand
      let brand: string | null = null;
      const brandEl = doc.querySelector('span.G6XhRU') || doc.querySelector('.mEh187');
      if (brandEl) {
        brand = brandEl.textContent?.trim() || null;
      }
      if (!brand) {
        const words = name.split(' ');
        if (words.length > 1) {
          brand = words[0];
        }
      }

      // 3. Price (in INR)
      let rawPrice: string | null = null;
      const priceSelectors = [
        'div._30jeq3._16Jk6d',
        'div.Nx9bqj.CxhGGd',
        'div._30jeq3',
        'div.Nx9bqj',
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
      const imgEl = (doc.querySelector('img._396cs4._3exPp9') ||
        doc.querySelector('img._2r_T1I') ||
        doc.querySelector('img.DByuf4')) as HTMLImageElement | null;
      if (imgEl && imgEl.src) {
        imageUrl = imgEl.src;
      }

      // 5. Category Breadcrumbs
      let category: string | null = null;
      const breadcrumbEl = doc.querySelector('._2WhKao') || doc.querySelector('.r2CdBx');
      if (breadcrumbEl) {
        category = breadcrumbEl.textContent?.replace(/\s+/g, ' ').trim() || null;
      }

      // 6. Specifications
      const specifications: Record<string, string> = {};
      const specRows = doc.querySelectorAll('table._14cfVK tr, div._3k-BhJ tr, tr._1s_Smc');
      specRows.forEach((row) => {
        const titleEl = row.querySelector('td._1hKmbr, td:first-child');
        const valEl = row.querySelector('li._21Ahn-, td:last-child');
        const k = titleEl?.textContent?.trim();
        const v = valEl?.textContent?.trim();
        if (k && v && k !== v && k.length < 50) {
          specifications[k] = v;
        }
      });

      // 7. Product ID / PID
      const pidMatch = url.match(/pid=([a-zA-Z0-9]+)/i) || url.match(/\/p\/([a-zA-Z0-9]+)/i);
      const pid = pidMatch ? pidMatch[1] : null;

      const product = normalizeExtractedProduct({
        name,
        brand,
        rawPrice,
        productUrl: url,
        sourceStore: this.name,
        imageUrl,
        category,
        specifications,
        rawSkuId: pid,
      });

      return {
        status: 'success',
        store: this.name,
        host,
        url,
        product,
        message: 'Successfully extracted product details from Flipkart page.',
      };
    } catch (err: any) {
      return {
        status: 'extraction_failed',
        store: this.name,
        host,
        url,
        product: null,
        message: 'Unexpected error extracting data from Flipkart page.',
        error: err.message,
      };
    }
  }
}

export const flipkartAdapter = new FlipkartAdapter();
