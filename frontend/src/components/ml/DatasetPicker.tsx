'use client';

import { useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Checkbox,
  Group,
  Paper,
  ScrollArea,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';

export interface DatasetPickerItem {
  name: string;
  kind: 'training' | 'dpo';
  size_bytes: number;
  line_count: number;
  modified_at: string;
}

interface DatasetPickerProps {
  title: string;
  description: string;
  items: DatasetPickerItem[];
  selected: string[];
  onChange: (selected: string[]) => void;
  recommendedNames?: string[];
}

const fmt = {
  size: (bytes: number) =>
    bytes >= 1024 * 1024
      ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
      : bytes >= 1024
        ? `${(bytes / 1024).toFixed(1)} KB`
        : `${bytes} B`,
  num: (value: number) => value.toLocaleString(),
};

export default function DatasetPicker({
  title,
  description,
  items,
  selected,
  onChange,
  recommendedNames = [],
}: DatasetPickerProps) {
  const [query, setQuery] = useState('');

  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const itemMap = useMemo(() => new Map(items.map(item => [item.name, item])), [items]);

  const filteredItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const base = [...items].sort((a, b) => b.modified_at.localeCompare(a.modified_at));
    if (!normalized) return base;
    return base.filter(item => item.name.toLowerCase().includes(normalized));
  }, [items, query]);

  const visibleItems = filteredItems.slice(0, 120);
  const selectedLines = selected.reduce((total, name) => total + (itemMap.get(name)?.line_count ?? 0), 0);

  const toggleItem = (name: string, checked: boolean) => {
    if (checked) {
      onChange(Array.from(new Set([...selected, name])));
      return;
    }
    onChange(selected.filter(value => value !== name));
  };

  const selectAllFiltered = () => {
    onChange(Array.from(new Set([...selected, ...filteredItems.map(item => item.name)])));
  };

  const clearSelection = () => {
    onChange([]);
  };

  const selectRecommended = () => {
    const suggested = recommendedNames.filter(name => itemMap.has(name));
    if (suggested.length > 0) {
      onChange(suggested);
      return;
    }
    onChange(filteredItems.slice(0, 6).map(item => item.name));
  };

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="flex-start">
        <div>
          <Text size="sm" fw={700}>
            {title}
          </Text>
          <Text size="xs" c="dimmed">
            {description}
          </Text>
        </div>
        <Badge variant="light" color="blue">
          {selected.length} selected
        </Badge>
      </Group>

      <Group gap="xs">
        <Button size="compact-xs" variant="light" onClick={selectRecommended}>
          Core
        </Button>
        <Button size="compact-xs" variant="subtle" onClick={selectAllFiltered}>
          Filtered
        </Button>
        <Button size="compact-xs" variant="subtle" color="gray" onClick={clearSelection}>
          Clear
        </Button>
      </Group>

      <Paper withBorder p="xs" radius="md" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <Group justify="space-between" mb={6}>
          <Text size="xs" c="dimmed">
            {fmt.num(selectedLines)} lines across {selected.length} files
          </Text>
          <Text size="xs" c="dimmed">
            {fmt.num(items.length)} available
          </Text>
        </Group>

        <TextInput
          size="xs"
          placeholder="Filter datasets"
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          leftSection={<IconSearch size={14} />}
          mb="xs"
        />

        <ScrollArea h={220} offsetScrollbars>
          <Stack gap={6}>
            {visibleItems.map(item => (
              <Checkbox.Card
                key={item.name}
                checked={selectedSet.has(item.name)}
                onChange={(checked) => toggleItem(item.name, checked)}
                p="xs"
                radius="md"
                style={{
                  background: selectedSet.has(item.name) ? 'rgba(61, 150, 255, 0.10)' : 'rgba(255,255,255,0.02)',
                  borderColor: selectedSet.has(item.name) ? 'rgba(61, 150, 255, 0.28)' : 'rgba(255,255,255,0.08)',
                }}
              >
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <div style={{ minWidth: 0 }}>
                    <Text size="xs" fw={600} truncate="end">
                      {item.name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {fmt.num(item.line_count)} lines • {fmt.size(item.size_bytes)}
                    </Text>
                  </div>
                  <Checkbox.Indicator />
                </Group>
              </Checkbox.Card>
            ))}

            {visibleItems.length === 0 && (
              <Text size="xs" c="dimmed" ta="center" py="md">
                No datasets match this filter.
              </Text>
            )}
          </Stack>
        </ScrollArea>

        {filteredItems.length > visibleItems.length && (
          <Text size="xs" c="dimmed" mt="xs">
            Showing the newest 120 matches. Narrow the filter to target a specific file set.
          </Text>
        )}
      </Paper>
    </Stack>
  );
}
