// ShopSense AI — Chrome Extension Background Service Worker (Manifest V3)

console.log('[ShopSense AI] Background Service Worker initialized.');

// Configure side panel to open upon clicking the toolbar icon
if (chrome.sidePanel && 'setPanelBehavior' in chrome.sidePanel) {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.warn('[ShopSense AI] Could not set panel behavior:', error));
}

// Fallback action click handler if panel behavior is unsupported
chrome.action?.onClicked?.addListener((tab) => {
  if (chrome.sidePanel && tab.id) {
    chrome.sidePanel.open({ tabId: tab.id }).catch((err) => {
      console.warn('[ShopSense AI] Could not open side panel:', err);
    });
  }
});

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    console.log('[ShopSense AI] First-time install detected.');
  } else if (details.reason === 'update') {
    console.log('[ShopSense AI] Extension updated.');
  }
});

// Listener for runtime messages
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'PING') {
    sendResponse({ status: 'PONG', timestamp: Date.now() });
    return true;
  }

  // Fetch active tab extraction context
  if (message.type === 'FETCH_ACTIVE_TAB_CONTEXT') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTab = tabs[0];
      if (!activeTab || !activeTab.id || !activeTab.url) {
        sendResponse({ supported: false, error: 'No active tab available' });
        return;
      }

      const url = activeTab.url;

      let host = '';
      try {
        host = new URL(url).hostname.toLowerCase();
      } catch {
        sendResponse({ supported: false, url, host: '', title: activeTab.title || '' });
        return;
      }

      // Check if URL matches supported shopping domains
      const isSupported = /amazon\.|flipkart\.|bestbuy\.|walmart\.|target\./i.test(host);
      if (!isSupported) {
        sendResponse({
          supported: false,
          isProductPage: false,
          url,
          title: activeTab.title || '',
          host,
          message: `ShopSense does not support automated extraction on ${host}. You can still chat or search catalog products directly.`
        });
        return;
      }

      // Send message to content script on active tab
      chrome.tabs.sendMessage(activeTab.id, { type: 'GET_PAGE_CONTEXT' }, (response) => {
        if (chrome.runtime.lastError || !response) {
          // If content script was not yet injected (tab was open before extension loaded),
          // dynamically inject it using chrome.scripting.executeScript
          if (chrome.scripting && activeTab.id) {
            chrome.scripting.executeScript({
              target: { tabId: activeTab.id },
              files: ['assets/content.js']
            }).then(() => {
              // Wait briefly for content script to initialize, then retry extraction
              setTimeout(() => {
                if (!activeTab.id) return;
                chrome.tabs.sendMessage(activeTab.id, { type: 'GET_PAGE_CONTEXT' }, (retryResponse) => {
                  if (chrome.runtime.lastError || !retryResponse) {
                    sendResponse({
                      supported: true,
                      isProductPage: false,
                      url,
                      title: activeTab.title || '',
                      host,
                      message: 'Navigated to store page. Click "Scan Tab" to extract product specifications.'
                    });
                  } else {
                    sendResponse(retryResponse);
                  }
                });
              }, 150);
            }).catch((injectErr) => {
              console.warn('[ShopSense AI] Dynamic script injection failed:', injectErr);
              sendResponse({
                supported: true,
                isProductPage: false,
                url,
                title: activeTab.title || '',
                host,
                message: 'Could not connect to page. Refresh the page or click "Scan Tab".'
              });
            });
          } else {
            sendResponse({
              supported: true,
              isProductPage: false,
              url,
              title: activeTab.title || '',
              host,
              message: 'Waiting for product details or page is still loading.'
            });
          }
        } else {
          sendResponse(response);
        }
      });
    });
    return true; // Keep message channel open for async response
  }

  return false;
});

// Broadcast active tab updates to side panel if open
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.active) {
    chrome.runtime.sendMessage({ type: 'TAB_UPDATED', url: tab.url }).catch(() => {});
  }
});
chrome.tabs.onActivated.addListener(() => {
  chrome.runtime.sendMessage({ type: 'TAB_ACTIVATED' }).catch(() => {});
});
