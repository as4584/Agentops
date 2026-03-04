'use client';

import { useEffect, useState, type FC } from 'react';
import {
  Badge,
  Button,
  Center,
  Chip,
  Group,
  Loader,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { API_BASE } from '@/lib/api';

/* ── Types ─────────────────────────────────────────────── */

interface BrandIntakeData {
  brand_name: string;
  brand_voice: string;
  target_audience: string;
  content_pillars: string[];
  platform_targets: string[];
  posting_frequency: string;
  brand_timezone: string;
}

const EMPTY_INTAKE: BrandIntakeData = {
  brand_name: '',
  brand_voice: '',
  target_audience: '',
  content_pillars: [],
  platform_targets: [],
  posting_frequency: '3x/week',
  brand_timezone: 'America/New_York',
};

const PLATFORM_OPTIONS = ['instagram', 'tiktok', 'youtube_shorts', 'youtube'];
const PILLAR_OPTIONS = ['Educational', 'Behind-the-scenes', 'Tutorial', 'Thought-leadership', 'Entertainment'];

/* ── Component ─────────────────────────────────────────── */

const BrandIntakePanel: FC = () => {
  const [view, setView] = useState<'edit' | 'summary'>('edit');
  const [data, setData] = useState<BrandIntakeData>(EMPTY_INTAKE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* ── Load existing intake ──────────────────────────── */

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/content/intake`);
        if (res.ok) {
          setData(await res.json());
          setView('summary');
        }
      } catch {
        /* no saved intake is fine */
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  /* ── Submit ────────────────────────────────────────── */

  const handleSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/content/intake`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setView('summary');
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  /* ── Field updater ─────────────────────────────────── */

  const set = <K extends keyof BrandIntakeData>(
    key: K,
    value: BrandIntakeData[K],
  ) => setData(prev => ({ ...prev, [key]: value }));

  /* ── Render ────────────────────────────────────────── */

  if (loading) {
    return (
      <Center h="100%">
        <Loader size="sm" />
      </Center>
    );
  }

  return (
    <Stack gap={8} h="100%">
      <Group justify="space-between">
        <Text fw={700} size="sm" c="dimmed" tt="uppercase">
          Brand Intake
        </Text>
        <SegmentedControl
          size="xs"
          value={view}
          onChange={(v) => setView(v as 'edit' | 'summary')}
          data={[
            { label: 'Edit', value: 'edit' },
            { label: 'Summary', value: 'summary' },
          ]}
        />
      </Group>

      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}

      <ScrollArea style={{ flex: 1 }} offsetScrollbars>
        {view === 'edit' ? (
          <Stack gap={10}>
            <TextInput
              label="Brand name"
              size="xs"
              value={data.brand_name}
              onChange={e => set('brand_name', e.currentTarget.value)}
            />

            <Textarea
              label="Brand voice"
              size="xs"
              minRows={2}
              value={data.brand_voice}
              onChange={e => set('brand_voice', e.currentTarget.value)}
            />

            <TextInput
              label="Target audience"
              size="xs"
              value={data.target_audience}
              onChange={e => set('target_audience', e.currentTarget.value)}
            />

            <Text size="xs" fw={500}>
              Content pillars
            </Text>
            <Chip.Group
              multiple
              value={data.content_pillars}
              onChange={(v) => set('content_pillars', v)}
            >
              <Group gap={6}>
                {PILLAR_OPTIONS.map(p => (
                  <Chip key={p} size="xs" value={p}>
                    {p}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>

            <Text size="xs" fw={500}>
              Platforms
            </Text>
            <Chip.Group
              multiple
              value={data.platform_targets}
              onChange={(v) => set('platform_targets', v)}
            >
              <Group gap={6}>
                {PLATFORM_OPTIONS.map(p => (
                  <Chip key={p} size="xs" value={p}>
                    {p}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>

            <Select
              label="Posting frequency"
              size="xs"
              value={data.posting_frequency}
              onChange={(v) => set('posting_frequency', v ?? '3x/week')}
              data={[
                { value: 'daily', label: 'Daily' },
                { value: '3x/week', label: '3 × Week' },
                { value: 'weekly', label: 'Weekly' },
              ]}
            />

            <Button
              size="xs"
              onClick={handleSubmit}
              loading={saving}
              disabled={!data.brand_name.trim()}
            >
              Save
            </Button>
          </Stack>
        ) : (
          <Stack gap={10}>
            <TextInput label="Brand name" size="xs" value={data.brand_name} readOnly />
            <Textarea label="Brand voice" size="xs" value={data.brand_voice} readOnly minRows={2} />
            <TextInput label="Target audience" size="xs" value={data.target_audience} readOnly />

            <Text size="xs" fw={500}>
              Content pillars
            </Text>
            <Group gap={6}>
              {data.content_pillars.map(p => (
                <Badge key={p} size="sm" variant="light">
                  {p}
                </Badge>
              ))}
            </Group>

            <Text size="xs" fw={500}>
              Platforms
            </Text>
            <Group gap={6}>
              {data.platform_targets.map(p => (
                <Badge key={p} size="sm" variant="light">
                  {p}
                </Badge>
              ))}
            </Group>

            <Text size="xs" c="dimmed">
              Frequency: {data.posting_frequency}
            </Text>

            <Button size="xs" variant="light" onClick={() => setView('edit')}>
              Edit
            </Button>
          </Stack>
        )}
      </ScrollArea>
    </Stack>
  );
};

export default BrandIntakePanel;
