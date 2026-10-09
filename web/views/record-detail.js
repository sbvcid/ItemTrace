/**
 * Record Detail View (/i/:id)
 *
 * Detailed view of a saved record:
 * - High resolution photos
 * - Structured specs and serials
 * - Fast copy action for serial numbers
 */

import { api, getPhotoUrl } from '../core/api.js';
import { showToast } from '../core/router.js';
import { t } from '../i18n/index.js';

export async function createRecordDetailView(params, router) {
  const el = document.createElement('div');
  el.className = 'record-detail-view';

  const itemId = params.id;

  el.innerHTML = `
    <header class="app-header">
      <div style="display: flex; align-items: center; gap: 8px;">
        <a href="/" class="icon-btn" title="${t('detail.backHome')}" data-link>←</a>
        <span style="font-weight: 700; font-size: 1.05rem;" id="header-id">${itemId}</span>
      </div>
      <div class="header-actions">
        <span class="badge-seen" id="status-badge">${t('detail.statusActive')}</span>
      </div>
    </header>

    <main class="container" id="detail-content">
      <div style="text-align: center; padding: 48px 20px; color: var(--text-muted);">
        ${t('detail.loading')}
      </div>
    </main>
  `;

  const detailContent = el.querySelector('#detail-content');
  const statusBadge = el.querySelector('#status-badge');

  async function loadDetail() {
    try {
      const data = await api.getItem(itemId);
      renderDetail(data);
    } catch (err) {
      console.error('Failed to load item detail:', err);
      detailContent.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">⚠️</div>
          <div class="empty-title">${t('detail.notFoundTitle')}</div>
          <div class="empty-subtitle">${err.message}</div>
          <a href="/" class="btn-primary" style="display: inline-flex; width: auto;" data-link>${t('detail.backHome')}</a>
        </div>
      `;
    }
  }

  function renderDetail(data) {
    const item = data.item;
    const photos = data.photos || [];
    const identifiers = data.identifiers || [];

    statusBadge.textContent = item.status === 'active'
      ? t('detail.statusActive')
      : item.status === 'archived'
        ? t('detail.statusArchived')
        : t('detail.statusDeleted');

    // Photos carousel
    let photosHtml = '';
    if (photos.length > 0) {
      const primaryPhoto = photos[0];
      const primaryPhotoUrl = getPhotoUrl(primaryPhoto.filename);

      const thumbsHtml = photos.map((p, idx) => {
        const photoUrl = getPhotoUrl(p.filename);
        return `
          <div class="detail-thumb-item ${idx === 0 ? 'active' : ''}" data-url="${photoUrl}">
            <img src="${photoUrl}" alt="${t('detail.photosTitle', { n: idx + 1 })}" loading="lazy" />
          </div>
        `;
      }).join('');

      photosHtml = `
        <div class="detail-photos-carousel">
          <img src="${primaryPhotoUrl}" alt="${item.name || 'Photo'}" class="detail-main-img" id="main-photo" />
        </div>
        ${photos.length > 1 ? `<div class="detail-thumbs-bar" id="thumbs-bar">${thumbsHtml}</div>` : ''}
      `;
    } else {
      photosHtml = `
        <div class="detail-photos-carousel" style="background: var(--bg-subtle); color: var(--text-muted); min-height: 220px;">
          ${t('detail.noPhotos')}
        </div>
      `;
    }

    // Specifications & Identifiers
    const title = item.name || item.model || t('home.cardUntitled');
    const serialItems = identifiers.filter(i => i.kind === 'serial');

    const serialsHtml = serialItems.length > 0
      ? serialItems.map(i => `
          <div class="spec-item">
            <span class="spec-label">${t('detail.serialBadge')}</span>
            <div class="spec-val mono">
              <span>${i.value}</span>
              <button type="button" class="btn-copy" data-copy="${i.value}" title="${t('detail.copySerial')}">📋 ${t('detail.copySerial')}</button>
            </div>
          </div>
        `).join('')
      : (item.model ? `
          <div class="spec-item">
            <span class="spec-label">${t('detail.fieldModel')}</span>
            <div class="spec-val mono">${item.model}</div>
          </div>
        ` : '');

    detailContent.innerHTML = `
      ${photosHtml}

      <div class="detail-card" style="margin-top: 18px;">
        <div class="detail-title">${title}</div>

        <div class="detail-specs-grid">
          ${item.brand ? `
            <div class="spec-item">
              <span class="spec-label">${t('detail.fieldBrand')}</span>
              <div class="spec-val">${item.brand}</div>
            </div>
          ` : ''}
          ${item.model ? `
            <div class="spec-item">
              <span class="spec-label">${t('detail.fieldModel')}</span>
              <div class="spec-val">${item.model}</div>
            </div>
          ` : ''}
          ${item.category ? `
            <div class="spec-item">
              <span class="spec-label">${t('detail.fieldCategory')}</span>
              <div class="spec-val">${item.category}</div>
            </div>
          ` : ''}
          ${serialsHtml}
          ${item.condition ? `
            <div class="spec-item" style="grid-column: 1 / -1;">
              <span class="spec-label">${t('detail.fieldCondition')}</span>
              <div class="spec-val" style="font-weight: normal; font-size: 0.95rem; line-height: 1.5;">${item.condition}</div>
            </div>
          ` : ''}
          ${item.notes ? `
            <div class="spec-item" style="grid-column: 1 / -1;">
              <span class="spec-label">${t('detail.fieldCondition')}</span>
              <div class="spec-val" style="font-weight: normal; font-size: 0.95rem; line-height: 1.5;">${item.notes}</div>
            </div>
          ` : ''}
        </div>

        <div style="font-size: 0.82rem; color: var(--text-muted); display: flex; justify-content: space-between; align-items: center; padding-top: 8px;">
          <span>${t('detail.fieldCreated')}：${item.created_at ? item.created_at.replace('T', ' ').slice(0, 19) : '剛剛'}</span>
          <a href="/" class="btn-secondary" style="width: auto; padding: 6px 14px;" data-link>${t('detail.backHome')}</a>
        </div>
      </div>
    `;

    // Hook thumbnail click
    const mainPhoto = detailContent.querySelector('#main-photo');
    const thumbsBar = detailContent.querySelector('#thumbs-bar');
    if (thumbsBar && mainPhoto) {
      thumbsBar.addEventListener('click', (e) => {
        const thumb = e.target.closest('.detail-thumb-item');
        if (thumb) {
          const url = thumb.getAttribute('data-url');
          mainPhoto.src = url;
          thumbsBar.querySelectorAll('.detail-thumb-item').forEach(t => t.classList.remove('active'));
          thumb.classList.add('active');
        }
      });
    }

    // Hook copy buttons
    detailContent.querySelectorAll('.btn-copy').forEach(btn => {
      btn.addEventListener('click', async () => {
        const text = btn.getAttribute('data-copy');
        try {
          await navigator.clipboard.writeText(text);
          showToast(t('detail.serialCopied', { serial: text }));
        } catch (_) {
          showToast(t('detail.serialCopied', { serial: text }));
        }
      });
    });
  }

  loadDetail();

  return {
    element: el,
  };
}
