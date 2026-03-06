'use client';

import { useMemo, useState } from 'react';
import { Box, Button, Card, Group, NumberInput, Select, Slider, Stack, Switch, Text, Title } from '@mantine/core';

const glassStyle = {
  background: 'rgba(255,255,255,0.05)',
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '16px',
};

export default function PricingPage() {
  const [setupTier, setSetupTier] = useState('foundation');
  const [posts, setPosts] = useState(8);
  const [videos, setVideos] = useState(2);
  const [articles, setArticles] = useState(1);
  const [includeReceptionist, setIncludeReceptionist] = useState(true);
  const [includeChatbot, setIncludeChatbot] = useState(false);
  const [includeCrm, setIncludeCrm] = useState(false);
  const [customDiscount, setCustomDiscount] = useState(0);

  const totals = useMemo(() => {
    const setupBase = setupTier === 'foundation' ? 2000 : setupTier === 'growth' ? 3000 : 4000;
    const monthlyBase = setupTier === 'foundation' ? 1500 : setupTier === 'growth' ? 2500 : 4000;

    const contentAddOn = Math.max(posts - 8, 0) * 35 + Math.max(videos - 2, 0) * 85 + Math.max(articles - 1, 0) * 120;
    const addOnsSetup = (includeChatbot ? 600 : 0) + (includeCrm ? 900 : 0);
    const addOnsMonthly = (includeReceptionist ? 299 : 0);

    const setupSubtotal = setupBase + addOnsSetup;
    const monthlySubtotal = monthlyBase + contentAddOn + addOnsMonthly;
    const discountFactor = Math.max(0, 1 - customDiscount / 100);

    return {
      setupSubtotal,
      monthlySubtotal,
      setupTotal: Math.round(setupSubtotal * discountFactor),
      monthlyTotal: Math.round(monthlySubtotal * discountFactor),
      firstMonthTotal: Math.round((setupSubtotal + monthlySubtotal) * discountFactor),
    };
  }, [setupTier, posts, videos, articles, includeReceptionist, includeChatbot, includeCrm, customDiscount]);

  return (
    <Stack p="xl" gap="lg">
      <Title order={2}>Pricing Calculator</Title>
      <Text c="dimmed">Build business-owner-ready proposals with startup + monthly totals.</Text>

      <Group align="flex-start" grow>
        <Card style={glassStyle}>
          <Stack>
            <Select
              label="Setup Tier"
              value={setupTier}
              onChange={(value) => setSetupTier(value || 'foundation')}
              data={[
                { value: 'foundation', label: 'Foundation ($2,000 setup)' },
                { value: 'growth', label: 'Growth Engine ($3,000 setup)' },
                { value: 'domination', label: 'Authority Builder ($4,000 setup)' },
              ]}
            />

            <Box>
              <Text size="sm" mb={8}>Monthly Posts: {posts}</Text>
              <Slider value={posts} onChange={setPosts} min={8} max={28} step={2} />
            </Box>

            <Box>
              <Text size="sm" mb={8}>Monthly Videos: {videos}</Text>
              <Slider value={videos} onChange={setVideos} min={2} max={12} step={1} />
            </Box>

            <Box>
              <Text size="sm" mb={8}>Monthly Articles: {articles}</Text>
              <Slider value={articles} onChange={setArticles} min={1} max={8} step={1} />
            </Box>

            <Switch label="Include AI Receptionist (+$299/mo)" checked={includeReceptionist} onChange={(e) => setIncludeReceptionist(e.currentTarget.checked)} />
            <Switch label="Include Website Chatbot (+$600 setup)" checked={includeChatbot} onChange={(e) => setIncludeChatbot(e.currentTarget.checked)} />
            <Switch label="Include CRM Lead Tracker (+$900 setup)" checked={includeCrm} onChange={(e) => setIncludeCrm(e.currentTarget.checked)} />

            <NumberInput
              label="Discount %"
              value={customDiscount}
              onChange={(value) => setCustomDiscount(Number(value) || 0)}
              min={0}
              max={35}
              step={1}
            />
          </Stack>
        </Card>

        <Card style={glassStyle}>
          <Stack>
            <Title order={4}>Proposal Totals</Title>
            <Group justify="space-between">
              <Text>Setup Subtotal</Text>
              <Text fw={700}>${totals.setupSubtotal.toLocaleString()}</Text>
            </Group>
            <Group justify="space-between">
              <Text>Monthly Subtotal</Text>
              <Text fw={700}>${totals.monthlySubtotal.toLocaleString()}</Text>
            </Group>
            <Group justify="space-between">
              <Text>Setup Total (after discount)</Text>
              <Text fw={700}>${totals.setupTotal.toLocaleString()}</Text>
            </Group>
            <Group justify="space-between">
              <Text>Monthly Total (after discount)</Text>
              <Text fw={700}>${totals.monthlyTotal.toLocaleString()}</Text>
            </Group>
            <Group justify="space-between">
              <Text>First Month Total</Text>
              <Text fw={700} size="xl">${totals.firstMonthTotal.toLocaleString()}</Text>
            </Group>
            <Button fullWidth>Use This Pricing</Button>
          </Stack>
        </Card>
      </Group>
    </Stack>
  );
}
