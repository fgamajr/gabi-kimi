/**
 * Type declarations for Vite environment variables
 * 
 * Add this to: frontend/src/vite-env.d.ts
 * or create: frontend/src/env.d.ts
 */

/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the GABI API */
  readonly VITE_API_URL: string;
  
  /** WebSocket URL for real-time updates (optional) */
  readonly VITE_WS_URL?: string;
  
  /** Application environment */
  readonly VITE_APP_ENV?: 'development' | 'staging' | 'production';
  
  /** Enable mock API (for development) */
  readonly VITE_USE_MOCK_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
