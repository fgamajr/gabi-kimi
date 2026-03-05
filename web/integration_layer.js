/**
 * GABI Search - Integration Layer
 * PerformancePolisher Agent - WCAG 2.1 AA, Micro-interactions, Performance
 * @version 2.0.0
 */

(function () {
  'use strict';

  // =============================================================================
  // CONFIGURATION
  // =============================================================================
  const CONFIG = {
    DEBOUNCE_MS: 150,
    THROTTLE_MS: 100,
    RETRY_MAX: 3,
    RETRY_DELAY_MS: 1000,
    LAZY_RENDER_BATCH: 10,
    SCROLL_TOP_THRESHOLD: 400,
    TOAST_DURATION: 5000,
    KONAMI_CODE: ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'],
    STORAGE_KEY: 'gabi_prefs'
  };

  // =============================================================================
  // UTILITY FUNCTIONS
  // =============================================================================

  /**
   * Debounce function - delays execution until after wait milliseconds
   * @param {Function} fn - Function to debounce
   * @param {number} wait - Milliseconds to wait
   * @returns {Function} Debounced function
   */
  function debounce(fn, wait = CONFIG.DEBOUNCE_MS) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  /**
   * Throttle function - limits execution to once per limit milliseconds
   * @param {Function} fn - Function to throttle
   * @param {number} limit - Milliseconds between executions
   * @returns {Function} Throttled function
   */
  function throttle(fn, limit = CONFIG.THROTTLE_MS) {
    let inThrottle = false;
    return function (...args) {
      if (!inThrottle) {
        fn.apply(this, args);
        inThrottle = true;
        setTimeout(() => inThrottle = false, limit);
      }
    };
  }

  /**
   * Escape HTML special characters
   * @param {string} str - String to escape
   * @returns {string} Escaped string
   */
  function escapeHtml(str = '') {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Format date string to Brazilian locale
   * @param {string} dateStr - Date string (ISO or YYYY-MM-DD)
   * @returns {string} Formatted date
   */
  function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr);
      if (isNaN(date.getTime())) return dateStr;
      return new Intl.DateTimeFormat('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
      }).format(date);
    } catch {
      return dateStr;
    }
  }

  /**
   * Format number with Brazilian locale
   * @param {number} num - Number to format
   * @returns {string} Formatted number
   */
  function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return new Intl.NumberFormat('pt-BR').format(num);
  }

  /**
   * Copy text to clipboard
   * @param {string} text - Text to copy
   * @returns {Promise<boolean>} Success status
   */
  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.cssText = 'position:fixed;left:-9999px;opacity:0;';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      showToast('Copiado para a área de transferência!', 'success');
      return true;
    } catch (err) {
      showToast('Erro ao copiar. Tente manualmente.', 'error');
      return false;
    }
  }

  /**
   * Share document using Web Share API or fallback
   * @param {Object} doc - Document object with title and url
   */
  async function shareDocument(doc) {
    const shareData = {
      title: doc.title || 'Documento DOU',
      text: doc.snippet || '',
      url: doc.url || window.location.href
    };

    try {
      if (navigator.share) {
        await navigator.share(shareData);
      } else {
        // Fallback: copy URL
        await copyToClipboard(shareData.url);
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        showToast('Erro ao compartilhar', 'error');
      }
    }
  }

  /**
   * Parse hash/URL parameters
   * @returns {URLSearchParams} Parsed parameters
   */
  function parseHashParams() {
    const hash = window.location.hash.slice(1);
    const search = window.location.search;
    const params = new URLSearchParams(search || hash);
    return params;
  }

  /**
   * Update URL state with current parameters
   * @param {Object} params - Parameters object
   * @param {boolean} replace - Use replaceState instead of pushState
   */
  function updateUrlState(params = {}, replace = false) {
    const urlParams = new URLSearchParams();
    
    Object.entries(params).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== '') {
        urlParams.set(key, String(value));
      }
    });

    const queryString = urlParams.toString();
    const newUrl = `${window.location.pathname}${queryString ? '?' + queryString : ''}`;

    if (replace) {
      window.history.replaceState({ path: newUrl }, '', newUrl);
    } else {
      window.history.pushState({ path: newUrl }, '', newUrl);
    }
  }

  /**
   * Exponential backoff retry wrapper
   * @param {Function} fn - Async function to retry
   * @param {number} maxRetries - Maximum retry attempts
   * @returns {Promise<any>} Function result
   */
  async function withRetry(fn, maxRetries = CONFIG.RETRY_MAX) {
    let lastError;
    for (let i = 0; i <= maxRetries; i++) {
      try {
        return await fn();
      } catch (err) {
        lastError = err;
        if (i < maxRetries) {
          const delay = CONFIG.RETRY_DELAY_MS * Math.pow(2, i);
          await new Promise(r => setTimeout(r, delay));
        }
      }
    }
    throw lastError;
  }

  // =============================================================================
  // THEME MANAGEMENT
  // =============================================================================

  const ThemeManager = {
    current: 'dark',
    
    init() {
      const saved = this.loadPreference();
      const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const initialTheme = saved || (systemPrefersDark ? 'dark' : 'light');
      this.set(initialTheme, false);
      
      // Listen for system theme changes
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!this.loadPreference()) {
          this.set(e.matches ? 'dark' : 'light', false);
        }
      });
    },

    set(theme, save = true) {
      this.current = theme;
      document.documentElement.setAttribute('data-theme', theme);
      document.body.classList.toggle('theme-light', theme === 'light');
      document.body.classList.toggle('theme-dark', theme === 'dark');
      
      if (save) {
        this.savePreference(theme);
      }
      
      // Update meta theme-color for mobile browsers
      const metaTheme = document.querySelector('meta[name="theme-color"]');
      if (metaTheme) {
        metaTheme.content = theme === 'dark' ? '#0d111b' : '#ffffff';
      }
    },

    toggle() {
      this.set(this.current === 'dark' ? 'light' : 'dark');
    },

    savePreference(theme) {
      try {
        const prefs = JSON.parse(localStorage.getItem(CONFIG.STORAGE_KEY) || '{}');
        prefs.theme = theme;
        localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(prefs));
      } catch {}
    },

    loadPreference() {
      try {
        const prefs = JSON.parse(localStorage.getItem(CONFIG.STORAGE_KEY) || '{}');
        return prefs.theme;
      } catch {
        return null;
      }
    }
  };

  // =============================================================================
  // TOAST NOTIFICATION SYSTEM
  // =============================================================================

  const ToastSystem = {
    container: null,
    toasts: [],

    init() {
      if (this.container) return;
      
      this.container = document.createElement('div');
      this.container.id = 'toast-container';
      this.container.setAttribute('role', 'region');
      this.container.setAttribute('aria-live', 'polite');
      this.container.setAttribute('aria-label', 'Notificações');
      document.body.appendChild(this.container);
    },

    show(message, type = 'info', duration = CONFIG.TOAST_DURATION) {
      this.init();
      
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.setAttribute('role', 'alert');
      
      const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
      };
      
      toast.innerHTML = `
        <span class="toast-icon" aria-hidden="true">${icons[type] || icons.info}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" aria-label="Fechar notificação">×</button>
      `;
      
      toast.querySelector('.toast-close').onclick = () => this.dismiss(toast);
      
      this.container.appendChild(toast);
      this.toasts.push(toast);
      
      // Animate in
      requestAnimationFrame(() => {
        toast.classList.add('toast-visible');
      });
      
      // Auto dismiss
      if (duration > 0) {
        setTimeout(() => this.dismiss(toast), duration);
      }
      
      return toast;
    },

    dismiss(toast) {
      toast.classList.remove('toast-visible');
      toast.classList.add('toast-hiding');
      
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
        this.toasts = this.toasts.filter(t => t !== toast);
      }, 300);
    }
  };

  function showToast(message, type = 'info', duration) {
    return ToastSystem.show(message, type, duration);
  }

  // =============================================================================
  // LAZY RENDERING (INTERSECTION OBSERVER)
  // =============================================================================

  const LazyRenderer = {
    observer: null,
    pending: new Map(),

    init() {
      this.observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const callback = this.pending.get(entry.target);
            if (callback) {
              callback(entry.target);
              this.pending.delete(entry.target);
              this.observer.unobserve(entry.target);
            }
          }
        });
      }, {
        rootMargin: '50px 0px',
        threshold: 0.01
      });
    },

    observe(element, callback) {
      if (!this.observer) this.init();
      this.pending.set(element, callback);
      this.observer.observe(element);
    },

    unobserve(element) {
      if (this.observer) {
        this.observer.unobserve(element);
        this.pending.delete(element);
      }
    }
  };

  // =============================================================================
  // BACK TO TOP FAB
  // =============================================================================

  const BackToTop = {
    button: null,

    init() {
      this.button = document.createElement('button');
      this.button.id = 'back-to-top';
      this.button.className = 'fab-back-to-top';
      this.button.setAttribute('aria-label', 'Voltar ao topo');
      this.button.setAttribute('title', 'Voltar ao topo');
      this.button.innerHTML = '↑';
      this.button.style.opacity = '0';
      this.button.style.pointerEvents = 'none';
      document.body.appendChild(this.button);

      this.button.onclick = () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
        this.button.blur();
      };

      window.addEventListener('scroll', throttle(() => this.toggle(), CONFIG.THROTTLE_MS), { passive: true });
    },

    toggle() {
      const show = window.pageYOffset > CONFIG.SCROLL_TOP_THRESHOLD;
      this.button.style.opacity = show ? '1' : '0';
      this.button.style.pointerEvents = show ? 'auto' : 'none';
    }
  };

  // =============================================================================
  // KEYBOARD SHORTCUTS
  // =============================================================================

  const KeyboardShortcuts = {
    konamiIndex: 0,

    init() {
      document.addEventListener('keydown', (e) => this.handle(e));
    },

    handle(e) {
      // Ctrl+K / Cmd+K to focus search
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.getElementById('q');
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
        return;
      }

      // Escape to close modals/autocomplete
      if (e.key === 'Escape') {
        const autocomplete = document.getElementById('autocomplete');
        if (autocomplete && autocomplete.classList.contains('show')) {
          autocomplete.classList.remove('show');
          document.getElementById('q')?.focus();
        }
        return;
      }

      // Konami code easter egg
      this.checkKonami(e.key);
    },

    checkKonami(key) {
      if (key === CONFIG.KONAMI_CODE[this.konamiIndex]) {
        this.konamiIndex++;
        if (this.konamiIndex === CONFIG.KONAMI_CODE.length) {
          this.triggerEasterEgg();
          this.konamiIndex = 0;
        }
      } else {
        this.konamiIndex = 0;
      }
    },

    triggerEasterEgg() {
      showToast('🎉 Modo secreto ativado! Você é um explorador nato!', 'success', 8000);
      document.body.classList.add('konami-active');
      setTimeout(() => document.body.classList.remove('konami-active'), 5000);
      
      // Confetti effect (simple CSS-based)
      for (let i = 0; i < 20; i++) {
        setTimeout(() => this.createConfetti(), i * 50);
      }
    },

    createConfetti() {
      const confetti = document.createElement('div');
      confetti.className = 'confetti';
      confetti.style.left = Math.random() * 100 + 'vw';
      confetti.style.animationDelay = Math.random() * 2 + 's';
      confetti.style.backgroundColor = ['#00d0c8', '#6be4d4', '#ff6a7f', '#ffd700'][Math.floor(Math.random() * 4)];
      document.body.appendChild(confetti);
      setTimeout(() => confetti.remove(), 3000);
    }
  };

  // =============================================================================
  // PRINT HELPER
  // =============================================================================

  function printDocument(docId) {
    // Create a temporary print-friendly view
    const printWindow = window.open('', '_blank');
    if (!printWindow) {
      showToast('Permita popups para imprimir', 'warning');
      return;
    }

    const docTitle = document.getElementById('docTitle')?.textContent || 'Documento DOU';
    const docMeta = document.getElementById('docMeta')?.textContent || '';
    const docBody = document.getElementById('docBody')?.innerHTML || '';

    printWindow.document.write(`
      <!DOCTYPE html>
      <html lang="pt-BR">
      <head>
        <meta charset="UTF-8">
        <title>${escapeHtml(docTitle)}</title>
        <style>
          body { font-family: Georgia, serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 20px; color: #000; }
          h1 { font-size: 24px; margin-bottom: 10px; }
          .meta { color: #666; font-size: 14px; margin-bottom: 20px; border-bottom: 1px solid #ddd; padding-bottom: 10px; }
          .content { text-align: justify; }
          @media print { body { margin: 0; } }
        </style>
      </head>
      <body>
        <h1>${escapeHtml(docTitle)}</h1>
        <div class="meta">${escapeHtml(docMeta)}</div>
        <div class="content">${docBody}</div>
      </body>
      </html>
    `);
    
    printWindow.document.close();
    printWindow.focus();
    
    setTimeout(() => {
      printWindow.print();
    }, 250);
  }

  // =============================================================================
  // URL STATE SYNC
  // =============================================================================

  const UrlState = {
    syncFromState(state) {
      const params = {
        q: state.q !== '*' ? state.q : '',
        page: state.page > 1 ? state.page : '',
        section: document.getElementById('section')?.value || '',
        type: document.getElementById('type')?.value || '',
        dfrom: document.getElementById('dfrom')?.value || '',
        dto: document.getElementById('dto')?.value || ''
      };
      updateUrlState(params);
    },

    loadToState() {
      const params = parseHashParams();
      const updates = {};

      if (params.has('q')) updates.q = params.get('q');
      if (params.has('page')) updates.page = parseInt(params.get('page'), 10) || 1;
      if (params.has('section')) updates.section = params.get('section');
      if (params.has('type')) updates.type = params.get('type');
      if (params.has('dfrom')) updates.dfrom = params.get('dfrom');
      if (params.has('dto')) updates.dto = params.get('dto');

      return updates;
    },

    initListeners(onChange) {
      window.addEventListener('popstate', (e) => {
        if (e.state && onChange) {
          onChange(this.loadToState());
        }
      });
    }
  };

  // =============================================================================
  // ACCESSIBILITY HELPERS
  // =============================================================================

  const A11y = {
    announce(message, priority = 'polite') {
      const liveRegion = document.getElementById('a11y-live-region');
      if (liveRegion) {
        liveRegion.setAttribute('aria-live', priority);
        liveRegion.textContent = message;
        // Clear after announcement
        setTimeout(() => { liveRegion.textContent = ''; }, 1000);
      }
    },

    trapFocus(element) {
      const focusable = element.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      element.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return;

        if (e.shiftKey) {
          if (document.activeElement === first) {
            last.focus();
            e.preventDefault();
          }
        } else {
          if (document.activeElement === last) {
            first.focus();
            e.preventDefault();
          }
        }
      });
    },

    setExpanded(element, expanded) {
      element.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    },

    setSelected(element, selected) {
      element.setAttribute('aria-selected', selected ? 'true' : 'false');
    }
  };

  // =============================================================================
  // LOADING SKELETONS
  // =============================================================================

  const SkeletonLoader = {
    createCard() {
      const card = document.createElement('div');
      card.className = 'card skeleton-card';
      card.innerHTML = `
        <div class="skeleton kicker"></div>
        <div class="skeleton title"></div>
        <div class="skeleton snippet"></div>
        <div class="skeleton snippet short"></div>
      `;
      return card;
    },

    show(container, count = 5) {
      container.innerHTML = '';
      for (let i = 0; i < count; i++) {
        const skeleton = this.createCard();
        skeleton.style.animationDelay = `${i * 0.1}s`;
        container.appendChild(skeleton);
      }
    },

    hide(container) {
      const skeletons = container.querySelectorAll('.skeleton-card');
      skeletons.forEach(s => s.remove());
    }
  };

  // =============================================================================
  // PREFETCH MANAGER
  // =============================================================================

  const PrefetchManager = {
    prefetched: new Set(),

    async prefetch(url) {
      if (this.prefetched.has(url)) return;
      
      // Use requestIdleCallback if available, otherwise setTimeout
      const schedule = window.requestIdleCallback || ((cb) => setTimeout(cb, 1));
      
      schedule(() => {
        const link = document.createElement('link');
        link.rel = 'prefetch';
        link.href = url;
        link.as = 'fetch';
        document.head.appendChild(link);
        this.prefetched.add(url);
      });
    },

    prefetchInitial() {
      // Prefetch common API endpoints
      this.prefetch('/api/stats');
      this.prefetch('/api/types');
      
      // Prefetch next page if on first page
      const currentPage = window.GABI_STATE?.page || 1;
      if (currentPage === 1) {
        const params = new URLSearchParams(window.location.search);
        params.set('page', '2');
        this.prefetch(`/api/search?${params.toString()}`);
      }
    }
  };

  // =============================================================================
  // GLOBAL ERROR HANDLING
  // =============================================================================

  function setupGlobalErrorHandling() {
    // Unhandled promise rejections
    window.addEventListener('unhandledrejection', (e) => {
      console.error('Unhandled rejection:', e.reason);
      if (e.reason?.name === 'TypeError' && e.reason?.message?.includes('fetch')) {
        showToast('Erro de conexão. Verifique sua internet.', 'error');
      }
    });

    // Global errors
    window.addEventListener('error', (e) => {
      console.error('Global error:', e.error);
      if (e.message?.includes('ResizeObserver')) {
        // Ignore ResizeObserver loop errors (common false positive)
        e.preventDefault();
      }
    });

    // Override fetch with error handling
    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
      try {
        const response = await originalFetch.apply(this, args);
        if (!response.ok && response.status >= 500) {
          console.warn(`Server error ${response.status} for:`, args[0]);
        }
        return response;
      } catch (err) {
        if (err.name === 'TypeError') {
          showToast('Erro de rede. Tente novamente.', 'error');
        }
        throw err;
      }
    };
  }

  // =============================================================================
  // STICKY SEARCH HEADER
  // =============================================================================

  const StickyHeader = {
    hero: null,
    searchbox: null,
    
    init() {
      this.hero = document.querySelector('.hero');
      this.searchbox = document.querySelector('.searchbox');
      if (!this.hero || !this.searchbox) return;

      const observer = new IntersectionObserver(
        ([entry]) => {
          this.searchbox.classList.toggle('is-sticky', !entry.isIntersecting);
        },
        { threshold: 0, rootMargin: '-80px 0px 0px 0px' }
      );
      
      observer.observe(this.hero);
    }
  };

  // =============================================================================
  // MAIN INITIALIZATION
  // =============================================================================

  function initApp() {
    // Initialize all subsystems
    ThemeManager.init();
    ToastSystem.init();
    BackToTop.init();
    KeyboardShortcuts.init();
    LazyRenderer.init();
    StickyHeader.init();
    setupGlobalErrorHandling();

    // Create accessibility live region
    const liveRegion = document.createElement('div');
    liveRegion.id = 'a11y-live-region';
    liveRegion.setAttribute('aria-live', 'polite');
    liveRegion.setAttribute('aria-atomic', 'true');
    liveRegion.className = 'sr-only';
    document.body.appendChild(liveRegion);

    // Prefetch background data
    PrefetchManager.prefetchInitial();

    // Load URL state
    const urlState = UrlState.loadToState();
    
    // Apply URL state to form
    if (urlState.q) {
      const qInput = document.getElementById('q');
      if (qInput) qInput.value = urlState.q;
    }
    if (urlState.section) {
      const sectionSelect = document.getElementById('section');
      if (sectionSelect) sectionSelect.value = urlState.section;
    }
    if (urlState.type) {
      const typeSelect = document.getElementById('type');
      if (typeSelect) typeSelect.value = urlState.type;
    }
    if (urlState.dfrom) {
      const dfrom = document.getElementById('dfrom');
      if (dfrom) dfrom.value = urlState.dfrom;
    }
    if (urlState.dto) {
      const dto = document.getElementById('dto');
      if (dto) dto.value = urlState.dto;
    }

    // Expose global utilities
    window.GABI_UTILS = {
      debounce,
      throttle,
      escapeHtml,
      formatDate,
      formatNumber,
      copyToClipboard,
      shareDocument,
      parseHashParams,
      updateUrlState,
      withRetry,
      printDocument,
      showToast,
      A11y,
      SkeletonLoader,
      UrlState,
      ThemeManager
    };

    // Return initial state for app bootstrap
    return { urlState };
  }

  // Auto-init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }

  // Expose init for manual call
  window.initApp = initApp;

})();
