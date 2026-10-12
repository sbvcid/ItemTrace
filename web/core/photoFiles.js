/**
 * 照片輸入的格式分流（拍照與相簿／檔案匯入共用）。
 *
 * `accept="image/*"` 只是檔案選擇器的提示，並不能保證選到的每一種格式
 * 都能走完「預覽 → 上傳 → AI 分析」：
 *
 * - 瀏覽器預覽：HEIC／HEIF 只在 Safari 有原生解碼；Chrome／Edge／
 *   Firefox 選得到但無法渲染（縮圖會是破圖）。
 * - 後端：HEIC／HEIF 由伺服器解碼（pillow-heif，見 shop/heif.py）：
 *   選取時向 POST /api/inbox/preview 取得 JPEG 預覽；AI 分析與詳情頁
 *   也各自解碼成 JPEG。原始檔永不轉換、覆寫或遺失。
 *
 * 分流規則：
 * - HEIC／HEIF（依 MIME 或副檔名）：仍算「可匯入」，但必須先取得
 *   伺服器 JPEG 預覽（capture.js 負責）；取不到預覽就明確拒絕該檔。
 * - 其他 image/*（或常見副檔名）：沿用既有流程；若瀏覽器事後仍無法
 *   預覽，由縮圖的 onerror 兜底（見 capture.js renderTray）。
 * - 其餘一律列入不支援（明確提示，不靜默略過）。
 *
 * 判定只依 MIME 與副檔名 —— 這是保守的「接受或不接受」判斷，不是
 * 完整的格式驗證（檔頭 magic 檢查由後端解碼器負責）。
 */

export const HEIC_EXTENSIONS = Object.freeze(['heic', 'heif']);

function extensionOf(name) {
  const dot = String(name || '').lastIndexOf('.');
  return dot >= 0 ? String(name).slice(dot + 1).toLowerCase() : '';
}

/**
 * 是否為 HEIC／HEIF：瀏覽器多半無法直接預覽，需要伺服器 JPEG 預覽。
 * 原始 File 物件不受影響 —— 正式上傳仍用它（位元組原樣歸檔）。
 */
export function isHeicImageFile(file) {
  if (!file) return false;
  if (HEIC_EXTENSIONS.includes(extensionOf(file.name))) return true;
  const type = String(file.type || '').toLowerCase();
  return type === 'image/heic' || type === 'image/heif';
}

export function isAcceptedImageFile(file) {
  if (!file) return false;
  if (String(file.type || '').toLowerCase().startsWith('image/')) return true;
  // 有些平台（尤其手機）會給空 MIME；用副檔名當退路。
  return /\.(jpe?g|png|webp|bmp|gif|avif|heic|heif)$/i.test(file.name || '');
}

/**
 * 把一批使用者選取／拖入的檔案分成兩組。
 * @returns {{valid: File[], unsupported: File[]}} valid 含 HEIC／HEIF
 *   （它們仍需要伺服器預覽，見 capture.js）。
 */
export function partitionImageFiles(files) {
  const valid = [];
  const unsupported = [];
  for (const file of files || []) {
    if (isAcceptedImageFile(file)) {
      valid.push(file);
    } else {
      unsupported.push(file);
    }
  }
  return { valid, unsupported };
}
