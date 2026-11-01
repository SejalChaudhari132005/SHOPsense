// ShopSense AI — Typed Backend API Client
// Securely communicates with the FastAPI orchestrator (Rule: No Groq API keys in the extension)

import {
  BackendHealth,
  OrchestratorResponse,
  CompareResponse,
  WhyNotResponse,
  RefineRequest,
  PreferenceState,
} from '../types';

export class ApiError extends Error {
  isOffline: boolean;
  statusCode?: number;

  constructor(message: string, isOffline = false, statusCode?: number) {
    super(message);
    this.name = 'ApiError';
    this.isOffline = isOffline;
    this.statusCode = statusCode;
  }
}

const DEFAULT_API_BASE = 'http://127.0.0.1:8000';

class ShopSenseApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = DEFAULT_API_BASE) {
    this.baseUrl = baseUrl;
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  public setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/+$/, '');
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...options.headers,
    };

    try {
      const response = await fetch(url, { ...options, headers });

      if (!response.ok) {
        let errorDetail = `Server returned HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body?.message) errorDetail = body.message;
          else if (body?.detail) errorDetail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        } catch {
          // Response body was not JSON
        }
        throw new ApiError(errorDetail, false, response.status);
      }

      return (await response.json()) as T;
    } catch (err: any) {
      if (err instanceof ApiError) {
        throw err;
      }
      // Network failure / offline
      console.error('[ShopSense API Client Error]', err);
      throw new ApiError(
        `Unable to reach ShopSense backend at ${this.baseUrl}. Please verify the FastAPI server is running with 'uvicorn app.main:app'.`,
        true
      );
    }
  }

  /**
   * Health and diagnostic check
   */
  async checkHealth(): Promise<BackendHealth> {
    return this.request<BackendHealth>('/api/health');
  }

  /**
   * Main conversational turn through the 10-agent pipeline
   */
  async sendChatMessage(
    message: string,
    sessionId: string,
    turnId: number,
    clientContext?: Record<string, any>,
    inputSource: 'text' | 'voice' = 'text'
  ): Promise<OrchestratorResponse> {
    return this.request<OrchestratorResponse>('/api/chat/', {
      method: 'POST',
      body: JSON.stringify({
        message,
        session_id: sessionId,
        turn_id: turnId,
        input_source: inputSource,
        client_context: clientContext || null,
      }),
    });
  }

  /**
   * Side-by-side comparison for 2 to 4 products
   */
  async compareProducts(productIds: string[], sessionId?: string): Promise<CompareResponse> {
    return this.request<CompareResponse>('/api/compare/', {
      method: 'POST',
      body: JSON.stringify({
        product_ids: productIds,
        session_id: sessionId || null,
      }),
    });
  }

  /**
   * Why-Not explanation for an excluded or lower-ranked product
   */
  async getWhyNotAnalysis(productId: string, sessionId: string, compareWithId?: string): Promise<WhyNotResponse> {
    return this.request<WhyNotResponse>('/api/why-not/', {
      method: 'POST',
      body: JSON.stringify({
        product_id: productId,
        session_id: sessionId,
        compare_with_id: compareWithId || null,
      }),
    });
  }

  /**
   * Preference Memory: Retrieve user durable preferences and consent status
   */
  async getPreferences(userId: string = 'default_user'): Promise<PreferenceState> {
    return this.request<PreferenceState>(`/api/preferences/?user_id=${encodeURIComponent(userId)}`);
  }

  /**
   * Preference Memory: Save explicit consent and durable preferences
   */
  async savePreferences(payload: {
    user_id?: string;
    has_consented: boolean;
    is_memory_enabled: boolean;
    durable_preferences: Record<string, any>;
  }): Promise<PreferenceState> {
    return this.request<PreferenceState>('/api/preferences/', {
      method: 'POST',
      body: JSON.stringify({
        user_id: payload.user_id || 'default_user',
        has_consented: payload.has_consented,
        is_memory_enabled: payload.is_memory_enabled,
        durable_preferences: payload.durable_preferences,
      }),
    });
  }

  /**
   * Preference Memory: Toggle memory active/paused state
   */
  async togglePreferenceMemory(userId: string = 'default_user', isEnabled: boolean): Promise<PreferenceState> {
    return this.request<PreferenceState>(
      `/api/preferences/toggle?user_id=${encodeURIComponent(userId)}&is_enabled=${isEnabled}`,
      { method: 'PUT' }
    );
  }

  /**
   * Preference Memory: Right to be Forgotten - wipe all stored preferences
   */
  async deletePreferences(userId: string = 'default_user'): Promise<{ status: string; user_id: string; message: string }> {
    return this.request<{ status: string; user_id: string; message: string }>(
      `/api/preferences/?user_id=${encodeURIComponent(userId)}`,
      { method: 'DELETE' }
    );
  }

  /**
   * Mutates constraints (budget, color, size, brand) and reranks
   */
  async refineConstraints(refineData: RefineRequest): Promise<OrchestratorResponse> {
    return this.request<OrchestratorResponse>('/api/refine/', {
      method: 'POST',
      body: JSON.stringify(refineData),
    });
  }

  /**
   * Resets temporary dialogue session memory
   */
  async resetSession(sessionId: string): Promise<{ status: string; session_id: string }> {
    return this.request<{ status: string; session_id: string }>(`/api/chat/session/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
  }

  /**
   * User feedback tracking (thumbs up/down or accept/reject)
   */
  async recordFeedback(sessionId: string, productId: string, accepted: boolean): Promise<{ status: string }> {
    return this.request<{ status: string }>('/api/chat/feedback', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        product_id: productId,
        accepted,
      }),
    });
  }

  /**
   * Truthful multi-store operational status table
   */
  async getStoreStatuses(): Promise<{
    stores: Array<{
      store_id: string;
      store_name: string;
      status: string;
      is_configured: boolean;
      is_mocked: boolean;
      supported_currencies: string[];
      notes: string;
    }>;
    total_stores: number;
    live_verified_count: number;
    mocked_demo_count: number;
  }> {
    return this.request('/api/stores/status');
  }
}

export const apiClient = new ShopSenseApiClient();
export default apiClient;
