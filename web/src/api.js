// GABI API Client
const API_BASE = '/api/v1';

/**
 * Fetch wrapper with error handling
 */
async function apiFetch(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const response = await fetch(url, {
    headers: {
      'Accept': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: 'Unknown error' }));
    throw new Error(error.message || `HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * GABI API Client
 */
export const api = {
  /**
   * List all sources
   */
  async listSources() {
    const result = await apiFetch('/sources');
    return result.data;
  },

  /**
   * Get source details
   */
  async getSource(sourceId) {
    const result = await apiFetch(`/sources/${sourceId}`);
    return result.data;
  },

  /**
   * Refresh source discovery (enqueues job)
   */
  async refreshSource(sourceId) {
    const result = await apiFetch(`/sources/${sourceId}/refresh`, {
      method: 'POST',
    });
    return result.data;
  },

  /**
   * Get job status for a source
   */
  async getJobStatus(sourceId) {
    const result = await apiFetch(`/jobs/${sourceId}/status`);
    return result.data;
  },

  /**
   * Health check
   */
  async health() {
    const response = await fetch('/health');
    return response.ok;
  },
};
