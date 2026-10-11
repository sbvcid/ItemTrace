/**
 * ItemTrace V3 API Client
 *
 * Lightweight Fetch wrapper for communicating with the backend.
 *
 * 裝置授權（手機配對）：配對成功後權杖存在 localStorage，之後**每個**
 * API 呼叫都自動附加 `Authorization: Bearer`，使用者不需要手動貼上。
 * 另外伺服器會下一個 HttpOnly cookie，讓 `<img src="/files/…">` 這類
 * 不經過 fetch 的媒體請求也能通過認證。
 * 收到 401（權杖失效或已撤銷）時自動清除本機權杖 —— 下次載入會回到
 * 配對引導頁。
 */

const DEVICE_TOKEN_KEY = 'itemtrace.device.token';
const DEVICE_ID_KEY = 'itemtrace.device.id';
const DEVICE_NAME_KEY = 'itemtrace.device.name';

function readStorage(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (_) {
    return null;
  }
}

function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (_) {
    // 私密瀏覽等情況下 localStorage 可能不可用：不致命，cookie 仍可運作。
  }
}

function removeStorage(key) {
  try {
    window.localStorage.removeItem(key);
  } catch (_) {
    // 同上。
  }
}

export function getDeviceToken() {
  return readStorage(DEVICE_TOKEN_KEY);
}

export function storeDeviceSession({ token, deviceId = '', deviceName = '' } = {}) {
  if (token) writeStorage(DEVICE_TOKEN_KEY, token);
  if (deviceId) writeStorage(DEVICE_ID_KEY, deviceId);
  if (deviceName) writeStorage(DEVICE_NAME_KEY, deviceName);
}

export function clearDeviceSession() {
  removeStorage(DEVICE_TOKEN_KEY);
  removeStorage(DEVICE_ID_KEY);
  removeStorage(DEVICE_NAME_KEY);
}

function deviceAuthHeaders() {
  const token = getDeviceToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, options = {}) {
  const url = path.startsWith('/') ? path : `/${path}`;
  // SR-1（F3）：所有請求統一套上自訂標頭。變更類請求在後端據此擋掉
  // 跨站「簡單請求」——外部網頁要帶自訂標頭就得先過 CORS preflight，
  // 而本服務沒有 CORS。
  // 裝置權杖（若有）自動附加：已配對手機不必手動貼上 token。
  const headers = {
    'X-Requested-With': 'ItemTrace',
    ...deviceAuthHeaders(),
    ...(options.headers || {}),
  };
  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    // 權杖無效或已被撤銷：清除本機憑證，讓下次載入回到配對引導。
    if (response.status === 401) {
      clearDeviceSession();
    }
    let errorDetail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data && data.detail) {
        errorDetail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch (_) {
      // Non-JSON error
    }
    const err = new Error(errorDetail);
    err.status = response.status;
    throw err;
  }

  // Handle 204 or empty responses
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  // Items & Records
  async listItems(query = '', category = null) {
    const params = new URLSearchParams();
    if (query && query.trim()) params.set('q', query.trim());
    if (category) params.set('category', category);
    const qs = params.toString();
    return request(`/api/items${qs ? `?${qs}` : ''}`);
  },

  async getItem(id) {
    return request(`/api/items/${id}`);
  },

  async patchItem(id, changes) {
    return request(`/api/items/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    });
  },

  // 移至垃圾桶（軟刪除；資料與照片都保留，可從垃圾桶還原）
  async voidItem(id) {
    return request(`/api/items/${id}/void`, { method: 'POST' });
  },

  // 從垃圾桶還原（回到移入前的狀態）
  async restoreItem(id) {
    return request(`/api/items/${id}/restore`, { method: 'POST' });
  },

  // 永久刪除（僅限垃圾桶中的紀錄；不可逆）
  async purgeItem(id) {
    return request(`/api/items/${id}`, { method: 'DELETE' });
  },

  // 垃圾桶列表（只有 status=void 的紀錄）
  async listTrashItems() {
    return request('/api/items?status=void&limit=500');
  },

  // Photo Upload & Intake Pipeline
  async uploadInboxPhotos(files) {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }
    return request('/api/inbox/photos', {
      method: 'POST',
      body: formData,
    });
  },

  async intake(relativeFiles, kind = 'intake') {
    return request('/api/inbox/intake', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        files: relativeFiles,
        kind,
      }),
    });
  },

  // 取消建檔：清掉這次上傳的 inbox 暫存檔（冪等；不碰資料庫）
  async discardInboxFiles(relativeFiles) {
    return request('/api/inbox/discard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: relativeFiles }),
    });
  },

  // 草稿分析（capture 審閱用）：不建立任何紀錄。
  // 正式 Item／photos／suggestions 一律等「存起來」才建立。
  async analyzeDraft(relativeFiles) {
    return request('/api/inbox/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: relativeFiles }),
    });
  },

  // AI Vision Analysis
  // auto: 依政策自動套用低風險項目（Phase 2C-B；可復原）
  async analyzeItem(itemId, { auto = false } = {}) {
    const suffix = auto ? '?auto=1' : '';
    return request(`/api/items/${itemId}/ai/analyze${suffix}`, {
      method: 'POST',
    });
  },

  // Item events（Phase 2C-D：自動更新 banner 顯示前後值用）
  async listEvents(itemId, limit = 50) {
    return request(`/api/items/${itemId}/events?limit=${limit}`);
  },

  // Evidence accumulation (Phase 2B): add photos to an existing record
  async createObservation(itemId, { kind = 'recheck', note = '' } = {}) {
    return request(`/api/items/${itemId}/observations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, note }),
    });
  },

  async uploadObservationPhotos(observationId, files) {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }
    return request(`/api/observations/${observationId}/photos`, {
      method: 'POST',
      body: formData,
    });
  },

  async acceptSuggestion(suggestionId) {
    return request(`/api/suggestions/${suggestionId}/accept`, {
      method: 'POST',
    });
  },

  // 建立正式建議（外部工具路徑；capture 儲存時把 AI 草稿落成建議再接受，
  // 保留 model／confidence／來源照片的完整追溯）
  async createSuggestion(itemId, payload) {
    return request(`/api/items/${itemId}/suggestions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  async rejectSuggestion(suggestionId) {
    return request(`/api/suggestions/${suggestionId}/reject`, {
      method: 'POST',
    });
  },

  // 復原一次「自動套用」（Phase 2C-B）
  async undoSuggestion(suggestionId) {
    return request(`/api/suggestions/${suggestionId}/undo`, {
      method: 'POST',
    });
  },

  async addIdentifier(itemId, { kind = 'serial', value = '' }) {
    return request(`/api/items/${itemId}/identifiers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, value }),
    });
  },

  // Settings
  async getAiSettings() {
    return request('/api/settings/ai');
  },

  async updateAiSettings(data) {
    return request('/api/settings/ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  async testAiSettings(data) {
    return request('/api/settings/ai/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  // Phone Pairing
  // 電腦端（管理操作；伺服器只接受 loopback 呼叫）
  async getSession() {
    return request('/api/session');
  },

  async startPairing() {
    return request('/api/pairing/start', {
      method: 'POST',
    });
  },

  async pairingStatus(sessionId) {
    return request(`/api/pairing/sessions/${encodeURIComponent(sessionId)}`);
  },

  async listPairedDevices() {
    return request('/api/pairing/devices');
  },

  async revokePairedDevice(deviceId) {
    return request(`/api/pairing/devices/${encodeURIComponent(deviceId)}`, {
      method: 'DELETE',
    });
  },

  // 手機端：用 QR Code 網址帶來的 id + code 完成配對（未配對裝置允許）。
  async claimPairing(sessionId, code, deviceName = '') {
    return request('/api/pairing/claim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        code,
        device_name: deviceName,
      }),
    });
  },
};

/**
 * Standardized URL resolver for photos and thumbnails.
 * Handles:
 * - Local blob/data URLs
 * - Relative paths from DB ('files/ITM-...', 'inbox/...', 'ITM-...')
 * - Windows path separator normalization
 */
export function getPhotoUrl(path) {
  if (!path) return '';
  if (path.startsWith('blob:') || path.startsWith('data:') || path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  const clean = path.replace(/\\/g, '/').replace(/^\/+/, '');
  if (clean.startsWith('files/')) {
    return `/${clean}`;
  }
  return `/files/${clean}`;
}

