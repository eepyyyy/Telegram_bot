import React, { useState, useEffect } from 'react';
import { UserItem, DatabaseStats } from '../types';
import { api } from '../api';
import { Users, Search, Crown, RefreshCw } from 'lucide-react';

interface DatabaseExplorerProps {
  dbStats: DatabaseStats | null;
}

export const DatabaseExplorer: React.FC<DatabaseExplorerProps> = ({ dbStats }) => {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [totalUsers, setTotalUsers] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [updatingUserId, setUpdatingUserId] = useState<number | null>(null);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const data = await api.getUsers(page, 15, search);
      setUsers(data.users);
      setTotalUsers(data.total);
    } catch (err) {
      console.error('Failed to load users:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [page, search]);

  const handleTogglePremium = async (user: UserItem) => {
    setUpdatingUserId(user.user_id);
    const newPremium = !user.is_premium;
    const newLimit = newPremium ? 100 : 20;

    try {
      await api.toggleUserPremium(user.user_id, newPremium, newLimit);
      setUsers((prev) =>
        prev.map((u) =>
          u.user_id === user.user_id ? { ...u, is_premium: newPremium, daily_limit: newLimit } : u
        )
      );
    } catch (err) {
      alert(`Failed to update user: ${err}`);
    } finally {
      setUpdatingUserId(null);
    }
  };

  return (
    <div className="mt-card">
      <div className="card-header">
        <div className="card-title">
          <Users size={17} />
          <span>User Management & Catalog Database</span>
        </div>
        <button className="mt-btn" onClick={fetchUsers} disabled={loading} title="Refresh User List">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Format distribution overview */}
      {dbStats && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '0.85rem',
            marginBottom: '1.25rem',
          }}
        >
          <div style={{ backgroundColor: 'var(--bg-color)', padding: '0.85rem 1rem', borderRadius: 'var(--border-radius)' }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>ALAC LOSSLESS</span>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-color)', marginTop: '0.2rem' }}>
              {dbStats.formats.alac.count.toLocaleString()} tracks
              <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', marginLeft: '0.35rem' }}>
                ({dbStats.formats.alac.size_gb} GB)
              </span>
            </div>
          </div>

          <div style={{ backgroundColor: 'var(--bg-color)', padding: '0.85rem 1rem', borderRadius: 'var(--border-radius)' }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>AAC 256KBPS</span>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-color)', marginTop: '0.2rem' }}>
              {dbStats.formats.aac.count.toLocaleString()} tracks
              <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', marginLeft: '0.35rem' }}>
                ({dbStats.formats.aac.size_gb} GB)
              </span>
            </div>
          </div>

          <div style={{ backgroundColor: 'var(--bg-color)', padding: '0.85rem 1rem', borderRadius: 'var(--border-radius)' }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)', fontWeight: 600 }}>DOLBY ATMOS</span>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-color)', marginTop: '0.2rem' }}>
              {dbStats.formats.atmos.count.toLocaleString()} tracks
              <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)', marginLeft: '0.35rem' }}>
                ({dbStats.formats.atmos.size_gb} GB)
              </span>
            </div>
          </div>
        </div>
      )}

      {/* User Search Bar */}
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={15} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--sub-color)' }} />
          <input
            type="text"
            className="mt-input"
            style={{ paddingLeft: '36px' }}
            placeholder="Search by Username (@handle), Name, or Telegram User ID..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </div>
      </div>

      {/* Users Table */}
      <div className="mt-table-container">
        <table className="mt-table">
          <thead>
            <tr>
              <th>User / Handle</th>
              <th>Telegram ID</th>
              <th>Tier</th>
              <th>Total Downloads</th>
              <th>Today</th>
              <th>Daily Limit</th>
              <th>Last Active</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '2rem', color: 'var(--sub-color)' }}>
                  {loading ? 'Loading user records...' : 'No users found matching query.'}
                </td>
              </tr>
            ) : (
              users.map((user) => {
                const isUpdating = updatingUserId === user.user_id;
                const displayName = user.username
                  ? `@${user.username}`
                  : user.first_name
                  ? user.first_name
                  : `User ${user.user_id}`;

                return (
                  <tr key={user.user_id}>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.1rem' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text-color)' }}>
                          {displayName}
                        </span>
                        {user.first_name && user.username && (
                          <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>
                            {user.first_name}
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--sub-color)', fontFamily: 'var(--font-mono)' }}>
                      {user.user_id}
                    </td>
                    <td>
                      {user.is_premium ? (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.25rem',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            backgroundColor: 'rgba(226, 183, 20, 0.15)',
                            color: 'var(--main-color)',
                            fontSize: '0.72rem',
                            fontWeight: 700,
                          }}
                        >
                          <Crown size={12} /> VIP
                        </span>
                      ) : (
                        <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>STANDARD</span>
                      )}
                    </td>
                    <td style={{ fontWeight: 700 }}>{user.download_count}</td>
                    <td style={{ color: user.downloaded_today > 0 ? 'var(--main-color)' : 'var(--sub-color)' }}>
                      {user.downloaded_today}
                    </td>
                    <td>{user.daily_limit}/day</td>
                    <td style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
                      {user.last_download ? user.last_download.split('T')[0] : 'Never'}
                    </td>
                    <td>
                      <button
                        className={`mt-btn ${user.is_premium ? 'danger' : 'primary'}`}
                        onClick={() => handleTogglePremium(user)}
                        disabled={isUpdating}
                        style={{ padding: '0.25rem 0.6rem', fontSize: '0.72rem' }}
                      >
                        {isUpdating ? 'Saving...' : user.is_premium ? 'Revoke VIP' : 'Grant VIP'}
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1rem' }}>
        <span style={{ fontSize: '0.75rem', color: 'var(--sub-color)' }}>
          Showing {users.length} of {totalUsers} total users
        </span>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="mt-btn"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <button
            className="mt-btn"
            disabled={users.length < 15 || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
};
