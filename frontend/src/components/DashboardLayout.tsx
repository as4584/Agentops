import type { FC } from 'react';
import { Card } from '@mantine/core';
import { ActivePanel, PlanPanel, CostPanel, BuildPanel, MemoryPanel, ContentPanel, BrandIntakePanel } from '@/components/panels';

export interface DashboardLayoutProps {
  className?: string;
}

const DashboardLayout: FC<DashboardLayoutProps> = ({ className }) => (
  <div
      className={className}
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(12, 1fr)',
        gridTemplateRows: 'repeat(3, calc(33.33vh - 8px))',
        gap: 8,
        padding: 8,
        background: '#0b0c0e',
        minWidth: 1024,
        height: '100vh',
        overflow: 'hidden',
      }}
    >
      <Card style={{ gridColumn: '1 / 6', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 12, overflow: 'hidden' }}>
        <ActivePanel />
      </Card>
      <Card style={{ gridColumn: '6 / 10', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 12, overflow: 'hidden' }}>
        <PlanPanel />
      </Card>
      <Card style={{ gridColumn: '10 / 13', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 12, overflow: 'hidden' }}>
        <CostPanel />
      </Card>
      <Card style={{ gridColumn: '1 / 7', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 12, overflow: 'hidden' }}>
        <BuildPanel />
      </Card>
      <Card style={{ gridColumn: '7 / 13', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 12, overflow: 'hidden' }}>
        <MemoryPanel />
      </Card>
      <Card style={{ gridColumn: '1 / 9', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 12, overflow: 'hidden' }}>
        <ContentPanel />
      </Card>
      <Card style={{ gridColumn: '9 / 13', border: '1px solid #2a2d32', borderRadius: 6, background: '#141619', padding: 12, overflow: 'hidden' }}>
        <BrandIntakePanel />
      </Card>
    </div>
);

export default DashboardLayout;