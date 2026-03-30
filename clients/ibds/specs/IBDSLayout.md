## IBDSLayout Component Specification

### 1. TypeScript Interface

```typescript
import type { ReactNode } from 'react'
import type { Metadata } from 'next'
import { IBM_Plex_Sans, Inter } from 'next/font/google'

interface IBDSLayoutProps {
  children: ReactNode
}

// No state types - server component only
```

### 2. Component Structure

```typescript
// sections structure
<html lang="en">
  <head>
    {/* Metadata injected via Next.js metadata API */}
  </head>
  <body className={`${plexSans.className} ${inter.className}`}>
    {/* Children rendered directly without additional wrappers */}
    {children}
  </body>
</html>
```

### 3. Data Fetching

- **NOT RESPONSIBLE** for any data fetching, endpoints, polling, or loading states
- This is a server component root layout - no client-side fetching

### 4. Edge Cases It Must Handle

- SSR hydration mismatches due to font loading timing
- Font loading failures gracefully falling back to system fonts
- Metadata injection conflicts with page-level metadata
- CSS import resolution failures in different environments (dev/build)
- TypeScript module declaration issues for CSS imports
- Edge runtime compatibility for global styles
- 404/500 error page styling consistency through CSS cascade
- i18n locale changes if implemented in the future

### 5. What It Must NOT Do

- No client components (use client directive)
- No MantineProvider, ModalsProvider, or any Mantine context providers
- No navigation components or sidebars
- No state management (React hooks, Redux, Zustand, etc.)
- No local storage or cookie access
- No authentication wrapper or session handling
- No theme switching functionality
- No responsive breakpoints overtly defined
- No loading spinners, skeletons, or animation libraries
- No favicon.ico, manifest.json, or PWA configurations
- No analytics or third-party script injections
- No cookie banners or consent management
- No viewport meta tags (Next.js handles this)
- No app directory routing logic
- No _app.tsx or _document.tsx patterns