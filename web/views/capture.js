/**
 * Capture View (/capture)
 *
 * Core Experience Vertical Slice:
 * 📷 拍照 → AI 理解/整理 → 看見 vs 推測 → ✓ 存起來 → 回首頁看見最新紀錄
 */

import { api, getPhotoUrl } from '../core/api.js';
import { showToast } from '../core/router.js';
import { t } from '../i18n/index.js';

export async function createCaptureView(params, router) {
  const el = document.createElement('div');
  el.className = 'capture-view';

  el.innerHTML = `
    <header class="app-header">
      <div style="display: flex; align-items: center; gap: 8px;">
        <a href="/" class="icon-btn" title="${t('app.back')}" data-link>←</a>
        <span style="font-weight: 700; font-size: 1.05rem;">${t('capture.headerTitle')}</span>
      </div>
    </header>

    <main class="container">
      <!-- 步驟 1: 拍照與托盤 -->
      <section id="step-camera">
        <!-- 點選或拖放區域 -->
        <div class="capture-zone" id="drop-zone">
          <div class="capture-zone-icon">📷</div>
          <div class="capture-zone-title">${t('capture.btnCamera')}</div>
          <div class="capture-zone-hint">${t('capture.stepSubtitle')}</div>
          <input
            type="file"
            id="camera-input"
            class="file-input-hidden"
            accept="image/*"
            capture="environment"
            multiple
          />
        </div>

        <!-- 縮圖托盤 -->
        <div class="tray-section" id="tray-section" style="display: none; margin-top: 16px;">
          <div class="tray-header">
            <span class="tray-title" id="tray-count-label"></span>
            <button type="button" class="btn-secondary" id="btn-clear-all" style="width: auto; padding: 4px 10px; font-size: 0.8rem;">${t('app.cancel')}</button>
          </div>
          <div class="tray-grid" id="tray-grid">
            <!-- Thumbnails inserted here -->
            <button type="button" class="tray-add-more" id="btn-add-more">
              <span style="font-size: 1.2rem;">＋</span>
              <span>${t('capture.btnAddMore')}</span>
            </button>
          </div>
        </div>

        <!-- 開始整理按鈕 -->
        <div id="step-camera-actions" style="margin-top: 20px; display: none;">
          <button type="button" class="btn-primary" id="btn-start-organize">
            <span>✨</span>
            <span id="btn-start-text">${t('capture.btnStartAiSingle')}</span>
          </button>
        </div>
      </section>

      <!-- 步驟 2: AI 整理中 (Shimmer) -->
      <section id="step-loading" style="display: none;">
        <div class="ai-loading-box">
          <div class="ai-pulse-icon">✨</div>
          <div class="ai-loading-title">${t('capture.analyzingTitle')}</div>
          <div class="ai-loading-desc">${t('capture.analyzingSubtitle')}</div>
        </div>
      </section>

      <!-- 步驟 3: AI 成果呈遞與驗收 -->
      <section id="step-review" style="display: none;">
        <div class="ai-draft-box">
          <div class="ai-draft-header">
            <div class="ai-draft-badge">
              <span>✨</span>
              <span>${t('capture.reviewTitle')}</span>
            </div>
            <button type="button" class="icon-btn" id="btn-toggle-edit" title="${t('capture.btnEdit')}">
              <span style="font-size: 0.9rem;">✎ ${t('capture.btnEdit')}</span>
            </button>
          </div>

          <!-- 照片橫條 -->
          <div class="tray-grid" id="review-photos-bar" style="margin-bottom: 16px;"></div>

          <!-- 整理欄位清單 (Default view) -->
          <div class="ai-fields-list" id="fields-display-container">
            <!-- Populated dynamically -->
          </div>

          <!-- 編輯欄位清單 (Default hidden) -->
          <div class="ai-fields-list" id="fields-edit-container" style="display: none;">
            <div class="ai-field-row">
              <label class="ai-field-label">${t('detail.fieldName')}</label>
              <input type="text" class="ai-edit-input" id="edit-name" placeholder="${t('capture.namePlaceholder')}" />
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div class="ai-field-row">
                <label class="ai-field-label">${t('detail.fieldBrand')}</label>
                <input type="text" class="ai-edit-input" id="edit-brand" placeholder="${t('capture.brandPlaceholder')}" />
              </div>
              <div class="ai-field-row">
                <label class="ai-field-label">${t('detail.fieldModel')}</label>
                <input type="text" class="ai-edit-input" id="edit-model" placeholder="${t('capture.modelPlaceholder')}" />
              </div>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div class="ai-field-row">
                <label class="ai-field-label">${t('detail.fieldCategory')}</label>
                <input type="text" class="ai-edit-input" id="edit-category" placeholder="${t('capture.categoryPlaceholder')}" />
              </div>
              <div class="ai-field-row">
                <label class="ai-field-label">${t('capture.serialPlaceholder')}</label>
                <input type="text" class="ai-edit-input" id="edit-serial" placeholder="${t('capture.serialPlaceholder')}" />
              </div>
            </div>
            <div class="ai-field-row">
              <label class="ai-field-label">${t('detail.fieldCondition')}</label>
              <input type="text" class="ai-edit-input" id="edit-condition" placeholder="${t('capture.conditionPlaceholder')}" />
            </div>
          </div>

          <!-- 核心操作按鈕 -->
          <div class="draft-actions">
            <button type="button" class="btn-primary" id="btn-save-confirm">
              <span>✓</span>
              <span>${t('capture.btnSaveDirect')}</span>
            </button>
            <button type="button" class="btn-secondary" id="btn-cancel-draft">
              <span>${t('app.cancel')}</span>
            </button>
          </div>
        </div>
      </section>

      <!-- 序號特寫檢視 Modal -->
      <div id="inspector-modal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 999; align-items: center; justify-content: center; padding: 20px;">
        <div style="max-width: 90%; max-height: 90%; position: relative; display: flex; flex-direction: column; align-items: center;">
          <img id="inspector-img" src="" alt="${t('capture.inspectPhoto')}" style="max-width: 100%; max-height: 80vh; border-radius: var(--radius-md); object-fit: contain;" />
          <button type="button" id="btn-close-inspector" class="btn-secondary" style="margin-top: 12px; width: auto; color: #fff; background: rgba(255,255,255,0.2); border-color: rgba(255,255,255,0.4);">${t('app.close')}</button>
        </div>
      </div>
    </main>
  `;

  // Internal state for this capture session
  let capturedFiles = [];
  let currentItemId = null;
  let currentSuggestions = [];
  let isEditMode = false;

  // Phase 2A：記住本次 session 已成功套用的操作，重試時跳過，
  // 確保「再按一次存起來」不會重複套用同一個變更。
  const appliedSuggestionIds = new Set();
  let appliedSerialValue = null;

  // Elements
  const dropZone = el.querySelector('#drop-zone');
  const cameraInput = el.querySelector('#camera-input');
  const traySection = el.querySelector('#tray-section');
  const trayGrid = el.querySelector('#tray-grid');
  const trayCountLabel = el.querySelector('#tray-count-label');
  const stepCameraActions = el.querySelector('#step-camera-actions');
  const btnStartOrganize = el.querySelector('#btn-start-organize');
  const btnStartText = el.querySelector('#btn-start-text');
  const btnAddMore = el.querySelector('#btn-add-more');
  const btnClearAll = el.querySelector('#btn-clear-all');

  const stepCamera = el.querySelector('#step-camera');
  const stepLoading = el.querySelector('#step-loading');
  const stepReview = el.querySelector('#step-review');

  const fieldsDisplayContainer = el.querySelector('#fields-display-container');
  const fieldsEditContainer = el.querySelector('#fields-edit-container');
  const reviewPhotosBar = el.querySelector('#review-photos-bar');
  const btnToggleEdit = el.querySelector('#btn-toggle-edit');
  const btnSaveConfirm = el.querySelector('#btn-save-confirm');
  const btnCancelDraft = el.querySelector('#btn-cancel-draft');

  const editName = el.querySelector('#edit-name');
  const editBrand = el.querySelector('#edit-brand');
  const editModel = el.querySelector('#edit-model');
  const editCategory = el.querySelector('#edit-category');
  const editSerial = el.querySelector('#edit-serial');
  const editCondition = el.querySelector('#edit-condition');

  const inspectorModal = el.querySelector('#inspector-modal');
  const inspectorImg = el.querySelector('#inspector-img');
  const btnCloseInspector = el.querySelector('#btn-close-inspector');

  // Trigger camera input on click
  dropZone.addEventListener('click', () => cameraInput.click());
  btnAddMore.addEventListener('click', () => cameraInput.click());

  // Drag and drop handlers
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      appendFiles(Array.from(e.dataTransfer.files));
    }
  });

  cameraInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      appendFiles(Array.from(e.target.files));
      cameraInput.value = ''; // Reset for subsequent selections
    }
  });

  function appendFiles(newFiles) {
    const validImages = newFiles.filter(f => f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic|bmp)$/i.test(f.name));
    if (validImages.length === 0) {
      showToast(t('capture.uploadError'));
      return;
    }

    for (const file of validImages) {
      const url = URL.createObjectURL(file);
      capturedFiles.push({ file, url });
    }

    renderTray();
  }

  function renderTray() {
    // Remove old thumbnails, keep btnAddMore
    const items = trayGrid.querySelectorAll('.tray-item');
    items.forEach(item => item.remove());

    if (capturedFiles.length === 0) {
      traySection.style.display = 'none';
      stepCameraActions.style.display = 'none';
      return;
    }

    traySection.style.display = 'block';
    stepCameraActions.style.display = 'block';
    trayCountLabel.textContent = t('home.photoCount', { n: capturedFiles.length });
    btnStartText.textContent = t('capture.btnStartAi', { n: capturedFiles.length });

    capturedFiles.forEach((item, index) => {
      const thumb = document.createElement('div');
      thumb.className = 'tray-item';
      thumb.innerHTML = `
        <img src="${item.url}" alt="${t('home.photoCount', { n: index + 1 })}" />
        <button type="button" class="tray-item-remove" title="${t('app.delete')}">✕</button>
      `;

      thumb.querySelector('.tray-item-remove').addEventListener('click', (e) => {
        e.stopPropagation();
        URL.revokeObjectURL(item.url);
        capturedFiles.splice(index, 1);
        renderTray();
      });

      trayGrid.insertBefore(thumb, btnAddMore);
    });
  }

  btnClearAll.addEventListener('click', () => {
    capturedFiles.forEach(f => URL.revokeObjectURL(f.url));
    capturedFiles = [];
    renderTray();
  });

  // Start Organize Flow
  btnStartOrganize.addEventListener('click', async () => {
    if (capturedFiles.length === 0) return;

    // Switch to Loading View
    stepCamera.style.display = 'none';
    stepLoading.style.display = 'block';

    try {
      // Step 1: Upload photos to Inbox
      const rawFiles = capturedFiles.map(c => c.file);
      const uploadRes = await api.uploadInboxPhotos(rawFiles);
      const relativeFiles = uploadRes.entries.map(e => e.relative);

      // Step 2: Intake into Item
      const intakeRes = await api.intake(relativeFiles, 'intake');
      currentItemId = intakeRes.item_id;

      // Step 3: Call AI vision analysis
      let suggestions = [];
      try {
        suggestions = await api.analyzeItem(currentItemId);
      } catch (aiErr) {
        console.warn('AI analysis returned non-200 or no key:', aiErr);
        // Non-fatal: photos are safely stored!
      }

      currentSuggestions = suggestions || [];

      // Step 4: Show Review View
      stepLoading.style.display = 'none';
      stepReview.style.display = 'block';
      renderReviewScreen();
    } catch (err) {
      console.error('Capture pipeline failed:', err);
      showToast(`${t('capture.uploadError')}: ${err.message}`);
      stepLoading.style.display = 'none';
      stepCamera.style.display = 'block';
    }
  });

  function renderReviewScreen() {
    // Populate review photos bar
    reviewPhotosBar.innerHTML = '';
    capturedFiles.forEach((item) => {
      const photoThumb = document.createElement('div');
      photoThumb.className = 'tray-item';
      photoThumb.innerHTML = `<img src="${item.url}" alt="Photo" />`;
      reviewPhotosBar.appendChild(photoThumb);
    });

    // Extract values from AI suggestions
    const extracted = {
      name: '',
      brand: '',
      model: '',
      category: '',
      serial: '',
      condition: '',
    };
    const confidences = {};
    const sourcePhotos = {};

    for (const s of currentSuggestions) {
      if (s.field === 'name') {
        extracted.name = s.value;
        confidences.name = s.confidence;
      } else if (s.field === 'brand') {
        extracted.brand = s.value;
        confidences.brand = s.confidence;
      } else if (s.field === 'model') {
        extracted.model = s.value;
        confidences.model = s.confidence;
      } else if (s.field === 'category') {
        extracted.category = s.value;
        confidences.category = s.confidence;
      } else if (s.field === 'condition') {
        extracted.condition = s.value;
        confidences.condition = s.confidence;
      } else if (s.field === 'identifier:serial') {
        extracted.serial = s.value;
        confidences.serial = s.confidence;
        sourcePhotos.serial = s.source_photo_id;
      }
    }

    // Set initial edit inputs
    editName.value = extracted.name || '';
    editBrand.value = extracted.brand || '';
    editModel.value = extracted.model || '';
    editCategory.value = extracted.category || '';
    editSerial.value = extracted.serial || '';
    editCondition.value = extracted.condition || '';

    // Render Display Fields (區分「看見」與「推測」)
    fieldsDisplayContainer.innerHTML = '';

    const hasAnyField = extracted.name || extracted.brand || extracted.model || extracted.serial;

    if (!hasAnyField) {
      // General photo / pet / landscape / no AI key case (Scenario C)
      fieldsDisplayContainer.innerHTML = `
        <div style="background: var(--bg-subtle); padding: 14px; border-radius: var(--radius-md); font-size: 0.9rem; color: var(--text-secondary); line-height: 1.5;">
          ${t('capture.noFieldAlert')}
        </div>
        <div class="ai-field-row" style="margin-top: 12px;">
          <label class="ai-field-label">${t('detail.fieldName')}</label>
          <input type="text" class="ai-edit-input" id="fallback-name" placeholder="${t('capture.namePlaceholder')}" value="${editName.value || ''}" />
        </div>
      `;

      const fallbackNameInput = fieldsDisplayContainer.querySelector('#fallback-name');
      fallbackNameInput.addEventListener('input', () => {
        editName.value = fallbackNameInput.value;
      });
      return;
    }

    // 1. Name
    if (extracted.name) {
      fieldsDisplayContainer.appendChild(createFieldRow(t('detail.fieldName'), extracted.name, confidences.name));
    }

    // 2. Brand & Model
    if (extracted.brand || extracted.model) {
      const bmVal = [extracted.brand, extracted.model].filter(Boolean).join(' · ');
      const bmConf = Math.min(confidences.brand ?? 1, confidences.model ?? 1);
      fieldsDisplayContainer.appendChild(createFieldRow(`${t('detail.fieldBrand')} / ${t('detail.fieldModel')}`, bmVal, bmConf));
    }

    // 3. Category
    if (extracted.category) {
      fieldsDisplayContainer.appendChild(createFieldRow(t('detail.fieldCategory'), extracted.category, confidences.category));
    }

    // 4. Serial Number (with Magnifier context pill)
    if (extracted.serial) {
      const serialRow = createFieldRow(t('detail.serialBadge'), extracted.serial, confidences.serial, true);
      const labelGroup = serialRow.querySelector('.ai-field-label-group');

      const inspectBtn = document.createElement('button');
      inspectBtn.type = 'button';
      inspectBtn.className = 'icon-btn';
      inspectBtn.style.padding = '2px 8px';
      inspectBtn.style.fontSize = '0.78rem';
      inspectBtn.style.background = 'var(--bg-subtle)';
      inspectBtn.style.color = 'var(--text-secondary)';
      inspectBtn.innerHTML = `🔍 ${t('capture.inspectPhoto')}`;
      inspectBtn.addEventListener('click', () => {
        const targetPhoto = capturedFiles[0]?.url;
        if (targetPhoto) {
          inspectorImg.src = targetPhoto;
          inspectorModal.style.display = 'flex';
        }
      });

      labelGroup.appendChild(inspectBtn);
      fieldsDisplayContainer.appendChild(serialRow);
    }

    // 5. Condition
    if (extracted.condition) {
      fieldsDisplayContainer.appendChild(createFieldRow(t('detail.fieldCondition'), extracted.condition, confidences.condition));
    }
  }

  function createFieldRow(label, value, confidence, isMono = false) {
    const row = document.createElement('div');
    row.className = 'ai-field-row';

    // 規則：區分看見 (>= 0.85) 與推測 (< 0.85)
    const isCertain = confidence !== undefined && confidence !== null && confidence >= 0.85;
    const badgeHtml = isCertain
      ? `<span class="badge-seen">✓ ${t('capture.badgeSeen')}</span>`
      : `<span class="badge-guess">~ ${t('capture.badgeInferred')}</span>`;

    row.innerHTML = `
      <div class="ai-field-label-group">
        <span class="ai-field-label">${label}</span>
        ${badgeHtml}
      </div>
      <div class="ai-field-value ${isMono ? 'mono' : ''}">${value}</div>
    `;
    return row;
  }

  // Toggle Edit Mode
  btnToggleEdit.addEventListener('click', () => {
    isEditMode = !isEditMode;
    fieldsEditContainer.style.display = isEditMode ? 'flex' : 'none';
    fieldsDisplayContainer.style.display = isEditMode ? 'none' : 'flex';
    btnToggleEdit.innerHTML = isEditMode
      ? `<span style="font-size: 0.9rem; color: var(--color-primary); font-weight: 700;">✓ ${t('app.confirm')}</span>`
      : `<span style="font-size: 0.9rem;">✎ ${t('capture.btnEdit')}</span>`;
  });

  // Close inspector
  btnCloseInspector.addEventListener('click', () => {
    inspectorModal.style.display = 'none';
  });
  inspectorModal.addEventListener('click', (e) => {
    if (e.target === inspectorModal) inspectorModal.style.display = 'none';
  });

  // Confirm and Save (核心動作：✓ 存起來)
  //
  // 儲存分兩層：主要紀錄在 intake 時就已建立；這裡的工作是把 AI 建議與
  // 使用者編輯的值套用上去。任何一步失敗都要誠實回報（不得假裝全部成功），
  // 且重試不得重複套用 —— 已套用的建議與序號以區域狀態追蹤，後端的
  // pending 檢查與同值 no-op 則是第二道保險。
  btnSaveConfirm.addEventListener('click', async () => {
    if (!currentItemId) return;

    btnSaveConfirm.disabled = true;
    btnSaveConfirm.innerHTML = `<span>${t('app.loading')}</span>`;

    const failures = [];

    try {
      // 1. Accept suggestions one by one; already-applied ones are skipped.
      for (const suggestion of currentSuggestions) {
        if (appliedSuggestionIds.has(suggestion.id)) continue;
        try {
          await api.acceptSuggestion(suggestion.id);
          appliedSuggestionIds.add(suggestion.id);
        } catch (err) {
          console.warn(`Could not accept suggestion ${suggestion.id}:`, err);
          failures.push({ what: suggestion.field, error: err });
        }
      }

      // 2. Patch user-edited fields. Backend treats same-value PATCH as a no-op,
      //    so retrying this step never duplicates a change.
      const patchData = {};
      const newName = editName.value.trim();
      const newBrand = editBrand.value.trim();
      const newModel = editModel.value.trim();
      const newCategory = editCategory.value.trim();
      const newCondition = editCondition.value.trim();

      if (newName) patchData.name = newName;
      if (newBrand) patchData.brand = newBrand;
      if (newModel) patchData.model = newModel;
      if (newCategory) patchData.category = newCategory;
      if (newCondition) patchData.condition = newCondition;

      if (Object.keys(patchData).length > 0) {
        await api.patchItem(currentItemId, patchData);
      }

      // 3. Serial: only add manually when an accepted suggestion did not
      //    already create the same identifier (avoids a guaranteed 409).
      const newSerial = editSerial.value.trim();
      if (newSerial && appliedSerialValue !== newSerial) {
        const acceptedSerial = currentSuggestions.find(
          s => s.field === 'identifier:serial' && appliedSuggestionIds.has(s.id)
        );
        if (acceptedSerial && acceptedSerial.value.trim() === newSerial) {
          appliedSerialValue = newSerial;
        } else {
          try {
            await api.addIdentifier(currentItemId, { kind: 'serial', value: newSerial });
            appliedSerialValue = newSerial;
          } catch (err) {
            console.warn('Identifier add failed:', err.message);
            failures.push({ what: 'identifier:serial', error: err });
          }
        }
      }

      if (failures.length === 0) {
        showToast(t('capture.saveSuccess'));

        // 4. Back to Home: backend confirmed the save; the fresh record shows up
        //    first (created_at DESC) and is briefly highlighted via ?fresh=.
        router.navigate(`/?fresh=${currentItemId}`);
        return;
      }

      // 部分失敗：紀錄已建立，但部分內容未套用。不假裝全部成功，
      // 留在原畫面讓使用者直接重試（已套用的部分不會重跑）。
      console.warn('Save completed with failures:', failures);
      showToast(t('capture.savePartial', { n: failures.length }));
      btnSaveConfirm.disabled = false;
      btnSaveConfirm.innerHTML = `<span>✓ ${t('capture.btnSaveDirect')}</span>`;
    } catch (err) {
      // 硬失敗（例如 PATCH 失敗）：編輯的值沒有落地，留在原畫面重試。
      console.error('Failed to finalize item:', err);
      showToast(`${t('capture.saveError')}: ${err.message}`);
      btnSaveConfirm.disabled = false;
      btnSaveConfirm.innerHTML = `<span>✓ ${t('capture.btnSaveDirect')}</span>`;
    }
  });

  // Cancel
  btnCancelDraft.addEventListener('click', () => {
    capturedFiles.forEach(f => URL.revokeObjectURL(f.url));
    capturedFiles = [];
    router.navigate('/');
  });

  return {
    element: el,
    destroy() {
      capturedFiles.forEach(f => URL.revokeObjectURL(f.url));
    },
  };
}
