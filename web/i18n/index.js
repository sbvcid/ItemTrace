/**
 * ItemTrace Zero-Build ESM i18n System
 */

import zhTW from './zh-TW.js';
import en from './en.js';

const dictionaries = {
  'zh-TW': zhTW,
  'en': en,
};

const STORAGE_KEY = 'itemtrace_locale';
let currentLocale = 'zh-TW';
const listeners = new Set();

/**
 * Detect user's preferred locale from browser settings.
 */
function detectSystemLocale() {
  const navLang = (navigator.language || navigator.userLanguage || '').toLowerCase();
  if (navLang.startsWith('zh')) {
    return 'zh-TW';
  }
  return 'en';
}

/**
 * Initialize i18n locale from localStorage or system preference.
 */
export function initI18n() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && dictionaries[saved]) {
    currentLocale = saved;
  } else {
    currentLocale = detectSystemLocale();
  }
  return currentLocale;
}

/**
 * Get the currently active locale.
 */
export function getLocale() {
  return currentLocale;
}

/**
 * Change the active locale and notify all listeners.
 */
export function setLocale(locale) {
  if (!dictionaries[locale]) {
    console.warn(`Unsupported locale: ${locale}`);
    return;
  }
  currentLocale = locale;
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch (e) {
    // LocalStorage might be disabled in private browsing
  }
  listeners.forEach(cb => {
    try {
      cb(currentLocale);
    } catch (err) {
      console.error('Error in i18n listener:', err);
    }
  });
}

/**
 * Subscribe to locale change events.
 */
export function onLocaleChange(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

/**
 * Translate a key with optional interpolation params.
 * e.g. t('home.heroTitle') or t('home.photoCount', { n: 3 })
 */
export function t(key, params = {}) {
  const dict = dictionaries[currentLocale] || dictionaries['zh-TW'];
  const fallback = dictionaries['zh-TW'];

  const resolve = (obj, path) => {
    const parts = path.split('.');
    let cur = obj;
    for (const part of parts) {
      if (!cur || typeof cur !== 'object') return null;
      cur = cur[part];
    }
    return typeof cur === 'string' ? cur : null;
  };

  let template = resolve(dict, key) || resolve(fallback, key) || key;

  // Interpolate params: {n} -> value
  if (params && typeof params === 'object') {
    Object.keys(params).forEach(k => {
      const regex = new RegExp(`\\{${k}\\}`, 'g');
      template = template.replace(regex, params[k]);
    });
  }

  return template;
}

