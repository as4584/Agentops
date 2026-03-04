import { createTheme, MantineColorsTuple } from '@mantine/core';

export const theme = createTheme({
  colors: {
    dark: [
      '#e4e4e7', // 0 - text-primary
      '#8b8d94', // 1 - text-secondary
      '#52545a', // 2 - text-muted
      '#2a2d32', // 3 - border
      '#3a3d42', // 4 - border-focus
      '#1a1d21', // 5 - surface-raised
      '#141619', // 6 - surface
      '#0b0c0e', // 7 - background
      '#6c63ff', // 8 - primary
      '#6c63ff', // 9 - primary hover
    ] as MantineColorsTuple,
    primary: Array(10).fill('#6c63ff') as unknown as MantineColorsTuple,
    green:  Array(10).fill('#22c55e') as unknown as MantineColorsTuple,
    yellow: Array(10).fill('#eab308') as unknown as MantineColorsTuple,
    red:    Array(10).fill('#ef4444') as unknown as MantineColorsTuple,
    blue:   Array(10).fill('#3b82f6') as unknown as MantineColorsTuple,
    orange: Array(10).fill('#f97316') as unknown as MantineColorsTuple,
    cyan:   Array(10).fill('#06b6d4') as unknown as MantineColorsTuple,
  },
  primaryColor: 'primary',
  primaryShade: 8,
  defaultRadius: 4,
  radius: { xs: '4px', sm: '4px', md: '4px', lg: '6px', xl: '6px' },
  spacing: { xs: '8px', sm: '12px', md: '16px', lg: '24px', xl: '32px' },
  fontFamily: 'Inter, sans-serif',
  fontFamilyMonospace: 'JetBrains Mono, monospace',
  headings: { fontFamily: 'Inter, sans-serif' },
  shadows: { xs: 'none', sm: 'none', md: 'none', lg: 'none', xl: 'none' },
  black: '#0b0c0e',
  white: '#e4e4e7',
});
