import type { Metadata } from 'next';
import { ColorSchemeScript, MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { theme } from '@/theme';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/code-highlight/styles.css';
import './globals.css';

export const metadata: Metadata = {
  title: 'Agentop — Local AI Control Center',
  description: 'Multi-agent dashboard with architectural drift governance',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-mantine-color-scheme="dark">
      <head>
        <ColorSchemeScript defaultColorScheme="dark" />
      </head>
      <body>
        <MantineProvider theme={theme} defaultColorScheme="dark">
          <Notifications position="top-right" />
          {children}
        </MantineProvider>
      </body>
    </html>
  );
}
