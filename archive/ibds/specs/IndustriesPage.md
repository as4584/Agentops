1. TypeScript interface  
```
// IndustriesPage.tsx (server component)
import { Container, Box, Title, Text, Grid, Card } from '@mantine/core';

// No runtime props → no props interface.
// No client state → no state types.
// No icons used inside this page → no icon imports.
```

2. Component structure  
```
- <NavBar />  (imported, renders above hero)
- <Box sx={{ bg: 'navy', height: '40vh', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12 }}>
    <Title order={1} c="white" fz={48} fw={700}>Industries We Serve</Title>
    <Text c="white" fz={18} fw={400}>Tailored business development solutions for every sector.</Text>
  </Box>
- <Container size={1200} px={80} py={80}>
    <Grid gutter={24}>
      {staticIndustries.map(({ title, blurb }) => (
        <Grid.Col key={title} span={{ base: 12, sm: 6, md: 4 }}>
          <Card p={24} radius={4} withBorder bd="#DEE2E6" bg="white">
            <Box sx={{ borderLeft: '3px solid #C5A253', pl: 16 }}>
              <Title order={3} fz={18} fw={700}>{title}</Title>
              <Text mt={8} fz={16} lh="24px">{blurb}</Text>
              <Anchor href="/contact" c="#C5A253" mt={12} display="inline-block" fz={16}>Learn More</Anchor>
            </Box>
          </Card>
        </Grid.Col>
      ))}
    </Grid>
  </Container>
- <Footer />  (imported, renders below grid)
```

3. Data fetching  
- None.  
- No endpoints, polling, loading skeletons, or error states inside IndustriesPage.

4. Edge cases it must handle  
- Long words in titles/descriptions: Mantine Card’s default overflow-wrap is sufficient.  
- Missing blurb in static array: impossible — array is hard-coded.  
- SSR/CSS-in-JS hydration mismatch: ensure MantineProvider is in root layout (outside this file).  
- 404/redirect if accessed at wrong segment: handled by Next.js file-system routing, not this page.

5. What it must NOT do  
- Must not fetch data at runtime.  
- Must not contain client-side interactivity (buttons, forms, modals).  
- Must not import or use any client hooks (useState, useEffect, useRouter).  
- Must not inline global styles or inject <style> tags.  
- Must not export metadata from this file (export const metadata handled in parent layout).