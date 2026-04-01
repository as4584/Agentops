/**
 * Privacy Policy — Agentop Social Media Manager
 * URL: http://localhost:3007/legal/privacy
 *
 * Required by TikTok, Meta (Facebook/Instagram) for developer app registration.
 * Covers: data collection, TikTok API data handling, Meta API data handling,
 * local storage only, no third-party sharing.
 */

export default function PrivacyPolicy() {
  const lastUpdated = 'March 31, 2026';
  const appName = 'Agentop';
  const contactEmail = 'privacy@agentop.local';

  return (
    <div style={styles.page}>
      <div style={styles.container}>
        {/* Header */}
        <div style={styles.header}>
          <a href="http://localhost:3007" style={styles.backLink}>← Back to Dashboard</a>
          <div style={styles.badge}>Legal</div>
        </div>

        <h1 style={styles.h1}>Privacy Policy</h1>
        <p style={styles.meta}>
          Last updated: {lastUpdated} &nbsp;·&nbsp; {appName}
        </p>

        <hr style={styles.hr} />

        <Section title="1. Overview">
          <P>
            {appName} (&ldquo;we&rdquo;, &ldquo;our&rdquo;, or &ldquo;the Service&rdquo;) is a
            local-first, autonomous social media management application. This Privacy Policy
            explains what data we collect, how it is used, where it is stored, and your rights
            regarding that data.
          </P>
          <P>
            {appName} operates entirely on your own infrastructure (local machine or private
            server). <strong style={{ color: '#f1f5f9' }}>We do not operate any cloud backend,
            analytics service, or data collection infrastructure.</strong> All data described in
            this policy is stored locally on your device.
          </P>
        </Section>

        <Section title="2. Data We Collect">
          <h3 style={styles.h3}>2.1 Data You Provide</h3>
          <P>To connect social media accounts, you provide:</P>
          <ul style={styles.ul}>
            <li style={styles.li}>Platform API credentials (access tokens, client keys, page IDs)</li>
            <li style={styles.li}>Configuration preferences (upload schedules, alert thresholds)</li>
          </ul>
          <P>These are stored locally in your <code style={styles.code}>.env</code> file and
          <code style={styles.code}>backend/memory/</code> directory.</P>

          <h3 style={styles.h3}>2.2 Data Retrieved from TikTok</h3>
          <P>
            With your authorization and using OAuth scopes you explicitly grant, {appName}
            retrieves the following TikTok data:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Video metrics</strong>: view count, like count, comment count, share count, duration (via <code style={styles.code}>video.list</code> scope)</li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Publish status</strong>: upload and processing status of videos posted through the Service</li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Open ID</strong>: your TikTok account identifier (used to associate tokens; never displayed publicly)</li>
          </ul>
          <P>
            {appName} does <strong style={{ color: '#f1f5f9' }}>not</strong> access TikTok user
            profile data, follower lists, messages, comments, or any data beyond the
            <code style={styles.code}>video.publish</code> and <code style={styles.code}>video.list</code> scopes.
          </P>

          <h3 style={styles.h3}>2.3 Data Retrieved from Facebook and Instagram</h3>
          <P>
            With your authorization, {appName} retrieves the following Meta platform data:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Page insights</strong>: impressions, engaged users, fan adds, page views (Facebook)</li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Profile insights</strong>: impressions, reach, profile views, accounts engaged (Instagram)</li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Post insights</strong>: likes, comments, shares, saves, video views for content posted through the Service</li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Content publishing quota</strong>: remaining Instagram post quota (read-only)</li>
          </ul>
          <P>
            {appName} does <strong style={{ color: '#f1f5f9' }}>not</strong> access personal
            user profiles, private messages, friends lists, or advertising data.
          </P>

          <h3 style={styles.h3}>2.4 Operational Logs</h3>
          <P>
            {appName} writes structured logs to <code style={styles.code}>backend/logs/system.jsonl</code>
            for debugging and monitoring. Logs contain API call results, error messages, and
            scheduler events. They do not contain user personal data beyond platform-assigned IDs.
          </P>
        </Section>

        <Section title="3. How We Use Your Data">
          <P>Data collected by {appName} is used exclusively to:</P>
          <ul style={styles.ul}>
            <li style={styles.li}>Post content to your connected social media accounts on your behalf</li>
            <li style={styles.li}>Display analytics and performance metrics in the dashboard</li>
            <li style={styles.li}>Generate scheduled performance reports</li>
            <li style={styles.li}>Fire alerts when performance thresholds are crossed</li>
            <li style={styles.li}>Detect and warn about expiring access tokens</li>
          </ul>
          <P>
            We do not use your data for advertising, profiling, machine learning model training,
            or any purpose beyond the stated Service functionality.
          </P>
        </Section>

        <Section title="4. Data Storage and Security">
          <P>
            All data is stored <strong style={{ color: '#f1f5f9' }}>locally on your device</strong>:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}><code style={styles.code}>.env</code> — API credentials and configuration (never committed to version control)</li>
            <li style={styles.li}><code style={styles.code}>backend/memory/social_media/</code> — analytics cache, post history, alert history</li>
            <li style={styles.li}><code style={styles.code}>backend/memory/social_media/tiktok_tokens.json</code> — OAuth token storage</li>
            <li style={styles.li}><code style={styles.code}>backend/logs/system.jsonl</code> — operational logs</li>
          </ul>
          <P>
            No data is transmitted to any {appName} servers because no such servers exist.
            The only outbound network connections made by the Service are to:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}><code style={styles.code}>open.tiktokapis.com</code> — TikTok API</li>
            <li style={styles.li}><code style={styles.code}>graph.facebook.com</code> — Meta Graph API</li>
            <li style={styles.li}><code style={styles.code}>localhost:11434</code> — Local Ollama LLM (no external connection)</li>
          </ul>
          <P>
            You are responsible for securing the device or server where {appName} is deployed,
            including access to <code style={styles.code}>.env</code> files and memory directories
            containing access tokens.
          </P>
        </Section>

        <Section title="5. Data Sharing">
          <P>
            <strong style={{ color: '#f1f5f9' }}>We do not share your data with any third parties.</strong>
          </P>
          <P>
            Data is sent to TikTok and Meta APIs solely to fulfill actions you request
            (posting content, reading analytics). This transmission is governed by those
            platforms&apos; respective privacy policies:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}>
              TikTok:{' '}
              <a href="https://www.tiktok.com/legal/privacy-policy" target="_blank" rel="noreferrer" style={styles.link}>
                tiktok.com/legal/privacy-policy
              </a>
            </li>
            <li style={styles.li}>
              Meta:{' '}
              <a href="https://www.facebook.com/privacy/policy/" target="_blank" rel="noreferrer" style={styles.link}>
                facebook.com/privacy/policy
              </a>
            </li>
          </ul>
        </Section>

        <Section title="6. Data Retention">
          <P>
            Analytics cache, post history, and alert history are stored locally and retained
            indefinitely unless you manually delete the files in{' '}
            <code style={styles.code}>backend/memory/social_media/</code>.
          </P>
          <P>
            Access tokens are stored until you delete them or they expire. Token expiry is
            monitored daily and you are alerted 7 days before expiration.
          </P>
          <P>
            Operational logs rotate as configured. Default retention is unlimited; configure
            log rotation via your operating system&apos;s log management tools.
          </P>
        </Section>

        <Section title="7. TikTok-Specific Data Handling">
          <P>
            {appName} accesses TikTok&apos;s API under the following commitments required by
            TikTok&apos;s Developer Terms of Service:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}>We only request the minimum scopes necessary: <code style={styles.code}>video.publish</code> and <code style={styles.code}>video.list</code></li>
            <li style={styles.li}>TikTok API data is stored locally and not redistributed</li>
            <li style={styles.li}>We comply with TikTok&apos;s data deletion requirements: deleting <code style={styles.code}>backend/memory/social_media/analytics_cache.json</code> and <code style={styles.code}>tiktok_tokens.json</code> removes all TikTok-sourced data</li>
            <li style={styles.li}>AI-generated content is always flagged with <code style={styles.code}>is_aigc: true</code> per TikTok policy</li>
            <li style={styles.li}>We do not use TikTok data to build advertising profiles or train machine learning models</li>
          </ul>
        </Section>

        <Section title="8. Meta-Specific Data Handling">
          <P>
            {appName} accesses Meta&apos;s Graph API under the following commitments required
            by Meta&apos;s Platform Terms:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}>We only request permissions necessary for posting and analytics: <code style={styles.code}>pages_manage_posts</code>, <code style={styles.code}>pages_read_engagement</code>, <code style={styles.code}>instagram_content_publish</code>, <code style={styles.code}>instagram_manage_insights</code></li>
            <li style={styles.li}>Meta Platform Data is not transferred to data brokers or used for ad targeting</li>
            <li style={styles.li}>Users can revoke app permissions at any time via Facebook Settings → Apps and Websites</li>
            <li style={styles.li}>Revoking permissions and deleting local files in <code style={styles.code}>backend/memory/social_media/</code> constitutes full data deletion</li>
          </ul>
        </Section>

        <Section title="9. Your Rights">
          <P>You have the right to:</P>
          <ul style={styles.ul}>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Access</strong>: View all locally stored data in <code style={styles.code}>backend/memory/social_media/</code></li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Delete</strong>: Remove all stored data by deleting the <code style={styles.code}>backend/memory/social_media/</code> directory</li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Revoke access</strong>: Revoke platform permissions at any time through TikTok or Facebook settings</li>
            <li style={styles.li}><strong style={{ color: '#f1f5f9' }}>Portability</strong>: All data is in standard JSON format and fully accessible to you</li>
          </ul>
        </Section>

        <Section title="10. Cookies and Tracking">
          <P>
            {appName} does not use cookies, web beacons, tracking pixels, or any analytics
            technologies. The Service is accessed locally and does not interact with external
            tracking infrastructure.
          </P>
        </Section>

        <Section title="11. Children's Privacy">
          <P>
            The Service is not intended for use by individuals under the age of 13 (or the
            applicable minimum age in your jurisdiction). We do not knowingly collect personal
            data from children.
          </P>
        </Section>

        <Section title="12. Changes to This Policy">
          <P>
            We may update this Privacy Policy from time to time. The &ldquo;Last updated&rdquo;
            date at the top of this page reflects the most recent revision. Continued use of the
            Service after changes constitutes acceptance of the revised policy.
          </P>
        </Section>

        <Section title="13. Contact">
          <P>
            For privacy-related questions or data deletion requests, contact:{' '}
            <a href={`mailto:${contactEmail}`} style={styles.link}>{contactEmail}</a>
          </P>
        </Section>

        <hr style={styles.hr} />
        <div style={styles.footer}>
          <a href="/legal/terms" style={styles.link}>Terms of Service</a>
          <span style={{ color: '#475569' }}> · </span>
          <a href="/social" style={styles.link}>Social Media Dashboard</a>
          <span style={{ color: '#475569' }}> · </span>
          <a href="/" style={styles.link}>Agentop Dashboard</a>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 36 }}>
      <h2 style={styles.h2}>{title}</h2>
      {children}
    </section>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p style={styles.p}>{children}</p>;
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    background: '#0f0f1a',
    minHeight: '100vh',
    color: '#e2e8f0',
    padding: '48px 24px',
  },
  container: {
    maxWidth: 760,
    margin: '0 auto',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 32,
  },
  backLink: {
    color: '#64748b',
    textDecoration: 'none',
    fontSize: 14,
  },
  badge: {
    background: 'rgba(167,139,250,0.12)',
    border: '1px solid rgba(167,139,250,0.3)',
    color: '#a78bfa',
    borderRadius: 9999,
    padding: '3px 12px',
    fontSize: 12,
    fontWeight: 600,
  },
  h1: {
    fontSize: 36,
    fontWeight: 800,
    color: '#f1f5f9',
    marginBottom: 8,
  },
  h2: {
    fontSize: 18,
    fontWeight: 700,
    color: '#c4b5fd',
    marginBottom: 12,
  },
  h3: {
    fontSize: 15,
    fontWeight: 700,
    color: '#e2e8f0',
    marginBottom: 8,
    marginTop: 16,
  },
  meta: {
    color: '#475569',
    fontSize: 14,
    marginBottom: 0,
  },
  hr: {
    border: 'none',
    borderTop: '1px solid #1e1e3a',
    margin: '32px 0',
  },
  p: {
    color: '#94a3b8',
    lineHeight: 1.8,
    fontSize: 15,
    marginBottom: 12,
  },
  ul: {
    paddingLeft: 24,
    marginBottom: 12,
  },
  li: {
    color: '#94a3b8',
    lineHeight: 1.8,
    fontSize: 15,
    marginBottom: 6,
  },
  link: {
    color: '#a78bfa',
    textDecoration: 'none',
  },
  code: {
    background: '#1e1e3a',
    padding: '1px 6px',
    borderRadius: 4,
    fontSize: 13,
    fontFamily: 'monospace',
    color: '#c4b5fd',
  },
  footer: {
    fontSize: 13,
    color: '#475569',
    textAlign: 'center' as const,
    marginTop: 8,
  },
};
