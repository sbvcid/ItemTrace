/**
 * Record Detail View (/i/:id)
 *
 * Detailed view of a saved record:
 * - High resolution photos (all original evidence, including later additions)
 * - Structured specs, attributes and serials
 * - Phase 2B: add evidence photos to an existing record and let AI
 *   re-interpret in context. The photo is saved first; analysis failures
 *   never lose it and can be retried. Pending suggestions are reviewed
 *   and applied explicitly — nothing is overwritten silently.
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

    <div class="container detail-toolbar-wrap">
      <div class="detail-toolbar">
        <button type="button" class="btn-secondary detail-tool-btn" id="btn-add-photo">📷 <span>${t('detail.addPhoto')}</span></button>
        <button type="button" class="btn-secondary detail-tool-btn" id="btn-reanalyze">✨ <span>${t('detail.reanalyze')}</span></button>
      </div>
      <div class="detail-analysis-status" id="analysis-status" hidden></div>
      <div id="suggestion-review"></div>
    </div>

    <main class="container" id="detail-content">
      <div style="text-align: center; padding: 48px 20px; color: var(--text-muted);">
        ${t('detail.loading')}
      </div>
    </main>

    <input type="file" id="detail-photo-input" accept="image/*" multiple hidden />
  `;

  const detailContent = el.querySelector('#detail-content');
  const statusBadge = el.querySelector('#status-badge');
  const addPhotoBtn = el.querySelector('#btn-add-photo');
  const reanalyzeBtn = el.querySelector('#btn-reanalyze');
  const photoInput = el.querySelector('#detail-photo-input');
  const analysisStatus = el.querySelector('#analysis-status');
  const suggestionReview = el.querySelector('#suggestion-review');

  let busy = false;
  let currentPending = [];

  function setBusy(on) {
    busy = on;
    addPhotoBtn.disabled = on;
    reanalyzeBtn.disabled = on;
  }

  function setStatus(kind, message) {
    if (!kind) {
      analysisStatus.hidden = true;
      analysisStatus.className = 'detail-analysis-status';
      analysisStatus.innerHTML = '';
      return;
    }
    analysisStatus.hidden = false;
    analysisStatus.className = `detail-analysis-status is-${kind}`;
    const retryHtml = kind === 'failed'
      ? `<button type="button" class="btn-secondary detail-tool-btn" id="btn-retry-analysis">${t('detail.analysisRetry')}</button>`
      : '';
    analysisStatus.innerHTML = `
      <span class="analysis-text">${kind === 'running' ? '✨' : '⚠️'} ${message}</span>
      ${retryHtml}
    `;
    const retryBtn = analysisStatus.querySelector('#btn-retry-analysis');
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        if (!busy) runAnalysis();
      });
    }
  }

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

  function fieldLabel(field) {
    if (field === 'attribute:description') return t('detail.descriptionLabel');
    if (field.startsWith('attribute:')) {
      return t('detail.attributeLabel', { key: field.slice('attribute:'.length) });
    }
    if (field.startsWith('identifier:')) {
      return field.slice('identifier:'.length).toUpperCase();
    }
    const keys = {
      name: 'detail.fieldName',
      brand: 'detail.fieldBrand',
      model: 'detail.fieldModel',
      category: 'detail.fieldCategory',
      condition: 'detail.fieldCondition',
      notes: 'detail.fieldNotes',
    };
    return keys[field] ? t(keys[field]) : field;
  }

  function renderReview(suggestions) {
    currentPending = (suggestions || []).filter(s => s.status === 'pending');
    if (currentPending.length === 0) {
      suggestionReview.innerHTML = '';
      return;
    }
    const rows = currentPending.map(s => {
      const confidence = typeof s.confidence === 'number'
        ? `<span class="suggestion-confidence">${Math.round(s.confidence * 100)}%</span>`
        : '';
      return `
        <div class="suggestion-row" data-id="${s.id}">
          <div class="suggestion-info">
            <div class="suggestion-field">${fieldLabel(s.field)} ${confidence}</div>
            <div class="suggestion-value">${s.value}</div>
          </div>
          <div class="suggestion-actions">
            <button type="button" class="btn-mini" data-action="accept">${t('detail.apply')}</button>
            <button type="button" class="btn-mini btn-mini-muted" data-action="reject">${t('detail.reject')}</button>
          </div>
        </div>
      `;
    }).join('');

    suggestionReview.innerHTML = `
      <div class="detail-card suggestion-review-card">
        <div class="suggestion-title">${t('detail.pendingTitle', { n: currentPending.length })}</div>
        ${rows}
        ${currentPending.length > 1 ? `
          <button type="button" class="btn-primary" id="btn-apply-all" style="margin-top: 10px;">${t('detail.applyAll')}</button>
        ` : ''}
      </div>
    `;

    suggestionReview.querySelectorAll('.suggestion-row').forEach(row => {
      const id = row.getAttribute('data-id');
      row.querySelectorAll('button[data-action]').forEach(btn => {
        btn.addEventListener('click', () => {
          handleSuggestionAction(id, btn.getAttribute('data-action'));
        });
      });
    });

    const applyAll = suggestionReview.querySelector('#btn-apply-all');
    if (applyAll) {
      applyAll.addEventListener('click', () => applyAllSuggestions());
    }
  }

  async function handleSuggestionAction(suggestionId, action) {
    if (busy) return;
    setBusy(true);
    try {
      if (action === 'accept') {
        await api.acceptSuggestion(suggestionId);
      } else {
        await api.rejectSuggestion(suggestionId);
      }
      setStatus(null);
      await loadDetail();
    } catch (err) {
      console.error('Suggestion action failed:', err);
      showToast(`${t('detail.applyError')}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function applyAllSuggestions() {
    if (busy || currentPending.length === 0) return;
    setBusy(true);
    const results = await Promise.allSettled(
      currentPending.map(s => api.acceptSuggestion(s.id))
    );
    const failed = results.filter(r => r.status === 'rejected').length;
    setStatus(null);
    await loadDetail();
    setBusy(false);
    if (failed > 0) {
      showToast(t('detail.applyPartial', { n: failed }));
    }
  }

  async function performAnalysis() {
    setStatus('running', t('detail.analysisRunning'));
    try {
      await api.analyzeItem(itemId);
      setStatus(null);
      await loadDetail();
      return true;
    } catch (err) {
      // 證據（照片）已經保存；只有整理沒完成 —— 誠實回報並保留重試。
      console.warn('AI reinterpretation failed:', err);
      setStatus('failed', t('detail.analysisFailed', { err: err.message }));
      return false;
    }
  }

  async function runAnalysis() {
    if (busy) return;
    setBusy(true);
    try {
      await performAnalysis();
    } finally {
      setBusy(false);
    }
  }

  addPhotoBtn.addEventListener('click', () => {
    if (!busy) photoInput.click();
  });

  reanalyzeBtn.addEventListener('click', () => runAnalysis());

  photoInput.addEventListener('change', async () => {
    const files = Array.from(photoInput.files || []);
    photoInput.value = '';
    if (files.length === 0 || busy) return;

    setBusy(true);
    setStatus('running', t('detail.uploading'));
    try {
      // 先保存證據，再談理解 —— 順序固定：分析失敗不會丟照片。
      const observation = await api.createObservation(itemId, { kind: 'recheck' });
      const result = await api.uploadObservationPhotos(observation.id, files);
      const archived = (result.archived || []).length;
      const skipped = (result.skipped || []).length;
      let message = t('detail.photosAdded', { n: archived });
      if (skipped > 0) message += t('detail.photosSkipped', { n: skipped });
      showToast(message);

      await loadDetail();       // 新照片立即可見（即使 AI 後續失敗）
      await performAnalysis();  // 接著做情境式重新理解
    } catch (err) {
      console.error('Failed to add evidence photo:', err);
      setStatus(null);
      showToast(`${t('detail.uploadError')}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  });

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

    // 補充資訊：AI（或使用者）整理出的 attributes（Phase 2B）
    const attributeEntries = Object.entries(item.attributes || {})
      .filter(([, value]) =>
        value !== null && value !== undefined && String(value).trim() !== '');
    const attributesHtml = attributeEntries.length > 0
      ? `
          <div class="spec-item" style="grid-column: 1 / -1;">
            <span class="spec-label">${t('detail.attributesTitle')}</span>
            <div class="attribute-list">
              ${attributeEntries.map(([key, value]) => `
                <div class="attribute-row">
                  <span class="attribute-key">${key}</span>
                  <span class="attribute-value">${value}</span>
                </div>
              `).join('')}
            </div>
          </div>
        `
      : '';

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
              <span class="spec-label">${t('detail.fieldNotes')}</span>
              <div class="spec-val" style="font-weight: normal; font-size: 0.95rem; line-height: 1.5;">${item.notes}</div>
            </div>
          ` : ''}
          ${attributesHtml}
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

    // Pending AI suggestions (kept outside detailContent so they survive
    // the detail re-render during review actions).
    renderReview(data.suggestions);
  }

  loadDetail();

  return {
    element: el,
  };
}
