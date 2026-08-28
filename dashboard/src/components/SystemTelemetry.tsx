import React from 'react';
import { SystemStats } from '../types';
import { Cpu, HardDrive, Server, Activity } from 'lucide-react';

interface SystemTelemetryProps {
  system: SystemStats | null;
}

export const SystemTelemetry: React.FC<SystemTelemetryProps> = ({ system }) => {
  const cpuPercent = system?.cpu_percent ?? 0;
  const memory = system?.memory ?? { total_gb: 0, used_gb: 0, percent: 0 };
  const disk = system?.disk ?? { total_gb: 0, used_gb: 0, free_gb: 0, percent: 0 };
  const osName = system?.os ?? 'Linux/Windows Host';
  const pyVer = system?.python_version ?? '3.14';

  return (
    <div className="mt-card">
      <div className="card-header">
        <div className="card-title">
          <Server size={17} />
          <span>Host & System Telemetry</span>
        </div>
        <span style={{ fontSize: '0.72rem', color: 'var(--sub-color)' }}>
          {osName} · Python {pyVer}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem' }}>
        {/* 1. CPU */}
        <div style={{ backgroundColor: 'var(--bg-color)', padding: '1rem', borderRadius: 'var(--border-radius)', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.78rem', color: 'var(--sub-color)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <Cpu size={14} style={{ color: 'var(--main-color)' }} />
              CPU UTILIZATION
            </span>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-color)' }}>
              {cpuPercent}%
            </span>
          </div>
          <div className="progress-container">
            <div
              className="progress-fill"
              style={{
                width: `${Math.min(100, Math.max(5, cpuPercent))}%`,
                backgroundColor: cpuPercent > 85 ? 'var(--error-color)' : 'var(--main-color)',
              }}
            />
          </div>
        </div>

        {/* 2. RAM */}
        <div style={{ backgroundColor: 'var(--bg-color)', padding: '1rem', borderRadius: 'var(--border-radius)', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.78rem', color: 'var(--sub-color)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <Activity size={14} style={{ color: 'var(--main-color)' }} />
              RAM MEMORY
            </span>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-color)' }}>
              {memory.used_gb} / {memory.total_gb} GB ({memory.percent}%)
            </span>
          </div>
          <div className="progress-container">
            <div
              className="progress-fill"
              style={{
                width: `${Math.min(100, memory.percent)}%`,
                backgroundColor: memory.percent > 85 ? 'var(--error-color)' : 'var(--main-color)',
              }}
            />
          </div>
        </div>

        {/* 3. Disk */}
        <div style={{ backgroundColor: 'var(--bg-color)', padding: '1rem', borderRadius: 'var(--border-radius)', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.78rem', color: 'var(--sub-color)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <HardDrive size={14} style={{ color: 'var(--main-color)' }} />
              STORAGE DISK
            </span>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-color)' }}>
              {disk.used_gb} / {disk.total_gb} GB ({disk.percent}%)
            </span>
          </div>
          <div className="progress-container">
            <div
              className="progress-fill"
              style={{
                width: `${Math.min(100, disk.percent)}%`,
                backgroundColor: disk.percent > 90 ? 'var(--error-color)' : 'var(--main-color)',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
};
