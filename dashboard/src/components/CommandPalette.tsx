import React, { useState, useEffect, useRef } from 'react';
import { NavTabId } from './Navbar';
import { 
  Terminal, 
  Pause, 
  Play, 
  AlertTriangle, 
  Trash2, 
  Layers, 
  LogOut, 
  Server,
  Activity,
  Download,
  Sparkles,
  Users,
  ScrollText,
} from 'lucide-react';

interface CommandItem {
  id: string;
  title: string;
  category: string;
  icon: React.ReactNode;
  action: () => void;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectTab?: (tab: NavTabId) => void;
  onTogglePause: () => void;
  onToggleMaintenance: () => void;
  onClearQueue: (type: string) => void;
  onThemeChange: (theme: string) => void;
  onOpenApiSettings: () => void;
  onLogout: () => void;
  isPaused: boolean;
  isMaintenance: boolean;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onSelectTab,
  onTogglePause,
  onToggleMaintenance,
  onClearQueue,
  onThemeChange,
  onOpenApiSettings,
  onLogout,
  isPaused,
  isMaintenance,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands: CommandItem[] = [
    ...(onSelectTab ? [
      {
        id: 'nav-overview',
        title: 'Switch Tab: Overview (Real-time Operations)',
        category: 'Navigation',
        icon: <Activity size={16} />,
        action: () => {
          onSelectTab('overview');
          onClose();
        },
      },
      {
        id: 'nav-downloads',
        title: 'Switch Tab: Recent Downloads History & Telemetry',
        category: 'Navigation',
        icon: <Download size={16} />,
        action: () => {
          onSelectTab('downloads');
          onClose();
        },
      },
      {
        id: 'nav-artist-cache',
        title: 'Switch Tab: Artist Discography Cacher',
        category: 'Navigation',
        icon: <Sparkles size={16} />,
        action: () => {
          onSelectTab('artist_cache');
          onClose();
        },
      },
      {
        id: 'nav-database',
        title: 'Switch Tab: Users & Catalog Database',
        category: 'Navigation',
        icon: <Users size={16} />,
        action: () => {
          onSelectTab('database');
          onClose();
        },
      },
      {
        id: 'nav-logs',
        title: 'Switch Tab: Real-time Terminal Log Stream',
        category: 'Navigation',
        icon: <ScrollText size={16} />,
        action: () => {
          onSelectTab('logs');
          onClose();
        },
      },
    ] : []),
    {
      id: 'toggle-pause',
      title: isPaused ? 'Resume All Download Queues' : 'Emergency Pause All Queues',
      category: 'Bot Controls',
      icon: isPaused ? <Play size={16} /> : <Pause size={16} />,
      action: () => {
        onTogglePause();
        onClose();
      },
    },
    {
      id: 'toggle-maint',
      title: isMaintenance ? 'Turn OFF Maintenance Mode' : 'Turn ON Maintenance Mode',
      category: 'Bot Controls',
      icon: <AlertTriangle size={16} />,
      action: () => {
        onToggleMaintenance();
        onClose();
      },
    },
    {
      id: 'clear-all',
      title: 'Purge All Pending Queues',
      category: 'Queue Management',
      icon: <Trash2 size={16} />,
      action: () => {
        onClearQueue('all');
        onClose();
      },
    },
    {
      id: 'clear-alac',
      title: 'Clear ALAC / Lossless Queue',
      category: 'Queue Management',
      icon: <Trash2 size={16} />,
      action: () => {
        onClearQueue('alac');
        onClose();
      },
    },
    {
      id: 'clear-aac',
      title: 'Clear AAC Queue',
      category: 'Queue Management',
      icon: <Trash2 size={16} />,
      action: () => {
        onClearQueue('aac');
        onClose();
      },
    },
    {
      id: 'theme-serika',
      title: 'Theme: Serika Dark (Default Monkeytype)',
      category: 'Appearance',
      icon: <Layers size={16} />,
      action: () => {
        onThemeChange('serika_dark');
        onClose();
      },
    },
    {
      id: 'theme-carbon',
      title: 'Theme: Carbon',
      category: 'Appearance',
      icon: <Layers size={16} />,
      action: () => {
        onThemeChange('carbon');
        onClose();
      },
    },
    {
      id: 'theme-matrix',
      title: 'Theme: Matrix',
      category: 'Appearance',
      icon: <Layers size={16} />,
      action: () => {
        onThemeChange('matrix');
        onClose();
      },
    },
    {
      id: 'theme-dracula',
      title: 'Theme: Dracula',
      category: 'Appearance',
      icon: <Layers size={16} />,
      action: () => {
        onThemeChange('dracula');
        onClose();
      },
    },
    {
      id: 'api-settings',
      title: 'Configure Backend Server API URL',
      category: 'Connection',
      icon: <Server size={16} />,
      action: () => {
        onOpenApiSettings();
        onClose();
      },
    },
    {
      id: 'logout',
      title: 'Log out of Control Plane',
      category: 'Account',
      icon: <LogOut size={16} />,
      action: () => {
        onLogout();
        onClose();
      },
    },
  ];

  const filteredCommands = commands.filter(
    (c) =>
      c.title.toLowerCase().includes(query.toLowerCase()) ||
      c.category.toLowerCase().includes(query.toLowerCase())
  );

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredCommands.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % Math.max(1, filteredCommands.length));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action();
      }
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-content"
        style={{ maxWidth: '560px', padding: '1.25rem' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', borderBottom: '1px solid var(--sub-color)', paddingBottom: '0.75rem' }}>
          <Terminal size={18} style={{ color: 'var(--main-color)' }} />
          <input
            ref={inputRef}
            type="text"
            className="mt-input"
            style={{ border: 'none', background: 'transparent', padding: '0.2rem', fontSize: '1rem', boxShadow: 'none' }}
            placeholder="Type a command or search action..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <kbd>ESC</kbd>
        </div>

        {/* Command list */}
        <div style={{ maxHeight: '320px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          {filteredCommands.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--sub-color)', fontSize: '0.82rem' }}>
              No commands found matching "{query}"
            </div>
          ) : (
            filteredCommands.map((cmd, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={cmd.id}
                  onClick={() => cmd.action()}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.65rem 0.85rem',
                    borderRadius: 'var(--border-radius)',
                    backgroundColor: isSelected ? 'var(--sub-alt-color)' : 'transparent',
                    borderLeft: isSelected ? '3px solid var(--main-color)' : '3px solid transparent',
                    cursor: 'pointer',
                    transition: 'all 0.1s ease',
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <span style={{ color: isSelected ? 'var(--main-color)' : 'var(--sub-color)' }}>
                      {cmd.icon}
                    </span>
                    <span style={{ fontSize: '0.85rem', fontWeight: isSelected ? 600 : 400, color: isSelected ? 'var(--text-color)' : 'var(--sub-color)' }}>
                      {cmd.title}
                    </span>
                  </div>
                  <span style={{ fontSize: '0.7rem', color: 'var(--sub-color)', textTransform: 'uppercase' }}>
                    {cmd.category}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
