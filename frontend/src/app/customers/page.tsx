'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Group,
  Modal,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconArrowLeft, IconPlus, IconCheck } from '@tabler/icons-react';
import { API_BASE } from '@/lib/api';

type ServiceStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

type CustomerService = {
  id: string;
  type: string;
  status: ServiceStatus;
  progress_percent: number;
  assigned_agents: string[];
};

type Customer = {
  id: string;
  name: string;
  email: string;
  business_name: string;
  tier: 'foundation' | 'growth' | 'domination';
  website_url: string | null;
  social_media_accounts: Record<string, string>;
  monthly_token_budget: number;
  tokens_used_this_month: number;
  services: CustomerService[];
};

const glassStyle = {
  background: 'rgba(255,255,255,0.05)',
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '16px',
};

const serviceOptions = [
  { value: 'website', label: 'Website' },
  { value: 'seo', label: 'SEO' },
  { value: 'ai_receptionist', label: 'AI Receptionist' },
  { value: 'social_media', label: 'Social Media' },
];

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [serviceModalOpen, setServiceModalOpen] = useState(false);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string>('');
  const [selectedService, setSelectedService] = useState<string | null>(null);

  const [newName, setNewName] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newBusinessName, setNewBusinessName] = useState('');
  const [newTier, setNewTier] = useState<string>('foundation');

  async function fetchCustomers() {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/customers/`);
      if (response.ok) {
        const data = await response.json();
        setCustomers(data);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchCustomers();
  }, []);

  const totals = useMemo(() => {
    const totalTokens = customers.reduce((acc, customer) => acc + customer.tokens_used_this_month, 0);
    const totalServices = customers.reduce((acc, customer) => acc + customer.services.length, 0);
    return {
      customers: customers.length,
      totalTokens,
      totalServices,
    };
  }, [customers]);

  async function handleCreateCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    try {
      const response = await fetch(`${API_BASE}/api/customers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newName,
          email: newEmail,
          business_name: newBusinessName,
          tier: newTier,
        }),
      });

      if (response.ok) {
        setNewName('');
        setNewEmail('');
        setNewBusinessName('');
        setNewTier('foundation');
        await fetchCustomers();
      }
    } finally {
      setCreating(false);
    }
  }

  function openServiceModal(customerId: string) {
    setSelectedCustomerId(customerId);
    setSelectedService('website');
    setServiceModalOpen(true);
  }

  async function confirmAddService() {
    if (!selectedCustomerId || !selectedService) {
      return;
    }

    const response = await fetch(`${API_BASE}/api/customers/${selectedCustomerId}/services`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service_type: selectedService, notes: 'Added from dashboard' }),
    });

    if (response.ok) {
      setServiceModalOpen(false);
      await fetchCustomers();
    }
  }

  return (
    <Stack p="xl" gap="lg">
      <Group justify="space-between">
        <Group gap="md">
          <ActionIcon variant="subtle" size="lg" component={Link} href="/">
            <IconArrowLeft size={20} />
          </ActionIcon>
          <Box>
            <Title order={2}>Customer Operations</Title>
            <Text c="dimmed">Manage customers, services, and token usage</Text>
          </Box>
        </Group>
      </Group>

      <Group grow>
        <Card style={glassStyle}>
          <Text c="dimmed" size="sm">Customers</Text>
          <Title order={3}>{totals.customers}</Title>
        </Card>
        <Card style={glassStyle}>
          <Text c="dimmed" size="sm">Active Services</Text>
          <Title order={3}>{totals.totalServices}</Title>
        </Card>
        <Card style={glassStyle}>
          <Text c="dimmed" size="sm">Tokens Used</Text>
          <Title order={3}>{totals.totalTokens.toLocaleString()}</Title>
        </Card>
      </Group>

      <Card style={glassStyle}>
        <form onSubmit={handleCreateCustomer}>
          <Stack>
            <Title order={4}>Add Customer</Title>
            <Group grow>
              <TextInput required label="Name" value={newName} onChange={(e) => setNewName(e.currentTarget.value)} />
              <TextInput required label="Email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.currentTarget.value)} />
            </Group>
            <Group grow>
              <TextInput
                required
                label="Business Name"
                value={newBusinessName}
                onChange={(e) => setNewBusinessName(e.currentTarget.value)}
              />
              <Select
                label="Tier"
                data={[
                  { value: 'foundation', label: 'Foundation' },
                  { value: 'growth', label: 'Growth' },
                  { value: 'domination', label: 'Domination' },
                ]}
                value={newTier}
                onChange={(value) => setNewTier(value || 'foundation')}
              />
            </Group>
            <Group justify="flex-end">
              <Button type="submit" loading={creating}>Create Customer</Button>
            </Group>
          </Stack>
        </form>
      </Card>

      <Card style={glassStyle}>
        <Title order={4} mb="md">Customers</Title>
        <Table striped highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Business</Table.Th>
              <Table.Th>Tier</Table.Th>
              <Table.Th>Website</Table.Th>
              <Table.Th>Tokens</Table.Th>
              <Table.Th>Services</Table.Th>
              <Table.Th>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {customers.map((customer) => {
              const usagePct = customer.monthly_token_budget > 0
                ? (customer.tokens_used_this_month / customer.monthly_token_budget) * 100
                : 0;

              return (
                <Table.Tr key={customer.id}>
                  <Table.Td>
                    <Text fw={600}>{customer.business_name}</Text>
                    <Text size="xs" c="dimmed">{customer.email}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light">{customer.tier}</Badge>
                  </Table.Td>
                  <Table.Td>
                    {customer.website_url ? (
                      <Text size="sm">{customer.website_url}</Text>
                    ) : (
                      <Text size="sm" c="dimmed">Not assigned</Text>
                    )}
                  </Table.Td>
                  <Table.Td style={{ minWidth: 180 }}>
                    <Progress value={usagePct} size="sm" />
                    <Text size="xs" c="dimmed" mt={4}>
                      {customer.tokens_used_this_month.toLocaleString()} / {customer.monthly_token_budget.toLocaleString()}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6}>
                      {customer.services.slice(0, 3).map((service) => (
                        <Badge key={service.id} size="xs" color={service.status === 'completed' ? 'green' : 'blue'}>
                          {service.type}
                        </Badge>
                      ))}
                      {customer.services.length === 0 && <Text size="xs" c="dimmed">None</Text>}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={8}>
                      <ActionIcon variant="light" onClick={() => openServiceModal(customer.id)}>
                        <IconPlus size={18} />
                      </ActionIcon>
                      <Button component={Link} href={`/customers/${customer.id}`} size="xs" variant="subtle">
                        Profile
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
        {loading && <Text mt="sm" c="dimmed">Loading customers...</Text>}
      </Card>

      <Modal opened={serviceModalOpen} onClose={() => setServiceModalOpen(false)} title="Assign Service" centered>
        <Stack>
          <Text size="sm" c="dimmed">Pick a service and confirm to assign subagents.</Text>
          <Select
            data={serviceOptions}
            value={selectedService}
            onChange={setSelectedService}
            label="Service"
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setServiceModalOpen(false)}>Cancel</Button>
            <Button leftSection={<IconCheck size={14} />} onClick={confirmAddService}>Confirm</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
