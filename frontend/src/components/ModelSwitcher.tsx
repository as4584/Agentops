'use client';

/**
 * ModelSwitcher — Compact model selector per agent.
 * Fetches /models/registry, renders a Select with provider badge + cost.
 * On change calls PATCH /agents/{agentId}/model to persist the override.
 */

import { useEffect, useState } from 'react';
import { Badge, Combobox, Group, InputBase, Loader, Text, useCombobox } from '@mantine/core';
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
}

interface ModelSwitcherProps {
  agentId: string;
  value: string;
  onChange?: (modelId: string) => void;
}

const PROVIDER_COLOR: Record<string, string> = {
  ollama: 'green',
  openrouter: 'blue',
  openai: 'teal',
  anthropic: 'orange',
  copilot: 'gray',
};

function costLabel(m: RegistryModel): string {
  if (m.input_cost_per_m === 0) return 'free';
  return `$${m.input_cost_per_m.toFixed(2)}/M`;
}

// Shared registry cache so multiple switchers don't all fetch independently
let _modelsCache: RegistryModel[] | null = null;
let _modelsFetch: Promise<RegistryModel[]> | null = null;

async function getModels(): Promise<RegistryModel[]> {
  if (_modelsCache) return _modelsCache;
  if (_modelsFetch) return _modelsFetch;
  _modelsFetch = fetch(`${API_BASE}/models/registry`)
    .then(r => r.json())
    .then(d => {
      _modelsCache = d.models ?? [];
      return _modelsCache!;
    })
    .catch(() => { _modelsFetch = null; return []; });
  return _modelsFetch;
}

export default function ModelSwitcher({ agentId, value, onChange }: ModelSwitcherProps) {
  const [models, setModels] = useState<RegistryModel[]>([]);
  const [selected, setSelected] = useState(value);
  const [saving, setSaving] = useState(false);
  const combobox = useCombobox({ onDropdownClose: () => combobox.resetSelectedOption() });

  useEffect(() => { getModels().then(setModels); }, []);
  useEffect(() => { setSelected(value); }, [value]);

  const current = models.find(m => m.model_id === selected);

  const handleSelect = async (modelId: string) => {
    combobox.closeDropdown();
    if (modelId === selected) return;
    setSelected(modelId);
    setSaving(true);
    try {
      await fetch(`${API_BASE}/agents/${agentId}/model`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: modelId }),
      });
      onChange?.(modelId);
    } catch {
      setSelected(selected); // revert on error
    } finally {
      setSaving(false);
    }
  };

  const options = models.map(m => (
    <Combobox.Option value={m.model_id} key={m.model_id}>
      <Group justify="space-between" gap="xs" wrap="nowrap">
        <Text size="xs" ff="monospace" truncate style={{ maxWidth: 140 }}>{m.display_name}</Text>
        <Group gap={4} wrap="nowrap">
          <Badge size="xs" color={PROVIDER_COLOR[m.provider] ?? 'gray'} variant="light" style={{ flexShrink: 0 }}>
            {m.provider}
          </Badge>
          <Text size="xs" c="dimmed" ff="monospace" style={{ flexShrink: 0, minWidth: 36, textAlign: 'right' }}>
            {costLabel(m)}
          </Text>
        </Group>
      </Group>
    </Combobox.Option>
  ));

  return (
    <Combobox store={combobox} onOptionSubmit={handleSelect} withinPortal>
      <Combobox.Target>
        <InputBase
          component="button"
          type="button"
          pointer
          rightSection={saving ? <Loader size={10} /> : <Combobox.Chevron />}
          rightSectionPointerEvents="none"
          onClick={() => combobox.toggleDropdown()}
          size="xs"
          style={{ minWidth: 160, cursor: 'pointer' }}
          styles={{
            input: {
              background: 'var(--mantine-color-dark-7)',
              border: '1px solid var(--mantine-color-dark-4)',
              fontFamily: 'monospace',
              fontSize: 11,
              height: 26,
              paddingLeft: 8,
              paddingRight: 28,
            },
          }}
        >
          {current ? (
            <Group gap={6} wrap="nowrap">
              <Badge size="xs" color={PROVIDER_COLOR[current.provider] ?? 'gray'} variant="dot" style={{ flexShrink: 0 }}>
                {current.display_name}
              </Badge>
            </Group>
          ) : (
            <Text size="xs" c="dimmed">
              {models.length === 0 ? 'Loading…' : (selected || 'Select model')}
            </Text>
          )}
        </InputBase>
      </Combobox.Target>
      <Combobox.Dropdown style={{ background: 'var(--mantine-color-dark-7)', border: '1px solid var(--mantine-color-dark-4)' }}>
        <Combobox.Options>
          {models.length === 0
            ? <Combobox.Empty><Text size="xs" c="dimmed">Loading models…</Text></Combobox.Empty>
            : options
          }
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}
