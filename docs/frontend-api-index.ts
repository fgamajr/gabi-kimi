/**
 * GABI API Module - Barrel Exports
 * 
 * Copy this file to: frontend/src/lib/api/index.ts
 */

// Client and utilities
export { apiClient, tokenManager, ApiError, checkApiHealth } from './client';

// API modules
export { dashboardApi } from './dashboard';
export { sourcesApi } from './sources';

// Types
export type * from './types';
