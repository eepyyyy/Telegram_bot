export interface QueueStats {
  alac: number;
  lossless: number;
  aac: number;
  atmos: number;
  mv: number;
  total: number;
}

export interface SystemStats {
  os: string;
  python_version: string;
  uptime_seconds: number;
  cpu_percent: number;
  memory: {
    total_gb: number;
    used_gb: number;
    percent: number;
  };
  disk: {
    total_gb: number;
    used_gb: number;
    free_gb: number;
    percent: number;
  };
}

export interface BotStatus {
  is_paused: boolean;
  maintenance_mode: boolean;
  maintenance_message: string;
  active_downloads_count: number;
  queues: QueueStats;
  system: SystemStats;
  server_time: string;
}

export interface ActiveDownloadItem {
  task_id: string;
  user_id: number;
  track_title: string;
  artist: string;
  format: string;
  status: string;
  progress: number;
  cancelled: boolean;
  start_time: string | null;
  duration_seconds: number;
}

export interface DatabaseStats {
  total_tracks: number;
  total_albums: number;
  total_users: number;
  premium_users: number;
  downloads_today: number;
  total_downloads: number;
  total_size_bytes: number;
  total_size_gb: number;
  formats: {
    alac: { count: number; size_gb: number };
    aac: { count: number; size_gb: number };
    atmos: { count: number; size_gb: number };
  };
}

export interface UserItem {
  user_id: number;
  username: string | null;
  first_name: string | null;
  download_count: number;
  downloaded_today: number;
  last_download: string | null;
  is_premium: boolean;
  daily_limit: number;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  logger: string;
  message: string;
}

export interface RecentDownloadItem {
  id: number;
  user_id: number;
  username: string | null;
  first_name: string | null;
  is_premium: boolean;
  song_id: string | null;
  title: string;
  artist: string;
  album: string | null;
  artwork: string | null;
  format_type: 'ALAC' | 'AAC' | 'ATMOS' | 'MV' | string;
  size: number;
  is_cached: boolean;
  downloaded_at: string | null;
}

export interface RecentDownloadsResponse {
  downloads: RecentDownloadItem[];
  total: number;
  page: number;
  limit: number;
  cache_hit_rate: number;
  total_downloads: number;
  cached_downloads: number;
}

export interface ArtistSearchResult {
  id: string;
  name: string;
  url: string;
  artwork: string | null;
  genres: string[];
}

export interface DiscographyRelease {
  name: string;
  release_date?: string;
  track_count?: number;
  url: string;
  is_cached: boolean;
}

export interface ArtistDetailsResponse {
  artist_id: string;
  name: string;
  url: string;
  storefront: string;
  artwork: string | null;
  genres: string[];
  categories: Record<string, DiscographyRelease[]>;
  total_releases: number;
  total_cached_releases: number;
  coverage_percent: number;
  cached_tracks: {
    alac: number;
    aac: number;
    atmos: number;
    total: number;
  };
}

export interface CacheArtistPayload {
  albums: { url: string; name: string; track_count?: number }[];
  format: 'alac' | 'aac' | 'atmos' | 'all';
  admin_user_id?: number;
}

export interface CacheArtistResponse {
  success: boolean;
  queued_jobs: number;
  formats: string[];
  message: string;
}

