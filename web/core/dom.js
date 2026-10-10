/**
 * 最小的 DOM 安全工具（SR-1／SECURITY-AUDIT F6）。
 *
 * 這個 SPA 用 innerHTML 拼版型；任何來自紀錄、AI 建議、上傳內容或
 * 錯誤訊息的「不可信字串」，進入版型前都必須先過 escapeHtml()。
 * 不要假設 AI 產出是安全的。
 */
export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
