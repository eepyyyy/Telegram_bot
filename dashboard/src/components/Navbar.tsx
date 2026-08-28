import React, { useState } from 'react';
import { BotStatus } from '../types';
import { 
  Bot, 
  Pause, 
  Play, 
  AlertTriangle, 
  LogOut, 
  Terminal, 
  Moon, 
  Layers,
  Server
} from 'lucide-react';

interface NavbarProps {
  status: BotStatus | null;
  onTogglePause: () => void;
  onToggleMaintenance: () => void;
  onOpenCommandPalette: () => void;
  onOpenApiSettings: () => void;
  onLogout: () => void;
  currentTheme: string;
  onThemeChange: (theme: string) => void;
  isPausedLoading: boolean;
}

const formatUptime = (totalSeconds: number): string => {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${hours}h ${minutes}m ${seconds}s`;
};

const THEMES = [
  { id: 'serika_dark', name: 'serika dark' },
  { id: 'carbon', name: 'carbon' },
  { id: 'dracula', name: 'dracula' },
  { id: 'matrix', name: 'matrix' },
  { id: '8008', name: '8008' },
];

export const Navbar: React.FC<NavbarProps> = ({
  status,
  onTogglePause,
  onToggleMaintenance,
  onOpenCommandPalette,
  onOpenApiSettings,
  onLogout,
  currentTheme,
  onThemeChange,
  isPausedLoading,
}) => {
  const [showThemePicker, setShowThemePicker] = useState(false);

  const isPaused = status?.is_paused ?? false;
  const isMaintenance = status?.maintenance_mode ?? false;
  const uptime = status?.system?.uptime_seconds ?? 0;

  return (
    <header className="header-nav">
      {/* Brand & Status Pill */}
      <div className="logo-group" onClick={onOpenCommandPalette} title="Open Command Palette (Ctrl+K)">
        <Bot className="logo-icon" />
        <div>
          <h1 className="logo-title">
            tbot<span>.control</span>
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.2rem' }}>
            <span className="status-pill">
              <span className={`status-dot ${isPaused ? 'paused' : isMaintenance ? 'danger' : 'online'}`} />
              {isPaused ? 'QUEUES PAUSED' : isMaintenance ? 'MAINTENANCE' : 'RUNNING LIVE'}
            </span>
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>
              up: {formatUptime(uptime)}
            </span>
          </div>
        </div>
      </div>

      {/* Control Actions */}
      <div className="nav-actions">
        {/* Emergency Pause / Resume Master Button */}
        <button
          className={`mt-btn ${isPaused ? 'danger-active' : 'primary'}`}
          onClick={onTogglePause}
          disabled={isPausedLoading}
          style={{ minWidth: '165px', justifyContent: 'center' }}
          title="Toggle download queues (Tab+Enter)"
        >
          {isPaused ? <Play size={16} /> : <Pause size={16} />}
          <span>{isPaused ? 'RESUME QUEUES' : 'PAUSE QUEUES'}</span>
          <kbd className="kbd-accent" style={{ marginLeft: '4px', fontSize: '0.65rem' }}>Tab+↵</kbd>
        </button>

        {/* Maintenance Mode Toggle */}
        <button
          className={`mt-btn ${isMaintenance ? 'danger' : ''}`}
          onClick={onToggleMaintenance}
          title="Toggle maintenance mode for bot users"
        >
          <AlertTriangle size={15} />
          <span>{isMaintenance ? 'MAINTENANCE: ON' : 'MAINTENANCE'}</span>
        </button>

        {/* Command Palette Trigger */}
        <button className="mt-btn" onClick={onOpenCommandPalette} title="Command Palette">
          <Terminal size={15} />
          <span>COMMANDS</span>
          <kbd>Ctrl+K</kbd>
        </button>

        {/* Theme Picker Dropdown */}
        <div style={{ position: 'relative' }}>
          <button
            className="mt-btn"
            onClick={() => setShowThemePicker(!showThemePicker)}
            title="Switch Theme"
          >
            <Moon size={15} />
            <span>{currentTheme}</span>
          </button>

          {showThemePicker && (
            <div
              style={{
                position: 'absolute',
                top: '115%',
                right: 0,
                backgroundColor: 'var(--bg-color)',
                border: '1px solid var(--sub-color)',
                borderRadius: 'var(--border-radius)',
                padding: '0.5rem',
                zIndex: 100,
                boxShadow: 'var(--shadow-sm)',
                minWidth: '140px',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.25rem',
              }}
            >
              {THEMES.map((theme) => (
                <button
                  key={theme.id}
                  className={`mt-btn ${currentTheme === theme.id ? 'primary' : ''}`}
                  style={{ width: '100%', justifyContent: 'flex-start', padding: '0.4rem 0.6rem' }}
                  onClick={() => {
                    onThemeChange(theme.id);
                    setShowThemePicker(false);
                  }}
                >
                  <Layers size={13} />
                  <span>{theme.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* API Backend Host Config (for Cloudflare Pages users) */}
        <button className="mt-btn" onClick={onOpenApiSettings} title="Configure Backend API URL">
          <Server size={15} />
        </button>

        {/* Logout */}
        <button className="mt-btn" onClick={onLogout} title="Log out of control plane">
          <LogOut size={15} />
        </button>
      </div>
    </header>
  );
};
