/**
 * Terms of Service — Agentop Social Media Manager
 * URL: http://localhost:3007/legal/terms
 *
 * Required by TikTok, Meta (Facebook/Instagram) for developer app registration.
 */

export default function TermsOfService() {
  const lastUpdated = 'March 31, 2026';
  const appName = 'Agentop';
  const contactEmail = 'legal@agentop.local';

  return (
    <div style={styles.page}>
      <div style={styles.container}>
        {/* Header */}
        <div style={styles.header}>
          <a href="http://localhost:3007" style={styles.backLink}>← Back to Dashboard</a>
          <div style={styles.badge}>Legal</div>
        </div>

        <h1 style={styles.h1}>Terms of Service</h1>
        <p style={styles.meta}>
          Last updated: {lastUpdated} &nbsp;·&nbsp; {appName}
        </p>

        <hr style={styles.hr} />

        <Section title="1. Acceptance of Terms">
          <P>
            By accessing or using {appName} (the &ldquo;Service&rdquo;), you agree to be bound by
            these Terms of Service (&ldquo;Terms&rdquo;). If you do not agree to these Terms, do
            not use the Service.
          </P>
          <P>
            {appName} is a local-first, autonomous multi-agent social media management system
            that connects to third-party platforms including TikTok, Facebook, and Instagram on
            your behalf using credentials and permissions you explicitly provide.
          </P>
        </Section>

        <Section title="2. Description of Service">
          <P>
            {appName} provides the following functionality:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}>Posting content to connected social media accounts (TikTok, Facebook, Instagram)</li>
            <li style={styles.li}>Reading analytics and performance metrics from connected accounts</li>
            <li style={styles.li}>Scheduling and queuing social media posts</li>
            <li style={styles.li}>Monitoring engagement metrics and generating performance reports</li>
            <li style={styles.li}>Alerting on significant changes in account performance</li>
          </ul>
          <P>
            All actions taken by {appName} are initiated by you or by automated schedules you
            configure. The Service acts solely as an authorized agent on your behalf.
          </P>
        </Section>

        <Section title="3. Third-Party Platform Terms">
          <P>
            By connecting a social media account to {appName}, you represent and warrant that:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}>
              You own or have the right to manage the connected account
            </li>
            <li style={styles.li}>
              You will comply with TikTok&apos;s{' '}
              <a href="https://www.tiktok.com/legal/terms-of-service" target="_blank" rel="noreferrer" style={styles.link}>
                Terms of Service
              </a>{' '}
              and{' '}
              <a href="https://www.tiktok.com/legal/developer-terms-of-service" target="_blank" rel="noreferrer" style={styles.link}>
                Developer Terms
              </a>
            </li>
            <li style={styles.li}>
              You will comply with Meta&apos;s{' '}
              <a href="https://www.facebook.com/terms.php" target="_blank" rel="noreferrer" style={styles.link}>
                Terms of Service
              </a>{' '}
              and{' '}
              <a href="https://developers.facebook.com/terms/" target="_blank" rel="noreferrer" style={styles.link}>
                Platform Terms
              </a>
            </li>
            <li style={styles.li}>
              Content posted through {appName} complies with all applicable platform community
              guidelines, including TikTok&apos;s requirement to set <code style={styles.code}>is_aigc: true</code> for
              AI-generated content
            </li>
          </ul>
        </Section>

        <Section title="4. Permitted Use">
          <P>You agree to use the Service only for lawful purposes. You may not:</P>
          <ul style={styles.ul}>
            <li style={styles.li}>Post content that violates the terms or community guidelines of any connected platform</li>
            <li style={styles.li}>Use the Service to spam, harass, or engage in inauthentic behavior</li>
            <li style={styles.li}>Attempt to circumvent platform rate limits or API restrictions</li>
            <li style={styles.li}>Use the Service to collect personal data from third-party platforms beyond what is necessary for the stated functionality</li>
            <li style={styles.li}>Share your access credentials with unauthorized parties</li>
          </ul>
        </Section>

        <Section title="5. Data and Credentials">
          <P>
            {appName} stores your social media platform credentials (access tokens, page IDs,
            etc.) locally on your device or server in environment configuration files. These
            credentials are never transmitted to any third party other than the respective
            platform APIs (TikTok, Facebook, Instagram).
          </P>
          <P>
            Analytics data fetched from connected platforms is stored locally in{' '}
            <code style={styles.code}>backend/memory/social_media/</code> and is not shared with
            any third party.
          </P>
          <P>
            You are solely responsible for securing your environment, access tokens, and any
            data stored by the Service.
          </P>
        </Section>

        <Section title="6. Content Responsibility">
          <P>
            You are solely responsible for all content posted to social media platforms through
            {appName}. {appName} does not review, endorse, or take responsibility for
            user-submitted content. You must ensure that:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}>Content does not infringe any intellectual property rights</li>
            <li style={styles.li}>AI-generated content is properly disclosed per platform requirements</li>
            <li style={styles.li}>Paid partnerships and sponsored content are disclosed per applicable regulations</li>
            <li style={styles.li}>Content complies with all applicable laws in your jurisdiction</li>
          </ul>
        </Section>

        <Section title="7. API Usage and Rate Limits">
          <P>
            {appName} uses third-party platform APIs subject to their respective rate limits and
            usage policies. The Service enforces the following limits to ensure compliance:
          </P>
          <ul style={styles.ul}>
            <li style={styles.li}>TikTok: maximum 6 API requests per minute per access token</li>
            <li style={styles.li}>Instagram: maximum 100 posts per 24-hour rolling window</li>
            <li style={styles.li}>Facebook: exponential backoff on rate limit errors (codes 4, 17, 341)</li>
          </ul>
          <P>
            Exceeding platform limits may result in temporary or permanent suspension of API
            access. {appName} is not liable for account actions taken by third-party platforms.
          </P>
        </Section>

        <Section title="8. Disclaimers">
          <P>
            THE SERVICE IS PROVIDED &ldquo;AS IS&rdquo; WITHOUT WARRANTIES OF ANY KIND, EXPRESS
            OR IMPLIED. {appName.toUpperCase()} DOES NOT WARRANT THAT THE SERVICE WILL BE
            UNINTERRUPTED, ERROR-FREE, OR THAT ANY CONTENT POSTED WILL REMAIN AVAILABLE ON
            THIRD-PARTY PLATFORMS.
          </P>
          <P>
            {appName} is not affiliated with, endorsed by, or sponsored by TikTok, Meta,
            Facebook, or Instagram.
          </P>
        </Section>

        <Section title="9. Limitation of Liability">
          <P>
            TO THE MAXIMUM EXTENT PERMITTED BY LAW, {appName.toUpperCase()} SHALL NOT BE LIABLE
            FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES ARISING FROM YOUR
            USE OF THE SERVICE, INCLUDING BUT NOT LIMITED TO LOSS OF DATA, ACCOUNT SUSPENSION
            BY THIRD-PARTY PLATFORMS, OR DAMAGE TO REPUTATION.
          </P>
        </Section>

        <Section title="10. Changes to Terms">
          <P>
            We reserve the right to modify these Terms at any time. Continued use of the Service
            after changes constitutes acceptance of the revised Terms.
          </P>
        </Section>

        <Section title="11. Contact">
          <P>
            For questions about these Terms, contact:{' '}
            <a href={`mailto:${contactEmail}`} style={styles.link}>{contactEmail}</a>
          </P>
        </Section>

        <hr style={styles.hr} />
        <div style={styles.footer}>
          <a href="/legal/privacy" style={styles.link}>Privacy Policy</a>
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
