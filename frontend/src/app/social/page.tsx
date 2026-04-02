'use client';

/**
 * Social Media Manager Dashboard — /social
 *
 * This page serves as the "Website URL" for TikTok sandbox app registration.
 * TikTok app settings:
 *   Website URL:  http://localhost:3007/social
 *   Redirect URI: http://localhost:8000/auth/tiktok/callback
 *
 * Shows:
 * - Credential readiness for all platforms
 * - Live analytics cache (auto-refreshes every 30s)
 * - Post history
 * - Alert history
 * - One-click TikTok OAuth link
 */

import { useEffect, useState } from 'react';

const API = 'http://localhost:8000';

interface PlatformStatus {
  client_key_set?: boolean;
  access_token_set?: boolean;
  open_id_set?: boolean;
  app_id_set?: boolean;
  page_token_set?: boolean;
  page_id_set?: boolean;
  business_id_set?: boolean;
}

interface SocialStatus {
  tiktok: PlatformStatus;
  facebook: PlatformStatus;
  instagram: PlatformStatus;
  analytics_cache_exists: boolean;
  post_count: number;
}

interface AnalyticsCache {
  tiktok?: { fetched_at: number; videos: unknown[] };
  facebook?: { fetched_at: number; insights: unknown[] };
  instagram?: { fetched_at: number; insights: unknown[] };
}

interface PostRecord {
  platform: string;
  type: string;
  post_id: string | null;
  label: string;
  posted_at: number;
}

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 10px',
        borderRadius: 9999,
        fontSize: 12,
        fontWeight: 600,
        background: ok ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
        color: ok ? '#22c55e' : '#ef4444',
        border: `1px solid ${ok ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
      }}
    >
      <span>{ok ? '●' : '○'}</span>
      {label}
    </span>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        background: '#1a1a2e',
        border: '1px solid #2d2d4e',
        borderRadius: 12,
        padding: '20px 24px',
        marginBottom: 20,
      }}
    >
      <h2
        style={{
          fontSize: 14,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: '#64748b',
          marginBottom: 16,
        }}
      >
        {title}
      </h2>
      {children}
    </div>
  );
}

function ts(unix: number) {
  return new Date(unix * 1000).toLocaleString();
}

export default function SocialPage() {
  const [status, setStatus] = useState<SocialStatus | null>(null);
  const [cache, setCache] = useState<AnalyticsCache | null>(null);
  const [history, setHistory] = useState<PostRecord[]>([]);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function fetchAll() {
    try {
      const [statusRes, cacheRes, historyRes] = await Promise.all([
        fetch(`${API}/social/status`),
        fetch(`${API}/social/analytics/cache`),
        fetch(`${API}/social/history`),
      ]);
      if (!statusRes.ok) throw new Error(`Status ${statusRes.status}`);
      setStatus(await statusRes.json());
      setCache(await cacheRes.json());
      setHistory(await historyRes.json());
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reach backend');
    }
  }

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 30_000);
    return () => clearInterval(id);
  }, []);

  const tiktokReady =
    status?.tiktok.client_key_set && status?.tiktok.access_token_set;
  const fbReady = status?.facebook.app_id_set && status?.facebook.page_token_set;
  const igReady = status?.instagram.business_id_set && status?.instagram.page_token_set;

  return (
    <div
      style={{
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        background: '#0f0f1a',
        minHeight: '100vh',
        color: '#e2e8f0',
        padding: '32px 24px',
        maxWidth: 900,
        margin: '0 auto',
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 800, color: '#f1f5f9' }}>
              Social Media Manager
            </h1>
            <p style={{ color: '#64748b', fontSize: 14, marginTop: 4 }}>
              Agentop · 24/7 autonomous posting &amp; analytics
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {lastRefresh && (
              <span style={{ fontSize: 12, color: '#475569', alignSelf: 'center' }}>
                Updated {lastRefresh.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={fetchAll}
              style={{
                background: '#2d2d4e',
                border: '1px solid #3d3d6e',
                color: '#a78bfa',
                borderRadius: 8,
                padding: '8px 16px',
                fontSize: 13,
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              Refresh
            </button>
          </div>
        </div>

        {error && (
          <div
            style={{
              marginTop: 16,
              padding: '12px 16px',
              background: 'rgba(239,68,68,0.1)',
              border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: 8,
              color: '#ef4444',
              fontSize: 13,
            }}
          >
            ⚠ Backend unreachable: {error} — is{' '}
            <code style={{ fontSize: 12 }}>python -m backend.port_guard serve</code>{' '}
            running?
          </div>
        )}
      </div>

      {/* Platform credentials */}
      <Card title="Platform Credentials">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
          {/* TikTok */}
          <div
            style={{
              background: '#0f0f1a',
              border: '1px solid #2d2d4e',
              borderRadius: 10,
              padding: '16px 20px',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 12,
              }}
            >
              <span style={{ fontWeight: 700, fontSize: 15 }}>TikTok</span>
              <Badge ok={!!tiktokReady} label={tiktokReady ? 'Ready' : 'Not configured'} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Badge ok={!!status?.tiktok.client_key_set} label="Client Key" />
              <Badge ok={!!status?.tiktok.access_token_set} label="Access Token" />
              <Badge ok={!!status?.tiktok.open_id_set} label="Open ID" />
            </div>
            {!tiktokReady && (
              <a
                href="http://localhost:8000/auth/tiktok/login"
                style={{
                  display: 'block',
                  marginTop: 14,
                  padding: '8px 0',
                  background: 'rgba(167,139,250,0.15)',
                  border: '1px solid rgba(167,139,250,0.3)',
                  borderRadius: 8,
                  color: '#a78bfa',
                  textAlign: 'center',
                  fontSize: 13,
                  fontWeight: 600,
                  textDecoration: 'none',
                }}
              >
                → Authorize TikTok
              </a>
            )}
          </div>

          {/* Facebook */}
          <div
            style={{
              background: '#0f0f1a',
              border: '1px solid #2d2d4e',
              borderRadius: 10,
              padding: '16px 20px',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 12,
              }}
            >
              <span style={{ fontWeight: 700, fontSize: 15 }}>Facebook</span>
              <Badge ok={!!fbReady} label={fbReady ? 'Ready' : 'Not configured'} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Badge ok={!!status?.facebook.app_id_set} label="App ID" />
              <Badge ok={!!status?.facebook.page_token_set} label="Page Token" />
              <Badge ok={!!status?.facebook.page_id_set} label="Page ID" />
            </div>
            {!fbReady && (
              <a
                href="https://developers.facebook.com/apps/"
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'block',
                  marginTop: 14,
                  padding: '8px 0',
                  background: 'rgba(59,130,246,0.1)',
                  border: '1px solid rgba(59,130,246,0.3)',
                  borderRadius: 8,
                  color: '#3b82f6',
                  textAlign: 'center',
                  fontSize: 13,
                  fontWeight: 600,
                  textDecoration: 'none',
                }}
              >
                → Meta Developer Portal ↗
              </a>
            )}
          </div>

          {/* Instagram */}
          <div
            style={{
              background: '#0f0f1a',
              border: '1px solid #2d2d4e',
              borderRadius: 10,
              padding: '16px 20px',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 12,
              }}
            >
              <span style={{ fontWeight: 700, fontSize: 15 }}>Instagram</span>
              <Badge ok={!!igReady} label={igReady ? 'Ready' : 'Not configured'} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Badge ok={!!status?.instagram.business_id_set} label="Business ID" />
              <Badge ok={!!status?.instagram.page_token_set} label="Page Token" />
            </div>
            <p style={{ fontSize: 12, color: '#475569', marginTop: 12, lineHeight: 1.5 }}>
              Uses same token as Facebook. Link IG account to a Facebook Page in Meta Business Suite.
            </p>
          </div>
        </div>
      </Card>

      {/* Analytics cache */}
      <Card title="Analytics Cache">
        {!cache || Object.keys(cache).length === 0 ? (
          <p style={{ color: '#475569', fontSize: 14 }}>
            No analytics cached yet. Polling starts automatically once tokens are configured.
          </p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
            {cache.tiktok && (
              <div style={{ background: '#0f0f1a', border: '1px solid #2d2d4e', borderRadius: 8, padding: '12px 16px' }}>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>TikTok</div>
                <div style={{ fontSize: 13, color: '#64748b' }}>
                  {(cache.tiktok.videos as unknown[]).length} videos tracked
                </div>
                <div style={{ fontSize: 12, color: '#475569', marginTop: 4 }}>
                  Last: {ts(cache.tiktok.fetched_at)}
                </div>
              </div>
            )}
            {cache.facebook && (
              <div style={{ background: '#0f0f1a', border: '1px solid #2d2d4e', borderRadius: 8, padding: '12px 16px' }}>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>Facebook</div>
                <div style={{ fontSize: 13, color: '#64748b' }}>
                  {(cache.facebook.insights as unknown[]).length} metrics
                </div>
                <div style={{ fontSize: 12, color: '#475569', marginTop: 4 }}>
                  Last: {ts(cache.facebook.fetched_at)}
                </div>
              </div>
            )}
            {cache.instagram && (
              <div style={{ background: '#0f0f1a', border: '1px solid #2d2d4e', borderRadius: 8, padding: '12px 16px' }}>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>Instagram</div>
                <div style={{ fontSize: 13, color: '#64748b' }}>
                  {(cache.instagram.insights as unknown[]).length} metrics
                </div>
                <div style={{ fontSize: 12, color: '#475569', marginTop: 4 }}>
                  Last: {ts(cache.instagram.fetched_at)}
                </div>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Post history */}
      <Card title={`Post History (${history.length} total)`}>
        {history.length === 0 ? (
          <p style={{ color: '#475569', fontSize: 14 }}>No posts yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2d2d4e' }}>
                  {['Platform', 'Type', 'Label', 'Post ID', 'Time'].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: 'left',
                        padding: '6px 12px',
                        color: '#64748b',
                        fontWeight: 600,
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...history].reverse().slice(0, 20).map((p, i) => (
                  <tr
                    key={i}
                    style={{ borderBottom: '1px solid #1e1e3a' }}
                  >
                    <td style={{ padding: '8px 12px', textTransform: 'capitalize' }}>{p.platform}</td>
                    <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{p.type}</td>
                    <td
                      style={{
                        padding: '8px 12px',
                        color: '#94a3b8',
                        maxWidth: 200,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {p.label}
                    </td>
                    <td style={{ padding: '8px 12px', color: '#475569', fontFamily: 'monospace', fontSize: 11 }}>
                      {p.post_id ?? '—'}
                    </td>
                    <td style={{ padding: '8px 12px', color: '#475569', whiteSpace: 'nowrap' }}>
                      {ts(p.posted_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Setup guide */}
      <Card title="TikTok Sandbox Setup">
        <div style={{ fontSize: 13, lineHeight: 1.8, color: '#94a3b8' }}>
          <p style={{ marginBottom: 12 }}>
            Register these two URLs in your TikTok app at{' '}
            <a href="https://developers.tiktok.com/apps/" target="_blank" rel="noreferrer" style={{ color: '#a78bfa' }}>
              developers.tiktok.com ↗
            </a>
            :
          </p>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              {[
                ['App Field', 'Value', 'Purpose'],
                ['Website URL', 'http://localhost:3007/social', "This page — proves you have a working app"],
                ['Redirect URI', 'http://localhost:8000/auth/tiktok/callback', 'OAuth callback — receives auth code'],
              ].map(([label, value, purpose], i) => (
                <tr key={i} style={{ borderBottom: '1px solid #1e1e3a' }}>
                  <td
                    style={{
                      padding: '8px 12px',
                      color: i === 0 ? '#64748b' : '#e2e8f0',
                      fontWeight: i === 0 ? 600 : 400,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {label}
                  </td>
                  <td
                    style={{
                      padding: '8px 12px',
                      fontFamily: 'monospace',
                      fontSize: 12,
                      color: i === 0 ? '#64748b' : '#a78bfa',
                    }}
                  >
                    {value}
                  </td>
                  <td style={{ padding: '8px 12px', color: '#64748b', fontSize: 12 }}>{purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 16, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <a
              href="http://localhost:8000/auth/tiktok/login"
              style={{
                padding: '8px 18px',
                background: 'rgba(167,139,250,0.15)',
                border: '1px solid rgba(167,139,250,0.4)',
                borderRadius: 8,
                color: '#a78bfa',
                fontWeight: 700,
                fontSize: 13,
                textDecoration: 'none',
              }}
            >
              → Start TikTok OAuth
            </a>
            <a
              href="http://localhost:8000/auth/tiktok/status"
              target="_blank"
              rel="noreferrer"
              style={{
                padding: '8px 18px',
                background: '#1a1a2e',
                border: '1px solid #2d2d4e',
                borderRadius: 8,
                color: '#64748b',
                fontWeight: 600,
                fontSize: 13,
                textDecoration: 'none',
              }}
            >
              Token Status ↗
            </a>
            <a
              href="http://localhost:8000/docs#/social_media"
              target="_blank"
              rel="noreferrer"
              style={{
                padding: '8px 18px',
                background: '#1a1a2e',
                border: '1px solid #2d2d4e',
                borderRadius: 8,
                color: '#64748b',
                fontWeight: 600,
                fontSize: 13,
                textDecoration: 'none',
              }}
            >
              API Docs ↗
            </a>
          </div>
        </div>
      </Card>
    </div>
  );
}
