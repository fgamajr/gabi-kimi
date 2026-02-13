import { useState, useCallback } from 'react';

interface PaginationState {
  page: number;
  pageSize: number;
}

interface UsePaginationReturn extends PaginationState {
  setPage: (page: number) => void;
  setPageSize: (pageSize: number) => void;
  nextPage: () => void;
  previousPage: () => void;
  reset: () => void;
  canGoNext: (totalPages: number) => boolean;
  canGoPrevious: () => boolean;
}

export function usePagination(
  initialPage: number = 1,
  initialPageSize: number = 20
): UsePaginationReturn {
  const [state, setState] = useState<PaginationState>({
    page: initialPage,
    pageSize: initialPageSize,
  });

  const setPage = useCallback((page: number) => {
    setState(prev => ({ ...prev, page: Math.max(1, page) }));
  }, []);

  const setPageSize = useCallback((pageSize: number) => {
    setState({
      page: 1, // Reset to first page when changing page size
      pageSize: Math.max(1, pageSize),
    });
  }, []);

  const nextPage = useCallback(() => {
    setState(prev => ({ ...prev, page: prev.page + 1 }));
  }, []);

  const previousPage = useCallback(() => {
    setState(prev => ({ ...prev, page: Math.max(1, prev.page - 1) }));
  }, []);

  const reset = useCallback(() => {
    setState({
      page: initialPage,
      pageSize: initialPageSize,
    });
  }, [initialPage, initialPageSize]);

  const canGoNext = useCallback((totalPages: number): boolean => {
    return state.page < totalPages;
  }, [state.page]);

  const canGoPrevious = useCallback((): boolean => {
    return state.page > 1;
  }, [state.page]);

  return {
    ...state,
    setPage,
    setPageSize,
    nextPage,
    previousPage,
    reset,
    canGoNext,
    canGoPrevious,
  };
}

interface PaginationInfo {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export function usePaginationInfo(
  pagination: PaginationInfo | null | undefined
) {
  const startItem = pagination 
    ? (pagination.page - 1) * pagination.pageSize + 1 
    : 0;
  
  const endItem = pagination
    ? Math.min(pagination.page * pagination.pageSize, pagination.totalItems)
    : 0;

  return {
    startItem,
    endItem,
    totalItems: pagination?.totalItems || 0,
    hasPages: (pagination?.totalPages || 0) > 1,
  };
}
