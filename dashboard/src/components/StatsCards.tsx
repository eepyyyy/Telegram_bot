import React from 'react';
import { BotStatus, DatabaseStats } from '../types';
import { DownloadCloud, ListOrdered, Users, HardDrive, Zap } from 'lucide-react';

interface StatsCardsProps {
  status: BotStatus | null;
  dbStats: DatabaseStats | null;
}

export const StatsCards: React.FC<StatsCardsProps> = ({ status, dbStats }) => {
  const activeCount = status?.active_downloads_count ?? 0;
  const queues = status?.queues ?? { alac: 0, lossless: 0, aac: 0, atmos: 0, mv: 0, total: 0 };
  const usersCount = dbStats?.total_users ?? 0;
  const premiumCount = dbStats?.premium_users ?? 0;
  const downloadsToday = dbStats?.downloads_today ?? 0;
  const totalDownloads = dbStats?.total_downloads ?? 0;
  const totalSizeGb = dbStats?.total_size_gb ?? 0;
  const totalTracks = dbStats?.total_tracks ?? 0;

  return (
    <div className="stats-grid">
      {/* 1. Active Downloads */}
      <div className="mt-card stat-item">
        <div className="card-header" style={{ marginBottom: '0.4rem' }}>
          <span className="stat-label">Active Downloads</span>
          <DownloadCloud size={17} style={{ color: 'var(--main-color)' }} />
        </div>
        <div className="stat-value accent">
          {activeCount}
          <span className="stat-unit">{activeCount === 1 ? 'task' : 'tasks'}</span>
        </div>
        <span style={{ fontSize: '0.74rem', color: 'var(--sub-color)' }}>
          {activeCount > 0 ? '⚡ live download in progress' : 'workers idle and ready'}
        </span>
      </div>

      {/* 2. Queue Depth */}
      <div className="mt-card stat-item">
        <div className="card-header" style={{ marginBottom: '0.4rem' }}>
          <span className="stat-label">Pending Queues</span>
          <ListOrdered size={17} style={{ color: 'var(--main-color)' }} />
        </div>
        <div className="stat-value">
          {queues.total}
          <span className="stat-unit">waiting</span>
        </div>
        <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>
          ALAC:{queues.alac} · LOSSLESS:{queues.lossless} · AAC:{queues.aac} · ATMOS:{queues.atmos} · MV:{queues.mv}
        </span>
      </div>

      {/* 3. Today vs Total Downloads */}
      <div className="mt-card stat-item">
        <div className="card-header" style={{ marginBottom: '0.4rem' }}>
          <span className="stat-label">Today's Activity</span>
          <Zap size={17} style={{ color: 'var(--main-color)' }} />
        </div>
        <div className="stat-value accent">
          {downloadsToday}
          <span className="stat-unit">today</span>
        </div>
        <span style={{ fontSize: '0.74rem', color: 'var(--sub-color)' }}>
          {totalDownloads.toLocaleString()} all-time downloaded
        </span>
      </div>

      {/* 4. Total Users */}
      <div className="mt-card stat-item">
        <div className="card-header" style={{ marginBottom: '0.4rem' }}>
          <span className="stat-label">Bot Users</span>
          <Users size={17} style={{ color: 'var(--main-color)' }} />
        </div>
        <div className="stat-value">
          {usersCount}
          <span className="stat-unit">total</span>
        </div>
        <span style={{ fontSize: '0.74rem', color: 'var(--sub-color)' }}>
          💎 {premiumCount} VIP/Premium users
        </span>
      </div>

      {/* 5. Storage / Tracks */}
      <div className="mt-card stat-item">
        <div className="card-header" style={{ marginBottom: '0.4rem' }}>
          <span className="stat-label">Library Storage</span>
          <HardDrive size={17} style={{ color: 'var(--main-color)' }} />
        </div>
        <div className="stat-value">
          {totalSizeGb}
          <span className="stat-unit">GB</span>
        </div>
        <span style={{ fontSize: '0.74rem', color: 'var(--sub-color)' }}>
          {totalTracks.toLocaleString()} cached tracks / albums
        </span>
      </div>
    </div>
  );
};
