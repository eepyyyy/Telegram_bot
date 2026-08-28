import React, { useState, useEffect, useRef } from 'react';
import { LogEntry } from '../types';
import { api } from '../api';
import { Terminal, Search, ArrowDown } from 'lucide-react';

export const LogTerminal: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [level, setLevel] = useState<string>('ALL');
  const [search, setSearch] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const fetchLogs = async () => {
    try {
      const data = await api.getLogs(level, search, 200);
      setLogs(data.logs);
    } catch (err) {
      console.error('Failed to fetch logs:', err);
    }
  };

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 2500);
    return () => clearInterval(interval);
  }, [level, search]);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  return (
    <div className="mt-card">
      <div className="card-header">
        <div className="card-title">
          <Terminal size={17} />
          <span>Real-time Application Logs ({logs.length})</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          {/* Level Filters */}
          {(['ALL', 'INFO', 'WARNING', 'ERROR'] as const).map((lvl) => (
            <button
              key={lvl}
              className={`mt-btn ${level === lvl ? 'primary' : ''}`}
              style={{ padding: '0.25rem 0.6rem', fontSize: '0.72rem' }}
              onClick={() => setLevel(lvl)}
            >
              {lvl}
            </button>
          ))}

          {/* Auto-scroll toggle */}
          <button
            className={`mt-btn ${autoScroll ? 'success' : ''}`}
            style={{ padding: '0.25rem 0.6rem', fontSize: '0.72rem' }}
            onClick={() => setAutoScroll(!autoScroll)}
            title="Toggle automatic bottom scroll"
          >
            <ArrowDown size={12} />
            <span>{autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}</span>
          </button>
        </div>
      </div>

      {/* Search Filter */}
      <div style={{ marginBottom: '0.75rem', position: 'relative' }}>
        <Search size={14} style={{ position: 'absolute', left: '10px', top: '10px', color: 'var(--sub-color)' }} />
        <input
          type="text"
          className="mt-input"
          style={{ paddingLeft: '32px', padding: '0.45rem 2rem', fontSize: '0.78rem' }}
          placeholder="Filter log messages by keyword (e.g. gamdl, error, user_id)..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Terminal Viewport */}
      <div ref={scrollRef} className="terminal-window">
        {logs.length === 0 ? (
          <div style={{ color: 'var(--sub-color)', padding: '2rem', textAlign: 'center', fontSize: '0.8rem' }}>
            No log entries found matching the filter criteria.
          </div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className="log-row">
              <span className="log-time">[{log.timestamp}]</span>
              <span className={`log-level ${log.level}`}>{log.level}</span>
              <span style={{ color: 'var(--sub-color)', flexShrink: 0 }}>[{log.logger}]</span>
              <span className="log-msg">{log.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
