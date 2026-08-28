import React, { useState } from 'react';
import { QueueStats } from '../types';
import { Layers, Trash2, CheckCircle2 } from 'lucide-react';

interface QueueInspectorProps {
  queues: QueueStats;
  onClearQueue: (queueType: string) => void;
  isClearing: boolean;
}

const QUEUE_TABS = [
  { id: 'all', name: 'ALL QUEUES' },
  { id: 'alac', name: 'ALAC' },
  { id: 'lossless', name: 'LOSSLESS' },
  { id: 'aac', name: 'AAC' },
  { id: 'atmos', name: 'DOLBY ATMOS' },
  { id: 'mv', name: 'MUSIC VIDEO' },
];

export const QueueInspector: React.FC<QueueInspectorProps> = ({
  queues,
  onClearQueue,
  isClearing,
}) => {
  const [selectedTab, setSelectedTab] = useState('all');

  const getCountForTab = (tabId: string): number => {
    if (tabId === 'all') return queues.total;
    if (tabId === 'alac') return queues.alac;
    if (tabId === 'lossless') return queues.lossless;
    if (tabId === 'aac') return queues.aac;
    if (tabId === 'atmos') return queues.atmos;
    if (tabId === 'mv') return queues.mv;
    return 0;
  };

  const selectedCount = getCountForTab(selectedTab);

  return (
    <div className="mt-card">
      <div className="card-header">
        <div className="card-title">
          <Layers size={17} />
          <span>Queue Inspector & Manager</span>
        </div>

        <button
          className="mt-btn danger"
          onClick={() => onClearQueue(selectedTab)}
          disabled={isClearing || selectedCount === 0}
          title={`Purge pending items in ${selectedTab.toUpperCase()}`}
        >
          <Trash2 size={14} />
          <span>{isClearing ? 'Clearing...' : `Clear ${selectedTab.toUpperCase()} (${selectedCount})`}</span>
        </button>
      </div>

      {/* Format Selector Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
        {QUEUE_TABS.map((tab) => {
          const count = getCountForTab(tab.id);
          const isActive = selectedTab === tab.id;
          return (
            <button
              key={tab.id}
              className={`mt-btn ${isActive ? 'primary' : ''}`}
              onClick={() => setSelectedTab(tab.id)}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}
            >
              <span>{tab.name}</span>
              <span
                style={{
                  padding: '1px 5px',
                  borderRadius: '10px',
                  fontSize: '0.68rem',
                  backgroundColor: isActive ? 'var(--bg-color)' : 'var(--sub-color)',
                  color: isActive ? 'var(--main-color)' : 'var(--bg-color)',
                  fontWeight: 700,
                }}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Queue Details Card */}
      <div
        style={{
          backgroundColor: 'var(--bg-color)',
          borderRadius: 'var(--border-radius)',
          padding: '1.25rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-color)' }}>
            Selected Queue: {selectedTab.toUpperCase()}
          </span>
          <span style={{ fontSize: '0.74rem', color: 'var(--sub-color)' }}>
            {selectedCount === 0
              ? 'Queue is currently empty. No user jobs waiting.'
              : `${selectedCount} item(s) waiting in asynchronous queue buffer.`}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span className="status-pill">
            <CheckCircle2 size={13} style={{ color: 'var(--success-color)' }} />
            Worker Cluster Active
          </span>
        </div>
      </div>
    </div>
  );
};
