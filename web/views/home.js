/**
 * Home View (/)
 *
 * Focuses purely on two core actions:
 * 1. 📷 拍下來 (Capture)
 * 2. 🔍 找回來 (Retrieve / Search)
 */

import { api, getPhotoUrl } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';
import { t } from '../i18n/index.js';

export async function createHomeView(params, router) {
  const el = document.createElement('div');
  el.className = 'home-view';

  // 保存成功後由 Capture 帶來的「剛剛存入」參照。讀完即從 URL 移除，
  // 重新整理或返回首頁時不再高亮（短暫、克制的視覺提示）。
  const freshId = new URLSearchParams(window.location.search).get('fresh');
  if (freshId) {
    window.history.replaceState(null, '', '/');
  }

  el.innerHTML = `
    <header class="app-header">
      <a href="/" class="brand" data-link>
        <span class="brand-icon">IT</span>
        <span>ItemTrace</span>
      </a>
      <div class="header-actions">
        <a href="/settings" class="icon-btn" title="${t('app.settings')}" data-link>⚙</a>
      </div>
    </header>

    <main class="container">
      <!-- 📷 拍下來 (Core Action 1: Shutter Hero) -->
      <section class="hero-capture">
        <div class="hero-capture-title">${t('home.heroTitle')}</div>
        <div class="hero-capture-subtitle">${t('home.heroSubtitle')}</div>
        <a href="/capture" class="btn-shutter-hero" data-link>
          <span>📷</span>
          <span>${t('home.heroBtn')}</span>
        </a>
      </section>

      <!-- 🔍 找回來 (Core Action 2: Omni-Search) -->
      <section class="search-wrapper">
        <span class="search-icon">🔍</span>
        <input
          type="search"
          class="search-input"
          id="search-input"
          placeholder="${t('home.searchPlaceholder')}"
          autocomplete="off"
        />
        <button type="button" class="search-clear" id="search-clear" aria-label="Clear search">✕</button>
      </section>

      <!-- 紀錄列表 -->
      <section class="records-section">
        <div class="records-header">
          <div class="records-title" id="records-heading">${t('detail.headerTitle')}</div>
          <div class="records-count" id="records-count">${t('app.loading')}</div>
        </div>

        <div class="card-grid" id="card-grid">
          <!-- Dynamically populated -->
        </div>

        <div class="empty-state" id="empty-state" style="display: none;">
          <div class="empty-icon">📷</div>
          <div class="empty-title">${t('home.emptyTitle')}</div>
          <div class="empty-subtitle">${t('home.emptySubtitle')}</div>
          <a href="/capture" class="btn-shutter-hero" data-link>
            <span>📷</span>
            <span>${t('home.emptyAction')}</span>
          </a>
        </div>

        <div class="empty-state" id="no-search-results" style="display: none;">
          <div class="empty-icon">🔍</div>
          <div class="empty-title">${t('home.searchEmptyTitle')}</div>
          <div class="empty-subtitle">${t('home.searchEmptySubtitle')}</div>
        </div>
      </section>
    </main>

    <!-- Mobile Floating Action Button -->
    <div class="mobile-fab-container">
      <a href="/capture" class="btn-shutter-fab" title="${t('home.heroBtn')}" data-link>📷</a>
    </div>
  `;

  const searchInput = el.querySelector('#search-input');
  const searchClear = el.querySelector('#search-clear');
  const cardGrid = el.querySelector('#card-grid');
  const recordsCount = el.querySelector('#records-count');
  const emptyState = el.querySelector('#empty-state');
  const noSearchResults = el.querySelector('#no-search-results');
  const recordsHeading = el.querySelector('#records-heading');

  let debounceTimer = null;

  async function loadItems(query = '') {
    try {
      const items = await api.listItems(query);
      renderItems(items, query);
    } catch (err) {
      console.error('Failed to load items:', err);
      cardGrid.innerHTML = `
        <div style="grid-column: 1/-1; padding: 20px; text-align: center; color: var(--color-danger);">
          ${err.message}
        </div>
      `;
    }
  }

  function renderItems(items, query = '') {
    cardGrid.innerHTML = '';

    if (!items || items.length === 0) {
      recordsCount.textContent = t('home.photoCount', { n: 0 });
      if (query.trim()) {
        emptyState.style.display = 'none';
        noSearchResults.style.display = 'block';
      } else {
        emptyState.style.display = 'block';
        noSearchResults.style.display = 'none';
      }
      return;
    }

    emptyState.style.display = 'none';
    noSearchResults.style.display = 'none';
    recordsCount.textContent = t('home.photoCount', { n: items.length });

    const isSearch = Boolean(query.trim());
    items.forEach((item, index) => {
      // 首頁預設檢視把最新一筆放大呈現；搜尋結果維持一致的緊湊排列。
      const featured = !isSearch && index === 0;
      const fresh = !isSearch && Boolean(freshId) && item.id === freshId;
      cardGrid.appendChild(createRecordCard(item, { featured, fresh }));
    });
  }

  function attachThumbFallback(card) {
    // SR-1／F6：CSP（script-src 'self'）會擋 inline onerror，改用事件監聽；
    // 非圖片內容（例如誤入的 HTML 檔）載不出來時顯示佔位圖。
    const img = card.querySelector('.record-thumb');
    if (!img) return;
    img.addEventListener('error', () => {
      img.parentElement.innerHTML =
        '<div class="record-thumb-placeholder">📷</div>';
    });
  }

  function createRecordCard(item, { featured = false, fresh = false } = {}) {
    const card = document.createElement('a');
    card.className = 'record-card';
    if (featured) card.classList.add('record-card-featured');
    if (fresh) card.classList.add('record-card-fresh');
    card.href = `/i/${item.id}`;
    card.setAttribute('data-link', '');

    // SR-1／F6：紀錄欄位（含 AI 產出）一律先 escape 再進版型。
    const rawTitle = item.name || item.model || t('home.cardUntitled');
    const title = escapeHtml(rawTitle);

    // Standardized thumbnail URL resolver
    const thumbUrl = item.thumbnail ? getPhotoUrl(item.thumbnail) : null;
    const thumbHtml = thumbUrl
      ? `<img src="${escapeHtml(thumbUrl)}" alt="${title}" class="record-thumb" loading="lazy" />`
      : `<div class="record-thumb-placeholder">📷</div>`;

    const photoBadge = !featured && item.photo_count > 1
      ? `<div class="record-badge-count">${t('home.photoCount', { n: item.photo_count })}</div>`
      : '';

    if (featured) {
      const rawMetaParts = [
        item.brand,
        item.model && item.model !== rawTitle ? item.model : '',
        item.category,
      ].filter(Boolean);
      const rawMeta = rawMetaParts.join(' · ') || item.condition || '';
      const metaText = rawMeta ? escapeHtml(rawMeta) : t('home.cardLifeRecord');

      // 「最新」與「剛剛存入」用文字標籤傳達，不是只靠顏色。
      const badges = [];
      if (fresh) badges.push(`<span class="record-fresh-badge">${t('home.freshBadge')}</span>`);
      badges.push(`<span class="record-latest-badge">${t('home.latestBadge')}</span>`);
      if (item.photo_count > 0) {
        badges.push(`<span class="record-photo-total">${t('home.photoCount', { n: item.photo_count })}</span>`);
      }

      const conditionHtml = item.condition && item.condition !== rawMeta
        ? `<div class="record-condition">${escapeHtml(item.condition)}</div>`
        : '';
      const createdHtml = item.created_at
        ? `<div class="record-created">${t('detail.fieldCreated')} ${escapeHtml(item.created_at.slice(0, 10))}</div>`
        : '';

      card.innerHTML = `
        <div class="record-thumb-container">
          ${thumbHtml}
        </div>
        <div class="record-body">
          <div class="record-badges-row">${badges.join('')}</div>
          <div class="record-name">${title}</div>
          <div class="record-meta">${metaText}</div>
          ${conditionHtml}
          ${createdHtml}
        </div>
      `;
      attachThumbFallback(card);
      return card;
    }

    const rawMetaParts = [item.brand, item.category].filter(Boolean);
    const rawMeta = rawMetaParts.join(' · ') || item.condition || '';
    const metaText = rawMeta ? escapeHtml(rawMeta) : t('home.cardLifeRecord');

    const serialHtml = item.matched_identifier
      ? escapeHtml(item.matched_identifier)
      : (item.model ? t('home.modelPrefix', { model: escapeHtml(item.model) }) : null);
    const badgeHtml = serialHtml
      ? `<div class="record-serial">${serialHtml}</div>`
      : '';

    card.innerHTML = `
      <div class="record-thumb-container">
        ${thumbHtml}
        ${photoBadge}
      </div>
      <div class="record-body">
        <div class="record-name">${title}</div>
        <div class="record-meta">${metaText}</div>
        ${badgeHtml}
      </div>
    `;

    attachThumbFallback(card);
    return card;
  }

  // Debounced search input
  searchInput.addEventListener('input', (e) => {
    const val = e.target.value;
    searchClear.classList.toggle('active', Boolean(val));

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      loadItems(val);
    }, 150);
  });

  searchClear.addEventListener('click', () => {
    searchInput.value = '';
    searchClear.classList.remove('active');
    searchInput.focus();
    loadItems('');
  });

  // Initial load
  loadItems('');

  return {
    element: el,
    destroy() {
      clearTimeout(debounceTimer);
    },
  };
}
