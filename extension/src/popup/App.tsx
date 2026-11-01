// ShopSense AI — Main Chrome Side-Panel Application
// Manifest V3 Shopping Assistant powered by LangGraph 10-Agent Swarm

import React, { useState, useEffect, useRef } from 'react';
import { 
  Send, 
  Loader2, 
  RotateCcw, 
  Sparkles,
  Mic,
  MicOff
} from 'lucide-react';

import { 
  ChatMessage, 
  BackendHealth, 
  PageContext, 
  ProductRecommendation, 
  RefineRequest,
  ExtractedProduct
} from '../types';
import apiClient, { ApiError } from '../services/api';
import { formatPriceInINR } from '../services/currency';
import storageService from '../services/storage';
import { MOCK_PAGE_CONTEXTS } from './mockContexts';

import Header from './components/Header';
import CurrentProductBanner from './components/CurrentProductBanner';
import ProductCard from './components/ProductCard';
import ClarificationCard from './components/ClarificationCard';
import FallbackCard from './components/FallbackCard';
import EmptyState from './components/EmptyState';
import CompareModal from './components/CompareModal';
import WhyNotModal from './components/WhyNotModal';
import RefinementDrawer from './components/RefinementDrawer';
import PreferencesModal from './components/PreferencesModal';
import ComplementaryCard from './components/ComplementaryCard';
import AppFooter from './components/AppFooter';

export const App: React.FC = () => {
  const isExtensionEnvironment = typeof chrome !== 'undefined' && !!chrome.runtime?.id && !!chrome.runtime?.sendMessage;
  const [activeSim, setActiveSim] = useState<string>('amazon_sony');
  const [sessionId, setSessionId] = useState<string>('shopsense_init');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isConnecting, setIsConnecting] = useState<boolean>(true);
  const [backendHealth, setBackendHealth] = useState<BackendHealth | null>(null);
  const [pageContext, setPageContext] = useState<PageContext | null>(null);
  const [isListening, setIsListening] = useState<boolean>(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  // Modals & Panels
  const [comparedProductIds, setComparedProductIds] = useState<string[]>([]);
  const [showCompareModal, setShowCompareModal] = useState<boolean>(false);
  const [showRefineDrawer, setShowRefineDrawer] = useState<boolean>(false);
  const [showPreferencesModal, setShowPreferencesModal] = useState<boolean>(false);
  const [whyNotTarget, setWhyNotTarget] = useState<{ productId: string; productName: string } | null>(null);
  const [expandedRecs, setExpandedRecs] = useState<Record<string, boolean>>({});

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const inputSourceRef = useRef<'text' | 'voice'>('text');

  // Auto-scroll chat to latest message
  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior });
  };

  useEffect(() => {
    scrollToBottom('auto');
  }, [messages, isLoading]);

  // Initial Load: Storage, Backend Health, Active Tab Context
  useEffect(() => {
    let mounted = true;

    async function init() {
      try {
        const id = await storageService.getSessionId();
        const storedMessages = await storageService.getChatHistory();
        const storedCompared = await storageService.getComparisonList();

        if (mounted) {
          setSessionId(id);
          if (storedMessages.length > 0) {
            setMessages(storedMessages);
          }
          setComparedProductIds(storedCompared);
        }
      } catch (e) {
        console.warn('[ShopSense AI] Initialization storage error:', e);
      }

      // Check backend health
      try {
        const health = await apiClient.checkHealth();
        if (mounted) {
          setBackendHealth(health);
          setIsConnecting(false);
        }
      } catch (err) {
        if (mounted) {
          setBackendHealth(null);
          setIsConnecting(false);
        }
      }

      // Initial active tab context fetch
      refreshActiveTabContext();
    }

    init();

    return () => {
      mounted = false;
    };
  }, []);

  // Manually or automatically refresh active tab context
  const refreshActiveTabContext = () => {
    if (isExtensionEnvironment) {
      try {
        chrome.runtime.sendMessage({ type: 'FETCH_ACTIVE_TAB_CONTEXT' }, (res) => {
          if (res && !chrome.runtime.lastError) {
            setPageContext(res);
          }
        });
      } catch (e) {
        console.warn('[ShopSense AI] Error fetching tab context:', e);
      }
    } else {
      // In standalone dev preview, cycle through demo product
      setPageContext(MOCK_PAGE_CONTEXTS['amazon_sony']);
    }
  };

  // Listen for tab updates broadcast by service worker
  useEffect(() => {
    if (isExtensionEnvironment && chrome.runtime?.onMessage) {
      const listener = (msg: any) => {
        if (msg.type === 'TAB_UPDATED' || msg.type === 'TAB_ACTIVATED') {
          refreshActiveTabContext();
        }
      };
      chrome.runtime.onMessage.addListener(listener);
      return () => {
        chrome.runtime.onMessage.removeListener(listener);
      };
    }
  }, [isExtensionEnvironment]);

  // Sync messages to storage whenever updated
  useEffect(() => {
    if (messages.length > 0) {
      storageService.saveChatHistory(messages);
    }
  }, [messages]);

  // Sync comparison IDs to storage
  useEffect(() => {
    storageService.saveComparisonList(comparedProductIds);
  }, [comparedProductIds]);

  const toggleVoiceInput = () => {
    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) {
      setVoiceError('Voice input is not supported in this browser.');
      return;
    }
    if (isListening) {
      recognitionRef.current?.stop();
      return;
    }

    const recognition = new SpeechRecognitionAPI();
    recognition.lang = navigator.language || 'en-IN';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onstart = () => {
      setVoiceError(null);
      setIsListening(true);
    };
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript || '')
        .join('');
      setInputMessage(transcript);
      inputSourceRef.current = 'voice';
    };
    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      setVoiceError(
        event.error === 'not-allowed'
          ? 'Microphone access was blocked. Allow microphone access for ShopSense in Chrome settings, then try again.'
          : `Voice input failed: ${event.error}.`
      );
      setIsListening(false);
    };
    recognition.onend = () => {
      setIsListening(false);
    };
    recognitionRef.current = recognition;
    try {
      // Start synchronously from the button gesture; awaiting permission first
      // causes Chrome to reject the Web Speech request as "not-allowed".
      recognition.start();
    } catch (error) {
      setIsListening(false);
      setVoiceError(
        error instanceof DOMException && error.name === 'NotAllowedError'
          ? 'Microphone access was blocked. Allow microphone access for ShopSense in Chrome settings, then try again.'
          : 'Voice input could not start. Please try the microphone button again.'
      );
    }
  };

  // Execute a conversational turn
  const handleSendMessage = async (
    textToSend?: string,
    inputSource?: 'text' | 'voice'
  ) => {
    const text = (textToSend || inputMessage).trim();
    const effectiveInputSource = textToSend ? 'text' : inputSourceRef.current;
    if (!text || isLoading) return;

    const userMessage: ChatMessage = {
      id: 'msg_' + Date.now(),
      sender: 'user',
      text,
      timestamp: Date.now(),
    };

    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInputMessage('');
    setIsLoading(true);

    const turnId = newMessages.filter((m) => m.sender === 'user').length;

    try {
      const response = await apiClient.sendChatMessage(
        text,
        sessionId,
        turnId,
        pageContext?.supported ? pageContext : undefined,
        inputSource ?? effectiveInputSource
      );

      // Construct Assistant Response Message
      const assistantMessage: ChatMessage = {
        id: 'msg_asst_' + Date.now(),
        sender: 'assistant',
        text: response.analysis_summary
          ? `${response.analysis_summary}\n\n${response.message}`
          : response.message,
        timestamp: Date.now(),
        turnId: response.turn_id,
        actionTaken: response.action_taken,
        recommendations: response.recommendations || [],
        clarification: response.clarification,
        fallback: response.fallback,
        follow_up_suggestion: response.follow_up_suggestion,
        follow_up_question: response.follow_up_question,
        topThreeComparison: response.top_three_comparison,
      };

      setMessages([...newMessages, assistantMessage]);
      setBackendHealth((prev) => prev ? { ...prev, status: 'healthy' } : { status: 'healthy', version: '0.1.0', activeAgents: 10 });
    } catch (err: any) {
      const isOffline = err instanceof ApiError ? err.isOffline : false;
      const errorMsg = err.message || 'An error occurred while communicating with ShopSense.';

      const errorResponse: ChatMessage = {
        id: 'msg_err_' + Date.now(),
        sender: 'assistant',
        text: isOffline
          ? `⚠️ **Backend Unavailable**\n\nCould not reach the ShopSense FastAPI server at \`${apiClient.getBaseUrl()}\`.\n\nPlease ensure your backend is running with:\n\`\`\`bash\nuvicorn app.main:app --port 8000\n\`\`\``
          : `⚠️ **Processing Error**: ${errorMsg}`,
        timestamp: Date.now(),
        isError: true,
      };

      setMessages([...newMessages, errorResponse]);
      if (isOffline) {
        setBackendHealth(null);
      }
    } finally {
      setIsLoading(false);
    }
  };

  // User selects an option from ClarificationCard
  const handleSelectClarificationOption = (option: string) => {
    handleSendMessage(option);
  };

  // Compare product toggle
  const handleCompareToggle = (productId: string) => {
    setComparedProductIds((prev) => {
      if (prev.includes(productId)) {
        return prev.filter((id) => id !== productId);
      }
      if (prev.length >= 4) {
        alert('You can compare up to 4 products at a time.');
        return prev;
      }
      const updated = [...prev, productId];
      if (updated.length >= 2) {
        setShowCompareModal(true);
      }
      return updated;
    });
  };

  // Why-not analysis trigger
  const handleWhyNotClick = (productId: string, productName: string) => {
    setWhyNotTarget({ productId, productName });
  };

  // Apply constraint refinement
  const handleApplyRefine = async (refineData: RefineRequest) => {
    setIsLoading(true);
    setShowRefineDrawer(false);

    try {
      const response = await apiClient.refineConstraints(refineData);
      const assistantMessage: ChatMessage = {
        id: 'msg_asst_' + Date.now(),
        sender: 'assistant',
        text: response.message,
        timestamp: Date.now(),
        turnId: response.turn_id,
        actionTaken: response.action_taken,
        recommendations: response.recommendations || [],
        clarification: response.clarification,
        fallback: response.fallback,
        topThreeComparison: response.top_three_comparison,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err: any) {
      alert(`Could not apply refinement: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Reset conversation and session
  const handleResetSession = async () => {
    if (messages.length > 0) {
      const confirmReset = window.confirm(
        'Start a new shopping request? This will clear your current conversation history and session constraints.'
      );
      if (!confirmReset) return;
    }

    try {
      await apiClient.resetSession(sessionId);
    } catch {
      // Backend may be offline, still reset locally
    }

    const newId = await storageService.resetSession();
    setSessionId(newId);
    setMessages([]);
    setComparedProductIds([]);
    setInputMessage('');
  };

  // Analyze extracted product from active tab
  const handleAnalyzeExtractedProduct = (product: ExtractedProduct) => {
    const brandPrefix = product.brand ? `${product.brand} ` : '';
    const formattedPrice = formatPriceInINR(product.price, product.currency);
    const priceText = formattedPrice !== 'Price unavailable' ? ` (${formattedPrice})` : '';
    const prompt = `Can you analyze ${brandPrefix}${product.product_name}${priceText}? What are its key specifications, standout strengths, trade-offs, and value for money?`;
    handleSendMessage(prompt);
  };

  // Find alternatives to extracted product
  const handleFindAlternatives = (product: ExtractedProduct) => {
    const brandPrefix = product.brand ? `${product.brand} ` : '';
    const formattedPrice = formatPriceInINR(product.price, product.currency);
    const priceLimit = formattedPrice !== 'Price unavailable'
      ? ` around or under ${formattedPrice}`
      : '';
    const prompt = `Find the best verified alternatives in the catalog for ${brandPrefix}${product.product_name}${priceLimit}. Compare their features and value.`;
    handleSendMessage(prompt);
  };

  // Add extracted product to comparison
  const handleCompareProduct = (product: ExtractedProduct) => {
    if (product.product_id) {
      handleCompareToggle(product.product_id);
    } else {
      handleSendMessage(`Compare ${product.product_name} with top candidates in the catalog.`);
    }
  };

  // Incorporate active browsing context
  const handleIncorporatePageContext = (context: PageContext) => {
    if (context.extractedProduct) {
      handleAnalyzeExtractedProduct(context.extractedProduct);
    } else {
      const prompt = context.brand
        ? `I'm looking at ${context.brand} ${context.title}. Can you find similar alternatives or compare it with better matches within my budget?`
        : `I'm looking at ${context.title}. How does this match my criteria and what are the best alternatives?`;
      handleSendMessage(prompt);
    }
  };

  // Switch simulation context in dev/preview mode
  const handleSwitchSim = (key: string) => {
    setActiveSim(key);
    setPageContext(MOCK_PAGE_CONTEXTS[key] ?? null);
  };

  return (
    <div className="shopsense-app" role="region" aria-label="ShopSense AI Assistant">
      {/* Header Bar */}
      <Header
        health={backendHealth}
        isConnecting={isConnecting}
        comparedCount={comparedProductIds.length}
        onOpenCompare={() => setShowCompareModal(true)}
        onOpenRefine={() => setShowRefineDrawer(true)}
        onOpenPreferences={() => setShowPreferencesModal(true)}
        onResetSession={handleResetSession}
        onRefreshTab={refreshActiveTabContext}
        pageContext={pageContext}
        onIncorporatePageContext={handleIncorporatePageContext}
      />

      {/* Dev / Browser Preview Simulation Bar */}
      {!isExtensionEnvironment && (
        <div className="preview-simulation-bar" role="toolbar" aria-label="Dev Page Simulator">
          <span className="sim-label">⚡ Active Tab Simulation:</span>
          <button
            type="button"
            className={`btn-sim ${activeSim === 'amazon_sony' ? 'active' : ''}`}
            onClick={() => handleSwitchSim('amazon_sony')}
            title="Simulate Amazon Sony Headphones extraction"
          >
            Amazon page (INR display)
          </button>
          <button
            type="button"
            className={`btn-sim ${activeSim === 'flipkart_inr' ? 'active' : ''}`}
            onClick={() => handleSwitchSim('flipkart_inr')}
            title="Simulate Flipkart AirPods Max INR extraction"
          >
            Flipkart (₹ INR)
          </button>
          <button
            type="button"
            className={`btn-sim ${activeSim === 'amazon_missing_price' ? 'active' : ''}`}
            onClick={() => handleSwitchSim('amazon_missing_price')}
            title="Simulate page where price is missing"
          >
            Missing Price
          </button>
          <button
            type="button"
            className={`btn-sim ${activeSim === 'malformed_page' ? 'active' : ''}`}
            onClick={() => handleSwitchSim('malformed_page')}
            title="Simulate malformed page layout failure"
          >
            Malformed DOM
          </button>
          <button
            type="button"
            className={`btn-sim ${activeSim === 'unsupported_store' ? 'active' : ''}`}
            onClick={() => handleSwitchSim('unsupported_store')}
            title="Simulate unsupported domain (e.g. Etsy)"
          >
            Unsupported (Etsy)
          </button>
          <button
            type="button"
            className={`btn-sim ${activeSim === 'none' ? 'active' : ''}`}
            onClick={() => handleSwitchSim('none')}
            title="Clear active page context"
          >
            No Page
          </button>
        </div>
      )}

      {/* Active Tab Product Extraction Banner */}
      <CurrentProductBanner
        pageContext={pageContext}
        onAnalyzeProduct={handleAnalyzeExtractedProduct}
        onFindAlternatives={handleFindAlternatives}
        onCompareProduct={handleCompareProduct}
        onRefreshTab={refreshActiveTabContext}
        isLoading={isLoading}
      />

      {/* Main Conversation Stream */}
      <main className="conversation-container" tabIndex={0} aria-label="Conversation History">
        {messages.length === 0 ? (
          <EmptyState onSelectPrompt={(p) => handleSendMessage(p)} />
        ) : (
          <div className="messages-stream">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`message-row ${msg.sender === 'user' ? 'row-user' : 'row-assistant'}`}
              >
                {/* Assistant Avatar */}
                {msg.sender === 'assistant' && (
                  <div className="message-avatar">
                    <Sparkles size={14} className="avatar-icon" />
                  </div>
                )}

                <div className={`message-bubble ${msg.isError ? 'bubble-error' : ''}`}>
                  {/* Message Text */}
                  {!msg.fallback?.fallback_needed && (() => {
                    const clarificationQuestion = msg.clarification?.needs_clarification
                      ? msg.clarification.clarification_question?.trim()
                      : undefined;
                    const displayText = clarificationQuestion
                      ? msg.text.split(clarificationQuestion).join('').trim()
                      : msg.text;

                    return displayText ? (
                    <div className="message-text">
                      {displayText.split('\n\n').map((paragraph, pIdx) => (
                        <p key={pIdx}>{paragraph}</p>
                      ))}
                    </div>
                    ) : null;
                  })()}

                  {/* Clarification Box if present */}
                  {msg.clarification && msg.clarification.needs_clarification && (
                    <ClarificationCard
                      clarification={msg.clarification}
                      onSelectOption={handleSelectClarificationOption}
                    />
                  )}

                  {/* Fallback Constraint Relaxation Notice if present */}
                  {msg.fallback && msg.fallback.fallback_needed && (
                    <FallbackCard
                      fallback={msg.fallback}
                      onApproveRelaxation={(proposedBudget) => {
                        if (proposedBudget != null) {
                          handleSendMessage(
                            `Search with proposed relaxed budget of ₹${proposedBudget}`,
                          );
                        } else {
                          handleSendMessage('Proceed with proposed constraint relaxation');
                        }
                      }}
                      onKeepOriginal={() => {
                        handleSendMessage('Keep my strict original constraints');
                      }}
                    />
                  )}

                  {/* Context-Aware Complementary Suggestion (Feature 5) */}
                  {msg.follow_up_suggestion && (
                    <ComplementaryCard
                      suggestion={msg.follow_up_suggestion}
                      onExplore={(query) => handleSendMessage(query)}
                    />
                  )}
                  {msg.follow_up_question && (
                    <div className="follow-up-question">
                      {msg.follow_up_question}
                    </div>
                  )}

                  {/* Product Recommendations Grid (Section 4.E) */}
                  {msg.recommendations && msg.recommendations.length > 0 && (
                    <div className="recommendations-wrapper">
                      <div className="recommendations-header-row">
                        <span className="recommendations-title">
                          Curated Recommendations
                        </span>
                        <span className="recommendations-count">
                          {expandedRecs[msg.id] 
                            ? `${msg.recommendations.length} items` 
                            : `Top ${Math.min(3, msg.recommendations.length)} of ${msg.recommendations.length}`}
                        </span>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        {(expandedRecs[msg.id] 
                          ? msg.recommendations 
                          : msg.recommendations.slice(0, 3)
                        ).map((rec: ProductRecommendation, idx: number) => (
                          <ProductCard
                            key={rec.product.product_id}
                            recommendation={rec}
                            onCompareToggle={handleCompareToggle}
                            isCompared={comparedProductIds.includes(rec.product.product_id)}
                            onWhyNotClick={handleWhyNotClick}
                            isTopPick={idx === 0}
                          />
                        ))}
                      </div>

                      {/* "View all matches" action (Section 4.E) */}
                      {msg.recommendations.length > 3 && (
                        <button
                          type="button"
                          className="btn-banner-action"
                          style={{ alignSelf: 'center', marginTop: '6px' }}
                          onClick={() => setExpandedRecs(prev => ({ ...prev, [msg.id]: !prev[msg.id] }))}
                        >
                          {expandedRecs[msg.id] 
                            ? 'Show Top 3 Matches' 
                            : `View All ${msg.recommendations.length} Matches`}
                        </button>
                      )}
                    </div>
                  )}

                  {/* Error Retry Option */}
                  {msg.isError && (
                    <button
                      type="button"
                      className="btn-retry-error"
                      onClick={() => {
                        const lastUser = [...messages].reverse().find((m) => m.sender === 'user');
                        if (lastUser) handleSendMessage(lastUser.text);
                      }}
                    >
                      <RotateCcw size={12} />
                      <span>Retry Request</span>
                    </button>
                  )}
                </div>
              </div>
            ))}

            {/* In-flight Loading Indicator */}
            {isLoading && (
              <div className="message-row row-assistant">
                <div className="message-avatar">
                  <Sparkles size={14} className="avatar-icon spinning" />
                </div>
                <div className="message-bubble bubble-thinking">
                  <div className="thinking-content">
                    <Loader2 size={15} className="spinner-icon" />
                    <span>Evaluating catalog constraints and verified specifications...</span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </main>

      {/* Multiline Query Composer (Section 4.C) */}
      <div className="composer-area">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="composer-form"
        >
          <textarea
            ref={inputRef}
            rows={2}
            className="composer-textarea"
            placeholder="Describe what you are looking for, budget, or preferred features..."
            value={inputMessage}
            onChange={(e) => {
              setInputMessage(e.target.value);
              inputSourceRef.current = 'text';
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
              }
            }}
            disabled={isLoading}
            aria-label="Shopping inquiry input"
          />

          <div className="composer-footer-row">
            <span className="composer-hint">
              {voiceError || '↵ to send • Shift+↵ for new line'}
            </span>
            <button
              type="button"
              className="btn-send"
              onClick={toggleVoiceInput}
              disabled={isLoading}
              title={isListening ? 'Stop voice input' : 'Start voice input'}
              aria-label={isListening ? 'Stop voice input' : 'Start voice input'}
            >
              {isListening ? <MicOff size={14} /> : <Mic size={14} />}
            </button>
            <button
              type="submit"
              className="btn-send"
              disabled={!inputMessage.trim() || isLoading}
              title="Send inquiry"
              aria-label="Send message"
            >
              {isLoading ? <Loader2 size={14} className="spinner-icon" /> : <Send size={14} />}
            </button>
          </div>
        </form>
      </div>

      {/* Compact App Footer (Section 4.J) */}
      <AppFooter
        onResetSession={handleResetSession}
        onOpenPreferences={() => setShowPreferencesModal(true)}
      />

      {/* Side-by-Side Comparison Modal */}
      {showCompareModal && (
        <CompareModal
          productIds={comparedProductIds}
          sessionId={sessionId}
          onClose={() => setShowCompareModal(false)}
          onRemoveProduct={(id) => setComparedProductIds((prev) => prev.filter((p) => p !== id))}
          onClearAll={() => {
            setComparedProductIds([]);
            setShowCompareModal(false);
          }}
        />
      )}

      {/* Why-Not Analysis Modal */}
      {whyNotTarget && (
        <WhyNotModal
          productId={whyNotTarget.productId}
          productName={whyNotTarget.productName}
          sessionId={sessionId}
          availableRecommendations={
            [...messages].reverse().find((m) => m.recommendations && m.recommendations.length > 0)?.recommendations || []
          }
          onClose={() => setWhyNotTarget(null)}
          onSelectAlternative={(altId) => {
            setComparedProductIds((prev) => [...prev, altId]);
            setShowCompareModal(true);
          }}
        />
      )}

      {/* Cross-Session Preference Memory Modal (Feature 2) */}
      {showPreferencesModal && (
        <PreferencesModal
          userId="default_user"
          onClose={() => setShowPreferencesModal(false)}
        />
      )}

      {/* Constraint Refinement Drawer */}
      {showRefineDrawer && (
        <RefinementDrawer
          sessionId={sessionId}
          onClose={() => setShowRefineDrawer(false)}
          onApplyRefine={handleApplyRefine}
          isLoading={isLoading}
        />
      )}
    </div>
  );
};

export default App;
