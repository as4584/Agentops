'use client';

/**
 * ModelSwitcher - Full-featured model picker with search, provider grouping,
 * and full name display. Styled like an MCP tool picker.
 * Fetches /models/registry, then persists either a team preference or a direct agent override.
 */

import { useEffect, useMemo, useState } from 'react';
import {
  Badge, Box, Combobox, Group, Loader, ScrollArea,
  Text, ThemeIcon, useCombobox,
} from '@mantine/core';
import { IconCheck, IconChevronDown, IconSearch } from '@tabler/icons-react';
import { API_BASE } from '@/lib/api';

export interface RegistryModel {
  model_id: string;
  display_name: string;
  provider: string;
  context_window: number;
  input_cost_per_m: number;
  output_cost_per_m: number;
  supports_tools: boolean;
  available_locally: boolean;
  role?: string | null;
  alias_of?: string | null;
  runtime_model_id?: string | null;
}

interface ModelSwitcherProps {
  agentId?: string;
  teamId?: string;
  value: string;
  onChange?: (modelId: string) => void;
}

const PROVIDER_COLOR: Record<string, string> = {
  ollama: 'green',
  openrouter: 'blue',
  openai: 'teal',
  anthropic: 'orange',
  copilot: 'violet',
};

const PROVIDER_LABEL: Record<string, string> = {
  ollama: 'Local (Ollama)',
  openrouter: 'Cloud (OpenRouter)',
  openai: 'Cloud (OpenAI)',
  anthropic: 'Cloud (Anthropic)',
  copilot: 'GitHub Copilot',
};

const PROVIDER_ORDER = ['ollama', 'copilot', 'openai', 'anthropic', 'openrouter'];

function costLabel(m: RegistryModel): string {
  if (m.input_cost_per_m === 0) return 'free';
  return `$${m.input_cost_per_m.toFixed(2)}/M`;
}

function ctxLabel(ctx: number): string {
  if (ctx >= 1_000_000) return `${(ctx / 1_000_000).toFixed(0)}M ctx`;
  if (ctx >= 1_000) return `${(ctx / 1_000).toFixed(0)}K ctx`;
  return `${ctx} ctx`;
}

let modelsCache: RegistryModel[] | null = null;
let modelsFetch: Promise<RegistryModel[]> | null = null;

async function getModels(): Promise<RegistryModel[]> {
  if (modelsCache) return modelsCache;
  if (modelsFetch) return modelsFetch;
  modelsFetch = fetch(`${API_BASE}/models/registry`)
    .then(r => r.json())
    .then(d => {
      const nextModels = Array.isArray(d.models) ? (d.models as RegistryModel[]) : [];
      modelsCache = nextModels;
      return nextModels;
    })
    .catch(() => {
      modelsFetch = null;
      return [];
    });
  return modelsFetch;
}

export default function ModelSwitcher({ agentId, teamId, value, onChange }: ModelSwitcherProps) {
  const [models, setModels] = useState<RegistryModel[]>([]);
  const [selected, setSelected] = useState(value);
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'error'>('saved');
  const [search, setSearch] = useState('');
  const combobox = useCombobox({
    onDropdownClose: () => {
      combobox.resetSelectedOption();
      setSearch('');
    },
    onDropdownOpen: () => combobox.focusSearchInput(),
  });

  useEffect(() => {
    getModels().then(setModels);
  }, []);

  useEffect(() => {
    setSelected(value);
    setSaveState('saved');
  }, [value]);

  const current = models.find(m => m.model_id === selected);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return q
      ? models.filter(m =>
          m.display_name.toLowerCase().includes(q)
          || m.model_id.toLowerCase().includes(q)
          || m.provider.toLowerCase().includes(q)
          || (m.runtime_model_id ?? '').toLowerCase().includes(q),
        )
      : models;
  }, [models, search]);

  const grouped = useMemo(() => {
    const map = new Map<string, RegistryModel[]>();
    for (const model of filtered) {
      if (!map.has(model.provider)) map.set(model.provider, []);
      map.get(model.provider)?.push(model);
    }
    return Array.from(map.entries()).sort(([a], [b]) => {
      const ai = PROVIDER_ORDER.indexOf(a);
      const bi = PROVIDER_ORDER.indexOf(b);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
  }, [filtered]);

  const handleSelect = async (modelId: string) => {
    combobox.closeDropdown();
    if ((!teamId && !agentId) || modelId === selected) return;

    const prev = selected;
    setSelected(modelId);
    setSaveState('saving');

    try {
      const targetPath = teamId
        ? `/model-preferences/teams/${encodeURIComponent(teamId)}`
        : `/agents/${encodeURIComponent(agentId!)}/model`;
      const response = await fetch(`${API_BASE}${targetPath}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: modelId }),
      });
      if (!response.ok) throw new Error(`PATCH failed: ${response.status}`);
      onChange?.(modelId);
      setSaveState('saved');
    } catch {
      setSelected(prev);
      setSaveState('error');
    }
  };

  const sections = grouped.map(([provider, items]) => (
    <Combobox.Group
      key={provider}
      label={(
        <Group gap={6} px={4} py={2} wrap="nowrap">
          <Badge
            size="xs"
            color={PROVIDER_COLOR[provider] ?? 'gray'}
            variant="filled"
            radius="sm"
            style={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: 9, flexShrink: 0 }}
          >
            {provider}
          </Badge>
          <Text size="xs" c="dimmed" fw={600} style={{ whiteSpace: 'nowrap' }}>
            {PROVIDER_LABEL[provider] ?? provider}
          </Text>
          <Text size="xs" c="dimmed" ml="auto" style={{ whiteSpace: 'nowrap' }}>
            ({items.length})
          </Text>
        </Group>
      )}
    >
      {items.map(model => {
        const isSelected = model.model_id === selected;
        const color = PROVIDER_COLOR[provider] ?? 'gray';
        return (
          <Combobox.Option
            value={model.model_id}
            key={model.model_id}
            style={{
              borderRadius: 6,
              margin: '1px 4px',
              padding: '7px 10px',
              background: isSelected
                ? `color-mix(in srgb, var(--mantine-color-${color}-9) 40%, var(--mantine-color-dark-6))`
                : undefined,
              borderLeft: isSelected ? `2px solid var(--mantine-color-${color}-5)` : '2px solid transparent',
            }}
          >
            <Group gap={8} wrap="nowrap" mb={2}>
              {isSelected ? (
                <ThemeIcon size={16} radius="xl" color={color} variant="filled" style={{ flexShrink: 0 }}>
                  <IconCheck size={10} />
                </ThemeIcon>
              ) : (
                <Box w={16} style={{ flexShrink: 0 }} />
              )}
              <Text
                size="sm"
                fw={isSelected ? 700 : 500}
                style={{ lineHeight: 1.3, whiteSpace: 'nowrap' }}
              >
                {model.display_name}
              </Text>
            </Group>
            <Group gap={12} wrap="nowrap" ml={24} style={{ overflow: 'visible' }}>
              <Text
                size="xs"
                c="dimmed"
                ff="monospace"
                style={{ fontSize: 10, whiteSpace: 'nowrap', minWidth: 0 }}
              >
                {model.model_id}
              </Text>
              <Group gap={8} wrap="nowrap" style={{ flexShrink: 0, marginLeft: 'auto' }}>
                <Text size="xs" c="dimmed" ff="monospace" style={{ fontSize: 10 }}>
                  {ctxLabel(model.context_window)}
                </Text>
                <Text
                  size="xs"
                  ff="monospace"
                  fw={600}
                  c={model.input_cost_per_m === 0 ? 'teal' : 'yellow'}
                  style={{ fontSize: 10 }}
                >
                  {costLabel(model)}
                </Text>
                {model.supports_tools && (
                  <Badge size="xs" color="blue" variant="light" radius="sm" style={{ fontSize: 9 }}>
                    tools
                  </Badge>
                )}
                {model.role && (
                  <Badge size="xs" color="grape" variant="light" radius="sm" style={{ fontSize: 9 }}>
                    {model.role}
                  </Badge>
                )}
                {model.runtime_model_id && model.runtime_model_id !== model.model_id && (
                  <Badge size="xs" color="gray" variant="outline" radius="sm" style={{ fontSize: 9 }}>
                    {model.runtime_model_id}
                  </Badge>
                )}
              </Group>
            </Group>
          </Combobox.Option>
        );
      })}
    </Combobox.Group>
  ));

  return (
    <Combobox store={combobox} onOptionSubmit={handleSelect} withinPortal>
      <Combobox.Target withAriaAttributes={false}>
        <Box
          component="button"
          type="button"
          onClick={() => combobox.toggleDropdown()}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: 'var(--mantine-color-dark-6)',
            border: '1px solid var(--mantine-color-dark-4)',
            borderRadius: 6,
            padding: '4px 8px 4px 10px',
            cursor: 'pointer',
            minWidth: 180,
            maxWidth: 300,
            height: 30,
            transition: 'border-color 0.15s',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.borderColor = 'var(--mantine-color-dark-3)';
          }}
          onMouseLeave={e => {
            e.currentTarget.style.borderColor = 'var(--mantine-color-dark-4)';
          }}
        >
          {current ? (
            <>
              <Badge
                size="xs"
                color={PROVIDER_COLOR[current.provider] ?? 'gray'}
                variant="filled"
                radius="sm"
                style={{ flexShrink: 0, textTransform: 'uppercase', fontSize: 9 }}
              >
                {current.provider}
              </Badge>
              <Text
                size="xs"
                fw={500}
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  textAlign: 'left',
                }}
              >
                {current.display_name}
              </Text>
              <Badge
                size="xs"
                color={saveState === 'error' ? 'red' : saveState === 'saving' ? 'yellow' : 'teal'}
                variant="light"
                radius="sm"
                style={{ flexShrink: 0 }}
              >
                {saveState === 'error' ? 'Failed' : saveState === 'saving' ? 'Saving...' : 'Saved'}
              </Badge>
            </>
          ) : (
            <Text size="xs" c="dimmed" style={{ flex: 1, textAlign: 'left' }}>
              {models.length === 0 ? 'Loading...' : (selected || 'Select model')}
            </Text>
          )}
          {saveState === 'saving' ? (
            <Loader size={10} style={{ flexShrink: 0 }} />
          ) : (
            <IconChevronDown
              size={12}
              style={{ flexShrink: 0, color: 'var(--mantine-color-dimmed)', opacity: 0.6 }}
            />
          )}
        </Box>
      </Combobox.Target>

      <Combobox.Dropdown
        w={520}
        style={{
          background: 'var(--mantine-color-dark-7)',
          border: '1px solid var(--mantine-color-dark-4)',
          borderRadius: 10,
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          minWidth: 520,
          padding: 0,
          overflow: 'hidden',
        }}
      >
        <Box p={8} style={{ borderBottom: '1px solid var(--mantine-color-dark-5)' }}>
          <Combobox.Search
            value={search}
            onChange={e => setSearch(e.currentTarget.value)}
            placeholder="Search models..."
            leftSection={<IconSearch size={13} />}
            styles={{
              input: {
                background: 'var(--mantine-color-dark-6)',
                border: '1px solid var(--mantine-color-dark-4)',
                borderRadius: 6,
                fontSize: 12,
                height: 30,
              },
            }}
          />
        </Box>

        <Box
          px={12}
          py={4}
          style={{ borderBottom: '1px solid var(--mantine-color-dark-6)', background: 'var(--mantine-color-dark-8)' }}
        >
          <Group gap={8} wrap="nowrap">
            <Text size="xs" c="dimmed">
              {filtered.length} model{filtered.length !== 1 ? 's' : ''}
            </Text>
            {grouped.map(([provider, items]) => (
              <Badge key={provider} size="xs" color={PROVIDER_COLOR[provider] ?? 'gray'} variant="light" radius="sm">
                {items.length} {provider}
              </Badge>
            ))}
          </Group>
        </Box>

        <Combobox.Options>
          <ScrollArea.Autosize mah={400} type="scroll" scrollbarSize={6}>
            {models.length === 0 ? (
              <Combobox.Empty>
                <Text size="xs" c="dimmed" ta="center" py="md">
                  Loading models...
                </Text>
              </Combobox.Empty>
            ) : filtered.length === 0 ? (
              <Combobox.Empty>
                <Text size="xs" c="dimmed" ta="center" py="md">
                  No models match &quot;{search}&quot;
                </Text>
              </Combobox.Empty>
            ) : (
              <Box pb={4}>{sections}</Box>
            )}
          </ScrollArea.Autosize>
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}
