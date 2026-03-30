## MantineThemeConfig Spec

### 1. TypeScript Interface

```typescript
// No props, state, or Tabler Icons imports needed - this is a static theme object
import { createTheme, MantineColorsTuple } from '@mantine/core';

type ThemeColors = {
  background: string;
  surface: string;
  'surface-raised': string;
  border: string;
  'border-focus': string;
  primary: string;
  'accent-green': string;
  'accent-yellow': string;
  'accent-red': string;
  'accent-blue': string;
  'accent-orange': string;
  'accent-cyan': string;
  'text-primary': string;
  'text-secondary': string;
  'text-muted': string;
};
```

### 2. Component Structure

```typescript
const theme = createTheme({
  colors: {
    dark: [
      '#e4e4e7', // 0 - text-primary
      '#8b8d94', // 1 - text-secondary
      '#52545a', // 2 - text-muted
      '#0b0c0e', // 3 - background
      '#141619', // 4 - surface
      '#1a1d21', // 5 - surface-raised
      '#2a2d32', // 6 - border
      '#3a3d42', // 7 - border-focus
      '#6c63ff', // 8 - primary
      '#6c63ff', // 9 - primary (duplicate for consistency)
    ],
    primary: [
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
      '#6c63ff',
    ],
    green: Array(10).fill('#22c55e') as MantineColorsTuple,
    yellow: Array(10).fill('#eab308') as MantineColorsTuple,
    red: Array(10).fill('#ef4444') as MantineColorsTuple,
    blue: Array(10).fill('#3b82f6') as MantineColorsTuple,
    orange: Array(10).fill('#f97316') as MantineColorsTuple,
    cyan: Array(10).fill('#06b6d4') as MantineColorsTuple,
  },
  primaryColor: 'primary',
  primaryShade: 8,
  defaultRadius: 6,
  radius: {
    xs: 4,
    sm: 4,
    md: 4,
    lg: 6,
    xl: 6,
  },
  spacing: {
    xs: 8,
    sm: 12,
    md: 16,
    lg: 24,
    xl: 32,
  },
  fontFamily: 'Inter, sans-serif',
  fontFamilyMonospace: 'JetBrains Mono, monospace',
  headings: { fontFamily: 'Inter, sans-serif' },
  shadows: {
    xs: 'none',
    sm: 'none',
    md: 'none',
    lg: 'none',
    xl: 'none',
  },
  defaultGradient: { from: 'primary', to: 'primary' },
  colorScheme: 'dark',
  black: '#0b0c0e',
  white: '#e4e4e7',
});
```

### 3. Data Fetching
N/A - Static theme object with no dynamic data

### 4. Edge Cases
- Ensure color values exactly match specified hex codes
- All spacing values must be multiples of 4px
- Font families must exactly match specified names with fallbacks
- Must preserve dark mode without user override
- Must not have shadows despite Mantine defaults
- Must ensure primary color appears in both colors.dark and colors.primary array positions
- Must handle Mantine's requirement that color arrays contain 10 values

### 5. What it MUST NOT do
- Must not contain any other exported members
- Must not use CSS variables or dynamic styling
- Must not contain any runtime logic
- Must not include any React hooks
- Must not have any dependencies on runtime state
- Must not include any responsive breakpoints
- Must not include any color modes other than dark
- Must not export any types or utilities beyond the theme object