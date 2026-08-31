import React, { useState, useEffect } from 'react';
import {
  ArtistSearchResult,
  ArtistDetailsResponse,
  CacheArtistPayload,
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
} from 'lucide-react';

export const ArtistCacher: React.FC = () => {
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

  const loadArtistDetails = async (artistUrlOrId: string) => {
    setIsLoadingArtist(true);
    setCacheResultMsg(null);
    setSelectedUrls(new Set());
    setSearchResults([]);

    try {
      const data = await api.getArtistDetails(artistUrlOrId);
      setSelectedArtist(data);

      // Default to the first available category with items
      const categories = Object.keys(data.categories || {});
      const firstNonEmpty = categories.find((cat) => (data.categories[cat] || []).length > 0);
      if (firstNonEmpty) {
        setActiveCategory(firstNonEmpty);
      } else if (categories.length > 0) {
        setActiveCategory(categories[0]);
      }
    } catch (err) {
      alert(`Failed to fetch artist details: ${err}`);
    } finally {
      setIsLoadingArtist(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    loadArtistDetails(trimmed);
  };

  // Toggle individual release selection
  const toggleRelease = (url: string) => {
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

  // Select / Deselect all in current active category
  const toggleCategorySelection = () => {
    if (!selectedArtist) return;
    const currentCategoryItems = selectedArtist.categories[activeCategory] || [];
    const allSelected = currentCategoryItems.every((item) => selectedUrls.has(item.url));

    setSelectedUrls((prev) => {
      const next = new Set(prev);
      currentCategoryItems.forEach((item) => {
        if (allSelected) {
          next.delete(item.url);
        } else {
          next.add(item.url);
        }
      });
      return next;
    });
  };

  // Select all discography releases across all categories
  const selectAllDiscography = () => {
    if (!selectedArtist) return;
    const allUrls = new Set<string>();
    Object.values(selectedArtist.categories).forEach((items) => {
      items.forEach((item) => allUrls.add(item.url));
    });
    setSelectedUrls(allUrls);
  };

  // Select only uncached releases
  const selectUncachedReleases = () => {
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

    // Build payload releases list
    const albumsToCache: { url: string; name: string; track_count?: number }[] = [];
    Object.values(selectedArtist.categories).forEach((items) => {
      items.forEach((item) => {
        if (selectedUrls.has(item.url)) {
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
    } catch (err) {
      setCacheResultMsg({
        type: 'error',
        text: `Failed to queue releases: ${err}`,
      });
    } finally {
      setIsCaching(false);
    }
  };

  const currentCategoryItems = selectedArtist ? selectedArtist.categories[activeCategory] || [] : [];
  const isAllCurrentCategorySelected =
    currentCategoryItems.length > 0 && currentCategoryItems.every((item) => selectedUrls.has(item.url));

  return (
    <div className="mt-card" style={{ gap: '1.5rem' }}>
      {/* 1. Header */}
      <div className="card-header">
        <div className="card-title">
          <Sparkles size={18} />
          <span>Artist Discography Cacher & Stream Vault Importer</span>
        </div>
        <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
          Powered by Apple Music API & stream.eepy.in
        </span>
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

      {/* 4. Selected Artist Profile & Discography View */}
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
                const count = (selectedArtist.categories[catName] || []).length;
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
                      }}
                    >
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Quick Bulk Selection Tools */}
            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
              <button
                className="mt-btn"
                style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem' }}
                onClick={toggleCategorySelection}
              >
                {isAllCurrentCategorySelected ? <Square size={13} /> : <CheckSquare size={13} />}
                <span>{isAllCurrentCategorySelected ? 'Deselect Category' : 'Select Category'}</span>
              </button>

              <button
                className="mt-btn"
                style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem' }}
                onClick={selectUncachedReleases}
              >
                <Zap size={13} color="var(--main-color)" />
                <span>Select Uncached Only</span>
              </button>

              <button
                className="mt-btn"
                style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem' }}
                onClick={selectAllDiscography}
              >
                <Check size={13} />
                <span>Select All Discography</span>
              </button>

              {selectedUrls.size > 0 && (
                <button
                  className="mt-btn danger"
                  style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem' }}
                  onClick={clearSelection}
                >
                  Clear ({selectedUrls.size})
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

                return (
                  <div
                    key={release.url}
                    style={{
                      backgroundColor: isSelected ? 'rgba(226, 183, 20, 0.08)' : 'var(--bg-color)',
                      border: isSelected
                        ? '1px solid var(--main-color)'
                        : '1px solid var(--sub-alt-color)',
                      borderRadius: 'var(--border-radius)',
                      padding: '0.85rem 1rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.85rem',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      boxShadow: isSelected ? 'var(--shadow-glow)' : 'none',
                    }}
                    onClick={() => toggleRelease(release.url)}
                  >
                    {/* Checkbox indicator */}
                    <div style={{ color: isSelected ? 'var(--main-color)' : 'var(--sub-color)' }}>
                      {isSelected ? <CheckCircle2 size={20} /> : <Circle size={20} />}
                    </div>

                    {/* Album Details */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontWeight: 600,
                          fontSize: '0.85rem',
                          color: 'var(--text-color)',
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

                    {/* Cache Status Badge */}
                    <div>
                      {release.is_cached ? (
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
                );
              })}
            </div>
          )}

          {/* 5. Sticky Action Bar for Caching */}
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
                  {selectedUrls.size} release(s) selected for caching
                </span>
                <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>
                  Jobs will be dispatched to Telegram bot background workers
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
        </div>
      )}
    </div>
  );
};
