import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ArtistSearchResult,
  ArtistDetailsResponse,
  CacheArtistPayload,
  ActiveDownloadItem,
  BotStatus,
} from '../types';
import { api } from '../api';
import {
  Search,
  Music,
  Disc,
  Layers,
  Sparkles,
  CheckCircle2,
  Circle,
  Zap,
  ArrowRight,
  ExternalLink,
  RefreshCw,
  CheckSquare,
  Square,
  Check,
  AlertCircle,
  Radio,
  X,
} from 'lucide-react';

interface ArtistCacherProps {
  activeDownloads?: ActiveDownloadItem[];
  status?: BotStatus | null;
  onRefreshData?: () => void;
}

export const ArtistCacher: React.FC<ArtistCacherProps> = ({
  activeDownloads: propActiveDownloads,
  status: propStatus,
  onRefreshData,
}) => {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<ArtistSearchResult[]>([]);
  const [selectedArtist, setSelectedArtist] = useState<ArtistDetailsResponse | null>(null);
  const [isLoadingArtist, setIsLoadingArtist] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>('Full Albums');
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());
  const [targetFormat, setTargetFormat] = useState<'alac' | 'aac' | 'atmos' | 'all'>('alac');
  const [isCaching, setIsCaching] = useState(false);
  const [cacheResultMsg, setCacheResultMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Local active downloads state for fast live polling during caching
  const [localActiveDownloads, setLocalActiveDownloads] = useState<ActiveDownloadItem[]>([]);
  const [localQueues, setLocalQueues] = useState<any>(null);
  const prevActiveCountRef = useRef<number>(0);

  // Sync with propActiveDownloads or poll
  useEffect(() => {
    if (propActiveDownloads) {
      setLocalActiveDownloads(propActiveDownloads);
    }
  }, [propActiveDownloads]);

  useEffect(() => {
    if (propStatus?.queues) {
      setLocalQueues(propStatus.queues);
    }
  }, [propStatus]);

  // Fast live polling when there are active downloads or queues
  const pollLiveProgress = useCallback(async () => {
    try {
      const [downloadsRes, statusRes] = await Promise.allSettled([
        api.getActiveDownloads(),
        api.getStatus(),
      ]);

      let currentActiveCount = 0;

      if (downloadsRes.status === 'fulfilled') {
        setLocalActiveDownloads(downloadsRes.value.active_downloads);
        currentActiveCount = downloadsRes.value.active_downloads.length;
      }
      if (statusRes.status === 'fulfilled') {
        setLocalQueues(statusRes.value.queues);
      }

      // If downloads were running and just completed (transition to 0), auto-refresh artist cache status
      if (prevActiveCountRef.current > 0 && currentActiveCount === 0 && selectedArtist) {
        loadArtistDetails(selectedArtist.url, true);
        if (onRefreshData) onRefreshData();
      }

      prevActiveCountRef.current = currentActiveCount;
    } catch {
      // ignore
    }
  }, [selectedArtist, onRefreshData]);

  // Polling interval
  useEffect(() => {
    const totalQueued = localQueues?.total || 0;
    const isBusy = localActiveDownloads.length > 0 || totalQueued > 0 || isCaching;
    const intervalTime = isBusy ? 2500 : 8000;

    const timer = setInterval(() => {
      if (!document.hidden) {
        pollLiveProgress();
      }
    }, intervalTime);

    return () => clearInterval(timer);
  }, [pollLiveProgress, localActiveDownloads.length, localQueues?.total, isCaching]);

  // Debounced artist search
  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed || trimmed.startsWith('http')) {
      setSearchResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await api.searchArtist(trimmed);
        setSearchResults(res.artists || []);
      } catch (err) {
        console.error('Artist search failed:', err);
      } finally {
        setIsSearching(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [query]);

  const loadArtistDetails = async (artistUrlOrId: string, isSilent = false) => {
    if (!isSilent) {
      setIsLoadingArtist(true);
      setCacheResultMsg(null);
      setSelectedUrls(new Set());
      setSearchResults([]);
    }

    try {
      const data = await api.getArtistDetails(artistUrlOrId);
      setSelectedArtist(data);

      if (!isSilent) {
        // Default to the first available category with items
        const categories = Object.keys(data.categories || {});
        const firstNonEmpty = categories.find((cat) => (data.categories[cat] || []).length > 0);
        if (firstNonEmpty) {
          setActiveCategory(firstNonEmpty);
        } else if (categories.length > 0) {
          setActiveCategory(categories[0]);
        }
      }
    } catch (err) {
      if (!isSilent) {
        alert(`Failed to fetch artist details: ${err}`);
      }
    } finally {
      if (!isSilent) {
        setIsLoadingArtist(false);
      }
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    loadArtistDetails(trimmed);
  };

  // Toggle individual release selection (ONLY for UNCACHED items)
  const toggleRelease = (url: string, isCached: boolean) => {
    if (isCached) return; // Prevent selection of already cached items

    setSelectedUrls((prev) => {
      const next = new Set(prev);
      if (next.has(url)) {
        next.delete(url);
      } else {
        next.add(url);
      }
      return next;
    });
  };

  // Select / Deselect all UNCACHED in current active category
  const toggleCategorySelection = () => {
    if (!selectedArtist) return;
    const currentCategoryUncached = (selectedArtist.categories[activeCategory] || []).filter(
      (item) => !item.is_cached
    );
    if (currentCategoryUncached.length === 0) return;

    const allUncachedSelected = currentCategoryUncached.every((item) => selectedUrls.has(item.url));

    setSelectedUrls((prev) => {
      const next = new Set(prev);
      currentCategoryUncached.forEach((item) => {
        if (allUncachedSelected) {
          next.delete(item.url);
        } else {
          next.add(item.url);
        }
      });
      return next;
    });
  };

  // Select all UNCACHED discography releases across all categories
  const selectAllDiscography = () => {
    if (!selectedArtist) return;
    const uncachedUrls = new Set<string>();
    Object.values(selectedArtist.categories).forEach((items) => {
      items.forEach((item) => {
        if (!item.is_cached) {
          uncachedUrls.add(item.url);
        }
      });
    });
    setSelectedUrls(uncachedUrls);
  };

  const clearSelection = () => {
    setSelectedUrls(new Set());
  };

  // Trigger Bulk Caching
  const handleStartCaching = async () => {
    if (!selectedArtist || selectedUrls.size === 0) return;

    setIsCaching(true);
    setCacheResultMsg(null);

    // Build payload releases list (filter out any already cached items for safety)
    const albumsToCache: { url: string; name: string; track_count?: number }[] = [];
    Object.values(selectedArtist.categories).forEach((items) => {
      items.forEach((item) => {
        if (selectedUrls.has(item.url) && !item.is_cached) {
          albumsToCache.push({
            url: item.url,
            name: item.name,
            track_count: item.track_count,
          });
        }
      });
    });

    const payload: CacheArtistPayload = {
      albums: albumsToCache,
      format: targetFormat,
    };

    try {
      const res = await api.cacheArtist(payload);
      setCacheResultMsg({
        type: 'success',
        text: `🚀 ${res.message}`,
      });
      clearSelection();
      pollLiveProgress();
    } catch (err) {
      setCacheResultMsg({
        type: 'error',
        text: `Failed to queue releases: ${err}`,
      });
    } finally {
      setIsCaching(false);
    }
  };

  // Cancel an individual active download task
  const handleCancelActiveTask = async (taskId: string) => {
    try {
      await api.cancelTask(taskId);
      setLocalActiveDownloads((prev) => prev.filter((t) => t.task_id !== taskId));
    } catch (err) {
      alert(`Failed to cancel task: ${err}`);
    }
  };

  const currentCategoryItems = selectedArtist ? selectedArtist.categories[activeCategory] || [] : [];
  const uncachedCategoryItems = currentCategoryItems.filter((item) => !item.is_cached);
  const isAllCategoryUncachedSelected =
    uncachedCategoryItems.length > 0 &&
    uncachedCategoryItems.every((item) => selectedUrls.has(item.url));

  const totalQueuedJobs = localQueues?.total || 0;
  const isCacherBusy = localActiveDownloads.length > 0 || totalQueuedJobs > 0;

  // Helper to check if a release is actively being downloaded
  const getActiveTaskForRelease = (releaseName: string) => {
    if (!releaseName || localActiveDownloads.length === 0) return null;
    const norm = releaseName.toLowerCase().trim();
    return localActiveDownloads.find((task) => {
      const trackTitle = (task.track_title || '').toLowerCase();
      const albumTitle = (task.album_name || '').toLowerCase();
      return trackTitle.includes(norm) || albumTitle.includes(norm) || norm.includes(trackTitle);
    });
  };

  return (
    <div className="mt-card" style={{ gap: '1.5rem' }}>
      {/* 1. Header */}
      <div className="card-header">
        <div className="card-title">
          <Sparkles size={18} />
          <span>Artist Discography Cacher & Stream Vault Importer</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {isCacherBusy && (
            <span
              className="animate-pulse"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '3px 9px',
                borderRadius: '12px',
                backgroundColor: 'rgba(97, 218, 251, 0.15)',
                color: '#61dafb',
                fontSize: '0.72rem',
                fontWeight: 700,
              }}
            >
              <Radio size={12} />
              <span>CACHING ACTIVE ({localActiveDownloads.length} running, {totalQueuedJobs} queued)</span>
            </span>
          )}
          <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
            Apple Music API & stream.eepy.in
          </span>
        </div>
      </div>

      {/* 2. Search & URL Bar */}
      <form onSubmit={handleSearchSubmit} style={{ position: 'relative' }}>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search
              size={15}
              style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--sub-color)' }}
            />
            <input
              type="text"
              className="mt-input"
              style={{ paddingLeft: '36px', width: '100%' }}
              placeholder="Paste Apple Music Artist Link (e.g. https://music.apple.com/us/artist/...) or search artist name..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {isSearching && (
              <RefreshCw
                size={14}
                className="animate-spin"
                style={{ position: 'absolute', right: '12px', top: '12px', color: 'var(--main-color)' }}
              />
            )}
          </div>
          <button
            type="submit"
            className="mt-btn primary"
            disabled={isLoadingArtist || !query.trim()}
            style={{ minWidth: '130px', justifyContent: 'center' }}
          >
            {isLoadingArtist ? (
              <>
                <RefreshCw size={14} className="animate-spin" />
                <span>Loading...</span>
              </>
            ) : (
              <>
                <Search size={14} />
                <span>Fetch Artist</span>
              </>
            )}
          </button>
        </div>

        {/* Autocomplete Search Dropdown */}
        {searchResults.length > 0 && (
          <div
            style={{
              position: 'absolute',
              top: '105%',
              left: 0,
              right: '140px',
              backgroundColor: 'var(--bg-color)',
              border: '1px solid var(--sub-color)',
              borderRadius: 'var(--border-radius)',
              boxShadow: 'var(--shadow-sm)',
              zIndex: 50,
              maxHeight: '280px',
              overflowY: 'auto',
              padding: '0.4rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.2rem',
            }}
          >
            {searchResults.map((item) => (
              <div
                key={item.id}
                style={{
                  padding: '0.5rem 0.75rem',
                  borderRadius: 'var(--border-radius)',
                  cursor: 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  transition: 'background-color 0.15s ease',
                }}
                className="hover-highlight"
                onClick={() => {
                  setQuery(item.name);
                  loadArtistDetails(item.url || item.id);
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                  <Disc size={15} color="var(--main-color)" />
                  <span style={{ fontWeight: 600, color: 'var(--text-color)' }}>{item.name}</span>
                </div>
                {item.genres && item.genres.length > 0 && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>
                    {item.genres.join(', ')}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </form>

      {/* 3. Feedback Banner */}
      {cacheResultMsg && (
        <div
          style={{
            padding: '0.85rem 1.1rem',
            borderRadius: 'var(--border-radius)',
            backgroundColor:
              cacheResultMsg.type === 'success'
                ? 'rgba(152, 195, 121, 0.15)'
                : 'rgba(202, 71, 84, 0.15)',
            border: `1px solid ${
              cacheResultMsg.type === 'success' ? 'var(--success-color)' : 'var(--error-color)'
            }`,
            color:
              cacheResultMsg.type === 'success' ? 'var(--success-color)' : 'var(--error-color)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          {cacheResultMsg.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          <span>{cacheResultMsg.text}</span>
        </div>
      )}

      {/* 4. Live Caching Progress Panel */}
      {isCacherBusy && (
        <div
          style={{
            backgroundColor: 'var(--bg-color)',
            border: '1px solid #61dafb',
            borderRadius: 'var(--border-radius)',
            padding: '1rem 1.25rem',
            boxShadow: '0 0 16px rgba(97, 218, 251, 0.15)',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.85rem',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Radio size={16} color="#61dafb" className="animate-pulse" />
              <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--text-color)' }}>
                Live Caching Operations in Progress
              </span>
              <span
                style={{
                  fontSize: '0.72rem',
                  padding: '2px 7px',
                  borderRadius: '10px',
                  backgroundColor: 'rgba(97, 218, 251, 0.2)',
                  color: '#61dafb',
                  fontWeight: 700,
                }}
              >
                {localActiveDownloads.length} active • {totalQueuedJobs} pending
              </span>
            </div>
            <button
              className="mt-btn"
              style={{ fontSize: '0.72rem', padding: '0.25rem 0.5rem' }}
              onClick={pollLiveProgress}
              title="Refresh live status"
            >
              <RefreshCw size={12} />
              <span>Refresh</span>
            </button>
          </div>

          {/* Active Tasks List */}
          {localActiveDownloads.length === 0 ? (
            <div style={{ fontSize: '0.78rem', color: 'var(--sub-color)', fontStyle: 'italic' }}>
              Waiting for queue workers to pick up next pending job ({totalQueuedJobs} jobs in queue)...
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              {localActiveDownloads.map((task) => {
                const isIndeterminate = !task.progress || task.progress === 0;

                return (
                  <div
                    key={task.task_id}
                    style={{
                      backgroundColor: 'var(--sub-alt-color)',
                      padding: '0.65rem 0.85rem',
                      borderRadius: '6px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.4rem',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
                        <Disc size={15} color="var(--main-color)" className="animate-spin" />
                        <span
                          style={{
                            fontWeight: 600,
                            fontSize: '0.82rem',
                            color: 'var(--text-color)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                        >
                          {task.track_title}
                        </span>
                        {task.artist && (
                          <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
                            — {task.artist}
                          </span>
                        )}
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span
                          style={{
                            fontSize: '0.68rem',
                            padding: '1px 6px',
                            borderRadius: '4px',
                            backgroundColor: 'rgba(226, 183, 20, 0.15)',
                            color: 'var(--main-color)',
                            fontWeight: 700,
                          }}
                        >
                          {task.format}
                        </span>
                        <span style={{ fontSize: '0.72rem', color: '#61dafb', fontWeight: 600, textTransform: 'uppercase' }}>
                          {task.status} {task.progress > 0 ? `(${task.progress}%)` : ''}
                        </span>
                        <button
                          className="mt-btn danger"
                          style={{ padding: '2px 5px', fontSize: '0.68rem' }}
                          onClick={() => handleCancelActiveTask(task.task_id)}
                          title="Cancel this download task"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    </div>

                    {/* Progress Bar */}
                    <div
                      style={{
                        width: '100%',
                        height: '5px',
                        backgroundColor: 'var(--bg-color)',
                        borderRadius: '3px',
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          width: isIndeterminate ? '100%' : `${task.progress}%`,
                          height: '100%',
                          backgroundColor: '#61dafb',
                          transition: 'width 0.3s ease',
                          opacity: isIndeterminate ? 0.7 : 1,
                        }}
                        className={isIndeterminate ? 'animate-pulse' : ''}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 5. Selected Artist Profile & Discography View */}
      {selectedArtist && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Artist Hero Profile Banner */}
          <div
            style={{
              backgroundColor: 'var(--bg-color)',
              padding: '1.25rem',
              borderRadius: 'var(--border-radius)',
              border: '1px solid var(--sub-alt-color)',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '1.25rem',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
              {/* Artist Avatar */}
              <div
                style={{
                  width: '72px',
                  height: '72px',
                  borderRadius: '50%',
                  overflow: 'hidden',
                  backgroundColor: 'var(--sub-alt-color)',
                  border: '2px solid var(--main-color)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: 'var(--shadow-glow)',
                }}
              >
                {selectedArtist.artwork ? (
                  <img
                    src={selectedArtist.artwork}
                    alt={selectedArtist.name}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                ) : (
                  <Music size={28} color="var(--main-color)" />
                )}
              </div>

              {/* Artist Info */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <h2 style={{ fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-color)' }}>
                    {selectedArtist.name}
                  </h2>
                  <a
                    href={selectedArtist.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: 'var(--sub-color)', display: 'inline-flex' }}
                    title="Open on Apple Music"
                  >
                    <ExternalLink size={14} />
                  </a>
                </div>
                <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
                  {selectedArtist.genres?.join(' • ') || 'Artist'} • {selectedArtist.total_releases} total releases found
                </span>
              </div>
            </div>

            {/* Local DB Coverage Meter */}
            <div
              style={{
                display: 'flex',
                gap: '1.25rem',
                alignItems: 'center',
                flexWrap: 'wrap',
              }}
            >
              <div
                style={{
                  backgroundColor: 'var(--sub-alt-color)',
                  padding: '0.65rem 1rem',
                  borderRadius: 'var(--border-radius)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.25rem',
                  minWidth: '180px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', fontWeight: 600 }}>
                  <span style={{ color: 'var(--sub-color)' }}>DATABASE COVERAGE</span>
                  <span style={{ color: 'var(--main-color)' }}>{selectedArtist.coverage_percent}%</span>
                </div>
                <div
                  style={{
                    width: '100%',
                    height: '5px',
                    backgroundColor: 'var(--bg-color)',
                    borderRadius: '3px',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${selectedArtist.coverage_percent}%`,
                      height: '100%',
                      backgroundColor: 'var(--main-color)',
                    }}
                  />
                </div>
                <span style={{ fontSize: '0.68rem', color: 'var(--sub-color)' }}>
                  {selectedArtist.total_cached_releases} of {selectedArtist.total_releases} albums in DB
                </span>
              </div>

              {/* Cached Tracks Breakdown */}
              <div
                style={{
                  backgroundColor: 'var(--sub-alt-color)',
                  padding: '0.65rem 1rem',
                  borderRadius: 'var(--border-radius)',
                  fontSize: '0.75rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.2rem',
                }}
              >
                <span style={{ color: 'var(--sub-color)', fontWeight: 600, fontSize: '0.7rem' }}>
                  CACHED AUDIO TRACKS
                </span>
                <div style={{ display: 'flex', gap: '0.65rem', fontWeight: 700 }}>
                  <span style={{ color: 'var(--main-color)' }}>ALAC: {selectedArtist.cached_tracks.alac}</span>
                  <span style={{ color: '#bd93f9' }}>AAC: {selectedArtist.cached_tracks.aac}</span>
                  <span style={{ color: '#61dafb' }}>ATMOS: {selectedArtist.cached_tracks.atmos}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Category Tabs & Bulk Select Buttons */}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '0.75rem',
              borderBottom: '1px solid var(--sub-alt-color)',
              paddingBottom: '0.75rem',
            }}
          >
            {/* Categories */}
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {Object.keys(selectedArtist.categories).map((catName) => {
                const items = selectedArtist.categories[catName] || [];
                const uncachedCount = items.filter((i) => !i.is_cached).length;
                const isActive = activeCategory === catName;

                return (
                  <button
                    key={catName}
                    className={`mt-btn ${isActive ? 'primary' : ''}`}
                    style={{
                      padding: '0.4rem 0.85rem',
                      fontSize: '0.75rem',
                      fontWeight: isActive ? 700 : 500,
                    }}
                    onClick={() => setActiveCategory(catName)}
                  >
                    <Layers size={13} />
                    <span>{catName}</span>
                    <span
                      style={{
                        padding: '1px 5px',
                        borderRadius: '8px',
                        backgroundColor: isActive ? 'var(--bg-color)' : 'var(--sub-alt-color)',
                        fontSize: '0.68rem',
                        fontWeight: 700,
                        color: uncachedCount > 0 ? 'var(--text-color)' : 'var(--success-color)',
                      }}
                    >
                      {items.length} {uncachedCount === 0 && items.length > 0 ? '✓' : ''}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Quick Bulk Selection Tools (Only applies to UNCACHED items) */}
            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
              <button
                className="mt-btn"
                style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem' }}
                onClick={toggleCategorySelection}
                disabled={uncachedCategoryItems.length === 0}
                title={
                  uncachedCategoryItems.length === 0
                    ? 'All items in this category are already cached in database'
                    : 'Select or deselect all uncached items in this category'
                }
              >
                {uncachedCategoryItems.length === 0 ? (
                  <>
                    <CheckCircle2 size={13} color="var(--success-color)" />
                    <span>Category Fully Cached</span>
                  </>
                ) : isAllCategoryUncachedSelected ? (
                  <>
                    <Square size={13} />
                    <span>Deselect Category ({uncachedCategoryItems.length})</span>
                  </>
                ) : (
                  <>
                    <CheckSquare size={13} />
                    <span>Select Uncached ({uncachedCategoryItems.length})</span>
                  </>
                )}
              </button>

              <button
                className="mt-btn"
                style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem' }}
                onClick={selectAllDiscography}
              >
                <Check size={13} />
                <span>Select All Uncached</span>
              </button>

              {selectedUrls.size > 0 && (
                <button
                  className="mt-btn danger"
                  style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem' }}
                  onClick={clearSelection}
                >
                  Clear Selection ({selectedUrls.size})
                </button>
              )}
            </div>
          </div>

          {/* Releases Grid */}
          {currentCategoryItems.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--sub-color)' }}>
              No releases found in "{activeCategory}".
            </div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                gap: '0.85rem',
              }}
            >
              {currentCategoryItems.map((release) => {
                const isSelected = selectedUrls.has(release.url);
                const isCached = release.is_cached;
                const activeTask = getActiveTaskForRelease(release.name);
                const isDownloading = !!activeTask;

                return (
                  <div
                    key={release.url}
                    style={{
                      backgroundColor: isDownloading
                        ? 'rgba(97, 218, 251, 0.08)'
                        : isSelected
                        ? 'rgba(226, 183, 20, 0.08)'
                        : isCached
                        ? 'rgba(152, 195, 121, 0.03)'
                        : 'var(--bg-color)',
                      border: isDownloading
                        ? '1.5px solid #61dafb'
                        : isSelected
                        ? '1.5px solid var(--main-color)'
                        : isCached
                        ? '1px solid rgba(152, 195, 121, 0.2)'
                        : '1px solid var(--sub-alt-color)',
                      borderRadius: 'var(--border-radius)',
                      padding: '0.85rem 1rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.5rem',
                      cursor: isCached || isDownloading ? 'default' : 'pointer',
                      opacity: isCached ? 0.7 : 1,
                      transition: 'all 0.15s ease',
                      boxShadow: isDownloading
                        ? '0 0 12px rgba(97, 218, 251, 0.2)'
                        : isSelected
                        ? 'var(--shadow-glow)'
                        : 'none',
                    }}
                    onClick={() => toggleRelease(release.url, isCached || isDownloading)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                      {/* Checkbox indicator: ONLY FOR UNCACHED NON-DOWNLOADING ITEMS */}
                      {isCached ? (
                        <div style={{ color: 'var(--success-color)' }} title="Already cached in database">
                          <CheckCircle2 size={20} />
                        </div>
                      ) : isDownloading ? (
                        <div style={{ color: '#61dafb' }} title="Currently downloading">
                          <Disc size={20} className="animate-spin" />
                        </div>
                      ) : (
                        <div style={{ color: isSelected ? 'var(--main-color)' : 'var(--sub-color)' }}>
                          {isSelected ? <CheckCircle2 size={20} /> : <Circle size={20} />}
                        </div>
                      )}

                      {/* Album Details */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            fontWeight: 600,
                            fontSize: '0.85rem',
                            color: isCached ? 'var(--sub-color)' : 'var(--text-color)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                          title={release.name}
                        >
                          {release.name}
                        </div>
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            marginTop: '0.2rem',
                            fontSize: '0.72rem',
                            color: 'var(--sub-color)',
                          }}
                        >
                          {release.release_date && <span>{release.release_date.split('-')[0]}</span>}
                          {release.track_count && <span>• {release.track_count} tracks</span>}
                        </div>
                      </div>

                      {/* Cache / Downloading Status Badge */}
                      <div>
                        {isDownloading ? (
                          <span
                            className="animate-pulse"
                            style={{
                              fontSize: '0.65rem',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              backgroundColor: 'rgba(97, 218, 251, 0.2)',
                              color: '#61dafb',
                              fontWeight: 700,
                            }}
                          >
                            DOWNLOADING
                          </span>
                        ) : isCached ? (
                          <span
                            style={{
                              fontSize: '0.65rem',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              backgroundColor: 'rgba(152, 195, 121, 0.15)',
                              color: 'var(--success-color)',
                              fontWeight: 700,
                            }}
                          >
                            CACHED
                          </span>
                        ) : (
                          <span
                            style={{
                              fontSize: '0.65rem',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              backgroundColor: 'var(--sub-alt-color)',
                              color: 'var(--sub-color)',
                              fontWeight: 600,
                            }}
                          >
                            UNCACHED
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Active Download Progress Bar on Card */}
                    {isDownloading && activeTask && (
                      <div
                        style={{
                          width: '100%',
                          height: '4px',
                          backgroundColor: 'var(--sub-alt-color)',
                          borderRadius: '2px',
                          overflow: 'hidden',
                          marginTop: '0.25rem',
                        }}
                      >
                        <div
                          style={{
                            width: activeTask.progress > 0 ? `${activeTask.progress}%` : '100%',
                            height: '100%',
                            backgroundColor: '#61dafb',
                          }}
                          className={activeTask.progress === 0 ? 'animate-pulse' : ''}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* 6. Sticky Action Bar for Caching */}
          {selectedUrls.size > 0 && (
            <div
              style={{
                position: 'sticky',
                bottom: '1rem',
                backgroundColor: 'var(--bg-color)',
                border: '2px solid var(--main-color)',
                borderRadius: 'var(--border-radius)',
                padding: '0.85rem 1.25rem',
                boxShadow: 'var(--shadow-glow)',
                display: 'flex',
                flexWrap: 'wrap',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '1rem',
                zIndex: 30,
              }}
            >
              {/* Selection info */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <div
                  style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--sub-alt-color)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--main-color)',
                    fontWeight: 700,
                  }}
                >
                  {selectedUrls.size}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-color)' }}>
                    {selectedUrls.size} uncached release(s) selected for caching
                  </span>
                  <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>
                    Jobs will be queued for Telegram bot workers
                  </span>
                </div>
              </div>

              {/* Format selection & Caching action */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', fontWeight: 600 }}>
                    FORMAT:
                  </span>
                  <select
                    className="mt-input"
                    style={{ padding: '0.35rem 0.65rem', fontSize: '0.75rem', fontWeight: 600 }}
                    value={targetFormat}
                    onChange={(e) => setTargetFormat(e.target.value as any)}
                  >
                    <option value="alac">ALAC Lossless (Hi-Res/48k)</option>
                    <option value="aac">AAC 256kbps</option>
                    <option value="atmos">Dolby Atmos (Spatial)</option>
                    <option value="all">All Formats (Lossless + AAC + Atmos)</option>
                  </select>
                </div>

                <button
                  className="mt-btn primary"
                  disabled={selectedUrls.size === 0 || isCaching}
                  onClick={handleStartCaching}
                  style={{ minWidth: '180px', justifyContent: 'center', padding: '0.5rem 1rem' }}
                >
                  {isCaching ? (
                    <>
                      <RefreshCw size={15} className="animate-spin" />
                      <span>Dispatching Jobs...</span>
                    </>
                  ) : (
                    <>
                      <Zap size={15} />
                      <span>Start Caching Now</span>
                      <ArrowRight size={14} />
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
