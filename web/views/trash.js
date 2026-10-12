/**
 * Trash View (/trash)
 *
 * 垃圾桶：列出所有「移至垃圾桶」（status='void'）的紀錄。
 * - 還原：回到移入前的狀態，重新出現在首頁與搜尋結果
 * - 永久刪除：資料庫紀錄、關聯資料、事件歷史與照片檔案全部清除
 *   （先前建立的備份快照不會被自動清除，操作訊息有說明）
 *
 * 這裡只操作 void 的紀錄；一般紀錄要先在詳情頁「移至垃圾桶」。
 */

import { api, getItemThumbnailUrl } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';
import { showToast } from '../core/router.js';
import { t } from '../i18n/index.js';

export async function createTrashView(params, router) {
  const el = document.createElement('div');
  el.className = 'trash-view';

  el.innerHTML = `
    <header class="app-header">
      <div style="display: flex; align-items: center; gap: 8px;">
        <a href="/" class="icon-btn" title="${t('trash.backHome')}" data-link>←</a>
        <span style="font-weight: 700; font-size: 1.05rem;">🗑 ${t('trash.title')}</span>
      </div>
      <div class="header-actions">
        <span style="font-size: 0.8rem; color: var(--text-muted);" id="trash-count"></span>
      </div>
    </header>

    <main class="container">
      <div class="trash-note">${t('trash.pageNote')}</div>
      <div class="trash-list" id="trash-list"></div>

      <div class="empty-state" id="trash-empty" style="display: none;">
        <div class="empty-icon">🗑</div>
        <div class="empty-title">${t('trash.emptyTitle')}</div>
        <div class="empty-subtitle">${t('trash.emptySubtitle')}</div>
        <a href="/" class="btn-primary" style="display: inline-flex; width: auto;" data-link>${t('trash.backHome')}</a>
      </div>
    </main>
  `;

  const listContainer = el.querySelector('#trash-list');
  const emptyState = el.querySelector('#trash-empty');
  const countLabel = el.querySelector('#trash-count');
  let busy = false;

  function setBusy(on) {
    busy = on;
    listContainer.querySelectorAll('button').forEach(btn => {
      btn.disabled = on;
    });
  }

  async function loadTrash() {
    listContainer.innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--text-muted);">
        ${t('app.loading')}
      </div>
    `;
    try {
      const items = await api.listTrashItems();
      renderItems(items || []);
    } catch (err) {
      console.error('Failed to load trash:', err);
      countLabel.textContent = '';
      emptyState.style.display = 'none';
      listContainer.innerHTML = `
        <div style="padding: 20px; text-align: center; color: var(--color-danger);">
          ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  function displayName(item) {
    return item.name || item.model || t('home.cardUntitled');
  }

  function renderItems(items) {
    listContainer.innerHTML = '';
    emptyState.style.display = items.length === 0 ? 'block' : 'none';
    countLabel.textContent = items.length > 0
      ? t('trash.itemCount', { n: items.length })
      : '';

    items.forEach(item => {
      const row = document.createElement('div');
      row.className = 'trash-item';
      row.setAttribute('data-id', item.id);

      const name = displayName(item);
      const thumbUrl = item.thumbnail ? getItemThumbnailUrl(item) : null;
      const thumbHtml = thumbUrl
        ? `<img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(name)}" loading="lazy" />`
        : '<div class="trash-thumb-placeholder">📷</div>';

      const metaParts = [item.brand, item.model && item.model !== item.name ? item.model : '']
        .filter(Boolean);
      const metaText = metaParts.length > 0
        ? escapeHtml(metaParts.join(' · '))
        : t('home.cardLifeRecord');
      const photoText = item.photo_count > 0
        ? ` · ${t('home.photoCount', { n: item.photo_count })}`
        : '';

      row.innerHTML = `
        <div class="trash-item-thumb">${thumbHtml}</div>
        <div class="trash-item-info">
          <a class="trash-item-name" href="/i/${escapeHtml(item.id)}" data-link>${escapeHtml(name)}</a>
          <div class="trash-item-meta">${metaText}${photoText}</div>
          <div class="trash-item-id">${escapeHtml(item.id)}</div>
        </div>
        <div class="trash-item-actions">
          <button type="button" class="btn-mini" data-action="restore">${t('trash.restore')}</button>
          <button type="button" class="btn-mini btn-mini-danger" data-action="purge">${t('trash.purge')}</button>
        </div>
      `;

      row.querySelector('[data-action="restore"]').addEventListener('click', () => {
        restoreItem(item);
      });
      row.querySelector('[data-action="purge"]').addEventListener('click', () => {
        purgeItem(item);
      });

      // SR-1／F6：載不出來的縮圖換佔位圖（事件監聽，不用 inline handler）。
      const img = row.querySelector('.trash-item-thumb img');
      if (img) {
        img.addEventListener('error', () => {
          img.parentElement.innerHTML = '<div class="trash-thumb-placeholder">📷</div>';
        });
      }

      listContainer.appendChild(row);
    });
  }

  async function restoreItem(item) {
    if (busy) return;
    setBusy(true);
    try {
      await api.restoreItem(item.id);
      showToast(t('trash.restoreDone', { name: displayName(item) }));
      await loadTrash();
    } catch (err) {
      console.error('Restore failed:', err);
      showToast(`${t('trash.restoreError')}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function purgeItem(item) {
    if (busy) return;
    // 不可逆操作：明確二次確認；訊息說明備份快照中的副本不會被自動清除。
    const confirmed = window.confirm(
      t('trash.purgeConfirm', { name: displayName(item) })
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      await api.purgeItem(item.id);
      showToast(t('trash.purgeDone', { name: displayName(item) }));
      await loadTrash();
    } catch (err) {
      // 伺服器訊息會說明真實狀態（含刪不掉的檔案路徑），原文照顯示。
      console.error('Permanent delete failed:', err);
      showToast(`${t('trash.purgeError')}: ${err.message}`, 8000);
      // 失敗可能是「資料庫已刪、檔案還在」——重新載入讓清單對齊真實狀態。
      await loadTrash();
    } finally {
      setBusy(false);
    }
  }

  loadTrash();

  return {
    element: el,
  };
}
