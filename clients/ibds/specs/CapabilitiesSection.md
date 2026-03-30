1. TypeScript interface  
```ts
// CapabilitiesSection.tsx
'use client';

import { FC } from 'react';
import { Box, Container, Title, Text, Grid } from '@mantine/core';
import { IconChartBar, IconSettings, IconShield, IconArrowUpRight } from '@tabler/icons-react';

type Capability = {
  title: string;
  icon: React.ElementType;
  description: string;
};

type CapabilitiesSectionProps = {
  /**
   * Optional override list; when omitted, the canonical four
   * capabilities will be rendered.
   */
  capabilities?: Capability[];
  className?: string;
};
```

2. Component structure  
```tsx
const CapabilitiesSection: FC<CapabilitiesSectionProps> = ({ capabilities: _caps, className }) => {
  const data = _caps ?? [
    {
      title: 'Strategic Advisory',
      icon: IconChartBar,
      description:
        'Roadmaps, systems design, and strategic guidance for business decisions.'
    },
    {
      title: 'Operational Execution',
      icon: IconSettings,
      description:
        "We implement and run the systems, so you don't have to manage vendors."
    },
    {
      title: 'Compliance & Infrastructure',
      icon: IconShield,
      description: 'Entity setup, regulatory filings, and legal infrastructure.'
    },
    {
      title: 'Growth Systems',
      icon: IconArrowUpRight,
      description:
        'Market expansion, digital systems, and scalable growth infrastructure.'
    }
  ];

  return (
    <Box component="section" bg="#FFFFFF" py={80} className={className}>
      <Container size={1000}>
        {/* Label */}
        <Text
          tt="uppercase"
          fw={700}
          size="11px"
          c="#C89A3D"
          style={{ letterSpacing: '2px' }}
          ta="center"
          mb={16}
        >
          WHAT WE DO
        </Text>

        {/* H2 */}
        <Title
          ta="center"
          c="#111111"
          fw={700}
          style={{ fontSize: 36 }}
          mb={48}
        >
          Complete Business Development Infrastructure.
        </Title>

        {/* Grid */}
        <Grid gutter={24}>
          {data.map(({ title, icon: Icon, description }) => (
            <Grid.Col span={{ base: 12, sm: 6 }} key={title}>
              <Box
                bg="#F8F9FA"
                style={{
                  border: '1px solid #DEE2E6',
                  borderRadius: 4,
                  padding: 32,
                  transition: 'box-shadow 200ms'
                }}
                sx={{
                  '&:hover': { boxShadow: '0 4px 20px rgba(0,0,0,0.08)' }
                }}
              >
                {/* Icon area */}
                <Box
                  w={40}
                  h={40}
                  bg="#0B1F3B"
                  style={{ borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                >
                  <Icon size={20} stroke={1.5} color="#FFFFFF" />
                </Box>

                {/* Title */}
                <Text fw={700} c="#111111" size="18px" mt={16}>
                  {title}
                </Text>

                {/* Description */}
                <Text size="14px" c="#6C757D" fw={400} lh={1.6} mt={8}>
                  {description}
                </Text>
              </Box>
            </Grid.Col>
          ))}
        </Grid>
      </Container>
    </Box>
  );
};

export default CapabilitiesSection;
```

3. Data-fetching  
This component is strictly presentational; it neither initiates any fetch, polls any endpoint, nor needs loading/error logic. It receives pre-shaped data exclusively via its `capabilities` prop. No `useEffect`, `SWR`, or `React Query` code should be present.

4. Edge cases it must handle  
- Zero-length capabilities prop  
  → render nothing inside Grid (empty section).  
- Missing prop  
  → fall back to the built-in four items.  
- Responsive layout breakpoints per Mantine Grid: mobile (1 col), tablet & desktop (2x2).  
- Graceful SSR/SSG in Next.js 14 App Router environment.

5. What it must NOT do  
- Include any styling or content other than the spec.  
- Export any additional constants, helper functions, or sub-components.  
- Emit or render client-side navigation prompts or links.