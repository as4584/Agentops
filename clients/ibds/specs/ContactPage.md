## TypeScript Interface

```typescript
'use client';

import { useState } from 'react';
import { Container, Grid, Text, TextInput, Textarea, Button, Title, Stack } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconCheck, IconX } from '@tabler/icons-react';
import NavBar from '@/components/NavBar';
import Footer from '@/components/Footer';

interface FormValues {
  name: string;
  email: string;
  company: string;
  message: string;
}

type SubmitStatus = 'idle' | 'loading' | 'success' | 'error';

interface ContactFormState {
  status: SubmitStatus;
  message: string;
}
```

## Component Structure

```typescript
const ContactPage = () => {
  return (
    <>
      <NavBar />
      
      {/* Hero Section */}
      <div style={{ 
        backgroundColor: '#1A365D', 
        height: '30vh', 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center' 
      }}>
        <Title order={1} style={{ 
          color: 'white', 
          fontSize: '40px', 
          fontWeight: 700 
        }}>
          Schedule Your Consultation
        </Title>
      </div>

      <Container fluid>
        <Grid gutter={0} style={{ minHeight: '70vh' }}>
          {/* Left Column */}
          <Grid.Col span={{ base: 12, md: 6 }} style={{ 
            backgroundColor: '#1A365D', 
            padding: '48px'
          }}>
            <div style={{ 
              height: '100%', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center' 
            }}>
              <Text size="xl" style={{ color: 'white' }}>
                Schedule via Calendly
                {/* Replace with Calendly embed script */}
              </Text>
            </div>
          </Grid.Col>

          {/* Right Column */}
          <Grid.Col span={{ base: 12, md: 6 }} style={{ 
            backgroundColor: 'white', 
            padding: '48px' 
          }}>
            <Stack gap="xl">
              <Title order={2} style={{ 
                fontSize: '24px', 
                fontWeight: 700, 
                color: '#1A365D' 
              }}>
                Or Send Us a Message
              </Title>

              {/* Form goes here */}
            </Stack>
          </Grid.Col>
        </Grid>
      </Container>
      
      <Footer />
    </>
  );
};
```

## Data Fetching

```typescript
// Endpoint: POST /api/contact
// No polling intervals
// Loading state handled via submitStatus and form submission
// Error state handled via submitStatus.message
```

Implementation pattern:
- Single POST request on form submission
- Request body: `{ name: string, email: string, company: string, message: string }`
- Response handling: status codes 200 = success, all others = error
- Success message: "Thank you — we'll be in touch within 24 hours."
- Error message: From response or fallback

## Edge Cases

1. **Network failure** - Handle fetch rejection with user-friendly error
2. **Slow connection** - Disable submit button during loading state
3. **Validation failures** - Prevent submission if required fields empty
4. **Multiple rapid submissions** - Prevent duplicate submissions while loading
5. **Server errors** - Display specific error message from response if available
6. **Empty form submission** - Use form validation to prevent
7. **Invalid email format** - Validate email format client-side before send
8. **Very long messages** - Textarea maxLength handling
9. **Focus management** - Focus first error field on validation fail

## Must NOT Do

1. **No routing logic** - Do not implement any navigation redirects
2. **No authentication handling** - Do not check user authentication state
3. **No data persistence** - Do not cache or store form data locally
4. **No tracking/analytics** - Do not add any event tracking
5. **No SEO tags** - Do not add meta tags or structured data
6. **No PWA features** - Do not implement service worker or offline handling
7. **No scroll restoration** - Do not manage scroll position
8. **No i18n/l10n** - Do not implement internationalization
9. **No debug logging** - Do not log form data or network requests to console
10. **No components beyond Navbar/Footer** - Do not create or import any other components