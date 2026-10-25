// ShopSense AI — Content Script (Manifest V3)
// Safely extracts visible product data from supported e-commerce pages using modular adapters.

import extractionRegistry from '../extraction';
import { PageContext } from '../types';

(() => {
  try {
    const host = window.location.hostname.toLowerCase();
    const isSupportedDomain = extractionRegistry.getSupportedDomains().some(
      (d) => host === d || host.endsWith('.' + d)
    );

    if (!isSupportedDomain) {
      return;
    }

    console.log('[ShopSense AI] Content script active on supported domain:', host);

    function getExtractionContext(): PageContext {
      const url = window.location.href;
      const result = extractionRegistry.extractFromDocument(document, url);

      if (result.status === 'success' && result.product) {
        return {
          supported: true,
          isProductPage: true,
          host: result.host,
          url: result.url,
          title: result.product.product_name,
          price: result.product.price ? `${result.product.price} ${result.product.currency || ''}` : result.product.raw_price,
          brand: result.product.brand,
          category: result.product.category,
          imageUrl: result.product.image_url,
          extractedProduct: result.product,
        };
      }

      if (result.status === 'not_product_page') {
        return {
          supported: true,
          isProductPage: false,
          host: result.host,
          url: result.url,
          title: document.title || '',
          extractedProduct: null,
          error: result.message,
        };
      }

      // extraction_failed or unsupported
      return {
        supported: result.status !== 'unsupported_domain',
        isProductPage: false,
        host: result.host,
        url: result.url,
        title: document.title || '',
        extractedProduct: null,
        error: result.message,
      };
    }

    // Listen for requests from background worker or side-panel
    chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
      if (request.type === 'GET_PAGE_CONTEXT' || request.type === 'EXTRACT_PRODUCT') {
        const context = getExtractionContext();
        sendResponse(context);
        return true;
      }
      return false;
    });
  } catch (err) {
    console.warn('[ShopSense AI] Content script initialization error:', err);
  }
})();
