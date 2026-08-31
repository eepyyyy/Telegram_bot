import React, { useState, useEffect, useCallback } from 'react';
import { RecentDownloadsResponse } from '../types';
import { api } from '../api';
import {
  Download,
  Search,
  RefreshCw,
  Zap,
  Crown,
  Disc,
  Music,
  Tv,
  Clock,
} from 'lucide-react';

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

const formatRelativeTime = (isoString: string | null): string => {
  if (!isoString) return 'Unknown';
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (diffInSeconds < 10) return 'Just now';
    if (diffInSeconds < 60) return `${diffInSeconds}s ago`;
    const diffInMinutes = Math.floor(diffInSeconds / 60);
    if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
    const diffInHours = Math.floor(diffInMinutes / 60);
    if (diffInHours < 24) return `${diffInHours}h ago`;
    const diffInDays = Math.floor(diffInHours / 24);
    if (diffInDays < 7) return `${diffInDays}d ago`;
    return date.toLocaleDateString();
  } catch {
    return 'Recent';
  }
};

const getFormatBadgeStyle = (format: string) => {
  const fmt = (format || 'ALAC').toUpperCase();
  switch (fmt) {
    case 'ALAC':
    case 'LOSSLESS':
      return {
        bg: 'rgba(226, 183, 20, 0.15)',
        color: 'var(--main-color)',
        border: '1px solid rgba(226, 183, 20, 0.4)',
        label: 'ALAC LOSSLESS',
        icon: Disc,
      };
    case 'ATMOS':
      return {
        bg: 'rgba(97, 218, 251, 0.15)',
        color: '#61dafb',
        border: '1px solid rgba(97, 218, 251, 0.4)',
        label: 'DOLBY ATMOS',
        icon: Music,
      };
    case 'AAC':
      return {
        bg: 'rgba(189, 147, 249, 0.15)',
        color: '#bd93f9',
        border: '1px solid rgba(189, 147, 249, 0.4)',
        label: 'AAC 256K',
        icon: Music,
      };
    case 'MV':
    case 'VIDEO':
      return {
        bg: 'rgba(255, 121, 198, 0.15)',
        color: '#ff79c6',
        border: '1px solid rgba(255, 121, 198, 0.4)',
        label: 'MUSIC VIDEO',
        icon: Tv,
      };
    default:
      return {
        bg: 'var(--sub-alt-color)',
        color: 'var(--text-color)',
        border: '1px solid var(--sub-color)',
        label: fmt,
        icon: Disc,
      };
  }
};

export const RecentDownloads: React.FC = () => {
  const [data, setData] = useState<RecentDownloadsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [formatFilter, setFormatFilter] = useState('all');
  const [cachedFilter, setCachedFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(25);
  const [selectedArtwork, setSelectedArtwork] = useState<string | null>(null);

  const fetchRecentDownloads = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getRecentDownloads(page, limit, formatFilter, cachedFilter, search);
      setData(res);
    } catch (err) {
      console.error('Failed to load recent downloads:', err);
    } finally {
      setLoading(false);
    }
  }, [page, limit, formatFilter, cachedFilter, search]);

  useEffect(() => {
    fetchRecentDownloads();
  }, [fetchRecentDownloads]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;

  return (
    <div className="mt-card" style={{ gap: '1.25rem' }}>
      {/* 1. Header with Live Status & Refresh */}
      <div className="card-header">
        <div className="card-title">
          <Download size={18} />
          <span>Recent Downloads & Stream Telemetry</span>
          {data && (
            <span
              style={{
                fontSize: '0.72rem',
                padding: '2px 8px',
                borderRadius: '12px',
                backgroundColor: 'var(--sub-alt-color)',
                color: 'var(--main-color)',
                fontWeight: 700,
              }}
            >
              {data.total.toLocaleString()} TOTAL RECORDS
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            className="mt-btn"
            onClick={fetchRecentDownloads}
            disabled={loading}
            title="Refresh recent downloads"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* 2. Top Metric Banner */}
      {data && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '0.85rem',
          }}
        >
          {/* Cache Hit Ratio */}
          <div
            style={{
              backgroundColor: 'var(--bg-color)',
              padding: '0.85rem 1.1rem',
              borderRadius: 'var(--border-radius)',
              border: '1px solid var(--sub-alt-color)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>
                ⚡ CACHE HIT RATIO
              </span>
              <span style={{ fontSize: '0.85rem', color: 'var(--success-color)', fontWeight: 700 }}>
                {data.cache_hit_rate}%
              </span>
            </div>
            <div
              style={{
                width: '100%',
                height: '6px',
                backgroundColor: 'var(--sub-alt-color)',
                borderRadius: '3px',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${Math.min(100, Math.max(0, data.cache_hit_rate))}%`,
                  height: '100%',
                  backgroundColor: 'var(--success-color)',
                  transition: 'width 0.3s ease',
                }}
              />
            </div>
            <span style={{ fontSize: '0.7rem', color: 'var(--sub-color)' }}>
              {data.cached_downloads.toLocaleString()} instant cache deliveries
            </span>
          </div>

          {/* Fresh Downloads */}
          <div
            style={{
              backgroundColor: 'var(--bg-color)',
              padding: '0.85rem 1.1rem',
              borderRadius: 'var(--border-radius)',
              border: '1px solid var(--sub-alt-color)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
            }}
          >
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>
              ⬇ FRESH BOT DOWNLOADS
            </span>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-color)' }}>
              {(data.total_downloads - data.cached_downloads).toLocaleString()}
              <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', marginLeft: '0.35rem' }}>
                items fetched from Apple Music
              </span>
            </div>
          </div>

          {/* Total Processed */}
          <div
            style={{
              backgroundColor: 'var(--bg-color)',
              padding: '0.85rem 1.1rem',
              borderRadius: 'var(--border-radius)',
              border: '1px solid var(--sub-alt-color)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
            }}
          >
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>
              🌐 TOTAL DELIVERIES LOGGED
            </span>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--main-color)' }}>
              {data.total_downloads.toLocaleString()}
              <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', marginLeft: '0.35rem' }}>
                transactions
              </span>
            </div>
          </div>
        </div>
      )}

      {/* 3. Filter & Search Controls */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.75rem',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        {/* Search Bar */}
        <div style={{ position: 'relative', flex: '1 1 300px' }}>
          <Search
            size={14}
            style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--sub-color)' }}
          />
          <input
            type="text"
            className="mt-input"
            style={{ paddingLeft: '34px', width: '100%' }}
            placeholder="Search by track, artist, song ID, Telegram user ID..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </div>

        {/* Format Selector Pills */}
        <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
          {['all', 'alac', 'aac', 'atmos', 'mv'].map((fmt) => (
            <button
              key={fmt}
              className={`mt-btn ${formatFilter === fmt ? 'primary' : ''}`}
              style={{
                padding: '0.35rem 0.65rem',
                fontSize: '0.72rem',
                fontWeight: formatFilter === fmt ? 700 : 500,
                textTransform: 'uppercase',
              }}
              onClick={() => {
                setFormatFilter(fmt);
                setPage(1);
              }}
            >
              {fmt}
            </button>
          ))}
        </div>

        {/* Cache Mode Pills */}
        <div style={{ display: 'flex', gap: '0.35rem' }}>
          {[
            { id: 'all', label: 'All Modes' },
            { id: 'true', label: '⚡ Cached' },
            { id: 'false', label: '⬇ Fresh DL' },
          ].map((mode) => (
            <button
              key={mode.id}
              className={`mt-btn ${cachedFilter === mode.id ? 'primary' : ''}`}
              style={{
                padding: '0.35rem 0.65rem',
                fontSize: '0.72rem',
                fontWeight: cachedFilter === mode.id ? 700 : 500,
              }}
              onClick={() => {
                setCachedFilter(mode.id);
                setPage(1);
              }}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </div>

      {/* 4. Recent Downloads Data Table */}
      <div className="mt-table-container">
        <table className="mt-table">
          <thead>
            <tr>
              <th style={{ width: '48px' }}>Cover</th>
              <th>Track & Artist</th>
              <th>Format</th>
              <th>Delivery Status</th>
              <th>File Size</th>
              <th>Requested By</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {!data || data.downloads.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--sub-color)' }}>
                  {loading ? 'Loading recent download history...' : 'No downloads found matching current query.'}
                </td>
              </tr>
            ) : (
              data.downloads.map((item) => {
                const formatBadge = getFormatBadgeStyle(item.format_type);
                const FormatIcon = formatBadge.icon;
                const displayName = item.username
                  ? `@${item.username}`
                  : item.first_name
                  ? item.first_name
                  : `User ${item.user_id}`;

                return (
                  <tr key={item.id}>
                    {/* Artwork */}
                    <td>
                      <div
                        style={{
                          width: '40px',
                          height: '40px',
                          borderRadius: '6px',
                          overflow: 'hidden',
                          backgroundColor: 'var(--sub-alt-color)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          cursor: item.artwork ? 'pointer' : 'default',
                        }}
                        onClick={() => item.artwork && setSelectedArtwork(item.artwork)}
                        title={item.artwork ? 'Click to preview full artwork' : undefined}
                      >
                        {item.artwork ? (
                          <img
                            src={item.artwork}
                            alt=""
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                            loading="lazy"
                            onError={(e) => {
                              (e.target as HTMLElement).style.display = 'none';
                            }}
                          />
                        ) : (
                          <Music size={18} color="var(--sub-color)" />
                        )}
                      </div>
                    </td>

                    {/* Track Info */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem', maxWidth: '320px' }}>
                        <span
                          style={{
                            fontWeight: 600,
                            color: 'var(--text-color)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                          title={item.title}
                        >
                          {item.title}
                        </span>
                        <span
                          style={{
                            fontSize: '0.75rem',
                            color: 'var(--sub-color)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                          title={`${item.artist}${item.album ? ` — ${item.album}` : ''}`}
                        >
                          {item.artist}
                          {item.album && ` • ${item.album}`}
                        </span>
                      </div>
                    </td>

                    {/* Format Pill */}
                    <td>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.3rem',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          backgroundColor: formatBadge.bg,
                          color: formatBadge.color,
                          border: formatBadge.border,
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        <FormatIcon size={12} />
                        {formatBadge.label}
                      </span>
                    </td>

                    {/* Cache Status Badge */}
                    <td>
                      {item.is_cached ? (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.3rem',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            backgroundColor: 'rgba(152, 195, 121, 0.15)',
                            color: 'var(--success-color)',
                            fontSize: '0.72rem',
                            fontWeight: 700,
                          }}
                        >
                          <Zap size={12} /> INSTANT CACHE
                        </span>
                      ) : (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.3rem',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            backgroundColor: 'rgba(97, 218, 251, 0.15)',
                            color: '#61dafb',
                            fontSize: '0.72rem',
                            fontWeight: 600,
                          }}
                        >
                          <Download size={12} /> FRESH DL
                        </span>
                      )}
                    </td>

                    {/* File Size */}
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                      {item.size > 0 ? (
                        formatBytes(item.size)
                      ) : (
                        <span style={{ color: 'var(--sub-color)' }}>—</span>
                      )}
                    </td>

                    {/* Requested User */}
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                            <span style={{ fontWeight: 600, fontSize: '0.8rem', color: 'var(--text-color)' }}>
                              {displayName}
                            </span>
                            {item.is_premium && (
                              <span title="VIP Subscriber" style={{ display: 'inline-flex' }}>
                                <Crown size={12} color="var(--main-color)" />
                              </span>
                            )}
                          </div>
                          <span style={{ fontSize: '0.7rem', color: 'var(--sub-color)', fontFamily: 'var(--font-mono)' }}>
                            ID: {item.user_id}
                          </span>
                        </div>
                      </div>
                    </td>

                    {/* Timestamp */}
                    <td>
                      <div
                        style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', color: 'var(--sub-color)', fontSize: '0.75rem' }}
                        title={item.downloaded_at || ''}
                      >
                        <Clock size={12} />
                        <span>{formatRelativeTime(item.downloaded_at)}</span>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* 5. Pagination Toolbar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.75rem',
          marginTop: '0.5rem',
        }}
      >
        <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
          Showing {data?.downloads.length || 0} of {data?.total || 0} items • Page {page} of {totalPages}
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <select
            className="mt-input"
            style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
            value={limit}
            onChange={(e) => {
              setLimit(Number(e.target.value));
              setPage(1);
            }}
          >
            <option value={15}>15 / page</option>
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>

          <button
            className="mt-btn"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <button
            className="mt-btn"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>

      {/* 6. Artwork Lightbox Modal */}
      {selectedArtwork && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.8)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            cursor: 'pointer',
          }}
          onClick={() => setSelectedArtwork(null)}
        >
          <div
            style={{
              maxWidth: '90vw',
              maxHeight: '90vh',
              borderRadius: 'var(--border-radius)',
              overflow: 'hidden',
              boxShadow: 'var(--shadow-glow)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={selectedArtwork}
              alt="Full Artwork"
              style={{ width: '100%', height: '100%', maxHeight: '80vh', objectFit: 'contain' }}
            />
            <div style={{ padding: '0.5rem', textAlign: 'center', backgroundColor: 'var(--bg-color)' }}>
              <button className="mt-btn primary" onClick={() => setSelectedArtwork(null)}>
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
