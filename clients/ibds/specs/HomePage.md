1. TypeScript interface  
```ts
// src/app/page.tsx
import { Metadata } from 'next' // only Next.js native import allowed
// no Mantine or icon imports—server component
```

No props, no state, no client hooks → no interface needed.  
Export: `export default function Home()`

2. Component structure  
```tsx
export default async function Home() {
  return (
    <>
      <NavBar />
      <HeroSection />
      <TurnkeySection />
      <LifecycleSection />
      <CapabilitiesSection />
      <IndustriesSection />
      <ExecutiveCTA />
      <Footer />
    </>
  )
}
```
No wrappers, no `<ScrollArea>`, no Mantine layout components.

3. Data fetching  
None. HomePage is a static server component; it does not call any API routes, does not poll, does not handle loading or error states.

4. Edge cases it must handle  
- None—any data dependencies are delegated to the child sections.  
- Must not break if any child throws; Next.js 14 error boundary at page level will catch.

5. What it must NOT do  
- Must NOT include `'use client'`.  
- Must NOT fetch data, manage state, or perform side effects.  
- Must NOT wrap children in extra containers, providers, or theme wrappers.