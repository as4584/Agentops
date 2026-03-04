```ts
// 1. TypeScript interface (props, state types, key imports from Mantine v7 and @tabler/icons-react)
import type { FC } from 'react';
import { MantineProvider, Card } from '@mantine/core';
import { ActivePanel, PlanPanel, CostPanel, BuildPanel, MemoryPanel } from '@/components/panels';
import { theme } from '@/lib/theme';

export interface DashboardLayoutProps {
  className?: string;
}

// 2. Component structure (sections, layout, scroll areas)
const DashboardLayout: FC<DashboardLayoutProps> = ({ className }) => (
  <MantineProvider theme={theme}>
    <div
      className={className}
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(12, 1fr)',
        gridTemplateRows: 'repeat(2, calc(50vh - 8px))',
        gap: 8,
        padding: 8,
        background: '#0b0c0e',
        minWidth: 1024,
        height: '100vh',
        overflow: 'hidden',
      }}
    >
      <Card style={{ gridColumn: '1 / 6', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 0 }}>
        <ActivePanel />
      </Card>
      <Card style={{ gridColumn: '6 / 10', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 0 }}>
        <PlanPanel />
      </Card>
      <Card style={{ gridColumn: '10 / 13', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 0 }}>
        <CostPanel />
      </Card>
      <Card style={{ gridColumn: '1 / 7', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 0 }}>
        <BuildPanel />
      </Card>
      <Card style={{ gridColumn: '7 / 13', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 0 }}>
        <MemoryPanel />
      </Card>
    </div>
  </MantineProvider>
);

export default DashboardLayout;

// 3. Data fetching (which endpoints, polling interval, loading/error states)
// NONE – DashboardLayout is purely presentational; each panel self-fetches.

// 4. Edge cases it must handle
// - Viewport < 1024 px: panels must stack vertically (handled by external responsive layer, not this component).
// - Scroll overflow: each Card must clip internal scroll; DashboardLayout itself never scrolls.

// 5. What it must NOT do
// - MUST NOT fetch data.
// - MUST NOT manage global state.
// - MUST NOT include header, sidebar, or navigation.
// - MUST NOT export anything other than the default component.
```