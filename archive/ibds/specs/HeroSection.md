HeroSection – TypeScript Spec
────────────────────────────

1. TypeScript interface
```ts
import { FC } from 'react';
import { Box, Flex, Title, Text, Button } from '@mantine/core';
import { IconWave } from '@tabler/icons-react';

type HeroProps = {};                // Component receives no props

type ScrollState = {                // Internal state
  userHasScrolled: boolean;
  heroInView:      boolean;        // IntersectionObserver for fade-in
};
```

2. Component structure
- Root: `Box` (`w="100vw" h="100vh"`).  
  Flex column, center align, gradient background.  
  Relative position so all absolute children (map & nodes) sit inside.

- Content wrapper: `Flex direction="column" align="center"`  
  - `Title order={1} className="fade-in"` – styled with Mantine fontsize clamp system (`fontSize={{base:36,sm:48,md:64}}`).  
    Two explicit `<br />` after “Solution”.

- Underline `Box` (hr replacement): 2px [#C5A253] bar 80 px wide, `mt={16}`.

- Subheadline `Text` – `size="xl"` (18px), weight 400, `opacity={0.7}`, `maxWidth={600}` centered, `mt={24}`, animation delay 100 ms.

- CTA Button – `mt={40}`, single element, text “Schedule Executive Consultation”, `color="#0B1F3B"`, `bg="#C5A253"`.  
  Hover style overrides via `sx={{ '&:hover': { backgroundColor:'#B89345' } }}`. No secondary CTA/button group allowed.

- Map SVG container – absolutely positioned bottom, centered, `w="70%"`, `pointerEvents="none"`.  
  Inline SVG path for simplified US outline, fill="#ffffff", opacity=0.06.

- Node container – absolutely positioned above SVG at same Z index.  
  5 `Box` circles (`w={8} h={8} bg="#C5A253" borderRadius="50%"`) at visual coordinates matching NY, LA, Chicago, Houston, Miami.  
  Render map and nodes only after first scroll ≥ 10 px (via `useEffect` scroll listener + `setState`).  
  Each circle carries `className="gold-pulse"`.

- Fade-in observer hooks  
  `useEffect` + `useRef` on root Box. When 20 % visible, flip `heroInView` to trigger CSS keyframes on `.fade-in`.

3. Data fetching  
None.  
The section is purely presentational and must not call any endpoint or poll.

4. Edge cases
- SSR: use `useEffect` for IntersectionObserver & scroll listener to prevent hydration mismatches.  
- Resize: SVG maintains aspect ratio, no text reflow breaks through Mantine clamp font.  
- Oversized viewports (>1600 px): content stays capped at 800 px; SVG keeps 70 % width.  
- Motion reduced (user preference): CSS overrides inside globals.css switch pulse to static and fade-in to immediate.

5. What it must NOT do
- Mount no secondary buttons, navigation bars, carousel, or any form inputs.  
- Never use Mantine’s `AppShell` or `Header` inside HeroSection.  
- Avoid importing any Next.js router navigation until clicked.  
- Must not mutate theme Mantine object; all colors inline opaque.

Component export default.