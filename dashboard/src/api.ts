import { BotStatus, ActiveDownloadItem, DatabaseStats, UserItem, LogEntry } from './types';

// Detect default backend URL based on environment
export const getDefaultApiBase = (): string => {
  const saved = localStorage.getItem('tbot_custom_api_url');
  if (saved) return saved.replace(/\/+$/, '');
  
  // If running on Vite dev server
  if (window.location.port === '3000') {
    return 'http://localhost:8080';
  }
  // Otherwise default to current origin (works when served from same backend)
  return window.location.origin;
};

let currentApiBase = getDefaultApiBase();

export const setApiBase = (url: string) => {
  currentApiBase = url.replace(/\/+$/, '');
  localStorage.setItem('tbot_custom_api_url', currentApiBase);
};

export const getApiBase = () => currentApiBase;

export const getToken = (): string | null => {
  return localStorage.getItem('tbot_admin_token');
};

export const setToken = (token: string) => {
  localStorage.setItem('tbot_admin_token', token);
};

export const clearToken = () => {
  localStorage.removeItem('tbot_admin_token');
};

// Generic authenticated fetch helper
const request = async <T>(endpoint: string, options: RequestInit = {}): Promise<T> => {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const url = `${currentApiBase}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new Event('auth:unauthorized'));
    throw new Error('Session expired or unauthorized. Please log in again.');
  }

  if (!response.ok) {
    let errorMsg = `HTTP Error ${response.status}`;
    try {
      const errData = await response.json();
      errorMsg = errData.message || errData.error || errorMsg;
    } catch {
      // ignore
    }
    throw new Error(errorMsg);
  }

  return response.json();
};

export const api = {
  // 1. Auth
  async login(password: string): Promise<{ success: boolean; token: string }> {
    const data = await request<{ success: boolean; token: string }>('/api/admin/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    });
    if (data.token) {
      setToken(data.token);
    }
    return data;
  },

  logout() {
    clearToken();
  },

  // 2. Status & Health
  async getStatus(): Promise<BotStatus> {
    return request<BotStatus>('/api/admin/status');
  },

  // 3. Bot Controls
  async togglePause(): Promise<{ success: boolean; is_paused: boolean }> {
    return request<{ success: boolean; is_paused: boolean }>('/api/admin/control', {
      method: 'POST',
      body: JSON.stringify({ action: 'toggle_pause' }),
    });
  },

  async setPause(paused: boolean): Promise<{ success: boolean; is_paused: boolean }> {
    return request<{ success: boolean; is_paused: boolean }>('/api/admin/control', {
      method: 'POST',
      body: JSON.stringify({ action: paused ? 'pause' : 'resume' }),
    });
  },

  async setMaintenance(enabled: boolean, message?: string): Promise<{ success: boolean; maintenance_mode: boolean }> {
    return request<{ success: boolean; maintenance_mode: boolean }>('/api/admin/control', {
      method: 'POST',
      body: JSON.stringify({ action: 'set_maintenance', enabled, message }),
    });
  },

  // 4. Active Downloads
  async getActiveDownloads(): Promise<{ active_downloads: ActiveDownloadItem[]; count: number }> {
    return request<{ active_downloads: ActiveDownloadItem[]; count: number }>('/api/admin/active-downloads');
  },

  // 5. Cancel Task
  async cancelTask(taskId: string): Promise<{ success: boolean; message: string }> {
    return request<{ success: boolean; message: string }>('/api/admin/cancel-task', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    });
  },

  // 6. Clear Queue
  async clearQueue(queueType: string = 'all'): Promise<{ success: boolean; removed_jobs: number }> {
    return request<{ success: boolean; removed_jobs: number }>('/api/admin/clear-queue', {
      method: 'POST',
      body: JSON.stringify({ queue_type: queueType }),
    });
  },

  // 7. Database Stats
  async getStats(): Promise<DatabaseStats> {
    return request<DatabaseStats>('/api/admin/stats');
  },

  // 8. User Management
  async getUsers(page = 1, limit = 20, search = ''): Promise<{ users: UserItem[]; total: number }> {
    const params = new URLSearchParams({
      page: String(page),
      limit: String(limit),
      search,
    });
    return request<{ users: UserItem[]; total: number }>(`/api/admin/users?${params.toString()}`);
  },

  async toggleUserPremium(userId: number, isPremium: boolean, dailyLimit: number): Promise<{ success: boolean }> {
    return request<{ success: boolean }>(`/api/admin/users/${userId}/premium`, {
      method: 'POST',
      body: JSON.stringify({ is_premium: isPremium, daily_limit: dailyLimit }),
    });
  },

  // 9. Real-time Logs
  async getLogs(level = 'ALL', search = '', limit = 150): Promise<{ logs: LogEntry[]; total_buffered: number }> {
    const params = new URLSearchParams({
      level,
      search,
      limit: String(limit),
    });
    return request<{ logs: LogEntry[]; total_buffered: number }>(`/api/admin/logs?${params.toString()}`);
  },
};
