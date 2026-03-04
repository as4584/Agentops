1. TypeScript interface / key imports
```ts
// NavBar.tsx
'use client';

import { useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { Box, Burger, Collapse, Group, Text, UnstyledButton, rem } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { IconMenu2, IconX } from '@tabler/icons-react';

type NavLink = { label: string; href: string };

// No props exposed to parent — self-contained.
```

2. Component structure
- Outer: `Box` with `top-0 sticky z-50` + navy background + `max-width: var(--ibds-max-width)` centered via Mantine `mx="auto"` and `px={24}`.
- Inner 64px high flex container (`h={64}`) with `justify="space-between"` align center.
- Left: conditional `Image` (falls back to gold text) wrapped in `Link` (`/`).
- Right desktop (`≥768px`): horizontal `Group` of `UnstyledButton` Link items.
- Right mobile (`<768px`): `Burger` toggling a full-width `Collapse` under the bar; inside Collapse a vertical `Group` of identical links.
- No scroll areas; all nav items client-side.

3. Data fetching
None. No external APIs, no polling, no loading/error states.

4. Edge cases to handle
- Logo file missing or 404: gracefully render gold “IBDS” text.
- Very long viewport width: respect `var(--ibds-max-width)` centering; no horizontal scroll.
- Burger toggle race conditions (rapid clicks): local `useState<boolean>` handles it.
- Server/client mismatch on media query: use `useMediaQuery` with default fallback to mobile (true) to avoid hydration error.

5. Must NOT
- Include authentication buttons or user state.
- Fetch or post any data.
- Emit global banners, footers, or any other component.
- Depend on context, cookies, headers, or cookies-based redirects.