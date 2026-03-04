1. TypeScript interface
```ts
// Footer.tsx
import { Box, Flex, Text, Container, Stack } from '@mantine/core';

type FooterProps = {
  className?: string;          // optional wrapper override
  testId?: string;             // e2e hook
};
```

2. Component structure
```tsx
/*
  <footer>                                   // role="contentinfo"
    <Container size={1200} p={0}>             // centers content
      <Box
        bg="var(--ibds-navy)"                 // background token
        c="white"                             // Mantine color prop
        pt={48}
        pb={48}
        style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }}
      >
        <Flex
          direction={{ base: 'column', sm: 'row' }}
          justify="space-between"
          align={{ base: 'flex-start', sm: 'center' }}
          gap="xl"
        >
          <Stack gap="xs">
            <Text c="gold" fw={700} fz={16}>
              Innovation Business Development Solutions
            </Text>
            <Text fz={14}>
              The One-Stop Solution for Business Development.
            </Text>
            <Text fz={12} c="dimmed">
              © 2025 Innovation BDS. All rights reserved.
            </Text>
          </Stack>

          <Stack gap={8} align="flex-start">
            <Text component="a" href="/industries" fz={14}>
              Industries
            </Text>
            <Text component="a" href="/who-we-serve" fz={14}>
              Who We Serve
            </Text>
            <Text component="a" href="/contact" fz={14}>
              Contact
            </Text>
          </Stack>
        </Flex>
      </Box>
    </Container>
  </footer>
*/
```

3. Data fetching
   - None. Static content, no API calls, no polling.

4. Edge cases
   - Accepts and forwards className & testId for consumer overrides/testing.
   - Responsive: stacks columns on < sm, side-by-side ≥ sm.
   - Links use native <a> so they remain server-side friendly with next/link if parent wraps them.

5. Must NOT
   - Render social-media icons.
   - Render newsletter sign-up.
   - Fetch or display dynamic data.
   - Accept children or any prop beyond className/testId.
   - Import anything from @tabler/icons-react or additional Mantine components.