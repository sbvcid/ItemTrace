/**
 * Pairing View (/pair?id=…&code=…)
 *
 * 手機掃描電腦上的 QR Code 後開啟的頁面。由 QR Code 的網址取得工作階段
 * id 與一次性配對碼，POST /api/pairing/claim 完成配對，成功後把裝置權杖
 * 存進本機（後續 API 自動附加授權），並導回首頁。
 *
 * 未配對的裝置只能載入前端殼與配對端點，所以這個頁面在「尚未配對」
 * 的狀態下也可以運作。
 */

import { api, storeDeviceSession } from '../core/api.js';
import { t } from '../i18n/index.js';

function guessDeviceName() {
  const ua = navigator.userAgent || '';
  if (/iPhone/i.test(ua)) return 'iPhone';
  if (/iPad/i.test(ua)) return 'iPad';
  if (/Android/i.test(ua)) return 'Android 手機';
  if (/Macintosh/i.test(ua)) return 'Mac';
  if (/Windows/i.test(ua)) return 'Windows 電腦';
  return '手機';
}

export async function createPairView() {
  const el = document.createElement('div');
  el.className = 'pair-view';

  const params = new URLSearchParams(window.location.search);
  const sessionId = (params.get('id') || '').trim();
  const code = (params.get('code') || '').trim();

  el.innerHTML = `
    <header class="app-header">
      <div style="display: flex; align-items: center; gap: 10px;">
        <span class="brand-icon">IT</span>
        <span style="font-weight: 700; font-size: 1.05rem;">${t('app.title')}</span>
      </div>
    </header>
    <main class="container">
      <div class="detail-card" style="margin-top: 24px; text-align: center; padding: 32px 24px;">
        <div id="pair-status" aria-live="polite">
          <div class="empty-icon" id="pair-icon">⏳</div>
          <div class="empty-title" id="pair-title">${t('pair.connecting')}</div>
          <div class="empty-subtitle" id="pair-detail">${t('pair.connectingDetail')}</div>
        </div>
        <div id="pair-hints" style="display: none; text-align: left; margin-top: 20px; padding: 14px 16px; background: var(--bg-subtle); border: 1px solid var(--border-subtle); border-radius: var(--radius-md);">
          <div style="font-weight: 700; font-size: 0.85rem; margin-bottom: 8px;">${t('pair.hintsTitle')}</div>
          <ul style="font-size: 0.82rem; color: var(--text-secondary); line-height: 1.7; padding-left: 18px;">
            <li>${t('pair.hintSameNetwork')}</li>
            <li>${t('pair.hintRegenerate')}</li>
          </ul>
        </div>
      </div>
    </main>
  `;

  const iconEl = el.querySelector('#pair-icon');
  const titleEl = el.querySelector('#pair-title');
  const detailEl = el.querySelector('#pair-detail');
  const hintsEl = el.querySelector('#pair-hints');

  function showError(message) {
    iconEl.textContent = '⚠️';
    titleEl.textContent = t('pair.errorTitle');
    detailEl.textContent = message || t('pair.errorFallback');
    hintsEl.style.display = 'block';
  }

  function showSuccess(deviceName) {
    iconEl.textContent = '✅';
    titleEl.textContent = t('pair.successTitle');
    detailEl.textContent = t('pair.successSubtitle', { name: deviceName });
    hintsEl.style.display = 'none';
  }

  if (!sessionId || !code) {
    showError(t('pair.missingLink'));
    return { element: el };
  }

  try {
    const result = await api.claimPairing(sessionId, code, guessDeviceName());
    // 伺服器同時下了 HttpOnly cookie（媒體請求用），權杖存本機供
    // fetch 自動附加 Authorization。
    storeDeviceSession({
      token: result.token,
      deviceId: result.device_id,
      deviceName: result.device_name,
    });
    showSuccess(result.device_name);
    // 給使用者看到成功訊息後才進首頁；用 replace 避免「上一頁」回到
    // 已用過的配對連結。
    setTimeout(() => window.location.replace('/'), 1200);
  } catch (err) {
    showError(err && err.message ? err.message : '');
  }

  return { element: el };
}
