/**
 * ItemTrace V3 Client Router
 *
 * Lightweight SPA history router with dynamic parameter parsing.
 */

import { escapeHtml } from './dom.js';

class Router {
  constructor() {
    this.routes = [];
    this.currentView = null;
    this.container = null;

    window.addEventListener('popstate', () => this.resolve());

    // Intercept clicks on links with data-link
    document.addEventListener('click', (e) => {
      const link = e.target.closest('a[data-link]');
      if (link) {
        e.preventDefault();
        const href = link.getAttribute('href');
        this.navigate(href);
      }
    });
  }

  init(container) {
    this.container = container;
    this.resolve();
  }

  add(pattern, handler) {
    // Convert pattern like "/i/:id" to regex
    const paramNames = [];
    const regexPath = pattern.replace(/:([a-zA-Z0-9_]+)/g, (_, name) => {
      paramNames.push(name);
      return '([^/]+)';
    });
    const regex = new RegExp(`^${regexPath}$`);
    this.routes.push({ pattern, regex, paramNames, handler });
    return this;
  }

  navigate(path) {
    if (window.location.pathname !== path) {
      window.history.pushState(null, '', path);
    }
    this.resolve();
  }

  async resolve() {
    if (!this.container) return;

    const path = window.location.pathname;

    for (const route of this.routes) {
      const match = path.match(route.regex);
      if (match) {
        const params = {};
        route.paramNames.forEach((name, index) => {
          params[name] = decodeURIComponent(match[index + 1]);
        });

        if (this.currentView && typeof this.currentView.destroy === 'function') {
          this.currentView.destroy();
        }

        try {
          this.container.innerHTML = '';
          const viewInstance = await route.handler(params, this);
          this.currentView = viewInstance;
          if (viewInstance && viewInstance.element) {
            this.container.appendChild(viewInstance.element);
          }
          window.scrollTo(0, 0);
        } catch (err) {
          console.error('Route handler error:', err);
          // SR-1／F6：錯誤訊息屬不可信內容 → escape；按鈕改用事件監聽
          // （CSP script-src 'self' 會擋 inline onclick）。
          this.container.innerHTML = `
            <div class="container empty-state">
              <div class="empty-icon">⚠️</div>
              <div class="empty-title">畫面載入失敗</div>
              <div class="empty-subtitle">${escapeHtml(err.message || '未知錯誤')}</div>
              <button class="btn-primary" id="btn-route-back">返回上一頁</button>
            </div>
          `;
          const backButton = this.container.querySelector('#btn-route-back');
          if (backButton) {
            backButton.addEventListener('click', () => window.history.back());
          }
        }
        return;
      }
    }

    // 404 fallback: redirect to home
    this.navigate('/');
  }
}

export const router = new Router();

export function showToast(message, duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

