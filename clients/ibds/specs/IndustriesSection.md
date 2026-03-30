## IndustriesSection Component Specification

### 1. TypeScript Interface

```typescript
import { Box, Container, Grid, Text, Anchor } from '@mantine/core';
import { IconArrowRight } from '@tabler/icons-react';
import { FC } from 'react';

// Data structure for industry items
interface IndustryItem {
  name: string;
  tag: string;
}

// Component props (empty as this is a static section)
interface IndustriesSectionProps {}

// No internal state needed - static display
type IndustriesSectionState = 'idle';
```

### 2. Component Structure

```typescript
const IndustriesSection: FC<IndustriesSectionProps> = () => {
  // Layout structure:
  // - Root Box with section background (#F8F9FA)
  //   - Container (80px py)
  //     - Centered flex column
  //       - Label Text (INDUSTRIES - gold, 11px/700)
  //       - H2 Text (36px/700, centered)
  //       - Grid container (max-width 1000px, centered)
  //         - Responsive Grid (3 cols → 2 cols → 1 col)
  //           - Industry tiles (6 items)
  //             - Box for each tile
  //               - Left accent border
  //               - Text content
  //       - Centered link button
};
```

### 3. Data & Implementation

```typescript
// Hardcoded static data
const industries: IndustryItem[] = [
  { name: 'Technology', tag: 'AI, SaaS, Web3' },
  { name: 'Healthcare', tag: 'Digital Health, Biotech' },
  { name: 'Retail & E-Commerce', tag: 'Online Stores, Marketplaces' },
  { name: 'Professional Services', tag: 'Consulting, Legal, Accounting' },
  { name: 'Real Estate', tag: 'Residential, Commercial' },
  { name: 'Hospitality & Food Service', tag: 'Hotels, Restaurants' },
];

// No data fetching required
// No polling interval
// No loading states (static content)
// No error states (static content)
```

### 4. Edge Cases to Handle

- Empty `industries` array → Should show empty grid gracefully
- Long industry names → Text should wrap to prevent overflow
- Long tag text → Text should wrap to prevent overflow
- Screen sizes below 350px → Ensure single column layout maintains legibility
- Browser zoom above 200% → Text scaling should maintain readability
- Touch devices → Ensure hover states have appropriate touch fallback behavior

### 5. What It Must NOT Do

- No API calls or external data fetching
- No dynamic content updates
- No local storage/session storage usage
- No global state management (Redux, Context, etc.)
- No animations beyond CSS transitions
- No routing logic (link is visual only)
- No form handling
- No user input collection
- No modal/drawer triggers
- No dynamic imports or code splitting
- No i18n/l10n implementation