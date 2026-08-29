import React from 'react';
import { ActiveDownloadItem } from '../types';
import { Activity, XOctagon, Music, User, Clock, Disc } from 'lucide-react';

interface ActiveDownloadsProps {
  downloads: ActiveDownloadItem[];
  onCancelTask: (taskId: string) => void;
  cancellingTaskId: string | null;
}

const getFormatBadgeStyle = (formatStr: string) => {
  const fmt = (formatStr || '').toUpperCase();
  if (fmt.includes('ATMOS')) {
    return { backgroundColor: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', borderColor: 'rgba(168, 85, 247, 0.3)' };
  }
  if (fmt.includes('AAC')) {
    return { backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', borderColor: 'rgba(59, 130, 246, 0.3)' };
  }
  if (fmt.includes('VIDEO') || fmt.includes('MV')) {
    return { backgroundColor: 'rgba(239, 68, 68, 0.15)', color: '#f87171', borderColor: 'rgba(239, 68, 68, 0.3)' };
  }
  // ALAC / LOSSLESS (default)
  return { backgroundColor: 'rgba(234, 179, 8, 0.15)', color: '#fde047', borderColor: 'rgba(234, 179, 8, 0.3)' };
};

export const ActiveDownloads: React.FC<ActiveDownloadsProps> = ({
  downloads,
  onCancelTask,
  cancellingTaskId,
}) => {
  return (
    <div className="mt-card">
      <div className="card-header">
        <div className="card-title">
          <Activity size={17} />
          <span>Live Active Downloads ({downloads.length})</span>
        </div>
        {downloads.length > 0 && (
          <span className="status-pill">
            <span className="status-dot online" />
            DOWNLOADING
          </span>
        )}
      </div>

      {downloads.length === 0 ? (
        <div
          style={{
            padding: '2.5rem 1rem',
            textAlign: 'center',
            color: 'var(--sub-color)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '0.6rem',
          }}
        >
          <Disc size={28} style={{ opacity: 0.4 }} />
          <span style={{ fontSize: '0.88rem' }}>No downloads currently in progress.</span>
          <span style={{ fontSize: '0.74rem' }}>
            Queue workers are idle and listening for incoming Telegram commands.
          </span>
        </div>
      ) : (
        <div>
          {downloads.map((item) => {
            const isCancelling = cancellingTaskId === item.task_id;
            const badgeStyle = getFormatBadgeStyle(item.format);
            const progressPct = Math.min(100, Math.max(5, item.progress || 0));

            return (
              <div key={item.task_id} className="download-item">
                <div className="download-meta">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1, minWidth: '240px' }}>
                    <div
                      style={{
                        width: '42px',
                        height: '42px',
                        backgroundColor: 'var(--sub-alt-color)',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--main-color)',
                        flexShrink: 0,
                      }}
                    >
                      <Music size={20} />
                    </div>
                    <div className="track-info" style={{ overflow: 'hidden' }}>
                      <span
                        className="track-title"
                        style={{
                          fontSize: '0.95rem',
                          fontWeight: 600,
                          color: 'var(--text-color)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: 'block',
                        }}
                      >
                        {item.track_title}
                      </span>
                      <span
                        className="track-artist"
                        style={{
                          fontSize: '0.8rem',
                          color: 'var(--sub-color)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: 'block',
                        }}
                      >
                        {item.artist}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', flexWrap: 'wrap' }}>
                    <span
                      className="format-badge"
                      style={{
                        padding: '0.25rem 0.6rem',
                        borderRadius: '4px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        border: '1px solid',
                        ...badgeStyle,
                      }}
                    >
                      {item.format}
                    </span>

                    <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                      <User size={13} />
                      <strong style={{ color: 'var(--text-color)' }}>{item.user_id}</strong>
                    </span>

                    <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                      <Clock size={13} />
                      <strong style={{ color: 'var(--text-color)' }}>{item.duration_seconds}s</strong>
                    </span>

                    <button
                      className="mt-btn danger"
                      onClick={() => onCancelTask(item.task_id)}
                      disabled={isCancelling}
                      style={{ padding: '0.35rem 0.65rem', fontSize: '0.74rem' }}
                      title="Kill subprocess and cancel download"
                    >
                      <XOctagon size={13} />
                      <span>{isCancelling ? 'Killing...' : 'Cancel Task'}</span>
                    </button>
                  </div>
                </div>

                {/* Progress bar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.3rem' }}>
                  <div className="progress-container" style={{ flex: 1 }}>
                    <div
                      className="progress-fill animated"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                  <span style={{ fontSize: '0.74rem', color: 'var(--main-color)', fontWeight: 700, minWidth: '45px', textAlign: 'right' }}>
                    {item.progress > 0 ? `${item.progress}%` : item.status.toUpperCase()}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
