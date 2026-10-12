/**
 * 照片輸入的格式分流（拍照與相簿／檔案匯入共用）。
 *
 * `accept="image/*"` 只是檔案選擇器的提示，並不能保證選到的每一種格式
 * 都能走完「預覽 → 上傳 → AI 分析」：
 *
 * - 瀏覽器預覽：HEIC／HEIF 只在 Safari 有原生解碼；Chrome／Edge／
 *   Firefox 選得到但無法渲染（縮圖會是破圖）。
 * - 後端：像素上限檢查只做 JPEG／PNG 的零解碼讀取，其他格式照收；
 *   AI 縮圖（shop/ai_client.encode_photo）用 Pillow 重編碼成 JPEG，
 *   HEIC 需要額外的插件才解得開，否則原樣 passthrough。
 *
 * 專案立場是零外部依賴、不用大型影像函式庫，所以 HEIC／HEIF 不假裝
 * 支援，在**選取當下**就明確分流、提示使用者（而不是匯入後才在預覽
 * 或分析時失敗）。其餘格式沿用既有流程；若瀏覽器事後仍無法預覽，
 * 由縮圖的 onerror 兜底（見 capture.js renderTray）。
 *
 * 判定只依 MIME 與副檔名 —— 這是保守的「接受或不接受」判斷，不是
 * 完整的格式驗證（檔頭 magic 檢查不在本輪範圍）。
 */

export const UNSUPPORTED_IMAGE_EXTENSIONS = Object.freeze(['heic', 'heif']);

function extensionOf(name) {
  const dot = String(name || '').lastIndexOf('.');
  return dot >= 0 ? String(name).slice(dot + 1).toLowerCase() : '';
}

export function isUnsupportedImageFile(file) {
  if (!file) return false;
  if (UNSUPPORTED_IMAGE_EXTENSIONS.includes(extensionOf(file.name))) return true;
  const type = String(file.type || '').toLowerCase();
  return type === 'image/heic' || type === 'image/heif';
}

export function isAcceptedImageFile(file) {
  if (!file) return false;
  if (isUnsupportedImageFile(file)) return false;
  if (String(file.type || '').toLowerCase().startsWith('image/')) return true;
  // 有些平台（尤其手機）會給空 MIME；用副檔名當退路。
  return /\.(jpe?g|png|webp|bmp|gif|avif)$/i.test(file.name || '');
}

/**
 * 把一批使用者選取／拖入的檔案分成兩組。
 * @returns {{valid: File[], unsupported: File[]}}
 */
export function partitionImageFiles(files) {
  const valid = [];
  const unsupported = [];
  for (const file of files || []) {
    if (isUnsupportedImageFile(file)) {
      unsupported.push(file);
    } else if (isAcceptedImageFile(file)) {
      valid.push(file);
    } else {
      unsupported.push(file);
    }
  }
  return { valid, unsupported };
}
