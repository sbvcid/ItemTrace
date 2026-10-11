/**
 * ItemTrace V3 Main Application Entrypoint
 *
 * Boots router, initializes i18n, and binds views.
 *
 * 啟動時先問 /api/session 這條連線的身分：
 * - admin（電腦本機）→ 直接進 App
 * - device（已配對手機）→ 直接進 App（api.js 自動附加裝置權杖）
 * - unpaired（未配對的區網裝置）→ 顯示配對引導頁，不呼叫任何資料 API
 * /pair 路由例外：配對頁本身要在未配對狀態下運作。
 */

import { router } from './core/router.js';
import { initI18n, onLocaleChange, t } from './i18n/index.js';
import { api } from './core/api.js';
import { createHomeView } from './views/home.js';
import { createCaptureView } from './views/capture.js';
import { createRecordDetailView } from './views/record-detail.js';
import { createSettingsView } from './views/settings.js';
import { createTrashView } from './views/trash.js';
import { createPairView } from './views/pair.js';

function renderUnpairedNotice(container) {
  container.innerHTML = `
    <header class="app-header">
      <div style="display: flex; align-items: center; gap: 10px;">
        <span class="brand-icon">IT</span>
        <span style="font-weight: 700; font-size: 1.05rem;">${t('app.title')}</span>
      </div>
    </header>
    <main class="container">
      <div class="empty-state" style="margin-top: 24px;">
        <div class="empty-icon">🔒</div>
        <div class="empty-title">${t('unpaired.title')}</div>
        <div class="empty-subtitle">${t('unpaired.body')}</div>
        <button class="btn-primary" id="btn-unpaired-retry">${t('unpaired.retry')}</button>
      </div>
    </main>
  `;
  const retry = container.querySelector('#btn-unpaired-retry');
  if (retry) {
    retry.addEventListener('click', () => window.location.reload());
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  // Initialize locale from storage or browser
  initI18n();

  const container = document.getElementById('app');

  router
    .add('/', createHomeView)
    .add('/capture', createCaptureView)
    .add('/i/:id', createRecordDetailView)
    .add('/items/:id', createRecordDetailView) // Backward compatibility link
    .add('/trash', createTrashView)
    .add('/settings', createSettingsView)
    .add('/pair', createPairView);

  // Automatically re-render current view on language change
  onLocaleChange(() => {
    router.resolve();
  });

  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  const isPairPath = path === '/pair';

  if (!isPairPath) {
    let role = null;
    try {
      const session = await api.getSession();
      role = session && session.role ? session.role : 'unpaired';
    } catch (err) {
      // 401＝裝置權杖失效或已撤銷（api.js 已清除本機權杖）→ 顯示配對引導；
      // 其他錯誤（伺服器暫時不可用）→ 仍進 App，讓各頁顯示自己的錯誤。
      role = err && err.status === 401 ? 'unpaired' : null;
    }
    if (role === 'unpaired') {
      renderUnpairedNotice(container);
      return;
    }
  }

  router.init(container);
});
