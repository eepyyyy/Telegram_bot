import React, { useState, useEffect, useCallback } from 'react';
import {
  AlbumItem,
  AlbumsResponse,
  AlbumDetailsResponse,
  UpdateAlbumPayload,
  VerifyZipResponse,
} from '../types';
import { api } from '../api';
import {
  Search,
  RefreshCw,
  Edit3,
  Trash2,
  ExternalLink,
  Copy,
  Check,
  Disc,
  Music,
  Eye,
  FolderArchive,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
  Layers,
  Save,
  X,
} from 'lucide-react';

const formatBytes = (bytes: number | null | undefined): string => {
  if (!bytes || bytes <= 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

export const AlbumZipManager: React.FC = () => {
  const [data, setData] = useState<AlbumsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [search, setSearch] = useState<string>('');
  const [filter, setFilter] = useState<string>('all');
  const [sort, setSort] = useState<string>('recent');
  const [page, setPage] = useState<number>(1);
  const [limit] = useState<number>(20);

  // Modals & Active state
  const [editAlbum, setEditAlbum] = useState<AlbumItem | null>(null);
  const [editPayload, setEditPayload] = useState<UpdateAlbumPayload>({});
  const [isSaving, setIsSaving] = useState<boolean>(false);

  const [inspectAlbumId, setInspectAlbumId] = useState<string | null>(null);
  const [inspectDetails, setInspectDetails] = useState<AlbumDetailsResponse | null>(null);
  const [inspectLoading, setInspectLoading] = useState<boolean>(false);

  const [verifyingKey, setVerifyingKey] = useState<string | null>(null); // "albumId:format"
  const [verifyResult, setVerifyResult] = useState<{ key: string; result: VerifyZipResponse } | null>(null);

  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  const showNotification = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setNotification({ message, type });
    setTimeout(() => {
      setNotification((curr) => (curr?.message === message ? null : curr));
    }, 4500);
  };

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  const fetchAlbums = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getAlbums(page, limit, search, filter, sort);
      setData(res);
    } catch (err: any) {
      console.error('Failed to load albums:', err);
      showNotification(`Failed to load albums: ${err.message || err}`, 'error');
    } finally {
      setLoading(false);
    }
  }, [page, limit, search, filter, sort]);

  useEffect(() => {
    fetchAlbums();
  }, [fetchAlbums]);

  // Open Edit Modal
  const handleOpenEdit = (album: AlbumItem) => {
    setEditAlbum(album);
    setEditPayload({
      album: album.album || '',
      artist: album.artist || '',
      artwork: album.artwork || '',
      alac_zip_file_id: album.alac_zip_file_id || '',
      alac_zip_size: album.alac_zip_size,
      alac_gofile_url: album.alac_gofile_url || '',
      aac_zip_file_id: album.aac_zip_file_id || '',
      aac_zip_size: album.aac_zip_size,
      aac_gofile_url: album.aac_gofile_url || '',
      atmos_zip_file_id: album.atmos_zip_file_id || '',
      atmos_zip_size: album.atmos_zip_size,
      atmos_gofile_url: album.atmos_gofile_url || '',
    });
    setVerifyResult(null);
  };

  // Save Edit
  const handleSaveEdit = async () => {
    if (!editAlbum) return;
    setIsSaving(true);
    try {
      const res = await api.updateAlbumProperties(editAlbum.album_id, editPayload);
      showNotification(res.message || 'Album properties updated successfully!', 'success');
      setEditAlbum(null);
      fetchAlbums();
    } catch (err: any) {
      alert(`Failed to update album: ${err.message || err}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Clear ZIP Cache
  const handleClearZip = async (albumId: string, format: 'alac' | 'aac' | 'atmos' | 'all') => {
    const fmtText = format === 'all' ? 'ALL format ZIP caches' : `${format.toUpperCase()} ZIP cache`;
    if (!window.confirm(`Are you sure you want to clear the ${fmtText} for album ID ${albumId}?\n\nThe bot will re-download and re-package the album next time a user requests it.`)) {
      return;
    }

    try {
      const res = await api.clearAlbumZip(albumId, format);
      showNotification(res.message, 'success');
      fetchAlbums();
      if (editAlbum && editAlbum.album_id === albumId) {
        setEditAlbum(res.album);
      }
    } catch (err: any) {
      alert(`Failed to clear ZIP cache: ${err.message || err}`);
    }
  };

  // Delete Album completely
  const handleDeleteAlbum = async (albumId: string) => {
    const deleteTracks = window.confirm(
      `Do you also want to DELETE associated individual cached tracks from database?\n\nClick [OK] to delete album AND tracks.\nClick [Cancel] to delete ONLY the album record.`
    );
    if (!window.confirm(`CONFIRM: Permanently delete album record ${albumId}?`)) {
      return;
    }

    try {
      const res = await api.deleteAlbum(albumId, deleteTracks);
      showNotification(res.message, 'success');
      fetchAlbums();
    } catch (err: any) {
      alert(`Failed to delete album: ${err.message || err}`);
    }
  };

  // Verify Telegram File ID
  const handleVerifyZip = async (albumId: string, format: 'alac' | 'aac' | 'atmos') => {
    const key = `${albumId}:${format}`;
    setVerifyingKey(key);
    try {
      const res = await api.verifyAlbumZip(albumId, format);
      setVerifyResult({ key, result: res });
      if (res.valid) {
        showNotification(
          `✅ Valid Telegram File! Size: ${formatBytes(res.file_size)}`,
          'success'
        );
        fetchAlbums();
      } else {
        showNotification(`⚠️ Telegram Error: ${res.error || res.message}`, 'error');
      }
    } catch (err: any) {
      showNotification(`Verification request failed: ${err.message || err}`, 'error');
    } finally {
      setVerifyingKey(null);
    }
  };

  // Inspect Tracks
  const handleInspectAlbum = async (albumId: string) => {
    setInspectAlbumId(albumId);
    setInspectLoading(true);
    setInspectDetails(null);
    try {
      const res = await api.getAlbumDetails(albumId);
      setInspectDetails(res);
    } catch (err: any) {
      alert(`Failed to load album tracks: ${err.message || err}`);
      setInspectAlbumId(null);
    } finally {
      setInspectLoading(false);
    }
  };

  // Backfill Missing Sizes
  const handleBackfillSizes = async () => {
    try {
      const res = await api.backfillZipSizes();
      showNotification(res.message || 'ZIP size backfill started in background.', 'info');
      setTimeout(fetchAlbums, 3000);
    } catch (err: any) {
      alert(`Backfill failed: ${err.message || err}`);
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* 1. Header & Summary Stats */}
      <div className="mt-card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.8rem' }}>
          <div className="card-title">
            <FolderArchive size={19} />
            <span>Album ZIP Archives & Properties</span>
            <span className="badge" style={{ fontSize: '0.75rem', backgroundColor: 'var(--sub-alt-color)' }}>
              {data?.total ?? 0} Albums
            </span>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button
              className="mt-btn"
              onClick={handleBackfillSizes}
              title="Query Telegram API to calculate file sizes for albums currently missing size"
            >
              <Sparkles size={14} />
              <span>Backfill Missing Sizes</span>
            </button>
            <button className="mt-btn" onClick={fetchAlbums} disabled={loading} title="Refresh catalog">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Global Statistics Cards */}
        {data?.summary && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
              gap: '0.85rem',
              marginTop: '1rem',
            }}
          >
            <div
              style={{
                backgroundColor: 'var(--bg-color)',
                padding: '0.85rem 1rem',
                borderRadius: 'var(--border-radius)',
                borderLeft: '3px solid var(--main-color)',
              }}
            >
              <div style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>ALAC LOSSLESS ZIPS</div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-color)', marginTop: '0.2rem' }}>
                {data.summary.alac_zip_count.toLocaleString()}{' '}
                <span style={{ fontSize: '0.75rem', color: 'var(--main-color)' }}>
                  ({formatBytes(data.summary.alac_zip_size_bytes)})
                </span>
              </div>
            </div>

            <div
              style={{
                backgroundColor: 'var(--bg-color)',
                padding: '0.85rem 1rem',
                borderRadius: 'var(--border-radius)',
                borderLeft: '3px solid #bd93f9',
              }}
            >
              <div style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>AAC 256K ZIPS</div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-color)', marginTop: '0.2rem' }}>
                {data.summary.aac_zip_count.toLocaleString()}{' '}
                <span style={{ fontSize: '0.75rem', color: '#bd93f9' }}>
                  ({formatBytes(data.summary.aac_zip_size_bytes)})
                </span>
              </div>
            </div>

            <div
              style={{
                backgroundColor: 'var(--bg-color)',
                padding: '0.85rem 1rem',
                borderRadius: 'var(--border-radius)',
                borderLeft: '3px solid #61dafb',
              }}
            >
              <div style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>DOLBY ATMOS ZIPS</div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-color)', marginTop: '0.2rem' }}>
                {data.summary.atmos_zip_count.toLocaleString()}{' '}
                <span style={{ fontSize: '0.75rem', color: '#61dafb' }}>
                  ({formatBytes(data.summary.atmos_zip_size_bytes)})
                </span>
              </div>
            </div>

            <div
              style={{
                backgroundColor: 'var(--bg-color)',
                padding: '0.85rem 1rem',
                borderRadius: 'var(--border-radius)',
                borderLeft: '3px solid var(--success-color)',
              }}
            >
              <div style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>TOTAL ZIP STORAGE</div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-color)', marginTop: '0.2rem' }}>
                {data.summary.total_zip_size_gb} GB{' '}
                <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
                  ({data.summary.total_with_zip} archives)
                </span>
              </div>
            </div>
          </div>
        )}

        {/* 2. Search, Filter & Sort Controls */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0.75rem',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginTop: '1.25rem',
            paddingTop: '1rem',
            borderTop: '1px solid var(--sub-alt-color)',
          }}
        >
          {/* Search bar */}
          <div style={{ position: 'relative', flex: '1 1 280px', maxWidth: '420px' }}>
            <Search
              size={15}
              style={{
                position: 'absolute',
                left: '0.85rem',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--sub-color)',
              }}
            />
            <input
              type="text"
              placeholder="Search album title, artist, or Apple ID..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              style={{
                width: '100%',
                backgroundColor: 'var(--bg-color)',
                border: '1px solid var(--sub-alt-color)',
                borderRadius: 'var(--border-radius)',
                padding: '0.55rem 0.85rem 0.55rem 2.3rem',
                color: 'var(--text-color)',
                fontSize: '0.82rem',
                outline: 'none',
              }}
            />
            {search && (
              <button
                onClick={() => {
                  setSearch('');
                  setPage(1);
                }}
                style={{
                  position: 'absolute',
                  right: '0.75rem',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: 'var(--sub-color)',
                  cursor: 'pointer',
                }}
              >
                <X size={13} />
              </button>
            )}
          </div>

          {/* Filter Pills */}
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', alignItems: 'center' }}>
            {[
              { id: 'all', label: 'All Albums' },
              { id: 'has_zip', label: 'With Any ZIP' },
              { id: 'alac', label: 'ALAC ZIP' },
              { id: 'aac', label: 'AAC ZIP' },
              { id: 'atmos', label: 'Atmos ZIP' },
              { id: 'missing_zip', label: 'Missing ZIP' },
            ].map((f) => (
              <button
                key={f.id}
                className={`mt-btn ${filter === f.id ? 'primary' : ''}`}
                style={{ padding: '0.35rem 0.75rem', fontSize: '0.74rem' }}
                onClick={() => {
                  setFilter(f.id);
                  setPage(1);
                }}
              >
                {f.label}
              </button>
            ))}
          </div>

          {/* Sort selection */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>Sort:</span>
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPage(1);
              }}
              style={{
                backgroundColor: 'var(--bg-color)',
                border: '1px solid var(--sub-alt-color)',
                borderRadius: 'var(--border-radius)',
                padding: '0.4rem 0.65rem',
                color: 'var(--text-color)',
                fontSize: '0.78rem',
                cursor: 'pointer',
                outline: 'none',
              }}
            >
              <option value="recent">ID (Recent)</option>
              <option value="name">Album Name (A-Z)</option>
              <option value="artist">Artist Name (A-Z)</option>
              <option value="size_desc">Largest ZIP Size</option>
            </select>
          </div>
        </div>
      </div>

      {/* Notification Toast */}
      {notification && (
        <div
          style={{
            padding: '0.75rem 1.25rem',
            borderRadius: 'var(--border-radius)',
            fontSize: '0.82rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            backgroundColor:
              notification.type === 'success'
                ? 'rgba(152, 195, 121, 0.15)'
                : notification.type === 'error'
                ? 'rgba(202, 71, 84, 0.15)'
                : 'rgba(97, 218, 251, 0.15)',
            color:
              notification.type === 'success'
                ? 'var(--success-color)'
                : notification.type === 'error'
                ? 'var(--error-color)'
                : '#61dafb',
            border: `1px solid ${
              notification.type === 'success'
                ? 'rgba(152, 195, 121, 0.4)'
                : notification.type === 'error'
                ? 'rgba(202, 71, 84, 0.4)'
                : 'rgba(97, 218, 251, 0.4)'
            }`,
          }}
        >
          <span>{notification.message}</span>
          <button
            onClick={() => setNotification(null)}
            style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}
          >
            <X size={15} />
          </button>
        </div>
      )}

      {/* 3. Albums Table */}
      <div className="mt-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.8rem' }}>
            <thead>
              <tr style={{ backgroundColor: 'var(--sub-alt-color)', color: 'var(--sub-color)', borderBottom: '1px solid var(--sub-alt-color)' }}>
                <th style={{ padding: '0.85rem 1rem', width: '60px' }}>Artwork</th>
                <th style={{ padding: '0.85rem 1rem' }}>Album & Artist</th>
                <th style={{ padding: '0.85rem 1rem' }}>ALAC Lossless ZIP</th>
                <th style={{ padding: '0.85rem 1rem' }}>AAC 256K ZIP</th>
                <th style={{ padding: '0.85rem 1rem' }}>Dolby Atmos ZIP</th>
                <th style={{ padding: '0.85rem 1rem', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (!data || data.albums.length === 0) ? (
                <tr>
                  <td colSpan={6} style={{ padding: '3rem', textAlign: 'center', color: 'var(--sub-color)' }}>
                    <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 0.5rem auto' }} />
                    <div>Loading album ZIP catalog...</div>
                  </td>
                </tr>
              ) : !data || data.albums.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: '3rem', textAlign: 'center', color: 'var(--sub-color)' }}>
                    <FolderArchive size={28} style={{ margin: '0 auto 0.5rem auto', opacity: 0.5 }} />
                    <div style={{ fontWeight: 600, color: 'var(--text-color)' }}>No albums found</div>
                    <div style={{ fontSize: '0.75rem', marginTop: '0.2rem' }}>
                      Try adjusting your search query or format filter.
                    </div>
                  </td>
                </tr>
              ) : (
                data.albums.map((album) => {
                  return (
                    <tr
                      key={album.album_id}
                      style={{
                        borderBottom: '1px solid var(--sub-alt-color)',
                        transition: 'background-color var(--transition-fast)',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.02)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent';
                      }}
                    >
                      {/* Artwork Thumbnail */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'middle' }}>
                        {album.artwork ? (
                          <img
                            src={album.artwork.replace('{w}x{h}', '120x120')}
                            alt={album.album}
                            style={{
                              width: '44px',
                              height: '44px',
                              borderRadius: '6px',
                              objectFit: 'cover',
                              backgroundColor: 'var(--sub-alt-color)',
                            }}
                            onError={(e) => {
                              (e.target as HTMLElement).style.display = 'none';
                            }}
                          />
                        ) : (
                          <div
                            style={{
                              width: '44px',
                              height: '44px',
                              borderRadius: '6px',
                              backgroundColor: 'var(--sub-alt-color)',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              color: 'var(--sub-color)',
                            }}
                          >
                            <Disc size={20} />
                          </div>
                        )}
                      </td>

                      {/* Album Title & Artist */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'middle' }}>
                        <div style={{ fontWeight: 700, color: 'var(--text-color)', fontSize: '0.85rem' }}>
                          {album.album}
                        </div>
                        <div style={{ color: 'var(--sub-color)', fontSize: '0.75rem', marginTop: '0.15rem' }}>
                          {album.artist}
                        </div>
                        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', marginTop: '0.35rem' }}>
                          <span
                            onClick={() => copyToClipboard(album.album_id, `id_${album.album_id}`)}
                            title="Click to copy Apple Album ID"
                            style={{
                              fontSize: '0.68rem',
                              fontFamily: 'var(--font-mono)',
                              color: 'var(--sub-color)',
                              backgroundColor: 'var(--bg-color)',
                              padding: '1px 6px',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '3px',
                            }}
                          >
                            {copiedKey === `id_${album.album_id}` ? <Check size={10} color="var(--success-color)" /> : <Copy size={10} />}
                            {album.album_id}
                          </span>

                          <span
                            style={{
                              fontSize: '0.68rem',
                              color: 'var(--sub-color)',
                              backgroundColor: 'var(--bg-color)',
                              padding: '1px 6px',
                              borderRadius: '4px',
                            }}
                          >
                            {album.track_count} tracks in DB
                          </span>
                        </div>
                      </td>

                      {/* ALAC Lossless ZIP */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'middle' }}>
                        {album.has_alac_zip ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                              <span
                                style={{
                                  backgroundColor: 'rgba(226, 183, 20, 0.15)',
                                  color: 'var(--main-color)',
                                  border: '1px solid rgba(226, 183, 20, 0.4)',
                                  padding: '2px 7px',
                                  borderRadius: '12px',
                                  fontSize: '0.7rem',
                                  fontWeight: 700,
                                }}
                              >
                                {formatBytes(album.alac_zip_size)}
                              </span>

                              <button
                                className="mt-btn"
                                style={{ padding: '2px 5px', fontSize: '0.65rem' }}
                                onClick={() => handleVerifyZip(album.album_id, 'alac')}
                                disabled={verifyingKey === `${album.album_id}:alac`}
                                title="Verify file status on Telegram"
                              >
                                <ShieldCheck size={11} className={verifyingKey === `${album.album_id}:alac` ? 'animate-spin' : ''} />
                                <span>Verify</span>
                              </button>
                            </div>

                            {album.alac_zip_file_id && (
                              <div
                                onClick={() => copyToClipboard(album.alac_zip_file_id!, `alac_fid_${album.album_id}`)}
                                title="Click to copy Telegram File ID"
                                style={{
                                  fontSize: '0.68rem',
                                  fontFamily: 'var(--font-mono)',
                                  color: 'var(--sub-color)',
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '3px',
                                }}
                              >
                                <Copy size={10} />
                                <span>{album.alac_zip_file_id.slice(0, 16)}...</span>
                              </div>
                            )}

                            {album.alac_gofile_url && (
                              <a
                                href={album.alac_gofile_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{ fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '3px' }}
                              >
                                <ExternalLink size={10} /> GoFile Link
                              </a>
                            )}
                          </div>
                        ) : (
                          <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', opacity: 0.5 }}>
                            No ALAC ZIP
                          </span>
                        )}
                      </td>

                      {/* AAC 256K ZIP */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'middle' }}>
                        {album.has_aac_zip ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                              <span
                                style={{
                                  backgroundColor: 'rgba(189, 147, 249, 0.15)',
                                  color: '#bd93f9',
                                  border: '1px solid rgba(189, 147, 249, 0.4)',
                                  padding: '2px 7px',
                                  borderRadius: '12px',
                                  fontSize: '0.7rem',
                                  fontWeight: 700,
                                }}
                              >
                                {formatBytes(album.aac_zip_size)}
                              </span>

                              <button
                                className="mt-btn"
                                style={{ padding: '2px 5px', fontSize: '0.65rem' }}
                                onClick={() => handleVerifyZip(album.album_id, 'aac')}
                                disabled={verifyingKey === `${album.album_id}:aac`}
                                title="Verify file status on Telegram"
                              >
                                <ShieldCheck size={11} className={verifyingKey === `${album.album_id}:aac` ? 'animate-spin' : ''} />
                                <span>Verify</span>
                              </button>
                            </div>

                            {album.aac_zip_file_id && (
                              <div
                                onClick={() => copyToClipboard(album.aac_zip_file_id!, `aac_fid_${album.album_id}`)}
                                title="Click to copy Telegram File ID"
                                style={{
                                  fontSize: '0.68rem',
                                  fontFamily: 'var(--font-mono)',
                                  color: 'var(--sub-color)',
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '3px',
                                }}
                              >
                                <Copy size={10} />
                                <span>{album.aac_zip_file_id.slice(0, 16)}...</span>
                              </div>
                            )}

                            {album.aac_gofile_url && (
                              <a
                                href={album.aac_gofile_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{ fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '3px', color: '#bd93f9' }}
                              >
                                <ExternalLink size={10} /> GoFile Link
                              </a>
                            )}
                          </div>
                        ) : (
                          <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', opacity: 0.5 }}>
                            No AAC ZIP
                          </span>
                        )}
                      </td>

                      {/* Dolby Atmos ZIP */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'middle' }}>
                        {album.has_atmos_zip ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                              <span
                                style={{
                                  backgroundColor: 'rgba(97, 218, 251, 0.15)',
                                  color: '#61dafb',
                                  border: '1px solid rgba(97, 218, 251, 0.4)',
                                  padding: '2px 7px',
                                  borderRadius: '12px',
                                  fontSize: '0.7rem',
                                  fontWeight: 700,
                                }}
                              >
                                {formatBytes(album.atmos_zip_size)}
                              </span>

                              <button
                                className="mt-btn"
                                style={{ padding: '2px 5px', fontSize: '0.65rem' }}
                                onClick={() => handleVerifyZip(album.album_id, 'atmos')}
                                disabled={verifyingKey === `${album.album_id}:atmos`}
                                title="Verify file status on Telegram"
                              >
                                <ShieldCheck size={11} className={verifyingKey === `${album.album_id}:atmos` ? 'animate-spin' : ''} />
                                <span>Verify</span>
                              </button>
                            </div>

                            {album.atmos_zip_file_id && (
                              <div
                                onClick={() => copyToClipboard(album.atmos_zip_file_id!, `atmos_fid_${album.album_id}`)}
                                title="Click to copy Telegram File ID"
                                style={{
                                  fontSize: '0.68rem',
                                  fontFamily: 'var(--font-mono)',
                                  color: 'var(--sub-color)',
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '3px',
                                }}
                              >
                                <Copy size={10} />
                                <span>{album.atmos_zip_file_id.slice(0, 16)}...</span>
                              </div>
                            )}

                            {album.atmos_gofile_url && (
                              <a
                                href={album.atmos_gofile_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{ fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '3px', color: '#61dafb' }}
                              >
                                <ExternalLink size={10} /> GoFile Link
                              </a>
                            )}
                          </div>
                        ) : (
                          <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', opacity: 0.5 }}>
                            No Atmos ZIP
                          </span>
                        )}
                      </td>

                      {/* Row Actions */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'middle', textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
                          {/* Inspect tracks */}
                          <button
                            className="mt-btn"
                            style={{ padding: '0.35rem 0.6rem' }}
                            onClick={() => handleInspectAlbum(album.album_id)}
                            title="Inspect tracks and raw properties"
                          >
                            <Eye size={13} />
                          </button>

                          {/* Edit button */}
                          <button
                            className="mt-btn primary"
                            style={{ padding: '0.35rem 0.65rem' }}
                            onClick={() => handleOpenEdit(album)}
                            title="Edit ZIP properties, file IDs, sizes, or GoFile links"
                          >
                            <Edit3 size={13} />
                            <span>Edit</span>
                          </button>

                          {/* Delete dropdown / quick clear */}
                          <button
                            className="mt-btn danger"
                            style={{ padding: '0.35rem 0.6rem' }}
                            onClick={() => handleClearZip(album.album_id, 'all')}
                            title="Clear all cached ZIPs for this album (forces fresh download next time)"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0.85rem 1.25rem',
            borderTop: '1px solid var(--sub-alt-color)',
            fontSize: '0.78rem',
            color: 'var(--sub-color)',
          }}
        >
          <div>
            Showing {data?.albums.length ? (page - 1) * limit + 1 : 0} to{' '}
            {data ? Math.min(page * limit, data.total) : 0} of {data?.total ?? 0} albums
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button
              className="mt-btn"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              style={{ padding: '0.35rem 0.65rem' }}
            >
              <ChevronLeft size={14} />
              <span>Previous</span>
            </button>

            <span style={{ fontWeight: 600, color: 'var(--text-color)' }}>
              Page {page} of {totalPages}
            </span>

            <button
              className="mt-btn"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              style={{ padding: '0.35rem 0.65rem' }}
            >
              <span>Next</span>
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* 4. Edit Album ZIP Properties Modal */}
      {editAlbum && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1.5rem',
          }}
          onClick={() => setEditAlbum(null)}
        >
          <div
            className="mt-card"
            style={{
              width: '100%',
              maxWidth: '750px',
              maxHeight: '90vh',
              overflowY: 'auto',
              backgroundColor: 'var(--sub-alt-color)',
              border: '1px solid var(--sub-color)',
              boxShadow: 'var(--shadow-sm)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="card-header" style={{ marginBottom: '1rem' }}>
              <div className="card-title">
                <Edit3 size={17} />
                <span>Edit Album Properties & ZIP Cache</span>
              </div>
              <button
                className="mt-btn"
                style={{ padding: '0.3rem 0.5rem' }}
                onClick={() => setEditAlbum(null)}
              >
                <X size={15} />
              </button>
            </div>

            {/* Album Summary Banner */}
            <div
              style={{
                display: 'flex',
                gap: '1rem',
                alignItems: 'center',
                backgroundColor: 'var(--bg-color)',
                padding: '0.85rem 1rem',
                borderRadius: 'var(--border-radius)',
                marginBottom: '1.25rem',
              }}
            >
              {editAlbum.artwork ? (
                <img
                  src={editAlbum.artwork.replace('{w}x{h}', '120x120')}
                  alt={editAlbum.album}
                  style={{ width: '50px', height: '50px', borderRadius: '6px', objectFit: 'cover' }}
                />
              ) : (
                <Disc size={36} color="var(--sub-color)" />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, color: 'var(--text-color)', fontSize: '0.95rem' }}>
                  {editAlbum.album}
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--sub-color)' }}>{editAlbum.artist}</div>
                <div style={{ fontSize: '0.72rem', color: 'var(--main-color)', marginTop: '0.2rem' }}>
                  ID: {editAlbum.album_id} • {editAlbum.track_count} tracks in DB
                </div>
              </div>

              {/* Quick Clear All button */}
              <button
                className="mt-btn danger"
                style={{ fontSize: '0.72rem', padding: '0.4rem 0.75rem' }}
                onClick={() => handleClearZip(editAlbum.album_id, 'all')}
                title="Wipes all format ZIP properties so the bot re-downloads on next request"
              >
                <Trash2 size={13} />
                <span>Clear All ZIPs</span>
              </button>
            </div>

            {/* Form Sections */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* General Metadata */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.85rem' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--sub-color)', marginBottom: '0.3rem', fontWeight: 600 }}>
                    Album Title
                  </label>
                  <input
                    type="text"
                    value={editPayload.album ?? ''}
                    onChange={(e) => setEditPayload((p) => ({ ...p, album: e.target.value }))}
                    style={{
                      width: '100%',
                      backgroundColor: 'var(--bg-color)',
                      border: '1px solid var(--sub-color)',
                      borderRadius: 'var(--border-radius)',
                      padding: '0.5rem 0.75rem',
                      color: 'var(--text-color)',
                      fontSize: '0.8rem',
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--sub-color)', marginBottom: '0.3rem', fontWeight: 600 }}>
                    Artist Name
                  </label>
                  <input
                    type="text"
                    value={editPayload.artist ?? ''}
                    onChange={(e) => setEditPayload((p) => ({ ...p, artist: e.target.value }))}
                    style={{
                      width: '100%',
                      backgroundColor: 'var(--bg-color)',
                      border: '1px solid var(--sub-color)',
                      borderRadius: 'var(--border-radius)',
                      padding: '0.5rem 0.75rem',
                      color: 'var(--text-color)',
                      fontSize: '0.8rem',
                    }}
                  />
                </div>
              </div>

              {/* Artwork URL */}
              <div>
                <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--sub-color)', marginBottom: '0.3rem', fontWeight: 600 }}>
                  Artwork URL Template
                </label>
                <input
                  type="text"
                  value={editPayload.artwork ?? ''}
                  onChange={(e) => setEditPayload((p) => ({ ...p, artwork: e.target.value }))}
                  placeholder="https://is1-ssl.mzstatic.com/image/thumb/.../{w}x{h}bb.jpg"
                  style={{
                    width: '100%',
                    backgroundColor: 'var(--bg-color)',
                    border: '1px solid var(--sub-color)',
                    borderRadius: 'var(--border-radius)',
                    padding: '0.5rem 0.75rem',
                    color: 'var(--text-color)',
                    fontSize: '0.8rem',
                  }}
                />
              </div>

              {/* FORMAT 1: ALAC LOSSLESS ZIP */}
              <div
                style={{
                  backgroundColor: 'var(--bg-color)',
                  padding: '1rem',
                  borderRadius: 'var(--border-radius)',
                  border: '1px solid rgba(226, 183, 20, 0.3)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--main-color)', fontWeight: 700, fontSize: '0.82rem' }}>
                    <Disc size={15} />
                    <span>ALAC Lossless ZIP</span>
                    {editPayload.alac_zip_size ? (
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-color)', fontWeight: 500 }}>
                        ({formatBytes(editPayload.alac_zip_size)})
                      </span>
                    ) : null}
                  </div>

                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    <button
                      type="button"
                      className="mt-btn"
                      style={{ padding: '0.25rem 0.55rem', fontSize: '0.68rem' }}
                      onClick={() => handleVerifyZip(editAlbum.album_id, 'alac')}
                      disabled={!editPayload.alac_zip_file_id || verifyingKey === `${editAlbum.album_id}:alac`}
                      title="Test file ID with Telegram Bot API"
                    >
                      <ShieldCheck size={12} className={verifyingKey === `${editAlbum.album_id}:alac` ? 'animate-spin' : ''} />
                      <span>Verify File ID</span>
                    </button>
                    <button
                      type="button"
                      className="mt-btn danger"
                      style={{ padding: '0.25rem 0.55rem', fontSize: '0.68rem' }}
                      onClick={() => {
                        setEditPayload((p) => ({
                          ...p,
                          alac_zip_file_id: '',
                          alac_zip_size: null,
                          alac_gofile_url: '',
                        }));
                      }}
                      title="Clear ALAC fields"
                    >
                      <span>Clear ALAC</span>
                    </button>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: '0.75rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                      Telegram File ID
                    </label>
                    <input
                      type="text"
                      value={editPayload.alac_zip_file_id ?? ''}
                      onChange={(e) => setEditPayload((p) => ({ ...p, alac_zip_file_id: e.target.value }))}
                      placeholder="BQACAgIAAxkBAA..."
                      style={{
                        width: '100%',
                        backgroundColor: 'var(--sub-alt-color)',
                        border: '1px solid var(--sub-color)',
                        borderRadius: 'var(--border-radius)',
                        padding: '0.45rem 0.65rem',
                        color: 'var(--text-color)',
                        fontSize: '0.75rem',
                        fontFamily: 'var(--font-mono)',
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                      Size (Bytes)
                    </label>
                    <input
                      type="number"
                      value={editPayload.alac_zip_size ?? ''}
                      onChange={(e) => {
                        const val = e.target.value ? parseInt(e.target.value, 10) : null;
                        setEditPayload((p) => ({ ...p, alac_zip_size: val }));
                      }}
                      placeholder="e.g. 524288000"
                      style={{
                        width: '100%',
                        backgroundColor: 'var(--sub-alt-color)',
                        border: '1px solid var(--sub-color)',
                        borderRadius: 'var(--border-radius)',
                        padding: '0.45rem 0.65rem',
                        color: 'var(--text-color)',
                        fontSize: '0.75rem',
                      }}
                    />
                  </div>
                </div>

                <div style={{ marginTop: '0.65rem' }}>
                  <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                    GoFile High-Speed Download URL
                  </label>
                  <input
                    type="url"
                    value={editPayload.alac_gofile_url ?? ''}
                    onChange={(e) => setEditPayload((p) => ({ ...p, alac_gofile_url: e.target.value }))}
                    placeholder="https://gofile.io/d/..."
                    style={{
                      width: '100%',
                      backgroundColor: 'var(--sub-alt-color)',
                      border: '1px solid var(--sub-color)',
                      borderRadius: 'var(--border-radius)',
                      padding: '0.45rem 0.65rem',
                      color: 'var(--text-color)',
                      fontSize: '0.75rem',
                    }}
                  />
                </div>

                {verifyResult?.key === `${editAlbum.album_id}:alac` && (
                  <div
                    style={{
                      marginTop: '0.65rem',
                      padding: '0.4rem 0.65rem',
                      borderRadius: 'var(--border-radius)',
                      fontSize: '0.72rem',
                      backgroundColor: verifyResult.result.valid ? 'rgba(152, 195, 121, 0.15)' : 'rgba(202, 71, 84, 0.15)',
                      color: verifyResult.result.valid ? 'var(--success-color)' : 'var(--error-color)',
                      border: `1px solid ${verifyResult.result.valid ? 'rgba(152, 195, 121, 0.3)' : 'rgba(202, 71, 84, 0.3)'}`,
                    }}
                  >
                    {verifyResult.result.valid
                      ? `✅ Telegram file valid! Size: ${formatBytes(verifyResult.result.file_size)}`
                      : `❌ Verification failed: ${verifyResult.result.error || verifyResult.result.message}`}
                  </div>
                )}
              </div>

              {/* FORMAT 2: AAC 256K ZIP */}
              <div
                style={{
                  backgroundColor: 'var(--bg-color)',
                  padding: '1rem',
                  borderRadius: 'var(--border-radius)',
                  border: '1px solid rgba(189, 147, 249, 0.3)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: '#bd93f9', fontWeight: 700, fontSize: '0.82rem' }}>
                    <Music size={15} />
                    <span>AAC 256K ZIP</span>
                    {editPayload.aac_zip_size ? (
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-color)', fontWeight: 500 }}>
                        ({formatBytes(editPayload.aac_zip_size)})
                      </span>
                    ) : null}
                  </div>

                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    <button
                      type="button"
                      className="mt-btn"
                      style={{ padding: '0.25rem 0.55rem', fontSize: '0.68rem' }}
                      onClick={() => handleVerifyZip(editAlbum.album_id, 'aac')}
                      disabled={!editPayload.aac_zip_file_id || verifyingKey === `${editAlbum.album_id}:aac`}
                      title="Test file ID with Telegram Bot API"
                    >
                      <ShieldCheck size={12} className={verifyingKey === `${editAlbum.album_id}:aac` ? 'animate-spin' : ''} />
                      <span>Verify File ID</span>
                    </button>
                    <button
                      type="button"
                      className="mt-btn danger"
                      style={{ padding: '0.25rem 0.55rem', fontSize: '0.68rem' }}
                      onClick={() => {
                        setEditPayload((p) => ({
                          ...p,
                          aac_zip_file_id: '',
                          aac_zip_size: null,
                          aac_gofile_url: '',
                        }));
                      }}
                      title="Clear AAC fields"
                    >
                      <span>Clear AAC</span>
                    </button>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: '0.75rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                      Telegram File ID
                    </label>
                    <input
                      type="text"
                      value={editPayload.aac_zip_file_id ?? ''}
                      onChange={(e) => setEditPayload((p) => ({ ...p, aac_zip_file_id: e.target.value }))}
                      placeholder="BQACAgIAAxkBAA..."
                      style={{
                        width: '100%',
                        backgroundColor: 'var(--sub-alt-color)',
                        border: '1px solid var(--sub-color)',
                        borderRadius: 'var(--border-radius)',
                        padding: '0.45rem 0.65rem',
                        color: 'var(--text-color)',
                        fontSize: '0.75rem',
                        fontFamily: 'var(--font-mono)',
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                      Size (Bytes)
                    </label>
                    <input
                      type="number"
                      value={editPayload.aac_zip_size ?? ''}
                      onChange={(e) => {
                        const val = e.target.value ? parseInt(e.target.value, 10) : null;
                        setEditPayload((p) => ({ ...p, aac_zip_size: val }));
                      }}
                      placeholder="e.g. 157286400"
                      style={{
                        width: '100%',
                        backgroundColor: 'var(--sub-alt-color)',
                        border: '1px solid var(--sub-color)',
                        borderRadius: 'var(--border-radius)',
                        padding: '0.45rem 0.65rem',
                        color: 'var(--text-color)',
                        fontSize: '0.75rem',
                      }}
                    />
                  </div>
                </div>

                <div style={{ marginTop: '0.65rem' }}>
                  <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                    GoFile High-Speed Download URL
                  </label>
                  <input
                    type="url"
                    value={editPayload.aac_gofile_url ?? ''}
                    onChange={(e) => setEditPayload((p) => ({ ...p, aac_gofile_url: e.target.value }))}
                    placeholder="https://gofile.io/d/..."
                    style={{
                      width: '100%',
                      backgroundColor: 'var(--sub-alt-color)',
                      border: '1px solid var(--sub-color)',
                      borderRadius: 'var(--border-radius)',
                      padding: '0.45rem 0.65rem',
                      color: 'var(--text-color)',
                      fontSize: '0.75rem',
                    }}
                  />
                </div>

                {verifyResult?.key === `${editAlbum.album_id}:aac` && (
                  <div
                    style={{
                      marginTop: '0.65rem',
                      padding: '0.4rem 0.65rem',
                      borderRadius: 'var(--border-radius)',
                      fontSize: '0.72rem',
                      backgroundColor: verifyResult.result.valid ? 'rgba(152, 195, 121, 0.15)' : 'rgba(202, 71, 84, 0.15)',
                      color: verifyResult.result.valid ? 'var(--success-color)' : 'var(--error-color)',
                      border: `1px solid ${verifyResult.result.valid ? 'rgba(152, 195, 121, 0.3)' : 'rgba(202, 71, 84, 0.3)'}`,
                    }}
                  >
                    {verifyResult.result.valid
                      ? `✅ Telegram file valid! Size: ${formatBytes(verifyResult.result.file_size)}`
                      : `❌ Verification failed: ${verifyResult.result.error || verifyResult.result.message}`}
                  </div>
                )}
              </div>

              {/* FORMAT 3: DOLBY ATMOS ZIP */}
              <div
                style={{
                  backgroundColor: 'var(--bg-color)',
                  padding: '1rem',
                  borderRadius: 'var(--border-radius)',
                  border: '1px solid rgba(97, 218, 251, 0.3)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: '#61dafb', fontWeight: 700, fontSize: '0.82rem' }}>
                    <Music size={15} />
                    <span>Dolby Atmos ZIP</span>
                    {editPayload.atmos_zip_size ? (
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-color)', fontWeight: 500 }}>
                        ({formatBytes(editPayload.atmos_zip_size)})
                      </span>
                    ) : null}
                  </div>

                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    <button
                      type="button"
                      className="mt-btn"
                      style={{ padding: '0.25rem 0.55rem', fontSize: '0.68rem' }}
                      onClick={() => handleVerifyZip(editAlbum.album_id, 'atmos')}
                      disabled={!editPayload.atmos_zip_file_id || verifyingKey === `${editAlbum.album_id}:atmos`}
                      title="Test file ID with Telegram Bot API"
                    >
                      <ShieldCheck size={12} className={verifyingKey === `${editAlbum.album_id}:atmos` ? 'animate-spin' : ''} />
                      <span>Verify File ID</span>
                    </button>
                    <button
                      type="button"
                      className="mt-btn danger"
                      style={{ padding: '0.25rem 0.55rem', fontSize: '0.68rem' }}
                      onClick={() => {
                        setEditPayload((p) => ({
                          ...p,
                          atmos_zip_file_id: '',
                          atmos_zip_size: null,
                          atmos_gofile_url: '',
                        }));
                      }}
                      title="Clear Atmos fields"
                    >
                      <span>Clear Atmos</span>
                    </button>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: '0.75rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                      Telegram File ID
                    </label>
                    <input
                      type="text"
                      value={editPayload.atmos_zip_file_id ?? ''}
                      onChange={(e) => setEditPayload((p) => ({ ...p, atmos_zip_file_id: e.target.value }))}
                      placeholder="BQACAgIAAxkBAA..."
                      style={{
                        width: '100%',
                        backgroundColor: 'var(--sub-alt-color)',
                        border: '1px solid var(--sub-color)',
                        borderRadius: 'var(--border-radius)',
                        padding: '0.45rem 0.65rem',
                        color: 'var(--text-color)',
                        fontSize: '0.75rem',
                        fontFamily: 'var(--font-mono)',
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                      Size (Bytes)
                    </label>
                    <input
                      type="number"
                      value={editPayload.atmos_zip_size ?? ''}
                      onChange={(e) => {
                        const val = e.target.value ? parseInt(e.target.value, 10) : null;
                        setEditPayload((p) => ({ ...p, atmos_zip_size: val }));
                      }}
                      placeholder="e.g. 786432000"
                      style={{
                        width: '100%',
                        backgroundColor: 'var(--sub-alt-color)',
                        border: '1px solid var(--sub-color)',
                        borderRadius: 'var(--border-radius)',
                        padding: '0.45rem 0.65rem',
                        color: 'var(--text-color)',
                        fontSize: '0.75rem',
                      }}
                    />
                  </div>
                </div>

                <div style={{ marginTop: '0.65rem' }}>
                  <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--sub-color)', marginBottom: '0.2rem' }}>
                    GoFile High-Speed Download URL
                  </label>
                  <input
                    type="url"
                    value={editPayload.atmos_gofile_url ?? ''}
                    onChange={(e) => setEditPayload((p) => ({ ...p, atmos_gofile_url: e.target.value }))}
                    placeholder="https://gofile.io/d/..."
                    style={{
                      width: '100%',
                      backgroundColor: 'var(--sub-alt-color)',
                      border: '1px solid var(--sub-color)',
                      borderRadius: 'var(--border-radius)',
                      padding: '0.45rem 0.65rem',
                      color: 'var(--text-color)',
                      fontSize: '0.75rem',
                    }}
                  />
                </div>

                {verifyResult?.key === `${editAlbum.album_id}:atmos` && (
                  <div
                    style={{
                      marginTop: '0.65rem',
                      padding: '0.4rem 0.65rem',
                      borderRadius: 'var(--border-radius)',
                      fontSize: '0.72rem',
                      backgroundColor: verifyResult.result.valid ? 'rgba(152, 195, 121, 0.15)' : 'rgba(202, 71, 84, 0.15)',
                      color: verifyResult.result.valid ? 'var(--success-color)' : 'var(--error-color)',
                      border: `1px solid ${verifyResult.result.valid ? 'rgba(152, 195, 121, 0.3)' : 'rgba(202, 71, 84, 0.3)'}`,
                    }}
                  >
                    {verifyResult.result.valid
                      ? `✅ Telegram file valid! Size: ${formatBytes(verifyResult.result.file_size)}`
                      : `❌ Verification failed: ${verifyResult.result.error || verifyResult.result.message}`}
                  </div>
                )}
              </div>
            </div>

            {/* Modal Footer */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginTop: '1.5rem',
                paddingTop: '1rem',
                borderTop: '1px solid var(--sub-color)',
              }}
            >
              <button
                className="mt-btn danger"
                onClick={() => handleDeleteAlbum(editAlbum.album_id)}
                title="Completely delete album record from database"
              >
                <Trash2 size={14} />
                <span>Delete Album</span>
              </button>

              <div style={{ display: 'flex', gap: '0.75rem' }}>
                <button className="mt-btn" onClick={() => setEditAlbum(null)} disabled={isSaving}>
                  <span>Cancel</span>
                </button>
                <button className="mt-btn primary" onClick={handleSaveEdit} disabled={isSaving}>
                  <Save size={14} className={isSaving ? 'animate-spin' : ''} />
                  <span>{isSaving ? 'Saving Changes...' : 'Save Changes'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 5. Inspect Details & Tracks Modal */}
      {inspectAlbumId && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1.5rem',
          }}
          onClick={() => setInspectAlbumId(null)}
        >
          <div
            className="mt-card"
            style={{
              width: '100%',
              maxWidth: '850px',
              maxHeight: '90vh',
              overflowY: 'auto',
              backgroundColor: 'var(--sub-alt-color)',
              border: '1px solid var(--sub-color)',
              boxShadow: 'var(--shadow-sm)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="card-header" style={{ marginBottom: '1rem' }}>
              <div className="card-title">
                <Layers size={17} />
                <span>Album Inspector & Cached Tracks</span>
              </div>
              <button
                className="mt-btn"
                style={{ padding: '0.3rem 0.5rem' }}
                onClick={() => setInspectAlbumId(null)}
              >
                <X size={15} />
              </button>
            </div>

            {inspectLoading || !inspectDetails ? (
              <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--sub-color)' }}>
                <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 0.5rem auto' }} />
                <div>Fetching album tracks from database...</div>
              </div>
            ) : (
              <div>
                {/* Album Header */}
                <div
                  style={{
                    display: 'flex',
                    gap: '1rem',
                    alignItems: 'center',
                    backgroundColor: 'var(--bg-color)',
                    padding: '1rem',
                    borderRadius: 'var(--border-radius)',
                    marginBottom: '1.25rem',
                  }}
                >
                  {inspectDetails.album.artwork ? (
                    <img
                      src={inspectDetails.album.artwork.replace('{w}x{h}', '160x160')}
                      alt={inspectDetails.album.album}
                      style={{ width: '60px', height: '60px', borderRadius: '6px', objectFit: 'cover' }}
                    />
                  ) : (
                    <Disc size={40} color="var(--sub-color)" />
                  )}
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, color: 'var(--text-color)', fontSize: '1.05rem' }}>
                      {inspectDetails.album.album}
                    </div>
                    <div style={{ color: 'var(--sub-color)', fontSize: '0.82rem' }}>
                      {inspectDetails.album.artist}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--main-color)', marginTop: '0.2rem' }}>
                      ID: {inspectDetails.album.album_id} • {inspectDetails.tracks.length} tracks cached in DB
                    </div>
                  </div>

                  <button
                    className="mt-btn primary"
                    onClick={() => {
                      const alb = inspectDetails.album;
                      setInspectAlbumId(null);
                      handleOpenEdit(alb);
                    }}
                  >
                    <Edit3 size={13} />
                    <span>Edit Properties</span>
                  </button>
                </div>

                {/* Tracks Table */}
                <div style={{ fontWeight: 600, fontSize: '0.82rem', marginBottom: '0.5rem', color: 'var(--text-color)' }}>
                  Cached Tracks ({inspectDetails.tracks.length})
                </div>

                {inspectDetails.tracks.length === 0 ? (
                  <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--sub-color)', backgroundColor: 'var(--bg-color)', borderRadius: 'var(--border-radius)' }}>
                    No individual tracks cached in database for this album.
                  </div>
                ) : (
                  <div style={{ overflowX: 'auto', backgroundColor: 'var(--bg-color)', borderRadius: 'var(--border-radius)' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.76rem' }}>
                      <thead>
                        <tr style={{ color: 'var(--sub-color)', borderBottom: '1px solid var(--sub-alt-color)' }}>
                          <th style={{ padding: '0.6rem 0.8rem' }}>#</th>
                          <th style={{ padding: '0.6rem 0.8rem' }}>Track Title</th>
                          <th style={{ padding: '0.6rem 0.8rem' }}>Artist</th>
                          <th style={{ padding: '0.6rem 0.8rem' }}>Formats Available</th>
                          <th style={{ padding: '0.6rem 0.8rem' }}>Size</th>
                          <th style={{ padding: '0.6rem 0.8rem' }}>ISRC</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inspectDetails.tracks.map((t, idx) => (
                          <tr key={t.song_id || idx} style={{ borderBottom: '1px solid var(--sub-alt-color)' }}>
                            <td style={{ padding: '0.55rem 0.8rem', color: 'var(--sub-color)' }}>{idx + 1}</td>
                            <td style={{ padding: '0.55rem 0.8rem', fontWeight: 600, color: 'var(--text-color)' }}>
                              {t.title}
                            </td>
                            <td style={{ padding: '0.55rem 0.8rem', color: 'var(--sub-color)' }}>{t.artist}</td>
                            <td style={{ padding: '0.55rem 0.8rem' }}>
                              <div style={{ display: 'flex', gap: '3px' }}>
                                {t.formats.map((fmt) => (
                                  <span
                                    key={fmt}
                                    style={{
                                      fontSize: '0.65rem',
                                      fontWeight: 700,
                                      padding: '1px 5px',
                                      borderRadius: '4px',
                                      backgroundColor:
                                        fmt === 'ALAC'
                                          ? 'rgba(226, 183, 20, 0.15)'
                                          : fmt === 'ATMOS'
                                          ? 'rgba(97, 218, 251, 0.15)'
                                          : 'rgba(189, 147, 249, 0.15)',
                                      color:
                                        fmt === 'ALAC'
                                          ? 'var(--main-color)'
                                          : fmt === 'ATMOS'
                                          ? '#61dafb'
                                          : '#bd93f9',
                                    }}
                                  >
                                    {fmt}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td style={{ padding: '0.55rem 0.8rem', color: 'var(--sub-color)' }}>
                              {formatBytes(t.alac_size || t.aac_size || t.atmos_size)}
                            </td>
                            <td style={{ padding: '0.55rem 0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--sub-color)', fontSize: '0.7rem' }}>
                              {t.isrc || '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
