/**
 * Folder Detail View (/folders/:id)
 *
 * Displays items within a specific folder or the unclassified collection.
 * - Item listing with search
 * - Quick actions (move to trash, move to another folder)
 * - Back to folders list
 */

import { api, getItemThumbnailUrl } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';
import { showToast } from '../core/router.js';
import { t } from '../i18n/index.js';

export async function createFolderDetailView(params, router) {
  const el = document.createElement('div');
  el.className = 'folder-detail-view';

  const folderId = params.id;

  el.innerHTML = `
    <header class="app-header">
      <div class="header-breadcrumb">
        <a href="/folders" class="icon-btn" title="${t('folders.back')}" data-link>←</a>
        <span class="header-id" id="folder-name">${t('app.loading')}</span>
      </div>
      <div class="header-actions">
      </div>
    </header>

    <div class="container">
      <!-- 搜尋該資料夾內的紀錄 -->
      <section class="search-wrapper">
        <span class="search-icon">🔍</span>
        <input
          type="search"
          class="search-input"
          id="folder-search-input"
          placeholder="${t('folders.searchPlaceholder')}"
          autocomplete="off"
        />
        <button type="button" class="search-clear" id="folder-search-clear" aria-label="Clear search">✕</button>
      </section>

      <!-- Items list -->
      <section class="records-section">
        <div class="records-header">
          <div class="records-title" id="records-heading">${t('folders.itemsTitle')}</div>
          <div class="records-count" id="records-count">${t('app.loading')}</div>
        </div>

        <div class="card-grid" id="card-grid">
          <!-- Dynamically populated -->
        </div>

        <div class="empty-state" id="empty-state" style="display: none;">
          <div class="empty-icon">📁</div>
          <div class="empty-title">${t('folders.emptyItemsTitle')}</div>
          <div class="empty-subtitle">${t('folders.emptyItemsSubtitle')}</div>
          <a href="/" class="btn-primary" style="display: inline-flex; width: auto;" data-link>${t('folders.backToHome')}</a>
        </div>

        <div class="empty-state" id="no-search-results" style="display: none;">
          <div class="empty-icon">🔍</div>
          <div class="empty-title">${t('home.searchEmptyTitle')}</div>
          <div class="empty-subtitle">${t('home.searchEmptySubtitle')}</div>
        </div>
      </section>
    </div>
  `;

  const folderName = el.querySelector('#folder-name');
  const searchInput = el.querySelector('#folder-search-input');
  const searchClear = el.querySelector('#folder-search-clear');
  const cardGrid = el.querySelector('#card-grid');
  const recordsCount = el.querySelector('#records-count');
  const emptyState = el.querySelector('#empty-state');
  const noSearchResults = el.querySelector('#no-search-results');
  const recordsHeading = el.querySelector('#records-heading');

  let debounceTimer = null;
  let currentFolderName = '';

  async function loadFolderName() {
    if (folderId === 'unclassified') {
      currentFolderName = t('folders.unclassified');
      folderName.textContent = currentFolderName;
    } else {
      try {
        const data = await api.listFolders('active');
        const folder = (data.folders || []).find(f => f.id === folderId);
        if (folder) {
          currentFolderName = folder.name;
          folderName.textContent = currentFolderName;
        } else {
          folderName.textContent = t('folders.notFound');
        }
      } catch (err) {
        folderName.textContent = folderId;
      }
    }
  }

  async function loadItems(query = '') {
    try {
      let items = [];
      if (folderId === 'unclassified') {
        // Unclassified: items without a folder
        const result = await api.listItems(query);
        items = (result || []).filter(item => !item.folder_id);
      } else {
        // Regular folder: get items in this folder
        const result = await api.getFolderItems(folderId, 200, 0);
        items = result.items || [];
      }
      renderItems(items, query);
    } catch (err) {
      console.error('Failed to load items:', err);
      cardGrid.innerHTML = `
        <div style="grid-column: 1/-1; padding: 20px; text-align: center; color: var(--color-danger);">
          ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  function renderItems(items, query = '') {
    cardGrid.innerHTML = '';

    if (!items || items.length === 0) {
      recordsCount.textContent = t('folders.itemCount', { n: 0 });
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
    recordsCount.textContent = t('folders.itemCount', { n: items.length });

    items.forEach((item, index) => {
      const featured = index === 0;
      cardGrid.appendChild(createRecordCard(item, { featured }));
    });
  }

  function createRecordCard(item, { featured = false } = {}) {
    const card = document.createElement('a');
    card.className = 'record-card';
    if (featured) card.classList.add('record-card-featured');
    card.href = `/i/${item.id}`;
    card.setAttribute('data-link', '');

    const rawTitle = item.name || item.model || t('home.cardUntitled');
    const title = escapeHtml(rawTitle);

    const thumbUrl = item.thumbnail ? getItemThumbnailUrl(item) : null;
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

      const badges = [];
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
    } else {
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
    }

    // Thumb fallback
    const img = card.querySelector('.record-thumb');
    if (img) {
      img.addEventListener('error', () => {
        img.parentElement.innerHTML = '<div class="record-thumb-placeholder">📷</div>';
      });
    }

    return card;
  }

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

  async function init() {
    await loadFolderName();
    await loadItems('');
  }

  init();

  return {
    element: el,
    destroy() {
      clearTimeout(debounceTimer);
    },
  };
}
