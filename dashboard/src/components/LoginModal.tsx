import React, { useState } from 'react';
import { api, setApiBase, getApiBase } from '../api';
import { Bot, Lock, ArrowRight, Server, AlertCircle } from 'lucide-react';

interface LoginModalProps {
  onSuccess: () => void;
}

export const LoginModal: React.FC<LoginModalProps> = ({ onSuccess }) => {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showApiConfig, setShowApiConfig] = useState(false);
  const [apiUrl, setApiUrl] = useState(getApiBase());

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) return;

    setLoading(true);
    setError(null);

    try {
      if (apiUrl) {
        setApiBase(apiUrl);
      }
      await api.login(password);
      onSuccess();
    } catch (err: any) {
      setError(err.message || 'Invalid admin password');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-content" style={{ maxWidth: '440px' }}>
        {/* Brand Header */}
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.6rem' }}>
          <Bot size={36} style={{ color: 'var(--main-color)' }} />
          <h2 style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-color)' }}>
            tbot<span>.control</span>
          </h2>
          <p style={{ fontSize: '0.78rem', color: 'var(--sub-color)' }}>
            Authenticate with your admin password to access the control plane.
          </p>
        </div>

        {/* Error alert */}
        {error && (
          <div
            style={{
              padding: '0.75rem 1rem',
              backgroundColor: 'rgba(202, 71, 84, 0.15)',
              border: '1px solid rgba(202, 71, 84, 0.3)',
              borderRadius: 'var(--border-radius)',
              color: 'var(--error-color)',
              fontSize: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            <AlertCircle size={15} />
            <span>{error}</span>
          </div>
        )}

        {/* Password Form */}
        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--sub-color)', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
              Admin Password
            </label>
            <div style={{ position: 'relative' }}>
              <Lock size={15} style={{ position: 'absolute', left: '12px', top: '13px', color: 'var(--sub-color)' }} />
              <input
                type="password"
                className="mt-input"
                style={{ paddingLeft: '36px' }}
                placeholder="Enter password..."
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                disabled={loading}
              />
            </div>
          </div>

          {/* Toggle Backend URL (useful for Cloudflare Pages) */}
          <div>
            <button
              type="button"
              className="mt-btn"
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.72rem' }}
              onClick={() => setShowApiConfig(!showApiConfig)}
            >
              <Server size={13} />
              <span>{showApiConfig ? 'Hide Backend Host URL' : 'Configure Backend Server URL'}</span>
            </button>

            {showApiConfig && (
              <div style={{ marginTop: '0.5rem' }}>
                <input
                  type="text"
                  className="mt-input"
                  style={{ fontSize: '0.8rem', padding: '0.5rem 0.8rem' }}
                  placeholder="https://tbot.eepy.in or http://localhost:8080"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                />
                <span style={{ fontSize: '0.68rem', color: 'var(--sub-color)', display: 'block', marginTop: '0.25rem' }}>
                  If hosted on Cloudflare Pages, enter your public backend server or tunnel URL.
                </span>
              </div>
            )}
          </div>

          <button
            type="submit"
            className="mt-btn primary"
            disabled={loading || !password.trim()}
            style={{ width: '100%', justifyContent: 'center', padding: '0.75rem', fontSize: '0.9rem', marginTop: '0.5rem' }}
          >
            <span>{loading ? 'Authenticating...' : 'Access Dashboard'}</span>
            <ArrowRight size={16} />
          </button>
        </form>

        <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'var(--sub-color)' }}>
          Press <kbd>↵ Enter</kbd> to sign in
        </div>
      </div>
    </div>
  );
};
