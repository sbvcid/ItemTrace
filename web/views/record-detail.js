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
import { escapeHtml } from '../core/dom.js';
import { showToast } from '../core/router.js';
import { t } from '../i18n/index.js';

export async function createRecordDetailView(params, router) {
  const el = document.createElement('div');
  el.className = 'record-detail-view';

  const itemId = params.id;

  el.innerHTML = `
     <header class="app-header">
       <div class="header-breadcrumb">
         <a href="/" class="icon-btn" title="${t('detail.backHome')}" data-link>←</a>
         <span class="header-id">${itemId}</span>
       </div>
       <div class="header-actions">
       </div>
     </header>

     <div class="container detail-toolbar-wrap">
        <div class="detail-toolbar">
          <button type="button" class="btn-secondary detail-tool-btn" id="btn-add-photo">📷 <span>${t('detail.addPhoto')}</span></button>
          <button type="button" class="btn-secondary detail-tool-btn" id="btn-reanalyze">✨ <span>${t('detail.reanalyze')}</span></button>
          <button type="button" class="btn-secondary detail-tool-btn" id="btn-edit-toggle">✎ <span>${t('detail.modify')}</span></button>
          <button type="button" class="btn-secondary detail-tool-btn" id="btn-move-folder">📁 <span>${t('detail.moveToFolder')}</span></button>
          <button type="button" class="btn-secondary detail-tool-btn is-danger" id="btn-move-trash">🗑 <span>${t('detail.moveToTrash')}</span></button>
       </div>
       <div class="detail-analysis-status" id="analysis-status" hidden></div>
       <div id="suggestion-review"></div>
       <div class="detail-edit-form" id="detail-edit-form" hidden></div>
       <div class="detail-folder-selector" id="folder-selector" style="display: none;"></div>
     </div>

    <main class="container" id="detail-content">
      <div style="text-align: center; padding: 48px 20px; color: var(--text-muted);">
        ${t('detail.loading')}
      </div>
    </main>

    <input type="file" id="detail-photo-input" accept="image/*" multiple hidden />
  `;

  const detailContent = el.querySelector('#detail-content');
  const addPhotoBtn = el.querySelector('#btn-add-photo');
  const reanalyzeBtn = el.querySelector('#btn-reanalyze');
  const editToggleBtn = el.querySelector('#btn-edit-toggle');
  const moveFolderBtn = el.querySelector('#btn-move-folder');
  const moveTrashBtn = el.querySelector('#btn-move-trash');
  const editFormContainer = el.querySelector('#detail-edit-form');
  const folderSelector = el.querySelector('#folder-selector');
  const photoInput = el.querySelector('#detail-photo-input');
  const analysisStatus = el.querySelector('#analysis-status');
  const suggestionReview = el.querySelector('#suggestion-review');

  let busy = false;
  let currentPending = [];
  let isEditMode = false;
  let currentItemData = {};

  function setBusy(on) {
    busy = on;
    addPhotoBtn.disabled = on;
    reanalyzeBtn.disabled = on;
    editToggleBtn.disabled = on;
    moveFolderBtn.disabled = on;
    moveTrashBtn.disabled = on;
  }

  function setStatus(kind, message, action = null) {
    if (!kind) {
      analysisStatus.hidden = true;
      analysisStatus.className = 'detail-analysis-status';
      analysisStatus.innerHTML = '';
      return;
    }
    analysisStatus.hidden = false;
    analysisStatus.className = `detail-analysis-status is-${kind}`;
    const icon = kind === 'failed' ? '⚠️' : '✨';
    // SR-1／F6：訊息裡可能夾帶紀錄值或錯誤訊息（皆屬不可信）→ 一律 escape。
    analysisStatus.innerHTML = `
      <span class="analysis-text">${icon} ${escapeHtml(message)}</span>
      ${action ? `<button type="button" class="btn-secondary detail-tool-btn" id="btn-status-action">${escapeHtml(action.label)}</button>` : ''}
    `;
    const actionBtn = analysisStatus.querySelector('#btn-status-action');
    if (actionBtn && action) {
      actionBtn.addEventListener('click', () => {
        if (!busy) action.onClick();
      });
    }
  }

  async function loadDetail() {
    try {
      const data = await api.getItem(itemId);
      renderDetail(data);
    } catch (err) {
      console.error('Failed to load item detail:', err);
      renderLoadError(err);
    }
  }

  function renderLoadError(err) {
    // 錯誤分類：只有後端確實回報紀錄不存在（404）時才顯示「找不到此
    // 紀錄」；授權失敗、伺服器錯誤與網路中斷各有符合實際狀況的訊息，
    // 不再一律偽裝成 404。
    const status = err && typeof err.status === 'number' ? err.status : null;

    if (status === 404) {
      detailContent.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">⚠️</div>
          <div class="empty-title">${t('detail.notFoundTitle')}</div>
          <div class="empty-subtitle">${escapeHtml(err.message)}</div>
          <a href="/" class="btn-primary" style="display: inline-flex; width: auto;" data-link>${t('detail.backHome')}</a>
        </div>
      `;
      return;
    }

    let title = t('detail.loadErrorTitle');
    let subtitle = t('detail.loadErrorNetwork');
    if (status === 401 || status === 403) {
      title = t('detail.errorAuthTitle');
      subtitle = err.message || t('detail.loadErrorNetwork');
    } else if (status !== null) {
      subtitle = t('detail.loadErrorServer', { status });
      if (err.message && err.message !== `HTTP ${status}`) {
        subtitle = `${subtitle}：${err.message}`;
      }
    }

    detailContent.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div class="empty-title">${escapeHtml(title)}</div>
        <div class="empty-subtitle">${escapeHtml(subtitle)}</div>
        <button type="button" class="btn-primary" id="btn-detail-retry" style="display: inline-flex; width: auto;">${t('detail.retry')}</button>
        <a href="/" class="btn-secondary" style="display: inline-flex; width: auto; margin-top: 8px;" data-link>${t('detail.backHome')}</a>
      </div>
    `;
    const retryBtn = detailContent.querySelector('#btn-detail-retry');
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        detailContent.innerHTML = `
          <div style="text-align: center; padding: 48px 20px; color: var(--text-muted);">
            ${t('detail.loading')}
          </div>
        `;
        loadDetail();
      });
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

  function renderReview(suggestions, photos = []) {
    currentPending = (suggestions || []).filter(s => s.status === 'pending');
    if (currentPending.length === 0) {
      suggestionReview.innerHTML = '';
      return;
    }
    const photoIndexById = new Map(
      (photos || []).map((photo, index) => [photo.id, index + 1])
    );
    const rows = currentPending.map(s => {
      const confidence = typeof s.confidence === 'number'
        ? `<span class="suggestion-confidence">${Math.round(s.confidence * 100)}%</span>`
        : '';
      const photoNumber = s.source_photo_id
        ? photoIndexById.get(s.source_photo_id)
        : null;
      const photoChip = photoNumber
        ? `<span class="suggestion-photo">📷 #${photoNumber}</span>`
        : '';
      const isConflict = s.source === 'external_conflict';
      const conflictNote = isConflict
        ? `<div class="suggestion-conflict-note">⚠️ ${t('detail.conflictNote')}</div>`
        : '';
      return `
        <div class="suggestion-row${isConflict ? ' is-conflict' : ''}" data-id="${s.id}">
          <div class="suggestion-info">
            <div class="suggestion-field">${escapeHtml(fieldLabel(s.field))} ${confidence} ${photoChip}</div>
            <div class="suggestion-value">${escapeHtml(s.value)}</div>
            ${conflictNote}
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
      // Phase 2C-B：auto=1 —— 合格的低風險項目直接套用（可復原），
      // 其餘（含衝突升級）留在待確認清單。
      const created = await api.analyzeItem(itemId, { auto: true });
      await loadDetail();
      const applied = (created || []).filter(
        s => s.status === 'accepted' && s.source === 'auto'
      );
      if (applied.length > 0) {
        // Phase 2C-D：顯示「先前判讀 → 新值」，讓修訂看得懂。
        const details = await buildRevisionDetails(applied);
        setStatus(
          'applied',
          t('detail.analysisApplied', { n: applied.length, fields: details }),
          {
            label: t('detail.undo'),
            onClick: () => undoSuggestions(applied),
          }
        );
      } else {
        setStatus(null);
      }
      return true;
    } catch (err) {
      // 證據（照片）已經保存；只有整理沒完成 —— 誠實回報並保留重試。
      console.warn('AI reinterpretation failed:', err);
      setStatus('failed', t('detail.analysisFailed', { err: err.message }), {
        label: t('detail.analysisRetry'),
        onClick: () => runAnalysis(),
      });
      return false;
    }
  }

  async function buildRevisionDetails(applied) {
    // 從事件找每次自動套用的前值：banner 顯示「先前判讀 → 新值」。
    let events = [];
    try {
      events = (await api.listEvents(itemId, 50)) || [];
    } catch (err) {
      console.warn('events unavailable for revision details:', err);
    }
    const fieldPrevious = new Map();
    const attributePrevious = new Map();
    for (const event of events) {
      if (event.type !== 'field.changed' || event.actor !== 'system') continue;
      if (event.field === 'attributes') {
        const before = (event.prev_value && typeof event.prev_value === 'object')
          ? event.prev_value
          : {};
        const after = (event.next_value && typeof event.next_value === 'object')
          ? event.next_value
          : {};
        for (const s of applied) {
          if (!s.field.startsWith('attribute:')) continue;
          const key = s.field.slice('attribute:'.length);
          if (!attributePrevious.has(key) && before[key] !== after[key]) {
            attributePrevious.set(key, before[key]);
          }
        }
      } else if (!fieldPrevious.has(event.field)) {
        fieldPrevious.set(event.field, event.prev_value);
      }
    }
    return applied.map(s => {
      const label = fieldLabel(s.field);
      const key = s.field.startsWith('attribute:')
        ? s.field.slice('attribute:'.length)
        : null;
      const from = key ? attributePrevious.get(key) : fieldPrevious.get(s.field);
      if (from === undefined || from === null || from === '') {
        return t('detail.revisionFilled', { field: label, to: s.value });
      }
      return t('detail.revisionChanged', {
        field: label, from: String(from), to: s.value,
      });
    }).join('、');
  }

  async function undoSuggestions(applied) {
    if (busy || applied.length === 0) return;
    setBusy(true);
    try {
      const results = await Promise.allSettled(
        applied.map(s => api.undoSuggestion(s.id))
      );
      const stale = [];
      const failed = [];
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') return;
        const label = fieldLabel(applied[index].field);
        if (result.reason && result.reason.status === 409) {
          stale.push(label);
        } else {
          failed.push(label);
        }
      });
      setStatus(null);
      await loadDetail();
      if (stale.length > 0) {
        // 過期（值已被後續修改）：逐項說明哪些欄位維持現值。
        showToast(t('detail.undoStale', { fields: stale.join('、') }));
      } else if (failed.length > 0) {
        showToast(t('detail.undoFailed', { fields: failed.join('、') }));
      } else {
        showToast(t('detail.undoDone'));
      }
    } finally {
      setBusy(false);
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

  moveTrashBtn.addEventListener('click', async () => {
    if (busy) return;
    // 明確確認：說明會從一般列表隱藏，但照片與資料暫時保留、可還原。
    const confirmed = window.confirm(
      t('detail.trashConfirm', { name: currentItemData.item?.name || itemId })
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      await api.voidItem(itemId);
      showToast(t('detail.trashDone'));
      router.navigate('/');
    } catch (err) {
      console.error('Move to trash failed:', err);
      showToast(`${t('detail.trashError')}: ${err.message}`);
      setBusy(false);
    }
  });

  moveFolderBtn.addEventListener('click', async () => {
    if (busy || folderSelector.style.display !== 'none') return;
    showFolderSelector();
  });

  function showFolderSelector() {
    folderSelector.innerHTML = `
      <div class="detail-card" style="margin-top: 16px; padding: 16px;">
        <div style="font-weight: 700; margin-bottom: 12px;">${t('detail.selectFolder')}</div>
        <div id="folder-options" style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px;">
          <div style="text-align: center; color: var(--text-muted);">${t('app.loading')}</div>
        </div>
        <div style="display: flex; gap: 10px;">
          <button type="button" class="btn-secondary" id="btn-cancel-folder" style="flex: 1;">${t('app.cancel')}</button>
        </div>
      </div>
    `;
    folderSelector.style.display = 'block';
    
    // Load folders
    loadFoldersForSelector();
  }

  async function loadFoldersForSelector() {
    try {
      const data = await api.listFolders('active');
      const folders = data.folders || [];
      const optionsContainer = folderSelector.querySelector('#folder-options');
      
      let html = '';
      
      // Unclassified option
      html += `
        <button type="button" class="folder-option-btn" data-folder-id="">
          📋 ${t('folders.unclassified')}
        </button>
      `;
      
      // Folders
      folders.forEach(folder => {
        html += `
          <button type="button" class="folder-option-btn" data-folder-id="${escapeHtml(folder.id)}">
            📁 ${escapeHtml(folder.name)}
          </button>
        `;
      });
      
      optionsContainer.innerHTML = html;
      
      // Attach event listeners
      optionsContainer.querySelectorAll('.folder-option-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
          const folderId = btn.getAttribute('data-folder-id') || null;
          await performMoveToFolder(folderId);
        });
      });
    } catch (err) {
      console.error('Failed to load folders:', err);
      const optionsContainer = folderSelector.querySelector('#folder-options');
      optionsContainer.innerHTML = `
        <div style="color: var(--color-danger); padding: 8px;">
          ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  async function performMoveToFolder(folderId) {
    if (busy) return;
    setBusy(true);
    try {
      await api.moveItemToFolder(itemId, folderId);
      showToast(t('detail.moveToFolderDone'));
      closeFolderSelector();
      await loadDetail();
    } catch (err) {
      console.error('Move to folder failed:', err);
      showToast(`${t('detail.moveToFolderError')}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  function closeFolderSelector() {
    folderSelector.style.display = 'none';
    folderSelector.innerHTML = '';
  }

  // Close folder selector on click outside
  folderSelector.addEventListener('click', (e) => {
    if (e.target === folderSelector) {
      closeFolderSelector();
    }
  });

  const cancelFolderBtn = folderSelector.querySelector('#btn-cancel-folder');
  if (cancelFolderBtn) {
    cancelFolderBtn.addEventListener('click', closeFolderSelector);
  }

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

  editToggleBtn.addEventListener('click', () => {
    if (isEditMode || busy) return;
    enterEditMode();
  });

  function enterEditMode() {
    isEditMode = true;
    // 工具列只負責「進入編輯」；儲存與取消由表單自己的按鈕處理，
    // 不會出現工具列顯示「確認」卻只關閉表單的語意。
    editToggleBtn.style.display = 'none';
    renderEditForm(currentItemData);
    editFormContainer.hidden = false;
  }

  function exitEditMode() {
    isEditMode = false;
    editToggleBtn.style.display = '';
    editFormContainer.hidden = true;
    editFormContainer.innerHTML = '';
  }

  function renderEditForm(data) {
     const item = data.item || {};
     editFormContainer.innerHTML = `
       <div class="detail-card" style="margin-top: 16px; padding: 16px;">
         <div style="font-weight: 700; margin-bottom: 12px;">${t('detail.modifyTitle')}</div>
         
        <div style="margin-bottom: 12px;">
          <label class="ai-field-label">${t('detail.fieldName')}</label>
          <input type="text" class="ai-edit-input" id="edit-name" value="${escapeHtml(item.name || '')}" />
        </div>
        
        <div style="margin-bottom: 12px;">
          <label class="ai-field-label">${t('detail.fieldBrand')}</label>
          <input type="text" class="ai-edit-input" id="edit-brand" value="${escapeHtml(item.brand || '')}" />
        </div>
        
        <div style="margin-bottom: 12px;">
          <label class="ai-field-label">${t('detail.fieldModel')}</label>
          <input type="text" class="ai-edit-input" id="edit-model" value="${escapeHtml(item.model || '')}" />
        </div>
        
        <div style="margin-bottom: 12px;">
          <label class="ai-field-label">${t('detail.fieldCategory')}</label>
          <input type="text" class="ai-edit-input" id="edit-category" value="${escapeHtml(item.category || '')}" />
        </div>
        
        <div style="margin-bottom: 12px;">
          <label class="ai-field-label">${t('detail.fieldCondition')}</label>
          <input type="text" class="ai-edit-input" id="edit-condition" value="${escapeHtml(item.condition || '')}" />
        </div>
        
        <div style="margin-bottom: 12px;">
          <label class="ai-field-label">${t('detail.fieldNotes')}</label>
          <textarea class="ai-edit-input" id="edit-notes" style="min-height: 80px; resize: vertical;">${escapeHtml(item.notes || '')}</textarea>
        </div>
        
        <div style="display: flex; gap: 10px;">
          <button type="button" class="btn-primary" id="btn-save-edits" style="flex: 1;">✓ ${t('app.save')}</button>
          <button type="button" class="btn-secondary" id="btn-cancel-edits" style="flex: 1;">${t('app.cancel')}</button>
        </div>
      </div>
    `;

    editFormContainer.querySelector('#btn-save-edits')
      .addEventListener('click', saveEdits);
    editFormContainer.querySelector('#btn-cancel-edits')
      .addEventListener('click', cancelEdits);
  }

  function cancelEdits() {
    if (busy) return;
    // 取消：不送任何請求、不改任何資料；未儲存的輸入直接捨棄。
    exitEditMode();
  }

  async function saveEdits() {
    if (busy) return;
    setBusy(true);
    const saveBtn = editFormContainer.querySelector('#btn-save-edits');
    const cancelBtn = editFormContainer.querySelector('#btn-cancel-edits');
    if (saveBtn) saveBtn.disabled = true;
    if (cancelBtn) cancelBtn.disabled = true;

    try {
      const patchData = {};
      const newName = (editFormContainer.querySelector('#edit-name').value || '').trim();
      const newBrand = (editFormContainer.querySelector('#edit-brand').value || '').trim();
      const newModel = (editFormContainer.querySelector('#edit-model').value || '').trim();
      const newCategory = (editFormContainer.querySelector('#edit-category').value || '').trim();
      const newCondition = (editFormContainer.querySelector('#edit-condition').value || '').trim();
      const newNotes = (editFormContainer.querySelector('#edit-notes').value || '').trim();

      if (newName !== (currentItemData.item.name || '')) patchData.name = newName;
      if (newBrand !== (currentItemData.item.brand || '')) patchData.brand = newBrand;
      if (newModel !== (currentItemData.item.model || '')) patchData.model = newModel;
      if (newCategory !== (currentItemData.item.category || '')) patchData.category = newCategory;
      if (newCondition !== (currentItemData.item.condition || '')) patchData.condition = newCondition;
      if (newNotes !== (currentItemData.item.notes || '')) patchData.notes = newNotes;

      if (Object.keys(patchData).length === 0) {
        // 沒有變更：留在編輯模式，輸入原封不動，由使用者決定儲存或取消。
        showToast(t('detail.noChanges'));
        return;
      }

      await api.patchItem(itemId, patchData);
      exitEditMode();
      showToast(t('detail.saveDone'));
      // 儲存成功：重新載入，畫面顯示後端回報的最新資料。
      await loadDetail();
    } catch (err) {
      // 儲存失敗：表單留在編輯模式，使用者輸入完整保留，可直接重試。
      console.error('Failed to save edits:', err);
      showToast(`${t('detail.saveError')}: ${err.message}`);
    } finally {
      setBusy(false);
      if (saveBtn) saveBtn.disabled = false;
      if (cancelBtn) cancelBtn.disabled = false;
    }
  }

  function renderDetail(data) {
    // Save current data for edit form
    currentItemData = data;
    
    const item = data.item;
    const photos = data.photos || [];
    const identifiers = data.identifiers || [];

    // 已在垃圾桶的紀錄：不再提供「移至垃圾桶」；還原／永久刪除在垃圾桶頁。
    moveTrashBtn.style.display = item.status === 'void' ? 'none' : '';

    // Photos carousel
    let photosHtml = '';
    if (photos.length > 0) {
      const primaryPhoto = photos[0];
      const primaryPhotoUrl = getPhotoUrl(primaryPhoto.filename);

      const thumbsHtml = photos.map((p, idx) => {
        const photoUrl = getPhotoUrl(p.filename);
        return `
          <div class="detail-thumb-item ${idx === 0 ? 'active' : ''}" data-url="${escapeHtml(photoUrl)}">
            <img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(t('detail.photosTitle', { n: idx + 1 }))}" loading="lazy" />
          </div>
        `;
      }).join('');

      photosHtml = `
        <div class="detail-photos-carousel">
          <img src="${escapeHtml(primaryPhotoUrl)}" alt="${escapeHtml(item.name || 'Photo')}" class="detail-main-img" id="main-photo" />
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
    // SR-1／F6：所有紀錄欄位（含 AI 產出）進版型前先 escape。
    const title = escapeHtml(item.name || item.model || t('home.cardUntitled'));
    const serialItems = identifiers.filter(i => i.kind === 'serial');

    // 只負責序號列；型號由下面的 specs grid 顯示（以前這裡的 fallback
    // 會在沒有序號時再畫一次型號 → 型號設定後整列重複）。
    const serialsHtml = serialItems.map(i => `
          <div class="spec-item">
            <span class="spec-label">${t('detail.serialBadge')}</span>
            <div class="spec-val mono">
              <span>${escapeHtml(i.value)}</span>
              <button type="button" class="btn-copy" data-copy="${escapeHtml(i.value)}" title="${t('detail.copySerial')}">📋 ${t('detail.copySerial')}</button>
            </div>
          </div>
        `).join('');

    // 補充資訊：AI（或使用者）整理出的 attributes（Phase 2B）。
    // attribute:description 另外抽出來，作為標題後的描述主入口。
    const attributes = item.attributes || {};
    const description = typeof attributes.description === 'string'
      ? attributes.description.trim()
      : '';
    const attributeEntries = Object.entries(attributes)
      .filter(([key, value]) =>
        key !== 'description'
        && value !== null && value !== undefined && String(value).trim() !== '');
    const attributesHtml = attributeEntries.length > 0
      ? `
          <div class="spec-item" style="grid-column: 1 / -1;">
            <span class="spec-label">${t('detail.attributesTitle')}</span>
            <div class="attribute-list">
              ${attributeEntries.map(([key, value]) => `
                <div class="attribute-row">
                  <span class="attribute-key">${escapeHtml(key)}</span>
                  <span class="attribute-value">${escapeHtml(value)}</span>
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
        ${description ? `<div class="detail-description">${escapeHtml(description)}</div>` : ''}

        <div class="detail-specs-grid">
          ${item.brand ? `
            <div class="spec-item">
              <span class="spec-label">${t('detail.fieldBrand')}</span>
              <div class="spec-val">${escapeHtml(item.brand)}</div>
            </div>
          ` : ''}
          ${item.model ? `
            <div class="spec-item">
              <span class="spec-label">${t('detail.fieldModel')}</span>
              <div class="spec-val">${escapeHtml(item.model)}</div>
            </div>
          ` : ''}
          ${item.category ? `
            <div class="spec-item">
              <span class="spec-label">${t('detail.fieldCategory')}</span>
              <div class="spec-val">${escapeHtml(item.category)}</div>
            </div>
          ` : ''}
          ${serialsHtml}
          ${item.condition ? `
            <div class="spec-item" style="grid-column: 1 / -1;">
              <span class="spec-label">${t('detail.fieldCondition')}</span>
              <div class="spec-val" style="font-weight: normal; font-size: 0.95rem; line-height: 1.5;">${escapeHtml(item.condition)}</div>
            </div>
          ` : ''}
          ${item.notes ? `
            <div class="spec-item" style="grid-column: 1 / -1;">
              <span class="spec-label">${t('detail.fieldNotes')}</span>
              <div class="spec-val" style="font-weight: normal; font-size: 0.95rem; line-height: 1.5;">${escapeHtml(item.notes)}</div>
            </div>
          ` : ''}
           ${attributesHtml}
         </div>

         <div class="detail-meta" style="font-size: 0.82rem; color: var(--text-muted); padding-top: 8px;">
           ${t('detail.fieldCreated')}：${escapeHtml(item.created_at ? item.created_at.replace('T', ' ').slice(0, 19) : '剛剛')}
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
    renderReview(data.suggestions, data.photos);
  }

  loadDetail();

  return {
    element: el,
  };
}
