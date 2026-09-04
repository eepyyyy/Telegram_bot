import React, { useState, useEffect, useCallback } from 'react';
import { BotStatus, ActiveDownloadItem, DatabaseStats } from './types';
import { api, getToken } from './api';
import { Navbar, NavTabId } from './components/Navbar';
import { StatsCards } from './components/StatsCards';
import { ActiveDownloads } from './components/ActiveDownloads';
import { QueueInspector } from './components/QueueInspector';
import { SystemTelemetry } from './components/SystemTelemetry';
import { DatabaseExplorer } from './components/DatabaseExplorer';
import { RecentDownloads } from './components/RecentDownloads';
import { ArtistCacher } from './components/ArtistCacher';
import { LogTerminal } from './components/LogTerminal';
import { CommandPalette } from './components/CommandPalette';
import { LoginModal } from './components/LoginModal';
import { ApiSettingsModal } from './components/ApiSettingsModal';

export const App: React.FC = () => {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(!!getToken());
  const [activeTab, setActiveTab] = useState<NavTabId>(
    (localStorage.getItem('tbot_active_tab') as NavTabId) || 'overview'
  );
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [activeDownloads, setActiveDownloads] = useState<ActiveDownloadItem[]>([]);
  const [dbStats, setDbStats] = useState<DatabaseStats | null>(null);

  const [isPausedLoading, setIsPausedLoading] = useState<boolean>(false);
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null);
  const [isClearingQueue, setIsClearingQueue] = useState<boolean>(false);

  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState<boolean>(false);
  const [isApiSettingsOpen, setIsApiSettingsOpen] = useState<boolean>(false);
  const [theme, setTheme] = useState<string>(localStorage.getItem('tbot_theme') || 'serika_dark');

  // Handle Tab Switch
  const handleTabChange = (tab: NavTabId) => {
    setActiveTab(tab);
    localStorage.setItem('tbot_active_tab', tab);
  };

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('tbot_theme', theme);
  }, [theme]);

  // Auth synchronization
  useEffect(() => {
    const handleUnauthorized = () => {
      setIsAuthenticated(false);
    };
    window.addEventListener('auth:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('auth:unauthorized', handleUnauthorized);
  }, []);

  // Polling data fetcher with independent error resilience
  const refreshData = useCallback(async () => {
    if (!getToken()) return;

    try {
      const results = await Promise.allSettled([
        api.getStatus(),
        api.getActiveDownloads(),
        api.getStats(),
      ]);

      if (results[0].status === 'fulfilled') {
        setStatus(results[0].value);
      }
      if (results[1].status === 'fulfilled') {
        setActiveDownloads(results[1].value.active_downloads);
      }
      if (results[2].status === 'fulfilled') {
        setDbStats(results[2].value);
      }
    } catch (err) {
      console.error('Failed to poll dashboard data:', err);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;

    let timer: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (document.hidden) return;
      refreshData();
      const delay = activeDownloads.length > 0 ? 5000 : 10000;
      timer = setInterval(() => {
        if (!document.hidden) {
          refreshData();
        }
      }, delay);
    };

    const handleVisibilityChange = () => {
      if (timer) clearInterval(timer);
      if (!document.hidden) {
        startPolling();
      }
    };

    startPolling();
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isAuthenticated, refreshData, activeDownloads.length]);

  // Keyboard shortcut listener (Ctrl+K, Shift+Enter, and Number keys 1-5 for tabs)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;

      // Ctrl+K or Cmd+K
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
        return;
      }

      // Shift + Enter for quick pause toggle
      if (e.key === 'Enter' && e.shiftKey) {
        e.preventDefault();
        handleTogglePause();
        return;
      }

      // Tab switcher shortcuts (1-5) when not focused on an input
      if (!isInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (e.key === '1') {
          handleTabChange('overview');
        } else if (e.key === '2') {
          handleTabChange('downloads');
        } else if (e.key === '3') {
          handleTabChange('artist_cache');
        } else if (e.key === '4') {
          handleTabChange('database');
        } else if (e.key === '5') {
          handleTabChange('logs');
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [status]);

  // Control Actions
  const handleTogglePause = async () => {
    setIsPausedLoading(true);
    try {
      const res = await api.togglePause();
      setStatus((prev) => prev ? { ...prev, is_paused: res.is_paused } : null);
      refreshData();
    } catch (err) {
      alert(`Failed to toggle pause: ${err}`);
    } finally {
      setIsPausedLoading(false);
    }
  };

  const handleToggleMaintenance = async () => {
    const newMode = status ? !status.maintenance_mode : true;
    try {
      const res = await api.setMaintenance(newMode);
      setStatus((prev) => prev ? { ...prev, maintenance_mode: res.maintenance_mode } : null);
      refreshData();
    } catch (err) {
      alert(`Failed to toggle maintenance mode: ${err}`);
    }
  };

  const handleCancelTask = async (taskId: string) => {
    setCancellingTaskId(taskId);
    try {
      await api.cancelTask(taskId);
      setActiveDownloads((prev) => prev.filter((item) => item.task_id !== taskId));
      refreshData();
    } catch (err) {
      alert(`Failed to cancel task: ${err}`);
    } finally {
      setCancellingTaskId(null);
    }
  };

  const handleClearQueue = async (queueType: string) => {
    setIsClearingQueue(true);
    try {
      const res = await api.clearQueue(queueType);
      alert(`Successfully purged ${res.removed_jobs} pending download job(s).`);
      refreshData();
    } catch (err) {
      alert(`Failed to clear queue: ${err}`);
    } finally {
      setIsClearingQueue(false);
    }
  };

  const handleLogout = () => {
    api.logout();
    setIsAuthenticated(false);
  };

  if (!isAuthenticated) {
    return <LoginModal onSuccess={() => setIsAuthenticated(true)} />;
  }

  return (
    <div className="app-container">
      {/* 1. Monkeytype Header & Navigation Tabs */}
      <Navbar
        status={status}
        activeTab={activeTab}
        onTabChange={handleTabChange}
        onTogglePause={handleTogglePause}
        onToggleMaintenance={handleToggleMaintenance}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        onOpenApiSettings={() => setIsApiSettingsOpen(true)}
        onLogout={handleLogout}
        currentTheme={theme}
        onThemeChange={setTheme}
        isPausedLoading={isPausedLoading}
      />

      {/* 2. Main Tab Views */}
      {activeTab === 'overview' && (
        <>
          <StatsCards status={status} dbStats={dbStats} />
          <ActiveDownloads
            downloads={activeDownloads}
            onCancelTask={handleCancelTask}
            cancellingTaskId={cancellingTaskId}
          />
          <QueueInspector
            queues={status?.queues || { alac: 0, lossless: 0, aac: 0, atmos: 0, mv: 0, total: 0 }}
            onClearQueue={handleClearQueue}
            isClearing={isClearingQueue}
          />
          <SystemTelemetry system={status?.system || null} />
          <DatabaseExplorer dbStats={dbStats} />
          <LogTerminal />
        </>
      )}

      {activeTab === 'downloads' && (
        <RecentDownloads />
      )}

      {activeTab === 'artist_cache' && (
        <ArtistCacher
          activeDownloads={activeDownloads}
          status={status}
          onRefreshData={refreshData}
        />
      )}

      {activeTab === 'database' && (
        <>
          <StatsCards status={status} dbStats={dbStats} />
          <DatabaseExplorer dbStats={dbStats} />
        </>
      )}

      {activeTab === 'logs' && (
        <LogTerminal />
      )}

      {/* Modals & Dialogs */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        onSelectTab={handleTabChange}
        onTogglePause={handleTogglePause}
        onToggleMaintenance={handleToggleMaintenance}
        onClearQueue={handleClearQueue}
        onThemeChange={setTheme}
        onOpenApiSettings={() => setIsApiSettingsOpen(true)}
        onLogout={handleLogout}
        isPaused={status?.is_paused ?? false}
        isMaintenance={status?.maintenance_mode ?? false}
      />

      <ApiSettingsModal
        isOpen={isApiSettingsOpen}
        onClose={() => setIsApiSettingsOpen(false)}
        onSaved={refreshData}
      />
    </div>
  );
};

