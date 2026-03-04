1. TypeScript interface  
```ts
import { FC } from 'react';
import { Container, Flex, Title, Text, Button, Box } from '@mantine/core';
import { IconArrowRight } from '@tabler/icons-react';

// WhoWeServePage is a server component – no props, no state, no client hooks
type WhoWeServePageProps = Record<string, never>;
```

2. Component structure  
- Server component file: `app/who-we-serve/page.tsx`  
- Imports: `NavBar` (server) and `Footer` (server) from `@/components/layout/*`  
- Hero: full-bleed navy `<Box bg="navy" h="40vh">` → centered `<Title order={1} c="white" fz={48} fw={700}>Who We Serve</Title>` + sub-headline `<Text c="white" fz={16}>`  
- Main content: single `<Container size="xl" px={0}>` wrapper  
  - 4 programmatic sections mapped from static array; array index drives alternating background colors (`white` | `#F8F9FA`)  
  - Each section `<Flex direction={{ base: 'column', md: 'row' }} gap={80} p={80}>`  
    - Left: `<Box flex={1}>` → `<Title order={2}>` (28/700 navy), `<Text fz={16}>` (#495057), `<Button component="a" href="/contact" rightSection={<IconArrowRight size={16}>}` variant="subtle" color="yellow">`  
    - Right: empty visual placeholder `<Box flex={1} h={240} bg="gray.1" style={{ borderRadius: 8 }}>` (no image src)  
- Scroll: native browser scroll; no Mantine ScrollArea  
- Export: `export default function WhoWeServePage(): JSX.Element`

3. Data fetching  
- None. Static server component; no fetch calls, no polling, no loading or error overlays

4. Edge cases handled  
- Responsive stack below `md` breakpoint (Mantine default breakpoints)  
- Server-only execution – no `'use client'` directive  
- No images → no broken-src flicker  
- No props → no prop-drill or default-prop logic  
- No external data → no runtime hydration mismatch

5. Must NOT do  
- No client-side state, hooks, or event handlers  
- No data fetching, API calls, or caching  
- No authentication checks  
- No dynamic metadata (assume static title is set in `layout.tsx`)  
- No animations, no third-party libraries beyond Mantine & Tabler icon  
- No redirection logic