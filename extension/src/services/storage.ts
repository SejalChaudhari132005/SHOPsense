// ShopSense AI — Chrome Storage & Session Management
// Persists active session IDs and conversation history across side-panel re-openings

import { ChatMessage } from '../types';

const SESSION_KEY = 'shopsense_session_id';
const MESSAGES_KEY = 'shopsense_chat_messages';
const COMPARISON_KEY = 'shopsense_comparison_list';

function generateUUID(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return 'shopsense_' + crypto.randomUUID();
  }
  return 'shopsense_' + Math.random().toString(36).substring(2, 12) + '_' + Date.now();
}

/**
 * Storage adapter that uses chrome.storage.local if available, else falls back to localStorage
 */
class StorageService {
  private hasChromeStorage(): boolean {
    return typeof chrome !== 'undefined' && !!chrome.storage && !!chrome.storage.local;
  }

  async getSessionId(): Promise<string> {
    if (this.hasChromeStorage()) {
      return new Promise((resolve) => {
        chrome.storage.local.get([SESSION_KEY], (res) => {
          let id = res[SESSION_KEY];
          if (!id) {
            id = generateUUID();
            chrome.storage.local.set({ [SESSION_KEY]: id });
          }
          resolve(id);
        });
      });
    }

    // Fallback to localStorage
    let id = localStorage.getItem(SESSION_KEY);
    if (!id) {
      id = generateUUID();
      localStorage.setItem(SESSION_KEY, id);
    }
    return id;
  }

  async resetSession(): Promise<string> {
    const newId = generateUUID();
    if (this.hasChromeStorage()) {
      await new Promise<void>((resolve) => {
        chrome.storage.local.set({ [SESSION_KEY]: newId, [MESSAGES_KEY]: [] }, () => resolve());
      });
    } else {
      localStorage.setItem(SESSION_KEY, newId);
      localStorage.removeItem(MESSAGES_KEY);
    }
    return newId;
  }

  async getChatHistory(): Promise<ChatMessage[]> {
    if (this.hasChromeStorage()) {
      return new Promise((resolve) => {
        chrome.storage.local.get([MESSAGES_KEY], (res) => {
          resolve(res[MESSAGES_KEY] || []);
        });
      });
    }

    try {
      const raw = localStorage.getItem(MESSAGES_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  async saveChatHistory(messages: ChatMessage[]): Promise<void> {
    // Keep at most 40 messages to avoid local storage overflow
    const trimmed = messages.slice(-40);
    if (this.hasChromeStorage()) {
      return new Promise((resolve) => {
        chrome.storage.local.set({ [MESSAGES_KEY]: trimmed }, () => resolve());
      });
    }
    localStorage.setItem(MESSAGES_KEY, JSON.stringify(trimmed));
  }

  async getComparisonList(): Promise<string[]> {
    if (this.hasChromeStorage()) {
      return new Promise((resolve) => {
        chrome.storage.local.get([COMPARISON_KEY], (res) => {
          resolve(res[COMPARISON_KEY] || []);
        });
      });
    }
    try {
      const raw = localStorage.getItem(COMPARISON_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  async saveComparisonList(ids: string[]): Promise<void> {
    if (this.hasChromeStorage()) {
      return new Promise((resolve) => {
        chrome.storage.local.set({ [COMPARISON_KEY]: ids }, () => resolve());
      });
    }
    localStorage.setItem(COMPARISON_KEY, JSON.stringify(ids));
  }
}

export const storageService = new StorageService();
export default storageService;
