# BrandIntakePanel Component Specification

## 1. TypeScript Interface

```typescript
// types.ts
interface BrandIntakeData {
  brand_name: string;
  brand_voice: string;
  target_audience: string;
  content_pillars: string[];
  platforms: ('Instagram' | 'TikTok' | 'YouTube' | 'Twitter/X')[];
  posting_frequency: 'daily' | '3x/week' | 'weekly';
}

interface BrandIntakePanelProps {
  className?: string;
}

// state types
type ViewState = 'loading' | 'form' | 'summary' | 'error';

interface ComponentState {
  view: ViewState;
  intakeData: BrandIntakeData | null;
}

// imports
import {
  TextInput,
  Textarea,
  TagsInput,
  Chip,
  Select,
  Button,
  Group,
  Stack,
  Title,
  Paper,
  Loader,
  Alert,
  Box
} from '@mantine/core';
import { IconEdit, IconCheck } from '@tabler/icons-react';
import { useState, useEffect } from 'react';
import { API_BASE } from '@/lib/api';
```

## 2. Component Structure

```typescript
Sections:
- Loading state container
- Error state container
- Form section:
  - ScrollArea container
  - Form with Stack spacing
  - Brand name field (TextInput)
  - Brand voice field (Textarea)
  - Target audience field (TextInput)
  - Content pillars field (TagsInput)
  - Platforms group (Chip.Group)
  - Posting frequency field (Select)
  - Submit button (Loading state during submission)
- Summary section:
  - ScrollArea container
  - Stack with label-value pairs
  - Edit button positioned below summary

Layout:
- Single column layout within Paper component
- Max-width: 600px
- Padding: lg on Paper
- Section spacing: xl between form sections
- Form footer spacing: xl
```

## 3. Data Fetching

```typescript
Endpoints:
- GET /content/intake
- POST /content/intake

Polling:
- Initial fetch on component mount
- No polling interval (single fetch)
- Refetch after successful POST

Loading states:
- Full screen Loader overlay during initial fetch
- Submit button Loading state during POST
- Disabled form fields during submission

Error states:
- Network errors on GET/POST
- Validation errors
- 404 on GET /content/intake = switch to form view
- Server errors = display Alert with retry button
```

## 4. Edge Cases It Must Handle

1. Brand intake exists → show summary
2. No brand intake (404) → show form
3. Empty form submission → prevent submit, highlight required fields
4. Invalid posting frequency selection → prevent with Select validation
5. Duplicate content pillars → TagsInput deduplication
6. No platforms selected → Chip validation
7. API timeout → show error with retry
8. Form submission failure → keep form state, show error
9. Rapid edit/save cycles → prevent concurrent POST requests
10. Network disconnection during form → offline error handling

## 5. What It Must NOT Do

- Not implement any other components
- Not handle authentication/state management beyond its scope
- Not store data in localStorage
- Not implement navigation/logic outside this panel
- Not share form state with other components
- Not implement auto-save functionality
- Not handle file uploads
- Not create/update/delete content campaigns
- Not modify global application state
- Not exceed 600px width constraint