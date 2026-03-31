import { createTheme, MantineColorsTuple } from '@mantine/core';

/**
 * Agentop — Premium dark theme
 *
 * Rich charcoal surfaces with blue accent. High contrast, glass feel,
 * visible card boundaries, and an overall polished modern aesthetic.
 */

const agentop: MantineColorsTuple = [
  '#e8f4ff', // 0 - lightest tint
  '#d0e8ff', // 1
  '#a3d0ff', // 2
  '#6db3ff', // 3
  '#3d96ff', // 4
  '#1a82ff', // 5 - primary
  '#0071f0', // 6 - pressed
  '#005fd4', // 7
  '#004db8', // 8
  '#003d99', // 9 - darkest
];

export const theme = createTheme({
  colors: {
    dark: [
      '#f0f0f5', // 0 - text-primary (crisp white)
      '#a1a1aa', // 1 - text-secondary
      '#71717a', // 2 - text-muted
      '#3f3f46', // 3 - border-subtle
      '#52525b', // 4 - border
      '#27272a', // 5 - surface-raised
      '#1e1e22', // 6 - card surface
      '#141417', // 7 - app background
      '#0c0c0f', // 8 - deepest
      '#09090b', // 9
    ] as MantineColorsTuple,
    agentop,
    primary: agentop,
    green: [
      '#e6f9ed', '#c3f0d5', '#8fe3b0', '#5ad68b', '#30c96e',
      '#22b85c', '#1da750', '#178f42', '#127836', '#0d612b',
    ] as MantineColorsTuple,
    yellow: [
      '#fef9e7', '#fdf0c4', '#fbe38d', '#f9d556', '#f7c82a',
      '#eab308', '#d4a007', '#b38706', '#926e05', '#715504',
    ] as MantineColorsTuple,
    red: [
      '#fef2f2', '#fde3e3', '#fbc5c5', '#f79a9a', '#f26b6b',
      '#ef4444', '#dc2626', '#b91c1c', '#991b1b', '#7f1d1d',
    ] as MantineColorsTuple,
    blue: [
      '#eff6ff', '#dbeafe', '#bfdbfe', '#93c5fd', '#60a5fa',
      '#3b82f6', '#2563eb', '#1d4ed8', '#1e40af', '#1e3a8a',
    ] as MantineColorsTuple,
    orange: [
      '#fff7ed', '#ffedd5', '#fed7aa', '#fdba74', '#fb923c',
      '#f97316', '#ea580c', '#c2410c', '#9a3412', '#7c2d12',
    ] as MantineColorsTuple,
    cyan: [
      '#ecfeff', '#cffafe', '#a5f3fc', '#67e8f9', '#22d3ee',
      '#06b6d4', '#0891b2', '#0e7490', '#155e75', '#164e63',
    ] as MantineColorsTuple,
  },
  primaryColor: 'agentop',
  primaryShade: 5,
  defaultRadius: 'md',
  radius: { xs: '6px', sm: '8px', md: '12px', lg: '16px', xl: '20px' },
  spacing: { xs: '8px', sm: '12px', md: '16px', lg: '24px', xl: '32px' },
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Inter, sans-serif',
  fontFamilyMonospace:
    '"SF Mono", "JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
  headings: {
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Inter, sans-serif',
    fontWeight: '600',
  },
  shadows: {
    xs: '0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)',
    sm: '0 2px 6px rgba(0,0,0,0.35), 0 1px 3px rgba(0,0,0,0.25)',
    md: '0 4px 14px rgba(0,0,0,0.4), 0 2px 6px rgba(0,0,0,0.3)',
    lg: '0 8px 28px rgba(0,0,0,0.45), 0 4px 10px rgba(0,0,0,0.35)',
    xl: '0 16px 48px rgba(0,0,0,0.5), 0 8px 20px rgba(0,0,0,0.4)',
  },
  black: '#141417',
  white: '#f0f0f5',
});
