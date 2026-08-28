import React, { useState } from 'react';
import { getApiBase, setApiBase } from '../api';
import { Server, Check, X } from 'lucide-react';

interface ApiSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export const ApiSettingsModal: React.FC<ApiSettingsModalProps> = ({
  isOpen,
  onClose,
  onSaved,
}) => {
  const [url, setUrl] = useState(getApiBase());

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setApiBase(url);
    onSaved();
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="card-title">
            <Server size={17} />
            <span>Backend Server API URL</span>
          </div>
          <button className="mt-btn" onClick={onClose} style={{ padding: '0.2rem 0.5rem' }}>
            <X size={14} />
          </button>
        </div>

        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--sub-color)', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
              Base API Host
            </label>
            <input
              type="text"
              className="mt-input"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="e.g. https://tbot.eepy.in or http://localhost:8080"
              autoFocus
            />
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', display: 'block', marginTop: '0.4rem' }}>
              When hosting this dashboard statically on Cloudflare Pages, specify your live Telegram Bot webhook/stream domain.
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
            <button type="button" className="mt-btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="mt-btn primary">
              <Check size={14} />
              <span>Save & Reconnect</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
