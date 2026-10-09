/**
 * Settings View (/settings)
 *
 * System settings:
 * 1. Language switcher (Traditional Chinese / English)
 * 2. AI Vision provider & API Key configuration
 * 3. Mobile LAN access guide
 */

import { api } from '../core/api.js';
import { showToast } from '../core/router.js';
import { t, getLocale, setLocale } from '../i18n/index.js';

export async function createSettingsView(params, router) {
  const el = document.createElement('div');
  el.className = 'settings-view';

  const currentLang = getLocale();

  el.innerHTML = `
    <header class="app-header">
      <div style="display: flex; align-items: center; gap: 8px;">
        <a href="/" class="icon-btn" title="${t('app.back')}" data-link>←</a>
        <span style="font-weight: 700; font-size: 1.05rem;">${t('settings.headerTitle')}</span>
      </div>
    </header>

    <main class="container">
      <!-- 1. 介面語言選擇 -->
      <div class="detail-card">
        <h2 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 6px;">🌐 ${t('settings.languageSection')}</h2>
        <div class="locale-grid">
          <div class="locale-option ${currentLang === 'zh-TW' ? 'active' : ''}" data-locale="zh-TW">
            <span class="locale-name">繁體中文</span>
            <span class="locale-desc">Traditional Chinese</span>
          </div>
          <div class="locale-option ${currentLang === 'en' ? 'active' : ''}" data-locale="en">
            <span class="locale-name">English</span>
            <span class="locale-desc">United States</span>
          </div>
        </div>
      </div>

      <!-- 2. AI 服務設定 -->
      <div class="detail-card" style="margin-top: 16px;">
        <h2 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 6px;">✨ ${t('settings.aiSection')}</h2>
        <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 20px; line-height: 1.5;">
          ${t('settings.aiDescription')}
        </p>

        <form id="ai-form" style="display: flex; flex-direction: column; gap: 16px;">
          <div class="ai-field-row">
            <label class="ai-field-label">${t('settings.providerLabel')}</label>
            <select class="ai-edit-input" id="setting-provider">
              <option value="openrouter">OpenRouter</option>
              <option value="google">Google Gemini</option>
              <option value="custom">Custom Endpoint</option>
            </select>
          </div>

          <div class="ai-field-row">
            <label class="ai-field-label">${t('settings.modelLabel')}</label>
            <input type="text" class="ai-edit-input" id="setting-model" placeholder="e.g. gemini-2.5-flash" />
          </div>

          <div class="ai-field-row" id="row-base-url">
            <label class="ai-field-label">API Base URL</label>
            <input type="text" class="ai-edit-input" id="setting-base-url" placeholder="https://..." />
          </div>

          <div class="ai-field-row">
            <label class="ai-field-label">${t('settings.apiKeyLabel')}</label>
            <input type="password" class="ai-edit-input" id="setting-api-key" placeholder="${t('settings.apiKeyPlaceholder')}" />
            <span style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;" id="api-key-status">${t('app.loading')}</span>
          </div>

          <div style="display: flex; gap: 10px; margin-top: 8px;">
            <button type="submit" class="btn-primary" id="btn-save-settings">${t('settings.btnSave')}</button>
            <button type="button" class="btn-secondary" id="btn-test-ai">${t('settings.btnTest')}</button>
          </div>
        </form>
      </div>

      <!-- 3. 手機連線提示 -->
      <div class="detail-card" style="margin-top: 16px;">
        <h3 style="font-size: 1rem; font-weight: 700; margin-bottom: 6px;">📱 Local Wi-Fi Access</h3>
        <p style="font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;">
          Connect your phone to the same Wi-Fi network and open <code>http://&lt;your-pc-ip&gt;:8731/</code> on your mobile browser to enjoy the native camera snap experience.
        </p>
      </div>
    </main>
  `;

  // Language switcher options
  const localeOptions = el.querySelectorAll('.locale-option');
  localeOptions.forEach(opt => {
    opt.addEventListener('click', () => {
      const targetLocale = opt.getAttribute('data-locale');
      if (targetLocale !== getLocale()) {
        setLocale(targetLocale);
      }
    });
  });

  const providerSelect = el.querySelector('#setting-provider');
  const modelInput = el.querySelector('#setting-model');
  const baseUrlInput = el.querySelector('#setting-base-url');
  const apiKeyInput = el.querySelector('#setting-api-key');
  const apiKeyStatus = el.querySelector('#api-key-status');
  const form = el.querySelector('#ai-form');
  const btnTestAi = el.querySelector('#btn-test-ai');
  const rowBaseUrl = el.querySelector('#row-base-url');

  providerSelect.addEventListener('change', () => {
    const val = providerSelect.value;
    rowBaseUrl.style.display = (val === 'custom') ? 'flex' : 'none';
    if (val === 'google') {
      baseUrlInput.value = 'https://generativelanguage.googleapis.com/v1beta/openai';
      if (!modelInput.value || modelInput.value.includes('qwen')) {
        modelInput.value = 'gemini-2.5-flash';
      }
    } else if (val === 'openrouter') {
      baseUrlInput.value = 'https://openrouter.ai/api/v1';
    }
  });

  async function loadSettings() {
    try {
      const data = await api.getAiSettings();
      providerSelect.value = data.provider || 'openrouter';
      modelInput.value = data.model || '';
      baseUrlInput.value = data.base_url || '';
      rowBaseUrl.style.display = (data.provider === 'custom') ? 'flex' : 'none';
      apiKeyStatus.textContent = data.configured
        ? `✓ ${t('settings.statusConfigured')}`
        : `⚠️ ${t('settings.statusNotConfigured')}`;
      apiKeyStatus.style.color = data.configured ? 'var(--color-seen)' : 'var(--color-inferred)';
    } catch (err) {
      apiKeyStatus.textContent = `${err.message}`;
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      provider: providerSelect.value,
      model: modelInput.value.trim(),
    };
    if (providerSelect.value === 'custom' || baseUrlInput.value.trim()) {
      payload.base_url = baseUrlInput.value.trim();
    }
    const key = apiKeyInput.value.trim();
    if (key) {
      payload.api_key = key;
    }

    try {
      await api.updateAiSettings(payload);
      showToast(t('settings.saveSuccess'));
      apiKeyInput.value = '';
      loadSettings();
    } catch (err) {
      showToast(`${err.message}`);
    }
  });

  btnTestAi.addEventListener('click', async () => {
    btnTestAi.disabled = true;
    btnTestAi.textContent = `${t('app.loading')}`;

    const payload = {
      provider: providerSelect.value,
      model: modelInput.value.trim(),
    };
    if (baseUrlInput.value.trim()) payload.base_url = baseUrlInput.value.trim();
    const key = apiKeyInput.value.trim();
    if (key) payload.api_key = key;

    try {
      const res = await api.testAiSettings(payload);
      if (res.ok) {
        showToast(t('settings.testSuccess'));
      } else {
        showToast(t('settings.testFail', { err: res.message || 'Error' }));
      }
    } catch (err) {
      showToast(t('settings.testFail', { err: err.message }));
    } finally {
      btnTestAi.disabled = false;
      btnTestAi.textContent = t('settings.btnTest');
    }
  });

  loadSettings();

  return {
    element: el,
  };
}
