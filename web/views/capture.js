/**
 * Capture View (/capture)
 *
 * Core Experience Vertical Slice:
 * 📷 拍照 → AI 理解/整理 → 看見 vs 推測 → ✓ 存起來 → 回首頁看見最新紀錄
 */

import { api } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';
import { isHeicImageFile, partitionImageFiles } from '../core/photoFiles.js';
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
      <!-- 步驟 1: 拍照／匯入與托盤 -->
      <section id="step-camera">
        <!-- 兩種明確入口：拍照（後置相機）與匯入（系統照片／檔案選擇器）＋拖放 -->
        <div class="capture-zone" id="drop-zone">
          <div class="capture-zone-icon">📷</div>
          <div class="capture-zone-title">${t('capture.zoneTitle')}</div>
          <div class="capture-zone-hint">${t('capture.zoneSubtitle')}</div>
          <div class="capture-zone-actions">
            <button type="button" class="btn-primary capture-entry-btn" id="btn-capture-photo">
              <span class="capture-entry-icon">📷</span>
              <span>${t('capture.btnTakePhoto')}</span>
            </button>
            <button type="button" class="btn-secondary capture-entry-btn" id="btn-import-photos">
              <span class="capture-entry-icon">🖼️</span>
              <span class="capture-entry-label" id="btn-import-text">${t('capture.btnImport')}</span>
            </button>
          </div>
          <div class="capture-zone-drophint">${t('capture.zoneDropHint')}</div>
          <!-- 拍照：capture="environment" 提示行動瀏覽器開啟後置相機（不保證所有裝置；
               桌面上就是一個檔案選擇器）。單張一拍，追加就再按一次。
               accept 明確列出 .heic／.heif：部分桌面系統的照片選擇器光靠
               image/* 不會顯示 iPhone 的 HEIC。 -->
          <input
            type="file"
            id="capture-input"
            class="file-input-hidden"
            accept="image/*,.heic,.heif"
            capture="environment"
          />
          <!-- 匯入：不設 capture，交給系統的照片／檔案選擇器；支援一次選多張。 -->
          <input
            type="file"
            id="import-input"
            class="file-input-hidden"
            accept="image/*,.heic,.heif"
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
          </div>
          <!-- 已有照片時的追加入口：同樣區分拍照與匯入，不再只有一個含糊的按鈕 -->
          <div class="tray-add-row" id="tray-add-row">
            <button type="button" class="tray-add-action" id="btn-add-capture">
              <span>📷</span>
              <span>${t('capture.addCapture')}</span>
            </button>
            <button type="button" class="tray-add-action" id="btn-add-import">
              <span>🖼️</span>
              <span>${t('capture.addImport')}</span>
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
            <div class="ai-field-row">
              <label class="ai-field-label">${t('detail.fieldCategory')}</label>
              <input type="text" class="ai-edit-input" id="edit-category" placeholder="${t('capture.categoryPlaceholder')}" />
            </div>
            <div class="ai-field-row">
              <label class="ai-field-label">${t('detail.fieldCondition')}</label>
              <input type="text" class="ai-edit-input" id="edit-condition" placeholder="${t('capture.conditionPlaceholder')}" />
            </div>
            <div class="ai-field-row">
              <label class="ai-field-label">${t('capture.descriptionLabel')}</label>
              <div id="edit-description-list"></div>
              <div id="description-choice-hint" class="description-choice-hint" style="display: none;"></div>
              <button type="button" class="btn-secondary" id="btn-add-description" style="width: auto; margin-top: 8px; font-size: 0.82rem;">${t('capture.addDescription')}</button>
            </div>
            <div class="ai-field-row">
              <label class="ai-field-label">${t('capture.identifiersSection')}</label>
              <div id="edit-identifiers-list"></div>
            </div>
            <div class="ai-field-row">
              <label class="ai-field-label">${t('capture.attributesSection')}</label>
              <div id="edit-attributes-list"></div>
              <button type="button" class="btn-secondary" id="btn-add-attribute" style="width: auto; margin-top: 8px; font-size: 0.82rem;">${t('capture.addAttribute')}</button>
            </div>
          </div>

          <!-- 核心操作：存起來／修改／取消（修改入口放在閱讀完的操作區） -->
          <div class="draft-actions">
            <button type="button" class="btn-primary" id="btn-save-confirm">
              <span>✓</span>
              <span>${t('capture.btnSaveDirect')}</span>
            </button>
            <button type="button" class="btn-secondary" id="btn-toggle-edit">
              <span id="btn-toggle-edit-text">✎ ${t('capture.btnEdit')}</span>
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

  // 「確認儲存才建檔」：審閱階段只有 inbox 暫存檔與未持久化的草稿建議，
  // 正式 Item／photos／suggestions 一律等使用者按「存起來」才建立。
  let pendingInboxFiles = [];   // 本輪上傳落在 inbox 的相對路徑（暫存）
  let stagedConsumed = false;   // 暫存檔已被 intake 歸檔（或已清理）
  let draftModel = '';          // 草稿分析用的模型名（存檔時寫入建議追溯）
  let organizeBusy = false;
  let saveBusy = false;
  let saveCompleted = false;

  let currentItemId = null;
  let currentSuggestions = [];  // 草稿建議（無 id；index 對應上傳順序）
  let isEditMode = false;

  // 動態屬性（AI 的 attribute:<key> ＋ 使用者新增）：審閱畫面與存檔都以
  // 這份清單為準。draftIndex 指向 currentSuggestions 的索引；null 表示
  // 使用者自己新增（存檔時以 PATCH attributes 合併）。original 用來標示
  // 使用者是否改過該值（「自訂」badge）。
  let attributeRows = [];
  // 識別碼列（serial／imei／barcode，每個 AI 建議一列；沒有 AI 序號時
  // 仍提供一列手動序號）。value 可被修改、列可被移除；appliedValue 記住
  // 已確實寫入正式紀錄的值，重試時才能真的刪除被改掉／移除的舊值。
  let identifierRows = [];

  // 本輪草稿的固定欄位原始 AI 值與信心（閱讀模式標示「自訂／看見／推測」用）。
  let extracted = {
    name: '',
    brand: '',
    model: '',
    category: '',
    condition: '',
  };
  let confidences = {};

  // 草稿的 source_photo_index → 本機 blob URL（審閱時照片還沒有後端 ID）。
  let photoUrlById = new Map();
  // 存檔 intake 之後 orig_name → photos.id（把草稿的來源照片對應到正式紀錄）。
  let archivedIdByOrigName = new Map();

  // Phase 2A：記住本次 session 已成功套用的操作，重試時跳過，
  // 確保「再按一次存起來」不會重複套用同一個變更。
  // 以草稿 index 為鍵；createdSuggestionIds 記住已建立的正式建議 id，
  // 讓「create 成功但 accept 失敗」的重試不會重複建立建議。
  const appliedSuggestionIds = new Set();
  const createdSuggestionIds = new Map();
  // 已落成「拒絕」的草稿索引：代表使用者清空／修改／移除了 AI 值，
  // 重試時不再處理（建議本身保存 AI 原值，追溯不被覆蓋）。
  const rejectedSuggestionIds = new Set();
  // 已套用但最後被改掉／移除、必須真正刪除的識別碼（不假裝已移除）。
  const identifierDeletes = [];
  // 已確實寫入正式 attributes 的鍵；重試時判斷「移除」是否需要真的刪。
  const attributeAppliedKeys = new Set();
  // 曾被寫入正式紀錄、但描述列已被整列移除的舊值：重試時 value-aware
  // 清除（只刪確實是我們寫入的值，不會誤刪後來選用的描述）。
  const descriptionDeletes = [];

  // Elements
  const dropZone = el.querySelector('#drop-zone');
  const captureInput = el.querySelector('#capture-input');
  const importInput = el.querySelector('#import-input');
  const btnCapturePhoto = el.querySelector('#btn-capture-photo');
  const btnImportPhotos = el.querySelector('#btn-import-photos');
  const btnImportText = el.querySelector('#btn-import-text');
  const traySection = el.querySelector('#tray-section');
  const trayGrid = el.querySelector('#tray-grid');
  const trayCountLabel = el.querySelector('#tray-count-label');
  const stepCameraActions = el.querySelector('#step-camera-actions');
  const btnStartOrganize = el.querySelector('#btn-start-organize');
  const btnStartText = el.querySelector('#btn-start-text');
  const btnAddCapture = el.querySelector('#btn-add-capture');
  const btnAddImport = el.querySelector('#btn-add-import');
  const btnClearAll = el.querySelector('#btn-clear-all');

  const stepCamera = el.querySelector('#step-camera');
  const stepLoading = el.querySelector('#step-loading');
  const stepReview = el.querySelector('#step-review');

  const fieldsDisplayContainer = el.querySelector('#fields-display-container');
  const fieldsEditContainer = el.querySelector('#fields-edit-container');
  const reviewPhotosBar = el.querySelector('#review-photos-bar');
  const btnToggleEdit = el.querySelector('#btn-toggle-edit');
  const btnToggleEditText = el.querySelector('#btn-toggle-edit-text');
  const btnSaveConfirm = el.querySelector('#btn-save-confirm');
  const btnCancelDraft = el.querySelector('#btn-cancel-draft');
  const editAttributesList = el.querySelector('#edit-attributes-list');
  const btnAddAttribute = el.querySelector('#btn-add-attribute');

  const editName = el.querySelector('#edit-name');
  const editBrand = el.querySelector('#edit-brand');
  const editModel = el.querySelector('#edit-model');
  const editCategory = el.querySelector('#edit-category');
  const editCondition = el.querySelector('#edit-condition');
  const editDescriptionList = el.querySelector('#edit-description-list');
  const descriptionChoiceHint = el.querySelector('#description-choice-hint');
  const btnAddDescription = el.querySelector('#btn-add-description');
  const editIdentifiersList = el.querySelector('#edit-identifiers-list');

  const inspectorModal = el.querySelector('#inspector-modal');
  const inspectorImg = el.querySelector('#inspector-img');
  const btnCloseInspector = el.querySelector('#btn-close-inspector');

  // 觸控（多半是手機）用「從相簿匯入」；桌面上「選擇照片」較中性。
  // DOM 掛載後才替換（掛載前的 isConnected 為 false，先照預設文案）。
  const isTouchDevice = () => (
    typeof window.matchMedia === 'function'
    && window.matchMedia('(pointer: coarse)').matches
  );
  function renderEntryLabels() {
    if (!el.isConnected) return;
    btnImportText.textContent = isTouchDevice()
      ? t('capture.btnImportMobile')
      : t('capture.btnImport');
  }

  // 兩個入口互相獨立：拍照走 capture="environment" 的輸入框，匯入走
  // 不帶 capture 的 multiple 檔案輸入框 —— 使用者不會誤以為只能拍照、
  // 或只能選已有的照片。
  btnCapturePhoto.addEventListener('click', () => captureInput.click());
  btnImportPhotos.addEventListener('click', () => importInput.click());
  btnAddCapture.addEventListener('click', () => captureInput.click());
  btnAddImport.addEventListener('click', () => importInput.click());

  // Drag and drop handlers（桌面拖放匯入；與兩個入口共用 appendFiles）
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
      appendFiles(Array.from(e.dataTransfer.files), 'import');
    }
  });

  // 取消選取不會觸發 change —— 先前已選的照片永遠保留；重設 value 只
  // 發生在確實讀到檔案之後（同一張照片可以再選一次）。
  captureInput.addEventListener('change', () => {
    appendFiles(Array.from(captureInput.files || []), 'capture');
    captureInput.value = '';
  });

  importInput.addEventListener('change', () => {
    appendFiles(Array.from(importInput.files || []), 'import');
    importInput.value = '';
  });

  // 選取中的伺服器預覽請求數（HEIC／HEIF 需要伺服器解碼成 JPEG）。
  // >0 時不允許開始 AI 整理 —— 避免這批檔案還沒進托盤就被上傳流程漏掉。
  let previewPending = 0;
  // 清空／離開頁面時遞增：仍在飛行的預覽結果一律丟棄，不復活已清掉的選取。
  let appendEpoch = 0;

  function updateOrganizeAvailability() {
    btnStartOrganize.disabled = organizeBusy || previewPending > 0;
  }

  async function appendFiles(newFiles, origin = 'import') {
    if (!newFiles || newFiles.length === 0) return;
    // 格式分流（web/core/photoFiles.js）：HEIC／HEIF 不再於選取時一律
    // 拒收 —— 先向伺服器取得 JPEG 預覽（原始 File 保留給正式上傳），
    // 取不到預覽就明確拒絕該檔、不讓它進入待整理清單（不靜默丟棄、
    // 不假裝支援）；其餘格式沿用既有本機 object URL 流程。
    const { valid, unsupported } = partitionImageFiles(newFiles);
    if (unsupported.length > 0) {
      showToast(t('capture.unsupportedFormat'));
    }
    if (valid.length === 0) return;

    // 追加：保留既有照片（不整批清空），新照片接在後面。
    for (const file of valid) {
      if (!isHeicImageFile(file)) {
        const url = URL.createObjectURL(file);
        capturedFiles.push({ file, url, origin });
        renderTray();
        continue;
      }

      const epoch = appendEpoch;
      previewPending += 1;
      updateOrganizeAvailability();
      try {
        const blob = await api.previewInboxPhoto(file);
        if (epoch !== appendEpoch) return;  // 期間已清空／離開：丟棄結果
        const url = URL.createObjectURL(blob);
        // 正式上傳用的原始 File 原封不動；url 只是伺服器產生的 JPEG 預覽。
        capturedFiles.push({ file, url, origin });
      } catch (err) {
        console.warn('HEIC preview failed:', file.name, err);
        showToast(t('capture.heicPreviewFailed', { name: file.name }));
      } finally {
        previewPending -= 1;
        updateOrganizeAvailability();
      }
      renderTray();
    }
  }

  function renderTray() {
    // Remove old thumbnails, keep the add-action row
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

      // 前端預覽兜底：無法解碼的圖（例如瀏覽器不支援的格式）不能靜默
      // 卡在托盤裡——移除該張並明確告知，其餘照片不受影響。
      thumb.querySelector('img').addEventListener('error', () => {
        const currentIndex = capturedFiles.indexOf(item);
        if (currentIndex === -1) return;
        URL.revokeObjectURL(item.url);
        capturedFiles.splice(currentIndex, 1);
        showToast(t('capture.previewUnsupported'));
        renderTray();
      });

      thumb.querySelector('.tray-item-remove').addEventListener('click', (e) => {
        e.stopPropagation();
        URL.revokeObjectURL(item.url);
        capturedFiles.splice(index, 1);
        renderTray();
      });

      trayGrid.appendChild(thumb);
    });
  }

  btnClearAll.addEventListener('click', () => {
    appendEpoch += 1;  // 丟棄仍在飛行的 HEIC 預覽結果
    capturedFiles.forEach(f => URL.revokeObjectURL(f.url));
    capturedFiles = [];
    renderTray();
  });

  // 清理本次上傳的 inbox 暫存檔。冪等：已不在（重複清理、已被 intake
  // 歸檔）不算錯誤；失敗只警告，不假裝清乾淨。
  async function discardStagedFiles() {
    if (stagedConsumed || pendingInboxFiles.length === 0) return;
    try {
      await api.discardInboxFiles(pendingInboxFiles);
      pendingInboxFiles = [];
    } catch (err) {
      console.warn('Discard staged inbox files failed:', err);
      showToast(t('capture.discardFailed'));
    }
  }

  // Start Organize Flow
  btnStartOrganize.addEventListener('click', async () => {
    // previewPending：HEIC／HEIF 的伺服器預覽還在產生時不得開始 ——
    // 否則那些檔案還沒進 capturedFiles 就被這輪上傳漏掉。
    if (capturedFiles.length === 0 || organizeBusy || previewPending > 0) return;

    organizeBusy = true;
    updateOrganizeAvailability();

    // Switch to Loading View
    stepCamera.style.display = 'none';
    stepLoading.style.display = 'block';

    try {
      // 上一次嘗試若停在中途（上傳成功但分析失敗），先清掉暫存檔再重傳，
      // 避免 inbox 累積重複檔案。
      await discardStagedFiles();

      // Step 1: Upload photos to Inbox（只落盤，不建任何紀錄）
      const rawFiles = capturedFiles.map(c => c.file);
      const uploadRes = await api.uploadInboxPhotos(rawFiles);
      pendingInboxFiles = (Array.isArray(uploadRes.staged) && uploadRes.staged.length)
        ? uploadRes.staged
        : uploadRes.entries.map(e => e.relative);

      // Step 2: Draft analysis（不建立任何紀錄）
      let draft = { model: '', suggestions: [] };
      try {
        draft = await api.analyzeDraft(pendingInboxFiles);
      } catch (aiErr) {
        console.warn('AI draft analysis failed:', aiErr);
        // Non-fatal：沒有 key／provider 故障 → 手動填寫後照樣可以存。
      }
      draftModel = draft.model || '';
      currentSuggestions = draft.suggestions || [];
      currentItemId = null;
      stagedConsumed = false;
      saveCompleted = false;
      createdSuggestionIds.clear();
      appliedSuggestionIds.clear();
      rejectedSuggestionIds.clear();
      identifierDeletes.length = 0;
      attributeAppliedKeys.clear();
      archivedIdByOrigName = new Map();

      // Step 3: Show Review View（草稿的來源照片用本機 blob URL 對應）
      photoUrlById = new Map(capturedFiles.map((c, i) => [i, c.url]));
      stepLoading.style.display = 'none';
      stepReview.style.display = 'block';
      renderReviewScreen();
    } catch (err) {
      console.error('Capture pipeline failed:', err);
      showToast(`${t('capture.uploadError')}: ${err.message}`);
      stepLoading.style.display = 'none';
      stepCamera.style.display = 'block';
    } finally {
      organizeBusy = false;
      updateOrganizeAvailability();
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

    // 固定欄位：沿用原本的萃取（最後一筆同欄位建議勝出，與存檔順序一致）。
    extracted = {
      name: '',
      brand: '',
      model: '',
      category: '',
      condition: '',
    };
    confidences = {};

    // 動態屬性（attribute:<key>，含 attribute:description）全部收進
    // attributeRows；識別碼（serial／imei／barcode）全部收進 identifierRows。
    // 舊版只認固定欄位，這些已經產生的建議會在使用者看不到的情況下被
    // 存檔流程默默套用 —— 現在全部先呈現、可修改、可移除，再依使用者
    // 最後確認的內容保存。描述（description）可能有多筆候選（同一欄位
    // 在不同照片讀到不同值），由使用者在審閱時明確選擇要保存的一筆。
    attributeRows = [];
    identifierRows = [];

    currentSuggestions.forEach((s, index) => {
      if (s.field.startsWith('attribute:')) {
        attributeRows.push({
          key: s.field.slice('attribute:'.length),
          value: s.value,
          original: s.value,
          confidence: s.confidence,
          sourcePhotoIndex: s.source_photo_index,
          draftIndex: index,
          // 描述候選的明確選擇（radio）；其他屬性不使用。
          isPrimary: false,
          // 曾實際寫入正式紀錄的值（重試時要真的清除用）；accept／PATCH 後更新。
          appliedValue: null,
        });
      } else if (s.field.startsWith('identifier:')) {
        identifierRows.push({
          kind: s.field.slice('identifier:'.length),
          value: s.value,
          original: s.value,
          appliedValue: null,
          confidence: s.confidence,
          sourcePhotoIndex: s.source_photo_index,
          draftIndex: index,
        });
      } else if (s.field === 'name') {
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
      }
    });

    // 沒有 AI 序號時，仍提供一列手動序號（沿用舊版可直接輸入序號的能力）。
    if (!identifierRows.some(r => r.kind === 'serial')) {
      identifierRows.push({
        kind: 'serial',
        value: '',
        original: null,
        appliedValue: null,
        confidence: null,
        sourcePhotoIndex: null,
        draftIndex: null,
      });
    }

    // 描述候選：只有一筆時即為要保存的描述（免選擇）；多筆時不預先選擇 ——
    // 不沉默擇一，由使用者明確指定（未選取的不會保存，建議保留原值追溯）。
    const descriptionRows = attributeRows.filter(r => r.key === 'description');
    if (descriptionRows.length === 1) {
      descriptionRows[0].isPrimary = true;
    }

    // Set initial edit inputs
    editName.value = extracted.name || '';
    editBrand.value = extracted.brand || '';
    editModel.value = extracted.model || '';
    editCategory.value = extracted.category || '';
    editCondition.value = extracted.condition || '';
    renderDescriptionEditRows();

    renderAttributeEditRows();
    renderIdentifierEditRows();
    renderDisplayFields();
  }

  // 目前編輯輸入框的固定欄位值（閱讀模式顯示與存檔都以此為準）。
  function currentReviewValues() {
    return {
      name: editName.value.trim(),
      brand: editBrand.value.trim(),
      model: editModel.value.trim(),
      category: editCategory.value.trim(),
      condition: editCondition.value.trim(),
    };
  }

  // 閱讀模式：以標題與描述為主要入口，列出所有有值的內容（空值不佔位）。
  function renderDisplayFields() {
    fieldsDisplayContainer.innerHTML = '';
    const values = currentReviewValues();

    const hasAny = Object.values(values).some(Boolean)
      || attributeRows.some(r => r.value.trim());
    if (!hasAny) {
      // 沒有 AI 欄位（沒有 key／AI 失敗／純風景）：仍可修改或直接存。
      fieldsDisplayContainer.innerHTML = `
        <div style="background: var(--bg-subtle); padding: 14px; border-radius: var(--radius-md); font-size: 0.9rem; color: var(--text-secondary); line-height: 1.5;">
          ${t('capture.noFieldAlert')}
        </div>
      `;
      return;
    }

    // 使用者改過的值標「自訂」；沒改的照原信心水準標「看見／推測」。
    const fixedBadge = (value, aiValue, confidence) => ({
      confidence,
      custom: Boolean(value) && value !== (aiValue || ''),
    });

    // 1. 標題
    if (values.name) {
      fieldsDisplayContainer.appendChild(createFieldRow(
        t('detail.fieldName'), values.name,
        fixedBadge(values.name, extracted.name, confidences.name)));
    }

    // 2. 描述（閱讀主入口）：一筆時直接呈現；多筆候選時全部列出 ——
    //    已選取的標「主要描述」、未選取的標「未採用（不會保存）」，
    //    尚未選擇時提示到「修改」中選擇（不得沉默擇一）。
    const descriptionRows = attributeRows.filter(
      r => r.key === 'description' && r.value.trim());
    if (descriptionRows.length === 1) {
      fieldsDisplayContainer.appendChild(createFieldRow(
        t('capture.descriptionLabel'), descriptionRows[0].value.trim(),
        { confidence: descriptionRows[0].confidence,
          custom: isRowCustom(descriptionRows[0]), paragraph: true }));
    } else if (descriptionRows.length > 1) {
      const chosen = chosenDescriptionRow();
      descriptionRows.forEach((row, index) => {
        const isChosen = row === chosen;
        const tags = [];
        if (row.sourcePhotoIndex !== null && row.sourcePhotoIndex !== undefined) {
          tags.push({ text: `📷 ${row.sourcePhotoIndex + 1}` });
        }
        if (isChosen) {
          tags.push({ text: t('capture.descriptionPrimary') });
        } else if (chosen) {
          tags.push({ text: t('capture.descriptionNotUsed'), muted: true });
        } else {
          tags.push({ text: t('capture.descriptionCandidate'), muted: true });
        }
        fieldsDisplayContainer.appendChild(createFieldRow(
          `${t('capture.descriptionLabel')} ${index + 1}`, row.value.trim(),
          { confidence: row.confidence, custom: isRowCustom(row),
            paragraph: true, tags, muted: !isChosen }));
      });
      if (!chosen) {
        const hint = document.createElement('div');
        hint.className = 'description-choice-hint';
        hint.textContent = t('capture.descriptionMultiHint', { n: descriptionRows.length });
        fieldsDisplayContainer.appendChild(hint);
      }
    }

    // 3. 品牌 / 型號
    if (values.brand || values.model) {
      const bmVal = [values.brand, values.model].filter(Boolean).join(' · ');
      const bmConf = Math.min(confidences.brand ?? 1, confidences.model ?? 1);
      const bmCustom = (values.brand && values.brand !== (extracted.brand || ''))
        || (values.model && values.model !== (extracted.model || ''));
      fieldsDisplayContainer.appendChild(createFieldRow(
        `${t('detail.fieldBrand')} / ${t('detail.fieldModel')}`, bmVal,
        { confidence: bmConf, custom: Boolean(bmCustom) }));
    }

    // 4. 分類
    if (values.category) {
      fieldsDisplayContainer.appendChild(createFieldRow(
        t('detail.fieldCategory'), values.category,
        fixedBadge(values.category, extracted.category, confidences.category)));
    }

    // 5. 識別碼（序號／IMEI／條碼；AI 來源的序號可查閱來源照片）
    identifierRows.forEach(row => {
      const value = row.value.trim();
      if (!value) return;
      const identifierRow = createFieldRow(
        row.kind.toUpperCase(), value,
        { confidence: row.confidence, mono: true, custom: isIdentifierCustom(row) });
      if (row.sourcePhotoIndex !== null && row.sourcePhotoIndex !== undefined) {
        const labelGroup = identifierRow.querySelector('.ai-field-label-group');
        const inspectBtn = document.createElement('button');
        inspectBtn.type = 'button';
        inspectBtn.className = 'icon-btn';
        inspectBtn.style.padding = '2px 8px';
        inspectBtn.style.fontSize = '0.78rem';
        inspectBtn.style.background = 'var(--bg-subtle)';
        inspectBtn.style.color = 'var(--text-secondary)';
        inspectBtn.innerHTML = `🔍 ${t('capture.inspectPhoto')}`;
        inspectBtn.addEventListener('click', () => {
          // 草稿索引直接對應本機拍攝順序的照片（審閱階段還沒有後端 ID）；
          // 查不到才退回第一張。
          const targetPhoto = photoUrlById.get(row.sourcePhotoIndex)
            || capturedFiles[0]?.url;
          if (targetPhoto) {
            inspectorImg.src = targetPhoto;
            inspectorModal.style.display = 'flex';
          }
        });
        labelGroup.appendChild(inspectBtn);
      }
      fieldsDisplayContainer.appendChild(identifierRow);
    });

    // 6. 外觀備註
    if (values.condition) {
      fieldsDisplayContainer.appendChild(createFieldRow(
        t('detail.fieldCondition'), values.condition,
        fixedBadge(values.condition, extracted.condition, confidences.condition)));
    }

    // 7. 其他動態屬性（補充屬性）
    const extraAttributes = attributeRows.filter(
      r => r.key !== 'description' && r.value.trim());
    if (extraAttributes.length > 0) {
      const section = document.createElement('div');
      section.className = 'ai-field-section-label';
      section.textContent = t('capture.attributesSection');
      fieldsDisplayContainer.appendChild(section);

      extraAttributes.forEach(row => {
        fieldsDisplayContainer.appendChild(createFieldRow(
          row.key, row.value.trim(),
          { confidence: row.confidence, custom: isRowCustom(row) }));
      });
    }
  }

  function isRowCustom(row) {
    if (!row.value.trim()) return false;
    return row.draftIndex === null || row.value.trim() !== (row.original || '');
  }

  function isIdentifierCustom(row) {
    if (!row.value.trim()) return false;
    return row.draftIndex === null || row.value.trim() !== (row.original || '').trim();
  }

  // 編輯模式：識別碼列（每個 AI 建議一列＋手動序號列）。值可修改；
  // AI 來源的列與已套用過的列可移除 —— 移除已套用的值會在存檔時真的刪除。
  function renderIdentifierEditRows() {
    editIdentifiersList.innerHTML = '';
    identifierRows.forEach(row => {
      const wrap = document.createElement('div');
      wrap.style.cssText = 'display: flex; gap: 8px; align-items: center; margin-bottom: 8px;';

      const label = document.createElement('span');
      label.className = 'ai-field-label';
      label.style.flex = '0 0 36%';
      label.textContent = row.kind.toUpperCase();
      wrap.appendChild(label);

      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'ai-edit-input';
      input.style.flex = '1';
      input.placeholder = row.kind === 'serial'
        ? t('capture.serialPlaceholder')
        : row.kind.toUpperCase();
      input.value = row.value;
      input.addEventListener('input', () => { row.value = input.value; });
      wrap.appendChild(input);

      if (row.draftIndex !== null || row.appliedValue) {
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'icon-btn';
        removeBtn.title = t('capture.removeIdentifier');
        removeBtn.innerHTML = '✕';
        removeBtn.addEventListener('click', () => {
          // 已套用過的舊值排入刪除清單：重試時真的從紀錄移除。
          if (row.appliedValue) {
            identifierDeletes.push({ kind: row.kind, value: row.appliedValue });
          }
          identifierRows = identifierRows.filter(entry => entry !== row);
          renderIdentifierEditRows();
        });
        wrap.appendChild(removeBtn);
      }

      editIdentifiersList.appendChild(wrap);
    });
  }

  // 目前會被保存的描述列：多筆有內容的候選時，必須是使用者明確選取的一筆；
  // 只有一筆候選時即為該筆。null 表示沒有要保存的描述。
  function chosenDescriptionRow() {
    const candidates = attributeRows.filter(
      r => r.key === 'description' && r.value.trim());
    if (candidates.length === 0) return null;
    return candidates.find(r => r.isPrimary)
      || (candidates.length === 1 ? candidates[0] : null);
  }

  // 編輯模式：描述候選列。每一筆 AI 描述建議都必須看得見、可修改、可移除
  // —— 舊版只顯示第一筆、其餘被排除在介面外，驗證卻檢查它們（存檔被
  // 阻止又無法在介面上修正的死結）。多筆候選時以 radio 明確選擇要保存
  // 的一筆；未選取的不會保存（存檔時標為未採用，保留 AI 原值、來源照片、
  // 模型與信心的追溯）。
  function renderDescriptionEditRows() {
    editDescriptionList.innerHTML = '';
    const rows = attributeRows.filter(r => r.key === 'description');
    const showChoice = rows.length > 1;

    rows.forEach((row, index) => {
      const wrap = document.createElement('div');
      wrap.className = 'description-candidate-row';
      wrap.style.cssText = 'display: flex; gap: 8px; align-items: flex-start; margin-bottom: 8px;';

      if (showChoice) {
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = 'description-primary';
        radio.className = 'description-primary-radio';
        radio.checked = Boolean(row.isPrimary);
        radio.title = t('capture.descriptionSetPrimary');
        radio.setAttribute('aria-label', t('capture.descriptionSetPrimary'));
        radio.style.cssText = 'margin-top: 12px; flex: 0 0 auto;';
        radio.addEventListener('change', () => {
          rows.forEach(entry => { entry.isPrimary = (entry === row); });
          renderDescriptionEditRows();
        });
        wrap.appendChild(radio);
      }

      const labelGroup = document.createElement('div');
      labelGroup.style.cssText = 'flex: 0 0 auto; display: flex; flex-direction: column; gap: 4px; max-width: 30%;';
      const label = document.createElement('span');
      label.className = 'ai-field-label';
      label.textContent = showChoice
        ? `${t('capture.descriptionLabel')} ${index + 1}`
        : t('capture.descriptionLabel');
      labelGroup.appendChild(label);
      if (row.sourcePhotoIndex !== null && row.sourcePhotoIndex !== undefined) {
        const inspectBtn = document.createElement('button');
        inspectBtn.type = 'button';
        inspectBtn.className = 'icon-btn';
        inspectBtn.style.cssText = 'padding: 2px 8px; font-size: 0.78rem; width: fit-content; background: var(--bg-subtle); color: var(--text-secondary);';
        inspectBtn.title = t('capture.inspectPhoto');
        inspectBtn.setAttribute('aria-label', t('capture.inspectPhoto'));
        inspectBtn.textContent = `🔍 📷 ${row.sourcePhotoIndex + 1}`;
        inspectBtn.addEventListener('click', () => {
          const targetPhoto = photoUrlById.get(row.sourcePhotoIndex)
            || capturedFiles[0]?.url;
          if (targetPhoto) {
            inspectorImg.src = targetPhoto;
            inspectorModal.style.display = 'flex';
          }
        });
        labelGroup.appendChild(inspectBtn);
      }
      wrap.appendChild(labelGroup);

      const valueInput = document.createElement('textarea');
      valueInput.className = 'ai-edit-input';
      valueInput.rows = 2;
      valueInput.style.cssText = 'flex: 1; resize: vertical;';
      valueInput.placeholder = t('capture.descriptionPlaceholder');
      valueInput.value = row.value;
      valueInput.addEventListener('input', () => { row.value = valueInput.value; });
      wrap.appendChild(valueInput);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'icon-btn';
      removeBtn.style.marginTop = '12px';
      removeBtn.title = t('capture.removeDescription');
      removeBtn.innerHTML = '✕';
      removeBtn.addEventListener('click', () => {
        // 曾寫入正式紀錄的舊值：記下來，重試存檔時真的從紀錄清除
        // （只清除確實是我們寫入的值，不會誤刪後來選用的新描述）。
        if (row.appliedValue) descriptionDeletes.push(row.appliedValue);
        attributeRows = attributeRows.filter(entry => entry !== row);
        renderDescriptionEditRows();
      });
      wrap.appendChild(removeBtn);

      editDescriptionList.appendChild(wrap);
    });

    const candidates = rows.filter(r => r.value.trim());
    const unresolved = candidates.length > 1
      && !candidates.some(r => r.isPrimary);
    descriptionChoiceHint.style.display = unresolved ? 'block' : 'none';
    descriptionChoiceHint.textContent = unresolved
      ? t('capture.descriptionChoiceHint')
      : '';
  }

  // 編輯模式：動態屬性的可編輯列（description 有專屬的候選列區塊，
  // 不重複列出）。
  function renderAttributeEditRows() {
    editAttributesList.innerHTML = '';
    attributeRows
      .filter(row => row.key !== 'description')
      .forEach(row => editAttributesList.appendChild(createAttributeEditRow(row)));
  }

  function createAttributeEditRow(row) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display: flex; gap: 8px; align-items: center; margin-bottom: 8px;';

    if (row.draftIndex === null) {
      // 使用者新增的屬性：key 可編輯。
      const keyInput = document.createElement('input');
      keyInput.type = 'text';
      keyInput.className = 'ai-edit-input';
      keyInput.style.flex = '0 0 36%';
      keyInput.placeholder = t('capture.attributeKeyPlaceholder');
      keyInput.value = row.key;
      keyInput.addEventListener('input', () => { row.key = keyInput.value; });
      wrap.appendChild(keyInput);
    } else {
      const label = document.createElement('span');
      label.className = 'ai-field-label';
      label.style.flex = '0 0 36%';
      label.style.overflow = 'hidden';
      label.style.textOverflow = 'ellipsis';
      label.textContent = row.key;
      wrap.appendChild(label);
    }

    const valueInput = document.createElement('input');
    valueInput.type = 'text';
    valueInput.className = 'ai-edit-input';
    valueInput.style.flex = '1';
    valueInput.placeholder = t('capture.attributeValuePlaceholder');
    valueInput.value = row.value;
    valueInput.addEventListener('input', () => { row.value = valueInput.value; });
    wrap.appendChild(valueInput);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'icon-btn';
    removeBtn.title = t('capture.removeAttribute');
    removeBtn.innerHTML = '✕';
    removeBtn.addEventListener('click', () => {
      attributeRows = attributeRows.filter(entry => entry !== row);
      renderAttributeEditRows();
    });
    wrap.appendChild(removeBtn);
    return wrap;
  }

  // 使用者自行新增描述列（沒有 AI 描述時也能自行填寫；新列即為選取狀態，
  // 原有描述列的選取會讓給新列）。
  btnAddDescription.addEventListener('click', () => {
    attributeRows.forEach(entry => {
      if (entry.key === 'description') entry.isPrimary = false;
    });
    attributeRows.push({
      key: 'description',
      value: '',
      original: '',
      confidence: null,
      sourcePhotoIndex: null,
      draftIndex: null,
      isPrimary: true,
      appliedValue: null,
    });
    renderDescriptionEditRows();
  });

  btnAddAttribute.addEventListener('click', () => {
    attributeRows.push({
      key: '',
      value: '',
      original: '',
      confidence: null,
      sourcePhotoIndex: null,
      draftIndex: null,
    });
    renderAttributeEditRows();
  });

   function createFieldRow(label, value, { confidence = null, mono = false, custom = false, paragraph = false, tags = [], muted = false } = {}) {
     const row = document.createElement('div');
     row.className = `ai-field-row${muted ? ' is-muted' : ''}`;

     // 規則：區分看見 (>= 0.85) 與推測 (< 0.85)；confidence=null 無信心值；使用者改過的值標「自訂」。
     const isCertain = confidence !== undefined && confidence !== null && confidence >= 0.85;
     const hasNoConfidence = confidence === null || confidence === undefined;
     const badgeHtml = custom
       ? `<span class="badge-custom">✎ ${t('capture.badgeCustom')}</span>`
       : hasNoConfidence
         ? `<span class="badge-unrated">🔍 ${t('capture.badgeUnrated')}</span>`
         : isCertain
           ? `<span class="badge-seen">✓ ${t('capture.badgeSeen')}</span>`
           : `<span class="badge-guess">~ ${t('capture.badgeInferred')}</span>`;
     const tagsHtml = tags
       .map(tag => `<span class="${tag.muted ? 'badge-muted' : 'badge-custom'}">${escapeHtml(tag.text)}</span>`)
       .join('');

     const valueStyle = paragraph
       ? 'font-weight: normal; font-size: 0.95rem; line-height: 1.6; white-space: pre-wrap;'
       : '';
     const valueClass = `ai-field-value ${mono ? 'mono' : ''}${!isCertain && !hasNoConfidence ? ' is-inferred' : ''}`;
     row.innerHTML = `
       <div class="ai-field-label-group">
         <span class="ai-field-label">${escapeHtml(label)}</span>
         ${badgeHtml}
         ${tagsHtml}
       </div>
       <div class="${valueClass}" style="${valueStyle}">${escapeHtml(value)}</div>
     `;
     return row;
   }

  // Toggle Edit Mode（閱讀↔修改；修改入口在內容下方操作區）
  function setEditMode(next) {
    isEditMode = next;
    fieldsEditContainer.style.display = isEditMode ? 'flex' : 'none';
    fieldsDisplayContainer.style.display = isEditMode ? 'none' : 'flex';
    if (isEditMode) {
      renderDescriptionEditRows();
      renderAttributeEditRows();
      renderIdentifierEditRows();
    } else {
      // 回到閱讀模式：顯示目前（可能已修改）的內容，而不是舊的 AI 值。
      renderDisplayFields();
    }
    btnToggleEditText.textContent = isEditMode
      ? `✓ ${t('app.confirm')}`
      : `✎ ${t('capture.btnEdit')}`;
  }

  btnToggleEdit.addEventListener('click', () => setEditMode(!isEditMode));

  // Close inspector
  btnCloseInspector.addEventListener('click', () => {
    inspectorModal.style.display = 'none';
  });
  inspectorModal.addEventListener('click', (e) => {
    if (e.target === inspectorModal) inspectorModal.style.display = 'none';
  });

  // 存檔前的本地驗證：必須在第一次呼叫 api.intake 之前完成 ——
  // 驗證失敗時不建立任何正式紀錄（不留半套）。回傳錯誤訊息或 null。
  const ATTRIBUTE_KEY_RE = /^[a-z][a-z0-9_]{0,39}$/;

  function validateDraftForSave() {
    // 1. name 是必要的紀錄標題。
    if (!editName.value.trim()) {
      return t('capture.nameRequired');
    }
    // 2. 使用者新增的屬性列：名稱不可空白、必須符合既有 key 規則。
    for (const row of attributeRows) {
      const key = row.key.trim();
      if (!row.value.trim()) continue;  // 沒內容的列不會保存，不需要驗證
      if (!key) {
        return t('capture.attributeKeyMissing');
      }
      if (row.draftIndex === null && !ATTRIBUTE_KEY_RE.test(key)) {
        return t('capture.attributeKeyInvalid', { key });
      }
    }
    // 3. 描述候選：多筆有內容的候選時必須明確選擇要保存的一筆 ——
    //    不得沉默擇一，也不得讓使用者在看不見的列上被卡住（每一列都能
    //    在編輯模式中操作，見 renderDescriptionEditRows）。未選取的候選
    //    保存時標為未採用，AI 原值與來源追溯完整保留。
    const descriptionCandidates = attributeRows.filter(
      r => r.key.trim() === 'description' && r.value.trim());
    if (descriptionCandidates.length > 1
        && descriptionCandidates.filter(r => r.isPrimary).length !== 1) {
      return t('capture.descriptionChooseRequired');
    }
    // 4. 其餘屬性不得有重複 key（description 由上面的選擇機制解析；
    //    含使用者自行新增、與 AI 既有列同名的情況）。
    const seen = new Set();
    for (const row of attributeRows) {
      const key = row.key.trim();
      if (!key || !row.value.trim()) continue;
      if (key === 'description') continue;
      if (seen.has(key)) {
        return t('capture.attributeKeyDuplicate', { key });
      }
      seen.add(key);
    }
    return null;
  }

  // 依 (kind, value) 找出已存在於紀錄中的識別碼並刪除（重試的清理步驟；
  // 找不到視為已完成）。值取自我們自己先前的寫入，逐字比對即可。
  async function deleteIdentifierByKindValue(kind, value) {
    const data = await api.getItem(currentItemId);
    const matches = (data.identifiers || []).filter(
      identifier => identifier.kind === kind && identifier.value === value);
    for (const identifier of matches) {
      await api.deleteIdentifier(identifier.id);
    }
  }

  // Confirm and Save (核心動作：✓ 存起來)
  //
  // 「確認儲存才建檔」：通過本地驗證後才呼叫 intake —— 正式 Item、
  // Observation、photos 在這一刻誕生。AI 草稿接著落成正式建議
  // （保留 model／confidence／來源照片追溯）：與使用者最終輸入等值才
  // accept；被清空／修改／移除的一律 reject（建議永遠保存 AI 原值，
  // 使用者的修改透過 PATCH 落地，不冒充 AI 判讀）。任何一步失敗都要
  // 誠實回報，且重試不得重複套用或留下舊值：
  // intake 只跑一次；已接受的建議、已拒絕的建議、已套用的識別碼與
  // attributes 鍵都以區域狀態追蹤，後端同值 no-op 是第二道保險。
  btnSaveConfirm.addEventListener('click', async () => {
    if (saveBusy || saveCompleted) return;
    if (pendingInboxFiles.length === 0 && !currentItemId) return;

    // 本地驗證必須在 intake 之前（失敗不留任何正式紀錄）。
    const validationError = validateDraftForSave();
    if (validationError) {
      showToast(validationError);
      setEditMode(true);  // 直接進編輯模式讓使用者修正
      if (!editName.value.trim()) {
        editName.focus();
      } else if (validationError === t('capture.descriptionChooseRequired')) {
        // 多筆描述候選尚未選擇：把候選列帶到眼前（每一列都可修改／移除／選擇）。
        editDescriptionList.scrollIntoView({ block: 'center' });
        editDescriptionList.querySelector('input[type="radio"]')?.focus();
      }
      return;
    }

    saveBusy = true;
    btnSaveConfirm.disabled = true;
    btnSaveConfirm.innerHTML = `<span>${t('app.loading')}</span>`;

    const failures = [];
    // 描述候選的選擇快照：只有使用者選取的一筆會寫入主表；未選取的候選
    // 一律標為未採用（建議保留 AI 原值／來源照片／模型／信心追溯）。
    const chosenDescription = chosenDescriptionRow();

    try {
      // 0. 這一刻才建立正式紀錄（重試時跳過 —— intake 是全有全無，
      //    已成功就不重跑，避免重複建檔）。
      if (!currentItemId) {
        const intakeRes = await api.intake(pendingInboxFiles, 'intake');
        currentItemId = intakeRes.item_id;
        stagedConsumed = true;
        archivedIdByOrigName = new Map(
          (intakeRes.archived || [])
            .filter(p => p && p.id && p.orig_name)
            .map(p => [p.orig_name, p.id])
        );
      }

      // 1. AI 草稿逐筆落成正式建議，依「使用者最後確認的內容」決定
      //    接受或拒絕。建議一律用 draft.value（AI 原值）建立 —— 使用者
      //    修改過的值走 PATCH，不會被冒充成原始 AI 判讀。
      const fixedFinals = {
        name: editName.value.trim(),
        brand: editBrand.value.trim(),
        model: editModel.value.trim(),
        category: editCategory.value.trim(),
        condition: editCondition.value.trim(),
      };
      for (let index = 0; index < currentSuggestions.length; index++) {
        if (appliedSuggestionIds.has(index) || rejectedSuggestionIds.has(index)) continue;
        const draft = currentSuggestions[index];
        let decision;
        if (draft.field.startsWith('attribute:')) {
          const key = draft.field.slice('attribute:'.length);
          const row = attributeRows.find(r => r.draftIndex === index);
          const finalValue = row ? row.value.trim() : '';
          // 描述多筆候選：只有使用者選取的一筆可能被接受；未選取的一律
          // 標為未採用，絕不讓後面的候選默默覆蓋選取的值。
          const unchosenDescription = key === 'description' && finalValue
            && row !== chosenDescription;
          decision = !unchosenDescription && finalValue
            && finalValue === (row.original || '').trim()
            ? 'accept' : 'reject';
        } else if (draft.field.startsWith('identifier:')) {
          const row = identifierRows.find(r => r.draftIndex === index);
          const finalValue = row ? row.value.trim() : '';
          decision = finalValue && finalValue === (row.original || '').trim()
            ? 'accept' : 'reject';
        } else {
          const finalValue = fixedFinals[draft.field] ?? '';
          decision = finalValue && finalValue === String(draft.value).trim()
            ? 'accept' : 'reject';
        }
        try {
          let suggestionId = createdSuggestionIds.get(index);
          if (!suggestionId) {
            const sourcePhotoId = archivedIdByOrigName.get(
              capturedFiles[draft.source_photo_index]?.file.name
            ) || null;
            const created = await api.createSuggestion(currentItemId, {
              field: draft.field,
              value: draft.value,  // 永遠是 AI 原值
              confidence: draft.confidence ?? null,
              source: 'external',
              model_name: draftModel,
              source_photo_id: sourcePhotoId,
              actor: 'external',
            });
            suggestionId = created.id;
            createdSuggestionIds.set(index, suggestionId);
          }
          if (decision === 'accept') {
            await api.acceptSuggestion(suggestionId);
            appliedSuggestionIds.add(index);
            const row = draft.field.startsWith('identifier:')
              ? identifierRows.find(r => r.draftIndex === index)
              : attributeRows.find(r => r.draftIndex === index);
            if (row) row.appliedValue = row.original;
          } else {
            await api.rejectSuggestion(suggestionId);
            rejectedSuggestionIds.add(index);
          }
        } catch (err) {
          console.warn(`Could not finalize suggestion #${index}:`, err);
          failures.push({ what: draft.field, error: err });
        }
      }

      // 2. 固定欄位以使用者最終輸入為準（含空字串）：清空的欄位必須真的
      //    清掉 —— 先前部分成功套用的值不能殘留；同值 PATCH 是 no-op，
      //    重試不會重複變更。
      await api.patchItem(currentItemId, {
        name: fixedFinals.name,
        brand: fixedFinals.brand,
        model: fixedFinals.model,
        category: fixedFinals.category,
        condition: fixedFinals.condition,
      });

      // 3. 識別碼：先真的刪除「已套用但被改掉／移除」的舊值（不假裝已
      //    移除），再處理修改後的值與手動序號。
      for (const row of identifierRows) {
        const finalValue = row.value.trim();
        if (row.appliedValue && row.appliedValue !== finalValue) {
          try {
            await deleteIdentifierByKindValue(row.kind, row.appliedValue);
            row.appliedValue = null;
          } catch (err) {
            console.warn('Identifier cleanup failed:', err.message);
            failures.push({ what: `identifier:${row.kind}`, error: err });
          }
        }
      }
      for (let i = identifierDeletes.length - 1; i >= 0; i--) {
        const entry = identifierDeletes[i];
        try {
          await deleteIdentifierByKindValue(entry.kind, entry.value);
          identifierDeletes.splice(i, 1);
        } catch (err) {
          console.warn('Identifier cleanup failed:', err.message);
          failures.push({ what: `identifier:${entry.kind}`, error: err });
        }
      }
      for (const row of identifierRows) {
        const finalValue = row.value.trim();
        if (!finalValue) continue;
        const original = (row.original || '').trim();
        if (row.draftIndex !== null && finalValue === original) {
          continue;  // 未修改：由 accept 建立（或重試完成），不重複新增
        }
        if (row.appliedValue === finalValue) continue;  // 已套用，重試不重做
        try {
          await api.addIdentifier(currentItemId, { kind: row.kind, value: finalValue });
          row.appliedValue = finalValue;
        } catch (err) {
          // 同商品同 (kind, value) 已存在 = 重試時的等價成功。
          if (err && err.status === 409) {
            row.appliedValue = finalValue;
            continue;
          }
          console.warn('Identifier add failed:', err.message);
          failures.push({ what: `identifier:${row.kind}`, error: err });
        }
      }

      // 4. 動態屬性：把「使用者改過／移除／新增」的差異併進 GET 到的現值
      //    後寫回。PATCH 是整包取代語意，但內容是現值加減差異 —— 不動
      //    看不見的鍵、不用新值偷覆蓋；被移除的鍵是真的從紀錄刪除。
      //
      //    描述（attribute:description）另外處理：只有使用者選取的一筆
      //    算數，未選取的候選絕不寫入。先前部分保存曾寫入、但最後不被
      //    選取的描述，只在「現值確實是我們寫入的舊值」時清除（value-
      //    aware，不會誤刪剛選取的新描述）。
      const attributeSet = new Map();
      const attributeRemove = new Set();
      const finalDescription = chosenDescription
        ? chosenDescription.value.trim() : '';
      const descriptionRemovals = new Set();
      const noteDescriptionRemoval = (value) => {
        const stale = String(value || '').trim();
        if (stale && stale !== finalDescription) {
          descriptionRemovals.add(stale);
        }
      };

      for (let index = 0; index < currentSuggestions.length; index++) {
        const draft = currentSuggestions[index];
        if (!draft.field.startsWith('attribute:')) continue;
        const key = draft.field.slice('attribute:'.length);
        const row = attributeRows.find(r => r.draftIndex === index);
        const finalValue = row ? row.value.trim() : '';
        const original = (row ? (row.original || '') : String(draft.value || '')).trim();

        if (key === 'description') {
          if (row && row === chosenDescription) {
            // 選取的一筆：等值且仍可接受 → 由 accept 處理；否則 PATCH 落地
            //（使用者改過，或先前已遭拒絕、不可能再接受）。
            if (finalValue && finalValue === original
                && !rejectedSuggestionIds.has(index)) {
              continue;
            }
            attributeSet.set(key, finalValue);
          } else if (row && row.appliedValue) {
            // 未選取的候選（或已被清空）：曾寫入的舊值必須清除。
            noteDescriptionRemoval(row.appliedValue);
          }
          continue;
        }

        if (finalValue && finalValue === original) {
          // 等值：正常由 accept 處理；但若這筆建議已不可能再接受（例如
          // 先前因修改被拒絕、重試前又改回原值），最終值仍必須落地。
          if (rejectedSuggestionIds.has(index)) attributeSet.set(key, finalValue);
          continue;
        }
        if (finalValue) {
          attributeSet.set(key, finalValue);
        } else if (appliedSuggestionIds.has(index) || attributeAppliedKeys.has(key)) {
          attributeRemove.add(key);
        }
      }
      // 已被整列移除、但曾寫入正式紀錄的描述舊值（移除時記下的）。
      for (const value of descriptionDeletes) noteDescriptionRemoval(value);

      for (const row of attributeRows) {
        if (row.draftIndex !== null) continue;
        const key = row.key.trim();
        const value = row.value.trim();
        if (key === 'description') {
          // 使用者自行新增的描述列：只有選取的一列會保存。
          if (row === chosenDescription && value) attributeSet.set(key, value);
          continue;
        }
        if (key && value) attributeSet.set(key, value);
      }
      // 本次流程曾寫入、但最終內容裡已不存在的鍵（例如部分保存後使用者
      // 移除了自己新增的屬性列）→ 真的從紀錄刪除。
      for (const key of attributeAppliedKeys) {
        if (!attributeSet.has(key)) attributeRemove.add(key);
      }
      if (attributeSet.size > 0 || attributeRemove.size > 0
          || descriptionRemovals.size > 0) {
        try {
          const current = await api.getItem(currentItemId);
          const merged = { ...(current.item.attributes || {}) };
          for (const key of attributeRemove) delete merged[key];
          if (descriptionRemovals.size > 0 && !attributeSet.has('description')) {
            const currentDescription = merged['description'];
            if (typeof currentDescription === 'string'
                && descriptionRemovals.has(currentDescription.trim())) {
              delete merged['description'];
            }
          }
          for (const [key, value] of attributeSet) merged[key] = value;
          await api.patchItem(currentItemId, { attributes: merged });
          for (const key of attributeRemove) attributeAppliedKeys.delete(key);
          for (const key of attributeSet.keys()) {
            if (key === 'description') {
              if (chosenDescription) {
                chosenDescription.appliedValue = finalDescription;
              }
            } else {
              attributeAppliedKeys.add(key);
            }
          }
          descriptionDeletes.length = 0;
        } catch (err) {
          console.warn('Attribute reconcile failed:', err.message);
          failures.push({ what: t('capture.attributesSection'), error: err });
        }
      }

      if (failures.length === 0) {
        saveCompleted = true;
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
      saveBusy = false;
      btnSaveConfirm.disabled = false;
      btnSaveConfirm.innerHTML = `<span>✓ ${t('capture.btnSaveDirect')}</span>`;
    } catch (err) {
      // 硬失敗（例如 intake 或 PATCH 失敗）：intake 失敗時沒有任何正式
      // 紀錄，暫存檔仍在；PATCH 失敗時編輯的值沒有落地。留在原畫面重試。
      console.error('Failed to finalize item:', err);
      showToast(`${t('capture.saveError')}: ${err.message}`);
      saveBusy = false;
      btnSaveConfirm.disabled = false;
      btnSaveConfirm.innerHTML = `<span>✓ ${t('capture.btnSaveDirect')}</span>`;
    }
  });

  // 取消：不留下本次操作產生的任何正式資料。
  //
  // - 還沒按過存起來：只有 inbox 暫存檔 → 清掉即可（冪等）。
  // - 已按過存起來（intake 已建立紀錄，例如部分失敗後放棄）：
  //   紀錄完全是本次操作的產物 → void + purge 清乾淨（Phase 3 既有流程）。
  //   清理失敗時誠實警告（紀錄已進垃圾桶，可從那裡永久刪除），不假裝成功。
  let discardBusy = false;
  btnCancelDraft.addEventListener('click', async () => {
    if (discardBusy) return;
    discardBusy = true;

    try {
      if (currentItemId && !saveCompleted) {
        try {
          await api.voidItem(currentItemId);
          await api.purgeItem(currentItemId);
          showToast(t('capture.discardDone'));
        } catch (err) {
          console.warn('Discard created record failed:', err);
          showToast(t('capture.discardFailed'));
        }
        currentItemId = null;
      } else {
        await discardStagedFiles();
      }
    } finally {
      capturedFiles.forEach(f => URL.revokeObjectURL(f.url));
      capturedFiles = [];
      router.navigate('/');
    }
  });

  // 掛載後才依裝置替換匯入按鈕文案（觸控裝置顯示「從相簿匯入」）。
  // router 是把 view 掛進 #app 容器（web/app.js 的 router.init），不是
  // 直接掛在 body；#app 本來就是 body 的子節點，所以觀察 body 的
  // childList 永遠等不到這次插入。改為觀察實際的 #app 掛載容器，
  // 並以 subtree 涵蓋任何層級的插入；掛載確認後立刻停止觀察，不做
  // 長期 DOM 監視。#app 不存在時退回 body（同樣 subtree，仍能等到）。
  if (typeof MutationObserver === 'function') {
    let labelObserver = null;
    const stopObserving = () => {
      if (labelObserver) {
        labelObserver.disconnect();
        labelObserver = null;
      }
    };
    const applyLabelsWhenMounted = () => {
      // 其他插入（例如 toast）先到時不能誤判掛載完成：繼續等自己的
      // view 真的接上文件為止。
      if (!el.isConnected) return;
      stopObserving();
      renderEntryLabels();
    };
    if (el.isConnected) {
      renderEntryLabels();
    } else {
      const mountRoot = document.getElementById('app') || document.body;
      labelObserver = new MutationObserver(applyLabelsWhenMounted);
      labelObserver.observe(mountRoot, { childList: true, subtree: true });
    }
  }

  return {
    element: el,
    destroy() {
      appendEpoch += 1;  // 丟棄仍在飛行的 HEIC 預覽結果（不在已卸載的 DOM 上復活）
      // 離開頁面：清掉還沒被 intake 消化的暫存檔。審閱階段沒有任何
      // 正式紀錄；已按過「存起來」的紀錄（含部分失敗）不在此清理 ——
      // 那是使用者按下儲存的意圖，明確取消才捨棄。
      if (!saveBusy && !saveCompleted) {
        discardStagedFiles();
      }
      capturedFiles.forEach(f => URL.revokeObjectURL(f.url));
    },
  };
}
