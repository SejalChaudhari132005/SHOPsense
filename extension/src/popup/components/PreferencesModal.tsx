// ShopSense AI — Preference Memory Across Sessions Modal
// Implements Feature 2: Consented durable preference memory, durable vs temporary distinction,
// view/edit/delete controls, and memory pause toggle.

import React, { useEffect, useState } from 'react';
import { 
  X, 
  ShieldCheck, 
  Trash2, 
  Save, 
  Power, 
  AlertCircle, 
  CheckCircle2, 
  Loader2, 
  UserCheck,
  Info
} from 'lucide-react';
import { PreferenceState } from '../../types';
import apiClient from '../../services/api';

interface PreferencesModalProps {
  userId?: string;
  onClose: () => void;
}

export const PreferencesModal: React.FC<PreferencesModalProps> = ({
  userId = 'default_user',
  onClose,
}) => {
  const [data, setData] = useState<PreferenceState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Form State
  const [consentGiven, setConsentGiven] = useState(false);
  const [isMemoryEnabled, setIsMemoryEnabled] = useState(true);
  const [preferredBrands, setPreferredBrands] = useState('');
  const [preferredCategories, setPreferredCategories] = useState('');
  const [shoeSize, setShoeSize] = useState('');
  const [apparelSize, setApparelSize] = useState('');
  const [budgetTier, setBudgetTier] = useState('mid-range');
  const [materialEthics, setMaterialEthics] = useState('');

  // Fetch initial preferences
  useEffect(() => {
    setLoading(true);
    apiClient
      .getPreferences(userId)
      .then((res) => {
        setData(res);
        setConsentGiven(res.consent_given);
        setIsMemoryEnabled(res.is_memory_enabled ?? true);

        const prefs = res.durable_preferences || res.preferences || {};
        setPreferredBrands(Array.isArray(prefs.preferred_brands) ? prefs.preferred_brands.join(', ') : '');
        setPreferredCategories(Array.isArray(prefs.preferred_categories) ? prefs.preferred_categories.join(', ') : '');
        setShoeSize(prefs.shoe_size ? String(prefs.shoe_size) : '');
        setApparelSize(prefs.apparel_size ? String(prefs.apparel_size) : '');
        setBudgetTier(prefs.budget_tier || 'mid-range');
        setMaterialEthics(prefs.material_ethics || '');

        setLoading(false);
      })
      .catch((err) => {
        setMessage({ text: err.message || 'Failed to load preferences', type: 'error' });
        setLoading(false);
      });
  }, [userId]);

  // Save Preferences
  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!consentGiven) {
      setMessage({
        text: 'Please confirm explicit consent before saving preferences across sessions.',
        type: 'error',
      });
      return;
    }

    setSaving(true);
    setMessage(null);

    const durable_preferences = {
      preferred_brands: preferredBrands
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      preferred_categories: preferredCategories
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      shoe_size: shoeSize.trim() || null,
      apparel_size: apparelSize.trim() || null,
      budget_tier: budgetTier,
      material_ethics: materialEthics.trim() || null,
    };

    try {
      const res = await apiClient.savePreferences({
        user_id: userId,
        has_consented: consentGiven,
        is_memory_enabled: isMemoryEnabled,
        durable_preferences,
      });

      setData(res);
      setMessage({ text: 'Durable preferences saved successfully!', type: 'success' });
    } catch (err: any) {
      setMessage({ text: err.message || 'Failed to save preferences', type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  // Toggle Memory State
  const handleToggleMemory = async () => {
    const nextState = !isMemoryEnabled;
    setIsMemoryEnabled(nextState);

    try {
      const res = await apiClient.togglePreferenceMemory(userId, nextState);
      setData(res);
      setMessage({
        text: nextState
          ? 'Preference memory re-enabled.'
          : 'Preference memory paused. Saved preferences will not be consulted until resumed.',
        type: 'success',
      });
    } catch (err: any) {
      setIsMemoryEnabled(!nextState);
      setMessage({ text: err.message || 'Failed to toggle memory', type: 'error' });
    }
  };

  // Delete All Stored Preferences (Right to be Forgotten)
  const handleDeleteAll = async () => {
    const confirmDelete = window.confirm(
      'Are you sure you want to permanently delete all saved preferences? This action cannot be undone.'
    );
    if (!confirmDelete) return;

    setSaving(true);
    try {
      await apiClient.deletePreferences(userId);
      setConsentGiven(false);
      setPreferredBrands('');
      setPreferredCategories('');
      setShoeSize('');
      setApparelSize('');
      setMaterialEthics('');
      setBudgetTier('mid-range');
      setData({
        user_id: userId,
        consent_given: false,
        is_memory_enabled: false,
        memory_status: 'no_consent',
        durable_preferences: null,
      });
      setMessage({ text: 'All stored preferences permanently deleted.', type: 'success' });
    } catch (err: any) {
      setMessage({ text: err.message || 'Failed to delete preferences', type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-sheet preferences-sheet" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <ShieldCheck size={18} className="modal-icon text-brand" />
            <h2 className="modal-title">Cross-Session Preference Memory</h2>
          </div>
          <button
            type="button"
            className="btn-icon-close"
            onClick={onClose}
            title="Close modal"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="modal-body">
          {/* User Profile Info Pill */}
          <div className="profile-indicator-row">
            <span className="profile-id-tag">
              <UserCheck size={12} /> Profile: <strong>{userId}</strong>
            </span>
            <span className={`status-badge-memory ${isMemoryEnabled && consentGiven ? 'active' : 'paused'}`}>
              {isMemoryEnabled && consentGiven ? 'Memory Active' : 'Memory Disabled'}
            </span>
          </div>

          {loading ? (
            <div className="modal-loading-state">
              <Loader2 size={24} className="spinner-icon" />
              <p>Loading preference profile...</p>
            </div>
          ) : (
            <form onSubmit={handleSave} className="preferences-form">
              {/* Notification Banner */}
              {message && (
                <div className={`pref-alert-banner ${message.type}`}>
                  {message.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
                  <span>{message.text}</span>
                </div>
              )}

              {/* Consent Toggle Box */}
              <div className="pref-consent-box">
                <label className="pref-toggle-label">
                  <input
                    type="checkbox"
                    checked={consentGiven}
                    onChange={(e) => setConsentGiven(e.target.checked)}
                    className="pref-checkbox"
                  />
                  <div className="pref-consent-text">
                    <strong>Enable Cross-Session Preference Memory</strong>
                    <p>
                      Explicitly permit ShopSense to store your durable preferences in encrypted local SQLite database.
                    </p>
                  </div>
                </label>
              </div>

              {/* Memory Pause Switch */}
              {consentGiven && (
                <div className="pref-control-row">
                  <div className="pref-control-label">
                    <Power size={14} />
                    <span>Preference Memory Status:</span>
                  </div>
                  <button
                    type="button"
                    className={`btn-memory-toggle ${isMemoryEnabled ? 'enabled' : 'disabled'}`}
                    onClick={handleToggleMemory}
                    title="Toggle active memory"
                  >
                    {isMemoryEnabled ? 'Active (Consulting)' : 'Paused (Ignored)'}
                  </button>
                </div>
              )}

              {/* Privacy Notice on Durable vs Temporary */}
              <div className="privacy-notice-box">
                <Info size={14} className="privacy-icon" />
                <div className="privacy-text">
                  <strong>Durable vs Temporary Constraints:</strong>
                  <p>
                    ShopSense preserves long-term attributes (e.g. shoe size, favorite brands). Temporary constraints (e.g. gifts, birthday deadlines, one-time occasions) are strictly session-only and never written to memory.
                  </p>
                </div>
              </div>

              {/* Preference Fields */}
              <div className="pref-fields-section">
                <div className="form-group">
                  <label htmlFor="pref-brands">Favorite / Preferred Brands (comma-separated)</label>
                  <input
                    id="pref-brands"
                    type="text"
                    className="form-input"
                    placeholder="e.g. Sony, Bose, Nike, Apple"
                    value={preferredBrands}
                    onChange={(e) => setPreferredBrands(e.target.value)}
                    disabled={!consentGiven}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="pref-categories">Preferred Categories</label>
                  <input
                    id="pref-categories"
                    type="text"
                    className="form-input"
                    placeholder="e.g. Electronics, Footwear, Travel"
                    value={preferredCategories}
                    onChange={(e) => setPreferredCategories(e.target.value)}
                    disabled={!consentGiven}
                  />
                </div>

                <div className="form-row-2col">
                  <div className="form-group">
                    <label htmlFor="pref-shoe">Shoe Size (US)</label>
                    <input
                      id="pref-shoe"
                      type="text"
                      className="form-input"
                      placeholder="e.g. 10.5"
                      value={shoeSize}
                      onChange={(e) => setShoeSize(e.target.value)}
                      disabled={!consentGiven}
                    />
                  </div>

                  <div className="form-group">
                    <label htmlFor="pref-apparel">Apparel Size</label>
                    <input
                      id="pref-apparel"
                      type="text"
                      className="form-input"
                      placeholder="e.g. M, L, XL"
                      value={apparelSize}
                      onChange={(e) => setApparelSize(e.target.value)}
                      disabled={!consentGiven}
                    />
                  </div>
                </div>

                <div className="form-row-2col">
                  <div className="form-group">
                    <label htmlFor="pref-budget">Default Budget Tier</label>
                    <select
                      id="pref-budget"
                      className="form-select"
                      value={budgetTier}
                      onChange={(e) => setBudgetTier(e.target.value)}
                      disabled={!consentGiven}
                    >
                      <option value="budget-conscious">Budget-Conscious (&lt; $50)</option>
                      <option value="mid-range">Mid-Range ($50 - $250)</option>
                      <option value="premium">Premium (&gt; $250)</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label htmlFor="pref-ethics">Material / Ethics</label>
                    <input
                      id="pref-ethics"
                      type="text"
                      className="form-input"
                      placeholder="e.g. Vegan, Recycled"
                      value={materialEthics}
                      onChange={(e) => setMaterialEthics(e.target.value)}
                      disabled={!consentGiven}
                    />
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="pref-actions-footer">
                <button
                  type="button"
                  className="btn-danger-outline"
                  onClick={handleDeleteAll}
                  disabled={saving || !data?.consent_given}
                  title="Erase all stored user preferences"
                >
                  <Trash2 size={13} />
                  <span>Wipe All Memory</span>
                </button>

                <div className="pref-save-group">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={onClose}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={saving || !consentGiven}
                  >
                    {saving ? <Loader2 size={13} className="spinner-icon" /> : <Save size={13} />}
                    <span>Save Preferences</span>
                  </button>
                </div>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default PreferencesModal;
