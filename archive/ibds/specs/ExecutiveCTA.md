## ExecutiveCTA Component Specification

### 1. TypeScript Interface
```typescript
// No props required as this is a static content component
interface ExecutiveCTAProps {}

// No state management needed - purely presentational
interface ExecutiveCTAState {}

// Key imports from Mantine v7
import { Box, Container, Center, Title, Text, Button } from '@mantine/core';

// No icons required from @tabler-icons-react
```

### 2. Component Structure
```typescript
// Layout hierarchy:
<Box component="section" style={{ backgroundColor: 'var(--ibds-navy)' }}> // Full width navy background
  <Container maw={700}> // Centered container with max-width
    <Center h="100%"> // Ensures centering
      <Title order={2} c="white" fz={36} fw={700}> // H2 heading
        Ready to Build the Infrastructure Your Business Requires?
      </Title>
      <Text c="rgba(255,255,255,0.7)" fz={16} fw={400} mt={16} lh={1.5}> // Subtext
        Schedule a consultation and get a clear roadmap for your business development in 30 days.
      </Text>
      <Button // Gold CTA button
        component={Link}
        href="/contact"
        color="gold"
        mt={40}
        size="lg"
        radius="xl"
      >
        Schedule Executive Consultation
      </Button>
    </Center>
  </Container>
</Box>
```

### 3. Data Fetching
- No data fetching required
- No endpoints to call
- No polling interval
- No loading states (component renders statically)
- No error states (purely presentational)

### 4. Edge Cases to Handle
- Ensure text remains readable on all screen sizes by wrapping:
  - Title: Default Mantine wrapping behavior
  - Subtext: Default Mantine wrapping behavior
- Handle extremely narrow viewports (320px+):
  - Container padding adjusts via Mantine responsive system
- Ensure color contrast meets WCAG AA standards:
  - White text on navy background: Pass
  - 70% opacity white on navy: Must ensure minimum contrast ratio
- Prevent horizontal overflow on mobile devices

### 5. What It Must NOT Do
- Must NOT implement any form validation
- Must NOT collect any form data or user input
- Must NOT perform any API calls
- Must NOT use any state management (React hooks, Zustand, etc.)
- Must NOT implement any animations or transitions beyond Mantine defaults
- Must NOT display dynamic content based on user data or cookies
- Must NOT implement scroll-triggered effects
- Must NOT interact with any external services (analytics, tracking)
- Must NOT implement any hover states beyond Mantine's default button styling