import React from 'react';
import { ActiveDownloadItem } from '../types';
import { Activity, XOctagon, Music, User, Clock, Disc } from 'lucide-react';

interface ActiveDownloadsProps {
  downloads: ActiveDownloadItem[];
  onCancelTask: (taskId: string) => void;
  cancellingTaskId: string | null;
}

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
            return (
              <div key={item.task_id} className="download-item">
                <div className="download-meta">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div
                      style={{
                        width: '38px',
                        height: '38px',
                        backgroundColor: 'var(--sub-alt-color)',
                        borderRadius: '6px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--main-color)',
                      }}
                    >
                      <Music size={18} />
                    </div>
                    <div className="track-info">
                      <span className="track-title">{item.track_title}</span>
                      <span className="track-artist">{item.artist}</span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                    <span className="format-badge">{item.format}</span>

                    <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                      <User size={13} />
                      {item.user_id}
                    </span>

                    <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                      <Clock size={13} />
                      {item.duration_seconds}s
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
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.2rem' }}>
                  <div className="progress-container" style={{ flex: 1 }}>
                    <div
                      className="progress-fill animated"
                      style={{ width: `${Math.max(15, item.progress || 60)}%` }}
                    />
                  </div>
                  <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>
                    {item.status.toUpperCase()}
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
