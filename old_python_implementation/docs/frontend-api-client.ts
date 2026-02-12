/**
 * GABI API Client
 * 
 * Axios-based API client with auth interceptors and error handling.
 * Copy this file to: frontend/src/lib/api/client.ts
 */

import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { toast } from 'sonner';

// Environment configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Custom error class for API errors
export class ApiError extends Error {
  constructor(
    public statusCode: number,
    public code: string,
    message: string,
    public requestId?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// Token management
class TokenManager {
  private token: string | null = null;
  private readonly STORAGE_KEY = 'gabi_access_token';

  getToken(): string | null {
    if (!this.token) {
      this.token = localStorage.getItem(this.STORAGE_KEY);
    }
    return this.token;
  }

  setToken(token: string): void {
    this.token = token;
    localStorage.setItem(this.STORAGE_KEY, token);
  }

  clearToken(): void {
    this.token = null;
    localStorage.removeItem(this.STORAGE_KEY);
  }
}

export const tokenManager = new TokenManager();

// Create axios instance
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor - add auth token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = tokenManager.getToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - handle errors
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response) {
      const data = error.response.data as any;
      const apiError = new ApiError(
        error.response.status,
        data?.error?.code || 'UNKNOWN_ERROR',
        data?.error?.message || data?.message || 'An error occurred',
        data?.error?.request_id
      );

      // Handle specific error cases
      switch (error.response.status) {
        case 401:
          tokenManager.clearToken();
          toast.error('Session expired. Please log in again.');
          window.location.href = '/login';
          break;
        case 403:
          toast.error('Permission denied');
          break;
        case 404:
          toast.error('Resource not found');
          break;
        case 429:
          toast.error('Rate limit exceeded. Please try again later.');
          break;
        case 500:
        case 502:
        case 503:
          toast.error('Server error. Please try again later.');
          break;
      }

      return Promise.reject(apiError);
    }

    // Network errors
    if (error.code === 'ECONNABORTED') {
      toast.error('Request timeout. Please check your connection.');
    } else if (!error.response) {
      toast.error('Network error. Please check your connection.');
    }

    return Promise.reject(error);
  }
);

// Health check helper
export async function checkApiHealth(): Promise<boolean> {
  try {
    // Use the public health endpoint
    const response = await axios.get(`${API_BASE_URL.replace('/api/v1', '')}/health/live`, {
      timeout: 5000,
    });
    return response.status === 200;
  } catch {
    return false;
  }
}
