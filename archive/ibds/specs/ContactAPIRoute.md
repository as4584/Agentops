ContactAPIRoute – TypeScript Next.js App Router API route spec  
File: app/api/contact/route.ts

1. TypeScript interface & key imports  
```typescript
import { NextRequest, NextResponse } from 'next/server';

interface ContactBody {
  name: string;
  email: string;
  company?: string;
  message?: string;
}
```

2. Component structure  
- Single exported async function named `POST`  
- Accepts: `request: NextRequest`  
- Returns: `Promise<NextResponse<{ ok: true } | { error: string }>>`

3. Data fetching  
- None (no external calls or internal state)  
- Polling interval: N/A  
- Loading/error states returned via NextResponse JSON

4. Edge cases handled  
- Non-JSON body → catch & return 400 { error: 'Invalid JSON' }  
- Missing name or email → 400 { error: 'Missing required fields' }  
- Email without “@” → 400 { error: 'Invalid email' }  
- Extra unknown fields → silently ignored  
- Console log failure (rare) → still return 200 { ok: true }

5. Must NOT  
- Call any external service, database, or webhook  
- Send email, push to queue, write to disk, or use fetch/axios  
- Accept methods other than POST  
- Set cookies, headers, or cache directives  
- Import Mantine or @tabler/icons-react