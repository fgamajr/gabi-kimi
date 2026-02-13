/**
 * Componente de lista de fontes
 */
export class SourceList {
  constructor(container) {
    this.container = container;
    this.onSourceClick = null;
    this.onRefreshClick = null;
    this.loadingSources = new Set();
    this.refreshingSources = new Map(); // sourceId -> { abortController, pollInterval }
  }

  render(sources) {
    this.container.innerHTML = '';
    
    if (sources.length === 0) {
      this.renderEmpty();
      return;
    }

    sources.forEach(source => {
      const card = this.createCard(source);
      this.container.appendChild(card);
    });
  }

  createCard(source) {
    const card = document.createElement('div');
    card.className = 'source-card';
    card.dataset.sourceId = source.id;
    
    const strategyColors = {
      'static_url': 'blue',
      'url_pattern': 'purple',
      'web_crawl': 'orange',
      'api_pagination': 'green'
    };
    
    const statusBadge = source.enabled 
      ? '<span class="status-badge enabled">● Ativo</span>' 
      : '<span class="status-badge disabled">● Inativo</span>';
    
    card.innerHTML = `
      <div class="source-header">
        <h3 class="source-name">${this.escapeHtml(source.name)} ${statusBadge}</h3>
        <span class="source-strategy">${source.strategy}</span>
      </div>
      <div class="source-provider">${this.escapeHtml(source.provider)}</div>
      <div class="source-meta">
        <span class="source-links-count" id="links-${source.id}">
          ${source.enabled ? 'Clique para ver detalhes' : 'Fonte desativada'}
        </span>
        <button class="btn btn-secondary btn-refresh" data-source-id="${source.id}" ${!source.enabled ? 'disabled' : ''}>
          🔄 Atualizar
        </button>
      </div>
    `;

    // Click on card -> show detail
    card.addEventListener('click', (e) => {
      if (!e.target.closest('.btn-refresh') && this.onSourceClick) {
        this.onSourceClick(source.id);
      }
    });

    // Click on refresh button
    const refreshBtn = card.querySelector('.btn-refresh');
    refreshBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (this.onRefreshClick && !this.loadingSources.has(source.id)) {
        this.onRefreshClick(source.id);
      }
    });

    return card;
  }

  renderEmpty() {
    this.container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📭</div>
        <p>Nenhuma fonte encontrada</p>
      </div>
    `;
  }

  setLoading(sourceId, isLoading) {
    const card = this.container.querySelector(`[data-source-id="${sourceId}"]`);
    if (!card) return;

    const btn = card.querySelector('.btn-refresh');
    
    if (isLoading) {
      this.loadingSources.add(sourceId);
      btn.innerHTML = '<span class="spinner"></span>';
      btn.disabled = true;
      card.classList.add('loading');
    } else {
      this.loadingSources.delete(sourceId);
      btn.innerHTML = '🔄 Atualizar';
      btn.disabled = false;
      card.classList.remove('loading');
    }
  }

  /**
   * Show refresh in progress with polling status
   */
  setRefreshing(sourceId, message, progress = null) {
    const card = this.container.querySelector(`[data-source-id="${sourceId}"]`);
    if (!card) return;

    this.loadingSources.add(sourceId);
    card.classList.add('loading');

    const btn = card.querySelector('.btn-refresh');
    btn.disabled = true;

    const countEl = document.getElementById(`links-${sourceId}`);
    if (countEl) {
      if (progress !== null) {
        countEl.innerHTML = `<span class="spinner"></span> ${message} (${progress}%)`;
      } else {
        countEl.innerHTML = `<span class="spinner"></span> ${message}`;
      }
      countEl.className = 'source-links-count has-links';
    }
  }

  /**
   * Stop refresh state for a source
   */
  stopRefreshing(sourceId) {
    // Cancel any existing polling for this source
    const existing = this.refreshingSources.get(sourceId);
    if (existing) {
      existing.abortController.abort();
      clearInterval(existing.pollInterval);
      this.refreshingSources.delete(sourceId);
    }

    this.setLoading(sourceId, false);
  }

  /**
   * Start polling for job status
   */
  startPolling(sourceId, api, onComplete, onError) {
    // Cancel any existing polling for this source
    this.stopRefreshing(sourceId);

    const abortController = new AbortController();
    const pollInterval = setInterval(async () => {
      try {
        const status = await api.getJobStatus(sourceId);
        
        if (!status) {
          // No job found, might be completed already
          this.stopRefreshing(sourceId);
          if (onComplete) onComplete();
          return;
        }

        const { status: jobStatus, progressPercent, progressMessage, linksDiscovered } = status;

        if (jobStatus === 'processing' || jobStatus === 'pending' || jobStatus === 'queued') {
          // Still running - update UI
          const message = progressMessage || 'Processando...';
          this.setRefreshing(sourceId, message, progressPercent || null);
          
          // Update links count if available
          if (linksDiscovered > 0) {
            this.updateSourceLinks(sourceId, linksDiscovered);
          }
        } else if (jobStatus === 'completed') {
          // Completed successfully
          this.stopRefreshing(sourceId);
          this.updateSourceLinks(sourceId, linksDiscovered || null);
          if (onComplete) onComplete();
        } else if (jobStatus === 'failed' || jobStatus === 'dead') {
          // Failed
          this.stopRefreshing(sourceId);
          if (onError) onError(new Error(`Job failed: ${status.errorMessage || 'Unknown error'}`));
        }
      } catch (error) {
        // Ignore errors during polling, keep trying
        console.warn('Polling error:', error);
      }
    }, 2000); // Poll every 2 seconds

    this.refreshingSources.set(sourceId, { abortController, pollInterval });

    // Cleanup after 10 minutes to prevent indefinite polling
    setTimeout(() => {
      this.stopRefreshing(sourceId);
    }, 10 * 60 * 1000);
  }

  updateSourceLinks(sourceId, count, isRefreshing = false) {
    const countEl = document.getElementById(`links-${sourceId}`);
    if (!countEl) return;

    if (isRefreshing) {
      countEl.innerHTML = '<span class="spinner"></span>';
      countEl.className = 'source-links-count';
    } else if (count !== null) {
      const text = count === 1 ? '1 link descoberto' : `${count} links descobertos`;
      countEl.textContent = text;
      countEl.className = 'source-links-count has-links';
    }
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}
