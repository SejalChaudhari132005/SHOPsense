# ShopSense AI — Chrome Extension (Manifest V3)

A high-performance Chrome side-panel shopping assistant powered by a 10-Agent LangGraph swarm and real-time product extraction.

## Features

- **Manifest V3 Side Panel**: Native Chrome side panel interface providing a seamless copilot experience while browsing.
- **Current-Page Product Extraction**:
  - Automatically identifies supported store pages (Amazon, Best Buy, Flipkart, Walmart, Target).
  - Extracts visible product title, brand, price, currency, thumbnail image, and technical specification tables.
  - Normalizes data into the shared `ExtractedProduct` schema with timestamp and data provenance.
  - Prompt injection defense: Treats all webpage content as untrusted input, stripping scripts and neutralizing system prompt overrides.
- **Interactive Product Banner**:
  - Displays the active product with provenance badge and unverified attribute warnings.
  - Collapsible specifications drawer.
  - One-click quick actions: **"Analyze with ShopSense"**, **"Find Alternatives"**, and **"Compare"**.
- **Multi-Store Product Discovery & Comparison**:
  - Unified multi-store candidate pool spanning Local Catalog, Amazon India, and Flipkart.
  - Cross-store duplicate detection and variant grouping.
  - Side-by-side merchant price comparison showing exact savings deltas and direct store links.
  - Benchmark USD currency normalization for fair ranking across USD, INR, EUR, and GBP.
- **Chat & Multi-Agent Swarm**:
  - Real-time conversation with verified product recommendations.
  - Fit-score breakdown drawer with category, use-case, and feature alignment.
  - Multi-product comparison modal with side-by-side spec differential.
  - "Why Not" rejected products inspector explaining exact exclusion criteria.

## Loading in Google Chrome

1. Build the extension:
   ```bash
   cd extension
   npm install
   npm run build
   ```
2. Open Chrome and navigate to `chrome://extensions`.
3. Enable **Developer mode** using the toggle switch in the upper-right corner.
4. Click **Load unpacked** in the top-left toolbar.
5. Select the `extension/dist` directory.
6. Open any supported store page (e.g., an Amazon or Best Buy product) and click the ShopSense AI extension icon to open the side panel.

## Development & Testing

- **Run Dev Server**:
  ```bash
  npm run dev
  ```
- **Run Extraction Unit Tests**:
  ```bash
  npx tsx src/extraction/__tests__/run_extraction_tests.ts
  ```
- **Type Checking & Production Build**:
  ```bash
  npm run build
  ```
