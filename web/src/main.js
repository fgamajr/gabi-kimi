import { api } from './api.js';
import { SourceList } from './components/source-list.js';
import { SourceDetail } from './components/source-detail.js';

// Initialize components
const sourceList = new SourceList(document.getElementById('source-grid'));
const sourceDetail = new SourceDetail(document.getElementById('detail-panel'));

// DOM elements
const sourceCountEl = document.getElementById('source-count');
const refreshAllBtn = document.getElementById('refresh-all');
const overlay = document.getElementById('overlay');
const closeDetailBtn = document.getElementById('close-detail');

// State
let sources = [];

// Initialize
async function init() {
  try {
    // Check API health
    const isHealthy = await api.health();
    if (!isHealthy) {
      showError('API não está respondendo');
      return;
    }

    // Load sources
    await loadSources();
    
    // Setup event listeners
    setupEventListeners();
  } catch (error) {
    showError(error.message);
  }
}

async function loadSources() {
  try {
    sources = await api.listSources();
    sourceCountEl.textContent = `${sources.length} fontes disponíveis`;
    sourceList.render(sources);
  } catch (error) {
    showError(`Erro ao carregar fontes: ${error.message}`);
  }
}

function setupEventListeners() {
  // Source card click -> show detail
  sourceList.onSourceClick = async (sourceId) => {
    try {
      const detail = await api.getSource(sourceId);
      sourceDetail.render(detail);
      openDetailPanel();
    } catch (error) {
      showError(`Erro ao carregar detalhes: ${error.message}`);
    }
  };

  // Refresh button on card
  sourceList.onRefreshClick = async (sourceId) => {
    try {
      // Start the refresh (enqueue job)
      await api.refreshSource(sourceId);
      
      // Show initial loading state
      sourceList.setRefreshing(sourceId, 'Iniciando...');
      
      // Start polling for job status
      sourceList.startPolling(
        sourceId,
        api,
        // onComplete
        async () => {
          // Reload source details
          const detail = await api.getSource(sourceId);
          sourceList.updateSourceLinks(sourceId, detail.links.length);
          
          // If detail panel is open for this source, update it
          if (sourceDetail.sourceId === sourceId) {
            sourceDetail.render(detail);
          }
        },
        // onError
        (error) => {
          showError(`Erro ao atualizar: ${error.message}`);
          sourceList.stopRefreshing(sourceId);
        }
      );
    } catch (error) {
      showError(`Erro ao atualizar: ${error.message}`);
      sourceList.stopRefreshing(sourceId);
    }
  };

  // Close detail panel
  closeDetailBtn.addEventListener('click', closeDetailPanel);
  overlay.addEventListener('click', closeDetailPanel);

  // Refresh all button
  refreshAllBtn.addEventListener('click', async () => {
    refreshAllBtn.disabled = true;
    refreshAllBtn.innerHTML = '<span class="spinner"></span> Atualizando...';
    
    try {
      let completedCount = 0;
      const totalEnabled = sources.filter(s => s.enabled).length;
      
      for (const source of sources) {
        if (!source.enabled) continue;
        
        // Start refresh for this source
        await api.refreshSource(source.id);
        sourceList.setRefreshing(source.id, 'Na fila...');
        
        // Start polling for this source
        sourceList.startPolling(
          source.id,
          api,
          // onComplete
          () => {
            completedCount++;
            if (completedCount >= totalEnabled) {
              // All done
              refreshAllBtn.disabled = false;
              refreshAllBtn.innerHTML = '🔄 Atualizar Tudo';
              loadSources(); // Reload all sources
            }
          },
          // onError
          () => {
            completedCount++;
            sourceList.stopRefreshing(source.id);
          }
        );
      }
      
      // If no enabled sources, re-enable button
      if (totalEnabled === 0) {
        refreshAllBtn.disabled = false;
        refreshAllBtn.innerHTML = '🔄 Atualizar Tudo';
      }
    } catch (error) {
      showError(`Erro ao atualizar fontes: ${error.message}`);
      refreshAllBtn.disabled = false;
      refreshAllBtn.innerHTML = '🔄 Atualizar Tudo';
    }
  });
}

function openDetailPanel() {
  document.getElementById('detail-panel').classList.add('open');
  document.getElementById('overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeDetailPanel() {
  document.getElementById('detail-panel').classList.remove('open');
  document.getElementById('overlay').classList.remove('open');
  document.body.style.overflow = '';
}

function showError(message) {
  console.error(message);
  const errorDiv = document.createElement('div');
  errorDiv.className = 'error-message';
  errorDiv.textContent = message;
  document.querySelector('.container').prepend(errorDiv);
  
  setTimeout(() => errorDiv.remove(), 5000);
}

// Start
init();
