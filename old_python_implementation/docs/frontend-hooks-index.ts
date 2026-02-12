/**
 * GABI Hooks Module - Barrel Exports
 * 
 * Copy this file to: frontend/src/hooks/index.ts
 */

// Dashboard hooks
export {
  useDashboardData,
  useDashboardStats,
  usePipeline,
  useActivity,
  useHealth,
  useSources,
  useTriggerIngestion,
  useSyncSource,
  DASHBOARD_KEYS,
} from './useDashboard';

// Sources hooks
export {
  useSourcesList,
  useSource,
  useSourceStatus,
  useToggleSourceStatus,
} from './useSources';
