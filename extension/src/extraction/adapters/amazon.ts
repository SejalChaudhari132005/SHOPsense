// ShopSense AI — Amazon Store Page Adapter
// Extracts visible product data from Amazon without aggressive scraping or privacy violations.

import { StoreAdapter, ExtractionResult } from '../../types/extraction';
import { normalizeExtractedProduct } from '../normalizer';

export class AmazonAdapter implements StoreAdapter {
  id = 'amazon';
  name = 'Amazon';
  supportedDomains = ['amazon.com', 'amazon.in', 'amazon.co.uk', 'amazon.ca', 'amazon.de', 'amazon.fr'];

  canHandle(_url: string, host: string): boolean {
    const cleanHost = host.toLowerCase().replace(/^www\./, '');
    return this.supportedDomains.some((d) => cleanHost === d || cleanHost.endsWith('.' + d));
  }

  isProductPage(doc: Document, url: string): boolean {
    // Check URL patterns for Amazon ASIN pages (/dp/B0..., /gp/product/B0...)
    if (/\/dp\/[A-Z0-9]{10}/i.test(url) || /\/gp\/product\/[A-Z0-9]{10}/i.test(url)) {
      return true;
    }
    // Check DOM elements characteristic of Amazon product pages
    return !!(
      doc.getElementById('productTitle') ||
      doc.getElementById('dp') ||
      doc.getElementById('add-to-cart-button')
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
        message: 'This Amazon page is not an individual product detail page (e.g. search results or category page).',
      };
    }

    try {
      // 1. Extract Product Title
      const titleEl = doc.getElementById('productTitle') || doc.querySelector('#title');
      const name = titleEl?.textContent?.trim() || '';

      if (!name) {
        return {
          status: 'extraction_failed',
          store: this.name,
          host,
          url,
          product: null,
          message: 'Amazon layout change detected: Product title selector not found.',
        };
      }

      // 2. Extract Brand
      let brand: string | null = null;
      const bylineEl = doc.getElementById('bylineInfo') || doc.querySelector('#brand');
      if (bylineEl) {
        brand = bylineEl.textContent?.replace(/Brand:\s*|Visit the\s*|Store/gi, '').trim() || null;
      }
      if (!brand) {
        // Fallback: Check product overview table row for Brand
        const brandRow = doc.querySelector('.po-brand .a-span9, tr.po-brand td:last-child');
        if (brandRow) brand = brandRow.textContent?.trim() || null;
      }

      // 3. Extract Price & Currency
      let rawPrice: string | null = null;
      const priceSelectors = [
        '.a-price .a-offscreen',
        '#corePrice_desktop .a-price .a-offscreen',
        '.apexPriceToPay .a-offscreen',
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '#price_inside_buybox',
      ];
      for (const sel of priceSelectors) {
        const el = doc.querySelector(sel);
        if (el && el.textContent?.trim()) {
          rawPrice = el.textContent.trim();
          break;
        }
      }

      // 4. Extract Product Image
      let imageUrl: string | null = null;
      const landingImg = doc.getElementById('landingImage') as HTMLImageElement | null;
      if (landingImg) {
        // LandingImage sometimes has higher-res in dataset
        imageUrl = landingImg.getAttribute('data-old-hires') || landingImg.src || null;
      }
      if (!imageUrl) {
        const altImg = (doc.getElementById('imgBlkFront') || doc.querySelector('#main-image')) as HTMLImageElement | null;
        if (altImg) imageUrl = altImg.src || null;
      }

      // 5. Extract Category / Breadcrumbs
      let category: string | null = null;
      const breadcrumbsEl = doc.getElementById('wayfinding-breadcrumbs_feature_div');
      if (breadcrumbsEl) {
        category = breadcrumbsEl.textContent?.replace(/\s+/g, ' ').trim() || null;
      }

      // 6. Extract Specifications
      const specifications: Record<string, string> = {};
      const specRows = doc.querySelectorAll('#productOverview_feature_div tr, #productDetails_techSpec_section_1 tr');
      specRows.forEach((row) => {
        const keyEl = row.querySelector('th, td:first-child');
        const valEl = row.querySelector('td:last-child');
        const k = keyEl?.textContent?.trim();
        const v = valEl?.textContent?.trim();
        if (k && v && k !== v && k.length < 50) {
          specifications[k] = v;
        }
      });

      // 7. Extract Availability
      let availability: string | null = null;
      const availEl = doc.getElementById('availability');
      if (availEl) {
        availability = availEl.textContent?.trim() || null;
      }

      // 8. ASIN
      const asinMatch = url.match(/\/(?:dp|product)\/([A-Z0-9]{10})/i);
      const asin = asinMatch ? asinMatch[1] : null;

      const product = normalizeExtractedProduct({
        name,
        brand,
        rawPrice,
        productUrl: url,
        sourceStore: this.name,
        imageUrl,
        category,
        specifications,
        availability,
        rawSkuId: asin,
      });

      return {
        status: 'success',
        store: this.name,
        host,
        url,
        product,
        message: 'Successfully extracted product details from Amazon page.',
      };
    } catch (err: any) {
      return {
        status: 'extraction_failed',
        store: this.name,
        host,
        url,
        product: null,
        message: 'Unexpected error extracting data from Amazon page.',
        error: err.message,
      };
    }
  }
}

export const amazonAdapter = new AmazonAdapter();
