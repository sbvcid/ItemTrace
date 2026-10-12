/**
 * Folders View (/folders)
 *
 * Phase 4: Folder management interface
 * - List all folders with item counts
 * - Virtual "Unclassified" folder for items without a folder
 * - Create, rename, delete folders
 * - Enter folder detail view
 */

import { api, getPhotoUrl } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';
import { showToast } from '../core/router.js';
import { t } from '../i18n/index.js';

export async function createFoldersView(params, router) {
  const el = document.createElement('div');
  el.className = 'folders-view';

  el.innerHTML = `
    <header class="app-header">
      <div style="display: flex; align-items: center; gap: 8px;">
        <a href="/" class="icon-btn" title="${t('app.back')}" data-link>←</a>
        <span style="font-weight: 700; font-size: 1.05rem;">📁 ${t('folders.title')}</span>
      </div>
      <div class="header-actions">
        <button type="button" class="icon-btn" title="${t('folders.create')}" id="btn-new-folder">＋</button>
      </div>
    </header>

    <main class="container">
      <div class="folder-actions-bar" id="folder-actions-bar">
        <!-- Buttons for organizing: AI sort (disabled), classification rules (disabled) -->
      </div>

      <div class="folder-list" id="folder-list">
        <div style="padding: 20px; text-align: center; color: var(--text-muted);">
          ${t('app.loading')}
        </div>
      </div>

      <div class="empty-state" id="folders-empty" style="display: none;">
        <div class="empty-icon">📁</div>
        <div class="empty-title">${t('folders.emptyTitle')}</div>
        <div class="empty-subtitle">${t('folders.emptySubtitle')}</div>
        <button type="button" class="btn-primary" id="btn-create-first" style="display: inline-flex; width: auto;">
          ＋ ${t('folders.create')}
        </button>
      </div>
    </main>

    <!-- Create folder modal -->
    <div class="modal" id="create-modal" style="display: none;">
      <div class="modal-overlay" id="modal-overlay"></div>
      <div class="modal-content">
        <h3>${t('folders.createTitle')}</h3>
        <input type="text" class="ai-edit-input" id="input-folder-name" 
               placeholder="${t('folders.namePlaceholder')}" maxlength="100" />
        <textarea class="ai-edit-input" id="input-folder-desc" 
                  placeholder="${t('folders.descPlaceholder')}" maxlength="500" 
                  style="min-height: 60px; resize: vertical;"></textarea>
        <div style="display: flex; gap: 10px; margin-top: 16px;">
          <button type="button" class="btn-primary" id="btn-confirm-create" style="flex: 1;">
            ${t('app.create')}
          </button>
          <button type="button" class="btn-secondary" id="btn-cancel-create" style="flex: 1;">
            ${t('app.cancel')}
          </button>
        </div>
      </div>
    </div>

    <!-- Edit folder modal (rename) -->
    <div class="modal" id="rename-modal" style="display: none;">
      <div class="modal-overlay" id="rename-overlay"></div>
      <div class="modal-content">
        <h3>${t('folders.renameTitle')}</h3>
        <input type="text" class="ai-edit-input" id="input-rename-name" maxlength="100" />
        <textarea class="ai-edit-input" id="input-rename-desc" 
                  placeholder="${t('folders.descPlaceholder')}" maxlength="500"
                  style="min-height: 60px; resize: vertical;"></textarea>
        <div style="display: flex; gap: 10px; margin-top: 16px;">
          <button type="button" class="btn-primary" id="btn-confirm-rename" style="flex: 1;">
            ${t('app.save')}
          </button>
          <button type="button" class="btn-secondary" id="btn-cancel-rename" style="flex: 1;">
            ${t('app.cancel')}
          </button>
        </div>
      </div>
    </div>
  `;

  const listContainer = el.querySelector('#folder-list');
  const emptyState = el.querySelector('#folders-empty');
  const newFolderBtn = el.querySelector('#btn-new-folder');
  const createFirstBtn = el.querySelector('#btn-create-first');
  const createModal = el.querySelector('#create-modal');
  const renameModal = el.querySelector('#rename-modal');
  const modalOverlay = el.querySelector('#modal-overlay');
  const renameOverlay = el.querySelector('#rename-overlay');

  let busy = false;
  let currentEditingFolderId = null;

  function setBusy(on) {
    busy = on;
    newFolderBtn.disabled = on;
    createFirstBtn.disabled = on;
    listContainer.querySelectorAll('button').forEach(btn => {
      btn.disabled = on;
    });
  }

  function closeCreateModal() {
    createModal.style.display = 'none';
    el.querySelector('#input-folder-name').value = '';
    el.querySelector('#input-folder-desc').value = '';
  }

  function closeRenameModal() {
    renameModal.style.display = 'none';
    el.querySelector('#input-rename-name').value = '';
    el.querySelector('#input-rename-desc').value = '';
    currentEditingFolderId = null;
  }

  function openCreateModal() {
    createModal.style.display = 'flex';
    el.querySelector('#input-folder-name').focus();
  }

  function openRenameModal(folder) {
    currentEditingFolderId = folder.id;
    el.querySelector('#input-rename-name').value = folder.name || '';
    el.querySelector('#input-rename-desc').value = folder.description || '';
    renameModal.style.display = 'flex';
    el.querySelector('#input-rename-name').focus();
  }

  modalOverlay.addEventListener('click', closeCreateModal);
  renameOverlay.addEventListener('click', closeRenameModal);

  el.querySelector('#btn-cancel-create').addEventListener('click', closeCreateModal);
  el.querySelector('#btn-cancel-rename').addEventListener('click', closeRenameModal);

  newFolderBtn.addEventListener('click', openCreateModal);
  createFirstBtn.addEventListener('click', openCreateModal);

  el.querySelector('#btn-confirm-create').addEventListener('click', async () => {
    if (busy) return;
    const name = el.querySelector('#input-folder-name').value.trim();
    if (!name) {
      showToast(t('folders.errorNameEmpty'));
      return;
    }
    setBusy(true);
    try {
      const desc = el.querySelector('#input-folder-desc').value.trim();
      await api.createFolder({ name, description: desc });
      showToast(t('folders.createSuccess', { name }));
      closeCreateModal();
      await loadFolders();
    } catch (err) {
      console.error('Create folder failed:', err);
      showToast(`${t('folders.createError')}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  });

  el.querySelector('#btn-confirm-rename').addEventListener('click', async () => {
    if (busy || !currentEditingFolderId) return;
    const name = el.querySelector('#input-rename-name').value.trim();
    if (!name) {
      showToast(t('folders.errorNameEmpty'));
      return;
    }
    setBusy(true);
    try {
      const desc = el.querySelector('#input-rename-desc').value.trim();
      await api.updateFolder(currentEditingFolderId, { name, description: desc });
      showToast(t('folders.renameSuccess'));
      closeRenameModal();
      await loadFolders();
    } catch (err) {
      console.error('Rename folder failed:', err);
      showToast(`${t('folders.renameError')}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  });

  async function loadFolders() {
    listContainer.innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--text-muted);">
        ${t('app.loading')}
      </div>
    `;
    try {
      const data = await api.listFolders('active');
      const folders = data.folders || [];
      const unclassifiedCount = data.unclassified_count || 0;
      renderFolders(folders, unclassifiedCount);
    } catch (err) {
      console.error('Failed to load folders:', err);
      emptyState.style.display = 'none';
      listContainer.innerHTML = `
        <div style="padding: 20px; text-align: center; color: var(--color-danger);">
          ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  function renderFolders(folders, unclassifiedCount) {
    listContainer.innerHTML = '';
    
    // Show empty state if no folders and no unclassified items
    if (folders.length === 0 && unclassifiedCount === 0) {
      emptyState.style.display = 'block';
      return;
    }
    
    emptyState.style.display = 'none';

    // Render unclassified virtual folder
    if (unclassifiedCount > 0) {
      const unclassifiedCard = document.createElement('div');
      unclassifiedCard.className = 'folder-card folder-card-unclassified';
      unclassifiedCard.innerHTML = `
        <div class="folder-card-header">
          <div class="folder-card-icon">📋</div>
          <div class="folder-card-title">${t('folders.unclassified')}</div>
        </div>
        <div class="folder-card-count">${t('folders.itemCount', { n: unclassifiedCount })}</div>
        <div class="folder-card-actions">
          <a href="/folders/unclassified" class="btn-mini" data-link>${t('folders.enter')}</a>
        </div>
      `;
      listContainer.appendChild(unclassifiedCard);
    }

    // Render regular folders
    folders.forEach(folder => {
      const card = document.createElement('div');
      card.className = 'folder-card';
      card.setAttribute('data-id', folder.id);

      const itemCount = folder.item_count || 0;
      const description = folder.description || '';

      card.innerHTML = `
        <div class="folder-card-header">
          <div class="folder-card-icon">📁</div>
          <div class="folder-card-info">
            <div class="folder-card-title">${escapeHtml(folder.name)}</div>
            ${description ? `<div class="folder-card-desc">${escapeHtml(description)}</div>` : ''}
          </div>
        </div>
        <div class="folder-card-count">${t('folders.itemCount', { n: itemCount })}</div>
        <div class="folder-card-actions">
          <a href="/folders/${escapeHtml(folder.id)}" class="btn-mini" data-link>${t('folders.enter')}</a>
          <button type="button" class="btn-mini" data-action="rename">${t('app.edit')}</button>
          <button type="button" class="btn-mini btn-mini-danger" data-action="delete">${t('app.delete')}</button>
        </div>
      `;

      card.querySelector('[data-action="rename"]').addEventListener('click', () => {
        openRenameModal(folder);
      });

      card.querySelector('[data-action="delete"]').addEventListener('click', () => {
        deleteFolder(folder);
      });

      listContainer.appendChild(card);
    });
  }

  async function deleteFolder(folder) {
    if (busy) return;
    const confirmed = window.confirm(
      t('folders.deleteConfirm', { name: folder.name })
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      await api.deleteFolder(folder.id);
      showToast(t('folders.deleteSuccess', { name: folder.name }));
      await loadFolders();
    } catch (err) {
      console.error('Delete folder failed:', err);
      showToast(`${t('folders.deleteError')}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  loadFolders();

  return {
    element: el,
  };
}
