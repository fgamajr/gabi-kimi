/**
 * Componente de detalhes da fonte
 */
export class SourceDetail {
  constructor(container) {
    this.container = container;
    this.sourceId = null;
  }

  render(detail) {
    this.sourceId = detail.id;
    
    const title = document.getElementById('detail-title');
    const content = document.getElementById('detail-content');
    
    title.textContent = detail.name;
    
    content.innerHTML = `
      ${this.renderMetadata(detail)}
      ${this.renderLinks(detail.links, detail.metadata)}
    `;
  }

  renderMetadata(detail) {
    const { metadata, strategy, provider, enabled } = detail;
    
    return `
      <div class="metadata-section">
        <h3>Informações</h3>
        <div class="metadata-grid">
          <div class="metadata-item">
            <div class="metadata-label">Provedor</div>
            <div class="metadata-value">${this.escapeHtml(provider)}</div>
          </div>
          <div class="metadata-item">
            <div class="metadata-label">Estratégia</div>
            <div class="metadata-value">${this.escapeHtml(strategy)}</div>
          </div>
          <div class="metadata-item">
            <div class="metadata-label">Status</div>
            <div class="metadata-value">${enabled ? '✅ Ativo' : '⏸️ Inativo'}</div>
          </div>
          ${metadata?.lastRefreshed ? `
          <div class="metadata-item">
            <div class="metadata-label">Última Atualização</div>
            <div class="metadata-value">${this.formatDate(metadata.lastRefreshed)}</div>
          </div>
          ` : ''}
          ${metadata?.domain ? `
          <div class="metadata-item">
            <div class="metadata-label">Domínio</div>
            <div class="metadata-value">${this.escapeHtml(metadata.domain)}</div>
          </div>
          ` : ''}
          ${metadata?.jurisdiction ? `
          <div class="metadata-item">
            <div class="metadata-label">Jurisdição</div>
            <div class="metadata-value">${this.escapeHtml(metadata.jurisdiction)}</div>
          </div>
          ` : ''}
          ${metadata?.category ? `
          <div class="metadata-item">
            <div class="metadata-label">Categoria</div>
            <div class="metadata-value">${this.escapeHtml(metadata.category)}</div>
          </div>
          ` : ''}
        </div>
        ${metadata?.discoveryNotice ? `
        <div class="discovery-notice" style="margin-top: 1rem; padding: 0.75rem; background: var(--surface-hover); border-radius: 8px; font-size: 0.875rem; color: var(--text-secondary);">
          ℹ️ ${this.escapeHtml(metadata.discoveryNotice)}
        </div>
        ` : ''}
      </div>
      
      ${detail.description ? `
      <div class="metadata-section">
        <h3>Descrição</h3>
        <p style="color: var(--text-secondary); line-height: 1.6;">
          ${this.escapeHtml(detail.description)}
        </p>
      </div>
      ` : ''}
    `;
  }

  renderLinks(links, metadata) {
    const notice = metadata?.discoveryNotice;
    if (!links || links.length === 0) {
      return `
        <div class="metadata-section">
          <h3>Links Descobertos</h3>
          <div class="empty-state">
            <div class="empty-state-icon">🔗</div>
            <p>${notice ? this.escapeHtml(notice) : 'Nenhum link descoberto ainda'}</p>
            ${!notice ? `<p style="font-size: 0.875rem; margin-top: 0.5rem;">Clique em "Atualizar" para executar o discovery</p>` : ''}
          </div>
        </div>
      `;
    }

    const linksHtml = links.map(link => `
      <div class="link-item">
        <div class="link-url">${this.escapeHtml(link.url)}</div>
        <div class="link-meta">
          <span>📅 ${this.formatDate(link.discoveredAt)}</span>
          ${link.etag ? `<span>🏷️ ETag: ${this.truncate(link.etag, 20)}</span>` : ''}
        </div>
      </div>
    `).join('');

    return `
      <div class="metadata-section">
        <h3>Links Descobertos (${links.length})</h3>
        <div class="links-list">
          ${linksHtml}
        </div>
      </div>
    `;
  }

  formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  truncate(str, maxLength) {
    if (!str) return '';
    if (str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
  }

  escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}
