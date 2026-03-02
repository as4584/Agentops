'use client';

import { createTheme, MantineColorsTuple } from '@mantine/core';

/**
 * Agentop Mantine Theme
 * Dark-mode only, matches the existing colour palette.
 */

const agentopPurple: MantineColorsTuple = [
  '#f0eeff',
  '#ddd9ff',
  '#b8b0ff',
  '#9186ff',
  '#7b73ff',
  '#6c63ff',
  '#6258ff',
  '#5248e4',
  '#473fcb',
  '#3a34b3',
];

export const theme = createTheme({
  primaryColor: 'agentop',
  colors: {
    agentop: agentopPurple,
  },
  fontFamily: '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif',
  fontFamilyMonospace: 'SF Mono, Fira Code, Cascadia Code, monospace',
  defaultRadius: 'md',
  cursorType: 'pointer',
});
