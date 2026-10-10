/**
 * ItemTrace V3 API Client
 *
 * Lightweight Fetch wrapper for communicating with the backend.
 */

async function request(path, options = {}) {
  const url = path.startsWith('/') ? path : `/${path}`;
  // SR-1（F3）：所有請求統一套上自訂標頭。變更類請求在後端據此擋掉
  // 跨站「簡單請求」——外部網頁要帶自訂標頭就得先過 CORS preflight，
  // 而本服務沒有 CORS。
  const headers = {
    'X-Requested-With': 'ItemTrace',
    ...(options.headers || {}),
  };
  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
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

