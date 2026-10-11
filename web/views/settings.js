/**
 * Settings View (/settings)
 *
 * System settings:
 * 1. Language switcher (Traditional Chinese / English)
 * 2. AI Vision provider & API Key configuration
 * 3. Mobile phone pairing (QR Code)
 * 4. Mobile LAN access guide
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
            <label class="ai-field-label">${t('settings.apiBaseUrlLabel')}</label>
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

      <!-- 3. 手機配對 -->
      <div class="detail-card" style="margin-top: 16px;">
        <h2 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 6px;">📱 ${t('settings.phonePairingSection')}</h2>
        <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 20px; line-height: 1.5;">
          ${t('settings.phonePairingDescription')}
        </p>

        <div id="pairing-section">
          <!-- 配對中：顯示 QR Code -->
          <div id="pairing-qr-container" style="display: none; text-align: center; padding: 20px;">
            <h3 style="font-size: 1rem; font-weight: 700; margin-bottom: 12px;">${t('settings.pairingScanTitle')}</h3>
            <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 16px;">${t('settings.pairingScanSubtitle')}</p>
            <div id="pairing-qr-code" style="display: inline-block; padding: 16px; background: white; border: 1px solid var(--border-default); border-radius: var(--radius-md);"></div>
            <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 12px; font-family: var(--font-mono);" id="pairing-code-display"></p>
            <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;" id="pairing-expires"></p>
            <button type="button" class="btn-secondary" id="btn-cancel-pairing" style="margin-top: 16px;">${t('settings.pairingCancel')}</button>
          </div>

          <!-- 未配對：顯示開始配對按鈕 -->
          <div id="pairing-start-container" style="text-align: center; padding: 20px;">
            <button type="button" class="btn-primary" id="btn-start-pairing">${t('settings.pairingStartBtn')}</button>
            <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 8px;">${t('settings.pairingStartNote')}</p>
          </div>
        </div>

        <!-- 已配對裝置列表 -->
        <div id="paired-devices-section" style="margin-top: 20px; display: none;">
          <h3 style="font-size: 1rem; font-weight: 700; margin-bottom: 12px;">${t('settings.pairedDevicesTitle')}</h3>
          <div id="paired-devices-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
          <p id="paired-devices-empty" style="font-size: 0.85rem; color: var(--text-muted); display: none;">${t('settings.pairedDevicesEmpty')}</p>
        </div>
      </div>

      <!-- 4. 手機連線提示 -->
      <div class="detail-card" style="margin-top: 16px;">
        <h3 style="font-size: 1rem; font-weight: 700; margin-bottom: 6px;">${t('settings.lanAccessTitle')}</h3>
        <p style="font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;">
          ${t('settings.lanAccessDescription')}
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

  // Pairing elements
  const btnStartPairing = el.querySelector('#btn-start-pairing');
  const btnCancelPairing = el.querySelector('#btn-cancel-pairing');
  const pairingQrContainer = el.querySelector('#pairing-qr-container');
  const pairingStartContainer = el.querySelector('#pairing-start-container');
  const pairingQrCode = el.querySelector('#pairing-qr-code');
  const pairingCodeDisplay = el.querySelector('#pairing-code-display');
  const pairingExpires = el.querySelector('#pairing-expires');
  const pairedDevicesSection = el.querySelector('#paired-devices-section');
  const pairedDevicesList = el.querySelector('#paired-devices-list');
  const pairedDevicesEmpty = el.querySelector('#paired-devices-empty');

  let pairingPollInterval = null;

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

  // Pairing functions
  async function loadPairedDevices() {
    try {
      const devices = await api.listPairedDevices();
      pairedDevicesList.innerHTML = '';
      if (devices.length === 0) {
        pairedDevicesEmpty.style.display = 'block';
        pairedDevicesSection.style.display = 'block';
        return;
      }
      pairedDevicesEmpty.style.display = 'none';
      pairedDevicesSection.style.display = 'block';
      for (const device of devices) {
        const deviceEl = document.createElement('div');
        deviceEl.style.cssText = 'display: flex; align-items: center; justify-content: space-between; padding: 12px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-md);';
        const isRevoked = device.revoked_at !== null;
        deviceEl.innerHTML = `
          <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 1.5rem;">${isRevoked ? '🔒' : '📱'}</span>
            <div>
              <div style="font-weight: 600; color: var(--text-primary);">${escapeHtml(device.name || `裝置 ${device.id.slice(-6)}`)}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">${device.id}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted);">
                ${t('settings.pairedDeviceCreated', { date: formatDate(device.created_at) })}
                ${device.last_seen_at ? ` · ${t('settings.pairedDeviceLastSeen', { date: formatDate(device.last_seen_at) })}` : ''}
                ${isRevoked ? ` · ${t('settings.pairedDeviceRevoked')}` : ''}
              </div>
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            ${!isRevoked ? `<button type="button" class="btn-mini-danger" data-device-id="${device.id}">${t('settings.pairedDeviceRevoke')}</button>` : ''}
          </div>
        `;
        pairedDevicesList.appendChild(deviceEl);
      }
      // Bind revoke buttons
      pairedDevicesList.querySelectorAll('.btn-mini-danger').forEach(btn => {
        btn.addEventListener('click', async () => {
          const deviceId = btn.getAttribute('data-device-id');
          if (confirm(t('settings.pairedDeviceRevokeConfirm', { name: deviceId }))) {
            try {
              await api.revokePairedDevice(deviceId);
              showToast(t('settings.pairedDeviceRevokedSuccess'));
              loadPairedDevices();
            } catch (err) {
              showToast(`${err.message}`);
            }
          }
        });
      });
    } catch (err) {
      console.error('Failed to load paired devices:', err);
    }
  }

  function formatDate(isoString) {
    try {
      const date = new Date(isoString);
      return date.toLocaleString(getLocale() === 'zh-TW' ? 'zh-TW' : 'en-US', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
      });
    } catch {
      return isoString;
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function generateQRCode(text) {
    // Simple QR code generation using a small library or API
    // For now, use a simple ASCII representation or Google Charts API
    // In production, you'd want a proper QR code library
    const size = 200;
    return `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&data=${encodeURIComponent(text)}`;
  }

  async function startPairing() {
    btnStartPairing.disabled = true;
    btnStartPairing.textContent = t('app.loading');

    try {
      const result = await api.startPairing();
      // Show QR code
      pairingQrCode.innerHTML = `<img src="${generateQRCode(result.qr_data)}" alt="QR Code" style="width: 200px; height: 200px;">`;
      pairingCodeDisplay.textContent = `${t('settings.pairingCodeLabel')}: ${result.pairing_code}`;
      pairingExpires.textContent = `${t('settings.pairingExpiresLabel')}: ${formatDate(result.expires_at)}`;
      pairingStartContainer.style.display = 'none';
      pairingQrContainer.style.display = 'block';

      // Poll for pairing completion
      pairingPollInterval = setInterval(async () => {
        try {
          // Check if pairing is complete by trying to list devices
          // The pairing is complete when the device appears in the list
          const devices = await api.listPairedDevices();
          // Look for a device created recently (within last 30 seconds)
          const now = Date.now();
          const newDevice = devices.find(d => {
            const created = new Date(d.created_at).getTime();
            return (now - created) < 30000 && !d.revoked_at;
          });
          if (newDevice) {
            clearInterval(pairingPollInterval);
            pairingPollInterval = null;
            pairingQrContainer.style.display = 'none';
            pairingStartContainer.style.display = 'block';
            btnStartPairing.disabled = false;
            btnStartPairing.textContent = t('settings.pairingStartBtn');
            showToast(t('settings.pairingSuccess'));
            loadPairedDevices();
          }
        } catch (err) {
          // Ignore polling errors
        }
      }, 2000);

    } catch (err) {
      showToast(`${err.message}`);
      btnStartPairing.disabled = false;
      btnStartPairing.textContent = t('settings.pairingStartBtn');
    }
  }

  btnStartPairing.addEventListener('click', startPairing);

  btnCancelPairing.addEventListener('click', () => {
    if (pairingPollInterval) {
      clearInterval(pairingPollInterval);
      pairingPollInterval = null;
    }
    pairingQrContainer.style.display = 'none';
    pairingStartContainer.style.display = 'block';
    btnStartPairing.disabled = false;
    btnStartPairing.textContent = t('settings.pairingStartBtn');
  });

  loadSettings();
  loadPairedDevices();

  // Cleanup on view destroy
  return {
    element: el,
    destroy() {
      if (pairingPollInterval) {
        clearInterval(pairingPollInterval);
      }
    },
  };
}
