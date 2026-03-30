# TurnkeySection Component Spec

## 1. TypeScript Interface

```typescript
import { Box, Container, Title, Text } from '@mantine/core';
import { useEffect, useRef, useState } from 'react';

interface TurnkeySectionProps {
  // No external props required - section content is static
}

interface IntersectionState {
  isVisible: boolean;
  hasBeenVisible: boolean;
}
```

## 2. Component Structure

```typescript
const TurnkeySection = () => {
  const sectionRef = useRef<HTMLDivElement>(null);
  const [intersection, setIntersection] = useState<IntersectionState>({
    isVisible: false,
    hasBeenVisible: false
  });

  // Scroll trigger implementation
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !intersection.hasBeenVisible) {
          setIntersection({
            isVisible: true,
            hasBeenVisible: true
          });
        }
      },
      { threshold: 0.3 }
    );

    if (sectionRef.current) {
      observer.observe(sectionRef.current);
    }

    return () => observer.disconnect();
  }, [intersection.hasBeenVisible]);

  return (
    <Box
      ref={sectionRef}
      component="section"
      style={{
        backgroundColor: 'var(--ibds-surface, #F8F9FA)',
        padding: '80px 0',
        opacity: intersection.isVisible ? 1 : 0,
        transform: intersection.isVisible ? 'translateY(0)' : 'translateY(20px)',
        transition: 'opacity 0.8s ease-out, transform 0.8s ease-out'
      }}
    >
      <Container size={800} style={{ textAlign: 'center' }}>
        {/* Gold accent bar */}
        <Box
          style={{
            width: 64,
            height: 3,
            backgroundColor: '#C5A253',
            margin: '0 auto 32px'
          }}
        />
        
        {/* Heading */}
        <Title
          order={2}
          style={{
            fontSize: 32,
            fontWeight: 700,
            color: '#111111',
            fontFamily: 'var(--mantine-font-family-display, sans-serif)'
          }}
        >
          We don't advise and leave.
        </Title>

        {/* Paragraph */}
        <Text
          style={{
            fontSize: 18,
            fontWeight: 400,
            color: '#495057',
            maxWidth: 640,
            margin: '24px auto 0',
            lineHeight: 1.7
          }}
        >
          We design, implement, and operationalize complete business systems. From compliance and infrastructure to operational systems and growth execution — we handle the complexity so you can focus on scaling.
        </Text>
      </Container>
    </Box>
  );
};

export default TurnkeySection;
```

## 3. Data Fetching

**None required** - This is a static content section with no dynamic data.

## 4. Edge Cases

- Must handle SSR/SSG rendering without hydration mismatch
- Must gracefully degrade if IntersectionObserver is not available (no animation)
- Must maintain visibility state even if user scrolls past and back
- Must preserve text alignment on all screen sizes
- Must handle reduced motion preferences (respect prefers-reduced-motion)

## 5. Must NOT Do

- Must NOT fetch any data from APIs
- Must NOT accept children or content props
- Must NOT implement internal navigation or links
- Must NOT include any interactive elements (buttons, forms)
- Must NOT implement any hover effects
- Must NOT make the content editable or dynamic
- Must NOT include any icons or imagery