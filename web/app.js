/**
 * ItemTrace V3 Main Application Entrypoint
 *
 * Boots router, initializes i18n, and binds views.
 */

import { router } from './core/router.js';
import { initI18n, onLocaleChange } from './i18n/index.js';
import { createHomeView } from './views/home.js';
import { createCaptureView } from './views/capture.js';
import { createRecordDetailView } from './views/record-detail.js';
import { createSettingsView } from './views/settings.js';

document.addEventListener('DOMContentLoaded', () => {
  // Initialize locale from storage or browser
  initI18n();

  const container = document.getElementById('app');

  router
    .add('/', createHomeView)
    .add('/capture', createCaptureView)
    .add('/i/:id', createRecordDetailView)
    .add('/items/:id', createRecordDetailView) // Backward compatibility link
    .add('/settings', createSettingsView)
    .init(container);

  // Automatically re-render current view on language change
  onLocaleChange(() => {
    router.resolve();
  });
});
